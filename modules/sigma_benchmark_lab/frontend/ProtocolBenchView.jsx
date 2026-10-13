import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Play, CheckCircle2, XCircle, RefreshCw, StopCircle,
  Terminal, ShieldCheck, Clock, FileCode, AlertTriangle,
  FolderSearch, Activity, Check, ChevronRight, RotateCcw, Trash2,
  Trophy, Wrench, Zap, HardDrive, Cpu
} from 'lucide-react';
import {
  getModelSpecs, detectModelFamily, isSigmanihModel, getModelChatSpeed,
  FAMILY_CONFIG
} from '../../components/Chat/core/modelSpecsHelper';
import { PROVIDER_COLORS, getProviderForModel } from '../../components/Chat/modelProviderMap';

const ACCENT = '#00d2ff';
const fmt = (n) => (Number(n) || 0).toLocaleString('it-IT');

export default function ProtocolBenchView({ models = [], onToast, activeTabId, benchTab }) {
  const [scenarios, setScenarios] = useState([]);
  const [selectedScenarios, setSelectedScenarios] = useState(['file_nuovo', 'modifica_mirata']);
  const [levelFilter, setLevelFilter] = useState('all');
  const [selectedModel, setSelectedModel] = useState(null);
  const [modelSearch, setModelSearch] = useState('');
  const [speedVersion, setSpeedVersion] = useState(0);

  const [currentJob, setCurrentJob] = useState(null);
  const [history, setHistory] = useState([]);
  const [activeHistoryId, setActiveHistoryId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [launching, setLaunching] = useState(false);

  const pollRef = useRef(null);

  // Ascolta aggiornamenti live di velocità di inferenza (tokens/sec)
  useEffect(() => {
    const handleSpeedUpdated = () => setSpeedVersion((v) => v + 1);
    window.addEventListener('sigma-model-speed-updated', handleSpeedUpdated);
    return () => window.removeEventListener('sigma-model-speed-updated', handleSpeedUpdated);
  }, []);

  const toast = useCallback((msg, kind) => {
    if (onToast) onToast(msg, kind);
  }, [onToast]);

  // Risoluzione ed estetica del nome del modello: mai "test-model" o "sigma" anonimo
  const formatModelTitle = useCallback((modelName) => {
    if (!modelName) return 'Modello Assegnato';
    let m = String(modelName).trim();
    if (m.startsWith('sigma:')) m = m.substring(6);
    if (m === 'sigma' || m === 'test-model') {
      const proxyMod = models.find((item) => item.id === 'sigma' || item.is_proxy);
      if (proxyMod?.resolved_target) {
        let rt = proxyMod.resolved_target;
        if (rt.startsWith('sigma:')) rt = rt.substring(6);
        return rt;
      }
      return 'SigmaEngine (Assegnato)';
    }
    return m;
  }, [models]);

  // Carica scenari dal backend con cache-busting
  const loadScenarios = useCallback(async () => {
    try {
      const res = await fetch(`/api/benchmark/protocol/scenarios?_t=${Date.now()}`, { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      if (data.scenarios) {
        setScenarios(data.scenarios);
        setSelectedScenarios(data.scenarios.map((s) => s.id));
      }
    } catch (err) {
      console.error('Scenari protocollo non caricati:', err);
    }
  }, []);

  // Carica storico dei run con cache-busting
  const loadHistory = useCallback(async () => {
    try {
      const res = await fetch(`/api/benchmark/protocol/history?_t=${Date.now()}`, { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      const list = data.history || [];
      setHistory(list);
      if (list.length > 0 && !activeHistoryId) {
        setActiveHistoryId(list[0].id);
      }
    } catch (err) {
      console.error('Storico protocollo non caricato:', err);
    }
  }, [activeHistoryId]);

  // Controlla stato del job corrente o ultimo con cache-busting
  const pollStatus = useCallback(async (jobId) => {
    try {
      const base = jobId
        ? `/api/benchmark/protocol/status?job_id=${encodeURIComponent(jobId)}`
        : '/api/benchmark/protocol/status';
      const sep = base.includes('?') ? '&' : '?';
      const url = `${base}${sep}_t=${Date.now()}`;
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok) return null;
      const data = await res.json();
      const job = data.job;
      if (job && job.id) {
        setCurrentJob(job);
        if (job.status === 'running') {
          return true;
        }
      }
      return false;
    } catch (err) {
      console.error('Errore polling protocollo:', err);
      return false;
    }
  }, []);

  // Inizializzazione
  useEffect(() => {
    loadScenarios();
    loadHistory();
    pollStatus();
  }, [loadScenarios, loadHistory, pollStatus]);

  // Ricarica immediata all'apertura tab o al cambio modalità
  useEffect(() => {
    if (benchTab === 'protocol' || activeTabId === 'benchmark') {
      loadHistory();
      pollStatus();
      loadScenarios();
    }
  }, [benchTab, activeTabId, loadHistory, pollStatus, loadScenarios]);

  // Aggiornamento immediato al focus della finestra o visibilitychange
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        loadHistory();
        pollStatus();
      }
    };
    window.addEventListener('focus', handleVisibility);
    document.addEventListener('visibilitychange', handleVisibility);
    return () => {
      window.removeEventListener('focus', handleVisibility);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [loadHistory, pollStatus]);

  // Polling continuo di background ogni 4s per mantenere lo storico sempre aggiornato
  useEffect(() => {
    const bgTimer = setInterval(() => {
      loadHistory();
      if (!currentJob || currentJob.status !== 'running') {
        pollStatus();
      }
    }, 4000);
    return () => clearInterval(bgTimer);
  }, [loadHistory, pollStatus, currentJob]);

  // Imposta modello predefinito
  useEffect(() => {
    if (!selectedModel && models.length > 0) {
      setSelectedModel(models[0].id);
    }
  }, [models, selectedModel]);

  // Polling ad alta frequenza (1.5s) quando c'è un job attivo
  useEffect(() => {
    if (currentJob && currentJob.status === 'running') {
      pollRef.current = setInterval(async () => {
        const stillRunning = await pollStatus(currentJob.id);
        if (!stillRunning) {
          clearInterval(pollRef.current);
          loadHistory();
        }
      }, 1500);
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [currentJob, pollStatus, loadHistory]);

  const handleStartRun = async () => {
    if (!selectedModel) {
      toast('Seleziona prima un modello da collaudare', 'warning');
      return;
    }
    if (selectedScenarios.length === 0) {
      toast('Seleziona almeno uno scenario di test', 'warning');
      return;
    }
    setLaunching(true);
    try {
      const res = await fetch('/api/benchmark/protocol/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: selectedModel,
          scenarios: selectedScenarios,
        }),
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        toast(`❌ ${data.error || 'Errore avvio test'}`, 'error');
        return;
      }
      toast(`🚀 Test di aderenza protocollo avviato su '${selectedModel}'`, 'success');
      await pollStatus(data.job_id);
      setActiveHistoryId(data.job_id);
    } catch (err) {
      toast(`❌ Errore di rete: ${err.message}`, 'error');
    } finally {
      setLaunching(false);
    }
  };

  const handleCancelRun = async () => {
    if (!currentJob || currentJob.status !== 'running') return;
    try {
      const res = await fetch('/api/benchmark/protocol/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: currentJob.id }),
      });
      const data = await res.json();
      if (data.success) {
        toast('🛑 Richiesta annullamento inviata', 'info');
        pollStatus(currentJob.id);
      }
    } catch (err) {
      toast(`❌ ${err.message}`, 'error');
    }
  };

  const handleDeleteHistory = async (e, id) => {
    e.stopPropagation();
    try {
      const res = await fetch('/api/benchmark/protocol/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id }),
      });
      const data = await res.json();
      if (data.success) {
        toast('🗑️ Test eliminato dallo storico', 'info');
        setHistory((prev) => {
          const next = prev.filter((h) => h.id !== id);
          if (activeHistoryId === id) {
            setActiveHistoryId(next.length > 0 ? next[0].id : null);
          }
          return next;
        });
      } else {
        toast(`❌ Errore eliminazione: ${data.error || 'Operazione fallita'}`, 'error');
      }
    } catch (err) {
      toast(`❌ Errore di rete: ${err.message}`, 'error');
    }
  };

  const handleRerun = (e, h) => {
    e.stopPropagation();
    if (!h) return;
    if (h.model) setSelectedModel(h.model);
    if (h.scenarios_planned && Array.isArray(h.scenarios_planned) && h.scenarios_planned.length > 0) {
      setSelectedScenarios(h.scenarios_planned);
    } else if (h.results?.scenari && Array.isArray(h.results.scenari)) {
      setSelectedScenarios(h.results.scenari.map((s) => s.id));
    }
    toast(`🔄 Parametri ripristinati per '${h.model}'. Clicca "Avvia Test Protocollo" per rieseguire`, 'info');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };


  const toggleScenario = (scId) => {
    setSelectedScenarios((prev) => (
      prev.includes(scId)
        ? prev.filter((id) => id !== scId)
        : [...prev, scId]
    ));
  };

  const isRunning = currentJob?.status === 'running';

  // Dati da visualizzare (quelli del job attivo se in esecuzione, altrimenti la voce di storico selezionata)
  const displayedRun = isRunning
    ? currentJob
    : (history.find((h) => h.id === activeHistoryId) || currentJob);

  const results = displayedRun?.results;
  const isCompleted = displayedRun?.status === 'completed' || displayedRun?.status === 'cancelled';

  // Filtra modelli per ricerca senza troncare
  const filteredModels = models.filter((m) => {
    const q = modelSearch.trim().toLowerCase();
    if (!q) return true;
    return `${m.name} ${m.id} ${m.family || ''} ${m.parameter_size || ''}`.toLowerCase().includes(q);
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {/* Box Introduttivo sulla Ragione del Test */}
      <div className="bench-card" style={{ background: 'rgba(0, 210, 255, 0.05)', borderColor: 'rgba(0, 210, 255, 0.25)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px' }}>
          <ShieldCheck size={22} color={ACCENT} style={{ flexShrink: 0, marginTop: '2px' }} />
          <div>
            <div style={{ fontSize: '0.86rem', fontWeight: 800, color: '#fff' }}>
              Misura della Pilotabilità Reale (Harness Protocol Benchmark)
            </div>
            <div style={{ fontSize: '0.74rem', color: 'var(--sigma-text-dim, #8b949e)', marginTop: '4px', lineHeight: '1.4' }}>
              Questo banco misura se il modello è <i>pilotabile</i> dentro il ciclo di Sigma Studio attraverso prove graduate (Livello 1 Base, Livello 2 Intermedio, Livello 3 Avanzato).
              <br />
              <span style={{ color: '#3fb950', fontWeight: 700 }}>🛡️ SandboxJail Attiva:</span> Ogni scenario gira in una sandbox temporanea isolata con confinamento dei percorsi e blocco modifiche al kernel. Sicuro al 100% per qualsiasi modello.
            </div>
          </div>
        </div>
      </div>

      {/* Configurazione & Lancio */}
      <div className="bench-card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
          <div style={{ fontSize: '0.85rem', fontWeight: 800, color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Activity size={16} color={ACCENT} /> Configura & Avvia Prova di Aderenza
          </div>
          <button
            onClick={() => { loadScenarios(); loadHistory(); pollStatus(); }}
            style={{
              background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: '8px', padding: '5px 12px', color: '#fff', cursor: 'pointer',
              fontSize: '0.72rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px',
            }}
          >
            <RefreshCw size={13} /> Aggiorna
          </button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 1.3fr) minmax(300px, 1fr)', gap: '14px' }}>
          {/* Selettore Modello Senza Troncature */}
          <div className="bench-panel" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div style={{ fontSize: '0.72rem', fontWeight: 700, color: '#8b949e', textTransform: 'uppercase' }}>
              1. Modello da Collaudare
            </div>
            <input
              type="text"
              placeholder="Filtra modelli disponibili..."
              value={modelSearch}
              onChange={(e) => setModelSearch(e.target.value)}
              style={{
                background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: '8px', padding: '6px 10px', color: '#fff', fontSize: '0.75rem', width: '100%',
              }}
            />
            <div style={{ maxHeight: '260px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '5px', paddingRight: '4px' }}>
              {filteredModels.map((m) => {
                const isSelected = selectedModel === m.id;
                const itemSpecs = getModelSpecs(m, models);
                const isSig = isSigmanihModel(m);
                const famKey = detectModelFamily(m);
                const familyConf = FAMILY_CONFIG[famKey] || FAMILY_CONFIG.altro;
                const providerKey = m.provider || getProviderForModel(m.name || m.id, {}) || 'sigma_engine';
                const colors = PROVIDER_COLORS[providerKey] || PROVIDER_COLORS[m.provider_label] || PROVIDER_COLORS.ollama;

                // Metriche di Benchmark
                const bm = m.benchmark_summary || itemSpecs?.benchmark || null;
                const hasBm = Boolean(bm && (bm.has_benchmarks || bm.score !== undefined || bm.overall_pass_rate !== undefined));
                const bmScore = hasBm ? (bm.score ?? bm.overall_pass_rate ?? bm.best_score ?? 0) : null;
                const bmColor = bmScore !== null ? (bmScore >= 75 ? '#10b981' : (bmScore >= 50 ? '#00d2ff' : '#ffb86c')) : '#8b949e';

                // Metriche Tool Benchmark (Wrench)
                const tScore = m.tool_score ?? bm?.tool_score ?? itemSpecs?.toolScore ?? null;
                const hasTool = Boolean(tScore !== null && tScore !== undefined);
                const toolPassed = m.tool_passed ?? bm?.tool_passed ?? itemSpecs?.toolStats?.passed ?? 0;
                const toolTotal = m.tool_total ?? bm?.tool_total ?? itemSpecs?.toolStats?.total ?? 0;
                const toolColor = tScore !== null ? (tScore >= 75 ? '#10b981' : (tScore >= 50 ? '#00d2ff' : '#ffb86c')) : '#8b949e';

                // Velocità live tokens/sec
                const chatTps = getModelChatSpeed(m.name || m.id, m) ?? (m.benchmark_summary?.tokens_per_sec || null);
                const params = itemSpecs?.params || m.parameter_size;
                const quant = itemSpecs?.quantization || m.quantization;
                const size = itemSpecs?.size || (m.size_gb ? `~${m.size_gb.toFixed(1)} GB` : null);

                return (
                  <div
                    key={m.id}
                    onClick={() => setSelectedModel(m.id)}
                    style={{
                      padding: '8px 10px', borderRadius: '8px', cursor: 'pointer',
                      background: isSelected ? 'rgba(0, 210, 255, 0.16)' : 'rgba(255,255,255,0.03)',
                      border: `1px solid ${isSelected ? ACCENT : 'rgba(255,255,255,0.06)'}`,
                      display: 'flex', flexDirection: 'column', gap: '5px',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    {/* Riga 1: Provider dot + Badge Sigmanih + Famiglia + Nome + Check */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', minWidth: 0, flex: 1 }}>
                        <span
                          style={{
                            width: '7px', height: '7px', borderRadius: '50%',
                            backgroundColor: colors.color || '#00d2ff', flexShrink: 0
                          }}
                          title={`Provider: ${m.provider_label || m.provider || 'locale'}`}
                        />

                        {isSig && (
                          <span
                            title="Modello Sigmanih Ecosystem"
                            style={{
                              fontSize: '0.55rem', fontWeight: 800, padding: '1px 5px', borderRadius: '4px',
                              background: 'rgba(255, 184, 108, 0.15)', border: '1px solid rgba(255, 184, 108, 0.35)',
                              color: '#ffb86c', flexShrink: 0
                            }}
                          >
                            Sigmanih
                          </span>
                        )}

                        {famKey && famKey !== 'altro' && famKey !== 'sigmanih' && (
                          <span
                            title={`Famiglia architetturale: ${familyConf.title}`}
                            style={{
                              fontSize: '0.55rem', fontWeight: 800, padding: '1px 5px', borderRadius: '4px',
                              background: familyConf.bg, border: `1px solid ${familyConf.border}`,
                              color: familyConf.color, flexShrink: 0
                            }}
                          >
                            {familyConf.title}
                          </span>
                        )}

                        <div className="bench-model-name" style={{ color: isSelected ? '#00f2fe' : '#fff', fontSize: '0.80rem' }}>
                          {m.name || m.id}
                        </div>
                      </div>

                      {isSelected && <Check size={13} color="#00f2fe" style={{ flexShrink: 0 }} />}
                    </div>

                    {/* Riga 2: Statistiche e Caratteristiche identiche alla Chat */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '5px', flexWrap: 'wrap', fontSize: '0.62rem' }}>
                      {/* 🏆 Benchmark Badge */}
                      <span
                        title={hasBm
                          ? `Valutazione Benchmark: ${Math.round(bmScore)}% ${bm?.tests_total ? `(${bm.tests_passed || 0}/${bm.tests_total} quesiti superati)` : ''}`
                          : 'Nessun benchmark registrato per questo modello'
                        }
                        style={{
                          fontSize: '0.58rem', fontWeight: 800, padding: '1px 5px', borderRadius: '4px',
                          background: hasBm ? `${bmColor}18` : 'rgba(255, 255, 255, 0.04)',
                          border: hasBm ? `1px solid ${bmColor}40` : '1px solid rgba(255, 255, 255, 0.08)',
                          color: bmColor,
                          display: 'inline-flex', alignItems: 'center', gap: '3px'
                        }}
                      >
                        <Trophy size={10} color={bmColor} />
                        <span>{hasBm ? `${Math.round(bmScore)}%` : '-'}</span>
                      </span>

                      {/* 🔧 Tool Benchmark Badge */}
                      <span
                        title={hasTool
                          ? `Benchmark Tools (Aderenza Protocollo & Tool Use): ${Math.round(tScore)}%${toolTotal ? ` (${toolPassed}/${toolTotal} prove superate)` : ''}`
                          : 'Nessun benchmark tools registrato per questo modello'
                        }
                        style={{
                          fontSize: '0.58rem', fontWeight: 800, padding: '1px 5px', borderRadius: '4px',
                          background: hasTool ? `${toolColor}18` : 'rgba(255, 255, 255, 0.04)',
                          border: hasTool ? `1px solid ${toolColor}40` : '1px solid rgba(255, 255, 255, 0.08)',
                          color: toolColor,
                          display: 'inline-flex', alignItems: 'center', gap: '3px'
                        }}
                      >
                        <Wrench size={10} color={toolColor} />
                        <span>{hasTool ? `${Math.round(tScore)}%` : '-'}</span>
                      </span>

                      {/* ⚡ Live Speed t/s Badge */}
                      <span
                        title={chatTps !== null
                          ? `Velocità inferenza registrata: ${chatTps} token/secondo`
                          : 'Nessuna misurazione live disponibile finché non viene eseguita inferenza.'
                        }
                        style={{
                          fontSize: '0.58rem', fontWeight: 800, padding: '1px 5px', borderRadius: '4px',
                          background: chatTps !== null ? 'rgba(0, 210, 255, 0.14)' : 'rgba(255, 255, 255, 0.04)',
                          border: chatTps !== null ? '1px solid rgba(0, 210, 255, 0.35)' : '1px solid rgba(255, 255, 255, 0.08)',
                          color: chatTps !== null ? '#00d2ff' : '#8b949e',
                          display: 'inline-flex', alignItems: 'center', gap: '2px'
                        }}
                      >
                        <Zap size={9} color={chatTps !== null ? '#00d2ff' : '#8b949e'} />
                        <span>{chatTps !== null ? `${chatTps} t/s` : '-'}</span>
                      </span>

                      {/* Parametri */}
                      {params && (
                        <span style={{
                          fontSize: '0.58rem', padding: '1px 5px', borderRadius: '4px',
                          background: 'rgba(0, 210, 255, 0.12)', color: '#00d2ff', fontWeight: 800
                        }}>
                          {params}
                        </span>
                      )}

                      {/* Quantizzazione */}
                      {quant && (
                        <span style={{
                          fontSize: '0.58rem', padding: '1px 5px', borderRadius: '4px',
                          background: 'rgba(168, 85, 247, 0.14)', color: '#c084fc',
                          border: '1px solid rgba(168, 85, 247, 0.3)', fontWeight: 700
                        }}>
                          {quant}
                        </span>
                      )}

                      {/* Dimensione / VRAM */}
                      {size && (
                        <span style={{
                          fontSize: '0.58rem', padding: '1px 5px', borderRadius: '4px',
                          background: 'rgba(255, 184, 108, 0.12)', color: '#ffb86c', fontWeight: 800
                        }}>
                          {size}
                        </span>
                      )}

                      {/* Provider Badge */}
                      <span style={{
                        fontSize: '0.55rem', fontWeight: 700, padding: '1px 5px', borderRadius: '4px',
                        backgroundColor: colors.bg || 'rgba(255,255,255,0.06)',
                        color: colors.color || '#fff', marginLeft: 'auto'
                      }}>
                        {m.provider === 'sigma_engine' ? 'SIGMA' : (m.provider_label || m.provider || 'locale')}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Selezione Scenari con Livelli e SandboxJail */}
          <div className="bench-panel" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '6px' }}>
              <div style={{ fontSize: '0.72rem', fontWeight: 700, color: '#8b949e', textTransform: 'uppercase' }}>
                2. Scenari di Prova ({selectedScenarios.length}/{scenarios.length} · {selectedScenarios.length * 11} prove)
              </div>
              <div style={{ display: 'flex', gap: '4px' }}>
                <button
                  type="button"
                  onClick={() => setSelectedScenarios(scenarios.map((s) => s.id))}
                  style={{ background: 'none', border: 'none', color: ACCENT, fontSize: '0.64rem', cursor: 'pointer', fontWeight: 700 }}
                >
                  Tutti ({scenarios.length * 11} prove)
                </button>
                <span style={{ color: '#8b949e', fontSize: '0.64rem' }}>·</span>
                <button
                  type="button"
                  onClick={() => setSelectedScenarios([])}
                  style={{ background: 'none', border: 'none', color: '#8b949e', fontSize: '0.64rem', cursor: 'pointer', fontWeight: 700 }}
                >
                  Nessuno
                </button>
              </div>
            </div>

            {/* Pulsanti Preset Rapidi per Suite e Livello */}
            <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
              <button
                type="button"
                onClick={() => setSelectedScenarios(scenarios.map((s) => s.id))}
                title="Seleziona l'intera suite di benchmark (tutti i livelli)"
                style={{
                  fontSize: '0.64rem', fontWeight: 800, padding: '2px 8px', borderRadius: '5px', cursor: 'pointer',
                  border: `1px solid ${selectedScenarios.length === scenarios.length && scenarios.length > 0 ? ACCENT : 'rgba(0,210,255,0.3)'}`,
                  background: selectedScenarios.length === scenarios.length && scenarios.length > 0 ? 'rgba(0,210,255,0.22)' : 'rgba(0,210,255,0.06)',
                  color: selectedScenarios.length === scenarios.length && scenarios.length > 0 ? '#00f2fe' : ACCENT,
                }}
              >
                🚀 Suite Completa ({scenarios.length * 11} Prove)
              </button>
              {[
                { id: '1', label: '🟢 Liv. 1 (22 Prove)', val: 1 },
                { id: '2', label: '🟡 Liv. 2 (22 Prove)', val: 2 },
                { id: '3', label: '🔴 Liv. 3 (22 Prove)', val: 3 },
              ].map((lvl) => {
                const lvlScenarios = scenarios.filter((s) => s.livello === lvl.val).map((s) => s.id);
                const allSelected = lvlScenarios.length > 0 && lvlScenarios.every((id) => selectedScenarios.includes(id));
                return (
                  <button
                    key={lvl.id}
                    type="button"
                    onClick={() => {
                      setLevelFilter(lvl.id);
                      setSelectedScenarios(lvlScenarios);
                    }}
                    title={`Imposta ed esegui solo gli scenari di ${lvl.label}`}
                    style={{
                      fontSize: '0.62rem', fontWeight: 700, padding: '2px 6px', borderRadius: '5px', cursor: 'pointer',
                      border: `1px solid ${allSelected ? ACCENT : 'rgba(255,255,255,0.08)'}`,
                      background: allSelected ? 'rgba(0,210,255,0.14)' : 'rgba(255,255,255,0.02)',
                      color: allSelected ? '#00f2fe' : '#8b949e',
                    }}
                  >
                    {lvl.label}
                  </button>
                );
              })}
            </div>


            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '180px', overflowY: 'auto', paddingRight: '4px' }}>
              {scenarios
                .filter((sc) => levelFilter === 'all' || String(sc.livello) === String(levelFilter))
                .map((sc) => {
                  const active = selectedScenarios.includes(sc.id);
                  const lvlColor = sc.livello === 1 ? '#3fb950' : sc.livello === 2 ? '#ffb86c' : '#ff5555';
                  return (
                    <div
                      key={sc.id}
                      onClick={() => toggleScenario(sc.id)}
                      style={{
                        padding: '8px 10px', borderRadius: '8px', cursor: 'pointer',
                        background: active ? 'rgba(0, 210, 255, 0.12)' : 'rgba(255,255,255,0.02)',
                        border: `1px solid ${active ? 'rgba(0, 210, 255, 0.35)' : 'rgba(255,255,255,0.06)'}`,
                        display: 'flex', alignItems: 'flex-start', gap: '8px',
                      }}
                    >
                      <div style={{
                        width: '16px', height: '16px', borderRadius: '4px', marginTop: '2px',
                        background: active ? ACCENT : 'rgba(255,255,255,0.1)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                      }}>
                        {active && <Check size={11} color="#000" strokeWidth={3} />}
                      </div>
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                          <span style={{ fontSize: '0.78rem', fontWeight: 700, color: '#fff', wordBreak: 'break-word' }}>
                            {sc.id} — {sc.descrizione}
                          </span>
                          <span style={{
                            fontSize: '0.58rem', fontWeight: 800, padding: '1px 5px', borderRadius: '4px',
                            background: `${lvlColor}22`, color: lvlColor, border: `1px solid ${lvlColor}44`,
                          }}>
                            {sc.livello_label || `Liv. ${sc.livello}`}
                          </span>
                        </div>
                        <div style={{ fontSize: '0.68rem', color: '#8b949e', marginTop: '2px', wordBreak: 'break-word' }}>
                          {sc.obiettivo}
                        </div>
                        <div style={{ fontSize: '0.64rem', color: '#ffb86c', marginTop: '2px', fontFamily: 'monospace' }}>
                          Verifica: {sc.verifica}
                        </div>
                      </div>
                    </div>
                  );
                })}
            </div>
          </div>
        </div>

        {/* Barra di Comando Esecuzione */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px',
          padding: '10px 14px', background: 'rgba(0,0,0,0.3)', borderRadius: '10px',
          border: '1px solid rgba(255,255,255,0.06)',
        }}>
          <div style={{ fontSize: '0.76rem', color: '#8b949e', display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <span>Modello: <strong style={{ color: '#fff' }}>{selectedModel || 'Nessuno'}</strong></span>
            <span>•</span>
            <span>Scenari: <strong style={{ color: '#fff' }}>{selectedScenarios.length}/{scenarios.length}</strong></span>
            <span>•</span>
            <span>Prove Pianificate: <strong style={{ color: '#00f2fe' }}>{selectedScenarios.length * 11} prove</strong></span>
            <span>•</span>
            <span>Tetto per scenario: <strong style={{ color: '#ffb86c' }}>300 s / 14 turni</strong></span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {isRunning ? (
              <button
                onClick={handleCancelRun}
                style={{
                  padding: '8px 18px', borderRadius: '8px', border: 'none',
                  background: 'linear-gradient(135deg, #ff5555 0%, #cc3333 100%)',
                  color: '#fff', fontWeight: 700, fontSize: '0.78rem', cursor: 'pointer',
                  display: 'flex', alignItems: 'center', gap: '6px',
                }}
              >
                <StopCircle size={15} /> Ferma Test
              </button>
            ) : (
              <button
                onClick={handleStartRun}
                disabled={launching || !selectedModel || selectedScenarios.length === 0}
                style={{
                  padding: '8px 22px', borderRadius: '8px', border: 'none',
                  background: (selectedModel && selectedScenarios.length > 0)
                    ? 'linear-gradient(135deg, #00d2ff 0%, #0072ff 100%)'
                    : 'rgba(255,255,255,0.1)',
                  color: '#fff', fontWeight: 700, fontSize: '0.78rem',
                  cursor: (selectedModel && selectedScenarios.length > 0) ? 'pointer' : 'not-allowed',
                  display: 'flex', alignItems: 'center', gap: '6px',
                  boxShadow: (selectedModel && selectedScenarios.length > 0) ? '0 0 16px rgba(0,210,255,0.3)' : 'none',
                }}
              >
                {launching ? <RefreshCw size={15} className="spin-icon" /> : <Play size={15} />}
                Avvia Test Protocollo
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Sezione Split: Storico Run a sinistra, Risultati Dettagliati a destra */}
      <div className="bench-grid-split">
        {/* Colonna Sinistra: Storico Prove */}
        <div className="bench-card" style={{ maxHeight: '720px', overflowY: 'auto' }}>
          <div style={{ fontSize: '0.82rem', fontWeight: 800, color: '#fff', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Clock size={15} color={ACCENT} /> Storico Prove Protocollo ({history.length})
          </div>

          {history.length === 0 && !isRunning ? (
            <div style={{ padding: '24px 10px', textAlign: 'center', color: '#8b949e', fontSize: '0.75rem' }}>
              Nessun test eseguito finora. Seleziona un modello e avvia la prima prova.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {isRunning && currentJob && (
                <div style={{
                  padding: '10px 12px', borderRadius: '8px', background: 'rgba(0,210,255,0.12)',
                  border: '1px solid rgba(0,210,255,0.4)', display: 'flex', flexDirection: 'column', gap: '6px',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span className="proto-badge ok" style={{ background: 'rgba(0,210,255,0.2)', color: '#00f2fe', borderColor: 'rgba(0,210,255,0.4)' }}>
                      ⚡ IN CORSO ({currentJob.progress}%)
                    </span>
                    <span style={{ fontSize: '0.68rem', color: '#8b949e' }}>
                      Scenario {currentJob.current_index}/{currentJob.total_scenarios}
                    </span>
                  </div>
                  <div className="bench-model-name" style={{ color: '#fff' }}>
                    {formatModelTitle(currentJob.model)}
                  </div>
                  <div style={{ fontSize: '0.7rem', color: '#00f2fe' }}>
                    {currentJob.message}
                  </div>
                  {/* Progress Bar */}
                  <div style={{ width: '100%', height: '4px', background: 'rgba(255,255,255,0.1)', borderRadius: '2px', overflow: 'hidden' }}>
                    <div style={{ width: `${currentJob.progress || 10}%`, height: '100%', background: ACCENT, transition: 'width 0.3s' }} />
                  </div>
                </div>
              )}

              {history.map((h) => {
                const isSelected = activeHistoryId === h.id;
                const score = h.results?.punteggio ?? null;
                const statusColor = h.status === 'completed'
                  ? (score >= 90 ? 'var(--success, #3fb950)' : score >= 60 ? '#ffb86c' : '#ff5555')
                  : '#8b949e';

                return (
                  <div
                    key={h.id}
                    onClick={() => setActiveHistoryId(h.id)}
                    className={`proto-history-item ${isSelected ? 'selected' : ''}`}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
                      <div className="bench-model-name" style={{ color: isSelected ? '#00f2fe' : '#fff' }}>
                        {formatModelTitle(h.model)}
                      </div>
                      {score !== null && (
                        <div style={{ fontSize: '0.88rem', fontWeight: 900, color: statusColor, flexShrink: 0 }}>
                          {score}/100
                        </div>
                      )}
                    </div>
                    <div style={{ fontSize: '0.68rem', color: '#8b949e', display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '4px' }}>
                      <span>{new Date(h.created_at).toLocaleTimeString('it-IT')}</span>
                      <span>
                        {h.results
                          ? `${h.results.superate}/${h.results.totali} prove (${h.results.scenari?.length || Math.round((h.results.totali || 11) / 11)} scenari) · ${h.results.turni_totali} turni`
                          : h.status}
                      </span>
                    </div>

                    {/* Azioni: Riesegui ed Elimina */}
                    <div className="proto-history-actions">
                      <button
                        type="button"
                        onClick={(e) => handleRerun(e, h)}
                        className="proto-history-btn"
                        title={`Ripristina parametri e risollecita il test per ${formatModelTitle(h.model)}`}
                      >
                        <RotateCcw size={10} /> Riesegui
                      </button>
                      <button
                        type="button"
                        onClick={(e) => handleDeleteHistory(e, h.id)}
                        className="proto-history-btn danger"
                        title="Elimina definitivamente questa valutazione"
                        style={{ marginLeft: 'auto' }}
                      >
                        <Trash2 size={11} /> Elimina
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Colonna Destra: Dettaglio Risultati & 10 Prove */}
        <div className="bench-card" style={{ minHeight: '500px' }}>
          {!displayedRun ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '350px', color: '#8b949e', gap: '10px' }}>
              <FolderSearch size={40} style={{ opacity: 0.3 }} />
              <div style={{ fontSize: '0.88rem' }}>Seleziona una prova per ispezionare la scorecard completa</div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {/* Header Risultato */}
              <div style={{
                padding: '12px 16px', background: 'rgba(10, 12, 26, 0.85)', borderRadius: '10px',
                border: '1px solid rgba(0, 210, 255, 0.25)', display: 'flex', justifyContent: 'space-between',
                alignItems: 'center', flexWrap: 'wrap', gap: '12px',
              }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                    <div style={{ fontSize: '1.05rem', fontWeight: 800, color: '#fff' }} className="bench-full-title">
                      {formatModelTitle(displayedRun.model)}
                    </div>
                    <span className={`proto-badge ${displayedRun.status === 'completed' ? 'ok' : 'ko'}`}>
                      {displayedRun.status === 'completed' ? 'COMPLETATO' : displayedRun.status.toUpperCase()}
                    </span>
                  </div>
                  <div style={{ fontSize: '0.7rem', color: '#8b949e', marginTop: '3px' }}>
                    Avviato: {new Date(displayedRun.created_at).toLocaleString('it-IT')}
                    {displayedRun.finished_at && ` · Durata: ${Math.round((new Date(displayedRun.finished_at) - new Date(displayedRun.created_at)) / 1000)}s`}
                  </div>
                </div>

                {results && (
                  <div style={{ textAlign: 'right' }}>
                    <div style={{
                      fontSize: '1.6rem', fontWeight: 900,
                      color: results.punteggio >= 90 ? 'var(--success, #3fb950)' : results.punteggio >= 60 ? '#ffb86c' : '#ff5555',
                    }}>
                      {results.punteggio}<span style={{ fontSize: '0.9rem', color: '#8b949e' }}>/100</span>
                    </div>
                    <div style={{ fontSize: '0.7rem', color: '#8b949e' }}>
                      {results.superate}/{results.totali} prove · {results.turni_totali} turni totali
                    </div>
                  </div>
                )}
              </div>

              {/* Riferimento SIGMA-CHECK per Audit */}
              {results?.check_line && (
                <div className="proto-check-line">
                  {results.check_line}
                </div>
              )}

              {/* Dettaglio Scenari e Prove */}
              {results?.scenari && results.scenari.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {results.scenari.map((sc) => {
                    const isAllOk = sc.superate === sc.totali;
                    return (
                      <div key={sc.scenario} className="proto-score-card">
                        <div className="proto-scenario-header">
                          <div>
                            <div className="proto-scenario-title">
                              Scenario: <span style={{ color: ACCENT }}>{sc.scenario}</span>
                            </div>
                            <div style={{ fontSize: '0.7rem', color: '#8b949e', marginTop: '2px' }}>
                              {sc.superate}/{sc.totali} prove superate · {sc.turni} turni · {sc.secondi}s
                              {sc.scaduto && <span style={{ color: '#ff5555', fontWeight: 700 }}> (SCADUTO PER TIMEOUT)</span>}
                            </div>
                          </div>
                          <span className={`proto-badge ${isAllOk ? 'ok' : 'ko'}`}>
                            {isAllOk ? 'TUTTO OK' : `${sc.totali - sc.superate} ERRORI`}
                          </span>
                        </div>

                        {sc.errore && (
                          <div style={{ fontSize: '0.72rem', color: '#ff5555', background: 'rgba(255,85,85,0.08)', padding: '6px 10px', borderRadius: '6px' }}>
                            ⚠️ {sc.errore}
                          </div>
                        )}

                        {/* Sandbox Conservata per Fallimento */}
                        {sc.sandbox && (
                          <div className="proto-sandbox-box">
                            📁 Sandbox conservata per analisi errori: <b>{sc.sandbox}</b>
                          </div>
                        )}

                        {/* Elenco 10 Prove */}
                        <div className="proto-prove-list">
                          {sc.prove.map((p) => (
                            <div key={p.id} className={`proto-prova-item ${p.superata ? 'ok' : 'ko'}`}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
                                {p.superata
                                  ? <CheckCircle2 size={15} color="var(--success, #3fb950)" />
                                  : <XCircle size={15} color="#ff5555" />}
                                <span className="proto-prova-id">{p.id}</span>
                              </div>
                              <div className="proto-prova-desc">
                                <div>{p.descrizione}</div>
                                {p.dettaglio && (
                                  <div className="proto-prova-detail">
                                    ← {p.dettaglio}
                                  </div>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : null}

              {/* Log Eventi del Run */}
              {displayedRun.logs && displayedRun.logs.length > 0 && (
                <div className="bench-panel" style={{ marginTop: '6px' }}>
                  <div style={{ fontSize: '0.72rem', fontWeight: 700, color: '#8b949e', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <Terminal size={13} color={ACCENT} /> Registro Esecuzione
                  </div>
                  <div style={{
                    maxHeight: '160px', overflowY: 'auto', fontFamily: 'monospace', fontSize: '0.68rem',
                    color: '#c9d1d9', display: 'flex', flexDirection: 'column', gap: '3px',
                  }}>
                    {displayedRun.logs.map((logLine, idx) => (
                      <div key={idx} style={{ wordBreak: 'break-all' }}>{logLine}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
