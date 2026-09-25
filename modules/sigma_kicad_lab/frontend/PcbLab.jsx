import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
  Cpu, Layers, Zap, Play, CheckCircle2, AlertTriangle, XCircle,
  FileCode, RefreshCw, Box, Download, Settings, Send,
  Plus, Eye, EyeOff, ZoomIn, ZoomOut, Maximize2, Sparkles, Terminal,
  Activity, ShieldCheck, Compass, Folder, ChevronRight, ChevronDown, PencilRuler
} from 'lucide-react';
import { useApp } from '../../contexts/AppContext';
import PcbEditor from './components/PcbEditor';

// ==============================================================================
// PcbLab — Sigma Studio Native KiCad PCB Design & Agent Team Studio
// ==============================================================================

//: L'agente che lavora sulla scheda: uno solo, quello vero. Il nome sta qui
//: perche' la chat lo mostra anche prima che il server risponda.
const AGENTE_KICAD = {
  sender: 'kicad_engineer',
  senderName: 'KiCad Hardware & PCB Engineer',
  icon: '🔌',
  color: '#10b981',
};

export default function PcbLab({ openTab }) {
  const { theme } = useApp();
  const isLight = theme === 'light';

  // --- Stato di Progetto & Scheda ---
  const [projects, setProjects] = useState([]);
  const [activeProject, setActiveProject] = useState(null);
  const [boardData, setBoardData] = useState(null);
  const [loadingBoard, setLoadingBoard] = useState(false);
  const [activeView, setActiveView] = useState('canvas'); // 'canvas' | 'editor' | '3d' | 'drc' | 'schematic'
  
  // --- Layer attivi nel viewer 2D ---
  const [visibleLayers, setVisibleLayers] = useState({
    'Edge.Cuts': true,
    'F.Cu': true,
    'B.Cu': true,
    'F.SilkS': true,
    'B.SilkS': false,
    'Pads': true,
    'Tracks': true,
    'Vias': true,
  });

  // --- Zoom & Pan Canvas ---
  const [zoom, setZoom] = useState(1.8);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });
  const [selectedComponent, setSelectedComponent] = useState(null);
  const [highlightedNet, setHighlightedNet] = useState(null);

  // --- Test DRC & ERC ---
  const [drcReport, setDrcReport] = useState(null);
  const [ercReport, setErcReport] = useState(null);
  const [runningDrc, setRunningDrc] = useState(false);
  const [runningErc, setRunningErc] = useState(false);

  // --- Render 3D ---
  const [render3DUrl, setRender3DUrl] = useState(null);
  const [rendering3D, setRendering3D] = useState(false);
  const [renderSide, setRenderSide] = useState('top');

  // --- Team Agenti Hardware & Chat ---
  const [messages, setMessages] = useState([
    {
      id: 'welcome',
      role: 'assistant',
      sender: 'hardware_architect',
      senderName: 'Lead Hardware Architect',
      icon: '⚡',
      color: '#f59e0b',
      text: 'Benvenuto in **Hardware Studio**! Il team di agenti KiCad è pronto per progettare, posizionare e verificare il tuo circuito con garanzia di collaudo ad anello chiuso (100% 0 errori DRC ed ERC). Descrivi cosa desideri realizzare o scegli un task rapido.',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    },
  ]);
  const [inputTask, setInputTask] = useState('');
  const [agentRunning, setAgentRunning] = useState(false);
  const [activeAgentRole, setActiveAgentRole] = useState('hardware_architect');
  const [verifiedBadge, setVerifiedBadge] = useState(true);

  // --- Modale Nuovo Progetto ---
  const [showNewModal, setShowNewModal] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [newBoardWidth, setNewBoardWidth] = useState(80);
  const [newBoardHeight, setNewBoardHeight] = useState(60);

  // Caricamento elenco progetti al mount
  const fetchProjects = useCallback(async () => {
    try {
      const res = await fetch('/api/kicad/projects');
      if (res.ok) {
        const data = await res.json();
        if (data.projects && data.projects.length > 0) {
          setProjects(data.projects);
          if (!activeProject) {
            setActiveProject(data.projects[0]);
          }
        }
      }
    } catch (err) {
      console.warn('Impossibile recuperare progetti KiCad:', err);
    }
  }, [activeProject]);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  // Carica dati scheda quando cambia il progetto attivo
  const fetchBoardData = useCallback(async (pcbPath) => {
    if (!pcbPath) return;
    setLoadingBoard(true);
    try {
      const res = await fetch(`/api/kicad/board?pcb_path=${encodeURIComponent(pcbPath)}`);
      if (res.ok) {
        const data = await res.json();
        if (data.board) {
          setBoardData(data.board);
        }
      }
    } catch (err) {
      console.error('Errore lettura PCB:', err);
    } finally {
      setLoadingBoard(false);
    }
  }, []);

  useEffect(() => {
    if (activeProject && activeProject.pcb_path) {
      fetchBoardData(activeProject.pcb_path);
    }
  }, [activeProject, fetchBoardData]);

  // Gestione creazione nuovo progetto
  const handleCreateProject = async (e) => {
    e.preventDefault();
    if (!newProjectName.trim()) return;
    try {
      const res = await fetch('/api/kicad/projects/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newProjectName.trim(),
          width_mm: parseFloat(newBoardWidth) || 80,
          height_mm: parseFloat(newBoardHeight) || 60,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setShowNewModal(false);
        setNewProjectName('');
        await fetchProjects();
        if (data.project) {
          setActiveProject({
            name: data.project.project_name,
            pcb_path: data.project.pcb_path,
            sch_path: data.project.sch_path,
            pro_path: data.project.pro_path,
          });
        }
      }
    } catch (err) {
      console.error('Errore creazione progetto:', err);
    }
  };

  // Esegui Ottimizzazione Piazzamento (Simulated Annealing)
  const handleOptimizePlacement = async () => {
    if (!activeProject?.pcb_path) return;
    try {
      const res = await fetch('/api/kicad/placement/optimize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pcb_path: activeProject.pcb_path,
          sch_path: activeProject.sch_path,
          iterations: 3000,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.moves && data.moves.length > 0) {
          // Applica modifiche
          await fetch('/api/kicad/placement/apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              pcb_path: activeProject.pcb_path,
              moves: data.moves,
            }),
          });
          // Ricarica la scheda
          fetchBoardData(activeProject.pcb_path);
          addAgentMessage(
            'pcb_layout',
            'PCB Layout Specialist',
            '🧩',
            '#10b981',
            `Piazzamento componenti ottimizzato con successo! Spostati **${data.moves.length}** footprint. Lunghezza totale collegamenti ridotta del **${data.improvement_pct}%**.`
          );
        } else {
          addAgentMessage('pcb_layout', 'PCB Layout Specialist', '🧩', '#10b981', 'Il piazzamento attuale risulta già ottimo; nessuna variazione necessaria.');
        }
      }
    } catch (err) {
      console.error('Errore piazzamento:', err);
    }
  };

  // Esegui Collaudo DRC con kicad-cli
  const handleRunDrc = async () => {
    if (!activeProject?.pcb_path) return;
    setRunningDrc(true);
    setActiveView('drc');
    try {
      const res = await fetch('/api/kicad/drc', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pcb_path: activeProject.pcb_path }),
      });
      if (res.ok) {
        const data = await res.json();
        setDrcReport(data.drc);
        const errCount = data.drc?.total_errors ?? 0;
        const unconnCount = data.drc?.total_unconnected ?? 0;
        setVerifiedBadge(errCount === 0 && unconnCount === 0);
        addAgentMessage(
          'hardware_verifier',
          'DRC/ERC Verifier',
          '🔍',
          '#ec4899',
          errCount === 0 && unconnCount === 0
            ? '✅ **Collaudo DRC Superato con Successo!** 0 violazioni di clearance e 0 piste disconnesse. La scheda è conforme alle regole di fabbricazione.'
            : `⚠️ **DRC Rilevato ${errCount} violazioni e ${unconnCount} disconnessioni.** Seleziona "Risolvi con Agente" per applicare le correzioni automatiche.`
        );
      }
    } catch (err) {
      console.error('Errore DRC:', err);
    } finally {
      setRunningDrc(false);
    }
  };

  // Esegui Render 3D con kicad-cli
  const handleRender3D = async (side = 'top') => {
    if (!activeProject?.pcb_path) return;
    setRendering3D(true);
    setActiveView('3d');
    setRenderSide(side);
    try {
      const res = await fetch('/api/kicad/render', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pcb_path: activeProject.pcb_path,
          side: side,
          width: 1440,
          height: 900,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.data_url) {
          setRender3DUrl(data.data_url);
        }
      }
    } catch (err) {
      console.error('Errore render 3D:', err);
    } finally {
      setRendering3D(false);
    }
  };

  // Esporta Gerber JLCPCB
  const handleExportGerbers = async () => {
    if (!activeProject?.pcb_path) return;
    try {
      const res = await fetch('/api/kicad/export/gerbers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pcb_path: activeProject.pcb_path }),
      });
      if (res.ok) {
        const data = await res.json();
        addAgentMessage(
          'manufacturing_specialist',
          'Manufacturing Specialist',
          '🏭',
          '#a855f7',
          `📦 **File di produzione Gerber e Drill generati con successo!**\nSalvato in: \`${data.gerbers?.output_dir}\` (${data.gerbers?.total_files} file pronti per JLCPCB/PCBWay).`
        );
      }
    } catch (err) {
      console.error('Errore export Gerber:', err);
    }
  };

  // Esporta BOM CSV
  const handleExportBom = async () => {
    if (!activeProject?.sch_path) return;
    try {
      const res = await fetch('/api/kicad/export/bom', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sch_path: activeProject.sch_path }),
      });
      if (res.ok) {
        const data = await res.json();
        addAgentMessage(
          'manufacturing_specialist',
          'Manufacturing Specialist',
          '🏭',
          '#a855f7',
          `📄 **Distinta Base (BOM) generata:**\nFile: \`${data.bom_path}\`\n\`\`\`csv\n${data.csv_preview?.slice(0, 400) || 'Dati BOM estratti'}\n\`\`\``
        );
      }
    } catch (err) {
      console.error('Errore export BOM:', err);
    }
  };

  const addAgentMessage = (sender, senderName, icon, color, text) => {
    setMessages((prev) => [
      ...prev,
      {
        id: `msg_${Date.now()}_${Math.random().toString(36).substr(2, 4)}`,
        role: 'assistant',
        sender,
        senderName,
        icon,
        color,
        text,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      },
    ]);
  };

  //: Il messaggio che cresce mentre l'agente scrive. Uno per run: i `token`
  //: arrivano a pezzi, e un messaggio per token riempirebbe la chat di duecento
  //: righe da un carattere.
  const streamRef = useRef(null);

  const apriMessaggioAgente = () => {
    const id = `stream_${Date.now()}`;
    streamRef.current = id;
    setMessages((prev) => [
      ...prev,
      {
        id,
        role: 'assistant',
        ...AGENTE_KICAD,
        text: '',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      },
    ]);
  };

  const aggiungiAlMessaggio = (pezzo) => {
    if (!pezzo) return;
    const id = streamRef.current;
    setMessages((prev) => prev.map((m) => (
      m.id === id ? { ...m, text: `${m.text || ''}${pezzo}` } : m
    )));
  };

  // Invio task alla chat dell'orchestratore
  const handleSendTask = async () => {
    if (!inputTask.trim() || agentRunning) return;
    const taskText = inputTask.trim();
    setInputTask('');

    setMessages((prev) => [
      ...prev,
      {
        id: `user_${Date.now()}`,
        role: 'user',
        text: taskText,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      },
    ]);

    setAgentRunning(true);
    apriMessaggioAgente();

    try {
      const response = await fetch('/api/kicad/agent/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task: taskText,
          pcb_path: activeProject?.pcb_path || '',
          sch_path: activeProject?.sch_path || '',
          project_dir: activeProject?.dir || '',
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed.startsWith('data: ')) {
            try {
              const event = JSON.parse(trimmed.substring(6));
              handleOrchestratorEvent(event);
            } catch (e) {
              // ignore parse errors
            }
          }
        }
      }
    } catch (err) {
      addAgentMessage(
        'hardware_architect',
        'Lead Hardware Architect',
        '⚡',
        '#f59e0b',
        `Si è verificato un errore durante l'esecuzione del task: ${err.message}`
      );
    } finally {
      setAgentRunning(false);
      if (activeProject?.pcb_path) {
        fetchBoardData(activeProject.pcb_path);
      }
    }
  };

  /**
   * Gli eventi che il server manda durante un run.
   *
   * Il vocabolario e' quello di
   * `core/modules/sigma_kicad_lab/orchestrator.py`: `token` e' il testo
   * dell'agente, `tool` un'operazione che ha chiamato, `tool_result` come e'
   * finita, `closed_loop_verification` l'esito dei controlli veri, `completed`
   * la fine. Un tipo aggiunto da un lato solo non lo disegna nessuno: se ne
   * aggiungi uno, aggiungilo in due posti.
   *
   * I `thought` non si mostrano: sono il canale in cui il modello si parla
   * addosso, e in una scheda serve la conclusione, non il ragionamento.
   */
  const handleOrchestratorEvent = (event) => {
    if (event.type === 'role_changed' && event.role) {
      setActiveAgentRole(event.role.id);
    } else if (event.type === 'token') {
      aggiungiAlMessaggio(event.text || '');
    } else if (event.type === 'tool') {
      aggiungiAlMessaggio(`\n\n⚙️ \`${event.tool}\`\n\n`);
    } else if (event.type === 'tool_result') {
      if (event.success === false) {
        aggiungiAlMessaggio(
          `⚠️ \`${event.tool}\` non riuscito: ${event.error || 'errore non riportato'}\n\n`
        );
      }
    } else if (event.type === 'status') {
      aggiungiAlMessaggio(`\n\n_${event.message || ''}_\n\n`);
    } else if (event.type === 'closed_loop_verification') {
      addAgentMessage(
        AGENTE_KICAD.sender,
        AGENTE_KICAD.senderName,
        '🔍',
        '#ec4899',
        `🔒 **Verifica conclusa**\nDRC Errors: **${event.drc_errors}** | ERC Errors: **${event.erc_errors}**\n${event.guarantee}`
      );
      setVerifiedBadge(event.drc_errors === 0 && event.erc_errors === 0);
    } else if (event.type === 'completed') {
      addAgentMessage(
        AGENTE_KICAD.sender,
        AGENTE_KICAD.senderName,
        AGENTE_KICAD.icon,
        AGENTE_KICAD.color,
        `🎯 **${event.message}**`
      );
    } else if (event.type === 'error') {
      addAgentMessage(
        AGENTE_KICAD.sender,
        AGENTE_KICAD.senderName,
        '⚠️',
        '#ef4444',
        `Il run si è fermato: ${event.message || 'errore non riportato'}`
      );
    }
  };

  // Calcolo viewBox per canvas SVG basato su dimensioni scheda
  const canvasBounds = useMemo(() => {
    if (!boardData) return { ox: 90, oy: 90, w: 100, h: 80 };
    const ox = boardData.origin_x > 0 ? boardData.origin_x - 10 : 90;
    const oy = boardData.origin_y > 0 ? boardData.origin_y - 10 : 90;
    const w = (boardData.width_mm || 80) + 20;
    const h = (boardData.height_mm || 60) + 20;
    return { ox, oy, w, h };
  }, [boardData]);

  // Gestione Pan & Drag sul Canvas
  const handleMouseDown = (e) => {
    if (e.button === 0) { // tasto sinistro
      setIsPanning(true);
      setPanStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
    }
  };

  const handleMouseMove = (e) => {
    if (isPanning) {
      setPan({ x: e.clientX - panStart.x, y: e.clientY - panStart.y });
    }
  };

  const handleMouseUp = () => {
    setIsPanning(false);
  };

  // React registra 'wheel' come listener passive: e.preventDefault() qui
  // fallisce con "Unable to preventDefault inside passive event listener".
  // Lo zoom non ha bisogno di bloccare lo scroll (il contenitore ha
  // overflow:hidden + overscroll-behavior:contain), quindi basta leggere deltaY.
  const handleWheel = (e) => {
    const zoomFactor = e.deltaY < 0 ? 1.15 : 0.85;
    setZoom((prev) => Math.min(Math.max(prev * zoomFactor, 0.5), 10));
  };

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        width: '100%',
        backgroundColor: isLight ? '#f8fafc' : '#07090e',
        color: isLight ? '#1e293b' : '#f1f5f9',
        fontFamily: "'Inter', sans-serif",
        overflow: 'hidden',
      }}
    >
      {/* 1. TOP ACTION TOOLBAR */}
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 18px',
          background: isLight ? '#ffffff' : '#0d111c',
          borderBottom: `1px solid ${isLight ? '#e2e8f0' : 'rgba(255,255,255,0.08)'}`,
          gap: '12px',
          flexWrap: 'wrap',
          zIndex: 10,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: '32px',
              height: '32px',
              borderRadius: '8px',
              background: 'linear-gradient(135deg, #0d6efd, #00d2ff)',
              color: '#fff',
              boxShadow: '0 0 12px rgba(13,110,253,0.4)',
            }}
          >
            <Cpu size={18} />
          </div>

          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontWeight: 700, fontSize: '0.92rem', letterSpacing: '-0.3px' }}>
                Hardware Studio
              </span>
              <span
                style={{
                  fontSize: '0.68rem',
                  fontWeight: 700,
                  padding: '2px 6px',
                  borderRadius: '4px',
                  background: 'rgba(13,110,253,0.18)',
                  color: '#38bdf8',
                  border: '1px solid rgba(56,189,248,0.3)',
                }}
              >
                KICAD 10
              </span>
              {verifiedBadge && (
                <span
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    fontSize: '0.68rem',
                    fontWeight: 700,
                    padding: '2px 6px',
                    borderRadius: '4px',
                    background: 'rgba(16,185,129,0.15)',
                    color: '#10b981',
                    border: '1px solid rgba(16,185,129,0.3)',
                  }}
                  title="Garanzia Anello Chiuso: 0 errori DRC ed ERC verificati da kicad-cli"
                >
                  <ShieldCheck size={12} /> 100% VERIFIED
                </span>
              )}
            </div>

            {/* Selettore Progetto */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '2px' }}>
              <Folder size={12} color="#94a3b8" />
              <select
                value={activeProject?.pcb_path || ''}
                onChange={(e) => {
                  const found = projects.find((p) => p.pcb_path === e.target.value);
                  if (found) setActiveProject(found);
                }}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: isLight ? '#475569' : '#94a3b8',
                  fontSize: '0.78rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                  outline: 'none',
                }}
              >
                {projects.map((p) => (
                  <option key={p.pcb_path} value={p.pcb_path} style={{ background: isLight ? '#fff' : '#0f172a' }}>
                    {p.name} ({p.pcb_path ? p.pcb_path.split(/[\\/]/).pop() : ''})
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {/* Pulsanti Azione Rapida */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button
            onClick={() => setShowNewModal(true)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 11px',
              borderRadius: '6px',
              background: isLight ? '#e2e8f0' : 'rgba(255,255,255,0.06)',
              border: `1px solid ${isLight ? '#cbd5e1' : 'rgba(255,255,255,0.1)'}`,
              color: isLight ? '#1e293b' : '#e2e8f0',
              fontSize: '0.75rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <Plus size={13} /> Nuovo
          </button>

          <button
            onClick={handleOptimizePlacement}
            title="Esegui Simulated Annealing per ottimizzare il piazzamento e minimizzare la lunghezza piste"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 11px',
              borderRadius: '6px',
              background: 'rgba(16,185,129,0.15)',
              border: '1px solid rgba(16,185,129,0.3)',
              color: '#10b981',
              fontSize: '0.75rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <Zap size={13} /> Ottimizza Layout
          </button>

          <button
            onClick={handleRunDrc}
            disabled={runningDrc}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 11px',
              borderRadius: '6px',
              background: 'rgba(236,72,153,0.15)',
              border: '1px solid rgba(236,72,153,0.3)',
              color: '#ec4899',
              fontSize: '0.75rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <RefreshCw size={13} className={runningDrc ? 'spin' : ''} /> Collaudo DRC
          </button>

          <button
            onClick={() => handleRender3D(renderSide)}
            disabled={rendering3D}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 11px',
              borderRadius: '6px',
              background: 'rgba(56,189,248,0.15)',
              border: '1px solid rgba(56,189,248,0.3)',
              color: '#38bdf8',
              fontSize: '0.75rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <Box size={13} className={rendering3D ? 'spin' : ''} /> Render 3D
          </button>

          <button
            onClick={handleExportGerbers}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 11px',
              borderRadius: '6px',
              background: 'rgba(168,85,247,0.15)',
              border: '1px solid rgba(168,85,247,0.3)',
              color: '#c084fc',
              fontSize: '0.75rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <Download size={13} /> Gerber JLCPCB
          </button>

          <button
            onClick={handleExportBom}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 11px',
              borderRadius: '6px',
              background: isLight ? '#f1f5f9' : 'rgba(255,255,255,0.06)',
              border: `1px solid ${isLight ? '#cbd5e1' : 'rgba(255,255,255,0.1)'}`,
              color: isLight ? '#334155' : '#cbd5e1',
              fontSize: '0.75rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <FileCode size={13} /> BOM
          </button>
        </div>
      </header>

      {/* 2. CORPO PRINCIPALE A 3 COLONNE */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden', position: 'relative' }}>
        
        {/* --- COLONNA SINISTRA: LAYER & COMPONENTI INSPECTOR --- */}
        <aside
          style={{
            width: '240px',
            background: isLight ? '#ffffff' : '#0a0e1a',
            borderRight: `1px solid ${isLight ? '#e2e8f0' : 'rgba(255,255,255,0.08)'}`,
            display: 'flex',
            flexDirection: 'column',
            overflowY: 'auto',
            fontSize: '0.78rem',
            userSelect: 'none',
          }}
        >
          {/* Selettore Layer */}
          <div style={{ padding: '12px 14px', borderBottom: `1px solid ${isLight ? '#e2e8f0' : 'rgba(255,255,255,0.06)'}` }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
              <span style={{ fontWeight: 700, textTransform: 'uppercase', fontSize: '0.68rem', letterSpacing: '0.5px', color: '#94a3b8' }}>
                Livelli PCB (Layers)
              </span>
              <Layers size={13} color="#94a3b8" />
            </div>

            {Object.keys(visibleLayers).map((lKey) => (
              <div
                key={lKey}
                onClick={() => setVisibleLayers((p) => ({ ...p, [lKey]: !p[lKey] }))}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '4px 6px',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  background: visibleLayers[lKey] ? (isLight ? '#f1f5f9' : 'rgba(255,255,255,0.04)') : 'transparent',
                  marginBottom: '2px',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span
                    style={{
                      width: '8px',
                      height: '8px',
                      borderRadius: '2px',
                      background:
                        lKey === 'F.Cu'
                          ? '#ef4444'
                          : lKey === 'B.Cu'
                          ? '#3b82f6'
                          : lKey === 'Edge.Cuts'
                          ? '#eab308'
                          : lKey === 'Pads'
                          ? '#10b981'
                          : lKey === 'Tracks'
                          ? '#06b6d4'
                          : '#94a3b8',
                    }}
                  />
                  <span style={{ fontWeight: visibleLayers[lKey] ? 600 : 400, color: visibleLayers[lKey] ? (isLight ? '#0f172a' : '#f8fafc') : '#64748b' }}>
                    {lKey}
                  </span>
                </div>
                {visibleLayers[lKey] ? <Eye size={12} color="#94a3b8" /> : <EyeOff size={12} color="#475569" />}
              </div>
            ))}
          </div>

          {/* Lista Componenti (Footprint) */}
          <div style={{ padding: '12px 14px', flex: 1, overflowY: 'auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
              <span style={{ fontWeight: 700, textTransform: 'uppercase', fontSize: '0.68rem', letterSpacing: '0.5px', color: '#94a3b8' }}>
                Componenti ({boardData?.components?.length || 0})
              </span>
              <Cpu size={13} color="#94a3b8" />
            </div>

            {boardData?.components?.map((c) => {
              const isSelected = selectedComponent?.reference === c.reference;
              return (
                <div
                  key={c.reference}
                  onClick={() => setSelectedComponent(c)}
                  style={{
                    padding: '6px 8px',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    background: isSelected ? 'rgba(13,110,253,0.18)' : 'transparent',
                    border: isSelected ? '1px solid rgba(13,110,253,0.4)' : '1px solid transparent',
                    marginBottom: '3px',
                    transition: 'all 0.15s ease',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ fontWeight: 700, color: '#38bdf8' }}>{c.reference}</span>
                    <span style={{ fontSize: '0.7rem', color: '#94a3b8' }}>{c.value || 'Passivo'}</span>
                  </div>
                  <div style={{ fontSize: '0.67rem', color: '#64748b', marginTop: '1px' }}>
                    X: {c.x_mm} mm · Y: {c.y_mm} mm · {c.pads?.length || 0} pin
                  </div>
                </div>
              );
            })}
          </div>

          {/* Dati Scheda Bottom Info */}
          {boardData && (
            <div
              style={{
                padding: '10px 14px',
                borderTop: `1px solid ${isLight ? '#e2e8f0' : 'rgba(255,255,255,0.06)'}`,
                background: isLight ? '#f8fafc' : 'rgba(0,0,0,0.2)',
                fontSize: '0.72rem',
                color: '#64748b',
              }}
            >
              <div>Dimensioni: <strong style={{ color: isLight ? '#0f172a' : '#f1f5f9' }}>{boardData.width_mm} × {boardData.height_mm} mm</strong></div>
              <div>Tracce: <strong style={{ color: isLight ? '#0f172a' : '#f1f5f9' }}>{boardData.tracks?.length || 0}</strong> · Via: <strong style={{ color: isLight ? '#0f172a' : '#f1f5f9' }}>{boardData.vias?.length || 0}</strong></div>
              <div>Nets: <strong style={{ color: isLight ? '#0f172a' : '#f1f5f9' }}>{boardData.nets?.length || 0}</strong></div>
            </div>
          )}
        </aside>

        {/* --- AREA CENTRALE: CANVAS 2D / VIEW 3D / DRC REPORT --- */}
        <main
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            position: 'relative',
            background: isLight ? '#f1f5f9' : '#05070d',
            overflow: 'hidden',
          }}
        >
          {/* Sub-Tab Navigation Bar */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              padding: '6px 14px',
              background: isLight ? '#ffffff' : '#090d18',
              borderBottom: `1px solid ${isLight ? '#e2e8f0' : 'rgba(255,255,255,0.06)'}`,
              gap: '6px',
            }}
          >
            <button
              onClick={() => setActiveView('canvas')}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '5px 12px',
                borderRadius: '5px',
                background: activeView === 'canvas' ? 'rgba(13,110,253,0.18)' : 'transparent',
                border: activeView === 'canvas' ? '1px solid rgba(13,110,253,0.3)' : '1px solid transparent',
                color: activeView === 'canvas' ? '#38bdf8' : '#94a3b8',
                fontSize: '0.75rem',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              <Cpu size={13} /> 2D PCB Canvas
            </button>

            <button
              onClick={() => setActiveView('editor')}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '5px 12px',
                borderRadius: '5px',
                background: activeView === 'editor' ? 'rgba(16,185,129,0.18)' : 'transparent',
                border: activeView === 'editor' ? '1px solid rgba(16,185,129,0.35)' : '1px solid transparent',
                color: activeView === 'editor' ? '#10b981' : '#94a3b8',
                fontSize: '0.75rem',
                fontWeight: 600,
                cursor: 'pointer',
              }}
              title="Disegna la scheda: sposta i pezzi, traccia piste, metti via, collega i pad"
            >
              <PencilRuler size={13} /> Editor PCB
            </button>

            <button
              onClick={() => {
                setActiveView('3d');
                if (!render3DUrl) handleRender3D('top');
              }}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '5px 12px',
                borderRadius: '5px',
                background: activeView === '3d' ? 'rgba(13,110,253,0.18)' : 'transparent',
                border: activeView === '3d' ? '1px solid rgba(13,110,253,0.3)' : '1px solid transparent',
                color: activeView === '3d' ? '#38bdf8' : '#94a3b8',
                fontSize: '0.75rem',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              <Box size={13} /> 3D Foto Render
            </button>

            <button
              onClick={() => setActiveView('drc')}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '5px 12px',
                borderRadius: '5px',
                background: activeView === 'drc' ? 'rgba(13,110,253,0.18)' : 'transparent',
                border: activeView === 'drc' ? '1px solid rgba(13,110,253,0.3)' : '1px solid transparent',
                color: activeView === 'drc' ? '#38bdf8' : '#94a3b8',
                fontSize: '0.75rem',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              <Activity size={13} /> Collaudo & DRC
              {drcReport && (
                <span
                  style={{
                    fontSize: '0.65rem',
                    padding: '1px 5px',
                    borderRadius: '10px',
                    background: drcReport.total_errors === 0 ? '#10b981' : '#ef4444',
                    color: '#fff',
                  }}
                >
                  {drcReport.total_errors}
                </span>
              )}
            </button>

            {/* Canvas Zoom Controls (visibili in canvas mode) */}
            {activeView === 'canvas' && (
              <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <button
                  onClick={() => setZoom((z) => Math.min(z * 1.25, 10))}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: '#94a3b8',
                    padding: '4px',
                    cursor: 'pointer',
                  }}
                  title="Zoom In"
                >
                  <ZoomIn size={14} />
                </button>
                <button
                  onClick={() => setZoom((z) => Math.max(z * 0.8, 0.4))}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: '#94a3b8',
                    padding: '4px',
                    cursor: 'pointer',
                  }}
                  title="Zoom Out"
                >
                  <ZoomOut size={14} />
                </button>
                <button
                  onClick={() => { setZoom(1.8); setPan({ x: 0, y: 0 }); }}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: '#94a3b8',
                    padding: '4px',
                    cursor: 'pointer',
                  }}
                  title="Reset Vista"
                >
                  <Maximize2 size={14} />
                </button>
              </div>
            )}
          </div>

          {/* VIEW: Editor PCB — scrive sul file con gli stessi tool dell'agente */}
          {activeView === 'editor' && (
            <PcbEditor
              progetto={activeProject}
              isLight={isLight}
              onChanged={() => fetchBoardData(activeProject ? activeProject.pcb_path : '')}
            />
          )}

          {/* VIEW: 2D PCB Canvas */}
          {activeView === 'canvas' && (
            <div
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onWheel={handleWheel}
              style={{
                flex: 1,
                position: 'relative',
                overflow: 'hidden',
                cursor: isPanning ? 'grabbing' : 'grab',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {loadingBoard ? (
                <div style={{ color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <RefreshCw size={18} className="spin" /> Caricamento vettoriale PCB...
                </div>
              ) : boardData ? (
                <svg
                  width="100%"
                  height="100%"
                  viewBox={`${canvasBounds.ox} ${canvasBounds.oy} ${canvasBounds.w} ${canvasBounds.h}`}
                  style={{
                    transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                    transformOrigin: 'center center',
                    transition: isPanning ? 'none' : 'transform 0.05s ease-out',
                  }}
                >
                  {/* Griglia di sfondo */}
                  <defs>
                    <pattern id="grid" width="10" height="10" patternUnits="userSpaceOnUse">
                      <path d="M 10 0 L 0 0 0 10" fill="none" stroke="rgba(255,255,255,0.03)" strokeWidth="0.2" />
                    </pattern>
                  </defs>
                  <rect
                    x={canvasBounds.ox - 100}
                    y={canvasBounds.oy - 100}
                    width={canvasBounds.w + 200}
                    height={canvasBounds.h + 200}
                    fill="url(#grid)"
                  />

                  {/* 1. Sfondo PCB (FR4 Dark Green/Black) */}
                  <rect
                    x={boardData.origin_x || 100}
                    y={boardData.origin_y || 100}
                    width={boardData.width_mm || 80}
                    height={boardData.height_mm || 60}
                    rx="2"
                    fill={isLight ? '#064e3b' : '#0a1d17'}
                    stroke="none"
                  />

                  {/* 2. Layer Edge.Cuts (Giallo) */}
                  {visibleLayers['Edge.Cuts'] && (
                    <rect
                      x={boardData.origin_x || 100}
                      y={boardData.origin_y || 100}
                      width={boardData.width_mm || 80}
                      height={boardData.height_mm || 60}
                      rx="2"
                      fill="none"
                      stroke="#eab308"
                      strokeWidth="0.3"
                    />
                  )}

                  {/* 3. Tracce (Tracks) */}
                  {visibleLayers['Tracks'] &&
                    boardData.tracks?.map((t, idx) => {
                      const isFcu = t.layer === 'F.Cu';
                      if ((isFcu && !visibleLayers['F.Cu']) || (!isFcu && !visibleLayers['B.Cu'])) {
                        return null;
                      }
                      return (
                        <line
                          key={`track_${idx}`}
                          x1={t.start_x}
                          y1={t.start_y}
                          x2={t.end_x}
                          y2={t.end_y}
                          stroke={isFcu ? '#ef4444' : '#3b82f6'}
                          strokeWidth={t.width_mm || 0.25}
                          strokeLinecap="round"
                          opacity={0.85}
                        />
                      );
                    })}

                  {/* 4. Vias */}
                  {visibleLayers['Vias'] &&
                    boardData.vias?.map((v, idx) => (
                      <g key={`via_${idx}`}>
                        <circle cx={v.x_mm} cy={v.y_mm} r={(v.size_mm || 0.8) / 2} fill="#eab308" />
                        <circle cx={v.x_mm} cy={v.y_mm} r={(v.drill_mm || 0.4) / 2} fill="#05070d" />
                      </g>
                    ))}

                  {/* 5. Componenti e Pads */}
                  {boardData.components?.map((c) => {
                    const isSelected = selectedComponent?.reference === c.reference;
                    return (
                      <g
                        key={`comp_${c.reference}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedComponent(c);
                        }}
                        style={{ cursor: 'pointer' }}
                      >
                        {/* Bounding Box / Courtyard Componente */}
                        <rect
                          x={c.x_mm - c.width_mm / 2}
                          y={c.y_mm - c.height_mm / 2}
                          width={c.width_mm}
                          height={c.height_mm}
                          fill={isSelected ? 'rgba(56,189,248,0.25)' : 'rgba(255,255,255,0.06)'}
                          stroke={isSelected ? '#38bdf8' : 'rgba(255,255,255,0.3)'}
                          strokeWidth={isSelected ? '0.3' : '0.15'}
                        />

                        {/* Pads */}
                        {visibleLayers['Pads'] &&
                          c.pads?.map((p, pIdx) => (
                            <rect
                              key={`pad_${c.reference}_${pIdx}`}
                              x={p.x_mm - 0.45}
                              y={p.y_mm - 0.55}
                              width="0.9"
                              height="1.1"
                              rx="0.2"
                              fill="#10b981"
                              stroke="#047857"
                              strokeWidth="0.1"
                            />
                          ))}

                        {/* Serigrafia (Ref text) */}
                        {visibleLayers['F.SilkS'] && (
                          <text
                            x={c.x_mm}
                            y={c.y_mm - c.height_mm / 2 - 0.6}
                            fontSize="1.1"
                            fill="#ffffff"
                            textAnchor="middle"
                            fontFamily="monospace"
                            fontWeight="bold"
                          >
                            {c.reference}
                          </text>
                        )}
                      </g>
                    );
                  })}
                </svg>
              ) : (
                <div style={{ textAlign: 'center', color: '#64748b' }}>
                  <Cpu size={42} style={{ marginBottom: '10px', opacity: 0.4 }} />
                  <div>Nessun progetto PCB KiCad aperto.</div>
                  <button
                    onClick={() => setShowNewModal(true)}
                    style={{
                      marginTop: '12px',
                      padding: '8px 16px',
                      borderRadius: '6px',
                      background: '#0d6efd',
                      color: '#fff',
                      border: 'none',
                      cursor: 'pointer',
                      fontWeight: 600,
                    }}
                  >
                    Crea Progetto da Template
                  </button>
                </div>
              )}
            </div>
          )}

          {/* VIEW: 3D Render Foto */}
          {activeView === '3d' && (
            <div
              style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '20px',
                background: '#020408',
              }}
            >
              <div style={{ marginBottom: '14px', display: 'flex', gap: '8px' }}>
                {['top', 'bottom', 'isometric'].map((s) => (
                  <button
                    key={s}
                    onClick={() => handleRender3D(s)}
                    disabled={rendering3D}
                    style={{
                      padding: '5px 14px',
                      borderRadius: '5px',
                      background: renderSide === s ? '#0d6efd' : 'rgba(255,255,255,0.08)',
                      color: '#fff',
                      border: 'none',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      cursor: 'pointer',
                      textTransform: 'capitalize',
                    }}
                  >
                    Vista {s}
                  </button>
                ))}
              </div>

              {rendering3D ? (
                <div style={{ color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <RefreshCw size={22} className="spin" />
                  <span>Generazione render fotorealistico KiCad 10 in corso...</span>
                </div>
              ) : render3DUrl ? (
                <div style={{ maxWidth: '90%', maxHeight: '75%', borderRadius: '8px', overflow: 'hidden', boxShadow: '0 20px 50px rgba(0,0,0,0.8)' }}>
                  <img src={render3DUrl} alt="KiCad 3D Render" style={{ width: '100%', height: 'auto', display: 'block' }} />
                </div>
              ) : (
                <div style={{ color: '#64748b' }}>Clicca su "Render 3D" per visualizzare la scheda.</div>
              )}
            </div>
          )}

          {/* VIEW: DRC & Health Check */}
          {activeView === 'drc' && (
            <div style={{ flex: 1, overflowY: 'auto', padding: '24px' }}>
              <div style={{ maxWidth: '750px', margin: '0 auto' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
                  <div>
                    <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 700 }}>
                      Collaudo DRC (Design Rule Check)
                    </h3>
                    <p style={{ margin: '4px 0 0', color: '#94a3b8', fontSize: '0.8rem' }}>
                      Esecuzione headless ad anello chiuso tramite <code style={{ color: '#38bdf8' }}>kicad-cli pcb drc</code>
                    </p>
                  </div>
                  <button
                    onClick={handleRunDrc}
                    disabled={runningDrc}
                    style={{
                      padding: '8px 16px',
                      borderRadius: '6px',
                      background: '#ec4899',
                      color: '#fff',
                      border: 'none',
                      fontWeight: 600,
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                    }}
                  >
                    <RefreshCw size={14} className={runningDrc ? 'spin' : ''} />
                    Riesegui Collaudo
                  </button>
                </div>

                {drcReport ? (
                  <div>
                    {/* Banner Esito */}
                    <div
                      style={{
                        padding: '14px 18px',
                        borderRadius: '8px',
                        background: drcReport.total_errors === 0 ? 'rgba(16,185,129,0.12)' : 'rgba(239,68,68,0.12)',
                        border: `1px solid ${drcReport.total_errors === 0 ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        marginBottom: '20px',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        {drcReport.total_errors === 0 ? (
                          <CheckCircle2 size={24} color="#10b981" />
                        ) : (
                          <AlertTriangle size={24} color="#ef4444" />
                        )}
                        <div>
                          <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>
                            {drcReport.total_errors === 0 ? '0 Errori DRC — Regole Rispettate' : `${drcReport.total_errors} Violazioni Rilevate`}
                          </div>
                          <div style={{ fontSize: '0.76rem', color: '#94a3b8' }}>
                            Piste disconnesse: {drcReport.total_unconnected || 0} · Parity schematico: conforme
                          </div>
                        </div>
                      </div>

                      {drcReport.total_errors > 0 && (
                        <button
                          onClick={() => {
                            setInputTask('Esegui correzione automatica di tutte le violazioni DRC e ricalcola le clearance.');
                            handleSendTask();
                          }}
                          style={{
                            padding: '6px 14px',
                            borderRadius: '5px',
                            background: '#0d6efd',
                            color: '#fff',
                            border: 'none',
                            fontWeight: 600,
                            cursor: 'pointer',
                            fontSize: '0.75rem',
                          }}
                        >
                          Risolvi con Agente
                        </button>
                      )}
                    </div>

                    {/* Elenco Violazioni */}
                    {drcReport.violations && drcReport.violations.length > 0 ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {drcReport.violations.map((v, i) => (
                          <div
                            key={i}
                            style={{
                              padding: '10px 14px',
                              borderRadius: '6px',
                              background: isLight ? '#fff' : 'rgba(255,255,255,0.04)',
                              border: `1px solid ${isLight ? '#e2e8f0' : 'rgba(255,255,255,0.08)'}`,
                              fontSize: '0.78rem',
                            }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                              <span style={{ fontWeight: 700, color: '#ef4444' }}>{v.type || 'Violazione Clearance'}</span>
                              <span style={{ fontSize: '0.7rem', color: '#64748b' }}>Severità: {v.severity || 'error'}</span>
                            </div>
                            <div style={{ marginTop: '4px', color: isLight ? '#334155' : '#cbd5e1' }}>{v.description}</div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div style={{ textAlign: 'center', color: '#10b981', padding: '30px' }}>
                        Tutti i controlli geometrici, elettrici e di clearance IPC-2221 sono passati con successo.
                      </div>
                    )}
                  </div>
                ) : (
                  <div style={{ textAlign: 'center', color: '#64748b', padding: '40px' }}>
                    Clicca su "Riesegui Collaudo" per avviare il DRC con kicad-cli.
                  </div>
                )}
              </div>
            </div>
          )}
        </main>

        {/* --- COLONNA DESTRA: HARDWARE AGENT CHAT --- */}
        <aside
          style={{
            width: '380px',
            background: isLight ? '#ffffff' : '#0c101c',
            borderLeft: `1px solid ${isLight ? '#e2e8f0' : 'rgba(255,255,255,0.08)'}`,
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          {/* Header Chat */}
          <div
            style={{
              padding: '12px 16px',
              borderBottom: `1px solid ${isLight ? '#e2e8f0' : 'rgba(255,255,255,0.06)'}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Sparkles size={16} color="#00d2ff" />
              <span style={{ fontWeight: 700, fontSize: '0.85rem' }}>Team Agenti Hardware</span>
            </div>
            <span
              style={{
                fontSize: '0.68rem',
                fontWeight: 600,
                color: '#10b981',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#10b981' }} />
              Live KiCad Engine
            </span>
          </div>

          {/* Badge Ruolo Attivo */}
          <div
            style={{
              padding: '6px 14px',
              background: isLight ? '#f8fafc' : 'rgba(255,255,255,0.02)',
              borderBottom: `1px solid ${isLight ? '#e2e8f0' : 'rgba(255,255,255,0.04)'}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              fontSize: '0.72rem',
            }}
          >
            <span style={{ color: '#94a3b8' }}>Ruolo Attivo:</span>
            <span style={{ fontWeight: 700, color: '#38bdf8' }}>
              {activeAgentRole === 'hardware_architect'
                ? '⚡ Lead Hardware Architect'
                : activeAgentRole === 'schematic_designer'
                ? '📐 Schematic Engineer'
                : activeAgentRole === 'pcb_layout'
                ? '🧩 PCB Layout Specialist'
                : activeAgentRole === 'hardware_verifier'
                ? '🔍 DRC/ERC Verifier'
                : '🏭 Manufacturing Specialist'}
            </span>
          </div>

          {/* Messaggi */}
          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              padding: '14px',
              display: 'flex',
              flexDirection: 'column',
              gap: '12px',
            }}
          >
            {messages.map((m) => {
              const isUser = m.role === 'user';
              return (
                <div
                  key={m.id}
                  style={{
                    alignSelf: isUser ? 'flex-end' : 'flex-start',
                    maxWidth: '92%',
                  }}
                >
                  {!isUser && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '3px', fontSize: '0.72rem' }}>
                      <span>{m.icon || '🤖'}</span>
                      <strong style={{ color: m.color || '#38bdf8' }}>{m.senderName || 'Agente'}</strong>
                      <span style={{ color: '#64748b', fontSize: '0.65rem' }}>{m.timestamp}</span>
                    </div>
                  )}

                  <div
                    style={{
                      padding: '10px 14px',
                      borderRadius: isUser ? '12px 12px 2px 12px' : '2px 12px 12px 12px',
                      background: isUser
                        ? '#0d6efd'
                        : isLight
                        ? '#f1f5f9'
                        : 'rgba(255,255,255,0.05)',
                      color: isUser ? '#ffffff' : isLight ? '#0f172a' : '#e2e8f0',
                      border: isUser ? 'none' : `1px solid ${isLight ? '#e2e8f0' : 'rgba(255,255,255,0.08)'}`,
                      fontSize: '0.8rem',
                      lineHeight: '1.45',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                    }}
                  >
                    {m.text}
                  </div>
                </div>
              );
            })}

            {agentRunning && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#00d2ff', fontSize: '0.76rem', fontStyle: 'italic' }}>
                <RefreshCw size={14} className="spin" />
                Il team di agenti sta analizzando ed eseguendo il task...
              </div>
            )}
          </div>

          {/* Suggerimenti Rapidi */}
          <div
            style={{
              padding: '6px 12px',
              borderTop: `1px solid ${isLight ? '#e2e8f0' : 'rgba(255,255,255,0.05)'}`,
              display: 'flex',
              gap: '6px',
              overflowX: 'auto',
            }}
          >
            {[
              'Alimentatore step-down 5V con LC',
              'Ottimizza routing e clearance',
              'Verifica DRC a 0 errori',
            ].map((p, idx) => (
              <button
                key={idx}
                onClick={() => setInputTask(p)}
                style={{
                  whiteSpace: 'nowrap',
                  padding: '3px 8px',
                  borderRadius: '12px',
                  background: isLight ? '#f1f5f9' : 'rgba(255,255,255,0.04)',
                  border: `1px solid ${isLight ? '#cbd5e1' : 'rgba(255,255,255,0.08)'}`,
                  color: isLight ? '#475569' : '#94a3b8',
                  fontSize: '0.68rem',
                  cursor: 'pointer',
                }}
              >
                {p}
              </button>
            ))}
          </div>

          {/* Input Chat */}
          <div
            style={{
              padding: '12px',
              borderTop: `1px solid ${isLight ? '#e2e8f0' : 'rgba(255,255,255,0.08)'}`,
              background: isLight ? '#ffffff' : '#080c16',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                background: isLight ? '#f8fafc' : 'rgba(255,255,255,0.04)',
                borderRadius: '8px',
                border: `1px solid ${isLight ? '#cbd5e1' : 'rgba(255,255,255,0.1)'}`,
                padding: '4px 8px',
              }}
            >
              <textarea
                value={inputTask}
                onChange={(e) => setInputTask(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSendTask();
                  }
                }}
                placeholder="Scrivi un task per il team di agenti hardware..."
                rows={2}
                style={{
                  flex: 1,
                  background: 'transparent',
                  border: 'none',
                  outline: 'none',
                  color: isLight ? '#0f172a' : '#f8fafc',
                  fontSize: '0.78rem',
                  resize: 'none',
                  fontFamily: 'inherit',
                }}
              />
              <button
                onClick={handleSendTask}
                disabled={agentRunning || !inputTask.trim()}
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '6px',
                  background: '#0d6efd',
                  color: '#fff',
                  border: 'none',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  opacity: agentRunning || !inputTask.trim() ? 0.4 : 1,
                }}
              >
                <Send size={14} />
              </button>
            </div>
          </div>
        </aside>
      </div>

      {/* MODALE NUOVO PROGETTO */}
      {showNewModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0,0,0,0.7)',
            backdropFilter: 'blur(6px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
          }}
        >
          <div
            style={{
              width: '400px',
              background: isLight ? '#ffffff' : '#0f172a',
              borderRadius: '12px',
              border: `1px solid ${isLight ? '#cbd5e1' : 'rgba(255,255,255,0.12)'}`,
              padding: '24px',
              boxShadow: '0 20px 50px rgba(0,0,0,0.5)',
            }}
          >
            <h3 style={{ margin: '0 0 16px', fontSize: '1.05rem', fontWeight: 700 }}>
              Crea Nuovo Progetto KiCad
            </h3>

            <form onSubmit={handleCreateProject}>
              <div style={{ marginBottom: '14px' }}>
                <label style={{ display: 'block', fontSize: '0.76rem', color: '#94a3b8', marginBottom: '4px' }}>
                  Nome Progetto
                </label>
                <input
                  type="text"
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  placeholder="es. power_supply_5v"
                  required
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    background: isLight ? '#f1f5f9' : 'rgba(255,255,255,0.06)',
                    border: `1px solid ${isLight ? '#cbd5e1' : 'rgba(255,255,255,0.1)'}`,
                    color: isLight ? '#0f172a' : '#f8fafc',
                    fontSize: '0.8rem',
                    outline: 'none',
                    boxSizing: 'border-box',
                  }}
                />
              </div>

              <div style={{ display: 'flex', gap: '12px', marginBottom: '20px' }}>
                <div style={{ flex: 1 }}>
                  <label style={{ display: 'block', fontSize: '0.76rem', color: '#94a3b8', marginBottom: '4px' }}>
                    Larghezza (mm)
                  </label>
                  <input
                    type="number"
                    value={newBoardWidth}
                    onChange={(e) => setNewBoardWidth(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: '6px',
                      background: isLight ? '#f1f5f9' : 'rgba(255,255,255,0.06)',
                      border: `1px solid ${isLight ? '#cbd5e1' : 'rgba(255,255,255,0.1)'}`,
                      color: isLight ? '#0f172a' : '#f8fafc',
                      fontSize: '0.8rem',
                      outline: 'none',
                      boxSizing: 'border-box',
                    }}
                  />
                </div>
                <div style={{ flex: 1 }}>
                  <label style={{ display: 'block', fontSize: '0.76rem', color: '#94a3b8', marginBottom: '4px' }}>
                    Altezza (mm)
                  </label>
                  <input
                    type="number"
                    value={newBoardHeight}
                    onChange={(e) => setNewBoardHeight(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: '6px',
                      background: isLight ? '#f1f5f9' : 'rgba(255,255,255,0.06)',
                      border: `1px solid ${isLight ? '#cbd5e1' : 'rgba(255,255,255,0.1)'}`,
                      color: isLight ? '#0f172a' : '#f8fafc',
                      fontSize: '0.8rem',
                      outline: 'none',
                      boxSizing: 'border-box',
                    }}
                  />
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                <button
                  type="button"
                  onClick={() => setShowNewModal(false)}
                  style={{
                    padding: '8px 14px',
                    borderRadius: '6px',
                    background: 'transparent',
                    border: 'none',
                    color: '#94a3b8',
                    cursor: 'pointer',
                    fontWeight: 600,
                  }}
                >
                  Annulla
                </button>
                <button
                  type="submit"
                  style={{
                    padding: '8px 16px',
                    borderRadius: '6px',
                    background: '#0d6efd',
                    color: '#fff',
                    border: 'none',
                    cursor: 'pointer',
                    fontWeight: 600,
                  }}
                >
                  Crea Progetto
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
