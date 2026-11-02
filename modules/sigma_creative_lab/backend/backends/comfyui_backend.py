"""Backend ComfyUI: traduce il contratto Sigma nelle sue API HTTP/websocket."""

import asyncio
import json
import math
import uuid

import aiohttp

from core.modules.sigma_creative_lab.backends.base import BackendJob, BackendUnavailable, GenerationBackend
from core.logger import get_logger

log = get_logger("comfyui_backend")

# Chiavi con cui i nodi di output dichiarano i file prodotti.
OUTPUT_KEYS = ("images", "gifs", "videos", "result", "meshes", "3d", "model_file", "audio")


class ComfyUIBackend(GenerationBackend):
    id = "comfyui"
    label = "ComfyUI"

    def __init__(self, base_url: str = "http://127.0.0.1:8188", config: dict = None):
        self.base_url = (base_url or "http://127.0.0.1:8188").rstrip("/")
        self.config = config or {}
        self.timeout_s = int(self.config.get("timeout", 600))
        self.client_id = str(uuid.uuid4())

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    async def _get(self, path: str, params: dict = None, raw: bool = False):
        timeout = aiohttp.ClientTimeout(total=60)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{self.base_url}{path}", params=params) as resp:
                    if resp.status != 200:
                        return None
                    return await (resp.read() if raw else resp.json())
        except aiohttp.ClientError as e:
            raise BackendUnavailable(f"ComfyUI non raggiungibile: {e}")

    async def _post(self, path: str, payload: dict) -> dict:
        timeout = aiohttp.ClientTimeout(total=60)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"{self.base_url}{path}", json=payload) as resp:
                    body = await resp.text()
                    if resp.status != 200:
                        raise RuntimeError(f"ComfyUI ha rifiutato la richiesta ({resp.status}): {body[:400]}")
                    return json.loads(body) if body else {}
        except aiohttp.ClientError as e:
            raise BackendUnavailable(f"ComfyUI non raggiungibile: {e}")

    # ------------------------------------------------------------------
    # Stato
    # ------------------------------------------------------------------

    async def is_available(self) -> bool:
        try:
            return await self._get("/system_stats") is not None
        except BackendUnavailable:
            return False

    async def get_system_stats(self) -> dict:
        stats = await self._get("/system_stats") or {}
        system = stats.get("system", {})
        devices = stats.get("devices", []) or []
        return {
            "backend": self.id,
            "version": system.get("comfyui_version", ""),
            "python": system.get("python_version", "").split(" ")[0],
            "torch": system.get("pytorch_version", ""),
            "ram_free_gb": round((system.get("ram_free") or 0) / 1024 ** 3, 1),
            "devices": [{
                "name": d.get("name", ""),
                "vram_total_gb": round((d.get("vram_total") or 0) / 1024 ** 3, 1),
                "vram_free_gb": round((d.get("vram_free") or 0) / 1024 ** 3, 1),
                "torch_vram_used_gb": round(
                    ((d.get("torch_vram_total") or 0) - (d.get("torch_vram_free") or 0)) / 1024 ** 3, 1),
            } for d in devices],
            "argv": system.get("argv", []),
        }

    @staticmethod
    def _options(node_info: dict, field: str) -> list:
        """Valori ammessi per un input: due schemi a seconda della versione."""
        for section in ("required", "optional"):
            spec = (node_info.get("input", {}).get(section) or {}).get(field)
            if not isinstance(spec, list) or not spec:
                continue
            if isinstance(spec[0], list):
                return [v for v in spec[0] if isinstance(v, str)]
            if spec[0] == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
                return [v for v in (spec[1].get("options") or []) if isinstance(v, str)]
        return []

    async def _object_info(self, class_type: str) -> dict:
        data = await self._get(f"/object_info/{class_type}")
        return (data or {}).get(class_type, {})

    async def discover_models(self) -> dict:
        classes = await asyncio.gather(*[
            self._object_info(c) for c in (
                "CheckpointLoaderSimple", "UNETLoader", "VAELoader", "DualCLIPLoader",
                "LoraLoader", "UpscaleModelLoader", "KSampler", "ControlNetLoader",
            )
        ], return_exceptions=True)
        classes = [c if isinstance(c, dict) else {} for c in classes]
        ckpt, unet, vae, clip, lora, upscaler, ksampler, controlnet = classes

        return {
            "checkpoints": self._options(ckpt, "ckpt_name"),
            "unets": self._options(unet, "unet_name"),
            "vaes": self._options(vae, "vae_name"),
            "clips": self._options(clip, "clip_name1"),
            "loras": self._options(lora, "lora_name"),
            "upscale_models": self._options(upscaler, "model_name"),
            "samplers": self._options(ksampler, "sampler_name"),
            "schedulers": self._options(ksampler, "scheduler"),
            "controlnets": self._options(controlnet, "control_net_name"),
        }

    async def validate_workflow(self, graph: dict, deferred_inputs: frozenset = frozenset(), expected_output: str = "") -> dict:
        """Controlla il contratto dei nodi senza accodare inferenze o caricare pesi."""
        if not isinstance(graph, dict) or not graph or len(graph) > 512:
            return {"ok": False, "problems": ["Workflow vuoto o troppo grande (massimo 512 nodi)"]}
        if any(not isinstance(node, dict) or not isinstance(node.get("class_type"), str) or
               not isinstance(node.get("inputs"), dict) for node in graph.values()):
            return {"ok": False, "problems": ["Usa un workflow esportato in formato API ComfyUI"]}
        names = sorted({node["class_type"] for node in graph.values()})
        semaphore = asyncio.Semaphore(6)
        async def describe(name):
            async with semaphore:
                return name, await self._object_info(name)
        definitions = dict(await asyncio.gather(*(describe(name) for name in names)))
        problems = []
        for node_id, node in graph.items():
            spec = definitions[node["class_type"]]
            if not spec:
                problems.append(f"Nodo non installato: {node['class_type']}")
                continue
            inputs = node["inputs"]
            required = (spec.get("input") or {}).get("required") or {}
            for field in required:
                if field not in inputs:
                    problems.append(f"{node['class_type']}: manca {field}")
            for field, value in inputs.items():
                if (str(node_id), field) in deferred_inputs:
                    continue
                field_spec = required.get(field) or ((spec.get("input") or {}).get("optional") or {}).get(field) or []
                # I collegamenti sono riferimenti a un nodo, non nomi di file.
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int) and not isinstance(value[1], bool):
                    if value[0] not in graph or value[1] < 0:
                        problems.append(f"{node_id}.{field}: collegamento non valido")
                    elif value[0] in graph:
                        outputs = definitions[graph[value[0]]["class_type"]].get("output")
                        if isinstance(outputs, list) and value[1] >= len(outputs):
                            problems.append(f"{node_id}.{field}: uscita del nodo inesistente")
                        elif isinstance(outputs, list) and field_spec:
                            known = {"MODEL", "CLIP", "VAE", "IMAGE", "LATENT", "CONDITIONING", "MASK", "AUDIO"}
                            wanted, provided = field_spec[0], outputs[value[1]]
                            if isinstance(wanted, str) and isinstance(provided, str) and wanted in known and provided in known and wanted != provided:
                                problems.append(f"{node_id}.{field}: tipo {provided} incompatibile con {wanted}")
                    continue
                options = self._options(spec, field)
                enumeration = bool(field_spec and (isinstance(field_spec[0], list) or field_spec[0] == "COMBO"))
                if enumeration and isinstance(value, str) and value not in options:
                    problems.append(f"{node['class_type']}.{field}: file o opzione non disponibile: {value}")
                elif isinstance(value, str) and "{{" in value:
                    problems.append(f"{node_id}.{field}: parametro non risolto")
                if field_spec and field_spec[0] in ("INT", "FLOAT"):
                    try:
                        number = float(value)
                        bounds = field_spec[1] if len(field_spec) > 1 and isinstance(field_spec[1], dict) else {}
                        if isinstance(value, bool) or not math.isfinite(number) or (field_spec[0] == "INT" and not number.is_integer()) or number < bounds.get("min", -math.inf) or number > bounds.get("max", math.inf):
                            raise ValueError("fuori intervallo")
                    except (ValueError, TypeError, OverflowError):
                        problems.append(f"{node_id}.{field}: numero non valido o fuori intervallo")
        if expected_output and not any(spec.get("output_node") and any(isinstance(value, list) and value and value[0] == expected_output
                for value in ((spec.get("input") or {}).get("required") or {}).values()) for spec in definitions.values()):
            problems.append(f"Il workflow non contiene un'uscita compatibile con {expected_output}")
        return {"ok": not problems, "problems": problems[:30], "checked_nodes": len(graph)}

    # ------------------------------------------------------------------
    # Esecuzione
    # ------------------------------------------------------------------

    async def get_queue(self) -> dict:
        data = await self._get("/queue") or {}
        running = data.get("queue_running", []) or []
        pending = data.get("queue_pending", []) or []
        return {
            "running": [q[1] for q in running if len(q) > 1],
            "pending": [q[1] for q in pending if len(q) > 1],
            "running_count": len(running),
            "pending_count": len(pending),
        }

    async def submit(self, payload: dict) -> str:
        workflow = payload.get("workflow", payload)
        data = await self._post("/prompt", {"prompt": workflow, "client_id": self.client_id})
        job_id = data.get("prompt_id")
        if not job_id:
            raise RuntimeError(f"ComfyUI non ha restituito un prompt_id: {data}")
        log.info(f"Job accodato su ComfyUI: {job_id}")
        return job_id

    async def get_job_status(self, job_id: str) -> BackendJob:
        history = (await self._get(f"/history/{job_id}") or {}).get(job_id, {})
        if history:
            status = (history.get("status") or {})
            if status.get("status_str") == "error":
                messages = status.get("messages") or []
                detail = next((json.dumps(m[1])[:300] for m in messages
                               if isinstance(m, list) and m and m[0] == "execution_error"), "")
                return BackendJob(job_id, "error", 100.0, error=detail or "Esecuzione fallita")
            if history.get("outputs"):
                return BackendJob(job_id, "done", 100.0, outputs=self._collect_outputs(history))

        queue = await self.get_queue()
        if any(q == job_id for q in queue["running"]):
            return BackendJob(job_id, "running", 50.0)
        if any(q == job_id for q in queue["pending"]):
            return BackendJob(job_id, "pending", 0.0)
        return BackendJob(job_id, "running" if not history else "done", 0.0 if not history else 100.0)

    async def cancel_job(self, job_id: str) -> bool:
        try:
            # Un job in coda si rimuove, uno in esecuzione si interrompe.
            await self._post("/queue", {"delete": [job_id]})
            queue = await self.get_queue()
            if job_id in queue["running"]:
                await self._post("/interrupt", {})
            return True
        except Exception as e:
            log.warning(f"Annullamento job {job_id} fallito: {e}")
            return False

    async def get_history(self, job_id: str) -> dict:
        return (await self._get(f"/history/{job_id}") or {}).get(job_id, {})

    @staticmethod
    def _collect_outputs(history: dict) -> list:
        outputs = []
        for node_id, node_output in (history.get("outputs") or {}).items():
            for key in OUTPUT_KEYS:
                for entry in (node_output.get(key) or []):
                    if isinstance(entry, dict) and entry.get("filename"):
                        outputs.append({
                            "filename": entry["filename"],
                            "subfolder": entry.get("subfolder", ""),
                            "kind": entry.get("type", "output"),
                            "node": node_id,
                        })
        return outputs

    async def get_outputs(self, job_id: str) -> list[tuple[bytes, str]]:
        history = await self.get_history(job_id)
        files = []
        for meta in self._collect_outputs(history):
            data = await self._get("/view", params={
                "filename": meta["filename"], "subfolder": meta["subfolder"], "type": meta["kind"],
            }, raw=True)
            if data:
                files.append((data, meta["filename"]))
        return files

    # ------------------------------------------------------------------

    async def upload_image(self, image_bytes: bytes, filename: str = None) -> str:
        """Carica un'immagine nella cartella input e ritorna il nome per LoadImage."""
        filename = filename or f"sigma_{uuid.uuid4().hex[:12]}.png"
        form = aiohttp.FormData()
        form.add_field("image", image_bytes, filename=filename, content_type="image/png")
        form.add_field("overwrite", "true")
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
                async with session.post(f"{self.base_url}/upload/image", data=form) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"Upload immagine fallito ({resp.status})")
                    data = await resp.json()
                    name = data.get("name", filename)
                    return f"{data['subfolder']}/{name}" if data.get("subfolder") else name
        except aiohttp.ClientError as e:
            raise BackendUnavailable(f"ComfyUI non raggiungibile: {e}")

    async def run(self, payload: dict, progress_cb=None, timeout_s: int = None) -> tuple[bytes, str]:
        """Esecuzione con attesa via websocket, polling come rete di sicurezza."""
        timeout_s = timeout_s or self.timeout_s
        job_id = await self.submit(payload)

        if not await self._wait_ws(job_id, progress_cb, timeout_s):
            await self._wait_poll(job_id, progress_cb, timeout_s)

        outputs = await self.get_outputs(job_id)
        if not outputs:
            raise RuntimeError("ComfyUI non ha prodotto alcun file")
        return outputs[0]

    async def _wait_ws(self, job_id: str, progress_cb, timeout_s: int) -> bool:
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_s)) as session:
                async with session.ws_connect(f"{ws_url}/ws?clientId={self.client_id}") as ws:
                    while loop.time() < deadline:
                        # Un messaggio perso o una connessione caduta senza errore
                        # lasciavano l'attesa appesa fino al timeout (2 ore per un
                        # clip): ogni 20 s di silenzio si controlla lo storico.
                        try:
                            msg = await ws.receive(timeout=20)
                        except asyncio.TimeoutError:
                            job = await self.get_job_status(job_id)
                            if job.status == "error":
                                raise RuntimeError(f"ComfyUI: {job.error}")
                            if job.status == "done":
                                return True
                            continue
                        if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                            return False
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        payload = json.loads(msg.data)
                        data = payload.get("data", {})
                        kind = payload.get("type")

                        if kind == "progress" and progress_cb:
                            total = data.get("max", 1) or 1
                            progress_cb({"job_id": job_id, "status": "running",
                                         "progress": round(data.get("value", 0) / total * 100, 1)})
                        elif ((kind == "executing" and data.get("node") is None) or kind == "execution_success") \
                                and data.get("prompt_id") == job_id:
                            return True
                        elif kind == "execution_error" and data.get("prompt_id") == job_id:
                            raise RuntimeError(f"ComfyUI: {data.get('exception_message', 'errore di esecuzione')}")
        except aiohttp.ClientError as e:
            log.debug(f"Websocket non disponibile ({e}): passo al polling")
            return False
        return False

    async def _wait_poll(self, job_id: str, progress_cb, timeout_s: int) -> None:
        waited, delay = 0.0, 1.0
        while waited < timeout_s:
            job = await self.get_job_status(job_id)
            if progress_cb:
                progress_cb(job.to_dict())
            if job.status == "error":
                raise RuntimeError(job.error)
            if job.status == "done":
                return
            await asyncio.sleep(delay)
            waited += delay
            delay = min(delay * 1.3, 5.0)
        raise TimeoutError(f"ComfyUI: timeout dopo {timeout_s}s")
