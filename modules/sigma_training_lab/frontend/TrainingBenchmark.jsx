import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Play, CheckCircle2, XCircle, Trash2, Cpu,
  Award, RefreshCw, Shield, Download, Check, StopCircle, Search,
  RotateCcw, Layers, Compass, AlertTriangle, HelpCircle, Database, Terminal,
  Zap, ChevronDown, Sparkles, CheckSquare, Square, Globe,
} from 'lucide-react';

const SUITE_LABELS = {
  all: { name: '🌐 Tutti i Benchmark', badge: 'FULL 100%', category: 'Generale' },
  mmlu: { name: '🏆 MMLU', badge: '57 Materie', category: 'Conoscenza Generale' },
  mmlu_pro: { name: '🧠 MMLU-Pro', badge: 'Ragionamento Hard', category: 'Ragionamento Avanzato' },
  gsm8k: { name: '🧮 GSM8K', badge: 'Math', category: 'Matematica & Logica' },
  math: { name: '📐 MATH', badge: 'Olimpico', category: 'Matematica Avanzata' },
  humaneval: { name: '💻 HumanEval', badge: 'pass@1', category: 'Coding & Programmazione' },
  mbpp: { name: '🐍 MBPP', badge: 'pass@1', category: 'Coding Python' },
  arc: { name: '🔬 ARC Science', badge: 'Scienze', category: 'Scienze Applicate' },
  hellaswag: { name: '💡 HellaSwag', badge: 'Buon Senso', category: 'Buon Senso' },
  truthfulqa: { name: '🛡️ TruthfulQA', badge: 'Anti-Allucinazione', category: 'Veridicità & Safety' },
  gpqa: { name: '🎓 GPQA', badge: 'Expert Level', category: 'Livello Accademico' },
  bbh: { name: '⚙️ BIG-Bench Hard', badge: '27 Task', category: 'Logica Multi-Step' },
};

const SUITE_ORDER = ['all', 'mmlu', 'mmlu_pro', 'gsm8k', 'math', 'humaneval', 'mbpp',
  'arc', 'hellaswag', 'truthfulqa', 'gpqa', 'bbh'];

const ACTIVE_STATUSES = ['running', 'loading_model', 'preparing', 'paused', 'cancelling', 'executing'];

const VERDICT_STYLE = {
  pass: { label: 'PASS', color: 'var(--success, #3fb950)', bg: 'rgba(63,185,80,0.12)', border: 'rgba(63,185,80,0.4)', Icon: CheckCircle2 },
  fail: { label: 'FAIL', color: '#ff5555', bg: 'rgba(255,85,85,0.12)', border: 'rgba(255,85,85,0.4)', Icon: XCircle },
  ambiguous: { label: 'RISPOSTA DUPLICE', color: '#ffb86c', bg: 'rgba(255,184,108,0.12)', border: 'rgba(255,184,108,0.45)', Icon: AlertTriangle },
  unparsable: { label: 'NON INTERPRETABILE', color: '#bc8cff', bg: 'rgba(188,140,255,0.12)', border: 'rgba(188,140,255,0.45)', Icon: HelpCircle },
  error: { label: 'ERRORE MODELLO', color: '#8b949e', bg: 'rgba(139,148,158,0.12)', border: 'rgba(139,148,158,0.4)', Icon: StopCircle },
};

const CONFIDENCE_LABEL = { high: 'alta', medium: 'media', low: 'bassa', none: '—' };

const ACCENT = '#00d2ff';
const fmt = (n) => (Number(n) || 0).toLocaleString('it-IT');

const card = {
  background: 'rgba(15,18,35,0.65)',
  border: '1px solid var(--border, rgba(255,255,255,0.1))',
  borderRadius: '16px',
  padding: '20px',
  backdropFilter: 'blur(12px)',
};

const panel = {
  background: 'rgba(10,12,26,0.65)',
  border: '1px solid var(--border, rgba(255,255,255,0.08))',
  borderRadius: '12px',
  padding: '14px',
};

const btn = (active, accent = ACCENT) => ({
  padding: '5px 12px',
  borderRadius: '8px',
  fontSize: '0.72rem',
  fontWeight: 600,
  cursor: 'pointer',
  background: active ? `${accent}2b` : 'rgba(255,255,255,0.05)',
  color: active ? accent : 'var(--text-dark, #8b949e)',
  border: `1px solid ${active ? accent : 'rgba(255,255,255,0.08)'}`,
  transition: 'all 0.15s ease',
});

const sectionTitle = {
  fontSize: '0.72rem',
  fontWeight: 700,
  color: 'var(--text-dark, #8b949e)',
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
  display: 'flex',
  alignItems: 'center',
  gap: '6px',
  marginBottom: '10px',
};

export default function TrainingBenchmark({ addToast }) {
  const [models, setModels] = useState([]);
  const [modelSearch, setModelSearch] = useState('');
  const [modelOpen, setModelOpen] = useState(false);
  const [modelCategory, setModelCategory] = useState('all');
  const [selectedModel, setSelectedModel] = useState(null);

  // Dataset / Suite Selection
  const [suiteMode, setSuiteMode] = useState('all'); // 'all' or 'custom'
  const [selectedSuites, setSelectedSuites] = useState(['mmlu', 'gsm8k', 'humaneval']);
  const [suiteInfo, setSuiteInfo] = useState({});
  const [suiteTotals, setSuiteTotals] = useState({ count: 0, cached_suites: 0, total_suites: 0 });
  const [downloading, setDownloading] = useState([]);

  // Copertura & Campioni
  const [evalMode, setEvalMode] = useState('sample'); // 'full' or 'sample'
  const [sampleCount, setSampleCount] = useState(100);
  const [launching, setLaunching] = useState(false);

  // Job & Dettaglio
  const [jobs, setJobs] = useState([]);
  const [selectedJobId, setSelectedJobId] = useState(null);

  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [verdictFilter, setVerdictFilter] = useState('all');
  const [suiteFilter, setSuiteFilter] = useState('all');
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(15);

  const toast = useCallback((msg, kind) => { if (addToast) addToast(msg, kind); }, [addToast]);

  const post = useCallback((path, body) => fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => r.json()), []);

  // ── Caricamenti ────────────────────────────────────────────────────────────

  const loadModels = useCallback(async () => {
    try {
      const res = await fetch('/api/training/benchmark/models');
      if (!res.ok) return;
      const data = await res.json();
      const list = Array.isArray(data) ? data : (data.models || []);
      setModels(list);
      setSelectedModel((prev) => (
        prev && list.some((m) => m.id === prev) ? prev : (list[0]?.id ?? 'sigma')
      ));
    } catch (err) {
      console.error('Modelli benchmark non caricati:', err);
    }
  }, []);

  const loadJobs = useCallback(async () => {
    try {
      const res = await fetch('/api/training/benchmark/jobs');
      if (!res.ok) return [];
      const list = (await res.json()) || [];
      setJobs(list);
      setSelectedJobId((prev) => (prev && list.some((j) => j.id === prev) ? prev : (list[0]?.id ?? null)));
      return list;
    } catch (err) {
      console.error('Job benchmark non caricati:', err);
      return [];
    }
  }, []);

  const loadSuiteInfo = useCallback(async () => {
    try {
      const res = await fetch('/api/training/benchmark/suite_info?suite=all');
      if (!res.ok) return;
      const data = await res.json();
      setSuiteInfo(data?.suites || {});
      setSuiteTotals({
        count: data?.count || 0,
        cached_suites: data?.cached_suites || 0,
        total_suites: data?.total_suites || 0,
      });
    } catch (err) {
      console.error('Stato dataset non caricato:', err);
    }
  }, []);

  useEffect(() => {
    loadModels();
    loadJobs();
    loadSuiteInfo();
  }, [loadModels, loadJobs, loadSuiteInfo]);

  const hasActiveJobs = useMemo(() => jobs.some((j) => ACTIVE_STATUSES.includes(j.status)), [jobs]);
  const wasActive = useRef(false);

  useEffect(() => {
    if (!hasActiveJobs) {
      if (wasActive.current) {
        wasActive.current = false;
        toast('✅ Valutazione benchmark completata.', 'success');
      }
      return undefined;
    }
    wasActive.current = true;
    const timer = setInterval(loadJobs, 1000);
    return () => clearInterval(timer);
  }, [hasActiveJobs, loadJobs, toast]);

  useEffect(() => {
    const timer = setTimeout(() => { setSearchQuery(searchInput); setPage(1); }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => { setPage(1); }, [selectedJobId, verdictFilter, suiteFilter, pageSize]);

  const activeJob = useMemo(
    () => jobs.find((j) => j.id === selectedJobId) || jobs[0] || null,
    [jobs, selectedJobId],
  );
  const activeStatus = activeJob?.status;
  const isRunning = ACTIVE_STATUSES.includes(activeStatus);

  const loadDetail = useCallback(async () => {
    if (!selectedJobId) { setDetail(null); return; }
    setDetailLoading(true);
    try {
      const params = new URLSearchParams({
        job_id: selectedJobId,
        page: String(page),
        page_size: String(pageSize),
        verdict: verdictFilter,
        suite: suiteFilter,
        q: searchQuery,
      });
      const res = await fetch(`/api/training/benchmark/results?${params}`);
      const data = await res.json();
      setDetail(data?.success === false ? null : data);
    } catch (err) {
      console.error('Dettaglio job non caricato:', err);
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, [selectedJobId, page, pageSize, verdictFilter, suiteFilter, searchQuery]);

  useEffect(() => { loadDetail(); }, [loadDetail]);

  useEffect(() => {
    if (!activeStatus || !ACTIVE_STATUSES.includes(activeStatus)) return undefined;
    const timer = setInterval(loadDetail, 1000);
    return () => clearInterval(timer);
  }, [activeStatus, loadDetail]);

  // ── Azioni ─────────────────────────────────────────────────────────────────

  // `limit` scarica solo le prime N righe dello split. Accorcia la prima
  // preparazione, e in cambio la cache e' l'inizio della suite e non un suo
  // campione: MMLU e' ordinato per materia, quindi un assaggio da 500 righe
  // copre le prime materie in ordine alfabetico e nessuna delle altre. Il
  // punteggio che ne esce non e' confrontabile con uno sulla suite intera, ed
  // e' per questo che la cache resta marcata come parziale.
  const handleDownload = async (suiteId, limit = 0) => {
    setDownloading((prev) => [...prev, suiteId]);
    toast(limit ? `📥 Assaggio di ${suiteId} (${limit} quesiti)...`
                : `📥 Download dataset ${suiteId}...`, 'info');
    try {
      const data = await post('/api/training/benchmark/download', { suite: suiteId, limit });
      toast(data.success
        ? `✅ ${suiteId}: ${fmt(data.count)} quesiti in cache${data.complete === false ? ' (parziale)' : ''}`
        : `❌ Download ${suiteId}: ${data.error || 'errore sconosciuto'}`,
      data.success ? 'success' : 'error');
      loadSuiteInfo();
    } catch (err) {
      toast(`❌ Errore di rete: ${err.message}`, 'error');
    } finally {
      setDownloading((prev) => prev.filter((s) => s !== suiteId));
    }
  };

  const toggleSuiteSelection = (id) => {
    if (id === 'all') {
      setSuiteMode('all');
      return;
    }
    setSuiteMode('custom');
    setSelectedSuites((prev) => {
      if (prev.includes(id)) {
        const next = prev.filter((s) => s !== id);
        return next.length > 0 ? next : [id];
      }
      return [...prev, id];
    });
  };

  const currentSuiteString = useMemo(() => {
    if (suiteMode === 'all') return 'all';
    return selectedSuites.join(',');
  }, [suiteMode, selectedSuites]);

  const plannedItems = useMemo(() => {
    if (suiteMode === 'all') {
      const total = suiteTotals.count || 0;
      return evalMode === 'sample' ? Math.min(sampleCount, total || sampleCount) : total;
    }
    let total = 0;
    for (const sid of selectedSuites) {
      total += (suiteInfo[sid]?.count || 0);
    }
    return evalMode === 'sample' ? Math.min(sampleCount, total || sampleCount) : total;
  }, [suiteMode, selectedSuites, suiteTotals, suiteInfo, evalMode, sampleCount]);

  const handleStart = async (overrideModel = null, overrideSuite = null) => {
    const model = overrideModel || selectedModel;
    const suite = overrideSuite || currentSuiteString;
    if (!model) { toast('⚠️ Seleziona un modello', 'warning'); return; }

    setLaunching(true);
    try {
      const data = await post('/api/training/benchmark/run', {
        model,
        suite,
        mode: evalMode,
        samples: evalMode === 'full' ? 0 : sampleCount,
        concurrency: 'auto',
      });
      if (!data.success) { toast(`❌ ${data.error || 'Avvio non riuscito'}`, 'error'); return; }
      setSelectedJobId(data.job.id);
      toast(`🚀 Benchmark avviato su ${model} (${data.job.concurrency}x)`, 'info');
      loadJobs();
    } catch (err) {
      toast(`❌ ${err.message}`, 'error');
    } finally {
      setLaunching(false);
    }
  };

  const jobAction = async (path, jobId, message, event) => {
    if (event) event.stopPropagation();
    try {
      const data = await post(path, { id: jobId });
      if (data.success) { toast(message, 'info'); loadJobs(); }
    } catch (err) {
      toast(`❌ ${err.message}`, 'error');
    }
  };

  const handleCancelAll = async () => {
    const active = jobs.filter((j) => ACTIVE_STATUSES.includes(j.status));
    for (const job of active) await post('/api/training/benchmark/cancel', { id: job.id });
    if (active.length) { toast('🛑 Valutazioni annullate.', 'warning'); loadJobs(); }
  };

  const handleExportReport = async () => {
    if (!activeJob) return;
    const params = new URLSearchParams({ job_id: activeJob.id, page: '1', page_size: '200', verdict: 'all' });
    let all = [];
    try {
      const first = await (await fetch(`/api/training/benchmark/results?${params}`)).json();
      all = first.results || [];
      for (let p = 2; p <= (first.pages || 1); p += 1) {
        params.set('page', String(p));
        const next = await (await fetch(`/api/training/benchmark/results?${params}`)).json();
        all = all.concat(next.results || []);
      }
    } catch (err) {
      toast(`❌ Export non riuscito: ${err.message}`, 'error');
      return;
    }
    const blob = new Blob([JSON.stringify({
      title: `Report Benchmark: ${activeJob.model}`,
      timestamp: activeJob.created_at,
      model: activeJob.model,
      suite: activeJob.suite_name,
      concurrency: activeJob.concurrency,
      reproducibility: activeJob.reproducibility,
      metrics: activeJob.metrics,
      verdict_counts: detail?.verdict_counts || {},
      suite_breakdown: detail?.suite_breakdown || {},
      test_results: all,
    }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `benchmark_${activeJob.model.replace(/[^a-zA-Z0-9]/g, '_')}_${activeJob.id}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
    toast(`📥 Report esportato (${fmt(all.length)} quesiti)`, 'success');
  };

  const handleExportReview = async () => {
    if (!activeJob) return;
    try {
      const data = await (await fetch(`/api/training/benchmark/review?job_id=${activeJob.id}`)).json();
      if (!data.success) { toast(`❌ ${data.error}`, 'error'); return; }
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `revisione_${activeJob.id}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      toast(`⚠️ Coda di revisione esportata (${fmt(data.count)} quesiti)`, 'success');
    } catch (err) {
      toast(`❌ ${err.message}`, 'error');
    }
  };

  // ── Derivati ───────────────────────────────────────────────────────────────

  const currentModel = useMemo(
    () => models.find((m) => m.id === selectedModel) || null,
    [models, selectedModel],
  );

  const filteredModels = useMemo(() => {
    let list = models;
    if (modelCategory !== 'all') {
      list = list.filter((m) => m.category === modelCategory);
    }
    const needle = modelSearch.trim().toLowerCase();
    if (!needle) return list;
    return list.filter((m) => `${m.name} ${m.provider_label} ${m.family} ${m.parameter_size} ${m.quantization}`
      .toLowerCase().includes(needle));
  }, [models, modelCategory, modelSearch]);

  const effectiveConcurrency = useMemo(() => {
    if (currentModel?.is_cloud) return 8;
    return 1;
  }, [currentModel]);

  const estimate = useMemo(() => {
    if (!plannedItems) return null;
    const perItemMs = currentModel?.is_cloud ? 700 : 900;
    const seconds = (plannedItems * perItemMs) / 1000 / effectiveConcurrency;
    if (seconds < 90) return `~${Math.round(seconds)} s`;
    if (seconds < 5400) return `~${Math.round(seconds / 60)} min`;
    return `~${(seconds / 3600).toFixed(1)} h`;
  }, [plannedItems, effectiveConcurrency, currentModel]);

  const metrics = activeJob?.metrics || {};
  const repro = activeJob?.reproducibility || {};
  const counts = detail?.verdict_counts || {};
  const reviewTotal = (counts.ambiguous || 0) + (counts.unparsable || 0) + (counts.error || 0);
  const jobSuites = Object.keys(detail?.suite_breakdown || {});
  const canLaunch = Boolean(selectedModel) && plannedItems > 0 && !launching;

  return (
    <div style={{ padding: '24px', height: '100%', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '22px' }}>

      {/* Intestazione Moderna */}
      <div className="app-page-header" style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px',
        padding: '16px 20px', background: 'rgba(15,18,35,0.7)', borderRadius: '16px', border: '1px solid var(--border, rgba(255,255,255,0.1))'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{
            width: '44px', height: '44px', borderRadius: '12px', background: 'rgba(0,210,255,0.15)',
            border: '1px solid rgba(0,210,255,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Award size={24} color="#00f2fe" />
          </div>
          <div>
            <h1 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 800, color: 'var(--text, #fff)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              Training Lab — LLM Benchmark Suite
            </h1>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-dark, #8b949e)', display: 'flex', alignItems: 'center', gap: '8px', marginTop: '2px' }}>
              <span>11 Benchmark Ufficiali (MMLU, GSM8K, HumanEval...)</span>
              <span>•</span>
              <span style={{ color: '#00f2fe', fontFamily: 'monospace', fontWeight: 700 }}>
                {fmt(suiteTotals.count)} QUESITI DISPONIBILI
              </span>
              <span>•</span>
              <span style={{ color: 'var(--success, #3fb950)', fontWeight: 600 }}>
                ⚡ SigmaEngine & Multi-Provider Attivo
              </span>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button onClick={() => { loadModels(); loadJobs(); loadSuiteInfo(); }} style={{
            background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)',
            borderRadius: '10px', padding: '8px 14px', color: 'var(--text, #fff)', cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', fontWeight: 600,
          }}>
            <RefreshCw size={14} /> Aggiorna Dati
          </button>
        </div>
      </div>

      {/* Sezione 1: Selezione Dataset e Benchmark */}
      <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: '14px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '0.94rem', fontWeight: 700, color: 'var(--text, #fff)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Database size={16} style={{ color: ACCENT }} />
              Dataset di Valutazione — {suiteTotals.cached_suites}/{suiteTotals.total_suites} suite pronte
            </h3>
            <div style={{ fontSize: '0.68rem', color: 'var(--text-dark, #8b949e)', marginTop: '2px' }}>
              Puoi selezionare <b>Tutti i benchmark</b> per una valutazione globale, oppure cliccare su <b>specifici dataset</b> per concentrare i campioni.
            </div>
          </div>

          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <button
              onClick={() => setSuiteMode('all')}
              style={{
                ...btn(suiteMode === 'all'),
                display: 'flex', alignItems: 'center', gap: '5px',
              }}
            >
              <Globe size={13} /> Tutti i Benchmark ({fmt(suiteTotals.count)})
            </button>
            <button
              onClick={() => handleDownload('all', 300)}
              disabled={downloading.length > 0}
              title="Prende le prime 300 righe di ogni suite: pronto in poco, ma e' l'inizio di ogni dataset e non un suo campione — il punteggio non e' confrontabile con un run sulla suite intera."
              style={{
                ...btn(false), border: '1px solid rgba(255,184,108,0.4)', color: '#ffb86c',
                background: 'rgba(255,184,108,0.1)', fontWeight: 700,
                cursor: downloading.length > 0 ? 'wait' : 'pointer',
              }}
            >
              {downloading.includes('all') ? '⏳' : '⚡ Assaggio rapido'}
            </button>
            <button
              onClick={() => handleDownload('all')}
              disabled={downloading.length > 0}
              title="Scarica una volta sola: le suite gia' in cache non vengono riscaricate."
              style={{
                ...btn(false), border: '1px solid rgba(0,210,255,0.4)', color: ACCENT,
                background: 'rgba(0,210,255,0.1)', fontWeight: 700,
                cursor: downloading.length > 0 ? 'wait' : 'pointer',
              }}
            >
              {downloading.includes('all') ? '⏳ Download in corso...' : '📥 Scarica tutte'}
            </button>
          </div>
        </div>

        {/* Griglia Suite con Toggle Multiplo */}
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
          gap: '10px', maxHeight: '280px', overflowY: 'auto', paddingRight: '4px',
        }}>
          {SUITE_ORDER.map((id) => {
            const label = SUITE_LABELS[id];
            const info = id === 'all'
              ? { cached: suiteTotals.cached_suites === suiteTotals.total_suites, count: suiteTotals.count }
              : (suiteInfo[id] || {});
            const isSelected = (id === 'all' && suiteMode === 'all') || (suiteMode === 'custom' && selectedSuites.includes(id));
            const busy = downloading.includes(id) || downloading.includes('all');

            return (
              <div
                key={id}
                onClick={() => toggleSuiteSelection(id)}
                style={{
                  background: isSelected ? 'rgba(0,210,255,0.14)' : 'rgba(10,12,26,0.6)',
                  border: `1px solid ${isSelected ? ACCENT : 'rgba(255,255,255,0.08)'}`,
                  borderRadius: '10px', padding: '10px 12px', cursor: 'pointer',
                  display: 'flex', flexDirection: 'column', gap: '6px',
                  transition: 'all 0.15s ease',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '6px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    {suiteMode === 'custom' && id !== 'all' ? (
                      selectedSuites.includes(id)
                        ? <CheckSquare size={14} color={ACCENT} />
                        : <Square size={14} color="var(--text-dark, #8b949e)" />
                    ) : null}
                    <span style={{ fontSize: '0.82rem', fontWeight: 700, color: isSelected ? ACCENT : 'var(--text, #fff)' }}>
                      {label.name}
                    </span>
                  </div>
                  <span style={{
                    fontSize: '0.55rem', fontWeight: 700, padding: '2px 6px', borderRadius: '5px',
                    background: isSelected ? 'rgba(0,210,255,0.25)' : 'rgba(255,255,255,0.06)',
                    color: isSelected ? ACCENT : 'var(--text-dark, #8b949e)', whiteSpace: 'nowrap',
                  }}>{label.badge}</span>
                </div>

                <div style={{ fontSize: '0.68rem', color: 'var(--text-dark, #8b949e)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  {info.cached ? (
                    <span style={{ color: info.complete === false ? '#ffb86c' : 'var(--success, #3fb950)', fontWeight: 700 }}>
                      {fmt(info.count)} quesiti{info.complete === false ? ' · parziale' : ''}
                    </span>
                  ) : <span style={{ color: '#8b949e' }}>Non scaricato</span>}

                  {id !== 'all' && (
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDownload(id); }}
                      disabled={busy}
                      style={{
                        background: info.needs_refresh ? 'rgba(255,184,108,0.12)' : 'rgba(0,210,255,0.1)',
                        border: `1px solid ${info.needs_refresh ? 'rgba(255,184,108,0.4)' : 'rgba(0,210,255,0.3)'}`,
                        borderRadius: '5px', padding: '2px 8px',
                        color: info.needs_refresh ? '#ffb86c' : ACCENT,
                        fontSize: '0.6rem', fontWeight: 700, cursor: busy ? 'wait' : 'pointer',
                      }}
                    >
                      {busy ? '⏳'
                        : info.complete === false ? 'Completa'
                        : info.cached ? (info.needs_refresh ? 'Aggiorna' : 'Riscarica')
                        : 'Scarica'}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Sezione 2: Configurazione Modello e Campioni */}
      <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <h3 style={{ margin: 0, fontSize: '0.94rem', fontWeight: 700, color: 'var(--text, #fff)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Compass size={16} style={{ color: ACCENT }} /> Configura & Avvia Valutazione
        </h3>

        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 1.2fr) minmax(300px, 1fr)', gap: '16px', alignItems: 'stretch' }}>
          {/* Selettore Modello Multi-Provider */}
          <ModelPicker
            models={filteredModels}
            allModels={models}
            total={models.length}
            current={currentModel}
            search={modelSearch}
            open={modelOpen}
            activeCategory={modelCategory}
            onCategory={setModelCategory}
            onSearch={setModelSearch}
            onToggle={() => {
              if (!modelOpen && models.length === 0) loadModels();
              setModelOpen((v) => !v);
            }}
            onRefresh={loadModels}
            onPick={(id) => { setSelectedModel(id); setModelOpen(false); setModelSearch(''); }}
          />

          {/* Selettore Copertura & Campioni Estesi */}
          <CoveragePicker
            evalMode={evalMode}
            sampleCount={sampleCount}
            plannedItems={plannedItems}
            suiteMode={suiteMode}
            selectedSuitesCount={selectedSuites.length}
            onMode={setEvalMode}
            onCount={setSampleCount}
          />
        </div>

        {/* Riepilogo di Lancio Ottimizzato */}
        <div style={{
          ...panel, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: '16px', flexWrap: 'wrap', borderColor: canLaunch ? 'rgba(0,210,255,0.4)' : 'var(--border, rgba(255,255,255,0.08))',
          background: 'rgba(10,12,26,0.85)',
        }}>
          <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap', fontSize: '0.74rem' }}>
            <Summary label="Modello" value={currentModel?.name || '—'} hint={currentModel?.provider_label} />
            <Summary label="Dataset / Suite" value={suiteMode === 'all' ? 'Tutte (11 Suite)' : `${selectedSuites.length} Selezionate`} />
            <Summary label="Quesiti Totali" value={fmt(plannedItems)} />
            <Summary
              label="Esecuzione"
              value={currentModel?.is_cloud ? '☁️ Parallel Pool (8x)' : '⚡ GPU Diretta (Full Speed)'}
              hint={currentModel?.is_cloud ? 'Cloud Concurrency' : '30+ tok/s Massima Efficienza'}
            />
            <Summary label="Stima Durata" value={estimate || '—'} />
          </div>

          <div style={{ display: 'flex', gap: '8px' }}>
            {hasActiveJobs && (
              <button onClick={handleCancelAll} style={{
                height: '42px', padding: '0 18px', border: 'none', borderRadius: '10px',
                background: 'linear-gradient(135deg, #ff5555 0%, #cc3333 100%)', color: '#fff',
                fontWeight: 700, fontSize: '0.82rem', cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: '6px',
              }}>
                <StopCircle size={16} /> Annulla
              </button>
            )}
            <button
              onClick={() => handleStart()}
              disabled={!canLaunch}
              style={{
                height: '42px', padding: '0 28px', border: 'none', borderRadius: '10px', color: '#fff',
                fontWeight: 700, fontSize: '0.84rem',
                background: canLaunch ? 'linear-gradient(135deg, #00d2ff 0%, #0072ff 100%)' : 'rgba(255,255,255,0.1)',
                cursor: canLaunch ? 'pointer' : 'not-allowed',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
                boxShadow: canLaunch ? '0 0 20px rgba(0,210,255,0.3)' : 'none',
              }}
            >
              {launching
                ? <><RefreshCw size={16} className="spin-icon" /> Avvio benchmark...</>
                : <><Play size={16} /> Avvia Valutazione</>}
            </button>
          </div>
        </div>
      </div>

      {/* Sezione 3: Cronologia Job & Ispezione Risultati */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 340px) 1fr', gap: '20px', alignItems: 'start' }}>
        {/* Lista Job Eseguiti */}
        <div style={{ ...card, padding: '16px', display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '820px', overflowY: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '10px' }}>
            <h3 style={{ margin: 0, fontSize: '0.88rem', fontWeight: 700, color: 'var(--text, #fff)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Layers size={15} style={{ color: ACCENT }} /> Valutazioni ({jobs.length})
            </h3>
          </div>

          {jobs.length === 0 ? (
            <div style={{ padding: '30px 10px', textAlign: 'center', color: 'var(--text-dark, #8b949e)', fontSize: '0.78rem' }}>
              Nessuna valutazione eseguita.
            </div>
          ) : jobs.map((j) => {
            const isSelected = selectedJobId === j.id;
            const jm = j.metrics || {};
            const isActive = ACTIVE_STATUSES.includes(j.status);
            return (
              <div key={j.id} onClick={() => setSelectedJobId(j.id)} style={{
                background: isSelected ? 'rgba(0,210,255,0.14)' : 'rgba(10,12,26,0.6)',
                border: `1px solid ${isSelected ? ACCENT : 'rgba(255,255,255,0.08)'}`,
                borderRadius: '10px', padding: '11px 13px', cursor: 'pointer',
                display: 'flex', flexDirection: 'column', gap: '7px',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '6px' }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text, #fff)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {j.model}
                    </div>
                    <div style={{ fontSize: '0.68rem', color: ACCENT, fontWeight: 600 }}>{j.suite_name || j.suite}</div>
                  </div>
                  <StatusPill job={j} />
                </div>

                {isActive && (
                  <div style={{ width: '100%', height: '4px', background: 'rgba(255,255,255,0.1)', borderRadius: '2px', overflow: 'hidden' }}>
                    <div style={{
                      width: `${j.progress || 0}%`, height: '100%',
                      background: j.status === 'paused' ? '#ffb86c' : ACCENT, transition: 'width 0.3s ease',
                    }} />
                  </div>
                )}

                <div style={{ fontSize: '0.68rem', color: 'var(--text-dark, #8b949e)' }}>
                  <span style={{ color: (jm.overall_score || 0) >= 50 ? 'var(--success, #3fb950)' : '#ff5555', fontWeight: 700 }}>
                    {jm.overall_score || 0}%
                  </span>
                  {' · '}{fmt(jm.tests_passed)}/{fmt(jm.tests_total)} pass
                  {jm.tests_review > 0 && <span style={{ color: '#ffb86c' }}> · {fmt(jm.tests_review)} rev.</span>}
                  {j.concurrency > 1 && <span> · {j.concurrency}x</span>}
                </div>

                <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                  {j.status === 'running' && (
                    <button onClick={(e) => jobAction('/api/training/benchmark/pause', j.id, '⏸️ In pausa', e)}
                      style={{ ...btn(true, '#ffb86c'), fontSize: '0.58rem' }}>⏸️ Pausa</button>
                  )}
                  {j.status === 'paused' && (
                    <button onClick={(e) => jobAction('/api/training/benchmark/resume', j.id, '▶️ Ripresa', e)}
                      style={{ ...btn(true, '#3fb950'), fontSize: '0.58rem' }}>▶️ Riprendi</button>
                  )}
                  {isActive && (
                    <button onClick={(e) => jobAction('/api/training/benchmark/cancel', j.id, '🛑 Annullato', e)}
                      style={{ ...btn(true, '#ff5555'), fontSize: '0.58rem' }}>🛑 Ferma</button>
                  )}
                  {!isActive && (
                    <button onClick={(e) => { e.stopPropagation(); handleStart(j.model, j.suite); }}
                      disabled={launching} style={{ ...btn(true), fontSize: '0.58rem', display: 'flex', alignItems: 'center', gap: '3px' }}>
                      <RotateCcw size={9} /> Riesegui
                    </button>
                  )}
                  <button onClick={(e) => jobAction('/api/training/benchmark/delete', j.id, '🗑️ Eliminato', e)}
                    style={{ background: 'none', border: 'none', color: 'var(--text-dark, #8b949e)', cursor: 'pointer', padding: '2px', marginLeft: 'auto' }}
                    title="Elimina job">
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        {/* Dettaglio del Job Selezionato */}
        <div style={{ ...card, display: 'flex', flexDirection: 'column', gap: '14px', minHeight: '600px' }}>
          {!activeJob ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '400px', color: 'var(--text-dark, #8b949e)', gap: '12px' }}>
              <Compass size={46} style={{ opacity: 0.3 }} />
              <div style={{ fontSize: '0.92rem', fontWeight: 600 }}>Seleziona una valutazione per esaminare i risultati</div>
            </div>
          ) : (
            <>
              <div style={{
                background: 'rgba(10,12,26,0.85)', border: '1px solid rgba(0,210,255,0.3)',
                borderRadius: '12px', padding: '14px 18px', display: 'flex',
                alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px',
              }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '9px', flexWrap: 'wrap' }}>
                    <h3 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 800, color: 'var(--text, #fff)' }}>{activeJob.model}</h3>
                    <span style={{ fontSize: '0.68rem', padding: '2px 8px', borderRadius: '6px', background: 'rgba(0,210,255,0.15)', color: ACCENT, fontWeight: 700 }}>
                      {activeJob.suite_name || activeJob.suite}
                    </span>
                    {repro.reproducible_hash && (
                      <span style={{ fontSize: '0.62rem', padding: '2px 8px', borderRadius: '6px', background: 'rgba(63,185,80,0.15)', color: 'var(--success, #3fb950)', fontWeight: 600, fontFamily: 'monospace' }}>
                        {repro.reproducible_hash}
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-dark, #8b949e)', marginTop: '4px' }}>
                    {new Date(activeJob.created_at).toLocaleString('it-IT')} · temp 0.0 · seed 42 ·
                    {' '}{repro.mode || '—'} · copertura {repro.dataset_coverage || '—'}
                    {activeJob.concurrency ? ` · ${activeJob.concurrency}x parallelo` : ''}
                    {activeJob.concurrency_source ? ` (${activeJob.concurrency_source})` : ''}
                  </div>
                  {/* Come si e' arrivati alla risposta fa parte della misura:
                      due run che hanno scelto in modi diversi non sono
                      confrontabili, per quanto vicini siano i punteggi. */}
                  <div style={{ fontSize: '0.68rem', color: 'var(--text-dark, #8b949e)', marginTop: '3px' }}>
                    {repro.objective_mode
                      ? 'modalita’ oggettiva: nessun ruolo, nessuno strumento, campionamento neutro'
                      : 'protocollo generativo su provider esterno'}
                    {{
                      'logit-ranking': ' · scelta decisa sui logit',
                      'continuation-ranking': ' · opzioni confrontate per verosimiglianza',
                      'grammar-constrained': ' · scelta vincolata da grammatica',
                      'generative-parse': ' · risposta letta dal testo',
                    }[repro.answer_protocol] || ''}
                    {repro.prompt_protocol ? ` · prompt v${repro.prompt_protocol}` : ''}
                  </div>
                  {/* Ogni suite si misura come viene pubblicata: MMLU sulla
                      verosimiglianza delle lettere, HellaSwag e ARC su quella
                      del testo delle opzioni, MMLU-Pro e GSM8K facendo
                      ragionare il modello. Due run con protocolli diversi non
                      sono confrontabili, e questo e' il posto in cui si vede. */}
                  {repro.protocols && Object.keys(repro.protocols).length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '5px' }}>
                      {Object.values(repro.protocols).map((p) => (
                        <span key={p.suite} title={p.note}
                          style={{
                            fontSize: '0.58rem', padding: '2px 6px', borderRadius: '5px',
                            background: 'rgba(255,255,255,0.05)',
                            color: 'var(--text-dark, #8b949e)', whiteSpace: 'nowrap',
                          }}>
                          {p.suite}: {p.metric}{p.shots ? ` · ${p.shots}-shot` : ''}{p.thinking ? ' · CoT' : ''}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                  <button onClick={handleExportReport} style={{ ...btn(false), border: '1px solid rgba(255,255,255,0.1)', color: 'var(--text, #fff)', display: 'flex', alignItems: 'center', gap: '5px' }}>
                    <Download size={13} /> Report JSON
                  </button>
                  {reviewTotal > 0 && (
                    <button onClick={handleExportReview} style={{ ...btn(true, '#ffb86c'), display: 'flex', alignItems: 'center', gap: '5px' }}>
                      <AlertTriangle size={13} /> Revisione ({fmt(reviewTotal)})
                    </button>
                  )}
                </div>
              </div>

              {/* Banner di Stato Live e Caricamento Modello */}
              {(activeJob.status === 'loading_model' || activeJob.status === 'preparing' || activeJob.status_message) && (
                <div style={{
                  background: activeJob.status === 'loading_model' ? 'rgba(255,184,108,0.12)' : 'rgba(0,210,255,0.1)',
                  border: `1px solid ${activeJob.status === 'loading_model' ? '#ffb86c' : 'rgba(0,210,255,0.35)'}`,
                  borderRadius: '10px', padding: '10px 14px', fontSize: '0.78rem',
                  color: activeJob.status === 'loading_model' ? '#ffb86c' : ACCENT,
                  display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600,
                }}>
                  {activeJob.status === 'loading_model' || activeJob.status === 'preparing'
                    ? <RefreshCw size={15} className="spin-icon" />
                    : <Zap size={15} />}
                  <span>{activeJob.status_message || (activeJob.status === 'loading_model' ? `Caricamento pesi ${activeJob.model} in VRAM...` : 'Preparazione dataset in corso...')}</span>
                </div>
              )}

              {activeJob.error && (
                <div style={{ background: 'rgba(255,85,85,0.1)', border: '1px solid rgba(255,85,85,0.35)', borderRadius: '10px', padding: '10px 14px', fontSize: '0.74rem', color: '#ff5555' }}>
                  {activeJob.error}
                </div>
              )}

              {/* Metriche Chiave */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(145px, 1fr))', gap: '10px' }}>
                {/* Durante il run lo score ufficiale divide per il totale
                    previsto, quindi un run perfetto a meta' strada mostra 50%:
                    e' cosi' che "32 giuste su 61" e' comparso come "32%". Il
                    numero ufficiale ha senso solo a run finito. */}
                {isRunning ? (
                  <Metric label="Accuratezza corrente" value={`${metrics.progress_score || 0}%`} color={ACCENT}
                    hint={`${fmt(metrics.tests_passed)}/${fmt(metrics.tests_total)} superati finora`} />
                ) : (
                  <Metric label="Score ufficiale" value={`${metrics.overall_score || 0}%`} color="var(--success, #3fb950)"
                    hint={`${fmt(metrics.tests_passed)}/${fmt(metrics.tests_total)} superati`} />
                )}
                {/* La percentuale e il suo denominatore vengono dalla stessa
                    fonte. Mescolando le metriche del server con il conteggio
                    delle righe caricate si leggeva "52.46% su 62 decisi", dove
                    52.46 era 32/61: due numeri veri che insieme non tornano. */}
                <Metric label="Accuratezza sui decisi" value={`${metrics.decided_accuracy_pct || 0}%`} color={ACCENT}
                  hint={`su ${fmt((metrics.tests_passed || 0) + (metrics.tests_failed || 0))} decisi`} />
                <Metric label="Da rivedere" value={fmt(metrics.tests_review)} color="#ffb86c"
                  hint={`${metrics.review_pct || 0}% del totale`} />
                {/* I quesiti al minuto valgono per entrambi i protocolli. I
                    token al secondo no: una scelta multipla decisa sui logit
                    produce un token, e "2.5 tok/s" descriveva come lentissimo
                    un run che macinava un quesito ogni 400 ms. */}
                <Metric label="Ritmo" value={`${metrics.avg_latency_ms ? Math.round(60000 / metrics.avg_latency_ms) : 0}/min`} color="#bc8cff"
                  hint={`${fmt(metrics.avg_latency_ms)} ms medi · ${metrics.tokens_per_sec || 0} tok/s`} />
              </div>

              {/* Ripartizione Verdetti */}
              {Object.keys(counts).length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {['pass', 'fail', 'ambiguous', 'unparsable', 'error'].filter((v) => counts[v]).map((v) => {
                    const s = VERDICT_STYLE[v];
                    return (
                      <div key={v} style={{
                        background: s.bg, border: `1px solid ${s.border}`, borderRadius: '6px',
                        padding: '4px 10px', fontSize: '0.68rem', fontWeight: 700, color: s.color,
                        display: 'flex', alignItems: 'center', gap: '5px',
                      }}>
                        <s.Icon size={12} /> {s.label}: {fmt(counts[v])}
                      </div>
                    );
                  })}
                </div>
              )}

              {jobSuites.length > 1 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {Object.entries(detail.suite_breakdown).map(([name, stats]) => {
                    const pct = stats.total ? Math.round((stats.passed / stats.total) * 100) : 0;
                    return (
                      <div key={name} style={{
                        background: 'rgba(10,12,26,0.7)', border: '1px solid var(--border, rgba(255,255,255,0.08))',
                        borderRadius: '6px', padding: '4px 10px', fontSize: '0.68rem', color: 'var(--text-dark, #8b949e)',
                      }}>
                        <b style={{ color: 'var(--text, #fff)' }}>{name}</b>: {stats.passed}/{stats.total} ({pct}%)
                        {stats.review > 0 && <span style={{ color: '#ffb86c' }}> · {stats.review} rev.</span>}
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Barra Ricerca e Filtri */}
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px',
                background: 'rgba(10,12,26,0.5)', border: '1px solid var(--border, rgba(255,255,255,0.08))',
                borderRadius: '10px', padding: '8px 14px', flexWrap: 'wrap',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, minWidth: '180px' }}>
                  <Search size={14} style={{ color: 'var(--text-dark, #8b949e)' }} />
                  <input type="text" value={searchInput} onChange={(e) => setSearchInput(e.target.value)}
                    placeholder="Cerca quesito, categoria o risposta generata..."
                    style={{ width: '100%', background: 'none', border: 'none', color: 'var(--text, #fff)', fontSize: '0.78rem', outline: 'none' }} />
                  {searchInput && (
                    <button onClick={() => setSearchInput('')} style={{ background: 'none', border: 'none', color: 'var(--text-dark, #8b949e)', cursor: 'pointer' }}>✕</button>
                  )}
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                  <button onClick={() => setVerdictFilter('all')} style={btn(verdictFilter === 'all')}>
                    Tutti ({fmt(Object.values(counts).reduce((a, b) => a + b, 0))})
                  </button>
                  <button onClick={() => setVerdictFilter('pass')} style={btn(verdictFilter === 'pass', '#3fb950')}>
                    ✓ {fmt(counts.pass)}
                  </button>
                  <button onClick={() => setVerdictFilter('fail')} style={btn(verdictFilter === 'fail', '#ff5555')}>
                    ✕ {fmt(counts.fail)}
                  </button>
                  <button onClick={() => setVerdictFilter('review')} style={btn(verdictFilter === 'review', '#ffb86c')}>
                    ⚠ Da rivedere ({fmt(reviewTotal)})
                  </button>
                </div>
              </div>

              {/* Lista Schede Quesiti */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', minHeight: '200px' }}>
                {detailLoading && !detail ? (
                  <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-dark, #8b949e)', fontSize: '0.78rem' }}>
                    <RefreshCw size={20} className="spin-icon" /> Caricamento quesiti...
                  </div>
                ) : !detail || detail.total === 0 ? (
                  <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--text-dark, #8b949e)', fontSize: '0.78rem' }}>
                    {activeJob.status === 'preparing'
                      ? 'Preparazione del dataset in corso...'
                      : 'Nessun quesito corrisponde ai filtri selezionati.'}
                  </div>
                ) : (
                  <>
                    {detail.results.map((tr, idx) => (
                      <QuestionCard
                        key={`${tr.id}_${idx}`}
                        result={tr}
                        model={activeJob.model}
                        number={(detail.page - 1) * detail.page_size + idx + 1}
                      />
                    ))}

                    {/* Paginazione */}
                    <div style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      background: 'rgba(10,12,26,0.85)', border: '1px solid rgba(0,210,255,0.3)',
                      borderRadius: '10px', padding: '8px 14px', flexWrap: 'wrap', gap: '10px',
                    }}>
                      <div style={{ fontSize: '0.72rem', color: 'var(--text-dark, #8b949e)' }}>
                        Quesiti <b style={{ color: 'var(--text, #fff)' }}>
                          {fmt((detail.page - 1) * detail.page_size + 1)}–{fmt(Math.min(detail.page * detail.page_size, detail.total))}
                        </b> di <b style={{ color: 'var(--text, #fff)' }}>{fmt(detail.total)}</b>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <select value={pageSize} onChange={(e) => setPageSize(Number(e.target.value))} style={{
                          background: 'rgba(255,255,255,0.06)', border: '1px solid var(--border, rgba(255,255,255,0.1))',
                          color: 'var(--text, #fff)', borderRadius: '6px', fontSize: '0.72rem', padding: '3px 8px', cursor: 'pointer',
                        }}>
                          {[10, 15, 25, 50, 100].map((n) => <option key={n} value={n}>{n} / pagina</option>)}
                        </select>
                        <button disabled={detail.page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}
                          style={{ ...btn(true), opacity: detail.page <= 1 ? 0.4 : 1, cursor: detail.page <= 1 ? 'not-allowed' : 'pointer' }}>
                          ◄ Prec.
                        </button>
                        <span style={{ fontSize: '0.74rem', fontWeight: 800, color: 'var(--text, #fff)' }}>
                          {detail.page} / {detail.pages}
                        </span>
                        <button disabled={detail.page >= detail.pages} onClick={() => setPage((p) => p + 1)}
                          style={{ ...btn(true), opacity: detail.page >= detail.pages ? 0.4 : 1, cursor: detail.page >= detail.pages ? 'not-allowed' : 'pointer' }}>
                          Succ. ►
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Sotto-Componenti Configuratori ──────────────────────────────────────────

function ModelPicker({ models, allModels = [], total, current, search, open, activeCategory, onCategory, onSearch, onToggle, onRefresh, onPick }) {
  const catCounts = useMemo(() => {
    const map = { all: allModels.length, sigma_engine: 0, ollama: 0, local_provider: 0, cloud: 0 };
    for (const m of allModels) {
      if (m.category && map[m.category] !== undefined) {
        map[m.category] += 1;
      }
    }
    return map;
  }, [allModels]);

  const categories = [
    { id: 'all', label: `Tutti (${catCounts.all || 0})` },
    { id: 'sigma_engine', label: `⚡ SigmaEngine (${catCounts.sigma_engine || 0})` },
    { id: 'ollama', label: `🐙 Ollama (${catCounts.ollama || 0})` },
    { id: 'local_provider', label: `💻 LM Studio (${catCounts.local_provider || 0})` },
    { id: 'cloud', label: `☁️ Cloud API (${catCounts.cloud || 0})` },
  ];

  return (
    <div style={{ ...panel, display: 'flex', flexDirection: 'column', gap: '10px' }}>
      <div style={sectionTitle}><Cpu size={14} /> Modello da Valutare</div>

      {/* Scheda Selezionata */}
      <button
        type="button"
        onClick={onToggle}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px',
          background: 'rgba(0,210,255,0.08)', border: `1px solid ${ACCENT}`,
          borderRadius: '10px', padding: '10px 14px', cursor: 'pointer', width: '100%',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '0.88rem', fontWeight: 800, color: ACCENT, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {current?.name || 'Seleziona un modello...'}
            </span>
            {current?.badge && (
              <span style={{ fontSize: '0.58rem', fontWeight: 800, padding: '2px 6px', borderRadius: '4px', background: 'rgba(0,210,255,0.2)', color: ACCENT }}>
                {current.badge}
              </span>
            )}
          </div>
          <span style={{ fontSize: '0.66rem', color: 'var(--text-dark, #8b949e)', fontFamily: 'monospace', marginTop: '2px' }}>
            {current
              ? [current.provider_label, current.parameter_size, current.quantization].filter(Boolean).join(' · ')
              : 'Nessun modello selezionato'}
          </span>
        </div>
        <ChevronDown size={16} style={{ color: ACCENT, flexShrink: 0, transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
      </button>

      {/* Menu a Tendina Filtrabile */}
      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '4px' }}>
          {/* Categorie Provider */}
          <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
            {categories.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => onCategory(c.id)}
                style={{
                  ...btn(activeCategory === c.id),
                  fontSize: '0.65rem', padding: '3px 8px',
                }}
              >
                {c.label}
              </button>
            ))}
          </div>

          {/* Campo Ricerca */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: '6px',
            background: 'rgba(0,0,0,0.35)', border: '1px solid var(--border, rgba(255,255,255,0.1))',
            borderRadius: '8px', padding: '6px 10px',
          }}>
            <Search size={13} style={{ color: 'var(--text-dark, #8b949e)', flexShrink: 0 }} />
            <input
              autoFocus type="text" value={search} onChange={(e) => onSearch(e.target.value)}
              placeholder="Cerca per nome, provider o quantizzazione..."
              style={{ width: '100%', background: 'none', border: 'none', color: 'var(--text, #fff)', fontSize: '0.74rem', outline: 'none' }}
            />
          </div>

          {/* Lista Modelli */}
          <div style={{
            display: 'flex', flexDirection: 'column', gap: '3px',
            maxHeight: '220px', overflowY: 'auto',
          }}>
            {models.length === 0 ? (
              <div style={{ fontSize: '0.72rem', color: 'var(--text-dark, #8b949e)', padding: '12px', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                <span>{allModels.length === 0 ? 'Caricamento modelli in corso...' : 'Nessun modello corrisponde ai filtri.'}</span>
                {onRefresh && (
                  <button type="button" onClick={(e) => { e.stopPropagation(); onRefresh(); }} style={{ ...btn(true), fontSize: '0.66rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <RefreshCw size={11} /> Aggiorna Catalogo Modelli
                  </button>
                )}
              </div>
            ) : models.map((m) => (
              <button
                type="button" key={m.id} onClick={() => onPick(m.id)}
                style={{
                  background: current?.id === m.id ? 'rgba(0,210,255,0.18)' : 'rgba(255,255,255,0.03)',
                  border: `1px solid ${current?.id === m.id ? ACCENT : 'transparent'}`,
                  borderRadius: '7px', padding: '7px 10px', cursor: 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', textAlign: 'left',
                }}
              >
                <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                  <span style={{
                    fontSize: '0.76rem', fontWeight: current?.id === m.id ? 800 : 600,
                    color: current?.id === m.id ? ACCENT : 'var(--text, #fff)',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>{m.name}</span>
                  <span style={{ fontSize: '0.62rem', color: 'var(--text-dark, #8b949e)', fontFamily: 'monospace' }}>
                    {m.provider_label} {m.parameter_size ? `· ${m.parameter_size}` : ''} {m.quantization ? `· ${m.quantization}` : ''}
                  </span>
                </div>
                {m.badge && (
                  <span style={{
                    fontSize: '0.55rem', fontWeight: 800, padding: '2px 6px', borderRadius: '4px',
                    background: 'rgba(255,255,255,0.08)', color: 'var(--text-dark, #8b949e)', flexShrink: 0,
                  }}>{m.badge}</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      <div style={{ marginTop: 'auto', paddingTop: '6px', fontSize: '0.66rem', color: 'var(--text-dark, #8b949e)' }}>
        {total} modelli disponibili (Locali GGUF, SigmaEngine, Ollama, Cloud API).
      </div>
    </div>
  );
}

function CoveragePicker({ evalMode, sampleCount, plannedItems, suiteMode, selectedSuitesCount, onMode, onCount }) {
  const samplePresets = [25, 50, 100, 250, 500, 1000, 2500];

  return (
    <div style={{ ...panel, display: 'flex', flexDirection: 'column', gap: '10px' }}>
      <div style={sectionTitle}><Shield size={14} /> Campioni & Copertura Dataset</div>

      {/* Modalità Copertura */}
      <div style={{ display: 'flex', gap: '8px' }}>
        <button type="button" onClick={() => onMode('sample')} style={{
          flex: 1, padding: '9px 10px', borderRadius: '8px', cursor: 'pointer',
          border: `1px solid ${evalMode === 'sample' ? ACCENT : 'rgba(255,255,255,0.08)'}`,
          background: evalMode === 'sample' ? 'rgba(0,210,255,0.15)' : 'rgba(0,0,0,0.25)',
          color: evalMode === 'sample' ? ACCENT : 'var(--text-dark, #8b949e)',
          fontSize: '0.75rem', fontWeight: 700,
        }}>⚡ Campione Rapido</button>
        <button type="button" onClick={() => onMode('full')} style={{
          flex: 1, padding: '9px 10px', borderRadius: '8px', cursor: 'pointer',
          border: `1px solid ${evalMode === 'full' ? 'var(--success, #3fb950)' : 'rgba(255,255,255,0.08)'}`,
          background: evalMode === 'full' ? 'rgba(63,185,80,0.15)' : 'rgba(0,0,0,0.25)',
          color: evalMode === 'full' ? 'var(--success, #3fb950)' : 'var(--text-dark, #8b949e)',
          fontSize: '0.75rem', fontWeight: 700,
        }}>🏆 100% Integrale</button>
      </div>

      {/* Selettore Quantità Campioni */}
      {evalMode === 'sample' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '0.7rem', color: 'var(--text-dark, #8b949e)' }}>Preset Campioni:</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-dark, #8b949e)' }}>Personalizzato:</span>
              <input
                type="number" min="5" max="50000" step="25"
                value={sampleCount}
                onChange={(e) => onCount(Math.max(5, Number(e.target.value)))}
                style={{
                  width: '70px', background: 'rgba(0,0,0,0.4)', border: '1px solid var(--border, rgba(255,255,255,0.1))',
                  borderRadius: '6px', padding: '3px 6px', color: ACCENT, fontWeight: 700, fontSize: '0.74rem', textAlign: 'center', outline: 'none'
                }}
              />
            </div>
          </div>

          <div style={{ display: 'flex', gap: '5px', flexWrap: 'wrap' }}>
            {samplePresets.map((cnt) => (
              <button
                key={cnt}
                type="button"
                onClick={() => onCount(cnt)}
                style={{
                  ...btn(sampleCount === cnt),
                  fontSize: '0.68rem', padding: '4px 8px',
                }}
              >
                {cnt}
              </button>
            ))}
          </div>
        </div>
      )}

      <div style={{ marginTop: 'auto', paddingTop: '6px', fontSize: '0.68rem', color: 'var(--text-dark, #8b949e)' }}>
        {evalMode === 'full'
          ? <>Ogni singolo quesito: <b style={{ color: 'var(--text, #fff)' }}>{fmt(plannedItems)} quesiti</b> con certificato SHA-256.</>
          : <>Campione deterministico (seed 42): <b style={{ color: ACCENT }}>{fmt(plannedItems)} quesiti</b> distribuiti su {suiteMode === 'all' ? 'tutte le 11 suite' : `${selectedSuitesCount} suite selezionate`}.</>}
      </div>
    </div>
  );
}


function Summary({ label, value, hint }) {
  return (
    <div>
      <div style={{ fontSize: '0.62rem', color: 'var(--text-dark, #8b949e)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
      <div style={{ fontSize: '0.88rem', fontWeight: 800, color: 'var(--text, #fff)', maxWidth: '220px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {value}
      </div>
      {hint && <div style={{ fontSize: '0.62rem', color: 'var(--text-dark, #8b949e)' }}>{hint}</div>}
    </div>
  );
}

function StatusPill({ job }) {
  const map = {
    loading_model: { text: '⏳ VRAM LOAD', color: '#ffb86c', bg: 'rgba(255,184,108,0.2)', spin: true },
    running: { text: `${job.progress || 0}%`, color: ACCENT, bg: 'rgba(0,210,255,0.2)', spin: true },
    preparing: { text: 'PREPARO', color: ACCENT, bg: 'rgba(0,210,255,0.2)', spin: true },
    cancelling: { text: 'FERMO...', color: '#ffb86c', bg: 'rgba(255,184,108,0.2)', spin: true },
    paused: { text: `⏸️ ${job.progress || 0}%`, color: '#ffb86c', bg: 'rgba(255,184,108,0.2)' },
    completed: { text: '✓ FATTO', color: 'var(--success, #3fb950)', bg: 'rgba(63,185,80,0.2)' },
    cancelled: { text: '🟡 ANNULLATO', color: '#ffb86c', bg: 'rgba(255,184,108,0.2)' },
    interrupted: { text: '⚠ INTERROTTO', color: '#ffb86c', bg: 'rgba(255,184,108,0.2)' },
    failed: { text: '🔴 FALLITO', color: '#ff5555', bg: 'rgba(255,85,85,0.2)' },
  };
  const s = map[job.status] || { text: job.status, color: 'var(--text-dark, #8b949e)', bg: 'rgba(255,255,255,0.06)' };
  return (
    <span style={{
      fontSize: '0.58rem', fontWeight: 700, padding: '2px 7px', borderRadius: '6px',
      background: s.bg, color: s.color, display: 'flex', alignItems: 'center', gap: '4px',
      whiteSpace: 'nowrap', flexShrink: 0,
    }}>
      {s.spin && <RefreshCw size={9} className="spin-icon" />}{s.text}
    </span>
  );
}

function Metric({ label, value, color, hint }) {
  return (
    <div style={{ background: 'rgba(10,12,26,0.6)', border: '1px solid var(--border, rgba(255,255,255,0.08))', borderRadius: '10px', padding: '10px 12px' }}>
      <div style={{ fontSize: '0.62rem', color: 'var(--text-dark, #8b949e)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</div>
      <div style={{ fontSize: '1.25rem', fontWeight: 800, color, marginTop: '2px' }}>{value}</div>
      <div style={{ fontSize: '0.64rem', color: 'var(--text-dark, #8b949e)' }}>{hint}</div>
    </div>
  );
}

function QuestionCard({ result, model, number }) {
  const style = VERDICT_STYLE[result.verdict] || VERDICT_STYLE.fail;
  const parsed = result.parsed || {};
  const correct = (result.correct_choice || '').trim().toUpperCase();
  const chosen = parsed.status === 'resolved' ? (parsed.value || '').toUpperCase() : null;
  const candidates = (parsed.candidates || []).map((c) => String(c).toUpperCase());
  const compact = result.verdict === 'pass';

  return (
    <div style={{
      background: style.bg, border: `1px solid ${style.border}`, borderRadius: '10px',
      padding: compact ? '9px 12px' : '13px 15px', display: 'flex', flexDirection: 'column',
      gap: compact ? '6px' : '10px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '7px', flexWrap: 'wrap' }}>
          <span style={{ color: style.color, display: 'flex', alignItems: 'center', gap: '4px', fontWeight: 800, fontSize: '0.72rem' }}>
            <style.Icon size={14} /> {style.label}
          </span>
          <span style={{ fontSize: '0.6rem', fontWeight: 700, padding: '1px 6px', borderRadius: '4px', background: 'rgba(0,210,255,0.15)', color: ACCENT }}>
            #{number}
          </span>
          {result.suite_name && (
            <span style={{ fontSize: '0.64rem', color: 'var(--text-dark, #8b949e)', fontWeight: 600 }}>{result.suite_name}</span>
          )}
          {result.category && (
            <span style={{ fontSize: '0.64rem', color: 'var(--text-dark, #8b949e)' }}>· {result.category}</span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontFamily: 'monospace', fontSize: '0.64rem' }}>
          {result.endpoint && (
            <span style={{ color: 'var(--text-dark, #8b949e)' }}>{result.endpoint}</span>
          )}
          <span style={{ color: ACCENT }}>⚡ {result.tokens_per_sec} tok/s</span>
          <span style={{ color: '#ffb86c' }}>⏱️ {fmt(result.latency_ms)} ms</span>
          {/* Una generazione troncata da una scadenza non e' una risposta
              sbagliata del modello: e' una misura che non e' stata completata,
              e va letta come tale accanto al verdetto. */}
          {result.finish_reason === 'timeout' && (
            <span title={result.warning || 'Generazione interrotta dalla scadenza'}
              style={{ color: '#ff7b72', fontWeight: 700 }}>⏳ scaduta</span>
          )}
          {result.finish_reason === 'length' && (
            <span title="Il budget di token e' finito prima della risposta"
              style={{ color: '#ffb86c', fontWeight: 700 }}>✂️ troncata</span>
          )}
        </div>
      </div>

      <div style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text, #fff)', lineHeight: 1.4, whiteSpace: 'pre-wrap' }}>
        {result.prompt}
      </div>

      {result.options?.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '5px' }}>
          {result.options.map((opt, i) => {
            const match = opt.match(/^\s*\(?([A-Za-z0-9])[)\].:]/);
            const letter = (match ? match[1] : String.fromCharCode(65 + i)).toUpperCase();
            const isCorrect = letter === correct;
            const isChosen = chosen === letter;
            const isCandidate = !isChosen && candidates.includes(letter);

            let bg = 'rgba(10,12,26,0.6)';
            let border = 'rgba(255,255,255,0.08)';
            let color = 'var(--text-dark, #8b949e)';
            let badge = null;

            if (isCorrect) {
              bg = 'rgba(63,185,80,0.14)'; border = 'rgba(63,185,80,0.5)'; color = 'var(--success, #3fb950)';
              badge = <Badge color="var(--success, #3fb950)"><Check size={8} /> CORRETTA</Badge>;
            }
            if (isCandidate) {
              bg = 'rgba(255,184,108,0.12)'; border = 'rgba(255,184,108,0.45)'; color = '#ffb86c';
              badge = <Badge color="#ffb86c">🤖 CANDIDATA</Badge>;
            }
            if (isChosen) {
              const ok = result.verdict === 'pass';
              bg = ok ? 'rgba(63,185,80,0.22)' : 'rgba(255,85,85,0.15)';
              border = ok ? '#3fb950' : 'rgba(255,85,85,0.6)';
              color = ok ? '#3fb950' : '#ff5555';
              badge = <Badge color={color}>🤖 SCELTA {ok ? '(GIUSTA)' : '(ERRATA)'}</Badge>;
            }

            return (
              <div key={i} style={{
                background: bg, border: `1px solid ${border}`, borderRadius: '5px',
                padding: '5px 9px', fontSize: '0.72rem', color,
                fontWeight: (isCorrect || isChosen || isCandidate) ? 700 : 500,
                display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px',
              }}>
                <span>{opt}</span>
                {badge}
              </div>
            );
          })}
        </div>
      )}

      {result.execution && (
        <div style={{
          background: 'rgba(10,12,26,0.8)', border: '1px solid var(--border, rgba(255,255,255,0.08))', borderRadius: '6px',
          padding: '6px 10px', fontSize: '0.69rem', color: 'var(--text-dark, #8b949e)',
          display: 'flex', alignItems: 'center', gap: '6px', fontFamily: 'monospace',
        }}>
          <Terminal size={11} style={{ color: style.color, flexShrink: 0 }} />
          <b style={{ color: style.color }}>{result.execution.status}</b>
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {result.execution.detail}
          </span>
        </div>
      )}

      <div style={{
        background: 'rgba(10,12,26,0.7)', padding: compact ? '6px 10px' : '9px 13px',
        borderRadius: '7px', border: `1px solid ${style.border}`,
        maxHeight: compact ? '90px' : '320px', overflowY: 'auto',
      }}>
        <div style={{ fontSize: '0.58rem', fontWeight: 800, color: style.color, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '3px', display: 'flex', alignItems: 'center', gap: '4px' }}>
          <Cpu size={10} /> Risposta generata da {model}
        </div>
        <div style={{ fontSize: '0.74rem', color: 'var(--text, #fff)', fontFamily: 'monospace', whiteSpace: 'pre-wrap', lineHeight: 1.35 }}>
          {result.given_answer || result.error || '(nessuna risposta generata)'}
        </div>

        {!result.options?.length && result.correct_answer && (
          <div style={{
            marginTop: '7px', paddingTop: '6px',
            borderTop: '1px dashed rgba(255,255,255,0.12)',
          }}>
            <div style={{
              fontSize: '0.58rem', fontWeight: 800, color: 'var(--success, #3fb950)',
              textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '3px',
              display: 'flex', alignItems: 'center', gap: '4px',
            }}>
              <Check size={10} /> Risposta attesa
              {result.correct_choice && (
                <span style={{ textTransform: 'none', color: 'var(--text-dark, #8b949e)', fontWeight: 600 }}>
                  — target: <b style={{ color: 'var(--success, #3fb950)' }}>{result.correct_choice}</b>
                </span>
              )}
            </div>
            <div style={{
              fontSize: '0.73rem', color: 'var(--text-dark, #8b949e)', fontFamily: 'monospace',
              whiteSpace: 'pre-wrap', lineHeight: 1.35,
            }}>
              {String(result.correct_answer)}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Badge({ color, children }) {
  return (
    <span style={{
      fontSize: '0.55rem', fontWeight: 800, background: `${color}33`, color,
      padding: '1px 5px', borderRadius: '4px', border: `1px solid ${color}`,
      display: 'flex', alignItems: 'center', gap: '3px', whiteSpace: 'nowrap', flexShrink: 0,
    }}>
      {children}
    </span>
  );
}

