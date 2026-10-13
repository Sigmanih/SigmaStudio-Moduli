import React, { useState } from 'react';
import { useApp } from '../../contexts/AppContext';
import TechSpaceCanvas from '../common/TechSpaceCanvas';
import ResearchLab from './ResearchLab';
import PipelineDesigner from './PipelineDesigner';
import RolesEditor from './RolesEditor';
import { FlaskConical, GitCompare, Users } from 'lucide-react';
import TabHeader from '../../components/common/TabHeader';

// ==============================================================================
// PIPELINES LAB TAB — Tre modalità:
// 1. "Pipeline Predefinita" (ResearchLab) — Template pronti con feedback loop
// 2. "Pipeline Designer" — Editor visuale DAG per configurazioni custom
// 3. "Ruoli AI" (RolesEditor) — Configurazione prompt, tool e budget in config/roles.json
// ==============================================================================

const MODES = [
  { 
    id: 'default', 
    label: '🚀 Pipeline Predefinita', 
    icon: FlaskConical, 
    desc: 'Template pronti con 4-7 agenti, feedback loop automatico e memoria distribuita' 
  },
  { 
    id: 'designer', 
    label: '🧩 Pipeline Designer', 
    icon: GitCompare, 
    desc: 'Editor visuale DAG per creare pipeline custom con routing condizionale' 
  },
  { 
    id: 'roles', 
    label: '👥 Ruoli AI', 
    icon: Users, 
    desc: 'Configurazione ruoli di squadra, prompt, tool abilitati e turn budget (roles.json)' 
  },
];

export default function ResearchLabTab({ onTasksUpdated, addToast }) {
  const { theme } = useApp();
  const [mode, setMode] = useState('default');

  const handleClose = () => {};

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', padding: 0, boxSizing: 'border-box', background: 'var(--bg)', color: '#e2e4eb', overflowY: 'auto', position: 'relative' }}>
      
      {/* Animated Translucent Cyber Space Background Canvas */}
      <TechSpaceCanvas isLight={theme === 'light'} />

      {/* Intestazione Universale Kernel Sigma Studio */}
      <TabHeader
        icon={FlaskConical}
        title="Pipelines Lab"
        highlight="SWARM ORCHESTRATION"
        tabs={MODES.map(m => ({
          id: m.id,
          label: m.label.replace(/^[\p{Emoji}\s]+/u, ''),
          icon: m.icon,
          active: mode === m.id,
          onClick: () => setMode(m.id)
        }))}
        description="Orchestrazione avanzata di swarm multidisciplinari, routing condizionale, ruoli e grafi DAG"
      />

      {/* Main Content Workspace Body */}
      <div style={{ padding: '24px', flex: 1, display: 'flex', flexDirection: 'column', gap: '20px', minHeight: 0 }}>

      {/* 3. MAIN CONTENT */}
      <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
        {mode === 'default' && (
          <ResearchLab onClose={handleClose} onTasksUpdated={onTasksUpdated} addToast={addToast} />
        )}
        {mode === 'designer' && (
          <PipelineDesigner onClose={handleClose} onTasksUpdated={onTasksUpdated} addToast={addToast} />
        )}
        {mode === 'roles' && (
          <RolesEditor addToast={addToast} />
        )}
      </div>
      </div>
    </div>
  );
}
