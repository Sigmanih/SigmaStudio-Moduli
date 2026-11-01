import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, HTTPException

from core.logger import get_logger
from core.mcp.governance import get_integration_config, set_integration_config

log = get_logger(__name__)
router = APIRouter()

CONFIG_PATH = Path("config/email_client.json")
DEMO_MODE_KEY = "demo_mode"


def _load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        log.warning("Config email non leggibile: %s", exc)
        return {}


def _save_config(cfg: Dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _get_email_server():
    from .email_server import EmailMCPServer
    return EmailMCPServer()


def _is_demo_mode() -> bool:
    cfg = _load_config()
    return bool(cfg.get(DEMO_MODE_KEY))


def _demo_inbox_messages() -> List[Dict[str, Any]]:
    return [
        {
            "id": "demo-1",
            "from": "Mario Rossi <mario.rossi@esempio.it>",
            "to": "tu@esempio.it",
            "subject": "Aggiornamento progetto Sigma Studio",
            "date": "Mon, 02 Jun 2025 14:30:00 +0200",
            "snippet": "Ciao, ti scrivo per aggiornarti sullo stato del modulo Email Hub...",
            "unread": True,
            "priority": "alta",
        },
        {
            "id": "demo-2",
            "from": "Laura Bianchi <laura.bianchi@esempio.it>",
            "to": "tu@esempio.it",
            "subject": "Riunione di domani",
            "date": "Mon, 02 Jun 2025 10:15:00 +0200",
            "snippet": "Ciao, ci vediamo domani alle 10:30 in sala riunioni...",
            "unread": False,
            "priority": "media",
        },
        {
            "id": "demo-3",
            "from": "Sigma Studio <no-reply@sigma.studio>",
            "to": "tu@esempio.it",
            "subject": "Benvenuto in Sigma Studio",
            "date": "Sun, 01 Jun 2025 09:00:00 +0200",
            "snippet": "Grazie per aver attivato il tuo account...",
            "unread": False,
            "priority": "bassa",
        },
    ]


def _demo_message_body(msg_id: str) -> Dict[str, Any]:
    if msg_id == "demo-1":
        return {
            "id": "demo-1",
            "from": "Mario Rossi <mario.rossi@esempio.it>",
            "to": "tu@esempio.it",
            "subject": "Aggiornamento progetto Sigma Studio",
            "date": "Mon, 02 Jun 2025 14:30:00 +0200",
            "body_html": "<p>Ciao,</p><p>ti scrivo per aggiornarti sullo stato del modulo Email Hub. Le rotte principali sono pronte e la UI sta prendendo forma.</p><p>Grazie,<br>Mario</p>",
            "attachments": [],
        }
    if msg_id == "demo-2":
        return {
            "id": "demo-2",
            "from": "Laura Bianchi <laura.bianchi@esempio.it>",
            "to": "tu@esempio.it",
            "subject": "Riunione di domani",
            "date": "Mon, 02 Jun 2025 10:15:00 +0200",
            "body_html": "<p>Ciao,</p><p>ci vediamo domani alle 10:30 in sala riunioni. Porta con te il portatile.</p><p>A presto,<br>Laura</p>",
            "attachments": [],
        }
    return {
        "id": msg_id,
        "from": "Sigma Studio <no-reply@sigma.studio>",
        "to": "tu@esempio.it",
        "subject": "Benvenuto in Sigma Studio",
        "date": "Sun, 01 Jun 2025 09:00:00 +0200",
        "body_html": "<p>Grazie per aver attivato il tuo account. Puoi iniziare a esplorare le funzionalità disponibili.</p>",
        "attachments": [],
    }


@router.get("/status")
async def get_status(request: Request):
    try:
        cfg = _load_config()
        demo = bool(cfg.get(DEMO_MODE_KEY))
        if demo:
            return {"status": "ok", "mode": "demo", "configured": True, "address": "demo@esempio.it"}

        server = _get_email_server()
        configured = server.is_configured()
        integration_cfg = get_integration_config("email") or {}
        address = integration_cfg.get("address", "")

        if not configured:
            return {"status": "ok", "mode": "unconfigured", "configured": False, "address": ""}

        # Prova di connettività IMAP se configurato
        imap_host = integration_cfg.get("imap_host", "") or cfg.get("imap_host", "")
        connectivity = "unknown"
        conn_error = None
        if imap_host:
            try:
                client = server._imap_connect()
                client.logout()
                connectivity = "ok"
            except Exception as exc:
                log.warning("Connettività IMAP fallita: %s", exc)
                connectivity = "error"
                msg = str(exc)
                if "AUTHENTICATIONFAILED" in msg:
                    conn_error = "Credenziali non valide su Gmail. Verifica di aver inserito tutte le 16 lettere della Password per le app (senza spazi mancanti o caratteri tagliati)."
                else:
                    conn_error = f"Errore connessione IMAP ({imap_host}): {msg}"

        return {
            "status": "ok",
            "mode": "live",
            "configured": True,
            "address": address,
            "imap_connectivity": connectivity,
            "error": conn_error,
        }
    except Exception as exc:
        log.error("Errore in /api/email/status: %s", exc)
        return {"status": "error", "mode": "unconfigured", "configured": False, "error": str(exc)}


@router.get("/inbox")
async def get_inbox(request: Request):
    try:
        limit = int(request.query_params.get("limit", 25))
        offset = int(request.query_params.get("offset", 0))
        folder = request.query_params.get("folder", "INBOX")
        unread_only = request.query_params.get("unread_only", "false").lower() == "true"

        if _is_demo_mode():
            messages = _demo_inbox_messages()
            if unread_only:
                messages = [m for m in messages if m["unread"]]
            total = len(messages)
            page = messages[offset:offset + limit]
            return {"status": "ok", "mode": "demo", "folder": folder, "total": total, "messages": page}

        server = _get_email_server()

        # Se il server non e' configurato e non siamo in modalita demo, ritorna lista vuota e stato chiaro
        if not server.is_configured():
            return {
                "status": "ok",
                "mode": "unconfigured",
                "configured": False,
                "folder": folder,
                "total": 0,
                "messages": [],
            }

        try:
            result = server._handle_read_inbox(folder=folder, unread_only=unread_only, limit=limit)
        except Exception as imap_err:
            log.warning("Connessione o lettura IMAP fallita: %s", imap_err)
            return {
                "status": "warning",
                "mode": "live",
                "configured": True,
                "error": str(imap_err),
                "folder": folder,
                "total": 0,
                "messages": [],
            }

        if not result.get("success"):
            return {
                "status": "warning",
                "mode": "live",
                "configured": True,
                "error": result.get("error", "Errore IMAP"),
                "folder": folder,
                "total": 0,
                "messages": [],
            }

        messages = result.get("messages", [])
        # Aggiunge campi extra per la UI
        for m in messages:
            m.setdefault("unread", True)
            m.setdefault("priority", "media")
            m["snippet"] = m.get("preview", "")[:200]

        return {
            "status": "ok",
            "mode": "live",
            "folder": folder,
            "total": result.get("total", len(messages)),
            "messages": messages[offset:offset + limit],
        }
    except Exception as exc:
        log.error("Errore in /api/email/inbox: %s", exc)
        return {
            "status": "error",
            "mode": "unconfigured" if not _is_demo_mode() else "demo",
            "error": str(exc),
            "folder": folder if "folder" in locals() else "INBOX",
            "total": 0,
            "messages": [],
        }


@router.get("/message/{msg_id}")
async def get_message(request: Request, msg_id: str):
    try:
        if _is_demo_mode():
            return {"status": "ok", "mode": "demo", "message": _demo_message_body(msg_id)}

        server = _get_email_server()
        client = server._imap_connect()
        try:
            client.select("INBOX", readonly=True)
            status, data = client.fetch(f'({msg_id})', "(RFC822)")
            if status != "OK" or not data or not isinstance(data[0], tuple):
                raise HTTPException(status_code=404, detail="Messaggio non trovato")

            import email as email_lib
            parsed = email_lib.message_from_bytes(data[0][1])
            body_html = ""
            attachments = []

            if parsed.is_multipart():
                for part in parsed.walk():
                    content_type = part.get_content_type()
                    disposition = str(part.get("Content-Disposition", ""))
                    if "attachment" in disposition:
                        filename = part.get_filename() or "allegato"
                        attachments.append({"name": filename, "size": len(part.get_payload(decode=True) or b"")})
                    elif content_type == "text/html":
                        payload = part.get_payload(decode=True) or b""
                        body_html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            else:
                payload = parsed.get_payload(decode=True) or b""
                if parsed.get_content_type() == "text/html":
                    body_html = payload.decode(parsed.get_content_charset() or "utf-8", errors="replace")
                else:
                    body_html = f"<pre>{payload.decode(parsed.get_content_charset() or 'utf-8', errors='replace')}</pre>"

            return {
                "status": "ok",
                "mode": "live",
                "message": {
                    "id": msg_id,
                    "from": server._decode(parsed.get("From", "")),
                    "to": server._decode(parsed.get("To", "")),
                    "subject": server._decode(parsed.get("Subject", "")),
                    "date": parsed.get("Date", ""),
                    "body_html": body_html,
                    "attachments": attachments,
                },
            }
        finally:
            try:
                client.logout()
            except Exception:
                pass
    except HTTPException:
        raise
    except Exception as exc:
        log.error("Errore in /api/email/message/%s: %s", msg_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/send")
async def send_email(request: Request):
    try:
        body = await request.json()
        to = body.get("to", "")
        cc = body.get("cc", "")
        subject = body.get("subject", "")
        email_body = body.get("body", "")
        html = bool(body.get("html", False))

        if not to or not subject or not email_body:
            raise HTTPException(status_code=400, detail="Mancano campi obbligatori: to, subject, body")

        if _is_demo_mode():
            log.info("Invio email in modalità demo a %s (oggetto: %s)", to, subject[:60])
            return {"status": "ok", "mode": "demo", "sent": True, "to": [a.strip() for a in to.split(",") if a.strip()]}

        server = _get_email_server()
        result = server._handle_send_email(to=to, cc=cc, subject=subject, body=email_body, html=html)
        if not result.get("success"):
            raise HTTPException(status_code=502, detail=result.get("error", "Invio fallito"))

        return {"status": "ok", "mode": "live", "sent": True, **result}
    except HTTPException:
        raise
    except Exception as exc:
        log.error("Errore in /api/email/send: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/ai-draft")
async def ai_draft(request: Request):
    try:
        body = await request.json()
        context = body.get("context", "")
        tone = body.get("tone", "professionale")
        action = body.get("action", "reply")  # reply | forward | draft

        if _is_demo_mode():
            if action == "reply":
                draft = (
                    "Grazie per il messaggio.\n\n"
                    "Ho preso visione dei punti sollevati e ti riscontro al più presto con un aggiornamento dettagliato.\n\n"
                    "Un cordiale saluto"
                )
            elif action == "forward":
                draft = (
                    "Inoltriamo questo messaggio per tua conoscenza.\n\n"
                    "Resto a disposizione per eventuali chiarimenti.\n\n"
                    "Cordiali saluti"
                )
            else:
                draft = (
                    "Oggetto: Proposta di collaborazione\n\n"
                    "Gentile,\n\n"
                    "mi permetto di contattarVi in merito a...\n\n"
                    "Resto in attesa di un Vostro cortese riscontro.\n\n"
                    "Cordiali saluti"
                )
            return {"status": "ok", "mode": "demo", "draft": draft, "action": action}

        # In modalità live usa l'engine/chat di Sigma Studio se disponibile
        try:
            from core.engine.chat import generate_text
            prompt = (
                f"Genera una bozza email {action} in tono {tone}.\n"
                f"Contesto: {context}\n"
                "Rispondi solo con il testo della bozza, senza preamboli."
            )
            draft = generate_text(prompt)
        except Exception as exc:
            log.warning("AI draft fallback: %s", exc)
            draft = (
                f"Bozza {action} generata in modo locale.\n\n"
                "Grazie per il messaggio, risponderò al più presto.\n\n"
                "Cordiali saluti"
            )

        return {"status": "ok", "mode": "live", "draft": draft, "action": action}
    except Exception as exc:
        log.error("Errore in /api/email/ai-draft: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/config")
async def get_config(request: Request):
    """Restituisce la configurazione attuale salvata per pre-popolare il form."""
    try:
        cfg = _load_config()
        # Per sicurezza passiamo i campi di connessione; la password viene restituita se presente
        return {
            "status": "ok",
            "config": {
                "address": cfg.get("address", ""),
                "password": cfg.get("password", ""),
                "smtp_host": cfg.get("smtp_host", ""),
                "smtp_port": cfg.get("smtp_port", 587),
                "imap_host": cfg.get("imap_host", ""),
                "imap_port": cfg.get("imap_port", 993),
                "demo_mode": bool(cfg.get(DEMO_MODE_KEY, False)),
            }
        }
    except Exception as exc:
        log.error("Errore in GET /api/email/config: %s", exc)
        return {"status": "error", "error": str(exc), "config": {}}


@router.post("/config")
async def update_config(request: Request):
    try:
        body = await request.json()
        cfg = _load_config()

        # Campi IMAP/SMTP
        for key in ("address", "password", "smtp_host", "smtp_port", "imap_host", "imap_port"):
            if key in body:
                cfg[key] = body[key]

        # Modalità demo
        if DEMO_MODE_KEY in body:
            cfg[DEMO_MODE_KEY] = bool(body[DEMO_MODE_KEY])

        _save_config(cfg)

        # Sincronizza anche con il governance config se presente
        try:
            integration_payload = {
                k: cfg[k]
                for k in ("address", "password", "smtp_host", "smtp_port", "imap_host", "imap_port")
                if k in cfg
            }
            if integration_payload:
                set_integration_config("email", integration_payload)
        except Exception as exc:
            log.warning("Sincronizzazione governance config fallita: %s", exc)

        log.info("Configurazione email aggiornata")
        return {"status": "ok", "saved": True, "demo_mode": bool(cfg.get(DEMO_MODE_KEY))}
    except Exception as exc:
        log.error("Errore in /api/email/config: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


def register_routes(app=None) -> None:
    """Registra le rotte /api/email/* sull'app FastAPI di Sigma Studio."""
    if app is None:
        raise RuntimeError("register_routes richiede l'istanza FastAPI.")
    app.include_router(router, prefix="/api/email", tags=["Email"])
    log.info("[sigma_email_client] 6 rotte /api/email/* registrate.")


def register_mcp(mcp_hub) -> None:
    """Registra il server MCP Email nell'hub MCP del kernel."""
    try:
        from .email_server import EmailMCPServer
        mcp_hub.register_server(EmailMCPServer())
        log.info("[sigma_email_client] EmailMCPServer registrato.")
    except Exception as exc:
        log.warning("[sigma_email_client] EmailMCPServer non registrato: %s", exc)
