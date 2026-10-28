# ==============================================================================
# sigma_youtube_studio/youtube_api.py — YouTube Data API v3 e Analytics, via REST
# ==============================================================================
"""Il canale YouTube dell'operatore visto da Sigma Studio.

Chiamate REST dirette con `requests` invece del client Google ufficiale: le
operazioni che servono sono una decina, e `google-api-python-client` porterebbe
dietro decine di pacchetti anche sul Raspberry Pi.

L'accesso e' OAuth 2.0 per app desktop con PKCE: l'utente crea il client sulla
Google Cloud Console, Sigma apre la pagina di consenso e riceve il codice sul
proprio indirizzo di loopback. Il refresh token vive in `config/`, accanto alle
altre credenziali, e non passa mai dal frontend.
"""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from core import paths
from core.logger import get_logger
from core.mcp.governance import get_integration_config, set_integration_config

log = get_logger(__name__)

MODULE_ID = "sigma_youtube_studio"
INTEGRATION_KEY = "youtube"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"
# force-ssl copre caricamento, modifica, sottotitoli e miniature; analytics in lettura
# si chiede subito per non dover rifare il consenso quando servira'.
SCOPES = ("https://www.googleapis.com/auth/youtube.force-ssl",
          "https://www.googleapis.com/auth/yt-analytics.readonly")
TIMEOUT = 30
# Multiplo di 256 KiB come chiede il protocollo; 32 MiB tiene basso il numero di
# richieste senza perdere troppo quando un blocco va ripetuto.
CHUNK = 32 * 1024 * 1024
CHUNK_RETRIES = 6

LANGUAGE_NAMES = {"en": "English", "it": "Italiano", "fr": "Français", "de": "Deutsch", "es": "Español",
                  "pt": "Português", "pt-BR": "Português (Brasil)", "ar": "العربية", "zh": "中文",
                  "zh-Hans": "中文（简体）", "zh-Hant": "中文（繁體）", "hi": "हिन्दी", "ja": "日本語",
                  "ru": "Русский", "nl": "Nederlands"}


class YouTubeError(RuntimeError):
    """Errore leggibile da mostrare all'utente o all'agente cosi' com'e'."""


# --- dove stanno le cose -------------------------------------------------------

def token_file() -> Path:
    return paths.config_dir() / "youtube_token.json"


def state_dir() -> Path:
    return paths.ensure(paths.module_state(MODULE_ID))


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("File %s illeggibile: %s", path, exc)
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# --- credenziali del client ----------------------------------------------------

def _client_file() -> Optional[Path]:
    """Il JSON scaricato dalla Cloud Console, lasciato in config/ col nome che Google gli da'."""
    found = sorted(paths.config_dir().glob("client_secret*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0] if found else None


def client_credentials() -> Dict[str, str]:
    cfg = get_integration_config(INTEGRATION_KEY)
    creds = {"client_id": (cfg.get("client_id") or "").strip(),
             "client_secret": (cfg.get("client_secret") or "").strip()}
    if creds["client_id"] and creds["client_secret"]:
        return creds
    f = _client_file()
    if f:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            block = data.get("installed") or data.get("web") or {}
            creds = {"client_id": block.get("client_id", ""), "client_secret": block.get("client_secret", "")}
        except Exception as exc:
            log.warning("Client OAuth in %s illeggibile: %s", f.name, exc)
    return creds


def save_client_credentials(client_id: str = "", client_secret: str = "", client_json: str = "") -> Dict[str, Any]:
    """Salva il client OAuth: a mano, oppure incollando il JSON scaricato dalla Cloud Console."""
    if client_json:
        try:
            data = json.loads(client_json)
        except ValueError as exc:
            raise YouTubeError(f"Il JSON del client non e' valido: {exc}") from exc
        block = data.get("installed") or data.get("web") or data
        client_id = block.get("client_id", "")
        client_secret = block.get("client_secret", "")
        if "web" in data:
            log.warning("Client OAuth di tipo 'web': per Sigma serve 'App desktop' (loopback senza URI registrati).")
    values = {}
    if client_id:
        values["client_id"] = client_id.strip()
    if client_secret:
        values["client_secret"] = client_secret.strip()
    if not values:
        raise YouTubeError("Servono client_id e client_secret (o il JSON del client).")
    set_integration_config(INTEGRATION_KEY, values)
    return {"configured": bool(client_credentials()["client_id"] and client_credentials()["client_secret"])}


# --- OAuth ---------------------------------------------------------------------

_pending: Dict[str, Dict[str, Any]] = {}
_pending_lock = threading.Lock()
PENDING_TTL_S = 900


def authorization_url(redirect_uri: str) -> Dict[str, str]:
    """L'indirizzo della pagina di consenso Google, con PKCE e uno state monouso."""
    creds = client_credentials()
    if not creds["client_id"]:
        raise YouTubeError("Prima inserisci il client OAuth (client_id e client_secret) creato sulla Google Cloud Console.")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    with _pending_lock:
        now = time.time()
        for k in [k for k, v in _pending.items() if now - v["at"] > PENDING_TTL_S]:
            _pending.pop(k, None)
        _pending[state] = {"verifier": verifier, "redirect_uri": redirect_uri, "at": now}
    query = {
        "client_id": creds["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
        "scope": " ".join(SCOPES), "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256",
        # offline + consent: senza, Google non rimanda il refresh token dopo il primo consenso.
        "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true",
    }
    return {"url": f"{AUTH_URL}?{urlencode(query)}", "state": state, "redirect_uri": redirect_uri}


def complete_authorization(code: str = "", state: str = "", pasted_url: str = "") -> Dict[str, Any]:
    """Scambia il codice col token. pasted_url serve quando il browser non raggiunge il loopback.

    Sul Raspberry usato da un altro computer la pagina di ritorno non si apre
    (127.0.0.1 e' il computer di chi guarda): l'utente copia l'indirizzo dalla
    barra e lo incolla nel pannello, che contiene comunque code e state.
    """
    if pasted_url:
        q = parse_qs(urlparse(pasted_url.strip()).query)
        if q.get("error"):
            raise YouTubeError(f"Google ha rifiutato l'accesso: {q['error'][0]}")
        code = (q.get("code") or [""])[0]
        state = (q.get("state") or [""])[0]
    with _pending_lock:
        pending = _pending.pop(state, None)
    if not code or not pending:
        raise YouTubeError("Richiesta di accesso scaduta o sconosciuta: riparti da 'Collega il canale'.")
    creds = client_credentials()
    try:
        r = requests.post(TOKEN_URL, data={
            "code": code, "client_id": creds["client_id"], "client_secret": creds["client_secret"],
            "redirect_uri": pending["redirect_uri"], "grant_type": "authorization_code",
            "code_verifier": pending["verifier"]}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise YouTubeError(f"Google irraggiungibile: {exc}") from exc
    data = r.json() if r.content else {}
    if r.status_code != 200:
        raise YouTubeError(f"Scambio del codice fallito: {data.get('error_description') or data.get('error') or r.text[:200]}")
    if not data.get("refresh_token"):
        raise YouTubeError("Google non ha restituito il refresh token: revoca l'accesso di Sigma dal tuo account Google e riprova.")
    token = {"refresh_token": data["refresh_token"], "access_token": data.get("access_token", ""),
             "expires_at": time.time() + int(data.get("expires_in", 3600)) - 60,
             "scope": data.get("scope", ""), "connected_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _write_json(token_file(), token)
    try:
        info = channel_info()
        token["channel"] = {"id": info.get("id"), "title": info.get("title")}
        _write_json(token_file(), token)
    except YouTubeError as exc:
        log.warning("Token ottenuto ma canale non letto: %s", exc)
    log.info("Canale YouTube collegato")
    return {"connected": True, "channel": token.get("channel")}


_token_lock = threading.Lock()


def access_token() -> str:
    """Un access token valido, rinnovato dal refresh token quando sta per scadere."""
    with _token_lock:
        token = _read_json(token_file(), {})
        if not token.get("refresh_token"):
            raise YouTubeError("Canale YouTube non collegato: apri la tab YouTube e premi 'Collega il canale'.")
        if token.get("access_token") and time.time() < float(token.get("expires_at", 0)):
            return token["access_token"]
        creds = client_credentials()
        try:
            r = requests.post(TOKEN_URL, data={
                "client_id": creds["client_id"], "client_secret": creds["client_secret"],
                "refresh_token": token["refresh_token"], "grant_type": "refresh_token"}, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise YouTubeError(f"Google irraggiungibile: {exc}") from exc
        data = r.json() if r.content else {}
        if r.status_code != 200:
            if data.get("error") == "invalid_grant":
                # Con la schermata di consenso in "Testing" Google fa scadere il refresh token dopo 7 giorni.
                raise YouTubeError("Accesso scaduto o revocato: ricollega il canale. Se succede ogni settimana, "
                                   "porta la schermata di consenso OAuth da 'Testing' a 'In produzione'.")
            raise YouTubeError(f"Rinnovo del token fallito: {data.get('error_description') or r.text[:200]}")
        token["access_token"] = data["access_token"]
        token["expires_at"] = time.time() + int(data.get("expires_in", 3600)) - 60
        _write_json(token_file(), token)
        return token["access_token"]


def disconnect() -> Dict[str, Any]:
    """Revoca il token presso Google e lo cancella da config/."""
    token = _read_json(token_file(), {})
    if token.get("refresh_token"):
        try:
            requests.post(REVOKE_URL, params={"token": token["refresh_token"]}, timeout=TIMEOUT)
        except requests.RequestException as exc:
            log.warning("Revoca del token non riuscita (lo cancello comunque): %s", exc)
    token_file().unlink(missing_ok=True)
    return {"connected": False}


def status() -> Dict[str, Any]:
    creds = client_credentials()
    token = _read_json(token_file(), {})
    f = _client_file()
    return {"client_configured": bool(creds["client_id"] and creds["client_secret"]),
            "client_source": "config" if get_integration_config(INTEGRATION_KEY).get("client_id") else (f.name if f else ""),
            "connected": bool(token.get("refresh_token")),
            "channel": token.get("channel"), "connected_at": token.get("connected_at"),
            "scopes": token.get("scope", "").split()}


# --- chiamate ------------------------------------------------------------------

def _explain(r: requests.Response) -> str:
    try:
        err = r.json().get("error", {})
        reason = (err.get("errors") or [{}])[0].get("reason", "")
        msg = err.get("message", "") or r.text[:200]
    except ValueError:
        return f"HTTP {r.status_code}: {r.text[:200]}"
    hints = {
        "quotaExceeded": "quota giornaliera della YouTube Data API esaurita: riprova domani",
        "uploadLimitExceeded": "limite di caricamenti del canale raggiunto",
        "forbidden": "permesso negato su questa risorsa",
        "insufficientPermissions": "permessi insufficienti: ricollega il canale",
        "accessNotConfigured": "API non abilitata nel progetto Google Cloud",
    }
    return f"{hints.get(reason, msg)} (HTTP {r.status_code}{', ' + reason if reason else ''})"


def _call(method: str, url: str, **kw) -> Dict[str, Any]:
    headers = kw.pop("headers", {})
    headers["Authorization"] = f"Bearer {access_token()}"
    try:
        r = requests.request(method, url, headers=headers, timeout=kw.pop("timeout", TIMEOUT), **kw)
    except requests.RequestException as exc:
        raise YouTubeError(f"YouTube irraggiungibile: {exc}") from exc
    if r.status_code >= 400:
        raise YouTubeError(_explain(r))
    return r.json() if r.content else {}


def channel_info() -> Dict[str, Any]:
    data = _call("GET", f"{API}/channels", params={"part": "snippet,statistics,contentDetails,status", "mine": "true"})
    items = data.get("items") or []
    if not items:
        raise YouTubeError("Nessun canale YouTube su questo account Google.")
    c = items[0]
    return {"id": c["id"], "title": c["snippet"]["title"],
            "thumbnail": c["snippet"].get("thumbnails", {}).get("default", {}).get("url", ""),
            "subscribers": c.get("statistics", {}).get("subscriberCount"),
            "views": c.get("statistics", {}).get("viewCount"),
            "videos": c.get("statistics", {}).get("videoCount"),
            "uploads_playlist": c.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", ""),
            "long_uploads": c.get("status", {}).get("longUploadsStatus", "")}


def list_videos(limit: int = 25) -> List[Dict[str, Any]]:
    """Gli ultimi video caricati, con stato, visualizzazioni e lingue gia' presenti."""
    playlist = channel_info()["uploads_playlist"]
    items = _call("GET", f"{API}/playlistItems", params={"part": "contentDetails", "playlistId": playlist,
                                                          "maxResults": max(1, min(50, int(limit)))}).get("items", [])
    ids = [i["contentDetails"]["videoId"] for i in items]
    if not ids:
        return []
    videos = _call("GET", f"{API}/videos", params={"part": "snippet,status,statistics,localizations,contentDetails",
                                                   "id": ",".join(ids)}).get("items", [])
    return [{"id": v["id"], "title": v["snippet"]["title"], "published_at": v["snippet"].get("publishedAt"),
             "privacy": v["status"].get("privacyStatus"), "upload_status": v["status"].get("uploadStatus"),
             "views": v.get("statistics", {}).get("viewCount"), "likes": v.get("statistics", {}).get("likeCount"),
             "duration": v.get("contentDetails", {}).get("duration"),
             "default_language": v["snippet"].get("defaultLanguage"),
             "localizations": sorted((v.get("localizations") or {}).keys()),
             "thumbnail": v["snippet"].get("thumbnails", {}).get("medium", {}).get("url", ""),
             "url": f"https://youtu.be/{v['id']}"} for v in videos]


def update_video(video_id: str, title: str = "", description: str = "", tags: Optional[List[str]] = None,
                 category_id: str = "", default_language: str = "", privacy: str = "",
                 localizations: Optional[Dict[str, Dict[str, str]]] = None,
                 contains_synthetic_media: Optional[bool] = None, made_for_kids: Optional[bool] = None) -> Dict[str, Any]:
    """Cambia solo i campi passati: YouTube vuole lo snippet intero, quindi si parte da quello attuale."""
    current = _call("GET", f"{API}/videos", params={"part": "snippet,status,localizations", "id": video_id}).get("items")
    if not current:
        raise YouTubeError(f"Video {video_id} non trovato sul canale.")
    v = current[0]
    snippet = {k: v["snippet"][k] for k in ("title", "description", "tags", "categoryId", "defaultLanguage",
                                            "defaultAudioLanguage") if k in v["snippet"]}
    if title:
        snippet["title"] = title[:100]
    if description:
        snippet["description"] = description[:5000]
    if tags is not None:
        snippet["tags"] = tags
    if category_id:
        snippet["categoryId"] = str(category_id)
    if default_language:
        snippet["defaultLanguage"] = default_language
    parts = ["snippet"]
    body: Dict[str, Any] = {"id": video_id, "snippet": snippet}
    if privacy or contains_synthetic_media is not None or made_for_kids is not None:
        st = {k: v["status"][k] for k in ("privacyStatus", "embeddable", "license", "publicStatsViewable",
                                          "selfDeclaredMadeForKids", "containsSyntheticMedia") if k in v["status"]}
        if privacy:
            st["privacyStatus"] = privacy
        if contains_synthetic_media is not None:
            st["containsSyntheticMedia"] = bool(contains_synthetic_media)
        if made_for_kids is not None:
            st["selfDeclaredMadeForKids"] = bool(made_for_kids)
        body["status"] = st
        parts.append("status")
    if localizations:
        if not snippet.get("defaultLanguage"):
            raise YouTubeError("Per aggiungere le traduzioni il video deve avere una lingua predefinita (default_language).")
        merged = dict(v.get("localizations") or {})
        for lang, loc in localizations.items():
            merged[lang] = {"title": (loc.get("title") or "")[:100], "description": (loc.get("description") or "")[:5000]}
        body["localizations"] = merged
        parts.append("localizations")
    out = _call("PUT", f"{API}/videos", params={"part": ",".join(parts)}, json=body)
    return {"id": out.get("id"), "title": out.get("snippet", {}).get("title"),
            "privacy": out.get("status", {}).get("privacyStatus"),
            "localizations": sorted((out.get("localizations") or {}).keys())}


def set_thumbnail(video_id: str, image_path: str) -> Dict[str, Any]:
    p = Path(image_path)
    if not p.is_file():
        raise YouTubeError(f"Miniatura non trovata: {p}")
    if p.stat().st_size > 2 * 1024 * 1024:
        raise YouTubeError("La miniatura supera i 2 MB consentiti da YouTube.")
    mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
    out = _call("POST", f"{UPLOAD_API}/thumbnails/set", params={"videoId": video_id},
                headers={"Content-Type": mime}, data=p.read_bytes(), timeout=120)
    return {"video_id": video_id, "thumbnail": (out.get("items") or [{}])[0].get("default", {}).get("url", "")}


def list_captions(video_id: str) -> List[Dict[str, Any]]:
    items = _call("GET", f"{API}/captions", params={"part": "snippet", "videoId": video_id}).get("items", [])
    return [{"id": c["id"], "language": c["snippet"]["language"], "name": c["snippet"].get("name", ""),
             "kind": c["snippet"].get("trackKind", "")} for c in items]


def upload_caption(video_id: str, language: str, path: str, name: str = "", replace: bool = True) -> Dict[str, Any]:
    """Carica un .srt/.vtt; con replace sostituisce la traccia della stessa lingua invece di affiancarla.

    La traccia da sostituire si riconosce dalla lingua e non dal nome: correggendo il nome
    (prima "pt-BR", poi "Português (Brasil)") restavano due tracce portoghesi affiancate.
    I sottotitoli automatici (asr) non si toccano.
    """
    p = Path(path)
    if not p.is_file():
        raise YouTubeError(f"Sottotitoli non trovati: {p}")
    name = name or LANGUAGE_NAMES.get(language, language)
    if replace:
        for c in list_captions(video_id):
            if c["language"] == language and c["kind"] != "asr":
                _call("DELETE", f"{API}/captions", params={"id": c["id"]})
    boundary = f"sigma{uuid.uuid4().hex}"
    meta = json.dumps({"snippet": {"videoId": video_id, "language": language, "name": name, "isDraft": False}})
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
            f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + p.read_bytes() + \
        f"\r\n--{boundary}--\r\n".encode()
    out = _call("POST", f"{UPLOAD_API}/captions", params={"part": "snippet", "uploadType": "multipart"},
                headers={"Content-Type": f"multipart/related; boundary={boundary}"}, data=body, timeout=120)
    return {"id": out.get("id"), "language": language, "name": name}


def analytics(days: int = 28, video_id: str = "") -> Dict[str, Any]:
    """Visualizzazioni, minuti guardati e durata media; per video o per tutto il canale."""
    end = time.strftime("%Y-%m-%d")
    start = time.strftime("%Y-%m-%d", time.localtime(time.time() - max(1, int(days)) * 86400))
    params = {"ids": "channel==MINE", "startDate": start, "endDate": end,
              "metrics": "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained"}
    if video_id:
        params["filters"] = f"video=={video_id}"
    total = _call("GET", ANALYTICS_API, params=params)
    row = (total.get("rows") or [[0, 0, 0, 0, 0]])[0]
    report = dict(zip(["views", "minutes_watched", "avg_view_seconds", "avg_view_percent", "subscribers_gained"], row))
    if not video_id:
        top = _call("GET", ANALYTICS_API, params={**params, "metrics": "views,estimatedMinutesWatched,averageViewPercentage",
                                                  "dimensions": "video", "sort": "-views", "maxResults": 10})
        report["top_videos"] = [dict(zip(["video_id", "views", "minutes_watched", "avg_view_percent"], r))
                                for r in top.get("rows") or []]
    else:
        lang = _call("GET", ANALYTICS_API, params={**params, "metrics": "views", "dimensions": "country",
                                                   "sort": "-views", "maxResults": 10})
        report["countries"] = [dict(zip(["country", "views"], r)) for r in lang.get("rows") or []]
    report.update({"start": start, "end": end, "video_id": video_id or None})
    return report


# --- caricamento ripristinabile --------------------------------------------------

def _uploads_file() -> Path:
    return state_dir() / "uploads.json"


_uploads_lock = threading.Lock()
_workers: Dict[str, threading.Thread] = {}


def _load_uploads() -> Dict[str, Dict[str, Any]]:
    return _read_json(_uploads_file(), {})


def _save_upload(job: Dict[str, Any]) -> None:
    with _uploads_lock:
        jobs = _load_uploads()
        jobs[job["id"]] = job
        _write_json(_uploads_file(), jobs)


def list_uploads() -> List[Dict[str, Any]]:
    jobs = _load_uploads()
    for j in jobs.values():
        # Un caricamento "in corso" senza thread vivo e' stato interrotto da un riavvio: si puo' riprendere.
        if j.get("status") == "uploading" and not (_workers.get(j["id"]) and _workers[j["id"]].is_alive()):
            j["status"] = "interrupted"
    return sorted(jobs.values(), key=lambda j: j.get("created", ""), reverse=True)


def get_upload(job_id: str) -> Dict[str, Any]:
    for j in list_uploads():
        if j["id"] == job_id:
            return j
    raise YouTubeError(f"Caricamento {job_id} sconosciuto.")


def start_upload(video_path: str, title: str, description: str = "", tags: Optional[List[str]] = None,
                 category_id: str = "1", privacy: str = "private", default_language: str = "",
                 default_audio_language: str = "", made_for_kids: bool = False,
                 contains_synthetic_media: bool = False, publish_at: str = "",
                 after: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Avvia il caricamento in un thread e restituisce subito il lavoro da seguire.

    `after` raccoglie cio' che si applica a video caricato: traduzioni di titolo
    e descrizione, sottotitoli, miniatura. Restano nel lavoro salvato, cosi' un
    caricamento ripreso dopo un riavvio li applica lo stesso.
    """
    p = Path(video_path)
    if not p.is_file():
        raise YouTubeError(f"Video non trovato: {p}")
    if privacy not in ("private", "unlisted", "public"):
        raise YouTubeError("privacy deve essere private, unlisted o public.")
    snippet = {"title": title[:100], "description": description[:5000], "categoryId": str(category_id or "1")}
    if tags:
        snippet["tags"] = tags
    if default_language:
        snippet["defaultLanguage"] = default_language
    if default_audio_language or default_language:
        snippet["defaultAudioLanguage"] = default_audio_language or default_language
    st: Dict[str, Any] = {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(made_for_kids),
                          "containsSyntheticMedia": bool(contains_synthetic_media)}
    if publish_at:
        # La pubblicazione programmata vuole il video privato fino all'ora indicata.
        st["privacyStatus"] = "private"
        st["publishAt"] = publish_at
    job = {"id": uuid.uuid4().hex[:12], "file": str(p), "size": p.stat().st_size, "sent": 0,
           "status": "uploading", "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "session_uri": "",
           "metadata": {"snippet": snippet, "status": st}, "after": after or {}, "video_id": "",
           "steps": [], "error": ""}
    _save_upload(job)
    _spawn(job["id"])
    return job


def resume_upload(job_id: str) -> Dict[str, Any]:
    job = get_upload(job_id)
    if job["status"] not in ("interrupted", "error"):
        raise YouTubeError(f"Il caricamento e' {job['status']}: non c'e' niente da riprendere.")
    job["status"], job["error"] = "uploading", ""
    _save_upload(job)
    _spawn(job_id)
    return job


def _spawn(job_id: str) -> None:
    t = threading.Thread(target=_run_upload, args=(job_id,), name=f"yt-upload-{job_id}", daemon=True)
    _workers[job_id] = t
    t.start()


def _open_session(job: Dict[str, Any]) -> str:
    r = requests.post(f"{UPLOAD_API}/videos", params={"uploadType": "resumable", "part": "snippet,status"},
                      headers={"Authorization": f"Bearer {access_token()}",
                               "Content-Type": "application/json; charset=UTF-8",
                               "X-Upload-Content-Length": str(job["size"]),
                               "X-Upload-Content-Type": mimetypes.guess_type(job["file"])[0] or "video/*"},
                      json=job["metadata"], timeout=TIMEOUT)
    if r.status_code >= 400:
        raise YouTubeError(_explain(r))
    return r.headers["Location"]


def _server_offset(job: Dict[str, Any]) -> Optional[int]:
    """Quanti byte ha gia' YouTube; None se la sessione e' finita (video gia' creato)."""
    r = requests.put(job["session_uri"], headers={"Authorization": f"Bearer {access_token()}",
                                                  "Content-Range": f"bytes */{job['size']}"}, timeout=TIMEOUT)
    if r.status_code in (200, 201):
        job["video_id"] = r.json().get("id", "")
        return None
    if r.status_code == 308:
        rng = r.headers.get("Range", "")
        return int(rng.split("-")[-1]) + 1 if rng else 0
    if r.status_code == 404:
        # Sessione scaduta (dura circa una settimana): se ne apre una nuova da zero.
        job["session_uri"] = ""
        return 0
    raise YouTubeError(_explain(r))


def _run_upload(job_id: str) -> None:
    job = _load_uploads()[job_id]
    try:
        if not job.get("session_uri"):
            job["session_uri"] = _open_session(job)
            job["sent"] = 0
        else:
            offset = _server_offset(job)
            if offset is not None and not job["session_uri"]:
                job["session_uri"] = _open_session(job)
            job["sent"] = job["size"] if offset is None else offset
        _save_upload(job)
        failures = 0
        with open(job["file"], "rb") as fh:
            while not job.get("video_id") and job["sent"] < job["size"]:
                start = job["sent"]
                fh.seek(start)
                data = fh.read(CHUNK)
                end = start + len(data) - 1
                try:
                    r = requests.put(job["session_uri"], data=data, timeout=600,
                                     headers={"Authorization": f"Bearer {access_token()}",
                                              "Content-Length": str(len(data)),
                                              "Content-Range": f"bytes {start}-{end}/{job['size']}"})
                except requests.RequestException as exc:
                    r, err = None, str(exc)
                if r is not None and r.status_code in (200, 201):
                    job["video_id"] = r.json().get("id", "")
                    job["sent"] = job["size"]
                elif r is not None and r.status_code == 308:
                    rng = r.headers.get("Range", "")
                    job["sent"] = int(rng.split("-")[-1]) + 1 if rng else 0
                    failures = 0
                elif r is not None and r.status_code < 500 and r.status_code not in (408, 429):
                    raise YouTubeError(_explain(r))
                else:
                    failures += 1
                    if failures > CHUNK_RETRIES:
                        raise YouTubeError(f"Troppi errori di rete consecutivi: {err if r is None else _explain(r)}")
                    time.sleep(min(60, 2 ** failures))
                    offset = _server_offset(job)
                    job["sent"] = job["size"] if offset is None else offset
                _save_upload(job)
        if not job.get("video_id"):
            raise YouTubeError("Caricamento terminato senza id del video.")
        job["status"] = "processing"
        _save_upload(job)
        _apply_after(job)
        job["status"] = "done"
        log.info("Video caricato su YouTube: %s", job["video_id"])
    except Exception as exc:
        job["status"], job["error"] = "error", str(exc)
        log.error("Caricamento YouTube %s fallito: %s", job_id, exc)
    finally:
        _save_upload(job)


def _apply_after(job: Dict[str, Any]) -> None:
    """Traduzioni, sottotitoli e miniatura dopo il caricamento; ogni passo si registra e non blocca gli altri."""
    after, vid = job.get("after") or {}, job["video_id"]
    done = {s["step"] for s in job.get("steps", []) if s.get("ok")}

    def step(name: str, fn: Callable[[], Any]) -> None:
        if name in done:
            return
        try:
            out = fn()
            job["steps"].append({"step": name, "ok": True, "result": out})
        except Exception as exc:
            job["steps"].append({"step": name, "ok": False, "error": str(exc)})
            log.warning("YouTube %s: passo '%s' fallito: %s", vid, name, exc)
        _save_upload(job)

    if after.get("localizations"):
        step("localizations", lambda: update_video(vid, localizations=after["localizations"]))
    for lang, path in (after.get("captions") or {}).items():
        step(f"caption_{lang}", lambda lang=lang, path=path: upload_caption(vid, lang, path))
    if after.get("thumbnail"):
        step("thumbnail", lambda: set_thumbnail(vid, after["thumbnail"]))


# --- pacchetto di pubblicazione ------------------------------------------------

def load_package(package_path: str) -> Dict[str, Any]:
    """Legge un youtube_package.json; i percorsi relativi valgono rispetto alla cartella del pacchetto."""
    p = Path(package_path)
    if p.is_dir():
        p = p / "youtube_package.json"
    if not p.is_file():
        raise YouTubeError(f"Pacchetto non trovato: {p}")
    try:
        pkg = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise YouTubeError(f"Pacchetto illeggibile: {exc}") from exc
    base = p.parent

    def resolve(x: str) -> str:
        q = Path(x)
        return str(q if q.is_absolute() else (base / q).resolve())

    default = pkg.get("default_language", "en")
    locs = pkg.get("localizations") or {}
    if default not in locs:
        raise YouTubeError(f"Il pacchetto non ha titolo e descrizione per la lingua predefinita '{default}'.")
    pkg["video"] = resolve(pkg["video"])
    if pkg.get("thumbnail"):
        pkg["thumbnail"] = resolve(pkg["thumbnail"])
    pkg["captions"] = {lang: resolve(path) for lang, path in (pkg.get("captions") or {}).items()}
    pkg["default_language"] = default
    missing = [x for x in [pkg["video"], pkg.get("thumbnail") or ""] + list(pkg["captions"].values())
               if x and not Path(x).is_file()]
    if missing:
        raise YouTubeError(f"File del pacchetto mancanti: {', '.join(missing)}")
    return pkg


def publish_package(package_path: str, privacy: str = "") -> Dict[str, Any]:
    pkg = load_package(package_path)
    default = pkg["default_language"]
    locs = pkg["localizations"]
    return start_upload(
        pkg["video"], title=locs[default]["title"], description=locs[default]["description"],
        tags=pkg.get("tags"), category_id=str(pkg.get("category_id", "1")),
        privacy=privacy or pkg.get("privacy", "private"), default_language=default,
        default_audio_language=pkg.get("default_audio_language", default),
        made_for_kids=bool(pkg.get("made_for_kids", False)),
        contains_synthetic_media=bool(pkg.get("contains_synthetic_media", False)),
        publish_at=pkg.get("publish_at", ""),
        after={"localizations": {k: v for k, v in locs.items() if k != default},
               "captions": pkg["captions"], "thumbnail": pkg.get("thumbnail", "")})
