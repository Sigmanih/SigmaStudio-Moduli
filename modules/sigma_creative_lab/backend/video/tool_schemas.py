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
            "name": "video_soundtrack",
            "description": "Attiva la colonna sonora della produzione (musica strumentale generata con ACE-Step, sotto le voci) e, se tutte le clip sono gia' pronte, rimonta il film con la musica. tags descrive genere e atmosfera in inglese.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {"type": "string", "description": "Identificativo della produzione"},
                    "tags": {"type": "string", "description": "Genere e atmosfera in inglese, es. 'anime soundtrack, school life, light pop, piano, strings'"},
                    "enabled": {"type": "boolean", "description": "false per toglierla"},
                    "bpm": {"type": "integer", "description": "Tempo (default 90)"},
                    "keyscale": {"type": "string", "description": "Tonalita', es. 'D major'"},
                    "music_db": {"type": "number", "description": "Volume della musica in dB (default -14)"},
                    "remix": {"type": "boolean", "description": "Rimonta subito se le clip sono pronte (default true)"}
                },
                "required": ["prod_id"]
            }
        }
    },
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
            "description": "Salva una correzione in inglese nel prompt dell'inquadratura (es. 'the lamp stays in her right hand') e la rimette in coda; se c'e' un fotogramma chiave lo rifa' con la stessa correzione. Con rerender=true avvia subito il nuovo render.",
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
            "description": "Stato dei job dell'editor (lettura e regia dei fumetti, dialoghi, scene, lezioni, "
                           "esportazioni). Per aspettare un job lungo usa wait_s (fino a 300): la chiamata torna "
                           "appena il job avanza o finisce, invece di interrogarlo a raffica.",
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
                    },
                    "wait_s": {"type": "number", "default": 0,
                               "description": "Secondi massimi di attesa di un cambiamento (0-300)"}
                },
                "required": []
            }
        }
    },

    # --- Trasposizione da fumetto ---
    {
        "type": "function",
        "function": {
            "name": "video_char_from_image",
            "description": "Proposte del riferimento di un personaggio RIDISEGNATE da un'immagine dell'opera "
                           "(copertina, tavola a colori, vignetta), invece che inventate da una descrizione. "
                           "Guarda le proposte con view_image e scegli con video_char_pick.",
            "parameters": {
                "type": "object",
                "properties": {
                    "char_id": {"type": "string"},
                    "image_path": {"type": "string", "description": "Immagine sorgente (assoluta o dalla radice del progetto)"},
                    "region": {"type": "array", "items": {"type": "number"},
                               "description": "Ritaglio [x0, y0, x1, y1] in pixel o frazioni 0-1 sul personaggio"},
                    "count": {"type": "integer", "default": 2},
                },
                "required": ["char_id", "image_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_manga_read",
            "description": "Collega alla produzione la cartella di un capitolo di manga e ne legge OGNI vignetta in "
                           "ordine manga (destra-sinistra, alto-basso): inquadratura, personaggi, azione, battute, "
                           "pensieri, didascalie, onomatopee. Job lungo (circa 1 minuto a pagina): segui con "
                           "video_job_status. Riprende dalle pagine gia' lette.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {"type": "string"},
                    "folder": {"type": "string", "description": "Cartella con le pagine (001.jpg, 002.jpg, ...)"},
                    "exclude_pages": {"type": "array", "items": {"type": "string"},
                                      "description": "Pagine da saltare: copertine, crediti, pagine vuote (es. \"001\")"},
                },
                "required": ["prod_id", "folder"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_manga_pages",
            "description": "Panoramica del capitolo letto: vignette e testi per pagina, vignette illeggibili, "
                           "regia fatta, e l'immagine di controllo di ogni pagina (riquadri numerati nell'ordine "
                           "di lettura) da verificare con view_image.",
            "parameters": {"type": "object", "properties": {"prod_id": {"type": "string"}}, "required": ["prod_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_manga_panel",
            "description": "Lettura completa di una vignetta (id come \"008_04\") col percorso del ritaglio.",
            "parameters": {
                "type": "object",
                "properties": {"prod_id": {"type": "string"}, "panel_id": {"type": "string"}},
                "required": ["prod_id", "panel_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_manga_script",
            "description": "Il capitolo letto come copione compatto: una riga per battuta, pensiero, didascalia o "
                           "onomatopea, con l'id della vignetta, nell'ordine del manga. Usalo per capire la storia e "
                           "trovare i nomi dei personaggi (query: \"SENSEI\", un nome). Non leggere vignette.json.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {"type": "string"},
                    "from_page": {"type": "string", "description": "Prima pagina, es. \"020\""},
                    "to_page": {"type": "string", "description": "Ultima pagina"},
                    "query": {"type": "string", "description": "Solo i testi che contengono questa parola"},
                },
                "required": ["prod_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_manga_fix_panel",
            "description": "Corregge la lettura di una vignetta dopo averla guardata con view_image: testi nel "
                           "giusto ordine e tipo, piano, azione. Usalo solo per errori visti, non per migliorare "
                           "lo stile: la fedelta' al fumetto viene prima.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {"type": "string"},
                    "panel_id": {"type": "string"},
                    "texts": {"type": "array", "items": {"type": "object", "properties": {
                        "tipo": {"type": "string", "enum": ["battuta", "pensiero", "didascalia", "onomatopea"]},
                        "testo": {"type": "string"}, "chi": {"type": "string"}}},
                        "description": "TUTTI i testi della vignetta, in ordine di lettura manga"},
                    "shot_size": {"type": "string"},
                    "action": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["prod_id", "panel_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_manga_direct",
            "description": "Regia di ogni vignetta coi personaggi della bibbia: chi e' in scena, chi dice ogni "
                           "testo (o se e' fuori campo), inquadratura animata in inglese e colori. Richiede la "
                           "bibbia completa. Job lungo: segui con video_job_status.",
            "parameters": {"type": "object", "properties": {"prod_id": {"type": "string"}}, "required": ["prod_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_manga_storyboard",
            "description": "Sostituisce le inquadrature della produzione con quelle del fumetto: una per vignetta "
                           "muta, una per ogni battuta/pensiero/didascalia, nell'ordine del manga, ognuna col suo "
                           "fotogramma chiave ridisegnato dalla vignetta. Le didascalie le dice il narratore.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prod_id": {"type": "string"},
                    "narrator": {"type": "string", "description": "Personaggio della bibbia che dice le didascalie"},
                    "extra_character": {"type": "string", "default": "Comparsa",
                                        "description": "Personaggio della bibbia per chi non e' riconosciuto"},
                    "exclude_pages": {"type": "array", "items": {"type": "string"},
                                      "description": "Pagine fuori dalla storia: copertine, crediti, pagine nere, "
                                                     "commento dell'autore"},
                },
                "required": ["prod_id", "narrator"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_manga_next",
            "description": "LA PRIMA CHIAMATA di ogni passo di una trasposizione da fumetto: guarda lo stato della "
                           "produzione su disco e dice la fase, cosa manca e il prossimo tool da usare, con gli "
                           "argomenti. Richiamalo dopo ogni passo e dopo un riavvio.",
            "parameters": {"type": "object", "properties": {"prod_id": {"type": "string"}}, "required": ["prod_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_manga_cast",
            "description": "I nomi propri che compaiono nelle battute del capitolo, contati, con le vignette e il "
                           "contesto, e chi dice le didascalie. Da usare PRIMA di creare i personaggi.",
            "parameters": {"type": "object", "properties": {"prod_id": {"type": "string"}}, "required": ["prod_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_manga_exclude",
            "description": "Segna le pagine fuori dalla storia (copertine, crediti, pagine nere, commento "
                           "dell'autore) dopo aver guardato il provino. Anche con lista vuota.",
            "parameters": {
                "type": "object",
                "properties": {"prod_id": {"type": "string"},
                               "pages": {"type": "array", "items": {"type": "string"}},
                               "not_characters": {"type": "array", "items": {"type": "string"},
                                                  "description": "Nomi del cast che non sono personaggi "
                                                                 "(luoghi, parole)"}},
                "required": ["prod_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_prod_remove_character",
            "description": "Toglie un personaggio dalla bibbia della produzione (non dalla libreria).",
            "parameters": {
                "type": "object",
                "properties": {"prod_id": {"type": "string"}, "name": {"type": "string"}},
                "required": ["prod_id", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_manga_speakers",
            "description": "Dopo la regia: l'LLM rilegge il copione intero, pagina per pagina, e corregge chi dice "
                           "ogni battuta (la regia vignetta per vignetta da' spesso la battuta a chi e' in scena "
                           "invece che a chi parla). Job lungo: segui con video_job_status.",
            "parameters": {
                "type": "object",
                "properties": {"prod_id": {"type": "string"},
                               "narrator": {"type": "string",
                                            "description": "Personaggio della bibbia che dice le didascalie"}},
                "required": ["prod_id", "narrator"],
            },
        },
    },

    # --- Restauro di film muti ---
    {
        "type": "function",
        "function": {
            "name": "video_restore_fetch",
            "description": "Scarica un film da Wikimedia Commons o Internet Archive (solo https su quei domini) e lo "
                           "importa nella timeline; se e' un riversamento interlacciato ricompone i fotogrammi della "
                           "pellicola. Prima verifica che l'opera sia libera nel paese di pubblicazione. Job: segui "
                           "con video_job_status.",
            "parameters": {
                "type": "object",
                "properties": {"prod_id": {"type": "string"},
                               "url": {"type": "string", "description": "URL diretto del file video"},
                               "label": {"type": "string", "default": ""}},
                "required": ["prod_id", "url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_restore_clean",
            "description": "Pulisce un film in bianco e nero: polvere e macchie (confronto coi fotogrammi vicini), "
                           "sfarfallio della luce, tremolio del proiettore (stabilizzazione). Nuova versione. "
                           "Fallo PRIMA di video_recolor: su un'immagine pulita il colore sbaglia meno. ~1x la durata. Job.",
            "parameters": {
                "type": "object",
                "properties": {"prod_id": {"type": "string"}, "item_id": {"type": "string", "default": ""}},
                "required": ["prod_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_recolor",
            "description": "Ricolora un elemento in bianco e nero (DDColor): nuova versione, colori stabili nel tempo, "
                           "didascalie lasciate in bianco e nero. ~2,5x la durata del film. Job.",
            "parameters": {
                "type": "object",
                "properties": {"prod_id": {"type": "string"},
                               "item_id": {"type": "string", "default": "",
                                           "description": "Elemento della timeline; vuoto se ce n'e' uno solo"}},
                "required": ["prod_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_upscale",
            "description": "Ingrandisce un elemento con Real-ESRGAN (nuova versione). Fallo DOPO la ricolorazione: "
                           "colorare alla risoluzione originale costa molto meno. Job.",
            "parameters": {
                "type": "object",
                "properties": {"prod_id": {"type": "string"}, "item_id": {"type": "string", "default": ""},
                               "height": {"type": "integer", "enum": [720, 1080, 1440, 2160], "default": 1440}},
                "required": ["prod_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_restore_read",
            "description": "Trova didascalie (testo chiaro su nero) e pagine scritte (lettere, libri, diari), ne legge "
                           "il testo e decide chi lo pronuncia. Job lungo: segui con video_job_status, poi controlla "
                           "con video_restore_cards.",
            "parameters": {
                "type": "object",
                "properties": {"prod_id": {"type": "string"}, "item_id": {"type": "string", "default": ""},
                               "title": {"type": "string", "default": "",
                                         "description": "Titolo del film: aiuta a riconoscere i personaggi"}},
                "required": ["prod_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_restore_cards",
            "description": "Testi letti con indice, tempo, tipo (title/page), personaggio che li legge, chi si vede "
                           "in scena (seen); voci assegnate e atmosfere della musica. A blocchi (start, count) o "
                           "filtrati con query; query='needs_review' da' solo le assegnazioni dubbie: il cast "
                           "automatico ne sbaglia circa un terzo, rivedile tutte.",
            "parameters": {
                "type": "object",
                "properties": {"prod_id": {"type": "string"}, "item_id": {"type": "string", "default": ""},
                               "start": {"type": "integer", "default": 0}, "count": {"type": "integer", "default": 40},
                               "query": {"type": "string", "default": ""}},
                "required": ["prod_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_restore_card_fix",
            "description": "Corregge un testo letto: testo sbagliato o incompleto, personaggio che lo legge (stesso "
                           "nome per lo stesso personaggio), genere/eta' della voce, oppure delete=true per non "
                           "leggerlo (es. il cast nei titoli). Poi rilancia video_restore_narrate.",
            "parameters": {
                "type": "object",
                "properties": {"prod_id": {"type": "string"}, "item_id": {"type": "string", "default": ""},
                               "index": {"type": "integer"}, "text": {"type": "string", "default": ""},
                               "speaker": {"type": "string", "default": ""}, "delete": {"type": "boolean", "default": False},
                               "gender": {"type": "string", "enum": ["", "male", "female"], "default": ""},
                               "age": {"type": "string", "enum": ["", "young", "adult", "old"], "default": ""},
                               "menacing": {"type": "boolean"},
                               "language": {"type": "string", "default": "",
                                            "description": "Lingua della traduzione da correggere (it, fr...): "
                                                           "con questo, 'text' sostituisce la battuta tradotta"}},
                "required": ["prod_id", "index"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_restore_narrate",
            "description": "Legge ad alta voce i testi, una voce per personaggio, e li mette sulla traccia voce "
                           "(sostituisce la narrazione precedente). Ogni battuta e' riascoltata da Whisper: le "
                           "poco chiare tornano in 'unclear'. language: en, it, fr, de, es, pt. Job.",
            "parameters": {
                "type": "object",
                "properties": {"prod_id": {"type": "string"}, "item_id": {"type": "string", "default": ""},
                               "language": {"type": "string", "default": "en"}},
                "required": ["prod_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_restore_score",
            "description": "Colonna sonora: sequenze di ~3 minuti tagliate sugli stacchi, atmosfera di ognuna dal "
                           "modello visivo, un brano ACE-Step per sequenza sulla traccia musica (si abbassa da sola "
                           "sotto le voci all'export). Job lungo.",
            "parameters": {
                "type": "object",
                "properties": {"prod_id": {"type": "string"}, "item_id": {"type": "string", "default": ""},
                               "style": {"type": "string", "default": "",
                                         "description": "Stile comune ai brani; vuoto = orchestra da film muto"},
                               "redescribe": {"type": "boolean", "default": False,
                                              "description": "Rifai da capo le atmosfere col modello visivo; senza, "
                                                             "si tengono quelle salvate (anche corrette) e si "
                                                             "rifanno solo i brani cambiati"}},
                "required": ["prod_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_restore_mood_fix",
            "description": "Corregge l'atmosfera di una sequenza della colonna sonora (indice da video_restore_cards, "
                           "campo moods): tag in inglese su emozione, tempo, dinamica, strumenti. Il modello visivo "
                           "sbaglia spesso (musica allegra in una scena notturna): guarda la sequenza e correggi, poi "
                           "video_restore_score rifa' solo i brani cambiati.",
            "parameters": {
                "type": "object",
                "properties": {"prod_id": {"type": "string"}, "item_id": {"type": "string", "default": ""},
                               "index": {"type": "integer"},
                               "tags": {"type": "string",
                                        "description": "Es. 'ominous, slow, low strings, muted brass, timpani'"}},
                "required": ["prod_id", "index", "tags"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "video_contact_sheet",
            "description": "Provino dell'elemento: 36 fotogrammi su tutta la durata in un'immagine. Guardalo con "
                           "view_image per controllare colori, didascalie e difetti dopo ogni passo.",
            "parameters": {
                "type": "object",
                "properties": {"prod_id": {"type": "string"}, "item_id": {"type": "string", "default": ""},
                               "every_s": {"type": "number", "default": 0}},
                "required": ["prod_id"],
            },
        },
    },
)
