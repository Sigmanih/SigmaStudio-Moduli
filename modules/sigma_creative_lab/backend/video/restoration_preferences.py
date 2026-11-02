"""Preferenze riutilizzabili del restauro, separate dai dati del singolo film."""
from core import paths
from core.store import JsonStore

LANGUAGES = ('en', 'fr', 'de', 'es', 'pt', 'it', 'zh', 'ar')
DEFAULTS = {'languages': list(LANGUAGES), 'default_language': 'en', 'source_language': 'auto',
            'content_type': 'silent', 'output_height': 1440, 'make_music': True,
            'preserve_source_audio': False, 'make_publication': True, 'include_sigla': True,
            'sigla_assets_dir': '', 'sigla_cta_language': 'en', 'output_dir': '',
            'output_subfolder': True, 'music_style': ''}
PREFERENCE_KEYS = frozenset(DEFAULTS)


def store():
    return JsonStore(paths.var_dir() / 'creative' / 'restoration_defaults.json', default={})


def load_defaults():
    saved = store().load()
    merged = {**DEFAULTS, **{k: v for k, v in saved.items() if k in PREFERENCE_KEYS}} if isinstance(saved, dict) else dict(DEFAULTS)
    try:
        normalized = options(merged, defaults=DEFAULTS)
        return {k: normalized[k] for k in PREFERENCE_KEYS}
    except ValueError:
        from core.logger import get_logger
        get_logger('restoration_preferences').warning('Preset del restauro non valido: usa i valori predefiniti')
        return dict(DEFAULTS)


def options(data, defaults=None):
    if not isinstance(data, dict):
        raise ValueError('Le opzioni del restauro devono essere un oggetto')
    result = {**(defaults if defaults is not None else load_defaults()), **data}
    languages = result.get('languages')
    if not isinstance(languages, list) or not languages or any(x not in LANGUAGES for x in languages):
        raise ValueError('Scegli almeno una lingua supportata')
    result['languages'] = list(dict.fromkeys(languages))
    default = result.get('default_language', 'en')
    if default not in result['languages']:
        default = result['languages'][0]
    result['default_language'] = default
    result['languages'] = [default, *[x for x in result['languages'] if x != default]]
    if result.get('content_type') not in ('silent', 'documentary'):
        raise ValueError('Tipo di contenuto non valido')
    if result.get('source_language') not in (*LANGUAGES, 'auto'):
        raise ValueError('Lingua originale non supportata')
    if result.get('output_height') not in (1080, 1440, 2160):
        raise ValueError('Risoluzione del restauro non supportata')
    for name in ('make_music', 'preserve_source_audio', 'make_publication', 'include_sigla', 'output_subfolder'):
        if not isinstance(result.get(name), bool):
            raise ValueError(f'{name}: scegliere un valore booleano')
    if result['content_type'] == 'documentary':
        result['preserve_source_audio'] = True
    for key in ('sigla_assets_dir', 'output_dir', 'music_style'):
        if not isinstance(result.get(key), str) or len(result[key]) > 4096:
            raise ValueError(f'{key}: valore non valido')
    if result.get('sigla_cta_language') not in LANGUAGES:
        raise ValueError('Lingua della sigla non supportata')
    for key, limit in (('publication_title', 100), ('publication_year', 4), ('source_credit', 1500)):
        value = result.get(key, '')
        if not isinstance(value, str) or len(value) > limit or any(c in value for c in '<>'):
            raise ValueError(f'{key}: valore non valido')
        result[key] = value.strip()
    if not isinstance(result.get('made_for_kids', False), bool):
        raise ValueError('Indica se il contenuto è destinato ai bambini')
    return result


def save_defaults(data):
    normalized = options(data)
    # Titolo, anno e attribuzioni appartengono al film, mai al preset del canale.
    value = {k: normalized[k] for k in PREFERENCE_KEYS}
    store().save(value)
    return value
