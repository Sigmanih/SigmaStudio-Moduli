import React, { useState } from 'react';
import { Search, Image as ImageIcon, Box, Layers, Film, Upload, X, Edit3, Trash2, Download } from 'lucide-react';

const TYPES = { image: 'Immagine', render: 'Render', mesh: 'Modello 3D', model_3d: 'Modello 3D', material: 'Materiale', video: 'Video' };
const FILTERS = [['all', 'Tutti'], ['image', 'Immagini'], ['3d', '3D'], ['material', 'Materiali'], ['video', 'Video']];

export default function AssetLibrary({ assets, selectedAsset, onSelect, onOpen, onUpload, onDelete, onClose, busy }) {
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [deleting, setDeleting] = useState(null);
  const filtered = assets.filter(a => (!query.trim() || (a.name || '').toLowerCase().includes(query.trim().toLowerCase())) &&
    (filter === 'all' || (filter === 'image' ? ['image', 'render'].includes(a.type) : filter === '3d' ? ['mesh', 'model_3d'].includes(a.type) : a.type === filter)));
  const isImage = a => ['image', 'render'].includes(a.type);
  return <aside className="cs-library" aria-label="Libreria creativa" data-agent-component="AssetLibrary" data-agent-id="creative-library">
    <header className="cs-section-heading"><h2>Libreria <small>{assets.length}</small></h2><button className="cs-icon-button" onClick={onClose} aria-label="Chiudi libreria"><X size={17} /></button></header>
    <button className="cs-secondary-button" onClick={onUpload} disabled={busy}><Upload size={16} /> Importa un’immagine</button>
    <label className="cs-library-search"><Search size={16} /><input type="search" aria-label="Cerca nella libreria" placeholder="Cerca per nome…" value={query} onChange={e => setQuery(e.target.value)} /></label>
    <div className="cs-library-filters" aria-label="Filtra gli elementi">{FILTERS.map(([id, label]) => <button className="cs-choice" key={id} aria-pressed={filter === id} onClick={() => setFilter(id)}>{label}</button>)}</div>
    <div className="cs-library-list">{filtered.length ? filtered.map(a => {
      const Icon = isImage(a) ? ImageIcon : a.type === 'video' ? Film : a.type === 'material' ? Layers : Box;
      return <button key={a.id} className="cs-library-item" aria-pressed={selectedAsset?.id === a.id} onClick={() => { onSelect(a); setDeleting(null); }} onDoubleClick={() => onOpen(a)}>
        {isImage(a) && a.url ? <img src={a.url} alt="" loading="lazy" /> : <Icon size={25} />}<span>{a.name || 'Senza titolo'}<small>{TYPES[a.type] || 'Elemento creativo'}</small></span>
      </button>;
    }) : <div className="cs-library-empty"><ImageIcon size={30} /><p>{assets.length ? 'Nessun risultato per questa ricerca.' : 'Qui troverai le tue creazioni. Parti da una descrizione o importa un’immagine.'}</p>{assets.length > 0 && <button className="cs-text-button" onClick={() => { setQuery(''); setFilter('all'); }}>Mostra tutti</button>}</div>}</div>
    {selectedAsset && <footer className="cs-library-actions"><strong>{selectedAsset.name || 'Elemento selezionato'}</strong><div>
      {selectedAsset.type !== 'video' && <button className="cs-secondary-button" onClick={() => onOpen(selectedAsset)} disabled={busy}><Edit3 size={14} /> Apri</button>}
      {selectedAsset.url && <a className="cs-icon-button" href={selectedAsset.url} download aria-label="Scarica l’elemento selezionato"><Download size={16} /></a>}
      <button className="cs-icon-button cs-danger" disabled={busy} onClick={() => setDeleting(selectedAsset.id)} aria-label="Elimina l’elemento selezionato"><Trash2 size={15} /></button>
    </div>{deleting === selectedAsset.id && <div className="cs-delete-confirm" role="alert"><p>Vuoi eliminare questo elemento dalla libreria?</p><button className="cs-secondary-button cs-danger" onClick={() => { onDelete(selectedAsset.id); setDeleting(null); }}>Elimina</button><button className="cs-text-button" onClick={() => setDeleting(null)}>Annulla</button></div>}</footer>}
  </aside>;
}
