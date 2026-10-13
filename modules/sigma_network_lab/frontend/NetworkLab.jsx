// ==============================================================================
// NetworkLab.jsx — Sigma Studio Network Explorer & Web Research Console
// ==============================================================================
import React, { useState, useEffect } from 'react';
import {
  Globe, Search, Send, Activity, Terminal, Shield, CheckCircle2,
  AlertCircle, Copy, ExternalLink, RefreshCw, Cpu, Server, Wifi,
  Layers, ArrowRight, Zap, Code, Database, Play
} from 'lucide-react';
import './styles/network-lab.css';
import TabHeader from '../../components/common/TabHeader';

export default function NetworkLab() {
  const [activeTab, setActiveTab] = useState('search');
  const [networkStatus, setNetworkStatus] = useState(null);
  const [statusLoading, setStatusLoading] = useState(false);

  // --- 1. Web Search State ---
  const [searchQuery, setSearchQuery] = useState('');
  const [searchEngine, setSearchEngine] = useState('duckduckgo');
  const [searchResults, setSearchResults] = useState([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchStats, setSearchStats] = useState(null);

  // --- 2. HTTP Client State ---
  const [httpMethod, setHttpMethod] = useState('GET');
  const [httpUrl, setHttpUrl] = useState('https://api.github.com/zen');
  const [httpHeaders, setHttpHeaders] = useState([{ key: 'Accept', value: 'application/json' }]);
  const [httpBody, setHttpBody] = useState('{\n  "query": "hello"\n}');
  const [httpSubTab, setHttpSubTab] = useState('headers');
  const [httpResponse, setHttpResponse] = useState(null);
  const [httpLoading, setHttpLoading] = useState(false);

  // --- 3. DNS Diagnostics State ---
  const [dnsDomain, setDnsDomain] = useState('google.com');
  const [dnsResults, setDnsResults] = useState(null);
  const [dnsLoading, setDnsLoading] = useState(false);

  // --- 4. Ping Tester State ---
  const [pingHost, setPingHost] = useState('1.1.1.1');
  const [pingPort, setPingPort] = useState(80);
  const [pingCount, setPingCount] = useState(4);
  const [pingResults, setPingResults] = useState(null);
  const [pingLoading, setPingLoading] = useState(false);

  // --- 5. MCP Tool Tester State ---
  const [mcpSelectedTool, setMcpSelectedTool] = useState('search_web');
  const [mcpToolParam, setMcpToolParam] = useState('Sigma Studio AI');
  const [mcpResult, setMcpResult] = useState(null);
  const [mcpLoading, setMcpLoading] = useState(false);

  // Fetch initial network status
  useEffect(() => {
    fetchNetworkStatus();
  }, []);

  const fetchNetworkStatus = async () => {
    setStatusLoading(true);
    try {
      const res = await fetch('/api/network/status');
      if (res.ok) {
        const data = await res.json();
        setNetworkStatus(data);
      }
    } catch (e) {
      console.warn('Network status fetch error:', e);
    } finally {
      setStatusLoading(false);
    }
  };

  // 1. Execute Search
  const handleSearch = async (e) => {
    if (e) e.preventDefault();
    if (!searchQuery.trim()) return;
    setSearchLoading(true);
    setSearchResults([]);
    try {
      const res = await fetch('/api/network/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: searchQuery, engine: searchEngine, max_results: 10 }),
      });
      const data = await res.json();
      if (data.success) {
        setSearchResults(data.results || []);
        setSearchStats({ count: data.results_count, elapsed: data.elapsed_ms });
      }
    } catch (err) {
      console.error('Search error:', err);
    } finally {
      setSearchLoading(false);
    }
  };

  // 2. Execute HTTP Request
  const handleHttpRequest = async () => {
    if (!httpUrl.trim()) return;
    setHttpLoading(true);
    setHttpResponse(null);

    // Build headers object
    const headersObj = {};
    httpHeaders.forEach((h) => {
      if (h.key.trim()) headersObj[h.key.trim()] = h.value;
    });

    let bodyPayload = null;
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(httpMethod) && httpBody.trim()) {
      try {
        bodyPayload = JSON.parse(httpBody);
      } catch {
        bodyPayload = httpBody;
      }
    }

    try {
      const res = await fetch('/api/network/request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          method: httpMethod,
          url: httpUrl,
          headers: headersObj,
          body: bodyPayload,
        }),
      });
      const data = await res.json();
      setHttpResponse(data);
    } catch (err) {
      setHttpResponse({ success: false, error: String(err), status_code: 0 });
    } finally {
      setHttpLoading(false);
    }
  };

  // 3. Execute DNS
  const handleDnsLookup = async (e) => {
    if (e) e.preventDefault();
    if (!dnsDomain.trim()) return;
    setDnsLoading(true);
    setDnsResults(null);
    try {
      const res = await fetch('/api/network/dns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain: dnsDomain }),
      });
      const data = await res.json();
      setDnsResults(data);
    } catch (err) {
      setDnsResults({ success: false, error: String(err) });
    } finally {
      setDnsLoading(false);
    }
  };

  // 4. Execute Ping
  const handlePing = async (e) => {
    if (e) e.preventDefault();
    if (!pingHost.trim()) return;
    setPingLoading(true);
    setPingResults(null);
    try {
      const res = await fetch('/api/network/ping', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ host: pingHost, port: Number(pingPort), count: Number(pingCount) }),
      });
      const data = await res.json();
      setPingResults(data);
    } catch (err) {
      setPingResults({ success: false, error: String(err) });
    } finally {
      setPingLoading(false);
    }
  };

  // 5. Execute MCP Tool
  const handleMcpTest = async () => {
    setMcpLoading(true);
    setMcpResult(null);
    try {
      let endpoint = '/api/network/search';
      let payload = { query: mcpToolParam };
      if (mcpSelectedTool === 'ping_node') {
        endpoint = '/api/network/ping';
        payload = { host: mcpToolParam, port: 80, count: 2 };
      } else if (mcpSelectedTool === 'resolve_dns') {
        endpoint = '/api/network/dns';
        payload = { domain: mcpToolParam };
      } else if (mcpSelectedTool === 'http_request' || mcpSelectedTool === 'fetch_web_page') {
        endpoint = '/api/network/request';
        payload = { method: 'GET', url: mcpToolParam.startsWith('http') ? mcpToolParam : `https://${mcpToolParam}` };
      }

      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      setMcpResult(data);
    } catch (err) {
      setMcpResult({ error: String(err) });
    } finally {
      setMcpLoading(false);
    }
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(typeof text === 'string' ? text : JSON.stringify(text, null, 2));
  };

  return (
    <div className="netlab-container">
      {/* Intestazione Universale Kernel Sigma Studio con Sub-Tab Switcher */}
      <TabHeader
        icon={Globe}
        title="AI Web Browser"
        highlight="WEB RESEARCH & MCP"
        tabs={[
          { id: 'search', label: 'Web Research', icon: Search, active: activeTab === 'search', onClick: () => setActiveTab('search') },
          { id: 'http', label: 'HTTP API Client', icon: Send, active: activeTab === 'http', onClick: () => setActiveTab('http') },
          { id: 'dns', label: 'DNS Diagnostics', icon: Database, active: activeTab === 'dns', onClick: () => setActiveTab('dns') },
          { id: 'ping', label: 'Ping & Latency', icon: Activity, active: activeTab === 'ping', onClick: () => setActiveTab('ping') },
          { id: 'mcp', label: 'AI Tools Tester', icon: Cpu, active: activeTab === 'mcp', onClick: () => setActiveTab('mcp') },
        ]}
        description="Ricerche web live, client HTTP REST, diagnostica DNS & tool MCP per agenti AI"
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <div className={`netlab-status-badge ${networkStatus?.internet_online ? '' : 'offline'}`} style={{ padding: '4px 10px', fontSize: '0.72rem' }}>
              <div className="netlab-dot" />
              <span>
                {networkStatus?.internet_online
                  ? `Online (${networkStatus.dns_latency_ms || '—'} ms)`
                  : 'Offline'}
              </span>
            </div>

            <button
              type="button"
              onClick={fetchNetworkStatus}
              title="Verifica connessione di rete"
              style={{
                background: 'rgba(255,255,255,0.06)',
                border: '1px solid rgba(255,255,255,0.12)',
                borderRadius: '8px',
                padding: '5px 10px',
                color: '#8b949e',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
                fontSize: '0.72rem',
                fontWeight: 600
              }}
            >
              <RefreshCw size={12} className={statusLoading ? 'animate-spin' : ''} />
              <span>Verifica</span>
            </button>
          </div>
        }
      />

      {/* Main Content Area */}
      <main className="netlab-content">
        {/* ===================================================================
            TAB 1: WEB RESEARCH
           =================================================================== */}
        {activeTab === 'search' && (
          <div>
            <div className="netlab-card">
              <form onSubmit={handleSearch} className="netlab-input-group">
                <input
                  type="text"
                  placeholder="Cerca su internet (es. FastAPI docs, PyTorch CUDA, Architettura LLM)..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="netlab-input"
                />
                <select
                  value={searchEngine}
                  onChange={(e) => setSearchEngine(e.target.value)}
                  className="netlab-select"
                >
                  <option value="duckduckgo">DuckDuckGo Live</option>
                  <option value="wikipedia">Wikipedia API</option>
                </select>
                <button
                  type="submit"
                  disabled={searchLoading || !searchQuery.trim()}
                  className="netlab-btn-primary"
                >
                  <Search size={14} /> {searchLoading ? 'Ricerca...' : 'Cerca'}
                </button>
              </form>

              {searchStats && (
                <div style={{ fontSize: '0.70rem', color: '#8b949e', marginTop: 4 }}>
                  Trovati {searchStats.count} risultati in {searchStats.elapsed} ms
                </div>
              )}
            </div>

            {/* Search Results List */}
            {searchResults.length > 0 && (
              <div>
                {searchResults.map((item, idx) => (
                  <div key={idx} className="netlab-result-card">
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noreferrer"
                        className="netlab-result-title"
                      >
                        {item.title} <ExternalLink size={12} />
                      </a>
                      <span
                        style={{
                          fontSize: '0.62rem',
                          background: 'rgba(63,185,80,0.15)',
                          color: '#3fb950',
                          padding: '2px 6px',
                          borderRadius: 4,
                          fontWeight: 700,
                        }}
                      >
                        {item.engine}
                      </span>
                    </div>
                    <div className="netlab-result-url">{item.url}</div>
                    <div className="netlab-result-snippet">{item.snippet}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ===================================================================
            TAB 2: HTTP API CLIENT (POSTMAN STYLE)
           =================================================================== */}
        {activeTab === 'http' && (
          <div>
            <div className="netlab-card">
              <div className="netlab-input-group">
                <select
                  value={httpMethod}
                  onChange={(e) => setHttpMethod(e.target.value)}
                  className="netlab-select"
                  style={{ minWidth: 100 }}
                >
                  <option value="GET">GET</option>
                  <option value="POST">POST</option>
                  <option value="PUT">PUT</option>
                  <option value="DELETE">DELETE</option>
                  <option value="PATCH">PATCH</option>
                  <option value="HEAD">HEAD</option>
                </select>

                <input
                  type="text"
                  placeholder="https://api.example.com/v1/resource"
                  value={httpUrl}
                  onChange={(e) => setHttpUrl(e.target.value)}
                  className="netlab-input"
                />

                <button
                  type="button"
                  onClick={handleHttpRequest}
                  disabled={httpLoading || !httpUrl.trim()}
                  className="netlab-btn-primary netlab-btn-accent"
                >
                  <Send size={14} /> {httpLoading ? 'Invio...' : 'Invia'}
                </button>
              </div>

              {/* Sub-tabs for Request Builder */}
              <div style={{ display: 'flex', gap: 6, margin: '10px 0', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 6 }}>
                <button
                  type="button"
                  onClick={() => setHttpSubTab('headers')}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: httpSubTab === 'headers' ? '#00f2fe' : '#8b949e',
                    fontSize: '0.72rem',
                    fontWeight: 700,
                    cursor: 'pointer',
                  }}
                >
                  Headers ({httpHeaders.length})
                </button>
                <button
                  type="button"
                  onClick={() => setHttpSubTab('body')}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: httpSubTab === 'body' ? '#00f2fe' : '#8b949e',
                    fontSize: '0.72rem',
                    fontWeight: 700,
                    cursor: 'pointer',
                  }}
                >
                  JSON Body
                </button>
              </div>

              {/* Sub-Tab: Headers */}
              {httpSubTab === 'headers' && (
                <div style={{ display: 'grid', gap: 6 }}>
                  {httpHeaders.map((h, i) => (
                    <div key={i} style={{ display: 'flex', gap: 6 }}>
                      <input
                        type="text"
                        placeholder="Header Key (es. Authorization)"
                        value={h.key}
                        onChange={(e) => {
                          const copy = [...httpHeaders];
                          copy[i].key = e.target.value;
                          setHttpHeaders(copy);
                        }}
                        className="netlab-input"
                      />
                      <input
                        type="text"
                        placeholder="Header Value"
                        value={h.value}
                        onChange={(e) => {
                          const copy = [...httpHeaders];
                          copy[i].value = e.target.value;
                          setHttpHeaders(copy);
                        }}
                        className="netlab-input"
                      />
                      <button
                        type="button"
                        onClick={() => setHttpHeaders(httpHeaders.filter((_, idx) => idx !== i))}
                        style={{ background: 'transparent', border: 'none', color: '#f85149', cursor: 'pointer' }}
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                  <button
                    type="button"
                    onClick={() => setHttpHeaders([...httpHeaders, { key: '', value: '' }])}
                    style={{
                      background: 'rgba(255,255,255,0.05)',
                      border: '1px dashed rgba(255,255,255,0.2)',
                      borderRadius: 6,
                      color: '#8b949e',
                      padding: '4px 10px',
                      fontSize: '0.70rem',
                      cursor: 'pointer',
                      width: 'fit-content',
                    }}
                  >
                    + Aggiungi Header
                  </button>
                </div>
              )}

              {/* Sub-Tab: JSON Body */}
              {httpSubTab === 'body' && (
                <div>
                  <textarea
                    rows={6}
                    value={httpBody}
                    onChange={(e) => setHttpBody(e.target.value)}
                    className="netlab-input"
                    style={{ width: '100%', fontFamily: 'Consolas, monospace', resize: 'vertical' }}
                    placeholder='{\n  "param": "value"\n}'
                  />
                </div>
              )}
            </div>

            {/* HTTP Response Panel */}
            {httpResponse && (
              <div className="netlab-card">
                <div className="netlab-card-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span
                      style={{
                        padding: '3px 8px',
                        borderRadius: 6,
                        fontWeight: 800,
                        fontSize: '0.72rem',
                        background:
                          httpResponse.status_code >= 200 && httpResponse.status_code < 300
                            ? 'rgba(63,185,80,0.2)'
                            : 'rgba(248,81,73,0.2)',
                        color:
                          httpResponse.status_code >= 200 && httpResponse.status_code < 300
                            ? '#3fb950'
                            : '#f85149',
                        border: '1px solid currentColor',
                      }}
                    >
                      {httpResponse.status_code} {httpResponse.status_text}
                    </span>
                    <span style={{ fontSize: '0.72rem', color: '#8b949e' }}>
                      ⏱ {httpResponse.latency_ms} ms
                    </span>
                    {httpResponse.size_label && (
                      <span style={{ fontSize: '0.72rem', color: '#8b949e' }}>
                        📦 {httpResponse.size_label}
                      </span>
                    )}
                  </div>

                  <button
                    type="button"
                    onClick={() => copyToClipboard(httpResponse.json_data || httpResponse.text_data)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 4,
                      background: 'rgba(255,255,255,0.06)',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: 6,
                      padding: '4px 8px',
                      color: '#f0f6fc',
                      fontSize: '0.68rem',
                      cursor: 'pointer',
                    }}
                  >
                    <Copy size={12} /> Copia Risposta
                  </button>
                </div>

                <div className="netlab-code-box">
                  {httpResponse.json_data
                    ? JSON.stringify(httpResponse.json_data, null, 2)
                    : httpResponse.text_data || httpResponse.error || 'Nessun contenuto restituito.'}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ===================================================================
            TAB 3: DNS DIAGNOSTICS
           =================================================================== */}
        {activeTab === 'dns' && (
          <div>
            <div className="netlab-card">
              <form onSubmit={handleDnsLookup} className="netlab-input-group">
                <input
                  type="text"
                  placeholder="Dominio o IP (es. google.com, github.com, 1.1.1.1)..."
                  value={dnsDomain}
                  onChange={(e) => setDnsDomain(e.target.value)}
                  className="netlab-input"
                />
                <button
                  type="submit"
                  disabled={dnsLoading || !dnsDomain.trim()}
                  className="netlab-btn-primary"
                >
                  <Database size={14} /> {dnsLoading ? 'Risoluzione...' : 'Risolvi DNS'}
                </button>
              </form>
            </div>

            {dnsResults && (
              <div className="netlab-card">
                <div className="netlab-card-header">
                  <h3 className="netlab-card-title">
                    <Database size={15} color="#3fb950" /> Record DNS per '{dnsResults.domain}'
                  </h3>
                  <span style={{ fontSize: '0.70rem', color: '#8b949e' }}>
                    Latenza query: {dnsResults.latency_ms} ms
                  </span>
                </div>

                {dnsResults.records && dnsResults.records.length > 0 ? (
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.75rem' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.1)', color: '#8b949e', textAlign: 'left' }}>
                        <th style={{ padding: '8px' }}>Tipo Record</th>
                        <th style={{ padding: '8px' }}>Valore / Indirizzo IP</th>
                        <th style={{ padding: '8px' }}>Host</th>
                        <th style={{ padding: '8px' }}>Stato</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dnsResults.records.map((r, i) => (
                        <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                          <td style={{ padding: '8px', color: '#00f2fe', fontWeight: 700 }}>{r.type}</td>
                          <td style={{ padding: '8px', fontFamily: 'Consolas, monospace', color: '#3fb950' }}>{r.value}</td>
                          <td style={{ padding: '8px', color: '#8b949e' }}>{r.host}</td>
                          <td style={{ padding: '8px', color: '#3fb950' }}>✓ {r.status}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div style={{ fontSize: '0.75rem', color: '#f85149' }}>
                    {dnsResults.error || 'Nessun record DNS risolto.'}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ===================================================================
            TAB 4: PING & LATENCY
           =================================================================== */}
        {activeTab === 'ping' && (
          <div>
            <div className="netlab-card">
              <form onSubmit={handlePing} className="netlab-input-group">
                <input
                  type="text"
                  placeholder="Host o IP target (es. 1.1.1.1, 8.8.8.8, github.com)..."
                  value={pingHost}
                  onChange={(e) => setPingHost(e.target.value)}
                  className="netlab-input"
                />
                <input
                  type="number"
                  placeholder="Porta"
                  value={pingPort}
                  onChange={(e) => setPingPort(e.target.value)}
                  className="netlab-input"
                  style={{ maxWidth: 90 }}
                />
                <select
                  value={pingCount}
                  onChange={(e) => setPingCount(e.target.value)}
                  className="netlab-select"
                >
                  <option value="3">3 ping</option>
                  <option value="5">5 ping</option>
                  <option value="10">10 ping</option>
                </select>
                <button
                  type="submit"
                  disabled={pingLoading || !pingHost.trim()}
                  className="netlab-btn-primary"
                >
                  <Activity size={14} /> {pingLoading ? 'Ping in corso...' : 'Avvia Ping'}
                </button>
              </form>
            </div>

            {pingResults && (
              <div>
                <div className="netlab-stats-row">
                  <div className="netlab-stat-box">
                    <div className="netlab-stat-label">Min Latenza</div>
                    <div className="netlab-stat-value" style={{ color: '#3fb950' }}>
                      {pingResults.min_ms !== null ? `${pingResults.min_ms} ms` : '—'}
                    </div>
                  </div>
                  <div className="netlab-stat-box">
                    <div className="netlab-stat-label">Media Latenza</div>
                    <div className="netlab-stat-value" style={{ color: '#00f2fe' }}>
                      {pingResults.avg_ms !== null ? `${pingResults.avg_ms} ms` : '—'}
                    </div>
                  </div>
                  <div className="netlab-stat-box">
                    <div className="netlab-stat-label">Max Latenza</div>
                    <div className="netlab-stat-value" style={{ color: '#d29922' }}>
                      {pingResults.max_ms !== null ? `${pingResults.max_ms} ms` : '—'}
                    </div>
                  </div>
                  <div className="netlab-stat-box">
                    <div className="netlab-stat-label">Pacchetti Persi</div>
                    <div className="netlab-stat-value" style={{ color: pingResults.loss_percentage > 0 ? '#f85149' : '#3fb950' }}>
                      {pingResults.loss_percentage}%
                    </div>
                  </div>
                </div>

                <div className="netlab-card">
                  <h3 className="netlab-card-title" style={{ marginBottom: 12 }}>
                    Dettaglio Campioni ({pingResults.received}/{pingResults.transmitted} riusciti)
                  </h3>
                  <div style={{ display: 'grid', gap: 6 }}>
                    {pingResults.samples?.map((s) => (
                      <div
                        key={s.seq}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          padding: '6px 10px',
                          borderRadius: 6,
                          background: 'rgba(255,255,255,0.03)',
                          fontSize: '0.72rem',
                          fontFamily: 'Consolas, monospace',
                        }}
                      >
                        <span style={{ color: '#8b949e' }}>Campione #{s.seq}</span>
                        <span style={{ color: '#f0f6fc' }}>IP: {s.ip || pingResults.ip}</span>
                        <span style={{ color: s.latency_ms ? '#3fb950' : '#f85149', fontWeight: 700 }}>
                          {s.latency_ms ? `${s.latency_ms} ms` : 'Timeout / Rifiutato'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ===================================================================
            TAB 5: AI NETWORK MCP TESTER
           =================================================================== */}
        {activeTab === 'mcp' && (
          <div>
            <div className="netlab-card">
              <h3 className="netlab-card-title" style={{ marginBottom: 8 }}>
                <Cpu size={15} color="#00f2fe" /> Network MCP Suite per Agenti AI
              </h3>
              <p style={{ fontSize: '0.72rem', color: '#8b949e', marginBottom: 14 }}>
                Strumenti di rete disponibili per l'Admin Developer Agent e la Swarm P2P di Sigma Studio.
              </p>

              <div className="netlab-input-group">
                <select
                  value={mcpSelectedTool}
                  onChange={(e) => setMcpSelectedTool(e.target.value)}
                  className="netlab-select"
                  style={{ minWidth: 160 }}
                >
                  <option value="search_web">search_web</option>
                  <option value="fetch_web_page">fetch_web_page</option>
                  <option value="http_request">http_request</option>
                  <option value="resolve_dns">resolve_dns</option>
                  <option value="ping_node">ping_node</option>
                </select>

                <input
                  type="text"
                  placeholder="Parametro tool (es. Query di ricerca, URL o Host)..."
                  value={mcpToolParam}
                  onChange={(e) => setMcpToolParam(e.target.value)}
                  className="netlab-input"
                />

                <button
                  type="button"
                  onClick={handleMcpTest}
                  disabled={mcpLoading}
                  className="netlab-btn-primary netlab-btn-accent"
                >
                  <Play size={14} /> {mcpLoading ? 'Esecuzione...' : 'Test Tool'}
                </button>
              </div>
            </div>

            {mcpResult && (
              <div className="netlab-card">
                <div className="netlab-card-header">
                  <h3 className="netlab-card-title">Output Esecuzione MCP</h3>
                  <button
                    type="button"
                    onClick={() => copyToClipboard(mcpResult)}
                    style={{
                      background: 'transparent',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: 6,
                      color: '#8b949e',
                      padding: '3px 6px',
                      fontSize: '0.65rem',
                      cursor: 'pointer',
                    }}
                  >
                    <Copy size={11} /> Copia JSON
                  </button>
                </div>
                <div className="netlab-code-box">
                  {JSON.stringify(mcpResult, null, 2)}
                </div>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
