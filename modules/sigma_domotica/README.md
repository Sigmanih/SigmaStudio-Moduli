# Domotica & Home Assistant IoT — Sigma Studio Module

Modulo open-source isolato per l'integrazione con **Home Assistant** nel workspace Sigma Studio.

## Funzionalità
- 🏠 Controllo entità smart (luci, prese, termostati, sensori)
- 🎬 Scene personalizzate e automazioni
- 📷 Streaming telecamere in tempo reale
- 🔧 Bridge MCP nativo con Home Assistant WebSocket API
- 🌡️ Dashboard telemetria domotica in tempo reale

## Installazione

Dal Hub Moduli & Estensioni di Sigma Studio → Tab "Repository Remoti" → Installa "Domotica & Home Assistant IoT"

### Manuale (avanzata)

1. Copia `frontend/DomoticaTab.jsx` in `sigma_studio/src/components/Workspace/DomoticaTab.jsx`
2. Copia `backend/homeassistant_server.py` in `core/mcp/homeassistant_server.py`
3. Configura `HA_URL` e `HA_TOKEN` nel pannello configurazione
4. Ricompila il frontend: `cd sigma_studio && npm run build`

## Configurazione

Nel pannello **Configurazione AI** di Sigma Studio, sezione "Domotica":
- `URL Home Assistant`: es. `http://homeassistant.local:8123`
- `Token Long-Lived`: generabile da Profilo → Token di lunga durata in HA

## Struttura

```
sigma_domotica/
├── manifest.json          ← descrittore modulo
├── frontend/
│   └── DomoticaTab.jsx    ← componente React (tab UI)
└── backend/
    └── homeassistant_server.py ← MCP server Home Assistant
```

## Disinstallazione

Dal Hub Moduli → Moduli Installati → Disinstalla "Domotica & Home Assistant IoT"

---

Parte di [SigmaStudio-Moduli](https://github.com/Sigmanih/SigmaStudio-Moduli) — Open Source
