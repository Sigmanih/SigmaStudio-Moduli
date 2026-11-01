"""Scene animate scritte in HTML/CSS/JS e rese in video: formule, grafici, schemi, elenchi.

Per spiegare fisica o matematica un modello video non serve e non basta: una
formula deve essere esatta, un grafico deve seguire la funzione. Qui la scena e'
una pagina web che espone `seek(t)` (disegna lo stato all'istante t) e il video
si ottiene fotogramma per fotogramma: si fissa il tempo, si scatta, si passa a
ffmpeg. Deterministico: la velocita' della macchina non cambia il risultato.

Il browser e' Chrome/Edge/Chromium gia' installato, pilotato col protocollo
DevTools (aiohttp, gia' usato dal resto del modulo): nessuna dipendenza nuova.

Contratto della pagina:
  window.sceneDuration = secondi          (facoltativo: altrimenti decide chi rende)
  window.seek = function (t) { ... }       disegna lo stato al tempo t, senza timer
Le animazioni CSS vengono comunque fermate e portate al tempo t dal renderer.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

from core.logger import get_logger

log = get_logger("creative_html_scene")

FPS = 24
SIZE = (1920, 1080)
# Contesto comune alle scene: KaTeX e uno stile di base sobrio e leggibile.
KATEX_DIR_NAMES = ("katex",)

BROWSER_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_browser() -> str | None:
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return next((p for p in BROWSER_CANDIDATES if Path(p).is_file()), None)


def katex_dir() -> Path | None:
    from core import paths
    d = paths.frontend_dir() / "node_modules" / "katex" / "dist"
    return d if (d / "katex.min.js").is_file() else None


BASE_CSS = """
html, body { margin: 0; width: 1920px; height: 1080px; overflow: hidden; }
body { background: #0f141c; color: #eef2f7; font-family: 'Segoe UI', 'DejaVu Sans', Arial, sans-serif; }
.katex { font-size: 1.15em; }
"""

# Prima del codice della scena: KaTeX locale e un aiuto `ease` per le animazioni.
HEAD = """<meta charset="utf-8"><style>{css}</style>
<link rel="stylesheet" href="katex/katex.min.css"><script src="katex/katex.min.js"></script>
<script>
window.clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
window.ease = (x) => { x = clamp(x); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
window.progress = (t, start, dur) => ease((t - start) / dur);
window.tex = (el, src, display = true) => katex.render(src, el, { displayMode: display, throwOnError: false });
</script>"""


def wrap(html_body: str) -> str:
    """Pagina completa: se l'autore ha scritto solo il corpo, lo si avvolge nel contorno standard."""
    if "<html" in html_body.lower():
        return html_body.replace("<head>", "<head>" + HEAD.replace("{css}", BASE_CSS), 1)
    return f"<!doctype html><html><head>{HEAD.replace("{css}", BASE_CSS)}</head><body>{html_body}</body></html>"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Cdp:
    """Il minimo del protocollo DevTools che serve: comandi con risposta ed eventi ignorati."""

    def __init__(self, ws):
        self.ws, self._id = ws, 0

    async def call(self, method: str, **params):
        self._id += 1
        msg_id = self._id
        await self.ws.send_str(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            raw = await self.ws.receive_json(timeout=60)
            if raw.get("id") == msg_id:
                if "error" in raw:
                    raise RuntimeError(f"{method}: {raw['error'].get('message')}")
                return raw.get("result", {})


async def _render(page: Path, out: Path, seconds: float, fps: int, size: tuple[int, int],
                  progress=None) -> dict:
    import aiohttp
    from core.modules.sigma_creative_lab.video.production import ffmpeg_bin
    browser = find_browser()
    if not browser:
        raise RuntimeError("nessun browser Chrome/Edge/Chromium trovato per rendere la scena")
    port = _free_port()
    profile = tempfile.mkdtemp(prefix="sigma_scene_profile_")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
    proc = subprocess.Popen([browser, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                             "--disable-gpu", "--hide-scrollbars", "--mute-audio", "--no-first-run",
                             "--allow-file-access-from-files", f"--window-size={size[0]},{size[1]}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    encoder = None
    errors: list[str] = []
    try:
        async with aiohttp.ClientSession() as session:
            ws_url = None
            for _ in range(100):
                try:
                    async with session.get(f"http://127.0.0.1:{port}/json/list") as r:
                        pages = [p for p in await r.json() if p.get("type") == "page"]
                        if pages:
                            ws_url = pages[0]["webSocketDebuggerUrl"]
                            break
                except aiohttp.ClientError:
                    pass
                await asyncio.sleep(0.1)
            if not ws_url:
                raise RuntimeError("il browser non risponde al protocollo DevTools")
            async with session.ws_connect(ws_url, max_msg_size=0) as ws:
                cdp = _Cdp(ws)
                await cdp.call("Emulation.setDeviceMetricsOverride", width=size[0], height=size[1],
                               deviceScaleFactor=1, mobile=False)
                await cdp.call("Page.enable")
                await cdp.call("Page.navigate", url=page.resolve().as_uri())
                # Attesa del caricamento (font di KaTeX compresi) senza dipendere dagli eventi.
                for _ in range(100):
                    r = await cdp.call("Runtime.evaluate", expression="document.readyState", returnByValue=True)
                    if r.get("result", {}).get("value") == "complete":
                        break
                    await asyncio.sleep(0.1)
                await cdp.call("Runtime.evaluate", expression="document.fonts.ready", awaitPromise=True)
                r = await cdp.call("Runtime.evaluate", returnByValue=True, expression=(
                    "({seek: typeof window.seek === 'function', duration: +window.sceneDuration || 0})"))
                info = r.get("result", {}).get("value") or {}
                if not info.get("seek"):
                    raise RuntimeError("la scena non definisce window.seek(t)")
                seconds = float(seconds or info.get("duration") or 6.0)
                n = max(1, int(round(seconds * fps)))
                encoder = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(fps),
                                            "-i", "-", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                                            "-map", "0:v", "-map", "1:a", "-frames:v", str(n), "-t", f"{n / fps:.3f}",
                                            "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p",
                                            "-c:a", "aac", "-b:a", "128k", str(out)],
                                           stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
                for k in range(n):
                    t = k / fps
                    r = await cdp.call("Runtime.evaluate", returnByValue=True, expression=(
                        "(() => { try {"
                        f" document.getAnimations().forEach(a => {{ a.pause(); a.currentTime = {t * 1000:.3f}; }});"
                        f" window.seek({t:.5f}); return ''; }} catch (e) {{ return String(e && e.stack || e); }} }})()"))
                    err = r.get("result", {}).get("value")
                    if err and len(errors) < 3:
                        errors.append(f"t={t:.2f}: {err[:300]}")
                    shot = await cdp.call("Page.captureScreenshot", format="jpeg", quality=92, captureBeyondViewport=False)
                    encoder.stdin.write(base64.b64decode(shot["data"]))
                    if progress and k % 12 == 0:
                        progress(k / n)
                encoder.stdin.close()
                encoder.wait(timeout=600)
                if encoder.returncode != 0:
                    raise RuntimeError(f"ffmpeg: {encoder.stderr.read().decode(errors='replace')[-300:]}")
    finally:
        if encoder and encoder.poll() is None:
            encoder.kill()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
    return {"clip_path": str(out), "frames": n, "seconds": n / fps, "errors": errors}


def render_scene(html: str, out: Path, seconds: float = 0.0, fps: int = FPS, size: tuple[int, int] = SIZE,
                 progress=None) -> dict:
    """Scrive la pagina accanto a una copia di KaTeX e la rende in `out` (MP4 con traccia audio muta)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sigma_scene_") as tmp:
        folder = Path(tmp)
        k = katex_dir()
        if k:
            shutil.copytree(k, folder / "katex", ignore=shutil.ignore_patterns("*.mjs", "contrib", "README.md"))
        page = folder / "scene.html"
        page.write_text(wrap(html), encoding="utf-8")
        # La pagina resta accanto al clip: per rifarla o modificarla serve il sorgente.
        out.with_suffix(".html").write_text(html, encoding="utf-8")
        return asyncio.run(_render(page, out, seconds, fps, size, progress))
