import React, { useState, useEffect, useCallback, Suspense, lazy } from 'react';
import { Wand2, Edit3, Box, Hexagon, Layers, Workflow, Cpu, X, RefreshCw, Palette, Library } from 'lucide-react';
import { useApp } from '../../contexts/AppContext';
import TabHeader from '../../components/common/TabHeader';
import GeneratePanel from './Generate/GeneratePanel';
import EditCanvas from './Edit/EditCanvas';
import MeshLab from './MeshLab/MeshLab';
import MaterialsPanel from './Materials/MaterialsPanel';
import ModelsPanel from './Models/ModelsPanel';
import CreativeNodeEditor from './NodeEditor/CreativeNodeEditor';
import AssetLibrary from './AssetLibrary';
import { IMAGE_DRAFT, draftFromAsset, selectImageModel } from './Generate/imageCreation';
import '../../styles/03-modules/creative-workspace.css';
import { useCreativeApi } from './useCreativeApi';
import { useCreativeModels } from './useCreativeModels';

// Lazy load 3D viewport
const Viewport3D = lazy(() => import('./Viewport3D/Viewport3D'));

const VIEWS = [
  { id: 'generate', label: '2D Generator', icon: Wand2, badge: 'SDXL' },
  { id: 'edit', label: 'Ritocco', icon: Edit3, badge: 'INPAINT' },
  { id: '3d', label: 'Studio 3D', icon: Box, badge: 'THREE.JS' },
  { id: 'mesh', label: 'Mesh Lab', icon: Hexagon, badge: 'BLENDER' },
  { id: 'materials', label: 'Materiali PBR', icon: Layers, badge: 'TEXTURE' },
  { id: 'pipeline', label: 'Pipeline Nodi', icon: Workflow, badge: 'COMFY' },
  { id: 'models', label: 'Modelli AI', icon: Cpu, badge: 'DIFFUSION' },
];

export default function CreativeStudio() {
  const { theme } = useApp();

  const [activeView, setActiveView] = useState('generate');
  const [assets, setAssets] = useState([]);
  const [selectedAsset, setSelectedAsset] = useState(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [imageDraft, setImageDraft] = useState(IMAGE_DRAFT);
  const [pipelineDraft, setPipelineDraft] = useState({ nodes: [], connections: [] });
  const [studioError, setStudioError] = useState('');

  const [backends, setBackends] = useState([]);
  const [capabilities, setCapabilities] = useState({});
  const [stats, setStats] = useState({ total: 0 });

  const { runTask, busy, error, clearError } = useCreativeApi();
  const { models, inventory, loading: modelsLoading, error: modelsError, meta, refresh: refreshModels } = useCreativeModels();
  const uploadInputRef = React.useRef(null);

  const fetchAssets = useCallback(() => (
    fetch('/api/creative/assets?limit=200')
      .then(async r => { const data = await r.json(); if (!r.ok || !data.success) throw new Error(data.error || 'Impossibile leggere la libreria Creative.'); return data; })
      .then(data => { if (Array.isArray(data.assets)) setAssets(data.assets); })
      .catch(e => setStudioError(e.message))
  ), []);

  const fetchCreativeData = useCallback(() => {
    setStudioError('');
    fetchAssets();
    fetch('/api/creative/backends/status').then(r => r.json()).then(data => {
      if (data.success) {
        setBackends(data.backends || []);
        setCapabilities(data.capabilities || {});
      }
    }).catch(() => setStudioError('Impossibile verificare i motori Creative. Premi Aggiorna Creative per riprovare.'));
    fetch('/api/creative/stats').then(r => r.json()).then(data => {
      if (data.success) setStats(data.stats || { total: 0 });
    }).catch(() => {});
  }, [fetchAssets]);

  useEffect(() => { fetchCreativeData(); }, [fetchCreativeData]);

  const registerAssets = useCallback((produced) => {
    const list = (Array.isArray(produced) ? produced : [produced]).filter(Boolean);
    if (!list.length) return;
    setAssets(prev => {
      const ids = new Set(list.map(a => a.id));
      return [...list, ...prev.filter(a => !ids.has(a.id))];
    });
    setSelectedAsset(list[0]);
    fetch('/api/creative/stats').then(r => r.json())
      .then(data => { if (data.success) setStats(data.stats || { total: 0 }); }).catch(() => {});
  }, []);

  // --- Operations ---
  const handleGenerate = useCallback((params, backend) => (
    runTask('/api/creative/generate',
      { task_type: 'text_to_image', params, backend },
      { label: 'Generazione immagine' })
      .then(data => registerAssets(data.asset))
      .catch(() => {})
  ), [runTask, registerAssets]);

  const handleEdit = useCallback((task_type, asset_id, params = {}) => (
    runTask('/api/creative/edit',
      { task_type, asset_id, params },
      { label: `Edit: ${task_type}` })
      .then(data => registerAssets(data.asset))
      .catch(() => {})
  ), [runTask, registerAssets]);

  const handleMesh = useCallback((task_type, asset_id, params = {}) => (
    runTask('/api/creative/mesh',
      { task_type, asset_id, params },
      { label: `Mesh: ${task_type}` })
      .then(data => registerAssets(data.asset))
      .catch(() => {})
  ), [runTask, registerAssets]);

  const handle3D = useCallback((task_type, params = {}) => (
    runTask('/api/creative/3d', { task_type, params }, { label: `3D: ${task_type}` })
      .then(data => registerAssets(data.asset))
      .catch(() => {})
  ), [runTask, registerAssets]);

  const handleMaterial = useCallback((task_type, params = {}) => (
    runTask('/api/creative/material', { task_type, params }, { label: `Materiale: ${task_type}` })
      .then(data => registerAssets(data.asset))
      .catch(() => {})
  ), [runTask, registerAssets]);

  const handleRender = useCallback((asset_id, params = {}) => (
    runTask('/api/creative/render', { asset_id, params }, { label: 'Render Blender' })
      .then(data => registerAssets(data.asset))
      .catch(() => {})
  ), [runTask, registerAssets]);

  const handleUpscale = useCallback((asset_id, scale = 2, restore = false) => (
    runTask('/api/creative/generate',
      { task_type: 'upscale', params: { source_asset_id: asset_id, scale, restore } },
      { label: restore ? `Restauro ${scale}x` : `Upscale ${scale}x` })
      .then(data => registerAssets(data.asset))
      .catch(() => {})
  ), [runTask, registerAssets]);

  const handleSegment = useCallback((asset_id, prompt = '') => (
    runTask('/api/creative/segment', { asset_id, params: { prompt } }, { label: 'Segmentazione' })
      .then(data => registerAssets(data.asset))
      .catch(() => {})
  ), [runTask, registerAssets]);

  const handleUpload = useCallback((file) => {
    if (!file?.type?.startsWith('image/')) { setStudioError('Scegli un file immagine. I video si importano nel modulo Film e manga.'); return; }
    const reader = new FileReader();
    reader.onerror = () => setStudioError('Il file non è leggibile. Prova a importarlo nuovamente.');
    reader.onload = () => {
      runTask('/api/creative/upload', { name: file.name, image: reader.result }, { label: 'Upload Asset' })
        .then(data => registerAssets(data.asset))
        .catch(() => {});
    };
    reader.readAsDataURL(file);
  }, [runTask, registerAssets]);

  const handleDelete = useCallback((asset_id) => {
    fetch('/api/creative/assets/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ asset_id }),
    }).then(async response => {
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.error || 'Eliminazione non riuscita');
      setAssets(prev => prev.filter(a => a.id !== asset_id));
      setSelectedAsset(prev => (prev?.id === asset_id ? null : prev));
      fetchCreativeData();
    }).catch(e => setStudioError(e.message));
  }, [fetchCreativeData]);

  // Render main canvas for active view
  const renderCanvas = () => {
    switch (activeView) {
      case 'generate':
        return (
          <GeneratePanel
            onGenerate={handleGenerate}
            onUpload={() => uploadInputRef.current?.click()}
            isGenerating={!!busy}
            backends={backends}
            models={models}
            inventory={inventory}
            recentAssets={assets.filter(a => a.type === 'image' || a.type === 'render')}
            onSelectAsset={setSelectedAsset}
            selectedAsset={selectedAsset} draft={imageDraft} onDraftChange={setImageDraft}
            loading={modelsLoading} modelError={modelsError} onRefreshModels={refreshModels}
            onManageModels={() => setActiveView('models')}
            onEditAsset={asset => { setSelectedAsset(asset); setActiveView('edit'); }}
            onReuseAsset={asset => setImageDraft(previous => draftFromAsset(asset, previous))}
          />
        );
      case 'edit':
        return (
          <EditCanvas
            asset={selectedAsset}
            busy={!!busy}
            capabilities={capabilities}
            onEdit={handleEdit}
            onChooseAsset={() => setLibraryOpen(true)}
            onUpscale={handleUpscale}
            onSegment={handleSegment}
          />
        );
      case '3d':
        return (
          <Suspense fallback={<div style={{ padding: '40px', textAlign: 'center' }}><p>Caricamento Viewport 3D...</p></div>}>
            <Viewport3D
              asset={selectedAsset}
              busy={!!busy}
              canGenerate3D={(capabilities.image_to_3d || []).length > 0}
              blenderAvailable={(capabilities.render || []).length > 0}
              onGenerate3D={handle3D}
              onChooseAsset={() => setLibraryOpen(true)}
              onRender={handleRender}
            />
          </Suspense>
        );
      case 'mesh':
        return (
          <MeshLab
            asset={selectedAsset}
            busy={!!busy}
            blenderAvailable={(capabilities.render || []).length > 0}
            onMeshOp={handleMesh}
            onChooseAsset={() => setLibraryOpen(true)}
          />
        );
      case 'materials':
        return (
          <MaterialsPanel
            asset={selectedAsset}
            assets={assets}
            busy={!!busy}
            blenderAvailable={(capabilities.render || []).length > 0}
            onMaterial={handleMaterial}
          />
        );
      case 'pipeline':
        return <CreativeNodeEditor assets={assets} onAssetsProduced={registerAssets} draft={pipelineDraft} onDraftChange={setPipelineDraft} />;
      case 'models':
        return <ModelsPanel models={models} inventory={inventory} meta={meta} loading={modelsLoading} error={modelsError} onRefresh={refreshAll} onOpenPipeline={() => setActiveView('pipeline')} onOpenSkill={id => setActiveView(id === 'creative-images' ? 'generate' : id === 'creative-3d-materials' ? '3d' : 'pipeline')} onUseModel={model => { setImageDraft(previous => selectImageModel(previous, { model_id: model.id }, model)); setActiveView('generate'); }} />;
      default:
        return null;
    }
  };

  const refreshAll = useCallback(() => { fetchCreativeData(); return refreshModels(); }, [fetchCreativeData, refreshModels]);
  const openAsset = asset => {
    setSelectedAsset(asset);
    if (['image', 'render'].includes(asset.type)) setActiveView('edit');
    else if (['mesh', 'model_3d'].includes(asset.type)) setActiveView('3d');
    else if (asset.type === 'material') setActiveView('materials');
    else setStudioError('I video si aprono dal modulo autonomo Film e manga.');
  };
  return <div className="creative-studio cs-workspace" data-theme={theme} data-agent-component="CreativeStudio" data-agent-id="creative-studio">
    <TabHeader icon={Palette} title="Creative" description={`${stats.total ?? assets.length} creazioni nella tua libreria`}
      tabs={[
        { id: 'generate', label: 'Immagini', icon: Wand2, views: ['generate', 'edit'] },
        { id: '3d', label: '3D e materiali', icon: Box, views: ['3d', 'mesh', 'materials'] },
        { id: 'models', label: 'Modelli e skill', icon: Cpu, views: ['models', 'pipeline'] },
      ].map(v => ({ id: v.id, label: v.label, icon: v.icon, active: v.views.includes(activeView), onClick: () => setActiveView(v.id) }))}
      actions={<div className="cs-workspace-actions">
        <button className="cs-secondary-button" aria-expanded={libraryOpen} onClick={() => setLibraryOpen(v => !v)}><Library size={15} /> Libreria</button>
        <button className="cs-icon-button" aria-label="Aggiorna Creative" onClick={refreshAll}><RefreshCw size={16} /></button>
      </div>} />
    <nav className="cs-context-tools" aria-label="Operazioni creative">{VIEWS.filter(v => ['generate', 'edit'].includes(activeView) ? ['generate', 'edit'].includes(v.id) : ['3d', 'mesh', 'materials'].includes(activeView) ? ['3d', 'mesh', 'materials'].includes(v.id) : ['models', 'pipeline'].includes(v.id)).map(v => <button key={v.id} className="cs-choice" aria-pressed={activeView === v.id} onClick={() => setActiveView(v.id)}><v.icon size={15} />{v.label}</button>)}</nav>
    {(error || studioError) && <div className="cs-studio-error" role="alert"><span>{error || studioError}</span><button className="cs-icon-button" aria-label="Chiudi messaggio" onClick={() => { clearError(); setStudioError(''); }}><X size={16} /></button></div>}
    {busy && <div className="cs-task-status" role="status" aria-live="polite"><span className="cs-status-dot" /><strong>{busy.label}</strong><span>{busy.message || 'Attendo il risultato dal modello…'}</span></div>}
    <input ref={uploadInputRef} type="file" accept="image/*" hidden onChange={e => { const file = e.target.files?.[0]; if (file) handleUpload(file); e.target.value = ''; }} />
    <div className="cs-workbench">
      {libraryOpen && <AssetLibrary assets={assets} selectedAsset={selectedAsset} busy={!!busy} onSelect={setSelectedAsset} onOpen={openAsset} onUpload={() => uploadInputRef.current?.click()} onDelete={handleDelete} onClose={() => setLibraryOpen(false)} />}
      <main className="cs-workspace-main" aria-label={VIEWS.find(v => v.id === activeView)?.label || 'Creative'}>{renderCanvas()}</main>
    </div>
  </div>;
}
