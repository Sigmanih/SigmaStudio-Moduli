import React, { useState, useEffect, useRef } from 'react';
import { Mic, Volume2, Play, Square, Download, Sliders, Sparkles, RefreshCw, Radio } from 'lucide-react';
import './styles/voice-studio.css';

export default function VoiceStudio() {
  const [engines, setEngines] = useState([]);
  const [defaultConfig, setDefaultConfig] = useState(null);
  const [loading, setLoading] = useState(false);
  
  const [selectedEngine, setSelectedEngine] = useState('');
  const [selectedVoice, setSelectedVoice] = useState('');
  const [speed, setSpeed] = useState(1.0);
  const [text, setText] = useState('Benvenuto nel Voice Studio di Sigma. Questa è una prova di sintesi vocale neurale.');
  
  const [audioUrl, setAudioUrl] = useState(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const audioRef = useRef(null);

  useEffect(() => {
    fetchEngines();
  }, []);

  const fetchEngines = async () => {
    try {
      setLoading(true);
      const res = await fetch('/api/tts/engines');
      const data = await res.json();
      if (data.success) {
        setEngines(data.engines || []);
        setDefaultConfig(data.default);
        if (data.default && !selectedEngine) {
          setSelectedEngine(data.default.engine);
          setSelectedVoice(data.default.voice);
        }
      }
    } catch (e) {
      console.error('Failed to load TTS engines', e);
    } finally {
      setLoading(false);
    }
  };

  const handleSynthesize = async () => {
    try {
      setLoading(true);
      const res = await fetch('/api/tts/speak', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          engine: selectedEngine,
          voice: selectedVoice,
          speed
        })
      });
      const data = await res.json();
      if (data.success && data.audio) {
        const url = `data:audio/wav;base64,${data.audio}`;
        setAudioUrl(url);
        if (audioRef.current) {
          audioRef.current.src = url;
          audioRef.current.play();
          setIsPlaying(true);
        }
      }
    } catch (e) {
      console.error('TTS synthesis failed', e);
    } finally {
      setLoading(false);
    }
  };

  const getAvailableVoices = () => {
    const engine = engines.find(e => e.id === selectedEngine);
    return engine ? engine.voices : [];
  };

  return (
    <div className="voice-studio-container">
      <div className="vs-sidebar">
        <div style={{ padding: '20px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
          <h2 style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: 0, fontSize: '1.2rem' }}>
            <Mic size={20} color="#ff79c6" />
            Voice Studio
          </h2>
        </div>
        
        <div style={{ padding: '20px', flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', color: '#8b92a5' }}>
              Motore TTS
            </label>
            <select 
              value={selectedEngine} 
              onChange={e => {
                setSelectedEngine(e.target.value);
                const engine = engines.find(eng => eng.id === e.target.value);
                if (engine && engine.voices.length > 0) {
                  setSelectedVoice(engine.voices[0].id || engine.voices[0]);
                }
              }}
              style={{ width: '100%', padding: '8px', background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.1)', color: 'white', borderRadius: '6px' }}
            >
              {engines.map(e => (
                <option key={e.id} value={e.id}>{e.name || e.id}</option>
              ))}
            </select>
          </div>

          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', color: '#8b92a5' }}>
              Voce Neurale
            </label>
            <select 
              value={selectedVoice} 
              onChange={e => setSelectedVoice(e.target.value)}
              style={{ width: '100%', padding: '8px', background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.1)', color: 'white', borderRadius: '6px' }}
            >
              {getAvailableVoices().map(v => {
                const id = v.id || v;
                const name = v.name || v;
                return <option key={id} value={id}>{name}</option>;
              })}
            </select>
          </div>

          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontSize: '0.9rem', color: '#8b92a5', display: 'flex', justifyContent: 'space-between' }}>
              <span>Velocità</span>
              <span>{speed.toFixed(1)}x</span>
            </label>
            <input 
              type="range" 
              className="vs-slider"
              min="0.5" 
              max="2.0" 
              step="0.1" 
              value={speed} 
              onChange={e => setSpeed(parseFloat(e.target.value))}
            />
          </div>
        </div>
      </div>

      <div className="vs-main">
        <div className="vs-card" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Radio size={18} /> Sintesi del Testo
            </h3>
            <button 
              onClick={handleSynthesize}
              disabled={loading}
              style={{
                background: '#ff79c6', color: '#282a36', border: 'none', padding: '8px 16px', borderRadius: '6px',
                fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '8px', cursor: loading ? 'not-allowed' : 'pointer',
                opacity: loading ? 0.7 : 1
              }}
            >
              {loading ? <RefreshCw size={16} className="spin" /> : <Sparkles size={16} />}
              Genera Audio
            </button>
          </div>
          
          <textarea
            value={text}
            onChange={e => setText(e.target.value)}
            style={{
              flex: 1, width: '100%', background: 'rgba(0,0,0,0.1)', border: '1px solid rgba(255,255,255,0.1)',
              color: 'white', padding: '16px', borderRadius: '8px', resize: 'none', fontSize: '1.1rem',
              lineHeight: '1.5', fontFamily: 'inherit'
            }}
            placeholder="Inserisci qui il testo da far leggere all'IA..."
          />
        </div>

        {audioUrl && (
          <div className="vs-card" style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <audio 
              ref={audioRef} 
              onEnded={() => setIsPlaying(false)}
              onPause={() => setIsPlaying(false)}
              onPlay={() => setIsPlaying(true)}
              style={{ display: 'none' }}
            />
            
            <button 
              onClick={() => {
                if (isPlaying) { audioRef.current?.pause(); }
                else { audioRef.current?.play(); }
              }}
              style={{
                background: 'rgba(255,255,255,0.1)', border: 'none', borderRadius: '50%', width: '48px', height: '48px',
                display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', cursor: 'pointer'
              }}
            >
              {isPlaying ? <Square size={20} /> : <Play size={20} fill="white" />}
            </button>
            
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 'bold', marginBottom: '4px' }}>Risultato Generato</div>
              <div style={{ fontSize: '0.85rem', color: '#8b92a5' }}>{selectedEngine} • {selectedVoice} • {speed}x</div>
            </div>
            
            <a 
              href={audioUrl} 
              download={`sigma_voice_${selectedEngine}_${selectedVoice}.wav`}
              style={{
                background: 'rgba(255,255,255,0.1)', color: 'white', border: 'none', padding: '8px 16px', borderRadius: '6px',
                display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', textDecoration: 'none', fontSize: '0.9rem'
              }}
            >
              <Download size={16} /> Salva WAV
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
