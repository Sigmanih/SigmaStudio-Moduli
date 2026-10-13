import React, { useCallback, useEffect, useState } from 'react';
import { Clapperboard, Link2, Cpu, Film, Scissors, UsersRound } from 'lucide-react';
import { useApp } from '../../contexts/AppContext';
import TechSpaceCanvas from '../common/TechSpaceCanvas';
import TabHeader from '../../components/common/TabHeader';
import ProductionPanel from './Video/ProductionPanel';
import CivitaiPanel from './Video/CivitaiPanel';
import EnginesPanel from './Video/EnginesPanel';
import EditorView from './Video/Editor/EditorView';
import CharacterLibrary from './Video/CharacterLibrary';
import './styles/creative-studio.css';

/*
 * Video Studio: tab dedicata ai video lunghi. Stesso modulo del Creative Lab
 * (sigma_creative_lab), punto d'ingresso separato: produzioni, modelli da
 * Civitai e motori di generazione.
 */

const VIEWS = [
  { id: 'productions', label: 'Produzioni', icon: Clapperboard },
  { id: 'editor', label: 'Editor', icon: Scissors },
  { id: 'characters', label: 'Personaggi', icon: UsersRound },
  { id: 'models', label: 'Modelli & Civitai', icon: Link2 },
  { id: 'engines', label: 'Motori', icon: Cpu },
];

export default function VideoStudio() {
  const { theme } = useApp();
  const [view, setView] = useState('productions');
  const [engines, setEngines] = useState(null);
  const [editing, setEditing] = useState(null);       // produzione aperta nell'editor

  const refreshEngines = useCallback(async () => {
    try {
      const d = await (await fetch('/api/creative/video/engines')).json();
      if (d.success) setEngines(d);
    } catch { /* lo stato dei motori e' accessorio: le altre viste funzionano lo stesso */ }
  }, []);

  useEffect(() => { refreshEngines(); }, [refreshEngines]);
  useEffect(() => {
    if (view !== 'engines') return undefined;
    const t = setInterval(refreshEngines, 4000);
    return () => clearInterval(t);
  }, [view, refreshEngines]);

  const aceInstalled = !!(engines?.components || []).find(c => c.id === 'ace_step' && c.installed);

  return (
    <div className="creative-studio cs-fade-in cs-video-studio">
      <TechSpaceCanvas isLight={theme === 'light'} />
      <TabHeader
        icon={Film}
        title="Video Studio"
        highlight="LONG FORM"
        tabs={VIEWS.map(v => ({
          id: v.id, label: v.label, icon: v.icon, active: view === v.id, onClick: () => setView(v.id),
        }))}
        description="Video lunghi con LTX-2.5 o MiniMax H3: personaggi riutilizzabili, storyboard, render su tutte le GPU, colonna sonora e montaggio"
      />
      <div className="cs-video-body">
        {view === 'productions' && (
          <ProductionPanel aceInstalled={aceInstalled} onOpenEditor={id => { setEditing(id); setView('editor'); }} />
        )}
        {view === 'editor' && <EditorView productionId={editing} onPickProduction={setEditing} />}
        {view === 'characters' && <CharacterLibrary />}
        {view === 'models' && <CivitaiPanel />}
        {view === 'engines' && <EnginesPanel engines={engines} onRefresh={refreshEngines} />}
      </div>
    </div>
  );
}
