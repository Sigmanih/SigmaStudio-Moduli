import React, { useState, useEffect, useCallback } from 'react';
import { Mail, Inbox, Send, Settings, Search, RefreshCw, Paperclip, Sparkles, X, CheckCircle2, AlertTriangle, User, Clock, ChevronLeft, ChevronRight, Trash2, Reply, Forward, Eye, EyeOff, Loader2 } from 'lucide-react';
import './styles/email-hub.css';

const API_BASE = '/api/email';

const PROVIDER_PRESETS = {
    gmail: { label: 'Gmail', imap_host: 'imap.gmail.com', imap_port: 993, smtp_host: 'smtp.gmail.com', smtp_port: 587 },
    outlook: { label: 'Outlook / Hotmail', imap_host: 'outlook.office365.com', imap_port: 993, smtp_host: 'smtp-mail.outlook.com', smtp_port: 587 },
    yahoo: { label: 'Yahoo Mail', imap_host: 'imap.mail.yahoo.com', imap_port: 993, smtp_host: 'smtp.mail.yahoo.com', smtp_port: 587 },
    custom: { label: 'Altro / Personalizzato', imap_host: '', imap_port: 993, smtp_host: '', smtp_port: 587 },
};

async function api(path, options = {}) {
    const res = await fetch(`${API_BASE}${path}`, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    });
    if (!res.ok) {
        let detail = `Errore HTTP ${res.status}`;
        try {
            const data = await res.json();
            detail = data.detail || data.error || detail;
        } catch { /* ignora */ }
        throw new Error(detail);
    }
    return res.json();
}

function formatDateTime(value) {
    if (!value) return '';
    try {
        const d = new Date(value);
        if (isNaN(d.getTime())) return value;
        return d.toLocaleString('it-IT', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch {
        return value;
    }
}

function extractAddress(from) {
    if (!from) return '';
    const match = from.match(/<([^>]+)>/);
    return match ? match[1] : from;
}

function getInitials(name) {
    if (!name) return '?';
    const parts = name.split(/[\s<>,]+/).filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return name.slice(0, 2).toUpperCase();
}

function sanitizeHtml(html) {
    // Rimuove script, iframe, object, embed e attributi on* per sicurezza
    if (!html) return '';
    const doc = new DOMParser().parseFromString(html, 'text/html');
    doc.querySelectorAll('script, iframe, object, embed, link, meta').forEach(el => el.remove());
    doc.querySelectorAll('*').forEach(el => {
        [...el.attributes].forEach(attr => {
            if (attr.name.startsWith('on') || (attr.name === 'href' && attr.value.trim().toLowerCase().startsWith('javascript:'))) {
                el.removeAttribute(attr.name);
            }
        });
    });
    return doc.body.innerHTML;
}

const EmailHub = () => {
    const [status, setStatus] = useState(null);
    const [messages, setMessages] = useState([]);
    const [selectedId, setSelectedId] = useState(null);
    const [messageDetail, setMessageDetail] = useState(null);
    const [searchQuery, setSearchQuery] = useState('');
    const [unreadOnly, setUnreadOnly] = useState(false);
    const [loadingInbox, setLoadingInbox] = useState(false);
    const [loadingMessage, setLoadingMessage] = useState(false);
    const [showComposer, setShowComposer] = useState(false);
    const [showSettings, setShowSettings] = useState(false);
    const [aiPanelOpen, setAiPanelOpen] = useState(false);
    const [aiDraft, setAiDraft] = useState('');
    const [aiLoading, setAiLoading] = useState(false);
    const [error, setError] = useState('');

    // Compositore
    const [composerTo, setComposerTo] = useState('');
    const [composerCc, setComposerCc] = useState('');
    const [composerSubject, setComposerSubject] = useState('');
    const [composerBody, setComposerBody] = useState('');
    const [composerHtml, setComposerHtml] = useState(false);
    const [sending, setSending] = useState(false);

    // Settings
    const [cfgProvider, setCfgProvider] = useState('gmail');
    const [cfgAddress, setCfgAddress] = useState('');
    const [cfgPassword, setCfgPassword] = useState('');
    const [showPassword, setShowPassword] = useState(false);
    const [cfgSmtpHost, setCfgSmtpHost] = useState(PROVIDER_PRESETS.gmail.smtp_host);
    const [cfgSmtpPort, setCfgSmtpPort] = useState(String(PROVIDER_PRESETS.gmail.smtp_port));
    const [cfgImapHost, setCfgImapHost] = useState(PROVIDER_PRESETS.gmail.imap_host);
    const [cfgImapPort, setCfgImapPort] = useState(String(PROVIDER_PRESETS.gmail.imap_port));
    const [demoMode, setDemoMode] = useState(false);
    const [savingConfig, setSavingConfig] = useState(false);

    const handleProviderChange = useCallback((providerKey) => {
        setCfgProvider(providerKey);
        const preset = PROVIDER_PRESETS[providerKey];
        if (preset.imap_host) setCfgImapHost(preset.imap_host);
        if (preset.smtp_host) setCfgSmtpHost(preset.smtp_host);
        setCfgImapPort(String(preset.imap_port));
        setCfgSmtpPort(String(preset.smtp_port));
    }, []);

    const loadConfig = useCallback(async () => {
        try {
            const data = await api('/config');
            if (data?.config) {
                const c = data.config;
                if (c.address) setCfgAddress(c.address);
                if (c.password) setCfgPassword(c.password);
                if (c.smtp_host) setCfgSmtpHost(c.smtp_host);
                if (c.smtp_port) setCfgSmtpPort(String(c.smtp_port));
                if (c.imap_host) setCfgImapHost(c.imap_host);
                if (c.imap_port) setCfgImapPort(String(c.imap_port));
            }
        } catch {
            // fallback silenzioso
        }
    }, []);

    const loadStatus = useCallback(async () => {
        try {
            const data = await api('/status');
            setStatus(data);
            if (data?.error) {
                setError(data.error);
            }
        } catch (e) {
            setStatus({ status: 'error', mode: 'unconfigured', configured: false, error: e.message });
        }
    }, []);

    const loadInbox = useCallback(async () => {
        setLoadingInbox(true);
        try {
            const params = new URLSearchParams({ limit: '50' });
            if (unreadOnly) params.set('unread_only', 'true');
            const data = await api(`/inbox?${params.toString()}`);
            if (data?.error) {
                setError(data.error);
            } else {
                setError('');
            }
            setMessages(data?.messages || []);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoadingInbox(false);
        }
    }, [unreadOnly]);

    const selectMessage = useCallback(async (msg) => {
        setSelectedId(msg.id);
        setMessageDetail(null);
        setLoadingMessage(true);
        try {
            const data = await api(`/message/${encodeURIComponent(msg.id)}`);
            setMessageDetail(data.message);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoadingMessage(false);
        }
    }, []);

    const handleSend = useCallback(async () => {
        if (!composerTo || !composerSubject || !composerBody) {
            setError('Compila destinatario, oggetto e corpo.');
            return;
        }
        setSending(true);
        setError('');
        try {
            await api('/send', {
                method: 'POST',
                body: JSON.stringify({ to: composerTo, cc: composerCc, subject: composerSubject, body: composerBody, html: composerHtml }),
            });
            setShowComposer(false);
            setComposerTo(''); setComposerCc(''); setComposerSubject(''); setComposerBody('');
            loadInbox();
        } catch (e) {
            setError(e.message);
        } finally {
            setSending(false);
        }
    }, [composerTo, composerCc, composerSubject, composerBody, composerHtml, loadInbox]);

    const handleAiDraft = useCallback(async () => {
        if (!composerBody && !composerSubject) {
            setError("Scrivi un po' di contesto per la bozza AI.");
            return;
        }
        setAiLoading(true);
        setError('');
        try {
            const data = await api('/ai-draft', {
                method: 'POST',
                body: JSON.stringify({ context: composerBody || composerSubject, tone: 'professionale', action: 'draft' }),
            });
            setAiDraft(data.draft);
            setAiPanelOpen(true);
        } catch (e) {
            setError(e.message);
        } finally {
            setAiLoading(false);
        }
    }, [composerBody, composerSubject]);

    const handleSaveConfig = useCallback(async () => {
        setSavingConfig(true);
        setError('');
        try {
            await api('/config', {
                method: 'POST',
                body: JSON.stringify({
                    address: cfgAddress, password: cfgPassword,
                    smtp_host: cfgSmtpHost, smtp_port: Number(cfgSmtpPort),
                    imap_host: cfgImapHost, imap_port: Number(cfgImapPort),
                    demo_mode: demoMode,
                }),
            });
            setShowSettings(false);
            loadStatus();
            loadInbox();
        } catch (e) {
            setError(e.message);
        } finally {
            setSavingConfig(false);
        }
    }, [cfgAddress, cfgPassword, cfgSmtpHost, cfgSmtpPort, cfgImapHost, cfgImapPort, demoMode, loadStatus, loadInbox]);

    useEffect(() => { loadStatus(); }, [loadStatus]);
    useEffect(() => { if (status?.configured) loadInbox(); }, [status, loadInbox]);

    const filteredMessages = messages.filter(m => {
        if (!searchQuery) return true;
        const q = searchQuery.toLowerCase();
        return (m.from || '').toLowerCase().includes(q) || (m.subject || '').toLowerCase().includes(q);
    });

    const statusBadge = () => {
        if (!status) return <span className="email-badge email-badge-loading">Caricamento...</span>;
        if (status.configured) {
            const addr = status.address ? ` (${status.address})` : '';
            return <span className="email-badge email-badge-ok">Connesso{addr}</span>;
        }
        return <span className="email-badge email-badge-off">Non configurato</span>;
    };

    return (
        <div className="email-hub-container">
            <header className="email-header">
                <div className="email-header-left">
                    <Mail size={20} />
                    <h2>Email Hub</h2>
                    {statusBadge()}
                </div>
                <div className="email-header-actions">
                    <button className="email-btn" onClick={() => { setShowSettings(true); loadConfig(); }} title="Configurazione Account">
                        <Settings size={16} /> Configura Account
                    </button>
                    <button className="email-btn email-btn-primary" onClick={() => setShowComposer(true)}>
                        <Send size={16} /> Componi
                    </button>
                </div>
            </header>

            {error && (
                <div className="email-alert email-alert-error">
                    <AlertTriangle size={16} />
                    <span>{error}</span>
                    <button onClick={() => setError('')}><X size={14} /></button>
                </div>
            )}

            <div className="email-main">
                <aside className="email-sidebar" style={{ display: 'flex', flexDirection: 'column' }}>
                    <div className="email-folder active">
                        <Inbox size={16} />
                        <span>Inbox</span>
                        <span className="email-unread-count">{messages.filter(m => m.unread).length}</span>
                    </div>
                    <label className="email-filter-label">
                        <input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} />
                        Solo non letti
                    </label>

                    <div style={{ marginTop: 'auto', paddingTop: '16px', borderTop: '1px solid var(--border-color, rgba(255,255,255,0.08))' }}>
                        <button 
                            className="email-btn" 
                            onClick={() => { setShowSettings(true); loadConfig(); }}
                            style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', fontSize: '0.78rem' }}
                        >
                            <Settings size={14} /> Configura Account
                        </button>
                    </div>
                </aside>

                <section className="email-list-panel">
                    <div className="email-search-bar">
                        <Search size={16} />
                        <input
                            type="text"
                            placeholder="Cerca mittente o oggetto..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                        />
                        <button onClick={loadInbox} disabled={loadingInbox}>
                            {loadingInbox ? <Loader2 size={16} className="spin" /> : <RefreshCw size={16} />}
                        </button>
                    </div>
                    <div className="email-message-list">
                        {filteredMessages.length === 0 && !loadingInbox && (
                            <div className="email-empty" style={{ padding: '24px', textAlign: 'center' }}>
                                <p style={{ margin: '0 0 10px 0', fontWeight: 600 }}>Nessun messaggio presente</p>
                                {!status?.configured && (
                                    <div style={{ marginTop: '8px' }}>
                                        <p style={{ margin: '0 0 12px 0', fontSize: '0.8rem', color: '#94a3b8' }}>
                                            Nessun account email configurato. Inserisci le tue credenziali IMAP/SMTP per leggere e inviare email.
                                        </p>
                                        <button className="email-btn email-btn-primary" onClick={() => { setShowSettings(true); loadConfig(); }} style={{ margin: '0 auto' }}>
                                            <Settings size={14} /> Configura Account Email
                                        </button>
                                    </div>
                                )}
                            </div>
                        )}
                        {filteredMessages.map(msg => (
                            <div
                                key={msg.id}
                                className={`email-item ${selectedId === msg.id ? 'active' : ''} ${msg.unread ? 'unread' : ''}`}
                                onClick={() => selectMessage(msg)}
                            >
                                <div className="email-avatar">{getInitials(msg.from)}</div>
                                <div className="email-item-body">
                                    <div className="email-item-top">
                                        <span className="email-sender">{msg.from}</span>
                                        <span className="email-date">{formatDateTime(msg.date)}</span>
                                    </div>
                                    <div className="email-subject">{msg.subject}</div>
                                    <div className="email-snippet">{msg.snippet || msg.preview || ''}</div>
                                </div>
                                {msg.unread && <span className="email-dot" />}
                            </div>
                        ))}
                    </div>
                </section>

                <section className="email-viewer-panel">
                    {!messageDetail && !loadingMessage && (
                        <div className="email-viewer-empty">
                            <Mail size={48} />
                            <p>Seleziona un messaggio per leggerlo</p>
                        </div>
                    )}
                    {loadingMessage && (
                        <div className="email-loading"><Loader2 size={32} className="spin" /></div>
                    )}
                    {messageDetail && (
                        <div className="email-message-detail">
                            <header className="email-msg-header">
                                <h3>{messageDetail.subject}</h3>
                                <div className="email-msg-meta">
                                    <span><User size={14} /> {messageDetail.from}</span>
                                    <span><Clock size={14} /> {formatDateTime(messageDetail.date)}</span>
                                </div>
                            </header>
                            <div className="email-msg-actions">
                                <button className="email-btn" onClick={() => { setComposerTo(extractAddress(messageDetail.from)); setComposerSubject(`Re: ${messageDetail.subject}`); setShowComposer(true); }}>
                                    <Reply size={14} /> Rispondi
                                </button>
                                <button className="email-btn" onClick={() => { setComposerTo(''); setComposerSubject(`Fwd: ${messageDetail.subject}`); setShowComposer(true); }}>
                                    <Forward size={14} /> Inoltra
                                </button>
                                <button className="email-btn email-btn-danger">
                                    <Trash2 size={14} /> Elimina
                                </button>
                            </div>
                            <div className="email-msg-body" dangerouslySetInnerHTML={{ __html: sanitizeHtml(messageDetail.body_html) }} />
                            {messageDetail.attachments?.length > 0 && (
                                <footer className="email-attachments">
                                    <Paperclip size={14} />
                                    {messageDetail.attachments.map((a, i) => (
                                        <span key={i} className="email-attachment">{a.name} ({(a.size / 1024).toFixed(1)} KB)</span>
                                    ))}
                                </footer>
                            )}
                        </div>
                    )}
                </section>
            </div>

            {showComposer && (
                <div className="email-modal-overlay" onClick={() => setShowComposer(false)}>
                    <div className="email-modal" onClick={(e) => e.stopPropagation()}>
                        <header className="email-modal-header">
                            <h3>Componi email</h3>
                            <button onClick={() => setShowComposer(false)}><X size={18} /></button>
                        </header>
                        <div className="email-composer-body">
                            <label>To <input value={composerTo} onChange={(e) => setComposerTo(e.target.value)} placeholder="destinatario@esempio.it" /></label>
                            <label>Cc <input value={composerCc} onChange={(e) => setComposerCc(e.target.value)} placeholder="copia@esempio.it (opzionale)" /></label>
                            <label>Oggetto <input value={composerSubject} onChange={(e) => setComposerSubject(e.target.value)} placeholder="Oggetto" /></label>
                            <div className="email-composer-toolbar">
                                <button className={`email-btn ${composerHtml ? 'active' : ''}`} onClick={() => setComposerHtml(!composerHtml)}>
                                    <Eye size={14} /> HTML
                                </button>
                                <button className="email-btn" onClick={handleAiDraft} disabled={aiLoading}>
                                    {aiLoading ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />} Migliora con AI
                                </button>
                            </div>
                            <textarea
                                rows={12}
                                value={composerBody}
                                onChange={(e) => setComposerBody(e.target.value)}
                                placeholder="Scrivi il tuo messaggio..."
                            />
                        </div>
                        {aiPanelOpen && (
                            <div className="email-ai-panel">
                                <header>
                                    <Sparkles size={14} /> Bozza AI
                                    <button onClick={() => setAiPanelOpen(false)}><X size={14} /></button>
                                </header>
                                <textarea rows={6} value={aiDraft} onChange={(e) => setAiDraft(e.target.value)} />
                                <button className="email-btn email-btn-primary" onClick={() => { setComposerBody(aiDraft); setAiPanelOpen(false); }}>
                                    <CheckCircle2 size={14} /> Usa questa bozza
                                </button>
                            </div>
                        )}
                        <footer className="email-modal-footer">
                            <button className="email-btn" onClick={() => setShowComposer(false)}>Annulla</button>
                            <button className="email-btn email-btn-primary" onClick={handleSend} disabled={sending}>
                                {sending ? <Loader2 size={14} className="spin" /> : <Send size={14} />} Invia
                            </button>
                        </footer>
                    </div>
                </div>
            )}

            {showSettings && (
                <div className="email-modal-overlay" onClick={() => setShowSettings(false)}>
                    <div className="email-modal email-settings-modal" onClick={(e) => e.stopPropagation()}>
                        <header className="email-modal-header">
                            <h3>Configurazione Email</h3>
                            <button onClick={() => setShowSettings(false)}><X size={18} /></button>
                        </header>
                        <div className="email-settings-body">
                            <label>Provider
                                <select value={cfgProvider} onChange={(e) => handleProviderChange(e.target.value)}>
                                    {Object.entries(PROVIDER_PRESETS).map(([key, preset]) => (
                                        <option key={key} value={key}>{preset.label}</option>
                                    ))}
                                </select>
                            </label>
                            <label>Indirizzo email 
                                <input type="email" value={cfgAddress} onChange={(e) => setCfgAddress(e.target.value)} placeholder="tu@esempio.it" />
                            </label>
                            <label>Password / App Password
                                <div style={{ position: 'relative', display: 'flex', alignItems: 'center', width: '100%' }}>
                                    <input 
                                        type={showPassword ? 'text' : 'password'} 
                                        value={cfgPassword} 
                                        onChange={(e) => setCfgPassword(e.target.value)} 
                                        placeholder="es. password per app Gmail o password account" 
                                        style={{ paddingRight: '40px', width: '100%' }}
                                    />
                                    <button
                                        type="button"
                                        onClick={() => setShowPassword(prev => !prev)}
                                        title={showPassword ? "Nascondi password" : "Mostra password (Inspect)"}
                                        style={{
                                            position: 'absolute',
                                            right: '8px',
                                            background: 'transparent',
                                            border: 'none',
                                            color: '#94a3b8',
                                            cursor: 'pointer',
                                            display: 'flex',
                                            alignItems: 'center',
                                            padding: '4px'
                                        }}
                                    >
                                        {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                                    </button>
                                </div>
                            </label>
                            <div className="email-row">
                                <label>SMTP Host <input value={cfgSmtpHost} onChange={(e) => setCfgSmtpHost(e.target.value)} placeholder="smtp.gmail.com" /></label>
                                <label>Porta SMTP <input type="number" value={cfgSmtpPort} onChange={(e) => setCfgSmtpPort(e.target.value)} /></label>
                            </div>
                            <div className="email-row">
                                <label>IMAP Host <input value={cfgImapHost} onChange={(e) => setCfgImapHost(e.target.value)} placeholder="imap.gmail.com" /></label>
                                <label>Porta IMAP <input type="number" value={cfgImapPort} onChange={(e) => setCfgImapPort(e.target.value)} /></label>
                            </div>
                            <p className="email-settings-hint">
                                Per Gmail: usa una password per app (non la password principale).<br />
                                Per Outlook: se richiesto, abilita l'accesso IMAP nelle impostazioni del conto Microsoft.<br />
                                La connessione usa TLS/STARTTLS sulle porte standard (993 IMAP, 587 SMTP).
                            </p>
                        </div>
                        <footer className="email-modal-footer">
                            <button className="email-btn" onClick={() => setShowSettings(false)}>Annulla</button>
                            <button className="email-btn email-btn-primary" onClick={handleSaveConfig} disabled={savingConfig}>
                                {savingConfig ? <Loader2 size={14} className="spin" /> : <CheckCircle2 size={14} />} Salva
                            </button>
                        </footer>
                    </div>
                </div>
            )}
        </div>
    );
};

export default EmailHub;
