import React, { useState, useMemo, useEffect } from 'react';
import { 
  Plus, Edit, PlusCircle, CheckCircle2, Clock, ChevronRight, ChevronLeft, Trash2, 
  AlertCircle, Filter, X, FileText, BookOpen, Terminal, PieChart, Calendar, History,
  ListTodo, Activity, Check, Sparkles, Search, FileCode, Tag, User, Cpu, RefreshCw, Layers
} from 'lucide-react';
import { useApp } from '../../contexts/AppContext';

// â”€â”€ Shared style tokens (crema / dark) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const getThemeTokens = (isLight) => ({
  bg:         isLight ? '#f7f4ed' : '#090a0f',
  cardBg:     isLight ? '#fffdf9' : '#11131b',
  cardHover:  isLight ? '#f2ede2' : '#0e1016',
  border:     isLight ? 'rgba(190, 160, 110, 0.35)' : '#1e2030',
  divider:    isLight ? 'rgba(190, 160, 110, 0.22)' : 'rgba(255,255,255,0.06)',
  tabBg:      isLight ? 'rgba(190, 160, 110, 0.12)' : 'rgba(255,255,255,0.03)',
  tabBorder:  isLight ? 'rgba(190, 160, 110, 0.3)' : 'rgba(255,255,255,0.08)',
  text:       isLight ? '#111111' : '#e2e4eb',
  muted:      isLight ? '#2e2820' : '#8b8fa3',
  dim:        isLight ? '#8a8174' : '#5a5e72',
  navBg:      isLight ? 'rgba(190, 160, 110, 0.14)' : '#1e2030',
  navBorder:  isLight ? 'rgba(190, 160, 110, 0.35)' : 'none',
  navText:    isLight ? '#111111' : '#e2e4eb'
});

// ==============================================================================
// RoadmapView (Pianificazione & Audit Trail)
// Calendario AttivitÃ , Kanban Task, Audit Log & Registro Modifiche AI
// ==============================================================================

export default function RoadmapView({ tasks, onEdit, onAdd, onDelete, onToggleStatus, onOpenFile, onClearAll }) {
  const { theme } = useApp();
  const isThemeLight = theme === 'light';
  const T = useMemo(() => getThemeTokens(isThemeLight), [isThemeLight]);
  const [activeTab, setActiveTab] = useState('calendar'); // 'calendar' | 'kanban' | 'audit'
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterModule, setFilterModule] = useState('all');
  
  // Calendar state
  const [currentDate, setCurrentDate] = useState(new Date());
  const [selectedDay, setSelectedDay] = useState(new Date().getDate());

  // Audit log mock / local data
  const [auditLogs, setAuditLogs] = useState([]);

  useEffect(() => {
    // Generate/Load system audit logs from localStorage or recent activity
    try {
      const logs = [];
      const chatSessions = localStorage.getItem('sigma_chat_sessions');
      if (chatSessions) {
        const parsed = JSON.parse(chatSessions);
        if (Array.isArray(parsed)) {
          parsed.forEach(s => {
            logs.push({
              id: `chat-${s.id || s.timestamp}`,
              type: 'chat',
              title: `Sessione Chat: ${s.title || 'Nuova Conversazione'}`,
              timestamp: s.timestamp || Date.now(),
              dateStr: new Date(s.timestamp || Date.now()).toISOString().split('T')[0],
              actor: 'Utente / Assistente AI',
              details: `${s.messages?.length || 0} messaggi scambiati`
            });
          });
        }
      }

      // Add task events to audit log
      tasks.forEach(t => {
        logs.push({
          id: `task-${t.id}`,
          type: 'task',
          title: `Task: ${t.titolo}`,
          timestamp: t.timestamp || Date.now(),
          dateStr: new Date(t.timestamp || Date.now()).toISOString().split('T')[0],
          actor: t.autore || 'Sistema / Utente',
          details: `Stato: ${t.status?.toUpperCase() || 'IN CORSO'} â€¢ PrioritÃ : ${t.priorita || 'media'}`
        });
      });

      logs.sort((a, b) => b.timestamp - a.timestamp);
      setAuditLogs(logs);
    } catch (e) {
      console.error('Failed to parse audit logs:', e);
    }
  }, [tasks]);

  const year = currentDate.getFullYear();
  const month = currentDate.getMonth();

  const monthNames = [
    'Gennaio', 'Febbraio', 'Marzo', 'Aprile', 'Maggio', 'Giugno',
    'Luglio', 'Agosto', 'Settembre', 'Ottobre', 'Novembre', 'Dicembre'
  ];

  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const firstDayIndex = (new Date(year, month, 1).getDay() + 6) % 7; // Monday = 0

  const prevMonth = () => setCurrentDate(new Date(year, month - 1, 1));
  const nextMonth = () => setCurrentDate(new Date(year, month + 1, 1));

  const selectedDateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(selectedDay).padStart(2, '0')}`;

  // Get events for specific day
  const getDayEvents = (dayNum) => {
    const dStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(dayNum).padStart(2, '0')}`;
    const dayTasks = tasks.filter(t => {
      if (!t.timestamp) return false;
      return new Date(t.timestamp).toISOString().split('T')[0] === dStr;
    });
    const dayAudits = auditLogs.filter(a => a.dateStr === dStr);
    return { dayTasks, dayAudits, total: dayTasks.length + dayAudits.length };
  };

  const selectedEvents = useMemo(() => getDayEvents(selectedDay), [selectedDay, month, year, tasks, auditLogs]);

  const modules = useMemo(() => {
    const mods = new Set();
    tasks.forEach(t => (t.moduli || []).forEach(m => mods.add(m)));
    return ['all', ...Array.from(mods).sort()];
  }, [tasks]);

  const filteredTasks = useMemo(() => {
    return tasks.filter(t => {
      if (filterStatus !== 'all' && t.status !== filterStatus) return false;
      if (filterModule !== 'all' && !(t.moduli || []).includes(filterModule)) return false;
      return true;
    });
  }, [tasks, filterStatus, filterModule]);

  const stats = useMemo(() => {
    const total = tasks.length;
    const done = tasks.filter(t => t.status === 'done').length;
    const inCorso = tasks.filter(t => t.status === 'in_corso').length;
    const blocked = tasks.filter(t => t.status === 'blocked').length;
    return { total, done, inCorso, blocked, progress: total > 0 ? Math.round((done / total) * 100) : 0 };
  }, [tasks]);

  const priorityColors = {
    critica: { bg: 'rgba(255,85,85,0.15)', color: '#ff5555', label: 'Critica' },
    alta: { bg: 'rgba(255,184,108,0.15)', color: '#ffb86c', label: 'Alta' },
    media: { bg: 'rgba(0,210,255,0.12)', color: '#00d2ff', label: 'Media' },
    bassa: { bg: 'rgba(148,148,165,0.12)', color: '#9494a5', label: 'Bassa' },
  };

  const statusIcons = {
    done: <CheckCircle2 size={16} color="#3fb950" />,
    in_corso: <Clock size={16} color="#00d2ff" />,
    blocked: <AlertCircle size={16} color="#ff5555" />,
  };

  const statusLabels = {
    done: 'Completato',
    in_corso: 'In Corso',
    blocked: 'Bloccato',
  };

  const getFileIcon = (type) => {
    switch (type) {
      case 'scripts': return <Terminal size={14} />;
      case 'viz': return <PieChart size={14} />;
      case 'whitepaper': return <BookOpen size={14} />;
      default: return <FileText size={14} />;
    }
  };

  return (
    <div className="roadmap-view" style={{ height: '100%', display: 'flex', flexDirection: 'column', padding: 0, background: T.bg, color: T.text, boxSizing: 'border-box', overflow: 'hidden' }}>
      
      {/* Hero Visual Banner with Standardized Theme System & Dimensions */}
      <div style={{
        position: 'relative',
        borderRadius: 0,
        overflow: 'hidden',
        padding: '24px 32px',
        minHeight: '110px',
        borderBottom: theme === 'light' ? '1px solid rgba(234, 88, 12, 0.35)' : '1px solid rgba(0, 210, 255, 0.25)',
        boxShadow: theme === 'light' ? '0 8px 24px rgba(234, 88, 12, 0.08)' : '0 8px 32px rgba(0,0,0,0.4)',
        backgroundImage: theme === 'light'
          ? 'linear-gradient(135deg, rgba(254, 252, 247, 0.76) 0%, rgba(248, 242, 232, 0.70) 100%), url("/images/roadmap_plan_banner.jpg")'
          : 'linear-gradient(135deg, rgba(10, 14, 26, 0.85) 0%, rgba(14, 22, 42, 0.80) 100%), url("/images/roadmap_plan_banner.jpg")',
        backgroundSize: 'cover',
        backgroundRepeat: 'no-repeat',
        backgroundPosition: 'center center',
        marginBottom: '20px',
        flexShrink: 0
      }}>
        <div style={{ position: 'relative', zIndex: 2, display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '16px' }}>
          <div style={{ maxWidth: '680px' }}>
            <div style={{
              display: 'inline-flex', alignItems: 'center', gap: '6px',
              padding: '3px 12px', borderRadius: '14px',
              background: theme === 'light' ? 'rgba(234, 88, 12, 0.12)' : 'rgba(0, 210, 255, 0.15)', 
              border: theme === 'light' ? '1px solid rgba(234, 88, 12, 0.35)' : '1px solid rgba(0, 210, 255, 0.35)',
              color: theme === 'light' ? '#ea580c' : '#00d2ff', 
              fontSize: '0.68rem', fontWeight: 800, letterSpacing: '1px', textTransform: 'uppercase', marginBottom: '6px'
            }}>
              <Calendar size={14} /> SYSTEM ROADMAP & DEVELOPMENT MILESTONES
            </div>
            <h1 style={{ margin: '0 0 6px 0', fontSize: '1.4rem', fontWeight: 800, color: theme === 'light' ? '#111111' : '#fff', letterSpacing: '-0.3px', textShadow: 'none' }}>
              ðŸ—“ï¸ Pianificazione & <span style={{
                color: theme === 'light' ? '#c2410c' : '#00d2ff',
                fontWeight: 800
              }}>Roadmap di Sviluppo</span>
            </h1>
            <p style={{ margin: 0, fontSize: '0.82rem', color: theme === 'light' ? '#4b5563' : '#cbd5e0', lineHeight: 1.45 }}>
              Calendario AttivitÃ , Kanban Task, Registro Modifiche AI e Controllo Esecuzioni.
            </p>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            {tasks.length > 1 && (
              <button 
                onClick={() => {
                  if (confirm(`Eliminare TUTTI i ${tasks.length} task? Opera irreversibile.`)) {
                    onClearAll && onClearAll();
                  }
                }} 
                style={{
                  display: 'flex', alignItems: 'center', gap: '6px', padding: '10px 16px', borderRadius: '12px',
                  fontSize: '0.82rem', fontWeight: 800, background: 'rgba(255,85,85,0.15)', border: '1px solid rgba(255,85,85,0.35)',
                  color: '#ff5555', cursor: 'pointer'
                }}
              >
                <Trash2 size={15} /> Cancella Tutti
              </button>
            )}
            <button 
              onClick={onAdd} 
              style={{
                display: 'flex', alignItems: 'center', gap: '6px', padding: '10px 18px', borderRadius: '12px',
                fontSize: '0.82rem', fontWeight: 800, background: 'linear-gradient(135deg, #00d2ff, #0072ff)',
                border: 'none', color: '#fff', cursor: 'pointer', boxShadow: '0 4px 14px rgba(0,210,255,0.25)'
              }}
            >
              <Plus size={16} /> Nuovo Task
            </button>
          </div>
        </div>
      </div>

      {/* Main Workspace Body Wrapper */}
      <div style={{ padding: '0 24px 16px 24px', display: 'flex', flexDirection: 'column', gap: '12px', flex: 1, minHeight: 0 }}>

      {/* 2. STATS WIDGETS BAR â€” COMPACT & MODERN */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '8px', marginBottom: '8px', flexShrink: 0 }}>
        <div style={{ background: T.cardBg, border: `1px solid ${T.border}`, borderRadius: '10px', padding: '10px 14px', display: 'flex', alignItems: 'center', gap: '10px', boxShadow: '0 2px 8px rgba(0,0,0,0.08)' }}>
          <span style={{ fontSize: '1.4rem' }}>ðŸ“‹</span>
          <div><span style={{ fontSize: '0.62rem', color: T.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', display: 'block' }}>Totale</span><span style={{ fontSize: '1.2rem', fontWeight: 700, color: T.text }}>{stats.total}</span></div>
        </div>
        <div style={{ background: T.cardBg, border: `1px solid ${T.border}`, borderRadius: '10px', padding: '10px 14px', display: 'flex', alignItems: 'center', gap: '10px', boxShadow: '0 2px 8px rgba(0,0,0,0.08)' }}>
          <span style={{ fontSize: '1.4rem' }}>âœ…</span>
          <div><span style={{ fontSize: '0.62rem', color: '#3fb950', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', display: 'block' }}>Completati {stats.progress}%</span><span style={{ fontSize: '1.2rem', fontWeight: 700, color: '#3fb950' }}>{stats.done}</span></div>
        </div>
        <div style={{ background: T.cardBg, border: `1px solid ${T.border}`, borderRadius: '10px', padding: '10px 14px', display: 'flex', alignItems: 'center', gap: '10px', boxShadow: '0 2px 8px rgba(0,0,0,0.08)' }}>
          <span style={{ fontSize: '1.4rem' }}>âš¡</span>
          <div><span style={{ fontSize: '0.62rem', color: '#00d2ff', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', display: 'block' }}>In Corso</span><span style={{ fontSize: '1.2rem', fontWeight: 700, color: '#00d2ff' }}>{stats.inCorso}</span></div>
        </div>
        <div style={{ background: T.cardBg, border: `1px solid ${T.border}`, borderRadius: '10px', padding: '10px 14px', display: 'flex', alignItems: 'center', gap: '10px', boxShadow: '0 2px 8px rgba(0,0,0,0.08)' }}>
          <span style={{ fontSize: '1.4rem' }}>ðŸ“œ</span>
          <div><span style={{ fontSize: '0.62rem', color: '#bc8cff', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', display: 'block' }}>Registro</span><span style={{ fontSize: '1.2rem', fontWeight: 700, color: '#bc8cff' }}>{auditLogs.length}</span></div>
        </div>
      </div>

      {/* 3. SUB-TAB SWITCHER */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '8px', borderBottom: `1px solid ${T.divider}`, paddingBottom: '8px', flexShrink: 0 }}>
        <button
          onClick={() => setActiveTab('calendar')}
          style={{
            display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 16px', borderRadius: '8px',
            fontSize: '0.78rem', fontWeight: 700, cursor: 'pointer',
            background: activeTab === 'calendar' ? 'rgba(0, 210, 255, 0.15)' : T.tabBg,
            border: activeTab === 'calendar' ? '1px solid rgba(0, 210, 255, 0.4)' : `1px solid ${T.tabBorder}`,
            color: activeTab === 'calendar' ? '#00d2ff' : T.muted,
            transition: 'all 0.2s ease'
          }}
        >
          <Calendar size={15} />
          <span>ðŸ“… Calendario & Timeline</span>
        </button>
        <button
          onClick={() => setActiveTab('kanban')}
          style={{
            display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 16px', borderRadius: '8px',
            fontSize: '0.78rem', fontWeight: 700, cursor: 'pointer',
            background: activeTab === 'kanban' ? 'rgba(188, 140, 255, 0.15)' : T.tabBg,
            border: activeTab === 'kanban' ? '1px solid rgba(188, 140, 255, 0.4)' : `1px solid ${T.tabBorder}`,
            color: activeTab === 'kanban' ? '#bc8cff' : T.muted,
            transition: 'all 0.2s ease'
          }}
        >
          <ListTodo size={15} />
          <span>ðŸ“‹ Gestione Task ({tasks.length})</span>
        </button>
        <button
          onClick={() => setActiveTab('audit')}
          style={{
            display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 16px', borderRadius: '8px',
            fontSize: '0.78rem', fontWeight: 700, cursor: 'pointer',
            background: activeTab === 'audit' ? 'rgba(63, 185, 80, 0.15)' : T.tabBg,
            border: activeTab === 'audit' ? '1px solid rgba(63, 185, 80, 0.4)' : `1px solid ${T.tabBorder}`,
            color: activeTab === 'audit' ? '#3fb950' : T.muted,
            transition: 'all 0.2s ease'
          }}
        >
          <History size={15} />
          <span>ðŸ“œ Registro Modifiche ({auditLogs.length})</span>
        </button>
      </div>

      {/* TAB 1: CALENDARIO INTERATTIVO */}
      {activeTab === 'calendar' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', flex: 1, minHeight: 0 }}>
          
          {/* Griglia Calendario Mensile */}
          <div style={{ background: T.cardBg, border: `1px solid ${T.border}`, borderRadius: '12px', padding: '14px', display: 'flex', flexDirection: 'column', gap: '10px', boxShadow: '0 2px 12px rgba(0,0,0,0.06)' }}>
            
            {/* Header Mese & Navigazione */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: `1px solid ${T.divider}`, paddingBottom: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Calendar size={18} style={{ color: '#00d2ff' }} />
                <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 700, color: T.text }}>
                  {monthNames[month]} {year}
                </h3>
                <span style={{ fontSize: '0.65rem', padding: '3px 10px', borderRadius: '12px', background: 'rgba(63,185,80,0.12)', border: '1px solid rgba(63,185,80,0.25)', color: '#3fb950', fontWeight: 700 }}>
                  ðŸŽ¯ Task Completati: {stats.done} / {stats.total} ({stats.progress}%)
                </span>
              </div>
              <div style={{ display: 'flex', gap: '6px' }}>
                <button onClick={prevMonth} style={{ background: T.navBg, border: `1px solid ${T.navBorder}`, color: T.navText, borderRadius: '6px', padding: '6px 10px', cursor: 'pointer' }}>
                  <ChevronLeft size={14} />
                </button>
                <button onClick={() => setCurrentDate(new Date())} style={{ background: 'rgba(0,210,255,0.1)', border: '1px solid rgba(0,210,255,0.2)', color: '#00d2ff', borderRadius: '6px', padding: '4px 10px', fontSize: '0.72rem', fontWeight: 600, cursor: 'pointer' }}>
                  Oggi
                </button>
                <button onClick={nextMonth} style={{ background: T.navBg, border: `1px solid ${T.navBorder}`, color: T.navText, borderRadius: '6px', padding: '6px 10px', cursor: 'pointer' }}>
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>

          {/* Giorni della Settimana */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', textAlign: 'center', fontSize: '0.65rem', fontWeight: 700, color: T.muted, paddingBottom: '2px' }}>
              <span>Lun</span><span>Mar</span><span>Mer</span><span>Gio</span><span>Ven</span><span>Sab</span><span>Dom</span>
            </div>

            {/* Griglia Giorni */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '3px', flex: 1 }}>
              {Array.from({ length: firstDayIndex }).map((_, i) => (
                <div key={`empty-${i}`} style={{ background: 'transparent', borderRadius: '8px' }} />
              ))}
              {Array.from({ length: daysInMonth }).map((_, i) => {
                const dayNum = i + 1;
                const isSelected = selectedDay === dayNum;
                const isToday = new Date().getDate() === dayNum && new Date().getMonth() === month && new Date().getFullYear() === year;
                const events = getDayEvents(dayNum);
                const dayDoneTasks = events.dayTasks.filter(t => t.status === 'done').length;
                const dayTotalTasks = events.dayTasks.length;
                
                return (
                  <div
                    key={dayNum}
                    onClick={() => setSelectedDay(dayNum)}
                    style={{
                      background: isSelected ? 'rgba(0, 210, 255, 0.15)' : T.cardHover,
                      border: isSelected ? '1px solid #00d2ff' : (isToday ? '1px solid rgba(188, 140, 255, 0.5)' : `1px solid ${T.border}`),
                      borderRadius: '6px',
                      padding: '4px 5px',
                      minHeight: '32px',
                      display: 'flex',
                      flexDirection: 'column',
                      justifyContent: 'space-between',
                      cursor: 'pointer',
                      transition: 'all 0.15s'
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.78rem', fontWeight: isToday || isSelected ? 700 : 500, color: isToday ? '#bc8cff' : (isSelected ? '#00d2ff' : T.text) }}>
                        {dayNum}
                      </span>
                      {isToday ? (
                        <span style={{ fontSize: '0.5rem', background: 'rgba(188, 140, 255, 0.2)', color: '#bc8cff', padding: '1px 4px', borderRadius: '4px', fontWeight: 700 }}>OGGI</span>
                      ) : (
                        dayTotalTasks > 0 && (
                          <span style={{
                            fontSize: '0.55rem', fontWeight: 700, padding: '1px 5px', borderRadius: '4px',
                            background: dayDoneTasks === dayTotalTasks ? 'rgba(63, 185, 80, 0.2)' : 'rgba(0, 210, 255, 0.15)',
                            color: dayDoneTasks === dayTotalTasks ? '#3fb950' : '#00d2ff'
                          }}>
                            âœ“ {dayDoneTasks}/{dayTotalTasks}
                          </span>
                        )
                      )}
                    </div>

                    {/* Indicatori Eventi */}
                    {events.total > 0 && (
                      <div style={{ display: 'flex', gap: '3px', flexWrap: 'wrap', marginTop: '4px', alignItems: 'center' }}>
                        {events.dayTasks.map((t, idx) => (
                          <span key={idx} style={{ width: '6px', height: '6px', borderRadius: '50%', background: t.status === 'done' ? '#3fb950' : '#00d2ff' }} title={t.titolo} />
                        ))}
                        {events.dayAudits.map((a, idx) => (
                          <span key={`a-${idx}`} style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#bc8cff' }} title={a.title} />
                        ))}
                        {isToday && dayTotalTasks > 0 && (
                          <span style={{ fontSize: '0.55rem', fontWeight: 700, marginLeft: 'auto', color: dayDoneTasks === dayTotalTasks ? '#3fb950' : '#00d2ff' }}>
                            {dayDoneTasks}/{dayTotalTasks}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Dettagli Giorno Selezionato */}
          <div style={{ background: T.cardBg, border: `1px solid ${T.border}`, borderRadius: '12px', padding: '12px', display: 'flex', flexDirection: 'column', gap: '10px', overflowY: 'auto' }}>
            <div style={{ borderBottom: `1px solid ${T.divider}`, paddingBottom: '10px' }}>
              <h4 style={{ margin: 0, fontSize: '0.9rem', fontWeight: 700, color: T.text }}>
                AttivitÃ  del {selectedDay} {monthNames[month]}
              </h4>
              <span style={{ fontSize: '0.7rem', color: T.muted }}>
                {selectedEvents.total} eventi registrati in questa data
              </span>
            </div>

            {selectedEvents.total === 0 ? (
              <div style={{ padding: '30px', textAlign: 'center', color: T.dim, fontSize: '0.75rem' }}>
                Nessuna attivitÃ  registrata per il giorno selezionato.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {selectedEvents.dayTasks.map(t => (
                  <div key={t.id} style={{ background: T.cardHover, border: `1px solid ${T.border}`, borderRadius: '8px', padding: '10px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span style={{ fontSize: '0.75rem', fontWeight: 700, color: T.text }}>{t.titolo}</span>
                      <span style={{ fontSize: '0.6rem', padding: '2px 6px', borderRadius: '4px', color: t.status === 'done' ? '#3fb950' : '#00d2ff', background: t.status === 'done' ? 'rgba(63,185,80,0.1)' : 'rgba(0,210,255,0.1)' }}>
                        {t.status?.toUpperCase()}
                      </span>
                    </div>
                    {t.descrizione && <p style={{ fontSize: '0.65rem', color: T.muted, margin: 0 }}>{t.descrizione}</p>}
                  </div>
                ))}

                {selectedEvents.dayAudits.map(a => (
                  <div key={a.id} style={{ background: T.cardHover, border: '1px solid rgba(188, 140, 255, 0.2)', borderRadius: '8px', padding: '10px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <span style={{ fontSize: '0.72rem', fontWeight: 600, color: '#bc8cff' }}>{a.title}</span>
                    <span style={{ fontSize: '0.62rem', color: T.muted }}>{a.details}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* TAB 2: GESTIONE TASK KANBAN */}
      {activeTab === 'kanban' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', flex: 1, minHeight: 0 }}>
          {/* Filters */}
          <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexShrink: 0 }}>
            <span style={{ fontSize: '0.72rem', color: T.muted, fontWeight: 600 }}>Filtra Stato:</span>
            <div style={{ display: 'flex', gap: '6px' }}>
              {[
                { key: 'all', label: 'Tutti' },
                { key: 'in_corso', label: 'In Corso' },
                { key: 'done', label: 'Completati' },
                { key: 'blocked', label: 'Bloccati' },
              ].map(f => (
                <button
                  key={f.key}
                  onClick={() => setFilterStatus(f.key)}
                  style={{
                    padding: '5px 12px', borderRadius: '6px', fontSize: '0.72rem', fontWeight: 600, cursor: 'pointer',
                    background: filterStatus === f.key ? 'rgba(0,210,255,0.15)' : T.cardBg,
                    border: filterStatus === f.key ? '1px solid rgba(0,210,255,0.3)' : `1px solid ${T.border}`,
                    color: filterStatus === f.key ? '#00d2ff' : T.muted
                  }}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <select
              value={filterModule}
              onChange={e => setFilterModule(e.target.value)}
              style={{ padding: '6px 12px', borderRadius: '6px', fontSize: '0.72rem', background: T.cardBg, border: `1px solid ${T.border}`, color: T.text, outline: 'none' }}
            >
              <option value="all">Tutti i moduli</option>
              {modules.filter(m => m !== 'all').map(m => (
                <option key={m} value={m}>Modulo {m}</option>
              ))}
            </select>
          </div>

          {/* Griglia Kanban */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '14px', overflowY: 'auto', flex: 1 }}>
            {filteredTasks.map((task, i) => {
              const prio = priorityColors[task.priorita] || priorityColors.media;
              return (
                <div 
                  key={task.id || i} 
                  onClick={() => onEdit(task)}
                  style={{
                    background: T.cardBg,
                    border: `1px solid ${T.border}`,
                    borderLeft: `4px solid ${task.status === 'done' ? '#3fb950' : (task.status === 'blocked' ? '#ff5555' : '#00d2ff')}`,
                    borderRadius: '12px',
                    padding: '16px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '10px',
                    cursor: 'pointer',
                    transition: 'all 0.15s'
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ fontSize: '0.65rem', fontWeight: 700, padding: '2px 8px', borderRadius: '4px', background: 'rgba(0,210,255,0.1)', color: '#00d2ff' }}>
                      MOD {task.moduli?.[0] || '??'}
                    </span>
                    <span style={{ fontSize: '0.65rem', fontWeight: 600, padding: '2px 8px', borderRadius: '4px', background: prio.bg, color: prio.color }}>
                      {prio.label}
                    </span>
                  </div>

                  <h4 style={{ margin: 0, fontSize: '0.88rem', fontWeight: 600, color: T.text }}>{task.titolo}</h4>
                  {task.descrizione && <p style={{ margin: 0, fontSize: '0.72rem', color: T.muted, lineHeight: 1.4 }}>{task.descrizione}</p>}

                  {/* Reference files */}
                  {task.files && task.files.length > 0 && (
                    <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', borderTop: `1px solid ${T.divider}`, paddingTop: '8px' }}>
                      {task.files.map((f, fi) => (
                        <span key={fi} onClick={(e) => { e.stopPropagation(); onOpenFile && onOpenFile(f.path); }} style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.62rem', background: T.cardHover, padding: '3px 8px', borderRadius: '6px', color: '#00d2ff', cursor: 'pointer' }}>
                          {getFileIcon(f.type)} {f.filename}
                        </span>
                      ))}
                    </div>
                  )}

                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: '4px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.7rem', color: T.muted }}>
                      {statusIcons[task.status]} <span>{statusLabels[task.status]}</span>
                    </div>
                    <div style={{ display: 'flex', gap: '6px' }}>
                      <button onClick={(e) => { e.stopPropagation(); onToggleStatus(task); }} style={{ padding: '4px 10px', borderRadius: '6px', fontSize: '0.68rem', background: 'transparent', border: `1px solid ${T.border}`, color: '#3fb950', cursor: 'pointer' }}>
                        {task.status === 'done' ? 'Riapri' : 'Completa'}
                      </button>
                      <button onClick={(e) => { e.stopPropagation(); onDelete(task); }} style={{ padding: '4px 8px', borderRadius: '6px', fontSize: '0.68rem', background: 'transparent', border: `1px solid ${T.border}`, color: '#ff5555', cursor: 'pointer' }}>
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* TAB 3: REGISTRO MODIFICHE (AUDIT TRAIL) */}
      {activeTab === 'audit' && (
        <div style={{ background: T.cardBg, border: `1px solid ${T.border}`, borderRadius: '14px', padding: '20px', display: 'flex', flexDirection: 'column', gap: '14px', flex: 1, minHeight: 0, overflowY: 'auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: `1px solid ${T.divider}`, paddingBottom: '10px' }}>
            <div>
              <h3 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 700, color: T.text }}>Registro Modifiche & Audit Log</h3>
              <span style={{ fontSize: '0.7rem', color: T.muted }}>Storico in tempo reale di modifiche al codice, sessioni agentiche ed esecuzioni</span>
            </div>
            <button onClick={() => window.location.reload()} style={{ padding: '6px 12px', borderRadius: '6px', background: 'rgba(0,210,255,0.1)', border: '1px solid rgba(0,210,255,0.2)', color: '#00d2ff', fontSize: '0.72rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <RefreshCw size={12} /> Aggiorna Log
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {auditLogs.map(log => (
              <div key={log.id} style={{ background: T.cardHover, border: `1px solid ${T.border}`, borderRadius: '10px', padding: '12px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '14px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <div style={{ width: '36px', height: '36px', borderRadius: '8px', background: 'rgba(188, 140, 255, 0.15)', border: '1px solid rgba(188, 140, 255, 0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#bc8cff' }}>
                    <FileCode size={18} />
                  </div>
                  <div>
                    <h4 style={{ margin: 0, fontSize: '0.82rem', fontWeight: 700, color: T.text }}>{log.title}</h4>
                    <span style={{ fontSize: '0.68rem', color: T.muted }}>{log.details}</span>
                  </div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '2px' }}>
                  <span style={{ fontSize: '0.65rem', color: '#00d2ff', fontWeight: 600 }}>{log.actor}</span>
                  <span style={{ fontSize: '0.6rem', color: T.dim }}>{log.dateStr}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      </div>
    </div>
  );
}
