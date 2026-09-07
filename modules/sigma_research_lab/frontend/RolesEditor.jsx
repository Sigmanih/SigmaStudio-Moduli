import React, { useState, useEffect, useCallback } from 'react';
import { useApp } from '../../contexts/AppContext';
import { 
  Users, Save, RotateCcw, Plus, Trash2, Check, RefreshCw, 
  Wrench, Sliders, FileText, Cpu, AlertCircle, Sparkles 
} from 'lucide-react';

const STANDARD_TOOLS = [
  { id: 'read_file', label: 'read_file', desc: 'Lettura file con paginazione e analisi AST' },
  { id: 'edit_file', label: 'edit_file', desc: 'Modifica chirurgica per blocchi univoci' },
  { id: 'write_file', label: 'write_file', desc: 'Creazione nuovi file o riscrittura completa' },
  { id: 'search_code', label: 'search_code', desc: 'Ricerca testuale e simboli nel workspace' },
  { id: 'list_dir', label: 'list_dir', desc: 'Esplorazione cartelle con profondità' },
  { id: 'glob', label: 'glob', desc: 'Filtro file tramite pattern glob' },
  { id: 'terminal', label: 'terminal', desc: 'Esecuzione comandi shell e suite di test' },
  { id: 'pipeline', label: 'pipeline', desc: 'Dichiarazione e avanzamento del DAG di task' },
  { id: 'git_status', label: 'git_status', desc: 'Controllo file modificati e branch git' },
  { id: 'git_log', label: 'git_log', desc: 'Storico commit del repository' },
  { id: 'git_diff', label: 'git_diff', desc: 'Differenze riga per riga' },
  { id: 'screenshot', label: 'screenshot', desc: 'Verifica visiva Chromium headless' },
  { id: 'visual_check', label: 'visual_check', desc: 'Controllo visivo interfaccia' },
  { id: 'delete', label: 'delete', desc: 'Rimozione file o cartelle' },
];

export default function RolesEditor({ addToast }) {
  const { theme } = useApp();
  const isLight = theme === 'light';

  const [roles, setRoles] = useState([]);
  const [selectedRoleId, setSelectedRoleId] = useState(null);
  const [editingRole, setEditingRole] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);
  const [customToolInput, setCustomToolInput] = useState('');
  const [customFocusInput, setCustomFocusInput] = useState('');
  const [showNewRoleModal, setShowNewRoleModal] = useState(false);
  const [newRoleData, setNewRoleData] = useState({
    id: '',
    name: '',
    icon: '🤖',
    system_prompt: 'Sei un agente specializzato per Sigma Studio.\nRispondi in italiano.',
    max_turns: 15,
  });

  const notify = useCallback((msg, type = 'info') => {
    if (typeof addToast === 'function') {
      addToast(msg, type);
    }
  }, [addToast]);

  const loadRoles = useCallback(async () => {
    setIsLoading(true);
    try {
      let res = await fetch('/api/roles');
      if (!res.ok) {
        res = await fetch('/api/developer/roles');
      }
      const data = await res.json();
      if (data.success && Array.isArray(data.roles)) {
        setRoles(data.roles);
        if (data.roles.length > 0) {
          const currentId = selectedRoleId || data.roles[0].id;
          const found = data.roles.find(r => r.id === currentId) || data.roles[0];
          setSelectedRoleId(found.id);
          setEditingRole(JSON.parse(JSON.stringify(found)));
          setHasChanges(false);
        }
      } else {
        notify('Impossibile caricare i ruoli: ' + (data.error || 'Errore sconosciuto'), 'error');
      }
    } catch (err) {
      notify('Errore di connessione durante il caricamento dei ruoli: ' + err.message, 'error');
    } finally {
      setIsLoading(false);
    }
  }, [selectedRoleId, notify]);

  useEffect(() => {
    loadRoles();
  }, [loadRoles]);

  const handleSelectRole = (role) => {
    if (hasChanges) {
      const conferma = window.confirm('Hai modifiche non salvate per questo ruolo. Vuoi continuare e scartarle?');
      if (!conferma) return;
    }
    setSelectedRoleId(role.id);
    setEditingRole(JSON.parse(JSON.stringify(role)));
    setHasChanges(false);
  };

  const handleFieldChange = (field, value) => {
    if (!editingRole) return;
    setEditingRole(prev => ({
      ...prev,
      [field]: value,
    }));
    setHasChanges(true);
  };

  const handleToggleTool = (toolId) => {
    if (!editingRole) return;
    const currentTools = Array.isArray(editingRole.tools) ? [...editingRole.tools] : [];
    const index = currentTools.indexOf(toolId);
    if (index >= 0) {
      currentTools.splice(index, 1);
    } else {
      currentTools.push(toolId);
    }
    handleFieldChange('tools', currentTools);
  };

  const handleAddCustomTool = () => {
    const trimmed = customToolInput.trim();
    if (!trimmed || !editingRole) return;
    const currentTools = Array.isArray(editingRole.tools) ? [...editingRole.tools] : [];
    if (!currentTools.includes(trimmed)) {
      currentTools.push(trimmed);
      handleFieldChange('tools', currentTools);
      setCustomToolInput('');
    }
  };

  const handleAddFocusArea = () => {
    const trimmed = customFocusInput.trim();
    if (!trimmed || !editingRole) return;
    const currentFocus = Array.isArray(editingRole.focus_areas) ? [...editingRole.focus_areas] : [];
    if (!currentFocus.includes(trimmed)) {
      currentFocus.push(trimmed);
      handleFieldChange('focus_areas', currentFocus);
      setCustomFocusInput('');
    }
  };

  const handleRemoveFocusArea = (area) => {
    if (!editingRole) return;
    const currentFocus = Array.isArray(editingRole.focus_areas) ? [...editingRole.focus_areas] : [];
    const updated = currentFocus.filter(a => a !== area);
    handleFieldChange('focus_areas', updated);
  };

  const handleSaveRole = async () => {
    if (!editingRole) return;
    setIsSaving(true);
    try {
      const patch = {
        name: editingRole.name,
        icon: editingRole.icon,
        system_prompt: editingRole.system_prompt,
        temperature: parseFloat(editingRole.temperature),
        top_p: parseFloat(editingRole.top_p),
        top_k: parseInt(editingRole.top_k, 10),
        max_tokens: parseInt(editingRole.max_tokens, 10),
        max_turns: parseInt(editingRole.max_turns, 10),
        model: editingRole.model || '',
        tools: editingRole.tools || [],
        focus_areas: editingRole.focus_areas || [],
      };

      const res = await fetch('/api/roles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: editingRole.id, patch }),
      });
      const data = await res.json();
      if (data.success && data.role) {
        notify(`Ruolo ${editingRole.name} salvato con successo in config/roles.json!`, 'success');
        setRoles(prev => prev.map(r => r.id === data.role.id ? data.role : r));
        setEditingRole(JSON.parse(JSON.stringify(data.role)));
        setHasChanges(false);
      } else {
        notify('Errore durante il salvataggio: ' + (data.error || 'Errore'), 'error');
      }
    } catch (err) {
      notify('Errore salvataggio ruolo: ' + err.message, 'error');
    } finally {
      setIsSaving(false);
    }
  };

  const handleResetRole = async () => {
    if (!editingRole) return;
    const conferma = window.confirm(`Vuoi davvero ripristinare il ruolo '${editingRole.name}' alle impostazioni predefinite del codice?`);
    if (!conferma) return;

    setIsSaving(true);
    try {
      const res = await fetch('/api/roles/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: editingRole.id }),
      });
      const data = await res.json();
      if (data.success) {
        notify(`Ruolo '${editingRole.name}' ripristinato ai valori predefiniti!`, 'info');
        await loadRoles();
      } else {
        notify('Errore durante il ripristino: ' + (data.error || 'Errore'), 'error');
      }
    } catch (err) {
      notify('Errore ripristino: ' + err.message, 'error');
    } finally {
      setIsSaving(false);
    }
  };

  const handleCreateNewRole = async () => {
    const rid = newRoleData.id.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_');
    if (!rid) {
      notify('Inserisci un identificatore valido per il nuovo ruolo.', 'warning');
      return;
    }
    try {
      const res = await fetch('/api/roles', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: rid,
          patch: {
            name: newRoleData.name || rid.toUpperCase(),
            icon: newRoleData.icon || '🤖',
            system_prompt: newRoleData.system_prompt,
            max_turns: parseInt(newRoleData.max_turns, 10) || 15,
            tools: ['read_file', 'terminal', 'search_code'],
          }
        }),
      });
      const data = await res.json();
      if (data.success) {
        notify(`Nuovo ruolo '${rid}' creato con successo!`, 'success');
        setShowNewRoleModal(false);
        await loadRoles();
        setSelectedRoleId(rid);
      } else {
        notify('Errore creazione: ' + (data.error || 'Errore'), 'error');
      }
    } catch (err) {
      notify('Errore creazione ruolo: ' + err.message, 'error');
    }
  };

  return (
    <div style={{
      display: 'flex',
      height: '100%',
      gap: '20px',
      overflow: 'hidden',
      fontFamily: 'Inter, system-ui, sans-serif'
    }}>
      {/* 1. SIDEBAR ELENCO RUOLI */}
      <div style={{
        width: '320px',
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
        background: isLight ? 'rgba(255, 255, 255, 0.7)' : 'rgba(15, 18, 28, 0.75)',
        border: isLight ? '1px solid rgba(0, 0, 0, 0.08)' : '1px solid rgba(255, 255, 255, 0.08)',
        borderRadius: '14px',
        padding: '16px',
        backdropFilter: 'blur(16px)',
        overflowY: 'auto'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: isLight ? '1px solid rgba(0,0,0,0.06)' : '1px solid rgba(255,255,255,0.06)', paddingBottom: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Users size={18} color={isLight ? '#ea580c' : '#00d2ff'} />
            <h3 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 800, color: isLight ? '#111' : '#fff' }}>Ruoli della Squadra</h3>
          </div>
          <div style={{ display: 'flex', gap: '6px' }}>
            <button
              onClick={loadRoles}
              title="Ricarica ruoli dal server"
              disabled={isLoading}
              style={{
                background: 'transparent',
                border: 'none',
                cursor: 'pointer',
                color: isLight ? '#666' : '#aaa',
                padding: '4px',
                borderRadius: '6px'
              }}
            >
              <RefreshCw size={14} className={isLoading ? 'spin' : ''} />
            </button>
            <button
              onClick={() => setShowNewRoleModal(true)}
              title="Aggiungi nuovo ruolo"
              style={{
                background: isLight ? '#ea580c' : '#00d2ff',
                color: isLight ? '#fff' : '#0a0d14',
                border: 'none',
                borderRadius: '6px',
                padding: '4px 8px',
                fontSize: '0.72rem',
                fontWeight: 700,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px'
              }}
            >
              <Plus size={13} /> Nuovo
            </button>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', overflowY: 'auto' }}>
          {roles.map(role => {
            const isSelected = selectedRoleId === role.id;
            return (
              <div
                key={role.id}
                onClick={() => handleSelectRole(role)}
                style={{
                  padding: '12px',
                  borderRadius: '10px',
                  cursor: 'pointer',
                  transition: 'all 0.18s ease',
                  background: isSelected
                    ? (isLight ? 'rgba(234, 88, 12, 0.12)' : 'rgba(0, 210, 255, 0.14)')
                    : (isLight ? 'rgba(0, 0, 0, 0.02)' : 'rgba(255, 255, 255, 0.02)'),
                  border: isSelected
                    ? (isLight ? '1px solid rgba(234, 88, 12, 0.4)' : '1px solid rgba(0, 210, 255, 0.4)')
                    : (isLight ? '1px solid rgba(0, 0, 0, 0.05)' : '1px solid rgba(255, 255, 255, 0.05)'),
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '6px'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontSize: '1.2rem' }}>{role.icon || '🤖'}</span>
                    <div>
                      <div style={{ fontSize: '0.85rem', fontWeight: 800, color: isSelected ? (isLight ? '#c2410c' : '#00d2ff') : (isLight ? '#222' : '#eee') }}>
                        {role.name}
                      </div>
                      <div style={{ fontSize: '0.68rem', color: isLight ? '#888' : '#777', fontFamily: 'monospace' }}>
                        id: {role.id}
                      </div>
                    </div>
                  </div>
                  <span style={{
                    fontSize: '0.62rem',
                    padding: '2px 6px',
                    borderRadius: '10px',
                    background: isLight ? 'rgba(0,0,0,0.06)' : 'rgba(255,255,255,0.08)',
                    color: isLight ? '#555' : '#bbb',
                    fontWeight: 600
                  }}>
                    {role.max_turns}t
                  </span>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.68rem', color: isLight ? '#666' : '#999', marginTop: '2px' }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                    <Wrench size={11} /> {role.tools?.length || 'Tutti'} tool
                  </span>
                  <span>•</span>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '140px' }}>
                    {role.model ? `Modello: ${role.model}` : 'Default motore'}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 2. AREA DETTAGLIO & EDITOR */}
      {editingRole ? (
        <div style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          background: isLight ? 'rgba(255, 255, 255, 0.7)' : 'rgba(15, 18, 28, 0.75)',
          border: isLight ? '1px solid rgba(0, 0, 0, 0.08)' : '1px solid rgba(255, 255, 255, 0.08)',
          borderRadius: '14px',
          padding: '20px',
          backdropFilter: 'blur(16px)',
          overflowY: 'auto',
          gap: '20px'
        }}>
          {/* Header Editor con Azioni */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: isLight ? '1px solid rgba(0,0,0,0.08)' : '1px solid rgba(255,255,255,0.08)',
            paddingBottom: '16px',
            flexWrap: 'wrap',
            gap: '12px'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <input
                type="text"
                value={editingRole.icon || ''}
                onChange={e => handleFieldChange('icon', e.target.value)}
                style={{
                  fontSize: '1.5rem',
                  width: '46px',
                  height: '46px',
                  textAlign: 'center',
                  borderRadius: '10px',
                  border: isLight ? '1px solid rgba(0,0,0,0.15)' : '1px solid rgba(255,255,255,0.15)',
                  background: isLight ? '#fff' : '#141724',
                  color: isLight ? '#111' : '#fff'
                }}
                title="Icona / Emoji del ruolo"
              />
              <div>
                <input
                  type="text"
                  value={editingRole.name || ''}
                  onChange={e => handleFieldChange('name', e.target.value)}
                  style={{
                    fontSize: '1.25rem',
                    fontWeight: 800,
                    borderRadius: '8px',
                    padding: '4px 8px',
                    border: isLight ? '1px solid rgba(0,0,0,0.15)' : '1px solid rgba(255,255,255,0.15)',
                    background: isLight ? '#fff' : '#141724',
                    color: isLight ? '#111' : '#fff',
                    outline: 'none',
                    minWidth: '220px'
                  }}
                  title="Nome descrittivo del ruolo"
                />
                <div style={{ fontSize: '0.72rem', color: isLight ? '#777' : '#888', marginTop: '4px' }}>
                  ID identificativo: <code>{editingRole.id}</code> (usato nei nodi DAG e nell'orchestrator)
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <button
                onClick={handleResetRole}
                disabled={isSaving}
                title="Ripristina alle impostazioni predefinite"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '8px 14px',
                  borderRadius: '8px',
                  background: isLight ? '#f3f4f6' : '#212534',
                  color: isLight ? '#4b5563' : '#cbd5e1',
                  border: isLight ? '1px solid #d1d5db' : '1px solid rgba(255,255,255,0.1)',
                  fontSize: '0.78rem',
                  fontWeight: 700,
                  cursor: 'pointer'
                }}
              >
                <RotateCcw size={14} /> Ripristina Default
              </button>

              <button
                onClick={handleSaveRole}
                disabled={isSaving || !hasChanges}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '8px 18px',
                  borderRadius: '8px',
                  background: hasChanges
                    ? (isLight ? '#ea580c' : '#00d2ff')
                    : (isLight ? '#9ca3af' : '#334155'),
                  color: hasChanges ? (isLight ? '#fff' : '#0a0d14') : '#fff',
                  border: 'none',
                  fontSize: '0.78rem',
                  fontWeight: 800,
                  cursor: hasChanges ? 'pointer' : 'default',
                  boxShadow: hasChanges ? (isLight ? '0 2px 10px rgba(234, 88, 12, 0.3)' : '0 2px 10px rgba(0, 210, 255, 0.3)') : 'none',
                  transition: 'all 0.2s ease'
                }}
              >
                <Save size={14} /> {isSaving ? 'Salvataggio...' : 'Salva in config/roles.json'}
              </button>
            </div>
          </div>

          {/* Griglia Parametri: Modello & Budget */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: '14px',
            background: isLight ? 'rgba(0,0,0,0.02)' : 'rgba(255,255,255,0.02)',
            padding: '14px',
            borderRadius: '10px',
            border: isLight ? '1px solid rgba(0,0,0,0.05)' : '1px solid rgba(255,255,255,0.05)'
          }}>
            <div>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', fontWeight: 700, color: isLight ? '#333' : '#ccc', marginBottom: '6px' }}>
                <Cpu size={14} /> Modello Preferito
              </label>
              <input
                type="text"
                value={editingRole.model || ''}
                onChange={e => handleFieldChange('model', e.target.value)}
                placeholder="Vuoto = Default motore attivo"
                style={{
                  width: '100%',
                  padding: '8px 10px',
                  borderRadius: '6px',
                  border: isLight ? '1px solid rgba(0,0,0,0.15)' : '1px solid rgba(255,255,255,0.15)',
                  background: isLight ? '#fff' : '#141724',
                  color: isLight ? '#111' : '#fff',
                  fontSize: '0.8rem',
                  outline: 'none',
                  boxSizing: 'border-box'
                }}
              />
              <span style={{ fontSize: '0.65rem', color: isLight ? '#888' : '#777', marginTop: '4px', display: 'block' }}>
                Nome alias o checkpoint (es. qwen2.5-coder-7b, deepseek-coder)
              </span>
            </div>

            <div>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', fontWeight: 700, color: isLight ? '#333' : '#ccc', marginBottom: '6px' }}>
                <Sliders size={14} /> Budget Turni Max ({editingRole.max_turns} turni)
              </label>
              <input
                type="range"
                min="3"
                max="50"
                step="1"
                value={editingRole.max_turns || 12}
                onChange={e => handleFieldChange('max_turns', parseInt(e.target.value, 10))}
                style={{ width: '100%', cursor: 'pointer' }}
              />
              <span style={{ fontSize: '0.65rem', color: isLight ? '#888' : '#777', marginTop: '2px', display: 'block' }}>
                Round-trip di tool concessi all'agente prima dello stop
              </span>
            </div>

            <div>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', fontWeight: 700, color: isLight ? '#333' : '#ccc', marginBottom: '6px' }}>
                <Sparkles size={14} /> Temperatura ({editingRole.temperature})
              </label>
              <input
                type="range"
                min="0.0"
                max="1.0"
                step="0.05"
                value={editingRole.temperature ?? 0.3}
                onChange={e => handleFieldChange('temperature', parseFloat(e.target.value))}
                style={{ width: '100%', cursor: 'pointer' }}
              />
              <span style={{ fontSize: '0.65rem', color: isLight ? '#888' : '#777', marginTop: '2px', display: 'block' }}>
                Bassa (0.2) per codice preciso, alta (0.7) per creatività
              </span>
            </div>

            <div>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', fontWeight: 700, color: isLight ? '#333' : '#ccc', marginBottom: '6px' }}>
                <FileText size={14} /> Max Tokens di Risposta
              </label>
              <input
                type="number"
                min="512"
                max="32768"
                step="512"
                value={editingRole.max_tokens || 4096}
                onChange={e => handleFieldChange('max_tokens', parseInt(e.target.value, 10))}
                style={{
                  width: '100%',
                  padding: '8px 10px',
                  borderRadius: '6px',
                  border: isLight ? '1px solid rgba(0,0,0,0.15)' : '1px solid rgba(255,255,255,0.15)',
                  background: isLight ? '#fff' : '#141724',
                  color: isLight ? '#111' : '#fff',
                  fontSize: '0.8rem',
                  outline: 'none',
                  boxSizing: 'border-box'
                }}
              />
            </div>
          </div>

          {/* Sezione Tool Abilitati */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.82rem', fontWeight: 800, color: isLight ? '#222' : '#eee' }}>
                <Wrench size={16} color={isLight ? '#ea580c' : '#00d2ff'} /> Tool Permessi per questo Ruolo
              </label>
              <span style={{ fontSize: '0.7rem', color: isLight ? '#777' : '#888' }}>
                I tool deselezionati vengono filtrati via prima dell'invio del prompt (ToolPolicy)
              </span>
            </div>

            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
              gap: '8px',
              marginBottom: '12px'
            }}>
              {STANDARD_TOOLS.map(tool => {
                const currentTools = Array.isArray(editingRole.tools) ? editingRole.tools : [];
                const isChecked = currentTools.includes(tool.id) || currentTools.length === 0;
                return (
                  <div
                    key={tool.id}
                    onClick={() => handleToggleTool(tool.id)}
                    style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '8px',
                      padding: '8px 10px',
                      borderRadius: '8px',
                      cursor: 'pointer',
                      background: isChecked
                        ? (isLight ? 'rgba(234, 88, 12, 0.08)' : 'rgba(0, 210, 255, 0.08)')
                        : (isLight ? 'rgba(0, 0, 0, 0.02)' : 'rgba(255, 255, 255, 0.02)'),
                      border: isChecked
                        ? (isLight ? '1px solid rgba(234, 88, 12, 0.3)' : '1px solid rgba(0, 210, 255, 0.3)')
                        : (isLight ? '1px solid rgba(0, 0, 0, 0.06)' : '1px solid rgba(255, 255, 255, 0.06)'),
                      transition: 'all 0.15s ease'
                    }}
                  >
                    <div style={{
                      width: '16px',
                      height: '16px',
                      borderRadius: '4px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      marginTop: '2px',
                      flexShrink: 0,
                      background: isChecked ? (isLight ? '#ea580c' : '#00d2ff') : 'transparent',
                      border: isChecked ? 'none' : (isLight ? '1px solid #999' : '1px solid #666'),
                      color: isLight ? '#fff' : '#0a0d14'
                    }}>
                      {isChecked && <Check size={12} strokeWidth={3} />}
                    </div>
                    <div>
                      <div style={{ fontSize: '0.78rem', fontWeight: 700, color: isChecked ? (isLight ? '#c2410c' : '#00d2ff') : (isLight ? '#555' : '#aaa'), fontFamily: 'monospace' }}>
                        {tool.label}
                      </div>
                      <div style={{ fontSize: '0.65rem', color: isLight ? '#777' : '#777', lineHeight: 1.2 }}>
                        {tool.desc}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Aggiunta Tool Personalizzati / Wildcard */}
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <input
                type="text"
                placeholder="Aggiungi tool personalizzato o pattern (es. mcp_*, git_*)..."
                value={customToolInput}
                onChange={e => setCustomToolInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleAddCustomTool()}
                style={{
                  flex: 1,
                  padding: '6px 10px',
                  borderRadius: '6px',
                  border: isLight ? '1px solid rgba(0,0,0,0.15)' : '1px solid rgba(255,255,255,0.15)',
                  background: isLight ? '#fff' : '#141724',
                  color: isLight ? '#111' : '#fff',
                  fontSize: '0.78rem',
                  outline: 'none'
                }}
              />
              <button
                onClick={handleAddCustomTool}
                style={{
                  padding: '6px 12px',
                  borderRadius: '6px',
                  background: isLight ? '#f3f4f6' : '#212534',
                  color: isLight ? '#333' : '#eee',
                  border: isLight ? '1px solid #d1d5db' : '1px solid rgba(255,255,255,0.1)',
                  fontSize: '0.75rem',
                  fontWeight: 700,
                  cursor: 'pointer'
                }}
              >
                Aggiungi Tool
              </button>
            </div>
          </div>

          {/* Sezione Focus Areas */}
          <div>
            <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: 800, color: isLight ? '#222' : '#eee', marginBottom: '6px' }}>
              Aree di Focalizzazione ({editingRole.focus_areas?.length || 0})
            </label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
              {(editingRole.focus_areas || []).map((area, idx) => (
                <span
                  key={idx}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '3px 10px',
                    borderRadius: '12px',
                    background: isLight ? 'rgba(0,0,0,0.06)' : 'rgba(255,255,255,0.08)',
                    fontSize: '0.72rem',
                    color: isLight ? '#333' : '#ddd'
                  }}
                >
                  {area}
                  <button
                    onClick={() => handleRemoveFocusArea(area)}
                    style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: '#ef4444', display: 'flex' }}
                    title="Rimuovi area"
                  >
                    <Trash2 size={11} />
                  </button>
                </span>
              ))}
            </div>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <input
                type="text"
                placeholder="Aggiungi area di attenzione (es. sicurezza, test unitari)..."
                value={customFocusInput}
                onChange={e => setCustomFocusInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleAddFocusArea()}
                style={{
                  maxWidth: '360px',
                  padding: '6px 10px',
                  borderRadius: '6px',
                  border: isLight ? '1px solid rgba(0,0,0,0.15)' : '1px solid rgba(255,255,255,0.15)',
                  background: isLight ? '#fff' : '#141724',
                  color: isLight ? '#111' : '#fff',
                  fontSize: '0.78rem',
                  outline: 'none'
                }}
              />
              <button
                onClick={handleAddFocusArea}
                style={{
                  padding: '6px 12px',
                  borderRadius: '6px',
                  background: isLight ? '#f3f4f6' : '#212534',
                  color: isLight ? '#333' : '#eee',
                  border: isLight ? '1px solid #d1d5db' : '1px solid rgba(255,255,255,0.1)',
                  fontSize: '0.75rem',
                  fontWeight: 700,
                  cursor: 'pointer'
                }}
              >
                + Aggiungi
              </button>
            </div>
          </div>

          {/* Sezione System Prompt */}
          <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: '260px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.82rem', fontWeight: 800, color: isLight ? '#222' : '#eee' }}>
                <FileText size={16} color={isLight ? '#ea580c' : '#00d2ff'} /> Prompt di Sistema del Ruolo (System Prompt)
              </label>
              <span style={{ fontSize: '0.68rem', color: isLight ? '#777' : '#888' }}>
                {editingRole.system_prompt?.length || 0} caratteri
              </span>
            </div>
            <textarea
              value={editingRole.system_prompt || ''}
              onChange={e => handleFieldChange('system_prompt', e.target.value)}
              rows={12}
              style={{
                width: '100%',
                flex: 1,
                minHeight: '220px',
                padding: '12px',
                borderRadius: '8px',
                border: isLight ? '1px solid rgba(0,0,0,0.15)' : '1px solid rgba(255,255,255,0.15)',
                background: isLight ? '#fcfbf9' : '#0d101a',
                color: isLight ? '#111' : '#e2e8f0',
                fontFamily: "'JetBrains Mono', Consolas, 'Courier New', monospace",
                fontSize: '0.82rem',
                lineHeight: 1.5,
                resize: 'vertical',
                outline: 'none',
                boxSizing: 'border-box'
              }}
              placeholder="Inserisci qui le istruzioni di sistema per questo ruolo..."
            />
          </div>
        </div>
      ) : (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#888' }}>
          Seleziona un ruolo dalla lista per visualizzarne o modificarne la configurazione.
        </div>
      )}

      {/* MODAL NUOVO RUOLO */}
      {showNewRoleModal && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.65)',
          backdropFilter: 'blur(4px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 9999
        }}>
          <div style={{
            width: '450px',
            background: isLight ? '#ffffff' : '#161926',
            border: isLight ? '1px solid #ccc' : '1px solid rgba(255,255,255,0.15)',
            borderRadius: '12px',
            padding: '24px',
            display: 'flex',
            flexDirection: 'column',
            gap: '14px',
            boxShadow: '0 12px 36px rgba(0,0,0,0.5)'
          }}>
            <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 800, color: isLight ? '#111' : '#fff' }}>
              Crea Nuovo Ruolo
            </h3>
            <div>
              <label style={{ fontSize: '0.75rem', fontWeight: 700, display: 'block', marginBottom: '4px' }}>ID Univoco (es. security_analyst)</label>
              <input
                type="text"
                placeholder="es. data_engineer"
                value={newRoleData.id}
                onChange={e => setNewRoleData(prev => ({ ...prev, id: e.target.value }))}
                style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid #888', background: isLight ? '#fff' : '#0d101a', color: isLight ? '#000' : '#fff', boxSizing: 'border-box' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '0.75rem', fontWeight: 700, display: 'block', marginBottom: '4px' }}>Nome Visibile & Icona</label>
              <div style={{ display: 'flex', gap: '8px' }}>
                <input
                  type="text"
                  value={newRoleData.icon}
                  onChange={e => setNewRoleData(prev => ({ ...prev, icon: e.target.value }))}
                  style={{ width: '50px', textAlign: 'center', fontSize: '1.2rem', padding: '6px', borderRadius: '6px', border: '1px solid #888', background: isLight ? '#fff' : '#0d101a', color: isLight ? '#000' : '#fff' }}
                />
                <input
                  type="text"
                  placeholder="Nome Ruolo"
                  value={newRoleData.name}
                  onChange={e => setNewRoleData(prev => ({ ...prev, name: e.target.value }))}
                  style={{ flex: 1, padding: '8px', borderRadius: '6px', border: '1px solid #888', background: isLight ? '#fff' : '#0d101a', color: isLight ? '#000' : '#fff' }}
                />
              </div>
            </div>
            <div>
              <label style={{ fontSize: '0.75rem', fontWeight: 700, display: 'block', marginBottom: '4px' }}>Budget Turni Iniziale</label>
              <input
                type="number"
                value={newRoleData.max_turns}
                onChange={e => setNewRoleData(prev => ({ ...prev, max_turns: e.target.value }))}
                style={{ width: '100%', padding: '8px', borderRadius: '6px', border: '1px solid #888', background: isLight ? '#fff' : '#0d101a', color: isLight ? '#000' : '#fff', boxSizing: 'border-box' }}
              />
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
              <button
                onClick={() => setShowNewRoleModal(false)}
                style={{ padding: '8px 14px', borderRadius: '6px', border: 'none', background: '#444', color: '#fff', cursor: 'pointer' }}
              >
                Annulla
              </button>
              <button
                onClick={handleCreateNewRole}
                style={{ padding: '8px 18px', borderRadius: '6px', border: 'none', background: isLight ? '#ea580c' : '#00d2ff', color: isLight ? '#fff' : '#0a0d14', fontWeight: 800, cursor: 'pointer' }}
              >
                Crea Ruolo
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
