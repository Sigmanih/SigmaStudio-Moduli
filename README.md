# 📦 SigmaStudio-Moduli — Official Extensions & Modules Hub

<p align="center">
  <strong>Official Open-Source Repository for Σ-SIGMA Studio Modular Extensions</strong>
</p>

<p align="center">
  <a href="README.md">🇬🇧 English</a> • <a href="README_IT.md">🇮🇹 Italiano</a> • <a href="https://github.com/Sigmanih/SigmaStudio">🧬 SigmaStudio Kernel</a>
</p>

---

## 🌟 Overview

Welcome to the official modules catalog for **Σ-SIGMA Studio**. 

Sigma Studio is built around a lightweight **Micro-Kernel architecture**. All specialized tools, generative labs, hardware telemetry, and advanced multi-agent workspaces are maintained in this repository as standalone, isolated modules.

Each module can be **installed, uninstalled, or updated with 1-click** directly from the **Marketplace & Extensions Hub** inside Sigma Studio, without restarting the server.

---

## 📂 Official Module Directory

| Module ID | Module Name | Category | Size | Key Capabilities & Highlights |
|:---|:---|:---|:---|:---|
| [`sigma_creative_lab`](modules/sigma_creative_lab/) | **Creative Lab 3D/2D** | Multimodal & Graphics | ~2 MB | FLUX.1 & SDXL Text-to-Image, Img2Img, SAM2/rembg background removal, Hunyuan3D/TripoSR 3D generation, PBR materials, Blender headless rendering, Wan2.1 video generation, DAG node editor, Creative MCP server. |
| [`sigma_training_lab`](modules/sigma_training_lab/) | **Training Lab & SLM Forge** | LLM Training & SLM | ~6 MB | Unsloth QLoRA, PEFT, Gradus Functional Weight Engine (FWE), Autopilot hyperparameter optimization, GGUF quantization, MMLU/GSM8K/HumanEval automated benchmarks. |
| [`sigma_voice_studio`](modules/sigma_voice_studio/) | **Voice Studio & Speech Lab** | Neural Voice & Audio | ~3 MB | Kokoro 82M ultra-fast TTS, Coqui XTTS-v2 zero-shot voice cloning, pitch/speed tuning, live waveform visualizer, voice presets, Voice MCP server. |
| [`sigma_hardware_lab`](modules/sigma_hardware_lab/) | **Hardware & GPU Telemetry** | System & VRAM | ~1 MB | Live VRAM and RAM allocation telemetry, GPU/CPU load charts, CUDA process monitor, zombie task termination, Ollama daemon restart. |
| [`sigma_research_lab`](modules/sigma_research_lab/) | **Pipelines Lab & Swarm** | Research & Automation | ~1 MB | Visual DAG pipeline designer, multi-agent automated research sessions, execution tree inspector. |
| [`sigma_knowledge`](modules/sigma_knowledge/) | **Argomenti & Knowledge Graph** | Knowledge & Memory | ~2 MB | D3 force-directed interactive relational graph, Universal Knowledge Nodes explorer, episodic memory broker, Memory MCP server. |
| [`sigma_roadmap`](modules/sigma_roadmap/) | **Roadmap & Task Kanban** | Productivity & Tasks | ~1 MB | Interactive Activity Calendar, drag-and-drop Kanban task board, chronological audit trail, floating milestone tracker. |
| [`sigma_domotica`](modules/sigma_domotica/) | **Smart Home Assistant** | IoT & Home Automation | ~1 MB | Native Home Assistant WebSocket/REST bridge, smart device discovery, automated routine triggers, climate and lighting controls. |

---

## 🏗️ Module Architecture Specification

Every module in `modules/<module_id>/` is completely self-contained with strict separation between frontend, backend, test suites, and metadata:

```text
modules/sigma_<module_name>/
├── manifest.json            # Module metadata, permissions, routes, and entrypoints
├── requirements.txt         # Module-specific Python dependencies
├── README.md                # Module documentation and usage guide
├── frontend/                # React components and styling (isolated from kernel)
│   ├── index.jsx            # Module root entrypoint exported to Sigma Studio
│   └── styles/              # Dedicated CSS rules
├── backend/                 # Python routes and MCP server implementations
│   ├── __init__.py
│   ├── handlers.py          # FastAPI route registration & hot-injection
│   └── mcp_server.py        # Optional Model Context Protocol server
└── tests/                   # Isolated test suite for automated CI/CD verification
```

### Manifest Schema (`manifest.json`)
```json
{
  "id": "sigma_example_module",
  "name": "Example Module Name",
  "version": "v1.0.0",
  "category": "Category Name",
  "tabType": "example_tab",
  "sidebarLabel": "Example Module",
  "sidebarIcon": "Sparkles",
  "description": "Comprehensive description of module capabilities.",
  "author": "Sigma Core Team",
  "repository": "https://github.com/Sigmanih/SigmaStudio-Moduli",
  "branch": "main",
  "path": "modules/sigma_example_module",
  "tags": ["AI", "FastAPI", "React"],
  "frontend": {
    "entrypoint": "frontend/index.jsx",
    "styles": ["frontend/styles/example.css"]
  },
  "backend": {
    "handlers_module": "core.modules.sigma_example_module.backend.handlers",
    "mcp_server_module": "core.modules.sigma_example_module.backend.mcp_server",
    "routes_prefix": "/api/example"
  },
  "requirements": "requirements.txt"
}
```

---

## 🛠️ How to Develop a New Module

1. **Create Directory**: Create `modules/sigma_<your_module>/` following the structure above.
2. **Define Manifest**: Write `manifest.json` describing your tab, sidebar icon, and routes.
3. **Build Frontend**: Implement your React component in `frontend/` and export it in `frontend/index.jsx`.
4. **Implement Backend**: Create `backend/handlers.py` with `register_routes(app)` and optional `register_mcp(mcp_hub)`.
5. **Add Tests**: Write Pytest test cases in `tests/`.
6. **Submit a PR**: Open a Pull Request to this repository. Once approved, the module becomes instantly discoverable by all Sigma Studio users worldwide.

---

## 📄 License

- **License**: MIT License — free for personal, academic, and commercial use.
- **Main Repository**: [Sigmanih/SigmaStudio](https://github.com/Sigmanih/SigmaStudio)
- **Author**: Sigma Core Team
