import React, { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Play } from 'lucide-react';
import '../../styles/03-modules/sigma-baseline.css';

const LABELS = {
  inference_error: 'Errore di inferenza', token_limit: 'Budget di token esaurito',
  timeout: 'Timeout del codice', no_code: 'Codice assente', no_tests: 'Test assenti',
  error: 'Errore di verifica', syntax_error: 'Sintassi', wrong_result: 'Risultato errato',
  runtime_error: 'Errore in esecuzione', unverified: 'Esito non verificabile',
};

export default function SigmaBaselineView({ models, jobs, onStarted }) {
  const [report, setReport] = useState(null);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [agentBusy, setAgentBusy] = useState(false);
  const [agentJobId, setAgentJobId] = useState('');
  const candidates = models.filter((m) => !m.is_proxy && m.details?.type !== 'vram'
    && (/^sigma:sigma(?:[-_.][a-z0-9][a-z0-9_.-]{0,95})?$/i.test(String(m.id))
      || /qwen3827b/.test(String(m.id).toLowerCase().replace(/[^a-z0-9]/g, ''))));
  const model = candidates.some((m) => m.id === selected) ? selected
    : (candidates.find((m) => m.id === 'sigma:sigma')?.id
      || candidates.find((m) => m.quantization === 'Q4_K_M')?.id || candidates[0]?.id || '');
  const running = [...jobs, ...(report?.protocol_runs || [])].some((j) => ['preparing', 'loading_model', 'running', 'executing',
    'pausing', 'paused', 'cancelling'].includes(j.status));
  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/benchmark/sigma/baseline', { signal: AbortSignal.timeout(20000) });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || 'Profilo non disponibile');
      setReport(data);
      const activeAgent = (data.protocol_runs || []).find((run) => ['running', 'cancelling'].includes(run.status));
      if (activeAgent) {
        setAgentBusy(true);
        setAgentJobId((current) => current || activeAgent.job_id);
      }
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!agentJobId) return undefined;
    let cancelled = false;
    let timer;
    const poll = async () => {
      try {
        const response = await fetch(`/api/benchmark/protocol/status?job_id=${encodeURIComponent(agentJobId)}`,
          { signal: AbortSignal.timeout(10000) });
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || 'Stato del benchmark non disponibile');
        if (data.job?.id !== agentJobId || data.job?.status === 'not_found') {
          if (!cancelled) { setAgentBusy(false); setAgentJobId(''); setError('Benchmark agente non trovato'); load(); }
          return;
        }
        if (!cancelled && ['completed', 'failed', 'cancelled'].includes(data.job?.status)) {
          setAgentBusy(false);
          setAgentJobId('');
          if (data.job.status === 'failed') setError(data.job.error || 'Benchmark agente fallito');
          load();
          return;
        }
      } catch (err) { if (!cancelled) setError(err.message); }
      if (!cancelled) timer = setTimeout(poll, 2500);
    };
    poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [agentJobId, load]);

  const launchAgent = async () => {
    setAgentBusy(true);
    setError('');
    try {
      const prepared = await fetch('/api/benchmark/sigma/prepare', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model }), signal: AbortSignal.timeout(180000),
      });
      const preparation = await prepared.json();
      if (!prepared.ok || !preparation.success) throw new Error(preparation.error || 'Vincolo hardware non verificato');
      const response = await fetch('/api/benchmark/protocol/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model }), signal: AbortSignal.timeout(30000),
      });
      const data = await response.json();
      if (!response.ok || !data.success || !data.job_id) throw new Error(data.error || 'Avvio agente non riuscito');
      setAgentJobId(data.job_id);
      load();
    } catch (err) { setError(err.message); setAgentBusy(false); }
  };

  const launch = async () => {
    setBusy(true);
    setError('');
    try {
      const profile = report.profile;
      const prepared = await fetch('/api/benchmark/sigma/prepare', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model }), signal: AbortSignal.timeout(180000),
      });
      const preparation = await prepared.json();
      if (!prepared.ok || !preparation.success) throw new Error(preparation.error || 'Vincolo hardware non verificato');
      const response = await fetch('/api/benchmark/run', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model, suite: profile.suite, samples: profile.samples,
          mode: profile.mode, concurrency: profile.concurrency, thinking_mode: profile.thinking_mode }),
        signal: AbortSignal.timeout(30000),
      });
      const data = await response.json();
      if (!response.ok || !data.success || !data.job?.id) throw new Error(data.error || 'Avvio non riuscito');
      onStarted(data.job.id);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };

  return (
    <section className="sigma-baseline">
      <div className="sigma-baseline-heading">
        <div><h2>sigma</h2><p>Modello locale · Primo tentativo verificato</p></div>
        <button type="button" onClick={load} disabled={loading}><RefreshCw size={16} /> Aggiorna profilo</button>
      </div>
      <p>HumanEval e MBPP, 100 quesiti complessivi, seed 42, temperatura 0, thinking disattivato e una richiesta alla volta.</p>
      <p><strong>Obiettivo di ottimizzazione:</strong> sola RTX 5070 Ti da 16 GiB, contesto di 8.192 token e batch 1.
        Budget iniziale dei pesi: 13 GiB, da confermare con la memoria effettiva di cache e buffer.
        Prima della misura il modello viene ricaricato e tutti i layer devono risultare sulla GPU, senza offload CPU.</p>
      <div className="sigma-baseline-controls">
        <label>Quantizzazione
          <select value={model} onChange={(event) => setSelected(event.target.value)} disabled={busy || agentBusy || running}>
            {!candidates.length && <option value="">Nessun modello locale compatibile disponibile</option>}
            {candidates.map((m) => <option key={m.id} value={m.id}>{m.name} · {m.quantization}</option>)}
          </select>
        </label>
        <button type="button" onClick={launch} disabled={!model || !report || busy || agentBusy || running}>
          <Play size={16} /> {busy ? 'Avvio…' : 'Misura coding'}
        </button>
        <button type="button" onClick={launchAgent} disabled={!model || !report || busy || agentBusy || running}>
          <Play size={16} /> {agentBusy ? 'Valutazione agente…' : 'Misura agente e tool'}
        </button>
      </div>
      {running && <p>È presente una valutazione attiva o sospesa. Completala prima di cambiare modello.</p>}
      {error && <p role="alert">{error}</p>}
      {loading && <p role="status">Caricamento delle misure…</p>}
      {agentJobId && <p role="status">Benchmark agente in esecuzione: {agentJobId}. L’esito viene aggiornato automaticamente.</p>}
      {report && <>
        {report.current_runtime?.model && <p>Motore attuale: {report.current_runtime.model} · contesto {report.current_runtime.n_ctx ?? 'non rilevato'} token ·
          {report.current_runtime.forced_single_gpu ? ` GPU singola ${report.current_runtime.main_gpu}` : ' GPU singola non imposta'}.
          Questa configurazione descrive il motore attuale, non i run storici.</p>}
        <p>{report.note}</p>
        {report.partial && <p>Storico parziale: sono mostrati solo i run entro il budget di lettura.</p>}
        <div className="sigma-baseline-table"><table>
          <caption>Misure di coding salvate · ogni riga è un run, senza graduatoria automatica</caption>
          <thead><tr><th>Modello / run</th><th>Stato</th><th>HumanEval</th><th>MBPP</th><th>pass@1</th>
            <th>Token/s del run</th><th>Latenza media</th><th>Collocazione registrata</th><th>Errori osservati</th></tr></thead>
          <tbody>{report.runs.map((run) => <tr key={run.job_id}>
            <td>{run.model}<small>{run.job_id}</small>{run.purpose === 'integration_smoke' && <small>Collaudo di integrazione</small>}</td><td>{run.status}</td>
            <td>{run.suites.humaneval.passed}/{run.suites.humaneval.total}</td>
            <td>{run.suites.mbpp.passed}/{run.suites.mbpp.total}</td>
            <td>{run.pass_at_1_pct ?? '—'}%</td>
            <td>{run.tokens_per_second ?? '—'}</td>
            <td>{run.avg_latency_ms == null ? '—' : `${run.avg_latency_ms} ms`}</td>
            <td>{run.execution_environment
              ? `${run.execution_environment.placement?.fully_offloaded ? 'Tutti i pesi su GPU' : 'Offload parziale'} · ${run.execution_environment.settings?.n_ctx ?? '—'} token`
              : 'Non registrata'}</td>
            <td>{Object.entries(run.failures).map(([kind, n]) => `${LABELS[kind] || kind}: ${n}`).join(' · ') || 'Nessuno'}</td>
          </tr>)}</tbody>
        </table></div>
        {!report.runs.length && <p>Nessuna misura di coding salvata per questa famiglia.</p>}
        <p>Il confronto richiede gli stessi quesiti, test e protocolli registrati. Campioni piccoli e run incompleti non stabiliscono quale quantizzazione sia migliore.</p>
        <details><summary>Confronti con quesiti e protocolli corrispondenti</summary>
        <ul>{report.comparisons.filter((c) => c.comparable).map((c) => <li key={`${c.left}-${c.right}`}>
          {c.left} → {c.right}: {c.delta_points > 0 ? '+' : ''}{c.delta_points} punti, sui dati registrati.
        </li>)}</ul></details>
        <h3>Compiti dell’agente e uso dei tool</h3>
        <p>Il successo richiede un risultato verificato, chiusura del compito e rispetto dei limiti.
          L’aderenza ai tool è una misura separata. Run con scenari diversi non sono confronti diretti.</p>
        <div className="sigma-baseline-table"><table>
          <caption>Completamento dei compiti · obiettivo superiore al 90% sui compiti valutati</caption>
          <thead><tr><th>Run / stato</th><th>Compiti riusciti</th><th>Aderenza ai tool</th><th>Checkpoint</th><th>Scenari ed errori</th></tr></thead>
          <tbody>{report.protocol_runs.map((run) => <tr key={run.job_id}>
            <td>{run.job_id}<small>{run.status}</small>{run.purpose === 'integration_smoke' && <small>Collaudo di integrazione</small>}</td>
            <td>{run.tasks_passed}/{run.tasks_total} · {run.task_success_pct ?? '—'}%
              {!!run.tasks_unverified && <small>{run.tasks_unverified} non verificati, inclusi nel totale</small>}</td>
            <td>{run.score ?? '—'}/100</td>
            <td>{run.checkpoint_sha256 ? <span title={run.checkpoint_sha256}>{run.checkpoint_sha256.slice(0, 12)}</span> : 'Impronta non registrata'}
              <small>{run.comparable ? 'Evidenza confrontabile' : 'Confronto non verificato'}</small></td>
            <td><details><summary>{run.cases?.length ?? 0} scenari</summary>
              <ul>{(run.cases || []).map((item) => <li key={item.id}>{item.id}: {item.passed === true ? 'riuscito' : item.passed === false ? 'non riuscito' : 'non verificato'}</li>)}</ul>
              <p>{Object.entries(run.failures).map(([kind, n]) => `${kind}: ${n}`).join(' · ') || 'Nessun errore di protocollo registrato'}</p>
              {(run.evidence_issues || []).map((issue, index) => <p key={`${index}-${issue}`}>{issue}</p>)}
            </details></td>
          </tr>)}</tbody>
        </table></div>
        <details><summary>Associazione codice e agente per checkpoint</summary>
          <p>{report.combined_evaluation?.policy}</p>
          {!report.combined_evaluation?.bundles?.length && <p>Nessuna coppia verificata disponibile.
            Le nuove esecuzioni registrano l’impronta dei pesi prima e dopo la prova; lo storico resta consultabile.</p>}
          {(report.combined_evaluation?.bundles || []).map((bundle) => <p key={bundle.id}>
            <strong>{bundle.checkpoint_sha256.slice(0, 12)}</strong>: codice {bundle.coding.passed}/{bundle.coding.total}
            {' · '}agente {bundle.agent.tasks_passed}/{bundle.agent.tasks_total}
            <small>{bundle.coding.job_id} · {bundle.agent.job_id}</small>
            <small>Valutazione {bundle.id.slice(0, 8)} · versione agente {bundle.agent.harness_fingerprint.slice(0, 8)}</small>
            {(bundle.coding.purpose === 'integration_smoke' || bundle.agent.purpose === 'integration_smoke') && <small>Associazione di collaudo: non certifica la qualità del modello</small>}
          </p>)}
          {(report.combined_evaluation?.comparisons || []).map((comparison) => <p key={`${comparison.reference}-${comparison.candidate}`}>
            {comparison.reference.slice(0, 8)} → {comparison.candidate.slice(0, 8)}: {({
              insufficient_evidence: 'evidenza incompleta', regression: 'regressione rilevata',
              no_demonstrated_gain: 'nessun guadagno dimostrato', candidate_for_validation: 'candidato da validare su nuovi compiti',
            })[comparison.status] || comparison.status}
            <small>Variazione: {({ weights: 'pesi', harness: 'motore agente', weights_and_harness: 'pesi e motore agente', repeat: 'ripetizione' })[comparison.change_axis]}</small>
            {!!comparison.issues.length && <small>{comparison.issues.join(' · ')}</small>}
          </p>)}
        </details>
      </>}
    </section>
  );
}
