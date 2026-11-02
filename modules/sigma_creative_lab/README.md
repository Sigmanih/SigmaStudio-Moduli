# Creative Lab 3D/2D — Sigma Studio Module

Modulo open-source per la generazione e manipolazione multimodale in **Sigma Studio**.

## Funzionalità
- 🎨 Text-to-Image (FLUX.1, SDXL, SD 1.5) via ComfyUI o API cloud
- 🖼️ Img2Img, Inpainting, Upscale, Style Transfer
- ✂️ Rimozione sfondo con SAM2 e rembg
- 🧊 Generazione 3D da immagine (Hunyuan3D, TripoSR)
- 🔧 Mesh Lab: ottimizzazione geometria con Blender headless
- 🎨 Materiali PBR (albedo, normal, roughness, metallic, AO)
- 🎬 Generazione video Text→Video e Image→Video (Wan2.1, LTX-Video)
- 🔗 Pipeline a nodi DAG multi-step
- 🤖 11 tool MCP per agenti AI

## Restauro pronto per YouTube

In Video Studio importa un film in un progetto dedicato, seleziona il video e premi **Restaura video**.
Scegli film/documentario muto oppure documentario con parlato, le lingue e le sigle del canale.
Il preset viene salvato all'avvio; titolo, anno e crediti restano specifici del film.

La pipeline crea il master multilingua con intro/outro, traduce i testi, genera le narrazioni e i sottotitoli
e prepara una cartella YouTube: `audio/`, `subtitles/`, `titles/`, `descriptions/`, `miniatura.jpg`,
`pacchetto_youtube.md` e `youtube_package.json`, compatibile con l'importatore YouTube Studio.
Per i documentari parlati conserva l'audio originale nella sua lingua e allinea i doppiaggi alle frasi trascritte.
Le fasi validate sono riprese dopo un errore; traduzioni incomplete e tracce mancanti impediscono il completamento.

La pipeline non pubblica sul canale. I doppiaggi separati si aggiungono in YouTube Studio → Lingue.
Anno, fonte e diritti non vengono dedotti automaticamente. Le traduzioni e le interpretazioni visive possono
richiedere revisione editoriale; gli interventi singoli sono disponibili nell'Inspector.

## Installazione

Dal **Hub Moduli & Estensioni** di Sigma Studio → Installa "Creative Lab 3D/2D"

## Struttura
```
sigma_creative_lab/
├── manifest.json
├── requirements.txt
├── frontend/          ← 28 componenti React + CSS
└── backend/           ← 44 file Python, 36 route HTTP, 11 MCP tool
```

---
Parte di [SigmaStudio-Moduli](https://github.com/Sigmanih/SigmaStudio-Moduli)
