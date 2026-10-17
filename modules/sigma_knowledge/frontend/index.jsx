// sigma_knowledge — Module Entrypoint
import React, { useState } from 'react';
import MappaArgomenti from './MappaArgomenti';
import KnowledgeNodeExplorer from './KnowledgeNodeExplorer';
import { PieChart, Layers } from 'lucide-react';

import TabHeader from '../../components/common/TabHeader';

export default function KnowledgeModuleTab({ onOpenFile, openTab }) {
  const [subView, setSubView] = useState('mappa'); // 'mappa' | 'nodes'

  const knowledgeTabs = [
    {
      id: 'mappa',
      label: 'Mappa Relazionale D3',
      icon: PieChart,
      active: subView === 'mappa',
      onClick: () => setSubView('mappa'),
    },
    {
      id: 'nodes',
      label: 'Universal Knowledge Nodes',
      icon: Layers,
      active: subView === 'nodes',
      onClick: () => setSubView('nodes'),
    },
  ];

  return (
    <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <TabHeader
        icon={PieChart}
        title="Argomenti & Conoscenza"
        highlight="KNOWLEDGE GRAPH"
        tabs={knowledgeTabs}
        description="Mappa concettuale interattiva D3, ontologia della conoscenza e nodi universali"
      />

      {/* Banner informativo transizione verso Developer Studio */}
      <div style={{
        padding: '6px 16px',
        background: 'linear-gradient(90deg, rgba(0, 242, 254, 0.12) 0%, rgba(168, 85, 247, 0.12) 100%)',
        borderBottom: '1px solid rgba(0, 242, 254, 0.25)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        fontSize: '0.72rem',
        color: '#e6edf3'
      }}>
        <span>
          ✨ <strong>Nuova integrazione completa:</strong> Il Grafo Relazionale, le note KaTeX e la Creazione AI sono ora integrati direttamente in <strong>Developer Studio</strong> con supporto per l'intero Workspace e Git in tempo reale.
        </span>
        {openTab && (
          <button
            onClick={() => openTab('developer_studio')}
            style={{
              padding: '3px 10px',
              borderRadius: '5px',
              border: 'none',
              background: '#00f2fe',
              color: '#07090e',
              fontSize: '0.7rem',
              fontWeight: 800,
              cursor: 'pointer',
              marginLeft: '12px'
            }}
          >
            Passa a Developer Studio →
          </button>
        )}
      </div>

      {/* Main Viewport */}
      <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
        {subView === 'mappa' ? (
          <MappaArgomenti onOpenFile={onOpenFile} />
        ) : (
          <KnowledgeNodeExplorer />
        )}
      </div>
    </div>
  );
}
