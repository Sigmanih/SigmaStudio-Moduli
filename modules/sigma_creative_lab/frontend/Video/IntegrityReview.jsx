import React, { useState, useEffect } from 'react';

const CHECKS = { anatomy: 'Corpo, arti, volto e articolazioni coerenti', hands: 'Mani, pollici e dita corretti, senza duplicazioni',
  objects: 'Oggetti, prese e contatti fisicamente coerenti', continuity: 'Nessuna deformazione o comparsa anomala durante la clip' };

export default function IntegrityReview({ shot, disabled, onCheck, onReview, toUrl }) {
  const [reason, setReason] = useState('');
  const [checks, setChecks] = useState([]);
  const [confirmed, setConfirmed] = useState(false);
  const record = shot.visual_integrity;
  useEffect(() => { setReason(''); setChecks([]); setConfirmed(false); }, [shot.id, record?.sha256]);
  if (!shot.clip_url) return null;
  return <details>
    <summary>Controllo anatomia, mani e oggetti · {shot.integrity_review?.verdict === 'approve' ? 'revisionata' : 'revisione richiesta'}</summary>
    <p className="cs-hint">Il giudice automatico può non vedere difetti evidenti. Apri i fotogrammi a piena risoluzione e controlla anche la clip completa prima di approvare. Il controllo del movimento è separato.</p>
    <button className="cs-tool-btn" disabled={disabled} onClick={onCheck}>Analizza anatomia e prepara fotogrammi</button>
    {record && <>
      <p className="cs-hint">Controllo automatico: {({pass:'positivo',fail:'negativo',uncertain:'incerto'})[record.status] || 'non disponibile'} · {record.sampled_frames} fotogrammi campionati</p>
      {(record.issues || []).map((issue, index) => <p className="cs-hint" key={index}>{issue}</p>)}
      <div className="cs-inline-params">{(record.evidence || []).map((path, index) => <a key={path} href={toUrl(path)} target="_blank" rel="noreferrer">Fotogramma {index + 1}</a>)}</div>
      {Object.entries(CHECKS).map(([key, label]) => <label key={key} className="cs-hint">
        <input type="checkbox" checked={checks.includes(key)} disabled={disabled} onChange={e => setChecks(e.target.checked ? [...checks, key] : checks.filter(x => x !== key))} /> {label}
      </label>)}
      <textarea className="cs-textarea" rows={3} maxLength={1500} value={reason} disabled={disabled} onChange={e => setReason(e.target.value)} placeholder="Descrivi cosa hai verificato e gli eventuali difetti (almeno 40 caratteri)" />
      <label className="cs-hint"><input type="checkbox" checked={confirmed} disabled={disabled} onChange={e => setConfirmed(e.target.checked)} /> Ho verificato i dettagli e la continuità della clip attuale</label>
      <button className="cs-tool-btn" disabled={disabled || !confirmed || checks.length !== 4 || reason.trim().length < 40 || record.status !== 'pass'} onClick={() => onReview({ verdict: 'approve', reason, checks, sha256: record.sha256, confirmed })}>Approva integrità visiva</button>
      <button className="cs-tool-btn" disabled={disabled || !confirmed || reason.trim().length < 40} onClick={() => onReview({ verdict: 'reject', reason, checks, sha256: record.sha256, confirmed })}>Respingi clip difettosa</button>
    </>}
    {shot.integrity_review && <p className="cs-hint">Revisione: {shot.integrity_review.verdict === 'approve' ? 'approvata' : 'respinta'} · {shot.integrity_review.reason}</p>}
  </details>;
}
