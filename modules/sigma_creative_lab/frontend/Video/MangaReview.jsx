import React, { useState, useEffect, useCallback } from 'react';
import { Users, CheckCircle2, Loader2, RefreshCw, MessageSquare } from 'lucide-react';

/*
 * Revisione di chi c'e' e chi parla in ogni vignetta di un fumetto trasposto.
 *
 * Il riconoscimento automatico sbaglia proprio qui: dal bianco e nero ne' la vista
 * ne' l'LLM capiscono chi e' chi, e una battuta finita al personaggio sbagliato
 * esce con la voce sbagliata. Chi conosce il fumetto lo vede in un attimo: una
 * vignetta per riga, un clic per correggere, e la correzione resta (la regia e la
 * rilettura automatica non la toccano piu').
 */

const API = '/api/creative/productions/manga/review';
const TIPO = { battuta: 'Battuta', pensiero: 'Pensiero', didascalia: 'Didascalia' };

async function call(url, body) {
  const res = await fetch(url, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  let data = {};
  try { data = await res.json(); } catch { /* risposta non JSON */ }
  if (!res.ok || data.success === false) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function PanelRow({ panel, characters, disabled, onSave }) {
  const [presenti, setPresenti] = useState(panel.presenti);
  const [righe, setRighe] = useState(panel.righe);
  const [saving, setSaving] = useState(false);
  const dirty = JSON.stringify(presenti) !== JSON.stringify(panel.presenti)
    || JSON.stringify(righe) !== JSON.stringify(panel.righe);

  useEffect(() => { setPresenti(panel.presenti); setRighe(panel.righe); }, [panel]);

  const togglePresente = (nome) => setPresenti(p => (p.includes(nome) ? p.filter(x => x !== nome) : [...p, nome]));
  const setRiga = (i, patch) => setRighe(r => r.map(x => (x.i === i ? { ...x, ...patch } : x)));

  const save = async () => {
    setSaving(true);
    const voci = Object.fromEntries(righe.map(r => [r.i, { chi: r.chi, fuori_campo: r.fuori_campo }]));
    try { await onSave(panel.id, presenti, voci); } finally { setSaving(false); }
  };

  return (
    <div className={`cs-review-row ${panel.rivista ? 'is-reviewed' : ''}`}>
      <img className="cs-review-panel" src={panel.ritaglio_url} alt={`Vignetta ${panel.id}`} loading="lazy" />
      <div className="cs-review-body">
        <div className="cs-review-head">
          <strong>{panel.id}</strong>
          {panel.rivista && <span className="cs-review-badge"><CheckCircle2 size={13} /> rivista</span>}
        </div>
        <div className="cs-review-cast" title="Chi si vede nella vignetta">
          <Users size={14} />
          {characters.map(nome => (
            <button key={nome} type="button" disabled={disabled}
                    className={`cs-review-chip ${presenti.includes(nome) ? 'is-on' : ''}`}
                    onClick={() => togglePresente(nome)}>{nome}</button>
          ))}
        </div>
        {righe.map(r => (
          <div key={r.i} className="cs-review-line">
            <span className="cs-review-kind">{TIPO[r.tipo] || r.tipo}</span>
            <span className="cs-review-text">{r.testo}</span>
            <select className="cs-review-select" value={r.chi} disabled={disabled}
                    onChange={e => setRiga(r.i, { chi: e.target.value })}>
              {!characters.includes(r.chi) && r.chi !== 'narrator' && <option value={r.chi}>{r.chi || '—'}</option>}
              <option value="narrator">Narratore</option>
              {characters.map(nome => <option key={nome} value={nome}>{nome}</option>)}
            </select>
            <label className="cs-review-off" title="Chi parla non si vede nella vignetta: voce fuori campo, niente labiale">
              <input type="checkbox" checked={r.fuori_campo} disabled={disabled}
                     onChange={e => setRiga(r.i, { fuori_campo: e.target.checked })} /> fuori campo
            </label>
          </div>
        ))}
        <button type="button" className="cs-tool-btn" disabled={disabled || saving || (!dirty && panel.rivista)}
                onClick={save}>
          {saving ? <Loader2 size={14} className="cs-spin-icon" /> : <CheckCircle2 size={14} />}
          {dirty ? 'Salva correzione' : 'Confermo cosi'}
        </button>
      </div>
    </div>
  );
}

export default function MangaReview({ productionId, disabled, onChanged }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [soloDaRivedere, setSoloDaRivedere] = useState(true);
  const [limite, setLimite] = useState(20);

  const load = useCallback(async () => {
    setError('');
    try { setData(await call(`${API}?id=${encodeURIComponent(productionId)}`)); }
    catch (e) { setError(e.message); }
  }, [productionId]);

  useEffect(() => { load(); }, [load]);

  const onSave = async (panelId, presenti, voci) => {
    setError('');
    try {
      await call(API, { id: productionId, panel_id: panelId, presenti, voci });
      setData(d => ({ ...d, panels: d.panels.map(p => (p.id === panelId ? { ...p, presenti, rivista: true,
        righe: p.righe.map(r => ({ ...r, ...(voci[r.i] || {}) })) } : p)) }));
      if (onChanged) onChanged();
    } catch (e) { setError(e.message); }
  };

  if (!data) {
    return error ? <div className="cs-mesh-card"><p className="cs-error">{error}</p></div> : null;
  }
  const conTesto = data.panels.filter(p => p.righe.length);
  const riviste = data.panels.filter(p => p.rivista).length;
  const elenco = (soloDaRivedere ? conTesto.filter(p => !p.rivista) : data.panels).slice(0, limite);

  return (
    <div className="cs-mesh-card">
      <h3 className="cs-mesh-title"><MessageSquare size={18} /> Chi c'e' e chi parla ({riviste}/{data.panels.length} riviste)</h3>
      <p className="cs-hint">
        Il riconoscimento automatico confonde i personaggi del bianco e nero. Controlla le vignette: chi si vede
        e chi dice ogni battuta. Le correzioni restano e passano subito alle inquadrature; quelle gia' rese tornano da rifare.
      </p>
      <div className="cs-review-tools">
        <label><input type="checkbox" checked={soloDaRivedere} onChange={e => setSoloDaRivedere(e.target.checked)} />
          {' '}solo vignette con battute non ancora riviste ({conTesto.filter(p => !p.rivista).length})</label>
        <button type="button" className="cs-tool-btn" onClick={load}><RefreshCw size={14} /> Aggiorna</button>
      </div>
      {error && <p className="cs-error">{error}</p>}
      <div className="cs-review-list">
        {elenco.map(p => (
          <PanelRow key={p.id} panel={p} characters={data.characters} disabled={disabled} onSave={onSave} />
        ))}
      </div>
      {elenco.length >= limite && (
        <button type="button" className="cs-tool-btn" onClick={() => setLimite(l => l + 20)}>Mostra altre 20</button>
      )}
    </div>
  );
}
