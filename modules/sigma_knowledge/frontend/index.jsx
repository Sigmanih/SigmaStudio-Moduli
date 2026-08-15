// sigma_knowledge — Module Entrypoint
import React, { useState } from 'react';
import MappaArgomenti from './MappaArgomenti';
import KnowledgeNodeExplorer from './KnowledgeNodeExplorer';
import { PieChart, Layers } from 'lucide-react';

export default function KnowledgeModuleTab({ onOpenFile, openTab }) {
  const [subView, setSubView] = useState('mappa'); // 'mappa' | 'nodes'

  return (
    <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Sub-header navigation bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 16px',
        borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
        background: 'rgba(15, 17, 26, 0.6)',
        backdropFilter: 'blur(8px)',
        flexShrink: 0
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button
            onClick={() => setSubView('mappa')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 12px',
              borderRadius: '8px',
              border: subView === 'mappa' ? '1px solid rgba(0, 210, 255, 0.4)' : '1px solid rgba(255, 255, 255, 0.05)',
              background: subView === 'mappa' ? 'rgba(0, 210, 255, 0.12)' : 'transparent',
              color: subView === 'mappa' ? '#00d2ff' : '#8b8fa3',
              fontSize: '0.78rem',
              fontWeight: 600,
              cursor: 'pointer'
            }}
          >
            <PieChart size={14} />
            Mappa Relazionale D3
          </button>

          <button
            onClick={() => setSubView('nodes')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 12px',
              borderRadius: '8px',
              border: subView === 'nodes' ? '1px solid rgba(188, 140, 255, 0.4)' : '1px solid rgba(255, 255, 255, 0.05)',
              background: subView === 'nodes' ? 'rgba(188, 140, 255, 0.12)' : 'transparent',
              color: subView === 'nodes' ? '#bc8cff' : '#8b8fa3',
              fontSize: '0.78rem',
              fontWeight: 600,
              cursor: 'pointer'
            }}
          >
            <Layers size={14} />
            Universal Knowledge Nodes
          </button>
        </div>
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
