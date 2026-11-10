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
