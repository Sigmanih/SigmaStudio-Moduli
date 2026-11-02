import React from 'react';
import { Image as ImageIcon, Download, Edit3, RotateCcw, Upload, ArrowUpRight } from 'lucide-react';

export default function CreationResults({ asset, assets, busy, onSelect, onEdit, onReuse, onUpload }) {
  return <section className="cs-creation-results" aria-label="Immagini create" data-agent-component="CreationResults" data-agent-id="creative-image-results">
    <div className="cs-result-heading"><div><span className="cs-eyebrow">SPAZIO ALL’IMMAGINAZIONE</span><h2>{asset ? 'La tua immagine' : 'Qui prende forma la tua idea'}</h2></div><button type="button" className="cs-secondary-button" onClick={onUpload} disabled={busy}><Upload size={15} /> Importa immagine</button></div>
    <div className={`cs-image-stage ${asset?.url ? 'has-image' : ''}`}>
      {asset?.url ? <img src={asset.url} alt={asset.name || 'Immagine selezionata'} /> : <div className="cs-stage-empty"><ImageIcon size={48} strokeWidth={1} /><h3>Ogni immagine comincia da una descrizione.</h3><p>Racconta il soggetto, l’atmosfera e lo stile. Il risultato comparirà qui, pronto da salvare o modificare.</p></div>}
    </div>
    {asset?.url && <div className="cs-result-actions"><span title={asset.name}>{asset.name || 'Immagine selezionata'}</span><a className="cs-secondary-button" href={asset.url} download><Download size={15} /> Scarica</a><button className="cs-secondary-button" type="button" onClick={() => onEdit(asset)} disabled={busy}><Edit3 size={15} /> Modifica</button>{asset.metadata?.params?.prompt && <button className="cs-secondary-button" type="button" onClick={() => onReuse(asset)} disabled={busy}><RotateCcw size={15} /> Riutilizza descrizione</button>}</div>}
    {assets.length > 0 && <section className="cs-recent-images" aria-label="Immagini recenti"><div className="cs-section-heading"><h3>Le tue immagini recenti</h3><small>{assets.length} immagini</small></div><div className="cs-recent-grid">{assets.slice(0, 12).map(item => <button key={item.id} type="button" aria-label={`Mostra ${item.name || 'immagine'}`} aria-pressed={asset?.id === item.id} onClick={() => onSelect(item)}>{item.url ? <img src={item.url} alt="" loading="lazy" /> : <ImageIcon size={24} />}<span>{item.name || 'Immagine'}</span><ArrowUpRight size={13} /></button>)}</div></section>}
  </section>;
}
