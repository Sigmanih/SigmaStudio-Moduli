# ==============================================================================
# core/modules/sigma_creative_lab/video/tool_schemas.py — Schemi dei Tool Video
# ==============================================================================
"""Dichiarazione degli schemi JSON dei tool video per l'Agent Harness."""

SCHEMI = (
    # --- Personaggi ---
    {
        "type": "function",
        "function": {
            "name": "video_char_list",
            "description": "Elenca tutti i personaggi memorizzati nella libreria del Video Studio.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_char_get",
            "description": "Restituisce i dati completi di un personaggio: DNA descrittivo, model sheet, viste e voce.",
            "parameters": {
                "type": "object",
                "properties": {
                    "char_id": {"type": "string", "description": "Identificativo univoco del personaggio"},
                },
                "required": ["char_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_char_create",
            "description": "Crea una nuova scheda personaggio con DNA visivo rigoroso nella libreria riutilizzabile.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nome del personaggio"},
                    "description": {
                        "type": "string",
                        "description": "Descrizione densa dell'aspetto (viso, occhi, capelli, vestiti immutabili)",
                    },
                    "genre": {
                        "type": "string",
                        "description": "Genere visivo (es. 'realistic', 'anime', 'cinematic')",
                        "default": "realistic",
                    },
                    "voice_id": {
                        "type": "string",
                        "description": "ID voce associata in Voice Studio (opzionale)",
                        "default": "",
                    },
                },
                "required": ["name", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_char_update",
            "description": "Aggiorna i campi di un personaggio esistente (descrizione, voce, note, genere).",
            "parameters": {
                "type": "object",
                "properties": {
                    "char_id": {"type": "string", "description": "Identificativo del personaggio"},
                    "name": {"type": "string", "description": "Nuovo nome opzionale"},
                    "description": {"type": "string", "description": "Nuova descrizione dell'aspetto"},
                    "genre": {"type": "string", "description": "Genere visivo"},
                    "voice_id": {"type": "string", "description": "ID voce associata"},
                    "notes": {"type": "string", "description": "Note di recitazione o caratterizzazione"},
                },
                "required": ["char_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_char_candidates",
            "description": "Genera proposte visive d'immagine per la scelta dell'immagine di riferimento iniziale.",
            "parameters": {
                "type": "object",
                "properties": {
                    "char_id": {"type": "string", "description": "Identificativo del personaggio"},
                    "count": {"type": "integer", "description": "Numero di proposte da generare (1-4)", "default": 4},
                },
                "required": ["char_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_char_pick",
            "description": "Seleziona una delle proposte generate come immagine di riferimento ufficiale del personaggio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "char_id": {"type": "string", "description": "Identificativo del personaggio"},
                    "file": {"type": "string", "description": "Percorso relativo del file scelto (es. 'candidates/cand_123.png')"},
                },
                "required": ["char_id", "file"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_char_view_prompt",
            "description": "Calcola il prompt ottimizzato per una vista specifica del model sheet (profile, back, closeup, happy, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "char_id": {"type": "string", "description": "Identificativo del personaggio"},
                    "view": {
                        "type": "string",
                        "enum": ["profile", "back", "closeup", "happy", "sad", "angry", "surprised"],
                        "description": "Tipo di inquadratura o espressione del model sheet",
                    },
                    "fix": {"type": "string", "description": "Correzione opzionale da iniettare nel prompt", "default": ""},
                },
                "required": ["char_id", "view"],
            },
        },
    },

    # --- Produzioni & Storyboard ---
    {
        "type": "function",
        "function": {
            "name": "video_prod_list",
            "description": "Elenca le produzioni video presenti nel workspace con stato, numero di inquadrature e durata.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_prod_get",
            "description": "Restituisce il manifest completo di una produzione video (settings, bible, storyboard, inquadrature).",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {"type": "string", "description": "Identificativo della produzione"},
                },
                "required": ["prod_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_prod_create",
            "description": "Crea una nuova produzione video con titolo, trattamento, stile visivo e impostazioni di modello.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titolo della produzione cinematografica"},
                    "treatment": {"type": "string", "description": "Soggetto, sinossi o trattamento della storia"},
                    "style": {"type": "string", "description": "Stile visivo (es. 'Cinematic 35mm, dark moody lighting')", "default": ""},
                    "video_model": {"type": "string", "enum": ["ltx25", "h3"], "description": "Modello video da usare", "default": "ltx25"},
                    "genre": {"type": "string", "description": "Genere della produzione", "default": "realistic"},
                },
                "required": ["title", "treatment"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_prod_plan_storyboard",
            "description": "Genera lo storyboard dal trattamento: se manca, sviluppa prima la storia e descrive luoghi e oggetti (bible.pre), poi scrive le inquadrature con luogo, oggetti ed espressioni.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {"type": "string", "description": "Identificativo della produzione"},
                    "minutes": {"type": "number", "description": "Durata complessiva desiderata in minuti", "default": 1.0},
                    "shot_min": {"type": "number", "description": "Durata minima per inquadratura in secondi", "default": 3.0},
                    "shot_max": {"type": "number", "description": "Durata massima per inquadratura in secondi", "default": 6.0},
                    "replace": {"type": "boolean", "description": "Se True sostituisce lo storyboard esistente", "default": True},
                },
                "required": ["prod_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_prod_add_shot",
            "description": "Aggiunge una nuova inquadratura allo storyboard con prompt, durata, transizione, props e personaggi.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {"type": "string", "description": "Identificativo della produzione"},
                    "prompt": {"type": "string", "description": "Descrizione visiva dell'inquadratura (in inglese)"},
                    "seconds": {"type": "number", "description": "Durata dell'inquadratura in secondi", "default": 4.0},
                    "transition": {"type": "string", "enum": ["cut", "continue"], "default": "cut"},
                    "scene": {"type": "string", "description": "Nome o titolo della scena", "default": "Scena"},
                    "props": {"type": "array", "items": {"type": "string"}, "description": "Oggetti di scena visibili"},
                    "characters": {"type": "array", "items": {"type": "string"}, "description": "Nomi dei personaggi visibili"},
                    "audio": {"type": "string", "description": "Audio, battuta o commento sonoro", "default": ""},
                },
                "required": ["prod_id", "prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_prod_update_shot",
            "description": "Aggiorna un'inquadratura esistente con correzioni di regia, continuity o prompt fotografico.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {"type": "string", "description": "Identificativo della produzione"},
                    "shot_index": {"type": "integer", "description": "Indice dell'inquadratura (0-based)"},
                    "prompt": {"type": "string", "description": "Nuovo prompt dell'inquadratura"},
                    "seconds": {"type": "number", "description": "Nuova durata in secondi"},
                    "transition": {"type": "string", "enum": ["cut", "continue"]},
                    "props": {"type": "array", "items": {"type": "string"}, "description": "Lista aggiornata dei props"},
                    "characters": {"type": "array", "items": {"type": "string"}, "description": "Personaggi aggiornati"},
                    "audio": {"type": "string", "description": "Audio o dialogo aggiornato"},
                },
                "required": ["prod_id", "shot_index"],
            },
        },
    },

    # --- Render, Qualità e Ispezione ---
    {
        "type": "function",
        "function": {
            "name": "video_render_shot",
            "description": ("Rimette in coda un'inquadratura e avvia il render in background (solo i clip mancanti). "
                            "Non aspetta la fine: controlla con video_render_status."),
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {"type": "string", "description": "Identificativo della produzione"},
                    "shot_index": {"type": "integer", "description": "Indice dell'inquadratura (0-based)"},
                    "gpu": {"type": "integer", "description": "Indice della GPU da impiegare", "default": 0},
                },
                "required": ["prod_id", "shot_index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_judge_clip",
            "description": ("Esamina la clip con il giudice visivo (malformazioni, fisica, direzione del moto, azione). "
                            "Il campo 'passed' e' la decisione da seguire: usa la stessa soglia della produzione."),
            "parameters": {
                "type": "object",
                "properties": {
                    "clip_path": {"type": "string", "description": "Percorso relativo o assoluto del file video (.mp4)"},
                    "intent": {"type": "string", "description": "Azione e contenuto atteso della scena"},
                    "camera": {"type": "string", "description": "Movimento camera richiesto (opzionale)", "default": ""},
                    "prod_id": {"type": "string", "description": "Produzione: per usare la sua soglia del giudice",
                                "default": ""},
                },
                "required": ["clip_path", "intent"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_inspect_shot",
            "description": "Restituisce lo storico di giudizio visivo, punteggio e clip renderizzate per un'inquadratura.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {"type": "string", "description": "Identificativo della produzione"},
                    "shot_index": {"type": "integer", "description": "Indice dell'inquadratura (0-based)"},
                },
                "required": ["prod_id", "shot_index"],
            },
        },
    },

    # --- Timeline ed Editor ---
    {
        "type": "function",
        "function": {
            "name": "video_timeline_get",
            "description": "Restituisce lo stato attuale della timeline, tracce, tagli e profondità storica dell'editor video.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {"type": "string", "description": "Identificativo della produzione"},
                },
                "required": ["prod_id"],
            },
        },
    },

    # --- Render, personaggi nella storia, fotogrammi chiave, correzioni ---
    {
        "type": "function",
        "function": {
            "name": "video_render",
            "description": "Avvia in background il render di tutte le inquadrature mancanti e il montaggio finale.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {
                        "type": "string",
                        "description": "Identificativo della produzione"
                    }
                },
                "required": [
                    "prod_id"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "video_render_status",
            "description": "Avanzamento del render: inquadratura corrente, ultimi eventi, clip completate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {
                        "type": "string",
                        "description": "Produzione (opzionale)",
                        "default": ""
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "video_char_sheet",
            "description": "Genera il model sheet del personaggio (profilo, retro, primo piano, espressioni), ogni vista confrontata col riferimento. Serve prima un riferimento scelto (video_char_pick).",
            "parameters": {
                "type": "object",
                "properties": {
                    "char_id": {
                        "type": "string",
                        "description": "Identificativo del personaggio"
                    },
                    "views": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        },
                        "description": "Viste da rifare (profile, back, closeup, happy, sad, angry, surprised); vuoto = tutte"
                    }
                },
                "required": [
                    "char_id"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "video_char_to_production",
            "description": "Aggiunge un personaggio della libreria alla bibbia della produzione, con immagine di riferimento e voce: da quel momento i fotogrammi chiave lo disegnano identico.",
            "parameters": {
                "type": "object",
                "properties": {
                    "char_id": {
                        "type": "string",
                        "description": "Identificativo del personaggio"
                    },
                    "prod_id": {
                        "type": "string",
                        "description": "Identificativo della produzione"
                    }
                },
                "required": [
                    "char_id",
                    "prod_id"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "video_keyframes",
            "description": "Genera i primi fotogrammi delle inquadrature (con i riferimenti dei personaggi) e li controlla col giudice. Da fare prima del render quando si usa LTX-2.5.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {
                        "type": "string",
                        "description": "Identificativo della produzione"
                    },
                    "shot_indices": {
                        "type": "array",
                        "items": {
                            "type": "integer"
                        },
                        "description": "Inquadrature da rifare; vuoto = tutte quelle senza fotogramma"
                    },
                    "missing_only": {
                        "type": "boolean",
                        "default": True
                    }
                },
                "required": [
                    "prod_id"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "video_shot_fix",
            "description": "Salva una correzione in inglese nel prompt dell'inquadratura (es. 'the lamp stays in her right hand') e la rimette in coda; con rerender=true avvia subito il nuovo render.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {
                        "type": "string",
                        "description": "Identificativo della produzione"
                    },
                    "shot_index": {
                        "type": "integer",
                        "description": "Indice dell'inquadratura (0-based)"
                    },
                    "fix": {
                        "type": "string",
                        "description": "Correzione breve in inglese"
                    },
                    "rerender": {
                        "type": "boolean",
                        "default": False
                    }
                },
                "required": [
                    "prod_id",
                    "shot_index",
                    "fix"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "video_dialogue",
            "description": "Battuta in campo: il personaggio della bibbia la dice con la sua voce e il labiale sincronizzato. La clip entra nella timeline. Job in coda: controlla con video_job_status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {
                        "type": "string",
                        "description": "Identificativo della produzione"
                    },
                    "character": {
                        "type": "string",
                        "description": "Nome del personaggio nella bibbia"
                    },
                    "text": {
                        "type": "string",
                        "description": "Battuta esatta, nella lingua del video"
                    },
                    "action": {
                        "type": "string",
                        "description": "Inquadratura e azione, in inglese",
                        "default": ""
                    },
                    "emotion": {
                        "type": "string",
                        "default": ""
                    },
                    "setting": {
                        "type": "string",
                        "description": "Ambiente della scena, in inglese",
                        "default": ""
                    },
                    "ambience": {
                        "type": "string",
                        "description": "Suoni d'ambiente",
                        "default": ""
                    }
                },
                "required": [
                    "prod_id",
                    "character",
                    "text"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "video_scene",
            "description": "Scena didattica esatta (formule, grafici, traiettorie, figure geometriche, elenchi) resa dal browser e inserita nella timeline. Job in coda.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {
                        "type": "string",
                        "description": "Identificativo della produzione"
                    },
                    "description": {
                        "type": "string",
                        "description": "Cosa deve mostrare la scena"
                    },
                    "seconds": {
                        "type": "number",
                        "default": 8.0
                    },
                    "mode": {
                        "type": "string",
                        "enum": [
                            "kit",
                            "html"
                        ],
                        "default": "kit"
                    }
                },
                "required": [
                    "prod_id",
                    "description"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "video_lesson",
            "description": "Lezione animata intera da un argomento: copione a capitoli, voce narrante, una scena per capitolo, montaggio. Job in coda.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {
                        "type": "string",
                        "description": "Identificativo della produzione"
                    },
                    "topic": {
                        "type": "string"
                    },
                    "minutes": {
                        "type": "number",
                        "default": 1.0
                    },
                    "audience": {
                        "type": "string",
                        "default": ""
                    },
                    "voice_id": {
                        "type": "string",
                        "description": "Voce della libreria di Voice Studio",
                        "default": ""
                    }
                },
                "required": [
                    "prod_id",
                    "topic"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "video_export",
            "description": "Esporta il montaggio della timeline in MP4. Job in coda.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {
                        "type": "string",
                        "description": "Identificativo della produzione"
                    }
                },
                "required": [
                    "prod_id"
                ]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "video_job_status",
            "description": "Stato dei job dell'editor (dialoghi, scene, lezioni, esportazioni).",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {
                        "type": "string",
                        "default": ""
                    },
                    "job_id": {
                        "type": "string",
                        "default": ""
                    }
                },
                "required": []
            }
        }
    },

)
