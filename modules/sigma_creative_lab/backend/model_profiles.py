"""Profili di esecuzione per pesi locali, indipendenti dalla provenienza del download."""

from __future__ import annotations

import hashlib
import json
import asyncio

from core.modules.sigma_creative_lab.workflow_registry import WorkflowManifest


async def profile_components(workflow: WorkflowManifest, backend) -> dict:
    from core.modules.sigma_creative_lab.workflow_registry import PLACEHOLDER
    if not workflow.workflow or len(workflow.workflow) > 512:
        raise ValueError("Workflow vuoto o troppo grande")
    semaphore = asyncio.Semaphore(6)
    async def describe(name):
        async with semaphore:
            return name, await backend._object_info(name)
    names = {node.get("class_type") for node in workflow.workflow.values() if isinstance(node, dict)}
    if None in names or len(names) > 128:
        raise ValueError("Il workflow non contiene nodi API validi")
    definitions = dict(await asyncio.gather(*(describe(name) for name in names)))
    fields = {}
    for node in workflow.workflow.values():
        definition = definitions[node["class_type"]]
        for key, value in (node.get("inputs") or {}).items():
            match = PLACEHOLDER.fullmatch(value.strip()) if isinstance(value, str) else None
            if not match:
                continue
            name = match.group(1)
            options = backend._options(definition, key)
            field = fields.setdefault(name, {"key": name, "options": None, "default": workflow.defaults.get(name), "nodes": []})
            field["nodes"].append(node["class_type"])
            if options:
                field["options"] = options if field["options"] is None else [option for option in field["options"] if option in options]
    return {"fields": list(fields.values()), "missing_nodes": [name for name, definition in definitions.items() if not definition]}


def prepare_profile(data: dict, registry) -> WorkflowManifest:
    if not isinstance(data, dict):
        raise ValueError("Il profilo deve essere un oggetto")
    template = registry.get(str(data.get("workflow_id") or ""))
    if not template or template.backend != "comfyui":
        raise ValueError("Scegli un workflow ComfyUI disponibile")
    label = str(data.get("label") or "").strip()
    if not label or len(label) > 120:
        raise ValueError("Assegna un nome al profilo (massimo 120 caratteri)")
    params = data.get("parameters") or {}
    if not isinstance(params, dict) or len(json.dumps(params, allow_nan=False)) > 65536:
        raise ValueError("I componenti del profilo devono essere un oggetto JSON di dimensioni limitate")
    unknown = set(params) - template.placeholders - set(template.defaults)
    if unknown:
        raise ValueError("Il workflow non espone questi parametri: " + ", ".join(sorted(unknown)))
    defaults = {**template.defaults, **params}
    checkpoint = data.get("checkpoint")
    if checkpoint:
        if not isinstance(checkpoint, str) or len(checkpoint) > 512:
            raise ValueError("Nome del file modello non valido")
        if "ckpt" not in template.placeholders:
            raise ValueError("Il workflow scelto non espone il parametro ckpt: associa il file al suo parametro nei componenti")
        defaults["ckpt"] = checkpoint
    identity = hashlib.sha256(json.dumps([label, template.id, defaults], sort_keys=True).encode()).hexdigest()[:16]
    return WorkflowManifest(id=f"profile_{identity}", name=label, capability=template.capability,
                            defaults=defaults, inputs=dict(template.inputs), workflow=template.workflow,
                            requirements=dict(template.requirements),
                            description=f"Profilo locale basato su {template.name}")


async def validate_profile(profile: WorkflowManifest, backend) -> dict:
    from core.modules.sigma_creative_lab.workflow_registry import finalize_params, substitute
    values = finalize_params(profile.defaults, {"prompt": "Verifica di compatibilita' del profilo"})
    runtime = {"input_image", "mask_image"}
    missing = sorted(key for key in profile.placeholders - runtime if values.get(key) in (None, ""))
    if missing:
        return {"ok": False, "problems": [f"Componente o parametro mancante: {key}" for key in missing]}
    graph = substitute(profile.workflow, values)
    deferred = frozenset((str(node_id), key) for node_id, node in profile.workflow.items()
                         for key, value in node.get("inputs", {}).items()
                         if isinstance(value, str) and value.strip() in {"{{input_image}}", "{{mask_image}}"})
    expected = "IMAGE" if profile.capability in {"text_to_image", "img_to_img", "inpaint", "outpaint", "instruct_edit", "upscale"} else ""
    result = await backend.validate_workflow(graph, deferred_inputs=deferred, expected_output=expected)
    result["runtime_inputs"] = sorted(profile.placeholders & runtime)
    return result
