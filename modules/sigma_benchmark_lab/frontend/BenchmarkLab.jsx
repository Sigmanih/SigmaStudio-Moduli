import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  Play, CheckCircle2, XCircle, Trash2, Cpu,
  Award, RefreshCw, Shield, Download, Check, StopCircle, Search,
  RotateCcw, Layers, Compass, AlertTriangle, HelpCircle, Database, Terminal,
  Zap, ChevronDown, ChevronRight, ChevronLeft, Code, Sparkles, CheckSquare, Square, Globe, Bot, ShieldCheck,
  List, LayoutGrid, Trophy, Wrench, HardDrive
} from 'lucide-react';
import ProtocolBenchView from './ProtocolBenchView.jsx';
import TabHeader from '../../components/common/TabHeader';
import {
  getModelSpecs, detectModelFamily, isSigmanihModel, getModelChatSpeed,
  FAMILY_CONFIG
} from '../../components/Chat/core/modelSpecsHelper';
import { PROVIDER_COLORS, getProviderForModel } from '../../components/Chat/modelProviderMap';

const SUITE_LABELS = {
  all: {
    name: '🌐 Tutti i Benchmark',
    badge: 'FULL 100%',
    category: 'Valutazione Globale',
    summary: 'Tutte le 11 suite ufficiali (~60.000 quesiti complessivi)',
    description: 'Valutazione olistica e bilanciata che copre l\'intero spettro delle capacità del modello: conoscenza enciclopedica (MMLU), ragionamento accademico (MMLU-Pro, GPQA), logica multi-step (BBH), problem-solving matematico (GSM8K, MATH), programmazione ed esecuzione codice (HumanEval, MBPP), scienze applicate (ARC), buon senso situazionale (HellaSwag) e mitigazione allucinazioni (TruthfulQA).',
  },
  mmlu: {
    name: '🏆 MMLU',
    badge: '57 Materie',
    category: 'Conoscenza Generale',
    summary: 'Massive Multitask Language Understanding: 57 discipline accademiche',
    description: 'Misura la conoscenza teorica ed enciclopedica su 57 discipline suddivise in materie umanistiche, scienze sociali, STEM e ambiti professionali (diritto, medicina). Valutato a 5-shot su scelta multipla (A-D) tramite logprob senza CoT.',
  },
  mmlu_pro: {
    name: '🧠 MMLU-Pro',
    badge: 'Ragionamento Hard',
    category: 'Ragionamento Avanzato',
    summary: 'Estensione rigorosa di MMLU con 10 alternative e ragionamento CoT',
    description: 'Evoluzione più complessa e rigorosa di MMLU concepita per premiare il ragionamento analitico profondo rispetto alla memorizzazione pura. Comprende 14 discipline avanzate con opzioni ampliate fino a 10 alternative ed eliminazione dei quesiti banali. Richiede Chain-of-Thought (CoT).',
  },
  gsm8k: {
    name: '🧮 GSM8K',
    badge: 'Math',
    category: 'Matematica & Logica',
    summary: 'Grade School Math: 8.500 problemi matematici verbali multi-step',
    description: '8.500 problemi matematici formulati linguisticamente a livello di scuola primaria e media. Misura la capacità di eseguire sequenze logiche di calcoli aritmetici estraendo il numero finale dopo il ragionamento passo-passo (CoT).',
  },
  math: {
    name: '📐 MATH',
    badge: 'Olimpico',
    category: 'Matematica Avanzata',
    summary: 'Hendrycks MATH: 12.500 problemi di livello olimpico e liceale superiore',
    description: 'Include 12.500 problemi complessi tratti da competizioni matematiche (AMC 10, AMC 12, AIME) su algebra, geometria, calcolo, teoria dei numeri e probabilità. Richiede soluzioni articolate e CoT esteso ad alto budget di token con verifica esatta della formula finale.',
  },
  humaneval: {
    name: '💻 HumanEval',
    badge: 'pass@1',
    category: 'Coding & Programmazione',
    summary: '164 problemi algoritmici Python verificati con unit test ufficiali',
    description: '164 sfide algoritmiche in Python contenenti docstring, specifiche funzionali e casi limite. Il codice generato dal modello viene realmente eseguito in sandbox isolata contro i test di unità ufficiali per determinare la metrica pass@1.',
  },
  mbpp: {
    name: '🐍 MBPP',
    badge: 'pass@1',
    category: 'Coding Python',
    summary: 'Mostly Basic Python Problems: circa 1.000 funzioni pratiche eseguite',
    description: 'Circa 1.000 compiti pratici di programmazione Python di livello base/intermedio incentrati su algoritmi di manipolazione stringhe, liste e dizionari. La correttezza viene accertata eseguendo il codice generato contro le asserzioni di test ufficiali (pass@1).',
  },
  arc: {
    name: '🔬 ARC Science',
    badge: 'Scienze',
    category: 'Scienze Applicate',
    summary: 'Abstraction & Reasoning Challenge: quesiti scientifici non banali',
    description: 'Quesiti scientifici a scelta multipla (scuole medie/superiori) che filtrano le domande risolvibili per sola associazione di parole superficiale, richiedendo reale comprensione causale, fisica e biologica del mondo naturale.',
  },
  hellaswag: {
    name: '💡 HellaSwag',
    badge: 'Buon Senso',
    category: 'Buon Senso',
    summary: 'Completamento di scenari realistici con finali avversari',
    description: 'Misura il buon senso situazionale chiedendo al modello di individuare la prosecuzione più logica e plausibile di scene di vita quotidiana tra 4 opzioni generate con filtri avversari. Valutato per verosimiglianza del testo continuato.',
  },
  truthfulqa: {
    name: '🛡️ TruthfulQA',
    badge: 'Anti-Allucinazione',
    category: 'Veridicità & Safety',
    summary: '817 quesiti trabocchetto ideati per far emergere miti e allucinazioni',
    description: '817 quesiti in materie come salute, diritto, finanza e società ideati specificamente per testare se il modello cade in false credenze popolari, miti comuni o allucinazioni del pretraining anziché rispondere con fatti verificati.',
  },
  gpqa: {
    name: '🎓 GPQA',
    badge: 'Expert Level',
    category: 'Livello Accademico',
    summary: 'Google-Proof Q&A: 448 quesiti a livello di dottorato (PhD) in STEM',
    description: '448 quesiti a scelta multipla ad altissima difficoltà redatti da specialisti con PhD in biologia, fisica e chimica. Sono domande concepite per non essere risolvibili tramite ricerca web immediata e richiedono ragionamento scientifico rigoroso (CoT).',
  },
  bbh: {
    name: '⚙️ BIG-Bench Hard',
    badge: '27 Task',
    category: 'Logica Multi-Step',
    summary: 'I 27 compiti più complessi di BIG-Bench dove il CoT fa la differenza',
    description: 'Selezione dei 27 task più impegnativi di BIG-Bench (ragionamento temporale, sillogismi, manipolazione simbolica, navigazione logica) in cui i modelli necessitano di una catena passo-passo di pensiero (CoT) per superare il caso.',
  },
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
  background: 'rgba(15,18,35,0.7)',
  border: '1px solid var(--border, rgba(255,255,255,0.09))',
  borderRadius: '12px',
  padding: '14px 18px',
  backdropFilter: 'blur(10px)',
};

const panel = {
  background: 'rgba(10,12,26,0.7)',
  border: '1px solid var(--border, rgba(255,255,255,0.07))',
  borderRadius: '10px',
  padding: '10px 12px',
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

const DATASET_CATEGORIES = {
  all: { label: 'Tutte le Suite', icon: '🌐', ids: ['all', 'mmlu', 'mmlu_pro', 'gsm8k', 'math', 'humaneval', 'mbpp', 'arc', 'hellaswag', 'truthfulqa', 'gpqa', 'bbh'] },
  code: { label: 'Coding', icon: '💻', ids: ['humaneval', 'mbpp'] },
  math: { label: 'Matematica', icon: '🧮', ids: ['gsm8k', 'math'] },
  reasoning: { label: 'Ragionamento', icon: '🧠', ids: ['mmlu_pro', 'bbh', 'gpqa'] },
  knowledge: { label: 'Conoscenza & Scienze', icon: '📚', ids: ['mmlu', 'arc', 'hellaswag'] },
  safety: { label: 'Safety & Fatti', icon: '🛡️', ids: ['truthfulqa'] },
};

function formatModelDisplay(modelName) {
  if (!modelName) return '—';
  let m = String(modelName).trim();
  if (m.startsWith('sigma:')) m = m.substring(6);
  if (m === 'sigma' || m === 'test-model') {
    return 'SigmaEngine (Assegnato)';
  }
  return m;
}

export default function BenchmarkLab({ addToast, activeTabId }) {
  const [benchTab, setBenchTab] = useState('official'); // 'official' | 'protocol'
  const [models, setModels] = useState([]);
  const [modelSearch, setModelSearch] = useState('');
  const [modelOpen, setModelOpen] = useState(false);
  const [modelCategory, setModelCategory] = useState('all');
  const [selectedModel, setSelectedModel] = useState(null);
  const [speedVersion, setSpeedVersion] = useState(0);

  // Ascolta aggiornamenti live di velocità di inferenza (tokens/sec)
  useEffect(() => {
    const handleSpeedUpdated = () => setSpeedVersion((v) => v + 1);
    window.addEventListener('sigma-model-speed-updated', handleSpeedUpdated);
    return () => window.removeEventListener('sigma-model-speed-updated', handleSpeedUpdated);
  }, []);

  // Dataset / Suite Selection
  const [suiteMode, setSuiteMode] = useState('all'); // 'all' or 'custom'
  const [selectedSuites, setSelectedSuites] = useState(['mmlu', 'gsm8k', 'humaneval']);
  const [datasetCat, setDatasetCat] = useState('all');
  const [suiteViewMode, setSuiteViewMode] = useState('compact'); // 'compact' | 'detailed'
  const [suiteInfo, setSuiteInfo] = useState({});
  const [suiteTotals, setSuiteTotals] = useState({ count: 0, cached_suites: 0, total_suites: 0 });
  const [downloading, setDownloading] = useState([]);

  // Copertura & Campioni
  const [evalMode, setEvalMode] = useState('sample'); // 'full' or 'sample'
  const [sampleCount, setSampleCount] = useState(100);
  const [thinkingMode, setThinkingMode] = useState('auto'); // 'auto', 'thinking', 'no_thinking'
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
  const [selectedResultIndex, setSelectedResultIndex] = useState(0);
  const [questionViewMode, setQuestionViewMode] = useState('compact'); // 'compact' | 'cards'


  // Ampliamento Benchmark
  const [extendModalOpen, setExtendModalOpen] = useState(false);
  const [extendSamples, setExtendSamples] = useState(25);
  const [extendSuite, setExtendSuite] = useState('all');
  const [extendMode, setExtendMode] = useState('sample');
  const [extendThinkingMode, setExtendThinkingMode] = useState('auto');
  const [extending, setExtending] = useState(false);

  const toast = useCallback((msg, kind) => { if (addToast) addToast(msg, kind); }, [addToast]);

  const post = useCallback((path, body) => fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => r.json()), []);

  // Risoluzione ed estetica del nome del modello: mai "test-model" o "sigma" anonimo
  const formatJobModel = useCallback((modelName) => {
    if (!modelName) return '—';
    let m = String(modelName).trim();
    if (m.startsWith('sigma:')) m = m.substring(6);
    if (m === 'sigma' || m === 'test-model') {
      const pEntry = models.find((mod) => mod.id === 'sigma' || mod.is_proxy);
      if (pEntry?.resolved_target) {
        let rt = pEntry.resolved_target;
        if (rt.startsWith('sigma:')) rt = rt.substring(6);
        return rt;
      }
      return 'SigmaEngine (Assegnato)';
    }
    return m;
  }, [models]);

  // ── Caricamenti ────────────────────────────────────────────────────────────

  const loadModels = useCallback(async () => {
    try {
      const res = await fetch(`/api/training/benchmark/models?_t=${Date.now()}`, { cache: 'no-store' });
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
      const res = await fetch(`/api/training/benchmark/jobs?_t=${Date.now()}`, { cache: 'no-store' });
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
      const res = await fetch(`/api/training/benchmark/suite_info?suite=all&_t=${Date.now()}`, { cache: 'no-store' });
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

  // Ricarica automatica all'entrata nella tab o al cambio tab interno
  useEffect(() => {
    loadModels();
    loadJobs();
    loadSuiteInfo();
  }, [activeTabId, benchTab, loadModels, loadJobs, loadSuiteInfo]);

  // Aggiornamento immediato al focus della finestra o al ripristino della tab (visibilitychange)
  useEffect(() => {
    const handleRefreshNow = () => {
      if (document.visibilityState === 'visible') {
        loadModels();
        loadJobs();
        loadSuiteInfo();
      }
    };
    window.addEventListener('focus', handleRefreshNow);
    document.addEventListener('visibilitychange', handleRefreshNow);
    return () => {
      window.removeEventListener('focus', handleRefreshNow);
      document.removeEventListener('visibilitychange', handleRefreshNow);
    };
  }, [loadModels, loadJobs, loadSuiteInfo]);

  // Polling periodico in background ogni 4 secondi per mantenere sempre freschi i benchmark
  useEffect(() => {
    const backgroundTimer = setInterval(() => {
      loadJobs();
      if (benchTab === 'official') {
        loadModels();
      }
    }, 4000);
    return () => clearInterval(backgroundTimer);
  }, [loadJobs, loadModels, benchTab]);

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

  useEffect(() => { setPage(1); setSelectedResultIndex(0); }, [selectedJobId, verdictFilter, suiteFilter, pageSize]);
  useEffect(() => { setSelectedResultIndex(0); }, [page]);


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
        thinking_mode: thinkingMode,
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

  const handleRerunJob = async (jobItem, e) => {
    if (e) e.stopPropagation();
    if (!jobItem?.id || !jobItem?.model) return;
    toast(`🔄 Riesecuzione benchmark su ${jobItem.model} (stessi quesiti)...`, 'info');
    try {
      const res = await post('/api/training/benchmark/rerun_suite', {
        id: jobItem.id,
        suite: 'all',
        concurrency: 'auto',
      });
      if (res.success) {
        toast(`🚀 Valutazione riavviata su ${jobItem.model}! Aggiornamento risultati in corso...`, 'success');
        setSelectedJobId(jobItem.id);
        loadJobs();
        loadDetail();
      } else {
        toast(`❌ ${res.error || 'Riesecuzione fallita'}`, 'error');
      }
    } catch (err) {
      toast(`❌ Errore riesecuzione: ${err.message}`, 'error');
    }
  };

  const handleRerunSuite = async (suiteKey, e) => {
    if (e) e.stopPropagation();
    if (!activeJob?.id || !activeJob?.model) { toast('⚠️ Benchmark o modello non selezionato', 'warning'); return; }
    const sKey = (suiteKey || suiteFilter || 'all').toLowerCase().replace('-', '_');
    const suiteName = SUITE_LABELS[sKey]?.name || sKey.toUpperCase();
    toast(`🔄 Riesecuzione su ${activeJob.model} per la suite ${suiteName} (stessi quesiti)...`, 'info');
    try {
      const res = await post('/api/training/benchmark/rerun_suite', {
        id: activeJob.id,
        suite: sKey,
        concurrency: 'auto'
      });
      if (res.success) {
        toast(`🚀 Valutazione ${suiteName} riavviata con successo! Aggiornamento risultati in corso...`, 'success');
        loadJobs();
        loadDetail();
      } else {
        toast(`❌ ${res.error || 'Riesecuzione suite fallita'}`, 'error');
      }
    } catch (err) {
      toast(`❌ Errore riesecuzione: ${err.message}`, 'error');
    }
  };

  const handleExtendBenchmark = async () => {
    if (!activeJob) return;
    setExtending(true);
    try {
      const targetSuite = extendSuite === 'all' ? (activeJob.suite || 'all') : extendSuite;
      const res = await post('/api/training/benchmark/extend', {
        id: activeJob.id,
        samples: extendMode === 'full' ? 0 : extendSamples,
        suite: targetSuite,
        mode: extendMode,
        concurrency: 'auto',
        thinking_mode: extendThinkingMode,
      });
      if (!res.success) {
        toast(`❌ ${res.error || 'Ampliamento non riuscito'}`, 'error');
        return;
      }
      const thLabel = extendThinkingMode === 'thinking' ? 'CoT' : extendThinkingMode === 'no_thinking' ? 'No-Think' : 'Auto';
      toast(`🚀 Benchmark in ampliamento (+${extendMode === 'full' ? 'Tutti i rimanenti' : `${extendSamples}`} quesiti [${thLabel}])!`, 'success');
      setExtendModalOpen(false);
      loadJobs();
      loadDetail();
    } catch (err) {
      toast(`❌ Errore ampliamento: ${err.message}`, 'error');
    } finally {
      setExtending(false);
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
    <div className="bench-lab-root">

      {/* Intestazione Universale Kernel Sigma Studio con Switcher Integrato */}
      <TabHeader
        icon={benchTab === 'protocol' ? Bot : Award}
        title="Benchmark Lab"
        highlight={benchTab === 'protocol' ? 'COLLAUDO TOOL' : 'VALUTAZIONE UFFICIALE'}
        tabs={[
          { id: 'official', label: 'Benchmark Ufficiali', icon: Award, active: benchTab === 'official', onClick: () => setBenchTab('official') },
          { id: 'protocol', label: 'Aderenza Protocollo Tool', icon: Bot, active: benchTab === 'protocol', onClick: () => setBenchTab('protocol') }
        ]}
        description={benchTab === 'protocol'
          ? '10 Prove Osservabili nel Transcript · Harness Pilotability Check · Zero Quiz · Solo Fatti sul Disco'
          : `11 Benchmark Ufficiali (MMLU, GSM8K, HumanEval...) · ${fmt(suiteTotals.count)} quesiti disponibili · SigmaEngine & Multi-Provider`}
        actions={
          <button
            onClick={() => { loadModels(); loadJobs(); loadSuiteInfo(); }}
            title="Ricarica i dati dei job e dei modelli da backend"
            style={{
              background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)',
              borderRadius: '6px', padding: '4px 10px', color: 'var(--text, #fff)', cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.72rem', fontWeight: 600,
            }}
          >
            <RefreshCw size={12} />
            <span>Aggiorna Dati</span>
          </button>
        }
      />

      <div className="bench-lab-content">
        {/* Vista Aderenza Protocollo */}
      {benchTab === 'protocol' ? (
        <ProtocolBenchView models={models} onToast={toast} activeTabId={activeTabId} benchTab={benchTab} />
      ) : (
        <>
          {/* Sezione 1: Selezione Dataset e Benchmark Compatta */}
          <div className="bench-card" style={{ padding: '10px 14px', gap: '8px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Database size={15} style={{ color: ACCENT }} />
                <span style={{ fontSize: '0.86rem', fontWeight: 800, color: 'var(--text, #fff)' }}>
                  Dataset di Valutazione
                </span>
                <span style={{ fontSize: '0.62rem', padding: '1px 6px', borderRadius: '4px', background: 'rgba(0,210,255,0.15)', color: '#00f2fe', fontWeight: 700, fontFamily: 'monospace' }}>
                  {suiteTotals.cached_suites}/{suiteTotals.total_suites} pronte ({fmt(suiteTotals.count)})
                </span>
              </div>

              {/* Azioni Rapide per Dataset & Toggle Vista */}
              <div style={{ display: 'flex', gap: '5px', alignItems: 'center', flexWrap: 'wrap' }}>
                <button
                  type="button"
                  onClick={() => setSuiteViewMode((v) => v === 'compact' ? 'detailed' : 'compact')}
                  style={{ ...btn(false), padding: '3px 8px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: '4px' }}
                  title="Alterna tra visualizzazione a chip compatte e schede dettagliate"
                >
                  {suiteViewMode === 'compact' ? <LayoutGrid size={11} /> : <List size={11} />}
                  {suiteViewMode === 'compact' ? 'Dettagli' : 'Compatto'}
                </button>
                <button
                  type="button"
                  onClick={() => { setSuiteMode('all'); setSelectedSuites(SUITE_ORDER.filter((s) => s !== 'all')); }}
                  style={{ ...btn(suiteMode === 'all'), padding: '3px 8px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: '4px' }}
                >
                  <Globe size={11} /> Tutte ({fmt(suiteTotals.count)})
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setSuiteMode('custom');
                    setSelectedSuites((prev) => prev.length === SUITE_ORDER.filter((s) => s !== 'all').length ? [] : SUITE_ORDER.filter((s) => s !== 'all'));
                  }}
                  style={{ ...btn(false), padding: '3px 8px', fontSize: '0.65rem', border: '1px solid rgba(255,255,255,0.12)' }}
                >
                  {selectedSuites.length === SUITE_ORDER.filter((s) => s !== 'all').length ? 'Deseleziona' : 'Seleziona'}
                </button>
                <button
                  type="button"
                  onClick={() => handleDownload('all', 300)}
                  disabled={downloading.length > 0}
                  title="Prende le prime 300 righe di ogni suite per un assaggio rapido."
                  style={{
                    ...btn(false), padding: '3px 8px', fontSize: '0.65rem',
                    border: '1px solid rgba(255,184,108,0.4)', color: '#ffb86c',
                    background: 'rgba(255,184,108,0.1)', fontWeight: 700,
                    cursor: downloading.length > 0 ? 'wait' : 'pointer',
                  }}
                >
                  {downloading.includes('all') ? '⏳' : '⚡ Assaggio'}
                </button>
                <button
                  type="button"
                  onClick={() => handleDownload('all')}
                  disabled={downloading.length > 0}
                  title="Scarica tutte le suite non ancora presenti in cache."
                  style={{
                    ...btn(false), padding: '3px 8px', fontSize: '0.65rem',
                    border: '1px solid rgba(0,210,255,0.4)', color: ACCENT,
                    background: 'rgba(0,210,255,0.1)', fontWeight: 700,
                    cursor: downloading.length > 0 ? 'wait' : 'pointer',
                  }}
                >
                  {downloading.includes('all') ? '⏳' : '📥 Scarica Tutte'}
                </button>
              </div>
            </div>

            {/* Filtri di Categoria per Suite */}
            <div className="bench-category-bar" style={{ gap: '4px' }}>
              {Object.entries(DATASET_CATEGORIES).map(([catKey, cat]) => (
                <button
                  key={catKey}
                  type="button"
                  onClick={() => setDatasetCat(catKey)}
                  className={`bench-cat-pill ${datasetCat === catKey ? 'active' : ''}`}
                  style={{ padding: '2px 8px', fontSize: '0.64rem' }}
                >
                  <span>{cat.icon}</span> {cat.label}
                </button>
              ))}
            </div>

            {/* Vista Compatta a Chip (Default) */}
            {suiteViewMode === 'compact' ? (
              <div className="bench-suite-chips-grid">
                {SUITE_ORDER
                  .filter((id) => datasetCat === 'all' || DATASET_CATEGORIES[datasetCat]?.ids.includes(id))
                  .map((id) => {
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
                        className={`bench-suite-chip ${isSelected ? 'selected' : ''}`}
                        title={`${label.name} (${label.category})\n\n${label.description}\n\nDataset: ${label.summary}`}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', minWidth: 0, flex: 1 }}>
                          {suiteMode === 'custom' && id !== 'all' && (
                            <div style={{
                              width: '13px', height: '13px', borderRadius: '3px', flexShrink: 0,
                              background: isSelected ? ACCENT : 'rgba(255,255,255,0.08)',
                              display: 'flex', alignItems: 'center', justifyContent: 'center',
                              border: `1px solid ${isSelected ? ACCENT : 'rgba(255,255,255,0.15)'}`,
                            }}>
                              {isSelected && <Check size={9} color="#000" strokeWidth={3} />}
                            </div>
                          )}
                          <span style={{ fontSize: '0.74rem', fontWeight: 700, color: isSelected ? '#00f2fe' : '#ffffff', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {label.name}
                          </span>
                          <span style={{ fontSize: '0.55rem', fontWeight: 600, color: isSelected ? '#00f2fe' : 'var(--sigma-text-dim, #8b949e)', background: 'rgba(255,255,255,0.06)', padding: '1px 4px', borderRadius: '3px', flexShrink: 0 }}>
                            {label.badge}
                          </span>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: '5px', flexShrink: 0 }}>
                          {info.cached ? (
                            <span style={{ fontSize: '0.62rem', color: info.complete === false ? '#ffb86c' : 'var(--success, #3fb950)', fontWeight: 600 }}>
                              {fmt(info.count)} {info.complete === false ? '⚡' : '✓'}
                            </span>
                          ) : (
                            <span style={{ fontSize: '0.62rem', color: '#8b949e' }}>—</span>
                          )}

                          {id !== 'all' && (!info.cached || info.needs_refresh || info.complete === false) && (
                            <button
                              type="button"
                              onClick={(e) => { e.stopPropagation(); handleDownload(id); }}
                              disabled={busy}
                              title={info.complete === false ? 'Completa' : info.cached ? 'Aggiorna' : 'Scarica'}
                              style={{
                                background: 'none', border: 'none', padding: '1px 3px', cursor: busy ? 'wait' : 'pointer',
                                color: info.needs_refresh ? '#ffb86c' : ACCENT, display: 'flex', alignItems: 'center'
                              }}
                            >
                              {busy ? '⏳' : <Download size={11} />}
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
              </div>
            ) : (
              /* Vista Dettagliata (Card estese) */
              <div className="bench-suite-grid">
                {SUITE_ORDER
                  .filter((id) => datasetCat === 'all' || DATASET_CATEGORIES[datasetCat]?.ids.includes(id))
                  .map((id) => {
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
                        className={`bench-suite-card ${isSelected ? 'selected' : ''}`}
                        title={`${label.name} (${label.category})\n\n${label.description}\n\nDataset: ${label.summary}`}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0, flex: 1 }}>
                            {suiteMode === 'custom' && id !== 'all' ? (
                              <div style={{
                                width: '16px', height: '16px', borderRadius: '4px', flexShrink: 0,
                                background: isSelected ? ACCENT : 'rgba(255,255,255,0.08)',
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                border: `1px solid ${isSelected ? ACCENT : 'rgba(255,255,255,0.15)'}`,
                              }}>
                                {isSelected && <Check size={11} color="#000" strokeWidth={3} />}
                              </div>
                            ) : null}
                            <span style={{ fontSize: '0.84rem', fontWeight: 800, color: isSelected ? '#00f2fe' : '#ffffff', wordBreak: 'break-word', overflowWrap: 'anywhere' }}>
                              {label.name}
                            </span>
                          </div>
                          <span style={{
                            fontSize: '0.58rem', fontWeight: 700, padding: '2px 7px', borderRadius: '5px',
                            background: isSelected ? 'rgba(0,210,255,0.22)' : 'rgba(255,255,255,0.06)',
                            color: isSelected ? '#00f2fe' : 'var(--sigma-text-dim, #8b949e)', whiteSpace: 'nowrap',
                          }}>
                            {label.badge}
                          </span>
                        </div>

                        <div style={{
                          fontSize: '0.68rem', color: isSelected ? 'rgba(255,255,255,0.85)' : 'var(--sigma-text-dim, #8b949e)',
                          lineHeight: '1.35', wordBreak: 'break-word', overflowWrap: 'anywhere',
                        }}>
                          {label.summary}
                        </div>

                        <div style={{ fontSize: '0.68rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 'auto', paddingTop: '4px' }}>
                          {info.cached ? (
                            <span style={{ color: info.complete === false ? '#ffb86c' : 'var(--success, #3fb950)', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '4px' }}>
                              <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: info.complete === false ? '#ffb86c' : 'var(--success, #3fb950)' }} />
                              {fmt(info.count)} quesiti{info.complete === false ? ' · parziale' : ' pronti'}
                            </span>
                          ) : (
                            <span style={{ color: '#8b949e', display: 'flex', alignItems: 'center', gap: '4px' }}>
                              <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#8b949e' }} />
                              Non in cache
                            </span>
                          )}

                          {id !== 'all' && (
                            <button
                              onClick={(e) => { e.stopPropagation(); handleDownload(id); }}
                              disabled={busy}
                              style={{
                                background: info.needs_refresh ? 'rgba(255,184,108,0.14)' : 'rgba(0,210,255,0.12)',
                                border: `1px solid ${info.needs_refresh ? 'rgba(255,184,108,0.4)' : 'rgba(0,210,255,0.35)'}`,
                                borderRadius: '6px', padding: '2px 8px',
                                color: info.needs_refresh ? '#ffb86c' : ACCENT,
                                fontSize: '0.62rem', fontWeight: 700, cursor: busy ? 'wait' : 'pointer',
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
            )}
          </div>

          {/* Sezione 2: Configurazione Modello e Campioni Compatta */}
          <div className={`bench-card ${modelOpen ? 'bench-card-dropdown-active' : ''}`} style={{ padding: '10px 14px', gap: '10px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
              <h3 style={{ margin: 0, fontSize: '0.86rem', fontWeight: 800, color: 'var(--text, #fff)', display: 'flex', alignItems: 'center', gap: '7px' }}>
                <Compass size={15} style={{ color: ACCENT }} /> Configura & Avvia Valutazione
              </h3>
              <span style={{ fontSize: '0.64rem', color: 'var(--sigma-text-dim, #8b949e)' }}>
                Seleziona modello, quota campioni e modalità CoT
              </span>
            </div>

            {/* Trio Configurazione: Modello, Campioni, Thinking */}
            <div className="bench-config-trio">
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

              <CoveragePicker
                evalMode={evalMode}
                sampleCount={sampleCount}
                plannedItems={plannedItems}
                suiteMode={suiteMode}
                selectedSuitesCount={selectedSuites.length}
                onMode={setEvalMode}
                onCount={setSampleCount}
              />

              <ThinkingPicker
                thinkingMode={thinkingMode}
                onThinkingMode={setThinkingMode}
              />
            </div>

            {/* Mission Bar: KPI e Avvio Compatto */}
            <div className="bench-mission-bar">
              <div className="bench-mission-kpis">
                <div className="bench-mission-kpi">
                  <span className="kpi-label">Modello</span>
                  <span className="kpi-val" style={{ color: '#00f2fe' }}>{currentModel?.name || '—'}</span>
                </div>
                <div className="bench-mission-kpi">
                  <span className="kpi-label">Suite</span>
                  <span className="kpi-val">{suiteMode === 'all' ? 'Tutte (11 Suite)' : `${selectedSuites.length} Selezionate`}</span>
                </div>
                <div className="bench-mission-kpi">
                  <span className="kpi-label">Quesiti</span>
                  <span className="kpi-val" style={{ color: 'var(--success, #3fb950)' }}>{fmt(plannedItems)}</span>
                </div>
                <div className="bench-mission-kpi">
                  <span className="kpi-label">Thinking Mode</span>
                  <span className="kpi-val" style={{ color: thinkingMode === 'thinking' ? '#bc8cff' : thinkingMode === 'no_thinking' ? '#ffb86c' : '#00d2ff' }}>
                    {thinkingMode === 'auto' ? '🧠 Auto' : thinkingMode === 'thinking' ? '💡 CoT' : '⚡ No-Think'}
                  </span>
                </div>
                <div className="bench-mission-kpi">
                  <span className="kpi-label">Stima Tempo</span>
                  <span className="kpi-val" style={{ color: '#ffb86c' }}>{estimate || '—'}</span>
                </div>
              </div>

              <div className="bench-mission-actions">
                {hasActiveJobs && (
                  <button onClick={handleCancelAll} className="bench-btn-cancel-compact">
                    <StopCircle size={14} /> Ferma
                  </button>
                )}
                <button
                  onClick={() => handleStart()}
                  disabled={!canLaunch}
                  className="bench-btn-start-compact"
                >
                  {launching
                    ? <><RefreshCw size={14} className="spin-icon" /> Avvio...</>
                    : <><Play size={14} /> Avvia Valutazione Benchmark</>}
                </button>
              </div>
            </div>
          </div>

      {/* Sezione 3: Cronologia Job & Ispezione Risultati */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(340px, 440px) 1fr', gap: '14px', alignItems: 'start' }}>
        {/* Lista Job Eseguiti */}
        <div style={{ ...card, padding: '14px', display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '820px', overflowY: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '8px' }}>
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
                borderRadius: '10px', padding: '10px 12px', cursor: 'pointer',
                display: 'flex', flexDirection: 'column', gap: '6px',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '6px' }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text, #fff)', wordBreak: 'break-word', overflowWrap: 'anywhere', lineHeight: '1.3' }}>
                      {formatJobModel(j.model)}
                    </div>
                    {(() => {
                      const sKey = (j.suite || '').toLowerCase().replace('-', '_');
                      const sLabel = SUITE_LABELS[sKey] || (j.suite === 'all' ? SUITE_LABELS.all : null);
                      return (
                        <div
                          style={{ fontSize: '0.68rem', color: ACCENT, fontWeight: 600, cursor: 'help' }}
                          title={sLabel ? `${sLabel.name} (${sLabel.category}):\n${sLabel.description}` : (j.suite_name || j.suite)}
                        >
                          {j.suite_name || j.suite}
                        </div>
                      );
                    })()}
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                    {j.thinking_mode === 'no_thinking' && (
                      <span style={{ fontSize: '0.6rem', padding: '1px 5px', borderRadius: '4px', background: 'rgba(255,184,108,0.15)', color: '#ffb86c', fontWeight: 700 }} title="No-Thinking (Risposta diretta)">
                        ⚡ No-Think
                      </span>
                    )}
                    {j.thinking_mode === 'thinking' && (
                      <span style={{ fontSize: '0.6rem', padding: '1px 5px', borderRadius: '4px', background: 'rgba(188,140,255,0.15)', color: '#bc8cff', fontWeight: 700 }} title="Thinking (Forzato CoT)">
                        💡 CoT
                      </span>
                    )}
                    {j.thinking_mode === 'mixed' && (
                      <span style={{ fontSize: '0.6rem', padding: '1px 5px', borderRadius: '4px', background: 'rgba(0,210,255,0.2)', color: '#00f2fe', fontWeight: 700 }} title="Ibrido (Test eseguiti sia con che senza thinking)">
                        🔀 Ibrido
                      </span>
                    )}
                    <StatusPill job={j} />
                  </div>
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
                  {jm.no_thinking_total > 0 && <span style={{ color: '#ffb86c' }}> · ⚡{jm.no_thinking_accuracy}%</span>}
                  {jm.thinking_total > 0 && <span style={{ color: '#bc8cff' }}> · 💡{jm.thinking_accuracy}%</span>}
                  {jm.tests_review > 0 && <span style={{ color: '#ffb86c' }}> · {fmt(jm.tests_review)} rev.</span>}
                  {j.concurrency > 1 && <span> · {j.concurrency}x</span>}
                </div>

                <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                  {j.status === 'running' && (
                    <button onClick={(e) => jobAction('/api/training/benchmark/pause', j.id, '⏸️ In pausa', e)}
                      style={{ ...btn(true, '#ffb86c'), fontSize: '0.58rem' }}>⏸️ Pausa</button>
                  )}
                  {(j.status === 'paused' || ((j.status === 'failed' || j.status === 'interrupted') && (j.metrics?.tests_total || 0) < (j.items_planned || 1))) && (
                    <button onClick={(e) => jobAction('/api/training/benchmark/resume', j.id, '▶️ Ripresa', e)}
                      style={{ ...btn(true, '#3fb950'), fontSize: '0.58rem' }}
                      title="Riprendi l'esecuzione dei quesiti mancanti">▶️ Riprendi</button>
                  )}
                  {isActive && (
                    <button onClick={(e) => jobAction('/api/training/benchmark/cancel', j.id, '🛑 Annullato', e)}
                      style={{ ...btn(true, '#ff5555'), fontSize: '0.58rem' }}>🛑 Ferma</button>
                  )}
                  {!isActive && (
                    <button onClick={(e) => handleRerunJob(j, e)}
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
                    <h3 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 800, color: 'var(--text, #fff)' }}>{formatJobModel(activeJob.model)}</h3>
                    {(() => {
                      const sKey = (activeJob.suite || '').toLowerCase().replace('-', '_');
                      const sMeta = SUITE_LABELS[sKey] || (activeJob.suite === 'all' ? SUITE_LABELS.all : null);
                      return (
                        <span
                          style={{ fontSize: '0.68rem', padding: '2px 8px', borderRadius: '6px', background: 'rgba(0,210,255,0.15)', color: ACCENT, fontWeight: 700, cursor: 'help' }}
                          title={sMeta ? `${sMeta.name} (${sMeta.category}):\n\n${sMeta.description}` : undefined}
                        >
                          {activeJob.suite_name || activeJob.suite}
                        </span>
                      );
                    })()}
                    {repro.reproducible_hash && (
                      <span style={{ fontSize: '0.62rem', padding: '2px 8px', borderRadius: '6px', background: 'rgba(63,185,80,0.15)', color: 'var(--success, #3fb950)', fontWeight: 600, fontFamily: 'monospace' }}>
                        {repro.reproducible_hash}
                      </span>
                    )}
                    {(repro.thinking_mode || activeJob.thinking_mode) && (
                      <span style={{
                        fontSize: '0.62rem', padding: '2px 8px', borderRadius: '6px',
                        background: (repro.thinking_mode || activeJob.thinking_mode) === 'no_thinking'
                          ? 'rgba(255,184,108,0.15)'
                          : (repro.thinking_mode || activeJob.thinking_mode) === 'thinking'
                            ? 'rgba(188,140,255,0.15)'
                            : (repro.thinking_mode || activeJob.thinking_mode) === 'mixed'
                              ? 'rgba(0,210,255,0.2)'
                              : 'rgba(0,210,255,0.12)',
                        color: (repro.thinking_mode || activeJob.thinking_mode) === 'no_thinking'
                          ? '#ffb86c'
                          : (repro.thinking_mode || activeJob.thinking_mode) === 'thinking'
                            ? '#bc8cff'
                            : (repro.thinking_mode || activeJob.thinking_mode) === 'mixed'
                              ? '#00f2fe'
                              : ACCENT,
                        fontWeight: 700,
                      }}>
                        {(repro.thinking_mode || activeJob.thinking_mode) === 'no_thinking'
                          ? '⚡ No-Thinking (Risposta diretta)'
                          : (repro.thinking_mode || activeJob.thinking_mode) === 'thinking'
                            ? '💡 Thinking (CoT forzato)'
                            : (repro.thinking_mode || activeJob.thinking_mode) === 'mixed'
                              ? '🔀 Ibrido (Thinking + No-Thinking)'
                              : '🧠 Thinking Auto (Protocollo Suite)'}
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
                      {Object.values(repro.protocols).map((p) => {
                        const sKey = (p.suite || '').toLowerCase().replace('-', '_');
                        const sMeta = SUITE_LABELS[sKey];
                        return (
                          <span key={p.suite}
                            title={sMeta ? `${sMeta.name} (${sMeta.category}):\n${sMeta.description}\n\nProtocollo: ${p.note || p.metric}` : p.note}
                            style={{
                              fontSize: '0.58rem', padding: '2px 6px', borderRadius: '5px',
                              background: 'rgba(255,255,255,0.05)',
                              color: 'var(--text-dark, #8b949e)', whiteSpace: 'nowrap',
                              cursor: 'help',
                            }}>
                            {p.suite}: {p.metric}{p.shots ? ` · ${p.shots}-shot` : ''}{p.thinking ? ' · CoT' : ''}
                          </span>
                        );
                      })}
                    </div>
                  )}
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                  {((activeJob.status === 'paused' || activeJob.status === 'failed' || activeJob.status === 'interrupted') && (activeJob.metrics?.tests_total || 0) < (activeJob.items_planned || 1)) && (
                    <button
                      type="button"
                      disabled={isRunning || extending}
                      onClick={(e) => jobAction('/api/training/benchmark/resume', activeJob.id, '▶️ Ripresa Benchmark', e)}
                      style={{
                        ...btn(true, '#3fb950'),
                        display: 'flex', alignItems: 'center', gap: '6px',
                        background: 'linear-gradient(135deg, rgba(63,185,80,0.3) 0%, rgba(46,160,67,0.2) 100%)',
                        border: '1px solid rgba(63,185,80,0.7)',
                        color: '#fff', fontWeight: 800,
                        boxShadow: '0 2px 12px rgba(63,185,80,0.25)',
                        cursor: isRunning || extending ? 'not-allowed' : 'pointer',
                        opacity: isRunning || extending ? 0.5 : 1,
                      }}
                      title={`Riprendi l'esecuzione dal quesito ${(activeJob.metrics?.tests_total || 0) + 1} fino a ${activeJob.items_planned || 'fine'} senza perdere i quesiti già valutati`}
                    >
                      <Play size={13} fill="currentColor" /> ▶️ Riprendi Benchmark ({fmt(activeJob.metrics?.tests_total || 0)}/{fmt(activeJob.items_planned || '?')})
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={isRunning || extending}
                    onClick={() => {
                      setExtendSuite('all');
                      setExtendThinkingMode(activeJob?.thinking_mode === 'mixed' ? 'auto' : (activeJob?.thinking_mode || 'auto'));
                      setExtendModalOpen(true);
                    }}
                    style={{
                      ...btn(true, '#00d2ff'),
                      display: 'flex', alignItems: 'center', gap: '6px',
                      background: 'linear-gradient(135deg, rgba(0,210,255,0.25) 0%, rgba(188,140,255,0.25) 100%)',
                      border: '1px solid rgba(0,210,255,0.6)',
                      color: '#fff', fontWeight: 700,
                      boxShadow: '0 2px 10px rgba(0,210,255,0.2)',
                      cursor: isRunning || extending ? 'not-allowed' : 'pointer',
                      opacity: isRunning || extending ? 0.5 : 1,
                    }}
                    title="Aggiungi altri quesiti a questo benchmark senza ripetere quelli già fatti"
                  >
                    <Sparkles size={13} color="#00f2fe" /> ➕ Amplia Benchmark
                  </button>
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
                {(metrics.no_thinking_total > 0 || (repro.thinking_mode || activeJob.thinking_mode) === 'no_thinking') && (
                  <Metric
                    label="⚡ No-Thinking"
                    value={`${metrics.no_thinking_accuracy ?? (activeJob.thinking_mode === 'no_thinking' ? metrics.overall_score : 0)}%`}
                    color="#ffb86c"
                    hint={`${fmt(metrics.no_thinking_passed ?? (activeJob.thinking_mode === 'no_thinking' ? metrics.tests_passed : 0))}/${fmt(metrics.no_thinking_total ?? (activeJob.thinking_mode === 'no_thinking' ? metrics.tests_total : 0))} quesiti diretti`}
                  />
                )}
                {(metrics.thinking_total > 0 || (repro.thinking_mode || activeJob.thinking_mode) === 'thinking') && (
                  <Metric
                    label="💡 Thinking CoT"
                    value={`${metrics.thinking_accuracy ?? (activeJob.thinking_mode === 'thinking' ? metrics.overall_score : 0)}%`}
                    color="#bc8cff"
                    hint={`${fmt(metrics.thinking_passed ?? (activeJob.thinking_mode === 'thinking' ? metrics.tests_passed : 0))}/${fmt(metrics.thinking_total ?? (activeJob.thinking_mode === 'thinking' ? metrics.tests_total : 0))} quesiti CoT`}
                  />
                )}
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

              {/* Ripartizione per Dataset / Suite Interattiva */}
              {detail?.suite_breakdown && Object.keys(detail.suite_breakdown).length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '7px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                    <div style={{ fontSize: '0.68rem', fontWeight: 700, color: 'var(--text-dark, #8b949e)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <Database size={13} style={{ color: ACCENT }} />
                      <span>Dataset nel Benchmark (clicca su una suite per visualizzare solo i suoi test):</span>
                    </div>
                    {suiteFilter !== 'all' && (
                      <button
                        type="button"
                        onClick={() => setSuiteFilter('all')}
                        style={{
                          background: 'rgba(0,210,255,0.12)', border: '1px solid rgba(0,210,255,0.35)',
                          borderRadius: '6px', padding: '2px 8px', fontSize: '0.64rem', color: ACCENT,
                          fontWeight: 700, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '4px',
                        }}
                      >
                        ✕ Mostra tutti i dataset
                      </button>
                    )}
                  </div>

                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    {Object.entries(detail.suite_breakdown).map(([name, stats]) => {
                      const sKey = name.toLowerCase().replace('-', '_');
                      const isSelected = suiteFilter.toLowerCase().replace('-', '_') === sKey;
                      const pct = stats.total ? Math.round((stats.passed / stats.total) * 100) : 0;
                      const meta = SUITE_LABELS[sKey] || { name: name.toUpperCase() };

                      return (
                        <div
                          key={name}
                          onClick={() => setSuiteFilter((prev) => (prev.toLowerCase().replace('-', '_') === sKey ? 'all' : sKey))}
                          title={meta.description ? `${meta.name} (${meta.category}):\n\n${meta.description}\n\nClicca per filtrare i quesiti di questo dataset.` : `Clicca per filtrare solo i test di ${name}`}
                          style={{
                            background: isSelected ? 'rgba(0,210,255,0.22)' : 'rgba(10,12,26,0.75)',
                            border: `1px solid ${isSelected ? ACCENT : 'rgba(255,255,255,0.1)'}`,
                            boxShadow: isSelected ? '0 0 14px rgba(0,210,255,0.35)' : 'none',
                            borderRadius: '8px', padding: '6px 12px', fontSize: '0.72rem',
                            color: isSelected ? '#fff' : 'var(--text-dark, #8b949e)',
                            cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px',
                            transition: 'all 0.2s ease',
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                            <b style={{ color: isSelected ? '#00f2fe' : 'var(--text, #fff)' }}>{meta.name || name}</b>:
                            <span style={{ color: pct >= 50 ? 'var(--success, #3fb950)' : '#ff5555', fontWeight: 700 }}>
                              {stats.passed}/{stats.total} ({pct}%)
                            </span>
                            {stats.review > 0 && <span style={{ color: '#ffb86c' }}> · {stats.review} rev.</span>}
                            {isSelected && (
                              <span style={{ fontSize: '0.58rem', padding: '1px 5px', borderRadius: '4px', background: 'rgba(0,210,255,0.3)', color: '#fff', fontWeight: 700 }}>
                                ATTIVO
                              </span>
                            )}
                          </div>

                          {/* Tasto Riavvio / Riprova Dataset */}
                          <button
                            type="button"
                            title={`Riesegui solo i test del dataset ${name} su ${activeJob.model}`}
                            onClick={(e) => handleRerunSuite(sKey, e)}
                            style={{
                              background: 'rgba(255,255,255,0.08)',
                              border: '1px solid rgba(255,255,255,0.18)',
                              borderRadius: '5px', padding: '3px 7px',
                              color: '#fff', fontSize: '0.62rem', fontWeight: 700,
                              cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '4px',
                              transition: 'all 0.15s ease',
                            }}
                          >
                            <RotateCcw size={10} /> Riesegui
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Barra Ricerca e Filtri */}
              <div style={{
                display: 'flex', flexDirection: 'column', gap: '8px',
                background: 'rgba(10,12,26,0.5)', border: '1px solid var(--border, rgba(255,255,255,0.08))',
                borderRadius: '10px', padding: '10px 14px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px', flexWrap: 'wrap' }}>
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

                  {/* Toggle Modalita Vista: Compatta (seleziona a schermo) vs Schede */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginLeft: 'auto' }}>
                    <button
                      type="button"
                      onClick={() => setQuestionViewMode('compact')}
                      title="Vista Compatta con Ispezione: seleziona e visualizza i quesiti a schermo intero senza scroll infinito"
                      style={{
                        ...btn(questionViewMode === 'compact'),
                        fontSize: '0.68rem', padding: '4px 8px', display: 'inline-flex', alignItems: 'center', gap: '4px',
                      }}
                    >
                      <LayoutGrid size={12} /> ☷ Compatta
                    </button>
                    <button
                      type="button"
                      onClick={() => setQuestionViewMode('cards')}
                      title="Vista a Schede: mostra l'elenco espanso di tutte le schede quesito"
                      style={{
                        ...btn(questionViewMode === 'cards'),
                        fontSize: '0.68rem', padding: '4px 8px', display: 'inline-flex', alignItems: 'center', gap: '4px',
                      }}
                    >
                      <List size={12} /> ☰ Schede
                    </button>
                  </div>
                </div>

                {/* Filtro Rapido per Dataset */}
                {jobSuites.length > 1 && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '5px', flexWrap: 'wrap', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '8px' }}>
                    <span style={{ fontSize: '0.66rem', color: 'var(--text-dark, #8b949e)', fontWeight: 600, marginRight: '4px' }}>Filtra Dataset:</span>
                    <button
                      type="button"
                      onClick={() => setSuiteFilter('all')}
                      style={{ ...btn(suiteFilter === 'all'), fontSize: '0.66rem', padding: '3px 8px' }}
                    >
                      🌐 Tutte ({fmt(Object.values(counts).reduce((a, b) => a + b, 0))})
                    </button>
                    {Object.entries(detail.suite_breakdown).map(([name, stats]) => {
                      const sKey = name.toLowerCase().replace('-', '_');
                      const isSelected = suiteFilter.toLowerCase().replace('-', '_') === sKey;
                      const sMeta = SUITE_LABELS[sKey];
                      return (
                        <button
                          key={name}
                          type="button"
                          onClick={() => setSuiteFilter(isSelected ? 'all' : sKey)}
                          title={sMeta ? `${sMeta.name} (${sMeta.category}):\n${sMeta.description}` : undefined}
                          style={{
                            ...btn(isSelected),
                            fontSize: '0.66rem', padding: '3px 8px',
                          }}
                        >
                          {name} ({stats.total})
                        </button>
                      );
                    })}
                  </div>
                )}
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
                    {questionViewMode === 'compact' ? (
                      <div className="bench-tests-master-detail">
                        {/* Colonna Sinistra: Lista Compatta Selezionabile */}
                        <div className="bench-tests-list-col">
                          {detail.results.map((tr, idx) => {
                            const qNum = (detail.page - 1) * detail.page_size + idx + 1;
                            const isSelected = (selectedResultIndex < detail.results.length ? selectedResultIndex : 0) === idx;
                            return (
                              <QuestionRowItem
                                key={`${tr.id}_${idx}`}
                                result={tr}
                                number={qNum}
                                isSelected={isSelected}
                                onSelect={() => setSelectedResultIndex(idx)}
                              />
                            );
                          })}
                        </div>

                        {/* Colonna Destra: Ispezione Dettagliata del Quesito Selezionato */}
                        <QuestionDetailInspector
                          result={detail.results[selectedResultIndex < detail.results.length ? selectedResultIndex : 0]}
                          model={activeJob.model}
                          number={(detail.page - 1) * detail.page_size + (selectedResultIndex < detail.results.length ? selectedResultIndex : 0) + 1}
                          currentIndex={selectedResultIndex < detail.results.length ? selectedResultIndex : 0}
                          totalInPage={detail.results.length}
                          onPrev={() => setSelectedResultIndex((prev) => Math.max(0, prev - 1))}
                          onNext={() => setSelectedResultIndex((prev) => Math.min(detail.results.length - 1, prev + 1))}
                        />
                      </div>
                    ) : (
                      detail.results.map((tr, idx) => (
                        <QuestionCard
                          key={`${tr.id}_${idx}`}
                          result={tr}
                          model={activeJob.model}
                          number={(detail.page - 1) * detail.page_size + idx + 1}
                        />
                      ))
                    )}


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

      {/* Modal Ampliamento Benchmark */}
      <ExtendBenchmarkModal
        open={extendModalOpen}
        activeJob={activeJob}
        extendSamples={extendSamples}
        extendSuite={extendSuite}
        extendMode={extendMode}
        extendThinkingMode={extendThinkingMode}
        extending={extending}
        onSamples={setExtendSamples}
        onSuite={setExtendSuite}
        onMode={setExtendMode}
        onThinkingMode={setExtendThinkingMode}
        onClose={() => setExtendModalOpen(false)}
        onConfirm={handleExtendBenchmark}
      />
        </>
      )}
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
    { id: 'sigma_engine', label: `⚡ Sigma (${catCounts.sigma_engine || 0})` },
    { id: 'ollama', label: `🐙 Ollama (${catCounts.ollama || 0})` },
    { id: 'local_provider', label: `💻 LM Studio (${catCounts.local_provider || 0})` },
    { id: 'cloud', label: `☁️ Cloud (${catCounts.cloud || 0})` },
  ];

  const colRef = useRef(null);

  const currentSpecs = useMemo(() => {
    if (!current) return null;
    return getModelSpecs(current, allModels);
  }, [current, allModels]);

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e) => {
      if (colRef.current && !colRef.current.contains(e.target)) {
        if (onToggle) onToggle();
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open, onToggle]);

  return (
    <div ref={colRef} className={`bench-config-col ${open ? 'dropdown-open' : ''}`}>
      <div className="bench-config-header">
        <span className="bench-config-title"><Cpu size={13} style={{ color: ACCENT }} /> Modello da Valutare</span>
        <span className="bench-config-count">{total} disponibili</span>
      </div>

      {/* Contenitore Relativo per allineare Trigger e Dropdown */}
      <div style={{ position: 'relative', width: '100%' }}>
        {/* Trigger Modello con Statistiche Arricchite */}
        <button
          type="button"
          onClick={onToggle}
          className={`bench-model-trigger ${open ? 'open' : ''}`}
        >
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', minWidth: 0, flex: 1, gap: '3px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', width: '100%', flexWrap: 'wrap' }}>
              <span style={{ fontSize: '0.78rem', fontWeight: 800, color: ACCENT, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {current?.name || 'Seleziona un modello...'}
              </span>

              {/* Statistiche Live nel Trigger come in Chat */}
              {currentSpecs?.chatSpeed !== null && currentSpecs?.chatSpeed !== undefined && (
                <span
                  title={`Velocità live misurata: ${currentSpecs.chatSpeed} tok/s`}
                  style={{
                    fontSize: '0.56rem', padding: '1px 5px', borderRadius: '4px',
                    background: 'rgba(0, 210, 255, 0.16)', color: '#00d2ff', fontWeight: 800,
                    display: 'inline-flex', alignItems: 'center', gap: '2px', whiteSpace: 'nowrap'
                  }}
                >
                  ⚡ {currentSpecs.chatSpeed} t/s
                </span>
              )}

              {currentSpecs?.params && (
                <span style={{ fontSize: '0.56rem', padding: '1px 5px', borderRadius: '4px', background: 'rgba(0, 210, 255, 0.16)', color: '#00d2ff', fontWeight: 800, whiteSpace: 'nowrap' }}>
                  ⚡ {currentSpecs.params}
                </span>
              )}

              {currentSpecs?.toolScore !== null && currentSpecs?.toolScore !== undefined && (
                <span
                  title={`Benchmark Tools (Aderenza Protocollo & Tool Use): ${Math.round(currentSpecs.toolScore)}%`}
                  style={{
                    fontSize: '0.56rem', padding: '1px 5px', borderRadius: '4px',
                    background: 'rgba(0, 210, 255, 0.16)', color: '#00d2ff', fontWeight: 800,
                    display: 'inline-flex', alignItems: 'center', gap: '3px', whiteSpace: 'nowrap'
                  }}
                >
                  <Wrench size={10} color="#00d2ff" />
                  <span>{Math.round(currentSpecs.toolScore)}%</span>
                </span>
              )}

              {currentSpecs?.size && (
                <span style={{ fontSize: '0.56rem', padding: '1px 5px', borderRadius: '4px', background: 'rgba(255, 184, 108, 0.15)', color: '#ffb86c', fontWeight: 800, whiteSpace: 'nowrap' }}>
                  💾 {currentSpecs.size}
                </span>
              )}

              {current?.badge && (
                <span style={{ fontSize: '0.55rem', fontWeight: 800, padding: '1px 5px', borderRadius: '4px', background: 'rgba(0,210,255,0.2)', color: ACCENT, flexShrink: 0 }}>
                  {current.badge}
                </span>
              )}
            </div>

            <span style={{ fontSize: '0.62rem', color: 'var(--text-dark, #8b949e)', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', width: '100%' }}>
              {current
                ? [current.provider_label, currentSpecs?.params || current.parameter_size, currentSpecs?.quantization || current.quantization].filter(Boolean).join(' · ')
                : 'Nessun modello selezionato'}
            </span>
          </div>
          <ChevronDown size={14} style={{ color: ACCENT, flexShrink: 0, transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
        </button>

        {/* Menu a Tendina Filtrabile Compatto */}
        {open && (
          <div className="bench-model-dropdown">
            {/* Categorie Provider */}
            <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
              {categories.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => onCategory(c.id)}
                  style={{
                    ...btn(activeCategory === c.id),
                    fontSize: '0.62rem', padding: '2px 6px',
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
              borderRadius: '6px', padding: '4px 8px',
            }}>
              <Search size={12} style={{ color: 'var(--text-dark, #8b949e)', flexShrink: 0 }} />
              <input
                autoFocus type="text" value={search} onChange={(e) => onSearch(e.target.value)}
                placeholder="Cerca per nome, provider o quantizzazione..."
                style={{ width: '100%', background: 'none', border: 'none', color: 'var(--text, #fff)', fontSize: '0.7rem', outline: 'none' }}
              />
            </div>

            {/* Lista Modelli Arricchita con Statistiche Identiche alla Chat */}
            <div style={{
              display: 'flex', flexDirection: 'column', gap: '4px',
              maxHeight: '260px', overflowY: 'auto', paddingRight: '2px'
            }}>
              {models.length === 0 ? (
                <div style={{ fontSize: '0.68rem', color: 'var(--text-dark, #8b949e)', padding: '10px', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '6px' }}>
                  <span>{allModels.length === 0 ? 'Caricamento modelli...' : 'Nessun modello trovato.'}</span>
                  {onRefresh && (
                    <button type="button" onClick={(e) => { e.stopPropagation(); onRefresh(); }} style={{ ...btn(true), fontSize: '0.62rem', display: 'flex', alignItems: 'center', gap: '4px', padding: '2px 6px' }}>
                      <RefreshCw size={10} /> Aggiorna Catalogo
                    </button>
                  )}
                </div>
              ) : models.map((m) => {
                const isSelected = current?.id === m.id;
                const itemSpecs = getModelSpecs(m, allModels);
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
                  <button
                    type="button" key={m.id} onClick={() => onPick(m.id)}
                    style={{
                      background: isSelected ? 'rgba(0,210,255,0.18)' : 'rgba(255,255,255,0.03)',
                      border: `1px solid ${isSelected ? ACCENT : 'rgba(255,255,255,0.06)'}`,
                      borderRadius: '7px', padding: '6px 8px', cursor: 'pointer',
                      display: 'flex', flexDirection: 'column', gap: '4px', textAlign: 'left',
                      transition: 'all 0.15s ease'
                    }}
                  >
                    {/* Riga 1: Dot provider + Sigmanih + Famiglia + Nome + Check */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', gap: '6px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '5px', minWidth: 0, flex: 1 }}>
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
                              fontSize: '0.54rem', fontWeight: 800, padding: '1px 4px', borderRadius: '3px',
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
                              fontSize: '0.54rem', fontWeight: 800, padding: '1px 4px', borderRadius: '3px',
                              background: familyConf.bg, border: `1px solid ${familyConf.border}`,
                              color: familyConf.color, flexShrink: 0
                            }}
                          >
                            {familyConf.title}
                          </span>
                        )}

                        <span style={{
                          fontSize: '0.74rem', fontWeight: isSelected ? 800 : 600,
                          color: isSelected ? '#00f2fe' : 'var(--text, #fff)',
                          wordBreak: 'break-word', overflowWrap: 'anywhere',
                        }}>{m.name}</span>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
                        {m.badge && (
                          <span style={{
                            fontSize: '0.50rem', fontWeight: 800, padding: '1px 4px', borderRadius: '3px',
                            background: 'rgba(255,255,255,0.08)', color: 'var(--text-dark, #8b949e)',
                          }}>{m.badge}</span>
                        )}
                        {isSelected && <Check size={12} color="#00f2fe" />}
                      </div>
                    </div>

                    {/* Riga 2: Statistiche e Badges identici alla Chat */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexWrap: 'wrap', fontSize: '0.60rem' }}>
                      {/* 🏆 Benchmark Badge */}
                      <span
                        title={hasBm
                          ? `Valutazione Benchmark: ${Math.round(bmScore)}%`
                          : 'Nessun benchmark registrato per questo modello'
                        }
                        style={{
                          fontSize: '0.56rem', fontWeight: 800, padding: '1px 5px', borderRadius: '3px',
                          background: hasBm ? `${bmColor}18` : 'rgba(255, 255, 255, 0.04)',
                          border: hasBm ? `1px solid ${bmColor}40` : '1px solid rgba(255, 255, 255, 0.08)',
                          color: bmColor,
                          display: 'inline-flex', alignItems: 'center', gap: '2px'
                        }}
                      >
                        <Trophy size={9} color={bmColor} />
                        <span>{hasBm ? `${Math.round(bmScore)}%` : '-'}</span>
                      </span>

                      {/* 🔧 Tool Benchmark Badge */}
                      <span
                        title={hasTool
                          ? `Benchmark Tools: ${Math.round(tScore)}%${toolTotal ? ` (${toolPassed}/${toolTotal})` : ''}`
                          : 'Nessun benchmark tools registrato'
                        }
                        style={{
                          fontSize: '0.56rem', fontWeight: 800, padding: '1px 5px', borderRadius: '3px',
                          background: hasTool ? `${toolColor}18` : 'rgba(255, 255, 255, 0.04)',
                          border: hasTool ? `1px solid ${toolColor}40` : '1px solid rgba(255, 255, 255, 0.08)',
                          color: toolColor,
                          display: 'inline-flex', alignItems: 'center', gap: '2px'
                        }}
                      >
                        <Wrench size={9} color={toolColor} />
                        <span>{hasTool ? `${Math.round(tScore)}%` : '-'}</span>
                      </span>

                      {/* ⚡ Live Speed t/s Badge */}
                      <span
                        title={chatTps !== null
                          ? `Velocità inferenza registrata: ${chatTps} token/secondo`
                          : 'Nessuna misurazione live disponibile'
                        }
                        style={{
                          fontSize: '0.56rem', fontWeight: 800, padding: '1px 5px', borderRadius: '3px',
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
                          fontSize: '0.56rem', padding: '1px 4px', borderRadius: '3px',
                          background: 'rgba(0, 210, 255, 0.12)', color: '#00d2ff', fontWeight: 800
                        }}>
                          {params}
                        </span>
                      )}

                      {/* Quantizzazione */}
                      {quant && (
                        <span style={{
                          fontSize: '0.56rem', padding: '1px 4px', borderRadius: '3px',
                          background: 'rgba(168, 85, 247, 0.14)', color: '#c084fc',
                          border: '1px solid rgba(168, 85, 247, 0.3)', fontWeight: 700
                        }}>
                          {quant}
                        </span>
                      )}

                      {/* Dimensione */}
                      {size && (
                        <span style={{
                          fontSize: '0.56rem', padding: '1px 4px', borderRadius: '3px',
                          background: 'rgba(255, 184, 108, 0.12)', color: '#ffb86c', fontWeight: 800
                        }}>
                          {size}
                        </span>
                      )}

                      {/* Provider Badge */}
                      <span style={{
                        fontSize: '0.54rem', fontWeight: 700, padding: '1px 4px', borderRadius: '3px',
                        backgroundColor: colors.bg || 'rgba(255,255,255,0.06)',
                        color: colors.color || '#fff', marginLeft: 'auto'
                      }}>
                        {m.provider === 'sigma_engine' ? 'SIGMA' : (m.provider_label || m.provider || 'locale')}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <div style={{ marginTop: 'auto', fontSize: '0.62rem', color: 'var(--text-dark, #8b949e)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        Locali GGUF, SigmaEngine, Ollama & Cloud
      </div>
    </div>
  );
}

function CoveragePicker({ evalMode, sampleCount, plannedItems, suiteMode, selectedSuitesCount, onMode, onCount }) {
  const samplePresets = [25, 50, 100, 250, 500, 1000];

  return (
    <div className="bench-config-col">
      <div className="bench-config-header">
        <span className="bench-config-title"><Shield size={13} style={{ color: 'var(--success, #3fb950)' }} /> Campioni & Copertura</span>
        <span className="bench-config-count" style={{ color: evalMode === 'full' ? 'var(--success, #3fb950)' : ACCENT, fontWeight: 700 }}>
          {fmt(plannedItems)} quesiti
        </span>
      </div>

      {/* Modalità Copertura */}
      <div style={{ display: 'flex', gap: '6px' }}>
        <button type="button" onClick={() => onMode('sample')} style={{
          flex: 1, padding: '5px 8px', borderRadius: '6px', cursor: 'pointer',
          border: `1px solid ${evalMode === 'sample' ? ACCENT : 'rgba(255,255,255,0.08)'}`,
          background: evalMode === 'sample' ? 'rgba(0,210,255,0.15)' : 'rgba(0,0,0,0.25)',
          color: evalMode === 'sample' ? ACCENT : 'var(--text-dark, #8b949e)',
          fontSize: '0.7rem', fontWeight: 700,
        }}>⚡ Campione</button>
        <button type="button" onClick={() => onMode('full')} style={{
          flex: 1, padding: '5px 8px', borderRadius: '6px', cursor: 'pointer',
          border: `1px solid ${evalMode === 'full' ? 'var(--success, #3fb950)' : 'rgba(255,255,255,0.08)'}`,
          background: evalMode === 'full' ? 'rgba(63,185,80,0.15)' : 'rgba(0,0,0,0.25)',
          color: evalMode === 'full' ? 'var(--success, #3fb950)' : 'var(--text-dark, #8b949e)',
          fontSize: '0.7rem', fontWeight: 700,
        }}>🏆 100% Integrale</button>
      </div>

      {/* Selettore Quantità Campioni Compatto */}
      {evalMode === 'sample' ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexWrap: 'wrap' }}>
          {samplePresets.map((cnt) => (
            <button
              key={cnt}
              type="button"
              onClick={() => onCount(cnt)}
              style={{
                padding: '2px 6px', borderRadius: '4px', fontSize: '0.64rem', fontWeight: 700, cursor: 'pointer',
                border: `1px solid ${sampleCount === cnt ? ACCENT : 'rgba(255,255,255,0.08)'}`,
                background: sampleCount === cnt ? 'rgba(0,210,255,0.18)' : 'rgba(255,255,255,0.03)',
                color: sampleCount === cnt ? ACCENT : 'var(--text-dark, #8b949e)',
              }}
            >
              {cnt >= 1000 ? `${cnt / 1000}k` : cnt}
            </button>
          ))}
          <div style={{ display: 'flex', alignItems: 'center', gap: '3px', marginLeft: 'auto' }}>
            <span style={{ fontSize: '0.58rem', color: 'var(--text-dark, #8b949e)' }}>Custom:</span>
            <input
              type="number" min="5" max="50000" step="25"
              value={sampleCount}
              onChange={(e) => onCount(Math.max(5, Number(e.target.value)))}
              style={{
                width: '52px', background: 'rgba(0,0,0,0.4)', border: '1px solid var(--border, rgba(255,255,255,0.1))',
                borderRadius: '5px', padding: '2px 4px', color: ACCENT, fontWeight: 700, fontSize: '0.68rem', textAlign: 'center', outline: 'none'
              }}
            />
          </div>
        </div>
      ) : (
        <div style={{ fontSize: '0.62rem', color: 'var(--text-dark, #8b949e)', padding: '2px 0' }}>
          Tutti i quesiti certificati delle suite selezionate.
        </div>
      )}

      <div style={{ marginTop: 'auto', fontSize: '0.6rem', color: 'var(--text-dark, #8b949e)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {evalMode === 'full'
          ? `Certificato integrale SHA-256`
          : `Seed 42 su ${suiteMode === 'all' ? '11 suite' : `${selectedSuitesCount} suite`}`}
      </div>
    </div>
  );
}

function ThinkingPicker({ thinkingMode, onThinkingMode }) {
  return (
    <div className="bench-config-col">
      <div className="bench-config-header">
        <span className="bench-config-title"><Zap size={13} style={{ color: '#bc8cff' }} /> Modalità Thinking</span>
        <span className="bench-config-count" style={{
          color: thinkingMode === 'thinking' ? '#bc8cff' : thinkingMode === 'no_thinking' ? '#ffb86c' : ACCENT,
          fontWeight: 700,
        }}>
          {thinkingMode === 'auto' ? '🧠 Auto' : thinkingMode === 'thinking' ? '💡 CoT' : '⚡ No-Think'}
        </span>
      </div>

      <div style={{ display: 'flex', gap: '5px' }}>
        <button
          type="button"
          onClick={() => onThinkingMode('auto')}
          style={{
            flex: 1, padding: '5px 5px', borderRadius: '6px', cursor: 'pointer',
            border: `1px solid ${thinkingMode === 'auto' ? ACCENT : 'rgba(255,255,255,0.08)'}`,
            background: thinkingMode === 'auto' ? 'rgba(0,210,255,0.15)' : 'rgba(0,0,0,0.25)',
            color: thinkingMode === 'auto' ? ACCENT : 'var(--text-dark, #8b949e)',
            fontSize: '0.68rem', fontWeight: 700,
          }}
          title="Auto: CoT su logica/matematica, risposta diretta su conoscenza"
        >
          🧠 Auto
        </button>
        <button
          type="button"
          onClick={() => onThinkingMode('no_thinking')}
          style={{
            flex: 1, padding: '5px 5px', borderRadius: '6px', cursor: 'pointer',
            border: `1px solid ${thinkingMode === 'no_thinking' ? '#ffb86c' : 'rgba(255,255,255,0.08)'}`,
            background: thinkingMode === 'no_thinking' ? 'rgba(255,184,108,0.15)' : 'rgba(0,0,0,0.25)',
            color: thinkingMode === 'no_thinking' ? '#ffb86c' : 'var(--text-dark, #8b949e)',
            fontSize: '0.68rem', fontWeight: 700,
          }}
          title="No-Thinking: risposte dirette senza CoT"
        >
          ⚡ No-Think
        </button>
        <button
          type="button"
          onClick={() => onThinkingMode('thinking')}
          style={{
            flex: 1, padding: '5px 5px', borderRadius: '6px', cursor: 'pointer',
            border: `1px solid ${thinkingMode === 'thinking' ? '#bc8cff' : 'rgba(255,255,255,0.08)'}`,
            background: thinkingMode === 'thinking' ? 'rgba(188,140,255,0.15)' : 'rgba(0,0,0,0.25)',
            color: thinkingMode === 'thinking' ? '#bc8cff' : 'var(--text-dark, #8b949e)',
            fontSize: '0.68rem', fontWeight: 700,
          }}
          title="Thinking CoT: catena di pensiero estesa ovunque"
        >
          💡 CoT
        </button>
      </div>

      <div style={{ marginTop: 'auto', fontSize: '0.6rem', color: 'var(--text-dark, #8b949e)', lineHeight: '1.25' }}>
        {thinkingMode === 'auto' && 'CoT logica/math, diretto conoscenza.'}
        {thinkingMode === 'no_thinking' && 'Risposta istintiva ad alta velocità.'}
        {thinkingMode === 'thinking' && 'Forza Chain-of-Thought su tutti i task.'}
      </div>
    </div>
  );
}


function Summary({ label, value, hint }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: '0.62rem', color: 'var(--text-dark, #8b949e)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
      <div style={{ fontSize: '0.84rem', fontWeight: 800, color: 'var(--text, #fff)', wordBreak: 'break-word', overflowWrap: 'anywhere', lineHeight: '1.25' }}>
        {value}
      </div>
      {hint && <div style={{ fontSize: '0.62rem', color: 'var(--text-dark, #8b949e)', wordBreak: 'break-word', marginTop: '1px' }}>{hint}</div>}
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

function QuestionRowItem({ result, number, isSelected, onSelect }) {
  const style = VERDICT_STYLE[result.verdict] || VERDICT_STYLE.fail;
  const sKey = (result.suite || result.suite_name || '').toLowerCase().replace('-', '_');
  const qMeta = SUITE_LABELS[sKey];
  const shortPrompt = (result.prompt || '').replace(/\s+/g, ' ').trim();
  const verdictClass = result.verdict === 'pass' ? 'verdict-pass' : result.verdict === 'fail' ? 'verdict-fail' : '';

  return (
    <div
      onClick={onSelect}
      className={`bench-test-item-row ${isSelected ? 'selected' : ''} ${verdictClass}`}
      title={shortPrompt}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', minWidth: 0, flex: 1 }}>
        <span style={{
          fontSize: '0.62rem', fontWeight: 800, padding: '2px 5px', borderRadius: '4px',
          background: isSelected ? 'rgba(0,210,255,0.25)' : 'rgba(255,255,255,0.06)',
          color: isSelected ? '#00f2fe' : 'var(--text-dark, #8b949e)',
          fontFamily: 'monospace', flexShrink: 0,
        }}>
          #{number}
        </span>

        {/* Verdetto Badge Icona */}
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: '3px',
          fontSize: '0.64rem', fontWeight: 800, color: style.color,
          padding: '1px 5px', borderRadius: '4px', background: 'rgba(0,0,0,0.3)',
          border: `1px solid ${style.border}`, flexShrink: 0,
        }}>
          <style.Icon size={11} /> {result.verdict === 'pass' ? 'PASS' : result.verdict === 'fail' ? 'FAIL' : style.label}
        </span>

        {/* Suite Badge */}
        {result.suite_name && (
          <span style={{
            fontSize: '0.6rem', color: '#fff', fontWeight: 700,
            background: 'rgba(255,255,255,0.06)', padding: '1px 5px', borderRadius: '4px',
            border: '1px solid rgba(255,255,255,0.08)', flexShrink: 0,
          }} title={qMeta?.name || result.suite_name}>
            {result.suite_name}
          </span>
        )}

        {/* Prompt su una sola riga */}
        <span className="row-prompt">
          {shortPrompt || '(Nessun testo)'}
        </span>
      </div>

      {/* Metriche rapide */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.62rem', fontFamily: 'monospace', flexShrink: 0 }}>
        {result.tokens_per_sec ? (
          <span style={{ color: ACCENT, fontWeight: 700 }}>{result.tokens_per_sec} t/s</span>
        ) : null}
        {result.latency_ms ? (
          <span style={{ color: '#ffb86c' }}>{fmt(result.latency_ms)}ms</span>
        ) : null}
        <ChevronRight size={12} style={{ color: isSelected ? '#00f2fe' : 'rgba(255,255,255,0.2)', transition: 'transform 0.15s' }} />
      </div>
    </div>
  );
}

function QuestionDetailInspector({ result, model, number, currentIndex, totalInPage, onPrev, onNext }) {
  if (!result) {
    return (
      <div style={{ padding: '30px', textAlign: 'center', color: 'var(--text-dark, #8b949e)', fontSize: '0.8rem' }}>
        Seleziona un quesito per visualizzare l'ispezione completa.
      </div>
    );
  }
  const [showThinking, setShowThinking] = useState(false);
  const style = VERDICT_STYLE[result.verdict] || VERDICT_STYLE.fail;
  const parsed = result.parsed || {};
  const correct = (result.correct_choice || '').trim().toUpperCase();
  const chosen = parsed.status === 'resolved' ? (parsed.value || '').toUpperCase() : null;
  const candidates = (parsed.candidates || []).map((c) => String(c).toUpperCase());

  // Rilevamento ed estrazione del ragionamento CoT
  const rawAnswer = result.given_answer || result.error || '';
  let thinkingText = result.thinking || result.reasoning || null;
  let cleanAnswer = rawAnswer;
  if (!thinkingText && typeof rawAnswer === 'string') {
    const thinkMatch = rawAnswer.match(/<think>([\s\S]*?)<\/think>/i);
    if (thinkMatch) {
      thinkingText = thinkMatch[1].trim();
      cleanAnswer = rawAnswer.replace(/<think>[\s\S]*?<\/think>/i, '').trim();
    }
  }

  return (
    <div className="bench-test-detail-col">
      {/* Barra di Navigazione Rapida Superiore */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '8px 12px', background: 'rgba(0,0,0,0.35)', borderRadius: '8px',
        border: '1px solid rgba(255,255,255,0.08)', flexWrap: 'wrap', gap: '8px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          <span style={{
            fontSize: '0.74rem', fontWeight: 900, color: '#fff',
            background: 'rgba(0,210,255,0.18)', border: '1px solid rgba(0,210,255,0.4)',
            padding: '2px 8px', borderRadius: '5px',
          }}>
            #{number}
          </span>
          <span style={{
            color: style.color, display: 'flex', alignItems: 'center', gap: '4px',
            fontWeight: 800, fontSize: '0.74rem', background: 'rgba(0,0,0,0.3)',
            padding: '2px 8px', borderRadius: '5px', border: `1px solid ${style.border}`,
          }}>
            <style.Icon size={14} /> {style.label}
          </span>
          {result.suite_name && (
            <span style={{
              fontSize: '0.68rem', color: '#fff', fontWeight: 700,
              background: 'rgba(255,255,255,0.06)', padding: '2px 7px', borderRadius: '5px',
              border: '1px solid rgba(255,255,255,0.1)',
            }}>
              {result.suite_name}
            </span>
          )}
          {result.category && (
            <span style={{ fontSize: '0.66rem', color: 'var(--text-dark, #8b949e)' }}>
              {result.category}
            </span>
          )}
        </div>

        {/* Tasti Navigazione Prec / Succ */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: '0.68rem', color: 'var(--text-dark, #8b949e)', marginRight: '4px' }}>
            {currentIndex + 1} di {totalInPage}
          </span>
          <button
            type="button"
            disabled={currentIndex <= 0}
            onClick={onPrev}
            style={{
              background: currentIndex <= 0 ? 'rgba(255,255,255,0.02)' : 'rgba(255,255,255,0.08)',
              border: '1px solid rgba(255,255,255,0.15)',
              color: currentIndex <= 0 ? 'rgba(255,255,255,0.2)' : '#fff',
              borderRadius: '5px', padding: '3px 8px', fontSize: '0.68rem',
              cursor: currentIndex <= 0 ? 'not-allowed' : 'pointer',
              display: 'inline-flex', alignItems: 'center', gap: '3px',
            }}
          >
            <ChevronLeft size={12} /> Prec
          </button>
          <button
            type="button"
            disabled={currentIndex >= totalInPage - 1}
            onClick={onNext}
            style={{
              background: currentIndex >= totalInPage - 1 ? 'rgba(255,255,255,0.02)' : 'rgba(0,210,255,0.15)',
              border: `1px solid ${currentIndex >= totalInPage - 1 ? 'rgba(255,255,255,0.15)' : 'rgba(0,210,255,0.4)'}`,
              color: currentIndex >= totalInPage - 1 ? 'rgba(255,255,255,0.2)' : '#00f2fe',
              borderRadius: '5px', padding: '3px 8px', fontSize: '0.68rem',
              cursor: currentIndex >= totalInPage - 1 ? 'not-allowed' : 'pointer',
              display: 'inline-flex', alignItems: 'center', gap: '3px',
            }}
          >
            Succ <ChevronRight size={12} />
          </button>
        </div>
      </div>

      {/* Metriche sintetiche di esecuzione */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap',
        fontSize: '0.68rem', fontFamily: 'monospace', padding: '4px 2px',
      }}>
        {result.endpoint && <span style={{ color: 'var(--text-dark, #8b949e)' }}>{result.endpoint}</span>}
        <span style={{ color: ACCENT, fontWeight: 700 }}>⚡ {result.tokens_per_sec || 0} tok/s</span>
        <span style={{ color: '#ffb86c', fontWeight: 700 }}>⏱️ {fmt(result.latency_ms)} ms</span>
        {result.finish_reason === 'timeout' && (
          <span style={{ color: '#ff7b72', background: 'rgba(255,123,114,0.15)', padding: '1px 6px', borderRadius: '4px' }}>⏳ Scaduta</span>
        )}
        {result.finish_reason === 'length' && (
          <span style={{ color: '#ffb86c', background: 'rgba(255,184,108,0.15)', padding: '1px 6px', borderRadius: '4px' }}>✂️ Troncata</span>
        )}
      </div>

      {/* Prompt Integrale del Quesito */}
      <div className="bench-question-prompt" style={{ maxHeight: '180px', overflowY: 'auto' }}>
        {result.prompt}
      </div>

      {/* Opzioni Multiple se applicabili */}
      {result.options?.length > 0 && (
        <div className="bench-options-grid" style={{ maxHeight: '200px', overflowY: 'auto' }}>
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
              bg = 'rgba(63,185,80,0.14)';
              border = 'rgba(63,185,80,0.55)';
              color = '#3fb950';
              badge = <span style={{ fontSize: '0.62rem', color: '#3fb950', fontWeight: 800 }}>✓ CORRETTA</span>;
            }
            if (isCandidate) {
              bg = 'rgba(255,184,108,0.12)';
              border = 'rgba(255,184,108,0.45)';
              color = '#ffb86c';
              badge = <span style={{ fontSize: '0.62rem', color: '#ffb86c', fontWeight: 800 }}>🤖 CANDIDATA</span>;
            }
            if (isChosen) {
              const ok = result.verdict === 'pass';
              bg = ok ? 'rgba(63,185,80,0.22)' : 'rgba(255,85,85,0.18)';
              border = ok ? '#3fb950' : 'rgba(255,85,85,0.7)';
              color = ok ? '#3fb950' : '#ff5555';
              badge = <span style={{ fontSize: '0.62rem', color, fontWeight: 800 }}>🤖 SCELTA {ok ? '(GIUSTA)' : '(ERRATA)'}</span>;
            }

            return (
              <div key={i} className="bench-opt-row" style={{
                background: bg,
                border: `1px solid ${border}`,
                color,
                fontWeight: (isCorrect || isChosen || isCandidate) ? 700 : 500,
              }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                  <span style={{
                    width: '18px', height: '18px', borderRadius: '50%',
                    background: (isCorrect || isChosen) ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.05)',
                    border: `1px solid ${border}`, display: 'inline-flex', alignItems: 'center',
                    justifyContent: 'center', fontSize: '0.64rem', fontWeight: 800, flexShrink: 0,
                  }}>
                    {letter}
                  </span>
                  <span>{opt}</span>
                </div>
                {badge}
              </div>
            );
          })}
        </div>
      )}

      {/* Risultato Sandbox Unit Test (HumanEval / MBPP) */}
      {result.execution && (
        <div style={{
          background: 'rgba(6, 8, 18, 0.95)',
          border: '1px solid rgba(0, 210, 255, 0.3)',
          borderRadius: '8px',
          overflow: 'hidden',
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            background: 'rgba(0,0,0,0.4)', padding: '5px 10px', borderBottom: '1px solid rgba(255,255,255,0.06)',
          }}>
            <span style={{ fontSize: '0.64rem', color: 'var(--text-dark, #8b949e)', fontFamily: 'monospace' }}>
              Sandbox Esecuzione Unit Test
            </span>
            <span style={{
              fontSize: '0.62rem', fontWeight: 800, color: result.execution.status === 'passed' ? 'var(--success, #3fb950)' : '#ff5555',
              background: result.execution.status === 'passed' ? 'rgba(63,185,80,0.15)' : 'rgba(255,85,85,0.15)',
              padding: '1px 6px', borderRadius: '4px', textTransform: 'uppercase',
            }}>
              {result.execution.status}
            </span>
          </div>
          {result.execution.detail && (
            <div style={{
              padding: '8px 10px', fontSize: '0.7rem', color: '#e6edf3',
              fontFamily: 'monospace', whiteSpace: 'pre-wrap', maxHeight: '130px', overflowY: 'auto',
            }}>
              {result.execution.detail}
            </div>
          )}
        </div>
      )}

      {/* Sezione Risposta Generata */}
      <div style={{
        background: 'rgba(10,12,26,0.75)',
        padding: '10px 12px',
        borderRadius: '8px',
        border: `1px solid ${style.border}`,
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px' }}>
          <div style={{
            fontSize: '0.64rem', fontWeight: 800, color: style.color,
            textTransform: 'uppercase', letterSpacing: '0.05em',
            display: 'flex', alignItems: 'center', gap: '5px',
          }}>
            <Cpu size={12} /> Risposta Generata da {model}
          </div>

          {thinkingText && (
            <button
              type="button"
              onClick={() => setShowThinking(!showThinking)}
              style={{
                background: 'rgba(188,140,255,0.12)',
                border: '1px solid rgba(188,140,255,0.3)',
                color: '#bc8cff',
                fontSize: '0.62rem',
                fontWeight: 700,
                padding: '2px 7px',
                borderRadius: '4px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              <Zap size={10} />
              {showThinking ? 'Nascondi CoT' : `Mostra CoT (${thinkingText.length} car.)`}
              <ChevronDown size={10} style={{ transform: showThinking ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
            </button>
          )}
        </div>

        {/* Box Thinking Collassabile */}
        {showThinking && thinkingText && (
          <div className="bench-thinking-box" style={{ maxHeight: '160px', overflowY: 'auto' }}>
            <div style={{ fontSize: '0.62rem', fontWeight: 800, color: '#bc8cff', marginBottom: '4px', textTransform: 'uppercase' }}>
              🧠 Catena di Pensiero (Chain of Thought):
            </div>
            <div style={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap', lineHeight: 1.4 }}>
              {thinkingText}
            </div>
          </div>
        )}

        {/* Risposta Pulita Finale */}
        <div style={{
          fontSize: '0.74rem', color: 'var(--text, #fff)',
          fontFamily: 'monospace', whiteSpace: 'pre-wrap', lineHeight: 1.4,
          maxHeight: '180px', overflowY: 'auto',
        }}>
          {cleanAnswer || '(Nessuna risposta testuale prodotta)'}
        </div>

        {/* Risposta Attesa di Riferimento */}
        {!result.options?.length && result.correct_answer && (
          <div style={{
            marginTop: '4px', paddingTop: '6px',
            borderTop: '1px dashed rgba(255,255,255,0.12)',
          }}>
            <div style={{
              fontSize: '0.62rem', fontWeight: 800, color: 'var(--success, #3fb950)',
              textTransform: 'uppercase', marginBottom: '2px',
            }}>
              ✓ Risposta Attesa Ufficiale:
            </div>
            <div style={{ fontSize: '0.74rem', color: '#a8f0b0', fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
              {result.correct_answer}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function QuestionCard({ result, model, number }) {
  const [showThinking, setShowThinking] = useState(false);
  const style = VERDICT_STYLE[result.verdict] || VERDICT_STYLE.fail;
  const parsed = result.parsed || {};
  const correct = (result.correct_choice || '').trim().toUpperCase();
  const chosen = parsed.status === 'resolved' ? (parsed.value || '').toUpperCase() : null;
  const candidates = (parsed.candidates || []).map((c) => String(c).toUpperCase());

  // Rilevamento ed estrazione del ragionamento CoT
  const rawAnswer = result.given_answer || result.error || '';
  let thinkingText = result.thinking || result.reasoning || null;
  let cleanAnswer = rawAnswer;
  if (!thinkingText && typeof rawAnswer === 'string') {
    const thinkMatch = rawAnswer.match(/<think>([\s\S]*?)<\/think>/i);
    if (thinkMatch) {
      thinkingText = thinkMatch[1].trim();
      cleanAnswer = rawAnswer.replace(/<think>[\s\S]*?<\/think>/i, '').trim();
    }
  }

  const sKey = (result.suite || result.suite_name || '').toLowerCase().replace('-', '_');
  const qMeta = SUITE_LABELS[sKey];

  return (
    <div className="bench-question-card" style={{
      background: style.bg,
      border: `1px solid ${style.border}`,
      boxShadow: result.verdict === 'pass' ? '0 2px 14px rgba(63,185,80,0.08)' : '0 2px 14px rgba(255,85,85,0.08)',
    }}>
      {/* Testata Quesito: Verdetto, Numero, Suite, Metriche */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          <span style={{
            color: style.color, display: 'flex', alignItems: 'center', gap: '5px',
            fontWeight: 800, fontSize: '0.76rem', background: 'rgba(0,0,0,0.3)',
            padding: '3px 8px', borderRadius: '6px', border: `1px solid ${style.border}`,
          }}>
            <style.Icon size={15} /> {style.label}
          </span>
          <span style={{
            fontSize: '0.64rem', fontWeight: 800, padding: '3px 8px', borderRadius: '6px',
            background: 'rgba(0,210,255,0.15)', color: ACCENT, border: '1px solid rgba(0,210,255,0.3)',
          }}>
            #{number}
          </span>
          {result.suite_name && (
            <span
              style={{
                fontSize: '0.7rem', color: '#fff', fontWeight: 700,
                background: 'rgba(255,255,255,0.06)', padding: '2px 8px', borderRadius: '6px',
                border: '1px solid rgba(255,255,255,0.08)', cursor: 'help',
              }}
              title={qMeta ? `${qMeta.name} (${qMeta.category}):\n${qMeta.description}` : result.suite_name}
            >
              {result.suite_name}
            </span>
          )}
          {result.category && (
            <span style={{ fontSize: '0.68rem', color: 'var(--text-dark, #8b949e)', fontWeight: 500 }}>
              {result.category}
            </span>
          )}
          {result.thinking_mode === 'thinking' || result.is_thinking || thinkingText ? (
            <span style={{
              fontSize: '0.62rem', fontWeight: 700, padding: '2px 7px', borderRadius: '6px',
              background: 'rgba(188,140,255,0.18)', color: '#bc8cff', border: '1px solid rgba(188,140,255,0.3)',
            }} title="Valutato con Chain-of-Thought (CoT)">
              💡 CoT
            </span>
          ) : result.thinking_mode === 'no_thinking' ? (
            <span style={{
              fontSize: '0.62rem', fontWeight: 700, padding: '2px 7px', borderRadius: '6px',
              background: 'rgba(255,184,108,0.15)', color: '#ffb86c', border: '1px solid rgba(255,184,108,0.25)',
            }} title="Valutato a risposta diretta senza CoT">
              ⚡ No-Think
            </span>
          ) : null}
        </div>

        {/* Metriche di Esecuzione */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontFamily: 'monospace', fontSize: '0.68rem' }}>
          {result.endpoint && (
            <span style={{ color: 'var(--text-dark, #8b949e)', opacity: 0.8 }}>{result.endpoint}</span>
          )}
          <span style={{ color: ACCENT, fontWeight: 700 }}>⚡ {result.tokens_per_sec || 0} tok/s</span>
          <span style={{ color: '#ffb86c', fontWeight: 700 }}>⏱️ {fmt(result.latency_ms)} ms</span>
          {result.finish_reason === 'timeout' && (
            <span title={result.warning || 'Generazione interrotta dalla scadenza'}
              style={{ color: '#ff7b72', fontWeight: 800, background: 'rgba(255,123,114,0.15)', padding: '2px 6px', borderRadius: '4px' }}>
              ⏳ Scaduta
            </span>
          )}
          {result.finish_reason === 'length' && (
            <span title="Il budget di token è finito prima della risposta"
              style={{ color: '#ffb86c', fontWeight: 800, background: 'rgba(255,184,108,0.15)', padding: '2px 6px', borderRadius: '4px' }}>
              ✂️ Troncata
            </span>
          )}
        </div>
      </div>

      {/* Testo del Quesito / Prompt */}
      <div className="bench-question-prompt">
        {result.prompt}
      </div>

      {/* Griglia Scelte Multiple (se applicabile) */}
      {result.options?.length > 0 && (
        <div className="bench-options-grid">
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
              bg = 'rgba(63,185,80,0.14)';
              border = 'rgba(63,185,80,0.55)';
              color = '#3fb950';
              badge = <Badge color="#3fb950"><Check size={9} /> CORRETTA</Badge>;
            }
            if (isCandidate) {
              bg = 'rgba(255,184,108,0.12)';
              border = 'rgba(255,184,108,0.45)';
              color = '#ffb86c';
              badge = <Badge color="#ffb86c">🤖 CANDIDATA</Badge>;
            }
            if (isChosen) {
              const ok = result.verdict === 'pass';
              bg = ok ? 'rgba(63,185,80,0.22)' : 'rgba(255,85,85,0.18)';
              border = ok ? '#3fb950' : 'rgba(255,85,85,0.7)';
              color = ok ? '#3fb950' : '#ff5555';
              badge = <Badge color={color}>🤖 SCELTA {ok ? '(GIUSTA)' : '(ERRATA)'}</Badge>;
            }

            return (
              <div key={i} className="bench-opt-row" style={{
                background: bg,
                border: `1px solid ${border}`,
                color,
                fontWeight: (isCorrect || isChosen || isCandidate) ? 700 : 500,
              }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                  <span style={{
                    width: '20px', height: '20px', borderRadius: '50%',
                    background: (isCorrect || isChosen) ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.05)',
                    border: `1px solid ${border}`, display: 'inline-flex', alignItems: 'center',
                    justifyContent: 'center', fontSize: '0.68rem', fontWeight: 800, flexShrink: 0,
                  }}>
                    {letter}
                  </span>
                  <span>{opt}</span>
                </div>
                {badge}
              </div>
            );
          })}
        </div>
      )}

      {/* Risultato Esecuzione Codice Sandbox (HumanEval / MBPP) */}
      {result.execution && (
        <div style={{
          background: 'rgba(6, 8, 18, 0.95)',
          border: '1px solid rgba(0, 210, 255, 0.3)',
          borderRadius: '8px',
          overflow: 'hidden',
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            background: 'rgba(0,0,0,0.4)', padding: '6px 12px', borderBottom: '1px solid rgba(255,255,255,0.06)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#ff5f56' }} />
              <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#ffbd2e' }} />
              <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#27c93f' }} />
              <span style={{ fontSize: '0.66rem', color: 'var(--text-dark, #8b949e)', fontFamily: 'monospace', marginLeft: '6px' }}>
                Sandbox Esecuzione Unit Test
              </span>
            </div>
            <span style={{
              fontSize: '0.66rem', fontWeight: 800, color: result.execution.status === 'passed' ? 'var(--success, #3fb950)' : '#ff5555',
              background: result.execution.status === 'passed' ? 'rgba(63,185,80,0.15)' : 'rgba(255,85,85,0.15)',
              padding: '2px 8px', borderRadius: '4px', textTransform: 'uppercase',
            }}>
              {result.execution.status}
            </span>
          </div>
          {result.execution.detail && (
            <div style={{
              padding: '8px 12px', fontSize: '0.72rem', color: '#e6edf3',
              fontFamily: 'monospace', whiteSpace: 'pre-wrap', maxHeight: '180px', overflowY: 'auto',
            }}>
              {result.execution.detail}
            </div>
          )}
        </div>
      )}

      {/* Sezione Risposta Generata */}
      <div style={{
        background: 'rgba(10,12,26,0.75)',
        padding: '10px 14px',
        borderRadius: '8px',
        border: `1px solid ${style.border}`,
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px' }}>
          <div style={{
            fontSize: '0.64rem', fontWeight: 800, color: style.color,
            textTransform: 'uppercase', letterSpacing: '0.05em',
            display: 'flex', alignItems: 'center', gap: '5px',
          }}>
            <Cpu size={12} /> Risposta Generata da {model}
          </div>

          {/* Toggle Thinking CoT se presente */}
          {thinkingText && (
            <button
              type="button"
              onClick={() => setShowThinking(!showThinking)}
              style={{
                background: 'rgba(188,140,255,0.12)',
                border: '1px solid rgba(188,140,255,0.3)',
                color: '#bc8cff',
                fontSize: '0.64rem',
                fontWeight: 700,
                padding: '2px 8px',
                borderRadius: '5px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              <Zap size={11} />
              {showThinking ? 'Nascondi Ragionamento CoT' : `Mostra CoT (${thinkingText.length} car.)`}
              <ChevronDown size={11} style={{ transform: showThinking ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
            </button>
          )}
        </div>

        {/* Box Thinking Collassabile */}
        {showThinking && thinkingText && (
          <div className="bench-thinking-box" style={{ maxHeight: '240px', overflowY: 'auto' }}>
            <div style={{ fontSize: '0.62rem', fontWeight: 800, color: '#bc8cff', marginBottom: '4px', textTransform: 'uppercase' }}>
              🧠 Catena di Pensiero (Chain of Thought):
            </div>
            <div style={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap', lineHeight: 1.4 }}>
              {thinkingText}
            </div>
          </div>
        )}

        {/* Risposta Pulita Finale */}
        <div style={{
          fontSize: '0.78rem', color: 'var(--text, #fff)',
          fontFamily: 'monospace', whiteSpace: 'pre-wrap', lineHeight: 1.4,
          maxHeight: '340px', overflowY: 'auto',
        }}>
          {cleanAnswer || '(Nessuna risposta testuale prodotta)'}
        </div>

        {/* Risposta Attesa di Riferimento */}
        {!result.options?.length && result.correct_answer && (
          <div style={{
            marginTop: '4px', paddingTop: '8px',
            borderTop: '1px dashed rgba(255,255,255,0.12)',
          }}>
            <div style={{
              fontSize: '0.62rem', fontWeight: 800, color: 'var(--success, #3fb950)',
              textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '3px',
              display: 'flex', alignItems: 'center', gap: '5px',
            }}>
              <Check size={11} /> Risposta Attesa dal Benchmark
              {result.correct_choice && (
                <span style={{ textTransform: 'none', color: 'var(--text-dark, #8b949e)', fontWeight: 600 }}>
                  — target: <b style={{ color: 'var(--success, #3fb950)' }}>{result.correct_choice}</b>
                </span>
              )}
            </div>
            <div style={{
              fontSize: '0.75rem', color: 'var(--text-dark, #8b949e)', fontFamily: 'monospace',
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

function ExtendBenchmarkModal({ open, activeJob, extendSamples, extendSuite, extendMode, extendThinkingMode, extending, onSamples, onSuite, onMode, onThinkingMode, onClose, onConfirm }) {
  if (!open || !activeJob) return null;

  const currentTotal = activeJob.metrics?.tests_total || activeJob.reproducibility?.dataset_items_processed || 0;
  const newEstimate = extendMode === 'full' ? 'Tutti i quesiti (~60.000)' : `${fmt(currentTotal + extendSamples)} quesiti`;

  const suitesAvailable = [
    { id: 'all', label: '🌐 Tutte le suite attive del benchmark' },
    { id: 'mmlu', label: '🏆 MMLU (Conoscenza Generale)' },
    { id: 'mmlu_pro', label: '🧠 MMLU-Pro (Ragionamento Avanzato)' },
    { id: 'gsm8k', label: '🧮 GSM8K (Matematica & Logica)' },
    { id: 'math', label: '📐 MATH (Matematica Olimpica)' },
    { id: 'humaneval', label: '💻 HumanEval (Coding pass@1)' },
    { id: 'mbpp', label: '🐍 MBPP (Python pass@1)' },
    { id: 'arc', label: '🔬 ARC Science (Scienze)' },
    { id: 'hellaswag', label: '💡 HellaSwag (Buon Senso)' },
    { id: 'truthfulqa', label: '🛡️ TruthfulQA (Anti-Allucinazione)' },
    { id: 'gpqa', label: '🎓 GPQA (Livello Accademico)' },
    { id: 'bbh', label: '⚙️ BIG-Bench Hard (Logica Multi-Step)' },
  ];

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      background: 'rgba(0, 0, 0, 0.75)', backdropFilter: 'blur(8px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999, padding: '20px',
    }}>
      <div style={{
        background: 'rgba(15, 18, 35, 0.95)', border: '1px solid rgba(0, 210, 255, 0.4)',
        borderRadius: '16px', padding: '24px', maxWidth: '560px', width: '100%',
        boxShadow: '0 10px 40px rgba(0, 210, 255, 0.25)', display: 'flex', flexDirection: 'column', gap: '16px',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Sparkles size={22} color="#00f2fe" />
            <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 800, color: '#fff' }}>
              Amplia & Continua Benchmark
            </h3>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', fontSize: '1.1rem' }}>✕</button>
        </div>

        <p style={{ margin: 0, fontSize: '0.76rem', color: '#8b949e', lineHeight: 1.4 }}>
          Aggiungi nuovi quesiti senza rieseguire quelli già completati. Il sistema aggregherà le nuove risposte alle precedenti, aggiornando il punteggio in modo incrementale e trasparente.
        </p>

        {/* Riepilogo Stato Attuale */}
        <div style={{
          background: 'rgba(0, 210, 255, 0.08)', border: '1px solid rgba(0, 210, 255, 0.25)',
          borderRadius: '10px', padding: '12px 14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div>
            <div style={{ fontSize: '0.64rem', color: '#8b949e', textTransform: 'uppercase' }}>Modello & Stato Attuale</div>
            <div style={{ fontSize: '0.86rem', fontWeight: 800, color: '#fff', marginTop: '2px' }}>{formatModelDisplay(activeJob.model)}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '3px' }}>
              <span style={{ fontSize: '0.68rem', color: '#00f2fe' }}>{activeJob.suite_name || activeJob.suite}</span>
              <span style={{
                fontSize: '0.6rem', padding: '1px 6px', borderRadius: '4px',
                background: activeJob.thinking_mode === 'no_thinking' ? 'rgba(255,184,108,0.15)' : activeJob.thinking_mode === 'thinking' ? 'rgba(188,140,255,0.15)' : activeJob.thinking_mode === 'mixed' ? 'rgba(0,210,255,0.2)' : 'rgba(0,210,255,0.12)',
                color: activeJob.thinking_mode === 'no_thinking' ? '#ffb86c' : activeJob.thinking_mode === 'thinking' ? '#bc8cff' : activeJob.thinking_mode === 'mixed' ? '#00f2fe' : ACCENT,
                fontWeight: 700,
              }}>
                {activeJob.thinking_mode === 'no_thinking' ? '⚡ No-Think' : activeJob.thinking_mode === 'thinking' ? '💡 CoT' : activeJob.thinking_mode === 'mixed' ? '🔀 Ibrido' : '🧠 Auto'}
              </span>
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '0.64rem', color: '#8b949e', textTransform: 'uppercase' }}>Completati</div>
            <div style={{ fontSize: '1.1rem', fontWeight: 800, color: '#3fb950' }}>{fmt(currentTotal)}</div>
          </div>
        </div>

        {/* Scelta Modalità & Campioni */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <label style={{ fontSize: '0.72rem', fontWeight: 700, color: '#fff' }}>
            Quanti nuovi quesiti aggiungere?
          </label>
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            {[25, 50, 100, 250, 500].map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => { onMode('sample'); onSamples(n); }}
                style={{
                  ...btn(extendMode === 'sample' && extendSamples === n),
                  fontSize: '0.74rem', padding: '6px 12px',
                }}
              >
                +{n} quesiti
              </button>
            ))}
            <button
              type="button"
              onClick={() => onMode('full')}
              style={{
                ...btn(extendMode === 'full', '#3fb950'),
                fontSize: '0.74rem', padding: '6px 12px',
              }}
            >
              🏆 Completa 100% (Tutti)
            </button>
          </div>
        </div>

        {/* Scelta Modalità Thinking & Ragionamento */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <label style={{ fontSize: '0.72rem', fontWeight: 700, color: '#fff', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Zap size={13} style={{ color: ACCENT }} /> Modalità Thinking & Ragionamento per i nuovi quesiti
          </label>
          <div style={{ display: 'flex', gap: '6px' }}>
            <button
              type="button"
              onClick={() => onThinkingMode('auto')}
              style={{
                flex: 1, padding: '7px 8px', borderRadius: '8px', cursor: 'pointer',
                border: `1px solid ${extendThinkingMode === 'auto' ? ACCENT : 'rgba(255,255,255,0.08)'}`,
                background: extendThinkingMode === 'auto' ? 'rgba(0,210,255,0.15)' : 'rgba(0,0,0,0.25)',
                color: extendThinkingMode === 'auto' ? ACCENT : 'var(--text-dark, #8b949e)',
                fontSize: '0.72rem', fontWeight: 700,
              }}
            >
              🧠 Auto (Suite)
            </button>
            <button
              type="button"
              onClick={() => onThinkingMode('no_thinking')}
              style={{
                flex: 1, padding: '7px 8px', borderRadius: '8px', cursor: 'pointer',
                border: `1px solid ${extendThinkingMode === 'no_thinking' ? '#ffb86c' : 'rgba(255,255,255,0.08)'}`,
                background: extendThinkingMode === 'no_thinking' ? 'rgba(255,184,108,0.15)' : 'rgba(0,0,0,0.25)',
                color: extendThinkingMode === 'no_thinking' ? '#ffb86c' : 'var(--text-dark, #8b949e)',
                fontSize: '0.72rem', fontWeight: 700,
              }}
            >
              ⚡ No-Thinking
            </button>
            <button
              type="button"
              onClick={() => onThinkingMode('thinking')}
              style={{
                flex: 1, padding: '7px 8px', borderRadius: '8px', cursor: 'pointer',
                border: `1px solid ${extendThinkingMode === 'thinking' ? 'var(--success, #3fb950)' : 'rgba(255,255,255,0.08)'}`,
                background: extendThinkingMode === 'thinking' ? 'rgba(63,185,80,0.15)' : 'rgba(0,0,0,0.25)',
                color: extendThinkingMode === 'thinking' ? 'var(--success, #3fb950)' : 'var(--text-dark, #8b949e)',
                fontSize: '0.72rem', fontWeight: 700,
              }}
            >
              💡 Thinking CoT
            </button>
          </div>
          <div style={{ fontSize: '0.66rem', color: 'var(--text-dark, #8b949e)' }}>
            {extendThinkingMode === 'auto' && 'Protocollo standard: CoT sui task di logica e matematica, risposta diretta sui compiti a scelta.'}
            {extendThinkingMode === 'no_thinking' && 'Forza risposte dirette senza Chain-of-Thought per misurare velocità e istinto del modello.'}
            {extendThinkingMode === 'thinking' && 'Forza catena di pensiero estesa (Chain-of-Thought) su tutti i quesiti aggiunti.'}
          </div>
        </div>

        {/* Scelta Suite da Ampliare */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <label style={{ fontSize: '0.72rem', fontWeight: 700, color: '#fff' }}>
            Quale dataset / suite ampliare?
          </label>
          <select
            value={extendSuite}
            onChange={(e) => onSuite(e.target.value)}
            style={{
              background: 'rgba(10, 12, 26, 0.9)', border: '1px solid rgba(255, 255, 255, 0.15)',
              borderRadius: '8px', padding: '8px 12px', color: '#fff', fontSize: '0.78rem', outline: 'none',
            }}
          >
            {suitesAvailable.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
          {extendSuite && SUITE_LABELS[extendSuite]?.description && (
            <div style={{
              fontSize: '0.68rem', color: '#00d2ff', background: 'rgba(0,210,255,0.06)',
              border: '1px solid rgba(0,210,255,0.2)', borderRadius: '6px', padding: '7px 10px',
              lineHeight: 1.35,
            }}>
              ℹ️ <b>{SUITE_LABELS[extendSuite].category}:</b> {SUITE_LABELS[extendSuite].description}
            </div>
          )}
        </div>

        {/* Anteprima Totale */}
        <div style={{ fontSize: '0.72rem', color: '#8b949e', background: 'rgba(255, 255, 255, 0.03)', borderRadius: '8px', padding: '8px 12px' }}>
          📈 Totale quesiti risultante: <b style={{ color: '#fff' }}>{fmt(currentTotal)}</b> ➔ <b style={{ color: '#00f2fe' }}>{newEstimate}</b> · Modalità: <b style={{ color: extendThinkingMode === 'no_thinking' ? '#ffb86c' : extendThinkingMode === 'thinking' ? '#bc8cff' : '#00d2ff' }}>
            {extendThinkingMode === 'no_thinking' ? '⚡ No-Thinking' : extendThinkingMode === 'thinking' ? '💡 Thinking CoT' : '🧠 Auto (Suite)'}
          </b>
        </div>

        {/* Azioni */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '6px' }}>
          <button
            type="button"
            onClick={onClose}
            style={{ ...btn(false), padding: '8px 16px', fontSize: '0.78rem' }}
          >
            Annulla
          </button>
          <button
            type="button"
            disabled={extending}
            onClick={onConfirm}
            style={{
              height: '38px', padding: '0 20px', border: 'none', borderRadius: '8px',
              background: 'linear-gradient(135deg, #00d2ff 0%, #0072ff 100%)', color: '#fff',
              fontWeight: 700, fontSize: '0.8rem', cursor: extending ? 'not-allowed' : 'pointer',
              display: 'flex', alignItems: 'center', gap: '6px',
            }}
          >
            {extending ? <RefreshCw size={14} className="spin-icon" /> : <Play size={14} />}
            Avvia Ampliamento
          </button>
        </div>
      </div>
    </div>
  );
}

