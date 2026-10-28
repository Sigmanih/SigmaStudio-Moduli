# ==============================================================================
# sigma_youtube_studio/tool_schemas.py — Gli schemi dei tool YouTube, per il modello
# ==============================================================================
"""Il catalogo che un agente legge. Arriva al kernel con `register_harness_tools()`."""
from core.harness.tool_schema import INTERO, STRINGA, function_schema as _f

_TAGS = {"type": "array", "items": STRINGA}
_PRIVACY = {"type": "string", "enum": ["private", "unlisted", "public"]}
_LOCALIZZAZIONI = {"type": "object", "description": "{lingua: {title, description}}, es. {\"it\": {...}}",
                   "additionalProperties": {"type": "object", "properties": {"title": STRINGA, "description": STRINGA}}}
_BOOL = {"type": "boolean"}

SCHEMI = [
    _f("youtube_status", "Il canale e' collegato? Nome, iscritti, video. Chiamalo per primo.", {}, []),
    _f("youtube_list_videos", "Gli ultimi video del canale con stato, visualizzazioni e lingue gia' tradotte.",
       {"limit": INTERO}, []),
    _f("youtube_publish_package",
       "Carica un video da un youtube_package.json (video, titoli e descrizioni per lingua, sottotitoli, "
       "miniatura). Il modo normale di pubblicare un restauro. Lavora in background.",
       {"package_path": STRINGA, "privacy": _PRIVACY}, ["package_path"]),
    _f("youtube_upload_video", "Carica un singolo file video con titolo e descrizione. Lavora in background.",
       {"video_path": STRINGA, "title": STRINGA, "description": STRINGA, "tags": _TAGS, "privacy": _PRIVACY,
        "default_language": STRINGA, "category_id": STRINGA, "contains_synthetic_media": _BOOL,
        "made_for_kids": _BOOL, "publish_at": {"type": "string", "description": "ISO 8601, es. 2026-11-01T18:00:00Z"}},
       ["video_path", "title"]),
    _f("youtube_upload_status", "Avanzamento dei caricamenti: percentuale, id del video, passi applicati.",
       {"upload_id": STRINGA}, []),
    _f("youtube_resume_upload", "Riprende un caricamento interrotto (riavvio, rete) da dove era arrivato.",
       {"upload_id": STRINGA}, ["upload_id"]),
    _f("youtube_update_video", "Cambia titolo, descrizione, tag, privacy o traduzioni di un video gia' caricato.",
       {"video_id": STRINGA, "title": STRINGA, "description": STRINGA, "tags": _TAGS, "privacy": _PRIVACY,
        "default_language": STRINGA, "localizations": _LOCALIZZAZIONI, "contains_synthetic_media": _BOOL},
       ["video_id"]),
    _f("youtube_upload_caption", "Carica un file .srt o .vtt come sottotitoli in una lingua (sostituisce i precedenti).",
       {"video_id": STRINGA, "language": STRINGA, "path": STRINGA, "name": STRINGA},
       ["video_id", "language", "path"]),
    _f("youtube_set_thumbnail", "Imposta la miniatura (jpg o png, max 2 MB, 1280x720 consigliato).",
       {"video_id": STRINGA, "image_path": STRINGA}, ["video_id", "image_path"]),
    _f("youtube_analytics", "Visualizzazioni, minuti guardati, permanenza media: del canale o di un video.",
       {"days": INTERO, "video_id": STRINGA}, []),
]
