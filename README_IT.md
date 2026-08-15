# 📦 SigmaStudio-Moduli — Hub Ufficiale Moduli ed Estensioni

<p align="center">
  <strong>Repository Open-Source Ufficiale per i Moduli e le Estensioni di Σ-SIGMA Studio</strong>
</p>

<p align="center">
  <a href="README.md">🇬🇧 English</a> • <a href="README_IT.md">🇮🇹 Italiano</a> • <a href="https://github.com/Sigmanih/SigmaStudio">🧬 Kernel di SigmaStudio</a>
</p>

---

## 🌟 Panoramica

Benvenuto nel catalogo ufficiale dei moduli ed estensioni per **Σ-SIGMA Studio**.

Sigma Studio adotta un'architettura **Micro-Kernel modulare a camere stagne**. Tutti i laboratori generativi avanzati, gli strumenti di telemetria hardware, la sintesi vocale e i sistemi multi-agente specializzati risiedono in questo repository come moduli autonomi ed isolati.

Ciascun modulo può essere **installato, disinstallato o aggiornato con 1-click** direttamente dall'**Hub Moduli & Estensioni** all'interno dell'interfaccia di Sigma Studio, senza necessità di riavviare il server.

---

## 📂 Catalogo Ufficiale dei Moduli

| ID Modulo | Nome Modulo | Categoria | Dimensione | Funzionalità Principali |
|:---|:---|:---|:---|:---|
| [`sigma_creative_lab`](modules/sigma_creative_lab/) | **Creative Lab 3D/2D** | Multimodale & Grafica | ~2 MB | Generazione Text-to-Image con FLUX.1 e SDXL, Img2Img, rimozione sfondo con SAM2 e rembg, generazione 3D con Hunyuan3D e TripoSR, materiali PBR, rendering Blender headless, generazione video Wan2.1, DAG node editor, Creative MCP server. |
| [`sigma_training_lab`](modules/sigma_training_lab/) | **Training Lab & SLM Forge** | Fine-Tuning & SLM | ~6 MB | Unsloth QLoRA, PEFT, Gradus Functional Weight Engine (FWE), Autopilot per tuning automatico iperparametri, quantizzazione GGUF per Ollama, benchmark automatizzati MMLU/GSM8K/HumanEval. |
| [`sigma_voice_studio`](modules/sigma_voice_studio/) | **Voice Studio & Speech Lab** | Voce Neurale & Audio | ~3 MB | Kokoro 82M ultra-veloce, Coqui XTTS-v2 zero-shot voice cloning, regolazione fine velocità/tono, waveform visualizer in tempo reale, preset vocali, Voice MCP server. |
| [`sigma_hardware_lab`](modules/sigma_hardware_lab/) | **Hardware & Telemetria GPU** | Sistema & VRAM | ~1 MB | Telemetria live di VRAM allocata/riservata e RAM di sistema, grafici di carico CPU/GPU, monitoraggio processi CUDA, terminazione processi zombie, riavvio automatico demone Ollama. |
| [`sigma_research_lab`](modules/sigma_research_lab/) | **Pipelines Lab & Swarm** | Ricerca & Automazione | ~1 MB | Visual designer per pipeline a nodi DAG, loop di ricerca autonoma multi-agente, ispezione dettagliata dello stato di esecuzione. |
| [`sigma_knowledge`](modules/sigma_knowledge/) | **Argomenti & Grafo Memoria** | Conoscenza & Memoria | ~2 MB | Grafo relazionale interattivo force-directed in D3.js, Universal Knowledge Nodes explorer, broker di memoria episodica, Memory MCP server. |
| [`sigma_roadmap`](modules/sigma_roadmap/) | **Roadmap & Kanban Task** | Produttività & Attività | ~1 MB | Calendario interattivo delle milestone, lavagna Kanban drag-and-drop con stati operativi, audit log cronologico, pannello flottante di monitoraggio. |
| [`sigma_domotica`](modules/sigma_domotica/) | **Smart Home Assistant** | IoT & Domotica | ~1 MB | Bridge WebSocket/REST nativo per Home Assistant, auto-discovery dispositivi smart, trigger di automazioni, gestione luci, clima e sensori. |

---

## 🏗️ Specifiche di Architettura Modulare

Ogni modulo in `modules/<id_modulo>/` è un pacchetto completamente autocontenuto con netta separazione tra frontend, backend, test suite e metadati:

```text
modules/sigma_<nome_modulo>/
├── manifest.json            # Metadati del modulo, permessi, rotte ed entrypoint
├── requirements.txt         # Dipendenze Python specifiche del modulo
├── README.md                # Documentazione e guida all'uso del modulo
├── frontend/                # Componenti React e fogli di stile (isolati dal kernel)
│   ├── index.jsx            # Entrypoint root esportato verso Sigma Studio
│   └── styles/              # Regole CSS dedicate
├── backend/                 # Route Python e implementazioni MCP server
│   ├── __init__.py
│   ├── handlers.py          # Registrazione route FastAPI ed injection a caldo
│   └── mcp_server.py        # Server Model Context Protocol opzionale
└── tests/                   # Suite di test isolata per validazione CI/CD
```

### Schema del Manifest (`manifest.json`)
```json
{
  "id": "sigma_esempio_modulo",
  "name": "Nome Modulo di Esempio",
  "version": "v1.0.0",
  "category": "Nome Categoria",
  "tabType": "esempio_tab",
  "sidebarLabel": "Esempio Modulo",
  "sidebarIcon": "Sparkles",
  "description": "Descrizione approfondita delle funzionalità del modulo.",
  "author": "Sigma Core Team",
  "repository": "https://github.com/Sigmanih/SigmaStudio-Moduli",
  "branch": "main",
  "path": "modules/sigma_esempio_modulo",
  "tags": ["AI", "FastAPI", "React"],
  "frontend": {
    "entrypoint": "frontend/index.jsx",
    "styles": ["frontend/styles/esempio.css"]
  },
  "backend": {
    "handlers_module": "core.modules.sigma_esempio_modulo.backend.handlers",
    "mcp_server_module": "core.modules.sigma_esempio_modulo.backend.mcp_server",
    "routes_prefix": "/api/esempio"
  },
  "requirements": "requirements.txt"
}
```

---

## 🛠️ Come Sviluppare un Nuovo Modulo

1. **Crea la Cartella**: Crea `modules/sigma_<tuo_modulo>/` seguendo la struttura sopra indicata.
2. **Definisci il Manifest**: Compila il file `manifest.json` specificando ID, tab, icone della sidebar e rotte API.
3. **Sviluppa il Frontend**: Crea i componenti React in `frontend/` ed esponili in `frontend/index.jsx`.
4. **Implementa il Backend**: Crea `backend/handlers.py` con le funzioni `register_routes(app)` e l'eventuale `register_mcp(mcp_hub)`.
5. **Scrivi i Test**: Aggiungi i test unitari in `tests/`.
6. **Invia una Pull Request**: Apri una PR verso questo repository. Una volta approvata, il modulo sarà immediatamente scaricabile e utilizzabile da tutti gli utenti di Sigma Studio.

---

## 📄 Licenza

- **Licenza**: MIT License — libera per uso personale, accademico e commerciale.
- **Repository Principale**: [Sigmanih/SigmaStudio](https://github.com/Sigmanih/SigmaStudio)
- **Autore**: Sigma Core Team
