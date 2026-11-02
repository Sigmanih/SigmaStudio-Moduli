import React, { useState } from 'react';
import { Box, Play, Download, AlertTriangle, Loader, Boxes } from 'lucide-react';
import { useThreeViewer } from './useThreeViewer';
import SceneControls from './SceneControls';
import CreativeEmptyState from '../shared/CreativeEmptyState';

export default function Viewport3D({ asset, busy, canGenerate3D, blenderAvailable, onGenerate3D, onRender, onChooseAsset }) {
  const modelUrl = asset?.model_url || asset?.file_urls?.model || null;
  if (!asset) return <CreativeEmptyState icon={Box} title="Il tuo spazio 3D" description="Scegli un modello dalla libreria oppure un’immagine da trasformare in 3D." onChoose={onChooseAsset} />;
  if (!modelUrl) return <section className="cs-creative-empty" data-agent-component="ModelSource" data-agent-id="creative-3d-source">
    <Boxes size={42} /><h2>{asset.name || 'Elemento selezionato'}</h2><p>Questo elemento non contiene un modello 3D.</p>
    {['image', 'render'].includes(asset.type) && <><button className="cs-secondary-button" disabled={busy || !canGenerate3D} onClick={() => onGenerate3D('image_to_3d', { asset_id: asset.id })}>Crea un modello da questa immagine</button>{!canGenerate3D && <p className="cs-hint">Nessun motore 3D disponibile. Controlla Modelli e skill.</p>}</>}
    <button className="cs-text-button" onClick={onChooseAsset}>Scegli un altro elemento</button>
  </section>;
  return <LoadedViewport key={asset.id} asset={asset} modelUrl={modelUrl} busy={busy} blenderAvailable={blenderAvailable} onRender={onRender} />;
}

function LoadedViewport({ asset, modelUrl, busy, blenderAvailable, onRender }) {
  const [wireframe, setWireframe] = useState(false);
  const [environment, setEnvironment] = useState('Studio');

  const { containerRef, status, error, stats, environments } = useThreeViewer({
    url: modelUrl, wireframe, environment,
  });

  return (
    <div className="cs-3d-container">
      <div ref={containerRef} className="cs-3d-canvas" />

      {status === 'loading' && (
        <div className="cs-3d-loading"><Loader size={18} className="cs-spin" /> Caricamento modello...</div>
      )}
      {status === 'error' && (
        <div className="cs-3d-loading error"><AlertTriangle size={18} /> {error}</div>
      )}

      <div className="cs-3d-overlay">
        <div className="cs-3d-stats">
          <h4 style={{ margin: '0 0 8px', color: 'var(--primary)' }}>{asset.name}</h4>
          {stats ? (
            <div className="cs-stat-grid">
              <span>Vertici:</span><span>{stats.vertices.toLocaleString()}</span>
              <span>Triangoli:</span><span>{stats.triangles.toLocaleString()}</span>
              <span>Mesh:</span><span>{stats.meshes}</span>
              <span>Materiali:</span><span>{stats.materials}</span>
              <span>UV:</span><span>{stats.hasUV ? 'sì' : 'no'}</span>
            </div>
          ) : (
            <p className="cs-hint">Statistiche in lettura dal modello...</p>
          )}
        </div>

        <SceneControls
          environment={environment}
          environments={environments}
          onEnvironmentChange={setEnvironment}
          wireframe={wireframe}
          onWireframeToggle={() => setWireframe(w => !w)}
          extra={(
            <>
              <a className="cs-pill" href={modelUrl} download title="Scarica il modello">
                <Download size={14} /> GLB
              </a>
              <button
                className="cs-pill cs-pill-warn"
                disabled={busy || !blenderAvailable}
                title={blenderAvailable ? 'Render fotorealistico con Blender' : 'Blender non configurato'}
                onClick={() => onRender(asset.id, { engine: 'cycles', width: 1280, height: 720, samples: 96 })}
              >
                <Play size={14} /> Blender Render
              </button>
            </>
          )}
        />
      </div>
    </div>
  );
}
