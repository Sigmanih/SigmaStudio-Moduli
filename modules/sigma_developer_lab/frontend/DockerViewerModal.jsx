import React, { useState, useEffect, useCallback } from 'react';
import { 
  X, RefreshCw, Box, CheckCircle2, AlertCircle, ShieldCheck, 
  Layers, Terminal, Play, Square, RotateCw, Trash2, FolderOpen, Plus, Rocket,
  ExternalLink
} from 'lucide-react';

const extractHostPorts = (portsStr) => {
  if (!portsStr) return [];
  const ports = new Set();
  const re = /(?:^|[,\s])(?:(?:\d{1,3}\.){3}\d{1,3}|\[::\]|::)?:?(\d+)->/g;
  let match;
  while ((match = re.exec(portsStr)) !== null) {
    if (match[1]) ports.add(match[1]);
  }
  return Array.from(ports);
};

export default function DockerViewerModal({ isOpen, onClose, isLight, onSelectContainer }) {
  const [dockerData, setDockerData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [actionLoading, setActionLoading] = useState(null); // id container o 'launch'
  const [feedback, setFeedback] = useState(null);
  const [activeTab, setActiveTab] = useState('containers'); // 'containers' | 'images' | 'sandbox'

  // Stato per il form di lancio container
  const [showLaunchForm, setShowLaunchForm] = useState(false);
  const [launchImage, setLaunchImage] = useState('nikolaik/python-nodejs:python3.12-nodejs22');
  const [customImageMode, setCustomImageMode] = useState(false);
  const [launchName, setLaunchName] = useState('');
  const [launchPorts, setLaunchPorts] = useState('5173:5173, 8000:8000, 3000:3000');
  const [launchMode, setLaunchMode] = useState('app'); // 'app' (avvia server) | 'sandbox' (tail -f /dev/null)

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/developer/sandbox');
      const data = await res.json();
      if (data && data.success) {
        setDockerData(data);
        // Se disponibile un'immagine locale e non è impostata, impostala come predefinita
        if (data.images && data.images.length > 0 && !launchImage) {
          const first = data.images[0];
          setLaunchImage(`${first.Repository}:${first.Tag || 'latest'}`);
        }
      }
    } catch (err) {
      console.error('Errore recupero dettagli Docker:', err);
    } finally {
      setLoading(false);
    }
  }, [launchImage]);

  useEffect(() => {
    if (isOpen) {
      fetchStatus();
      setFeedback(null);
    }
  }, [isOpen, fetchStatus]);

  const handleToggleMode = async (targetMode) => {
    setToggling(true);
    try {
      const res = await fetch('/api/developer/sandbox', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: targetMode })
      });
      const data = await res.json();
      if (data && data.success) {
        setDockerData(prev => ({ ...prev, ...data }));
      }
    } catch (err) {
      console.error('Errore modifica sandbox:', err);
    } finally {
      setToggling(false);
    }
  };

  const handleSaveSandboxImage = async (newImg) => {
    if (!newImg) return;
    try {
      const res = await fetch('/api/developer/sandbox', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: newImg })
      });
      const data = await res.json();
      if (data && data.success) {
        setDockerData(prev => ({ ...prev, image: newImg }));
        setFeedback({ type: 'success', message: `Immagine predefinita Sandbox aggiornata a: ${newImg}` });
      } else {
        setFeedback({ type: 'error', message: data?.error || 'Errore impostazione immagine sandbox' });
      }
    } catch (err) {
      setFeedback({ type: 'error', message: String(err) });
    }
  };

  const handleContainerAction = async (action, cid) => {
    if (!cid) return;
    setActionLoading(`${action}-${cid}`);
    setFeedback(null);
    try {
      const res = await fetch(`/api/developer/docker/container/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: cid, force: action === 'remove' })
      });
      const data = await res.json();
      if (data && data.success) {
        setFeedback({ type: 'success', message: data.message || `Operazione '${action}' eseguita con successo.` });
        await fetchStatus();
      } else {
        setFeedback({ type: 'error', message: data?.error || `Errore operazione ${action}` });
      }
    } catch (err) {
      setFeedback({ type: 'error', message: String(err) });
    } finally {
      setActionLoading(null);
    }
  };

  const handleLaunchContainer = async (e) => {
    if (e) e.preventDefault();
    setActionLoading('launch');
    setFeedback(null);
    try {
      const portsArr = launchPorts
        .split(/[,;\s]+/)
        .map(p => p.trim())
        .filter(p => p.includes(':'));

      const res = await fetch('/api/developer/docker/container/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image: launchImage.trim() || 'python:3.12-slim',
          name: launchName.trim() || undefined,
          ports: portsArr.length > 0 ? portsArr : undefined,
          modalita: launchMode
        })
      });
      const data = await res.json();
      if (data && data.success) {
        setFeedback({ type: 'success', message: data.message || 'Container avviato con successo!' });
        setShowLaunchForm(false);
        setLaunchName('');
        await fetchStatus();
      } else {
        setFeedback({ type: 'error', message: data?.error || 'Errore lancio container' });
      }
    } catch (err) {
      setFeedback({ type: 'error', message: String(err) });
    } finally {
      setActionLoading(null);
    }
  };

  const handleApplyImagePreset = (imgTag) => {
    setLaunchImage(imgTag);
    const lower = imgTag.toLowerCase();
    if (lower.includes('frontend')) {
      setLaunchPorts('5173:80');
      setLaunchName('biblioteca-frontend');
      setLaunchMode('app');
    } else if (lower.includes('backend')) {
      setLaunchPorts('3000:3000');
      setLaunchName('backend');
      setLaunchMode('app');
    } else {
      const cleanTag = imgTag.split(':')[0].replace(/[^a-zA-Z0-9_-]/g, '-');
      setLaunchName(`sandbox-${cleanTag}`);
      setLaunchPorts('3000:3000, 5173:5173');
      setLaunchMode('sandbox');
    }
  };

  const handleSelectImageForLaunch = (imgTag) => {
    handleApplyImagePreset(imgTag);
    setShowLaunchForm(true);
    setActiveTab('containers');
  };

  if (!isOpen) return null;

  const bgModal = isLight ? '#ffffff' : '#0d1117';
  const borderModal = isLight ? '#d0d7de' : 'rgba(255,255,255,0.12)';
  const textPrimary = isLight ? '#24292f' : '#f0f6fc';
  const textMuted = isLight ? '#57606a' : '#8b949e';
  const bgCard = isLight ? '#f6f8fa' : '#161b22';

  const isAvailable = dockerData?.docker_available ?? false;
  const isContainerMode = dockerData?.mode === 'container';
  const containers = dockerData?.containers || [];
  const images = dockerData?.images || [];

  return (
    <div 
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.65)',
        backdropFilter: 'blur(5px)',
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px'
      }}
    >
      <div 
        onClick={e => e.stopPropagation()}
        style={{
          width: '780px',
          maxWidth: '96vw',
          maxHeight: '88vh',
          background: bgModal,
          border: `1px solid ${borderModal}`,
          borderRadius: '12px',
          boxShadow: '0 20px 45px rgba(0,0,0,0.5)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden'
        }}
      >
        {/* Header */}
        <div style={{
          padding: '14px 18px',
          borderBottom: `1px solid ${borderModal}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: isLight ? '#f6f8fa' : 'rgba(255,255,255,0.02)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '32px',
              height: '32px',
              borderRadius: '8px',
              background: 'linear-gradient(135deg, #0284c7, #0ea5e9)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#ffffff',
              fontSize: '1.1rem'
            }}>
              🐳
            </div>
            <div>
              <div style={{ fontSize: '0.92rem', fontWeight: 800, color: textPrimary, display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span>Docker Sandbox & Container Control</span>
                <span style={{
                  fontSize: '0.62rem',
                  fontWeight: 700,
                  padding: '2px 6px',
                  borderRadius: '10px',
                  background: isAvailable ? 'rgba(56, 189, 248, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                  color: isAvailable ? '#38bdf8' : '#ef4444',
                  border: isAvailable ? '1px solid rgba(56, 189, 248, 0.3)' : '1px solid rgba(239, 68, 68, 0.3)'
                }}>
                  {isAvailable ? `v${dockerData?.docker_detail || 'Attivo'}` : 'Non disponibile'}
                </span>
              </div>
              <div style={{ fontSize: '0.68rem', color: textMuted }}>
                Attiva, controlla o lancia tutte le immagini e i container Docker locali
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <button
              onClick={fetchStatus}
              disabled={loading}
              title="Ricarica stato Docker"
              style={{
                background: 'transparent',
                border: `1px solid ${borderModal}`,
                borderRadius: '6px',
                padding: '6px 8px',
                color: textMuted,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                fontSize: '0.72rem'
              }}
            >
              <RefreshCw size={13} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
              <span>Ricarica</span>
            </button>
            <button
              onClick={onClose}
              style={{
                background: 'transparent',
                border: 'none',
                color: textMuted,
                cursor: 'pointer',
                padding: '4px'
              }}
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Feedback Alert Banner */}
        {feedback && (
          <div style={{
            padding: '8px 18px',
            fontSize: '0.74rem',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            background: feedback.type === 'success' ? 'rgba(34, 197, 94, 0.12)' : 'rgba(239, 68, 68, 0.12)',
            borderBottom: feedback.type === 'success' ? '1px solid rgba(34, 197, 94, 0.3)' : '1px solid rgba(239, 68, 68, 0.3)',
            color: feedback.type === 'success' ? '#22c55e' : '#ef4444'
          }}>
            {feedback.type === 'success' ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
            <span>{feedback.message}</span>
          </div>
        )}

        {/* Quick Mode Switcher Banner */}
        <div style={{
          padding: '12px 18px',
          background: isContainerMode ? 'rgba(56, 189, 248, 0.08)' : (isLight ? '#fafafa' : 'rgba(255,255,255,0.02)'),
          borderBottom: `1px solid ${borderModal}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '12px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <ShieldCheck size={18} color={isContainerMode ? '#38bdf8' : '#8b949e'} />
            <div>
              <div style={{ fontSize: '0.78rem', fontWeight: 700, color: textPrimary }}>
                Modalità Esecuzione Sandbox: <span style={{ color: isContainerMode ? '#38bdf8' : '#f59e0b' }}>
                  {isContainerMode ? 'Container Docker Isolato' : 'Host Locale (Standard)'}
                </span>
              </div>
              <div style={{ fontSize: '0.68rem', color: textMuted }}>
                {isContainerMode 
                  ? 'I comandi dei task e degli agenti girano isolati nel container con dev-server esposti.'
                  : 'I comandi girano sulla macchina host usando l\'ambiente nativo.'}
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <button
              onClick={() => handleToggleMode('host')}
              disabled={toggling || !isContainerMode}
              style={{
                padding: '4px 10px',
                borderRadius: '6px',
                fontSize: '0.72rem',
                fontWeight: 700,
                cursor: isContainerMode ? 'pointer' : 'default',
                background: !isContainerMode ? (isLight ? '#e1e4e8' : 'rgba(255,255,255,0.12)') : 'transparent',
                border: `1px solid ${borderModal}`,
                color: !isContainerMode ? textPrimary : textMuted
              }}
            >
              💻 Host
            </button>
            <button
              onClick={() => handleToggleMode('container')}
              disabled={toggling || !isAvailable || isContainerMode}
              style={{
                padding: '4px 12px',
                borderRadius: '6px',
                fontSize: '0.72rem',
                fontWeight: 700,
                cursor: (isAvailable && !isContainerMode) ? 'pointer' : 'default',
                background: isContainerMode ? '#0284c7' : 'transparent',
                border: isContainerMode ? 'none' : '1px solid rgba(56, 189, 248, 0.4)',
                color: isContainerMode ? '#ffffff' : '#38bdf8'
              }}
            >
              🐳 Docker Sandbox
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div style={{
          display: 'flex',
          borderBottom: `1px solid ${borderModal}`,
          padding: '0 18px',
          background: isLight ? '#f6f8fa' : 'rgba(0,0,0,0.15)',
          gap: '16px'
        }}>
          {[
            { id: 'containers', label: `Container (${containers.length})`, icon: Box },
            { id: 'images', label: `Tutte le Immagini Locali (${images.length})`, icon: Layers },
            { id: 'sandbox', label: 'Rete & Porte Dev', icon: Terminal },
          ].map(tab => {
            const Icon = tab.icon;
            const isTabActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '10px 4px',
                  border: 'none',
                  borderBottom: isTabActive ? '2px solid #00d2ff' : '2px solid transparent',
                  background: 'transparent',
                  color: isTabActive ? '#00d2ff' : textMuted,
                  fontWeight: isTabActive ? 800 : 600,
                  fontSize: '0.76rem',
                  cursor: 'pointer'
                }}
              >
                <Icon size={14} />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>

        {/* Content Body */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          padding: '18px',
          minHeight: '280px'
        }}>
          {activeTab === 'containers' && (
            <div>
              {/* Header Action Bar: Avvia Nuovo Container */}
              <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: '14px'
              }}>
                <div style={{ fontSize: '0.78rem', fontWeight: 700, color: textPrimary }}>
                  Gestione & Attivazione Container
                </div>
                <button
                  onClick={() => setShowLaunchForm(prev => !prev)}
                  disabled={!isAvailable}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '5px',
                    padding: '5px 12px',
                    borderRadius: '6px',
                    fontSize: '0.72rem',
                    fontWeight: 700,
                    background: showLaunchForm ? 'rgba(239, 68, 68, 0.15)' : 'linear-gradient(135deg, #0284c7, #0ea5e9)',
                    border: showLaunchForm ? '1px solid rgba(239, 68, 68, 0.3)' : 'none',
                    color: showLaunchForm ? '#ef4444' : '#ffffff',
                    cursor: isAvailable ? 'pointer' : 'not-allowed',
                    opacity: isAvailable ? 1 : 0.6
                  }}
                >
                  {showLaunchForm ? (
                    <>
                      <X size={12} />
                      <span>Annulla Creazione</span>
                    </>
                  ) : (
                    <>
                      <Plus size={13} />
                      <span>Avvia Nuovo Container</span>
                    </>
                  )}
                </button>
              </div>

              {/* Form Espandibile di Lancio Container */}
              {showLaunchForm && (
                <form 
                  onSubmit={handleLaunchContainer}
                  style={{
                    padding: '14px',
                    background: isLight ? '#f0f3f6' : 'rgba(2, 132, 199, 0.08)',
                    border: '1px solid rgba(56, 189, 248, 0.3)',
                    borderRadius: '8px',
                    marginBottom: '16px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '10px'
                  }}
                >
                  <div style={{ fontSize: '0.78rem', fontWeight: 800, color: '#38bdf8' }}>
                    🚀 Configura e Lancia Container Sandbox
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
                        <label style={{ fontSize: '0.68rem', fontWeight: 700, color: textMuted }}>
                          Immagine Docker:
                        </label>
                        <button
                          type="button"
                          onClick={() => setCustomImageMode(!customImageMode)}
                          style={{
                            background: 'none',
                            border: 'none',
                            color: '#38bdf8',
                            fontSize: '0.62rem',
                            cursor: 'pointer',
                            textDecoration: 'underline'
                          }}
                        >
                          {customImageMode ? 'Scegli da lista' : 'Inserimento manuale'}
                        </button>
                      </div>

                      {customImageMode ? (
                        <input
                          type="text"
                          value={launchImage}
                          onChange={e => setLaunchImage(e.target.value)}
                          placeholder="es. biblioteca-frontend:latest o python:3.12-slim"
                          style={{
                            width: '100%',
                            padding: '6px 8px',
                            borderRadius: '6px',
                            border: `1px solid ${borderModal}`,
                            background: isLight ? '#ffffff' : '#0d1117',
                            color: textPrimary,
                            fontSize: '0.74rem'
                          }}
                        />
                      ) : (
                        <select
                          value={launchImage}
                          onChange={e => handleApplyImagePreset(e.target.value)}
                          style={{
                            width: '100%',
                            padding: '6px 8px',
                            borderRadius: '6px',
                            border: `1px solid ${borderModal}`,
                            background: isLight ? '#ffffff' : '#0d1117',
                            color: textPrimary,
                            fontSize: '0.74rem',
                            cursor: 'pointer'
                          }}
                        >
                          {images.length > 0 && (
                            <optgroup label="Immagini Locali Rilevate in Docker">
                              {images.map(img => {
                                const repo = img.Repository || '';
                                const tag = img.Tag || 'latest';
                                const fullTag = `${repo}:${tag}`;
                                return (
                                  <option key={img.ID || fullTag} value={fullTag}>
                                    {fullTag} ({img.Size || 'locale'})
                                  </option>
                                );
                              })}
                            </optgroup>
                          )}
                          <optgroup label="Altre Immagini Consigliate">
                            <option value="nikolaik/python-nodejs:python3.12-nodejs22">nikolaik/python-nodejs:python3.12-nodejs22</option>
                            <option value="python:3.12-slim">python:3.12-slim</option>
                            <option value="node:22-slim">node:22-slim</option>
                          </optgroup>
                        </select>
                      )}
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: '0.68rem', fontWeight: 700, color: textMuted, marginBottom: '4px' }}>
                        Nome Container (opzionale):
                      </label>
                      <input
                        type="text"
                        value={launchName}
                        onChange={e => setLaunchName(e.target.value)}
                        placeholder="es. sigma-dev-sandbox"
                        style={{
                          width: '100%',
                          padding: '6px 8px',
                          borderRadius: '6px',
                          border: `1px solid ${borderModal}`,
                          background: isLight ? '#ffffff' : '#0d1117',
                          color: textPrimary,
                          fontSize: '0.74rem'
                        }}
                      />
                    </div>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.68rem', fontWeight: 700, color: textMuted, marginBottom: '4px' }}>
                        Porte da Inoltrare (Host:Container):
                      </label>
                      <input
                        type="text"
                        value={launchPorts}
                        onChange={e => setLaunchPorts(e.target.value)}
                        placeholder="5173:80, 3000:3000, 8000:8000"
                        style={{
                          width: '100%',
                          padding: '6px 8px',
                          borderRadius: '6px',
                          border: `1px solid ${borderModal}`,
                          background: isLight ? '#ffffff' : '#0d1117',
                          color: textPrimary,
                          fontSize: '0.74rem'
                        }}
                      />
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: '0.68rem', fontWeight: 700, color: textMuted, marginBottom: '4px' }}>
                        Tipo di Esecuzione:
                      </label>
                      <select
                        value={launchMode}
                        onChange={e => setLaunchMode(e.target.value)}
                        style={{
                          width: '100%',
                          padding: '6px 8px',
                          borderRadius: '6px',
                          border: `1px solid ${borderModal}`,
                          background: isLight ? '#ffffff' : '#0d1117',
                          color: textPrimary,
                          fontSize: '0.74rem',
                          cursor: 'pointer'
                        }}
                      >
                        <option value="app">🚀 Server Web / App (CMD Nativo)</option>
                        <option value="sandbox">🛡️ Sandbox Agente (tail -f /dev/null)</option>
                      </select>
                    </div>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '4px' }}>
                    <button
                      type="button"
                      onClick={() => setShowLaunchForm(false)}
                      style={{
                        padding: '5px 12px',
                        borderRadius: '6px',
                        fontSize: '0.72rem',
                        border: `1px solid ${borderModal}`,
                        background: 'transparent',
                        color: textMuted,
                        cursor: 'pointer'
                      }}
                    >
                      Annulla
                    </button>
                    <button
                      type="submit"
                      disabled={actionLoading === 'launch'}
                      style={{
                        padding: '5px 14px',
                        borderRadius: '6px',
                        fontSize: '0.72rem',
                        fontWeight: 700,
                        border: 'none',
                        background: '#0284c7',
                        color: '#ffffff',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px'
                      }}
                    >
                      {actionLoading === 'launch' && <RefreshCw size={12} style={{ animation: 'spin 1s linear infinite' }} />}
                      <span>Lancia ed Attiva Subito</span>
                    </button>
                  </div>
                </form>
              )}

              {/* Lista Container */}
              {containers.length === 0 ? (
                <div style={{
                  padding: '36px 18px',
                  textAlign: 'center',
                  background: bgCard,
                  borderRadius: '8px',
                  border: `1px dashed ${borderModal}`
                }}>
                  <Box size={32} color="#8b949e" style={{ margin: '0 auto 10px auto', display: 'block' }} />
                  <div style={{ fontSize: '0.84rem', fontWeight: 700, color: textPrimary, marginBottom: '4px' }}>
                    Nessun Container In Esecuzione
                  </div>
                  <div style={{ fontSize: '0.72rem', color: textMuted, maxWidth: '420px', margin: '0 auto 12px auto' }}>
                    Puoi attivare un nuovo container sandbox isolato per il tuo progetto premendo il pulsante sopra o dalla scheda "Immagini Locali".
                  </div>
                  {isAvailable && (
                    <button
                      onClick={() => setShowLaunchForm(true)}
                      style={{
                        padding: '6px 14px',
                        borderRadius: '6px',
                        fontSize: '0.74rem',
                        fontWeight: 700,
                        background: '#0284c7',
                        color: '#ffffff',
                        border: 'none',
                        cursor: 'pointer'
                      }}
                    >
                      Avvia Primo Container Sandbox
                    </button>
                  )}
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {containers.map((c, i) => {
                    const cid = c.ID || c.id || '';
                    const isRunning = c.State === 'running' || (c.Status && c.Status.toLowerCase().startsWith('up'));
                    const isActing = actionLoading && actionLoading.includes(cid);

                    return (
                      <div 
                        key={cid || i}
                        style={{
                          padding: '12px 14px',
                          background: bgCard,
                          border: `1px solid ${isRunning ? 'rgba(34, 197, 94, 0.3)' : borderModal}`,
                          borderRadius: '8px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: '12px',
                          boxShadow: isRunning ? '0 2px 8px rgba(34, 197, 94, 0.05)' : 'none'
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0 }}>
                          <div style={{
                            width: '12px',
                            height: '12px',
                            borderRadius: '50%',
                            background: isRunning ? '#22c55e' : '#8b949e',
                            boxShadow: isRunning ? '0 0 8px #22c55e' : 'none',
                            flexShrink: 0
                          }} />
                          <div style={{ minWidth: 0 }}>
                            <div style={{ fontSize: '0.84rem', fontWeight: 800, color: textPrimary, display: 'flex', alignItems: 'center', gap: '8px' }}>
                              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {c.Names || cid.substring(0, 12)}
                              </span>
                              <span style={{
                                fontSize: '0.62rem',
                                padding: '1px 6px',
                                borderRadius: '4px',
                                fontWeight: 700,
                                background: isRunning ? 'rgba(34, 197, 94, 0.15)' : 'rgba(255, 255, 255, 0.06)',
                                color: isRunning ? '#22c55e' : textMuted
                              }}>
                                {isRunning ? 'ATTIVO' : 'ARRESTATO'}
                              </span>
                            </div>
                            <div style={{ fontSize: '0.68rem', color: textMuted, marginTop: '2px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              Immagine: <span style={{ color: '#00d2ff' }}>{c.Image}</span> • {c.Status}
                            </div>
                            {c.Ports && (
                              <div style={{ marginTop: '2px' }}>
                                <div style={{ fontSize: '0.64rem', color: '#38bdf8' }}>
                                  Porte: {c.Ports}
                                </div>
                                {isRunning && extractHostPorts(c.Ports).length > 0 && (
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '5px', marginTop: '4px', flexWrap: 'wrap' }}>
                                    {extractHostPorts(c.Ports).map(port => (
                                      <button
                                        key={port}
                                        type="button"
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          window.open(`http://localhost:${port}`, '_blank', 'noopener,noreferrer');
                                        }}
                                        title={`Apri applicazione su http://localhost:${port}`}
                                        style={{
                                          display: 'inline-flex',
                                          alignItems: 'center',
                                          gap: '4px',
                                          padding: '2px 8px',
                                          borderRadius: '4px',
                                          fontSize: '0.66rem',
                                          fontWeight: 700,
                                          background: 'rgba(56, 189, 248, 0.15)',
                                          border: '1px solid rgba(56, 189, 248, 0.4)',
                                          color: '#38bdf8',
                                          cursor: 'pointer',
                                          boxShadow: '0 1px 3px rgba(0,0,0,0.2)'
                                        }}
                                      >
                                        <ExternalLink size={10} />
                                        <span>Apri localhost:{port}</span>
                                      </button>
                                    ))}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        </div>

                        {/* Bottoni di Azione sul Container */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
                          {isRunning ? (
                            <>
                              {onSelectContainer && (
                                <button
                                  onClick={() => onSelectContainer(cid)}
                                  title="Esplora ed edita i file all'interno di questo container"
                                  style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '4px',
                                    padding: '4px 8px',
                                    borderRadius: '5px',
                                    fontSize: '0.68rem',
                                    fontWeight: 700,
                                    background: 'rgba(0, 210, 255, 0.12)',
                                    border: '1px solid rgba(0, 210, 255, 0.3)',
                                    color: '#00d2ff',
                                    cursor: 'pointer'
                                  }}
                                >
                                  <FolderOpen size={12} />
                                  <span>Sfoglia</span>
                                </button>
                              )}
                              <button
                                onClick={() => handleContainerAction('restart', cid)}
                                disabled={isActing}
                                title="Riavvia container"
                                style={{
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '4px',
                                  padding: '4px 8px',
                                  borderRadius: '5px',
                                  fontSize: '0.68rem',
                                  fontWeight: 600,
                                  background: 'transparent',
                                  border: `1px solid ${borderModal}`,
                                  color: textPrimary,
                                  cursor: 'pointer'
                                }}
                              >
                                <RotateCw size={12} style={{ animation: isActing ? 'spin 1s linear infinite' : 'none' }} />
                                <span>Riavvia</span>
                              </button>
                              <button
                                onClick={() => handleContainerAction('stop', cid)}
                                disabled={isActing}
                                title="Arresta container"
                                style={{
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '4px',
                                  padding: '4px 8px',
                                  borderRadius: '5px',
                                  fontSize: '0.68rem',
                                  fontWeight: 700,
                                  background: 'rgba(239, 68, 68, 0.12)',
                                  border: '1px solid rgba(239, 68, 68, 0.3)',
                                  color: '#ef4444',
                                  cursor: 'pointer'
                                }}
                              >
                                <Square size={12} />
                                <span>Ferma</span>
                              </button>
                            </>
                          ) : (
                            <button
                              onClick={() => handleContainerAction('start', cid)}
                              disabled={isActing}
                              title="Avvia ed attiva questo container"
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '5px',
                                padding: '5px 10px',
                                borderRadius: '5px',
                                fontSize: '0.70rem',
                                fontWeight: 700,
                                background: 'linear-gradient(135deg, #22c55e, #16a34a)',
                                border: 'none',
                                color: '#ffffff',
                                cursor: 'pointer',
                                boxShadow: '0 2px 6px rgba(34, 197, 94, 0.3)'
                              }}
                            >
                              <Play size={12} fill="#ffffff" />
                              <span>Avvia</span>
                            </button>
                          )}

                          <button
                            onClick={() => {
                              if (window.confirm(`Eliminare il container ${c.Names || cid}?`)) {
                                handleContainerAction('remove', cid);
                              }
                            }}
                            disabled={isActing}
                            title="Elimina container"
                            style={{
                              background: 'transparent',
                              border: 'none',
                              color: textMuted,
                              cursor: 'pointer',
                              padding: '4px'
                            }}
                            onMouseEnter={e => e.currentTarget.style.color = '#ef4444'}
                            onMouseLeave={e => e.currentTarget.style.color = textMuted}
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {activeTab === 'images' && (
            <div>
              <div style={{
                fontSize: '0.74rem',
                color: textMuted,
                marginBottom: '12px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between'
              }}>
                <span>Tutte le immagini presenti nel demone Docker locale. Clicca <strong>Lancia</strong> per avviare un container istantaneo con quell'immagine.</span>
                <span style={{ fontWeight: 700, color: textPrimary }}>Totale: {images.length}</span>
              </div>

              {images.length === 0 ? (
                <div style={{
                  padding: '36px 18px',
                  textAlign: 'center',
                  background: bgCard,
                  borderRadius: '8px',
                  border: `1px dashed ${borderModal}`
                }}>
                  <Layers size={32} color="#8b949e" style={{ margin: '0 auto 10px auto', display: 'block' }} />
                  <div style={{ fontSize: '0.84rem', fontWeight: 700, color: textPrimary }}>
                    Nessuna Immagine Trovata
                  </div>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {images.map((img, i) => {
                    const tag = `${img.Repository}:${img.Tag || 'latest'}`;
                    return (
                      <div 
                        key={img.ID || i}
                        style={{
                          padding: '10px 14px',
                          background: bgCard,
                          border: `1px solid ${borderModal}`,
                          borderRadius: '8px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: '12px'
                        }}
                      >
                        <div>
                          <div style={{ fontSize: '0.82rem', fontWeight: 800, color: textPrimary }}>
                            {img.Repository} <span style={{ color: '#38bdf8', fontWeight: 700 }}>:{img.Tag || 'latest'}</span>
                          </div>
                          <div style={{ fontSize: '0.66rem', color: textMuted, marginTop: '2px' }}>
                            ID: {img.ID?.substring(0, 12)} • Creata: {img.CreatedSince || img.CreatedAt} • Dimensione: <strong style={{ color: textPrimary }}>{img.Size}</strong>
                          </div>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <button
                            onClick={() => handleSaveSandboxImage(tag)}
                            title={`Usa ${tag} come immagine predefinita per l'esecuzione sandbox`}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: '4px',
                              padding: '4px 8px',
                              borderRadius: '6px',
                              fontSize: '0.68rem',
                              fontWeight: 600,
                              background: dockerData?.image === tag ? 'rgba(34, 197, 94, 0.15)' : 'rgba(255, 255, 255, 0.05)',
                              border: dockerData?.image === tag ? '1px solid rgba(34, 197, 94, 0.4)' : `1px solid ${borderModal}`,
                              color: dockerData?.image === tag ? '#22c55e' : textPrimary,
                              cursor: 'pointer'
                            }}
                          >
                            <ShieldCheck size={12} />
                            <span>{dockerData?.image === tag ? 'Sandbox Attiva' : 'Usa per Sandbox'}</span>
                          </button>
                          <button
                            onClick={() => handleSelectImageForLaunch(tag)}
                            title={`Lancia un container sandbox con ${tag}`}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: '4px',
                              padding: '4px 10px',
                              borderRadius: '6px',
                              fontSize: '0.70rem',
                              fontWeight: 700,
                              background: 'linear-gradient(135deg, #0284c7, #0ea5e9)',
                              border: 'none',
                              color: '#ffffff',
                              cursor: 'pointer',
                              boxShadow: '0 2px 6px rgba(2, 132, 199, 0.25)'
                            }}
                          >
                            <Rocket size={12} />
                            <span>Lancia Container</span>
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {activeTab === 'sandbox' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{
                padding: '14px',
                background: bgCard,
                borderRadius: '8px',
                border: `1px solid ${borderModal}`
              }}>
                <div style={{ fontSize: '0.80rem', fontWeight: 800, color: textPrimary, marginBottom: '6px' }}>
                  🌐 Mappatura Porte Dev-Server Automatiche
                </div>
                <div style={{ fontSize: '0.70rem', color: textMuted, marginBottom: '10px' }}>
                  Quando i container Docker sono attivi con rete, le seguenti porte host vengono inoltrate automaticamente all'ambiente locale:
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                  {(dockerData?.ports || ['3000:3000', '5000:5000', '5173:5173', '8080:8080']).map(p => {
                    const hostPort = p.split(':')[0] || p;
                    return (
                      <button 
                        key={p}
                        type="button"
                        onClick={() => window.open(`http://localhost:${hostPort}`, '_blank', 'noopener,noreferrer')}
                        title={`Apri http://localhost:${hostPort} nel browser`}
                        style={{
                          padding: '5px 12px',
                          borderRadius: '6px',
                          background: 'rgba(0, 210, 255, 0.12)',
                          border: '1px solid rgba(0, 210, 255, 0.35)',
                          fontSize: '0.72rem',
                          fontWeight: 700,
                          color: '#00d2ff',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                          cursor: 'pointer',
                          boxShadow: '0 2px 6px rgba(0, 210, 255, 0.15)',
                          transition: 'all 0.15s ease'
                        }}
                      >
                        <ExternalLink size={12} />
                        <span>Porta {p} (Apri Web)</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div style={{
                padding: '14px',
                background: bgCard,
                borderRadius: '8px',
                border: `1px solid ${borderModal}`
              }}>
                <div style={{ fontSize: '0.80rem', fontWeight: 800, color: textPrimary, marginBottom: '6px' }}>
                  ⚙️ Limiti Risorse Sandbox
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', fontSize: '0.72rem' }}>
                  <div style={{ color: textMuted }}>
                    Memoria RAM Massima: <strong style={{ color: textPrimary }}>{dockerData?.memory || '4g'}</strong>
                  </div>
                  <div style={{ color: textMuted }}>
                    CPU Allocate: <strong style={{ color: textPrimary }}>{dockerData?.cpus || '2'} Core</strong>
                  </div>
                  <div style={{ color: textMuted }}>
                    Rete Container: <strong style={{ color: dockerData?.network ? '#22c55e' : '#f59e0b' }}>
                      {dockerData?.network ? 'Attiva (Consigliata)' : 'Isolata'}
                    </strong>
                  </div>
                  <div style={{ color: textMuted }}>
                    Modalità Corrente: <strong style={{ color: isContainerMode ? '#38bdf8' : '#f59e0b' }}>
                      {isContainerMode ? '🐳 Container Docker' : '💻 Host Nativo'}
                    </strong>
                  </div>

                  <div style={{ gridColumn: '1 / -1', marginTop: '6px', paddingTop: '8px', borderTop: `1px dashed ${borderModal}` }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
                      <span style={{ color: textMuted, fontWeight: 700 }}>Immagine Base per i Task AI (Sandbox):</span>
                      <span style={{ fontSize: '0.66rem', color: '#38bdf8', fontWeight: 700 }}>{dockerData?.image || 'python:3.12-slim'}</span>
                    </div>
                    <select
                      value={dockerData?.image || 'python:3.12-slim'}
                      onChange={(e) => handleSaveSandboxImage(e.target.value)}
                      style={{
                        width: '100%',
                        padding: '6px 8px',
                        borderRadius: '6px',
                        border: `1px solid ${borderModal}`,
                        background: isLight ? '#ffffff' : '#0d1117',
                        color: textPrimary,
                        fontSize: '0.74rem',
                        cursor: 'pointer'
                      }}
                    >
                      {images.length > 0 && (
                        <optgroup label="Tutte le Immagini Locali Rilevate in Docker">
                          {images.map(img => {
                            const repo = img.Repository || '';
                            const tag = img.Tag || 'latest';
                            const fullTag = `${repo}:${tag}`;
                            return (
                              <option key={img.ID || fullTag} value={fullTag}>
                                {fullTag} ({img.Size || 'locale'})
                              </option>
                            );
                          })}
                        </optgroup>
                      )}
                      <optgroup label="Immagini Consigliate dal Kernel">
                        <option value="python:3.12-slim">python:3.12-slim (Default Python)</option>
                        <option value="nikolaik/python-nodejs:python3.12-nodejs22">nikolaik/python-nodejs:python3.12-nodejs22 (Fullstack)</option>
                        <option value="node:22-slim">node:22-slim (NodeJS / Frontend)</option>
                      </optgroup>
                    </select>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: '12px 18px',
          borderTop: `1px solid ${borderModal}`,
          background: isLight ? '#f6f8fa' : 'rgba(255,255,255,0.02)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          gap: '10px'
        }}>
          <button
            onClick={onClose}
            style={{
              padding: '6px 14px',
              borderRadius: '6px',
              fontSize: '0.74rem',
              fontWeight: 700,
              background: isLight ? '#e1e4e8' : 'rgba(255,255,255,0.1)',
              border: 'none',
              color: textPrimary,
              cursor: 'pointer'
            }}
          >
            Chiudi
          </button>
        </div>
      </div>
    </div>
  );
}
