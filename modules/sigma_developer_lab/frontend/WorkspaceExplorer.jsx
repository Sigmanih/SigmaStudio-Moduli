import React, { useState } from 'react';
import { 
  Folder, FolderOpen, File, FileCode, FileText, ChevronRight, ChevronDown, 
  Plus, Trash2, Edit2, RefreshCw, Search, HardDrive, CornerDownRight,
  Box, ExternalLink, PieChart, Sparkles 
} from 'lucide-react';
import DockerViewerModal from './DockerViewerModal';
import WorkspaceContextMenu from './WorkspaceContextMenu';

export const getFileIcon = (filename = '') => {
  const ext = filename.split('.').pop().toLowerCase();
  switch (ext) {
    case 'js':
    case 'jsx':
    case 'ts':
    case 'tsx':
      return <FileCode size={14} color="#f7df1e" />;
    case 'py':
      return <FileCode size={14} color="#3572A5" />;
    case 'json':
      return <FileCode size={14} color="#56b6c2" />;
    case 'html':
      return <FileCode size={14} color="#e34c26" />;
    case 'css':
      return <FileCode size={14} color="#563d7c" />;
    case 'md':
      return <FileText size={14} color="#00f2fe" />;
    default:
      return <File size={14} color="#8b949e" />;
  }
};

const TreeNode = ({ 
  node, 
  activeFilePath, 
  onFileSelect, 
  onDeleteEntry, 
  onCreateEntry, 
  onOpenGraph,
  onAiCreate,
  onContextMenu,
  theme, 
  isLight,
  depth = 0
}) => {
  const isRoot = depth === 0;
  const [expanded, setExpanded] = useState(
    isRoot ||
    node.name === 'Sigma_Studio' || 
    node.name === 'data' || 
    node.name === 'roles' || 
    node.name === 'projects' || 
    node.name === 'agent_memory' || 
    node.name === 'sigma_studio'
  );

  if (!node) return null;

  const isDir = node.is_dir;
  const isSelected = activeFilePath === node.path;

  const handleRowClick = (e) => {
    e.stopPropagation();
    if (isDir) {
      setExpanded(!expanded);
    } else {
      onFileSelect(node.path);
    }
  };

  return (
    <div style={{ userSelect: 'none', fontSize: '0.74rem' }}>
      <div 
        onClick={handleRowClick}
        onContextMenu={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onContextMenu?.(e, node);
        }}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '3px 6px',
          borderRadius: '5px',
          cursor: 'pointer',
          background: isSelected ? (isLight ? 'rgba(0, 242, 254, 0.15)' : 'rgba(0, 242, 254, 0.12)') : 'transparent',
          color: isSelected ? '#00f2fe' : (isLight ? '#24292f' : '#c9d1d9'),
          fontWeight: isSelected ? 700 : 500,
          transition: 'all 0.1s ease'
        }}
        onMouseEnter={e => {
          if (!isSelected) e.currentTarget.style.background = isLight ? 'rgba(0,0,0,0.04)' : 'rgba(255,255,255,0.04)';
        }}
        onMouseLeave={e => {
          if (!isSelected) e.currentTarget.style.background = 'transparent';
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {isDir ? (
            <>
              {expanded ? <ChevronDown size={13} color="#8b949e" /> : <ChevronRight size={13} color="#8b949e" />}
              {expanded ? <FolderOpen size={14} color="#e5c07b" /> : <Folder size={14} color="#e5c07b" />}
            </>
          ) : (
            <>
              <span style={{ width: '13px', display: 'inline-block' }} />
              {getFileIcon(node.name)}
            </>
          )}
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {node.name}
          </span>
        </div>

        {/* Hover quick action buttons for graph / ai / create / delete */}
        <div className="node-actions" style={{ display: 'flex', alignItems: 'center', gap: '3px', opacity: 0.6 }} onClick={e => e.stopPropagation()}>
          {isDir && (
            <button
              onClick={() => onOpenGraph?.(node)}
              title="Visualizza Grafo Relazionale D3"
              style={{ background: 'none', border: 'none', color: '#00f2fe', cursor: 'pointer', padding: '2px' }}
            >
              <PieChart size={11} />
            </button>
          )}
          {isDir && (
            <button
              onClick={() => onAiCreate?.(node)}
              title="Crea file o documento con AI"
              style={{ background: 'none', border: 'none', color: '#eab308', cursor: 'pointer', padding: '2px' }}
            >
              <Sparkles size={11} />
            </button>
          )}
          {isDir && (
            <button
              onClick={() => onCreateEntry(node.path)}
              title="Nuovo file in questa cartella"
              style={{ background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', padding: '2px' }}
            >
              <Plus size={11} />
            </button>
          )}
          <button
            onClick={() => onDeleteEntry(node.path, node.is_dir)}
            title={`Elimina ${node.is_dir ? 'cartella' : 'file'}`}
            style={{ background: 'none', border: 'none', color: '#ef4444', cursor: 'pointer', padding: '2px' }}
          >
            <Trash2 size={11} />
          </button>
        </div>
      </div>

      {isDir && expanded && node.children && (
        <div style={{ paddingLeft: '12px', borderLeft: isLight ? '1px solid rgba(0,0,0,0.06)' : '1px solid rgba(255,255,255,0.06)', marginLeft: '6px' }}>
          {node.children.length === 0 ? (
            <div style={{ padding: '2px 6px', fontSize: '0.66rem', color: '#8b949e', fontStyle: 'italic' }}>(cartella vuota)</div>
          ) : (
            node.children.map(child => (
              <TreeNode 
                key={child.path} 
                node={child} 
                activeFilePath={activeFilePath} 
                onFileSelect={onFileSelect}
                onDeleteEntry={onDeleteEntry}
                onCreateEntry={onCreateEntry}
                onOpenGraph={onOpenGraph}
                onAiCreate={onAiCreate}
                onContextMenu={onContextMenu}
                theme={theme}
                isLight={isLight}
                depth={depth + 1}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
};

export default function WorkspaceExplorer({
  treeData,
  activeFilePath,
  workspaceRoot,
  workspaceRoots = [],
  onSelectWorkspaceRoot,
  onFileSelect,
  onRefreshTree,
  onCreateFile,
  onCreateFolder,
  onDeletePath,
  onOpenGraph,
  onAiCreate,
  onOpenStudy,
  onShowDiff,
  theme,
  isLight
}) {
  const [searchFilter, setSearchFilter] = useState('');
  const [showDockerModal, setShowDockerModal] = useState(false);
  const [contextMenu, setContextMenu] = useState({ visible: false, x: 0, y: 0, node: null });
  const textMuted = isLight ? '#57606a' : '#8b949e';

  const normPath = (p) => String(p || '').replace(/\\/g, '/').replace(/\/+$/, '');
  const studioRootObj = workspaceRoots.find(r => r.kind === 'studio');
  const projectsRootObj = workspaceRoots.find(r => r.kind === 'projects_root');

  let studioRoot = studioRootObj ? normPath(studioRootObj.path) : '';
  let projectsRoot = projectsRootObj ? normPath(projectsRootObj.path) : '';

  if (!studioRoot && projectsRoot) {
    studioRoot = projectsRoot.replace(/\/projects$/, '');
  }
  if (!projectsRoot && studioRoot) {
    projectsRoot = `${studioRoot}/projects`;
  }
  if (!studioRoot) {
    const cur = normPath(workspaceRoot);
    const idx = cur.toLowerCase().indexOf('/sigma_studio');
    studioRoot = idx !== -1 ? cur.slice(0, idx + '/sigma_studio'.length) : cur;
  }
  if (!projectsRoot) {
    projectsRoot = `${studioRoot}/projects`;
  }

  const handleContextMenu = (e, node) => {
    e.preventDefault();
    setContextMenu({
      visible: true,
      x: e.clientX,
      y: e.clientY,
      node: node || displayTree
    });
  };

  const filterTree = (node, query) => {
    if (!query) return node;
    if (!node) return null;
    if (!node.is_dir) {
      return node.name.toLowerCase().includes(query.toLowerCase()) ? node : null;
    }
    const filteredChildren = (node.children || [])
      .map(child => filterTree(child, query))
      .filter(Boolean);

    if (filteredChildren.length > 0 || node.name.toLowerCase().includes(query.toLowerCase())) {
      return { ...node, children: filteredChildren };
    }
    return null;
  };

  const displayTree = filterTree(treeData, searchFilter);

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      width: '100%',
      background: isLight ? '#f6f8fa' : '#0d1117',
      userSelect: 'none',
      overflow: 'hidden'
    }}>
      {/* Header with Workspace Selector */}
      <div style={{
        padding: '10px 12px',
        borderBottom: isLight ? '1px solid #d0d7de' : '1px solid rgba(255,255,255,0.08)',
        display: 'flex',
        flexDirection: 'column',
        gap: '6px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.74rem', fontWeight: 800, color: isLight ? '#24292f' : '#f0f6fc' }}>
            <HardDrive size={14} color="#00f2fe" />
            <span>WORKSPACE (ADMIN)</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
            <button
              onClick={() => onCreateFile(workspaceRoot)}
              title="Nuovo File"
              style={{ background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', padding: '3px' }}
            >
              <Plus size={13} />
            </button>
            <button
              onClick={onRefreshTree}
              title="Ricarica Albero"
              style={{ background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', padding: '3px' }}
            >
              <RefreshCw size={12} />
            </button>
          </div>
        </div>

        {/* Workspace Root Select */}
        <select
          value={workspaceRoot}
          onChange={e => onSelectWorkspaceRoot(e.target.value)}
          style={{
            width: '100%',
            padding: '4px 6px',
            borderRadius: '6px',
            fontSize: '0.68rem',
            background: isLight ? '#ffffff' : '#161b22',
            border: isLight ? '1px solid #d0d7de' : '1px solid rgba(255,255,255,0.12)',
            color: isLight ? '#24292f' : '#c9d1d9',
            outline: 'none',
            cursor: 'pointer'
          }}
        >
          {workspaceRoots.map(r => (
            <option key={r.path} value={r.path}>
              {r.label}
            </option>
          ))}
          {!workspaceRoots.some(r => normPath(r.path).toLowerCase() === normPath(workspaceRoot).toLowerCase()) && workspaceRoot && (
            <option key={workspaceRoot} value={workspaceRoot}>
              📍 {workspaceRoot.replace(/\\/g, '/').split('/').filter(Boolean).pop() || workspaceRoot}
            </option>
          )}
        </select>

        {/* Rimodernizzata Development Map & Quick Pinned Bookmarks */}
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '6px',
          padding: '6px 8px',
          borderRadius: '8px',
          background: isLight ? 'rgba(0,0,0,0.03)' : 'rgba(255,255,255,0.03)',
          border: isLight ? '1px solid rgba(0,0,0,0.06)' : '1px solid rgba(255,255,255,0.06)'
        }}>
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: '0.62rem',
            fontWeight: 700,
            color: textMuted
          }}>
            <span style={{ textTransform: 'uppercase', letterSpacing: '0.5px' }}>Navigazione Rapida</span>
            <span style={{ color: '#00d2ff', fontSize: '0.58rem' }}>Dev Map</span>
          </div>

          <div style={{
            display: 'flex',
            gap: '4px',
            overflowX: 'auto',
            paddingBottom: '2px',
            scrollbarWidth: 'none',
            msOverflowStyle: 'none'
          }}>
            {[
              { id: 'studio', label: '🏠 SigmaStudio', path: studioRoot },
              { id: 'projects', label: '📁 Progetti', path: projectsRoot },
              { id: 'userdata', label: '📌 User Data', path: `${studioRoot}/data` },
              { id: 'roles', label: '🎭 Ruoli', path: `${studioRoot}/roles` },
              { id: 'memory', label: '🧠 Memoria', path: `${studioRoot}/var/agent_memory` },
              { id: 'docker', label: '🐳 Docker', isDocker: true },
            ].map(pin => {
              const isPinnedActive = pin.isDocker
                ? Boolean(workspaceRoot?.startsWith('docker://'))
                : (Boolean(pin.path) && normPath(workspaceRoot).toLowerCase() === normPath(pin.path).toLowerCase());

              return (
                <button
                  key={pin.label}
                  type="button"
                  title={pin.isDocker ? 'Apri e naviga container Docker' : `Passa alla cartella: ${pin.path}`}
                  onClick={() => {
                    if (pin.isDocker) {
                      setShowDockerModal(true);
                    } else if (pin.path) {
                      onSelectWorkspaceRoot(pin.path);
                    }
                  }}
                  style={{
                    padding: '3px 7px',
                    borderRadius: '5px',
                    fontSize: '0.62rem',
                    fontWeight: 700,
                    background: isPinnedActive 
                      ? (isLight ? 'rgba(0, 210, 255, 0.15)' : 'rgba(0, 210, 255, 0.18)')
                      : (isLight ? '#ffffff' : 'rgba(255, 255, 255, 0.05)'),
                    border: isPinnedActive 
                      ? '1px solid rgba(0, 210, 255, 0.5)'
                      : (isLight ? '1px solid #d0d7de' : '1px solid rgba(255, 255, 255, 0.08)'),
                    color: isPinnedActive ? '#00d2ff' : (isLight ? '#24292f' : '#c9d1d9'),
                    cursor: 'pointer',
                    whiteSpace: 'nowrap',
                    transition: 'all 0.15s ease',
                    boxShadow: isPinnedActive ? '0 1px 4px rgba(0,210,255,0.2)' : 'none'
                  }}
                >
                  {pin.label}
                </button>
              );
            })}
          </div>

          {/* Tasto Dedicato: Visualizza Docker */}
          <button
            type="button"
            onClick={() => setShowDockerModal(true)}
            title="Apri il monitor Docker: visualizza container attivi, immagini scaricate e porte dev-server"
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '6px',
              padding: '4px 8px',
              borderRadius: '6px',
              fontSize: '0.65rem',
              fontWeight: 800,
              background: 'linear-gradient(135deg, rgba(2, 132, 199, 0.2), rgba(14, 165, 233, 0.12))',
              border: '1px solid rgba(56, 189, 248, 0.4)',
              color: '#38bdf8',
              cursor: 'pointer',
              transition: 'all 0.15s ease',
              marginTop: '2px'
            }}
            onMouseEnter={e => {
              e.currentTarget.style.background = 'linear-gradient(135deg, rgba(2, 132, 199, 0.35), rgba(14, 165, 233, 0.22))';
              e.currentTarget.style.borderColor = '#38bdf8';
            }}
            onMouseLeave={e => {
              e.currentTarget.style.background = 'linear-gradient(135deg, rgba(2, 132, 199, 0.2), rgba(14, 165, 233, 0.12))';
              e.currentTarget.style.borderColor = 'rgba(56, 189, 248, 0.4)';
            }}
          >
            <span>🐳</span>
            <span>Visualizza Docker & Sandbox</span>
            <ExternalLink size={10} style={{ opacity: 0.7 }} />
          </button>
        </div>

        {/* Quick Filter Input */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          padding: '3px 8px',
          borderRadius: '6px',
          background: isLight ? '#ffffff' : '#161b22',
          border: isLight ? '1px solid #d0d7de' : '1px solid rgba(255,255,255,0.12)'
        }}>
          <Search size={11} color="#8b949e" />
          <input
            type="text"
            placeholder="Cerca file o cartella..."
            value={searchFilter}
            onChange={e => setSearchFilter(e.target.value)}
            style={{
              width: '100%',
              background: 'transparent',
              border: 'none',
              color: isLight ? '#24292f' : '#c9d1d9',
              fontSize: '0.68rem',
              outline: 'none'
            }}
          />
        </div>
      </div>

      {/* Tree Content */}
      <div 
        onContextMenu={(e) => handleContextMenu(e, displayTree)}
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '8px 6px'
        }}
      >
        {displayTree ? (
          <TreeNode
            node={displayTree}
            activeFilePath={activeFilePath}
            onFileSelect={onFileSelect}
            onDeleteEntry={onDeletePath}
            onCreateEntry={onCreateFile}
            onOpenGraph={onOpenGraph}
            onAiCreate={onAiCreate}
            onContextMenu={handleContextMenu}
            theme={theme}
            isLight={isLight}
          />
        ) : (
          <div style={{ fontSize: '0.72rem', color: '#8b949e', textAlign: 'center', marginTop: '20px' }}>
            Nessun file trovato.
          </div>
        )}
      </div>

      {/* Menu Contestuale Tasto Destro */}
      {contextMenu.visible && (
        <WorkspaceContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          node={contextMenu.node}
          onClose={() => setContextMenu({ visible: false, x: 0, y: 0, node: null })}
          onOpenGraph={onOpenGraph}
          onAiCreate={onAiCreate}
          onOpenFile={onFileSelect}
          onOpenStudy={onOpenStudy}
          onNewFile={(n) => onCreateFile?.(n?.is_dir ? n.path : (n?.path?.replace(/\/[^/]+$/, '') || workspaceRoot))}
          onNewFolder={(n) => onCreateFolder ? onCreateFolder(n?.is_dir ? n.path : (n?.path?.replace(/\/[^/]+$/, '') || workspaceRoot)) : onCreateFile?.(n?.path || workspaceRoot)}
          onDelete={(n) => onDeletePath?.(n.path, n.is_dir)}
          onShowDiff={onShowDiff}
          isLight={isLight}
        />
      )}

      {/* Modale Visualizza Docker & Sandbox Monitor */}
      <DockerViewerModal 
        isOpen={showDockerModal} 
        onClose={() => setShowDockerModal(false)} 
        isLight={isLight} 
        onSelectContainer={(cid) => {
          if (onSelectWorkspaceRoot) {
            onSelectWorkspaceRoot(`docker://${cid}/`);
          }
          setShowDockerModal(false);
        }}
      />
    </div>
  );
}
