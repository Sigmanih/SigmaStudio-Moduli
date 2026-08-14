# 📦 SigmaStudio-Moduli — Repository Ufficiale Moduli Open Source

Benvenuto nel repository ufficiale dei **Moduli ed Estensioni per Σ-SIGMA Studio**.

Tutti i moduli presenti in questa repository possono essere installati, disinstallati e aggiornati direttamente dall'interfaccia grafica di **Sigma Studio (Hub Moduli & Estensioni)** con 1-click.

---

## 📂 Struttura Moduli

Ogni modulo in `/modules/<nome_modulo>` è completamente modulare e autocontenuto:

```text
modules/
└── sigma_audio_studio/          # Modulo Hi-Fi Sound, Web Radios & Music Lounge
    ├── manifest.json            # Metadati, routing, dipendenze ed endpoint
    ├── README.md                # Documentazione del modulo
    ├── backend/                 # Router FastAPI, controller e servizi
    │   ├── __init__.py
    │   ├── router.py
    │   └── service.py
    └── frontend/                # Componenti React, AudioContext e Stream Deck
        ├── index.js
        ├── AudioContext.jsx
        ├── AudioStudioTab.jsx
        ├── AudioFloatingWidget.jsx
        └── services/
            └── musicRecommendation.js
```

---

## 🚀 Moduli Disponibili

| Modulo ID | Nome | Categoria | Descrizione |
| :--- | :--- | :--- | :--- |
| `sigma_audio_studio` | **Hi-Fi Sound & FM Radio Studio** | Audio & Streaming | Ricevitore stream live FM, capolavori musicali per genere, audio DSP procedurale 432Hz e widget floating. |

---

## 🛠️ Come Sviluppare un Nuovo Modulo

1. Crea una cartella in `modules/<tuo_modulo>`.
2. Definisci il file `manifest.json` con id, nome, versione, tabType e permessi.
3. Inserisci la logica backend in `backend/` e l'interfaccia utente React in `frontend/`.
4. Invia una Pull Request a questo repository.
