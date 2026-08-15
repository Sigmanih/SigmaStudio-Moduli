import React, { useState, useEffect, useRef } from 'react';
import { 
  Mic, Volume2, Play, Square, Download, Sliders, Sparkles, RefreshCw, 
  Radio, Check, Save, User, Activity, Settings2, FileAudio, Upload
} from 'lucide-react';
import './styles/voice-studio.css';

const DEFAULT_PRESETS = [
  { id: 'assistant_it', name: 'Assistente AI Italiano', engine: 'kokoro', voice: 'if_sara', rate: 1.1, pitch: 1.0 },
  { id: 'tech_energetic', name: 'Tech & Codice Energetico', engine: 'kokoro', voice: 'im_nicola', rate: 1.25, pitch: 1.1 },
  { id: 'deep_story', name: 'Narratore Calmo & Profondo', engine: 'kokoro', voice: 'im_nicola', rate: 0.9, pitch: 0.85 },
  { id: 'system_default', name: 'Voce di Sistema Naturale', engine: 'browser', voice: '', rate: 1.0, pitch: 1.0 },
];

export default function VoiceStudio() {
  const [engines, setEngines] = useState([]);
  const [defaultConfig, setDefaultConfig] = useState(null);
  const [systemVoices, setSystemVoices] = useState([]);
  const [loading, setLoading] = useState(false);
  
  // Voice Controls State
  const [selectedEngine, setSelectedEngine] = useState('browser');
  const [selectedVoice, setSelectedVoice] = useState('');
  const [systemVoiceURI, setSystemVoiceURI] = useState('');
  const [speed, setSpeed] = useState(1.1);
  const [pitch, setPitch] = useState(1.0);
  const [volume, setVolume] = useState(1.0);
  const [text, setText] = useState('Ciao! Questo è il Voice Studio di Sigma. Qui puoi personalizzare, testare e costruire la voce ideale per i tuoi assistenti AI.');
  
  const [audioUrl, setAudioUrl] = useState(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [savedSuccess, setSavedSuccess] = useState(false);
  const audioRef = useRef(null);

  // Load Neural Engines from Backend API
  useEffect(() => {
    fetchEngines();
    loadSystemVoices();
    loadSavedAssistantConfig();
  }, []);

  const loadSavedAssistantConfig = () => {
    try {
      const saved = localStorage.getItem('sigma_assistant_voice_config');
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed.engine) setSelectedEngine(parsed.engine);
        if (parsed.neuralVoice) setSelectedVoice(parsed.neuralVoice);
        if (parsed.voiceURI) setSystemVoiceURI(parsed.voiceURI);
        if (parsed.rate) setSpeed(parsed.rate);
        if (parsed.pitch) setPitch(parsed.pitch);
      }
    } catch (e) {}
  };

  const loadSystemVoices = () => {
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      const update = () => {
        const voices = window.speechSynthesis.getVoices();
        setSystemVoices(voices);
        if (!systemVoiceURI && voices.length > 0) {
          const italian = voices.find(v => v.lang.startsWith('it') || v.lang.includes('IT'));
          setSystemVoiceURI(italian ? italian.voiceURI : voices[0].voiceURI);
        }
      };
      update();
      window.speechSynthesis.onvoiceschanged = update;
    }
  };

  const fetchEngines = async () => {
    try {
      setLoading(true);
      const res = await fetch('/api/tts/engines');
      if (res.ok) {
        const data = await res.json();
        setEngines(data.engines || []);
        setDefaultConfig(data.default);
        if (data.default && !selectedEngine) {
          setSelectedEngine(data.default.engine);
          setSelectedVoice(data.default.voice);
        }
      }
    } catch (e) {
      console.warn('Backend TTS API unavailable, using Browser Speech Synthesis', e);
    } finally {
      setLoading(false);
    }
  };

  const handleTestVoice = async () => {
    if (isPlaying) {
      if (typeof window !== 'undefined' && window.speechSynthesis) {
        window.speechSynthesis.cancel();
      }
      if (audioRef.current) {
        audioRef.current.pause();
      }
      setIsPlaying(false);
      return;
    }

    if (selectedEngine === 'browser' || !selectedEngine) {
      // Use Web Speech API
      if (typeof window !== 'undefined' && window.speechSynthesis) {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = speed;
        utterance.pitch = pitch;
        utterance.volume = volume;
        const chosen = systemVoices.find(v => v.voiceURI === systemVoiceURI);
        if (chosen) utterance.voice = chosen;

        utterance.onstart = () => setIsPlaying(true);
        utterance.onend = () => setIsPlaying(false);
        utterance.onerror = () => setIsPlaying(false);

        window.speechSynthesis.speak(utterance);
      }
      return;
    }

    // Use Neural Backend
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
          audioRef.current.volume = volume;
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

  const applyAsAssistantDefault = () => {
    try {
      const config = {
        engine: selectedEngine,
        neuralVoice: selectedVoice,
        voiceURI: systemVoiceURI,
        rate: speed,
        pitch: pitch,
        volume: volume
      };
      localStorage.setItem('sigma_assistant_voice_config', JSON.stringify(config));
      setSavedSuccess(true);
      setTimeout(() => setSavedSuccess(false), 2500);
      window.dispatchEvent(new CustomEvent('sigma_toast', {
        detail: { message: '✅ Voce assistente salvata come predefinita!', type: 'success' }
      }));
    } catch (e) {
      console.error(e);
    }
  };

  const applyPreset = (preset) => {
    setSelectedEngine(preset.engine);
    if (preset.voice) setSelectedVoice(preset.voice);
    if (preset.rate) setSpeed(preset.rate);
    if (preset.pitch) setPitch(preset.pitch);
  };

  const italianSystemVoices = systemVoices.filter(v => v.lang.startsWith('it') || v.lang.includes('IT'));
  const otherSystemVoices = systemVoices.filter(v => !v.lang.startsWith('it') && !v.lang.includes('IT'));
  const activeEngineObj = engines.find(e => e.id === selectedEngine);

  return (
    <div className="voice-studio-container">
      {/* SIDEBAR PARAMETRI & VOCI */}
      <div className="vs-sidebar">
        <div style={{ padding: '20px', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
          <h2 style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: 0, fontSize: '1.15rem', color: '#ff79c6', fontWeight: 800 }}>
            <Mic size={20} />
            Voice Studio & Lab
          </h2>
          <div style={{ fontSize: '0.72rem', color: '#8b8fa3', marginTop: '4px' }}>
            Configuratore & Sintetizzatore Vocale Neurale
          </div>
        </div>
        
        <div style={{ padding: '16px', flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Engine Selector */}
          <div>
            <label style={{ display: 'block', marginBottom: '6px', fontSize: '0.76rem', fontWeight: 700, color: '#8b8fa3' }}>
              Motore Vocale:
            </label>
            <select 
              value={selectedEngine} 
              onChange={e => setSelectedEngine(e.target.value)}
              style={{
                width: '100%', padding: '8px 10px', background: '#0e1016',
                border: '1px solid rgba(255,255,255,0.1)', color: '#f0f2f8',
                borderRadius: '8px', fontSize: '0.78rem', outline: 'none', cursor: 'pointer'
              }}
            >
              <option value="browser">🌐 Voce di Sistema (Browser SpeechSynthesis)</option>
              {engines.map(e => (
                <option key={e.id} value={e.id} disabled={!e.installed}>
                  🧠 {e.name || e.id} {e.installed ? '' : '(non installato)'}
                </option>
              ))}
            </select>
          </div>

          {/* If Neural Engine */}
          {selectedEngine !== 'browser' && activeEngineObj && activeEngineObj.voices?.length > 0 && (
            <div>
              <label style={{ display: 'block', marginBottom: '6px', fontSize: '0.76rem', fontWeight: 700, color: '#8b8fa3' }}>
                Voce Neurale ({activeEngineObj.name}):
              </label>
              <select 
                value={selectedVoice || activeEngineObj.default_voice} 
                onChange={e => setSelectedVoice(e.target.value)}
                style={{
                  width: '100%', padding: '8px 10px', background: '#0e1016',
                  border: '1px solid rgba(255,255,255,0.1)', color: '#f0f2f8',
                  borderRadius: '8px', fontSize: '0.78rem', outline: 'none', cursor: 'pointer'
                }}
              >
                {activeEngineObj.voices.map(v => (
                  <option key={v.id || v} value={v.id || v}>
                    {v.gender === 'male' ? '♂' : '♀'} {v.name || v} {v.lang ? `(${v.lang})` : ''}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* If System / Browser Voices */}
          {selectedEngine === 'browser' && (
            <div>
              <label style={{ display: 'block', marginBottom: '6px', fontSize: '0.76rem', fontWeight: 700, color: '#8b8fa3' }}>
                Seleziona Voce Sospesa:
              </label>
              <select 
                value={systemVoiceURI} 
                onChange={e => setSystemVoiceURI(e.target.value)}
                style={{
                  width: '100%', padding: '8px 10px', background: '#0e1016',
                  border: '1px solid rgba(255,255,255,0.1)', color: '#f0f2f8',
                  borderRadius: '8px', fontSize: '0.78rem', outline: 'none', cursor: 'pointer'
                }}
              >
                {italianSystemVoices.length > 0 && (
                  <optgroup label="🇮🇹 Voci Italiane">
                    {italianSystemVoices.map(v => (
                      <option key={v.voiceURI} value={v.voiceURI}>
                        🇮🇹 {v.name} ({v.lang})
                      </option>
                    ))}
                  </optgroup>
                )}
                {otherSystemVoices.length > 0 && (
                  <optgroup label="🌐 Altre Voci del Sistema">
                    {otherSystemVoices.map(v => (
                      <option key={v.voiceURI} value={v.voiceURI}>
                        🌐 {v.name} ({v.lang})
                      </option>
                    ))}
                  </optgroup>
                )}
              </select>
            </div>
          )}

          {/* Slider Velocità (Speed) */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px', fontSize: '0.75rem' }}>
              <span style={{ fontWeight: 600, color: '#8b8fa3' }}>Velocità (Speed):</span>
              <span style={{ color: '#ff79c6', fontWeight: 700 }}>{speed.toFixed(2)}x</span>
            </div>
            <input 
              type="range" 
              className="vs-slider"
              min="0.5" 
              max="2.0" 
              step="0.05" 
              value={speed} 
              onChange={e => setSpeed(parseFloat(e.target.value))}
            />
          </div>

          {/* Slider Tono (Pitch) */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px', fontSize: '0.75rem' }}>
              <span style={{ fontWeight: 600, color: '#8b8fa3' }}>Tono (Pitch):</span>
              <span style={{ color: '#00d2ff', fontWeight: 700 }}>{pitch.toFixed(2)}</span>
            </div>
            <input 
              type="range" 
              className="vs-slider"
              min="0.5" 
              max="1.8" 
              step="0.05" 
              value={pitch} 
              onChange={e => setPitch(parseFloat(e.target.value))}
              style={{ accentColor: '#00d2ff' }}
            />
          </div>

          {/* Presets Grid */}
          <div style={{ marginTop: '8px' }}>
            <label style={{ display: 'block', marginBottom: '6px', fontSize: '0.76rem', fontWeight: 700, color: '#8b8fa3' }}>
              Preset Vocali Rapidi:
            </label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {DEFAULT_PRESETS.map(p => (
                <button
                  key={p.id}
                  onClick={() => applyPreset(p)}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '8px 10px', borderRadius: '8px', background: 'rgba(255,255,255,0.03)',
                    border: '1px solid rgba(255,255,255,0.06)', color: '#e2e4eb', fontSize: '0.74rem',
                    cursor: 'pointer', textAlign: 'left', transition: 'all 0.15s'
                  }}
                >
                  <span>{p.name}</span>
                  <span style={{ color: '#ff79c6', fontSize: '0.68rem', fontWeight: 700 }}>{p.rate}x</span>
                </button>
              ))}
            </div>
          </div>

          {/* Save as Default Button */}
          <button
            onClick={applyAsAssistantDefault}
            style={{
              marginTop: '10px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '6px',
              padding: '10px',
              borderRadius: '10px',
              fontSize: '0.78rem',
              fontWeight: 700,
              background: savedSuccess ? 'rgba(63,185,80,0.2)' : 'linear-gradient(135deg, #ff79c6 0%, #bd93f9 100%)',
              border: savedSuccess ? '1px solid rgba(63,185,80,0.5)' : 'none',
              color: savedSuccess ? '#3fb950' : '#111',
              cursor: 'pointer',
              boxShadow: '0 4px 12px rgba(255,121,198,0.25)'
            }}
          >
            {savedSuccess ? <Check size={16} /> : <Save size={16} />}
            <span>{savedSuccess ? 'Impostata per l\'Assistente!' : 'Imposta come Voce Assistente'}</span>
          </button>
        </div>
      </div>

      {/* MAIN PLAYGROUND */}
      <div className="vs-main">
        {/* Test Synthesizer Card */}
        <div className="vs-card" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
            <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px', fontSize: '1rem', color: '#f0f2f8' }}>
              <Radio size={18} color="#ff79c6" /> 
              Sintesi Vocale Live & Test
            </h3>
            
            <button 
              onClick={handleTestVoice}
              disabled={loading}
              style={{
                background: isPlaying ? 'rgba(255,85,85,0.2)' : 'linear-gradient(135deg, #ff79c6, #bd93f9)',
                color: isPlaying ? '#ff5555' : '#111',
                border: isPlaying ? '1px solid rgba(255,85,85,0.4)' : 'none',
                padding: '8px 18px',
                borderRadius: '8px',
                fontWeight: 800,
                fontSize: '0.8rem',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                cursor: loading ? 'not-allowed' : 'pointer',
                boxShadow: isPlaying ? 'none' : '0 4px 14px rgba(255,121,198,0.3)'
              }}
            >
              {loading ? (
                <RefreshCw size={16} className="spin" />
              ) : isPlaying ? (
                <Square size={16} />
              ) : (
                <Play size={16} />
              )}
              <span>{isPlaying ? 'Ferma Test' : '🔊 Test Voce'}</span>
            </button>
          </div>
          
          <textarea
            value={text}
            onChange={e => setText(e.target.value)}
            style={{
              flex: 1,
              width: '100%',
              background: 'rgba(0,0,0,0.25)',
              border: '1px solid rgba(255,255,255,0.08)',
              color: '#fff',
              padding: '16px',
              borderRadius: '10px',
              resize: 'none',
              fontSize: '0.95rem',
              lineHeight: '1.6',
              fontFamily: 'inherit',
              outline: 'none'
            }}
            placeholder="Inserisci il testo che desideri sintetizzare..."
          />

          {/* Animated Waveform on Playback */}
          {isPlaying && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', justifyContent: 'center', padding: '12px 0' }}>
              <span style={{ fontSize: '0.74rem', color: '#ff79c6', fontWeight: 600, marginRight: '8px' }}>
                Riproduzione audio in corso...
              </span>
              <div style={{ display: 'flex', gap: '4px', alignItems: 'center', height: '20px' }}>
                <span style={{ width: '4px', height: '100%', background: '#ff79c6', borderRadius: '2px', animation: 'vs-wave 0.8s infinite ease-in-out' }} />
                <span style={{ width: '4px', height: '60%', background: '#00d2ff', borderRadius: '2px', animation: 'vs-wave 0.6s infinite ease-in-out 0.1s' }} />
                <span style={{ width: '4px', height: '90%', background: '#ff79c6', borderRadius: '2px', animation: 'vs-wave 1.0s infinite ease-in-out 0.2s' }} />
                <span style={{ width: '4px', height: '40%', background: '#00d2ff', borderRadius: '2px', animation: 'vs-wave 0.5s infinite ease-in-out 0.3s' }} />
              </div>
              <style>{`
                @keyframes vs-wave {
                  0%, 100% { transform: scaleY(0.2); }
                  50% { transform: scaleY(1); }
                }
              `}</style>
            </div>
          )}
        </div>

        {/* Audio Result & Download Card (when Neural audio generated) */}
        {audioUrl && (
          <div className="vs-card" style={{ display: 'flex', alignItems: 'center', gap: '16px', padding: '16px 20px' }}>
            <audio 
              ref={audioRef} 
              onEnded={() => setIsPlaying(false)}
              onPause={() => setIsPlaying(false)}
              onPlay={() => setIsPlaying(true)}
              style={{ display: 'none' }}
            />
            
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 700, fontSize: '0.85rem', color: '#f0f2f8' }}>File Audio WAV Generato</div>
              <div style={{ fontSize: '0.72rem', color: '#8b8fa3' }}>
                Motore: {selectedEngine} • Voce: {selectedVoice || 'default'} • Velocità: {speed}x
              </div>
            </div>
            
            <a 
              href={audioUrl} 
              download={`sigma_voice_${selectedEngine}_${selectedVoice || 'audio'}.wav`}
              style={{
                background: 'rgba(255,255,255,0.08)',
                color: '#fff',
                border: '1px solid rgba(255,255,255,0.1)',
                padding: '8px 16px',
                borderRadius: '8px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                textDecoration: 'none',
                fontSize: '0.78rem',
                fontWeight: 600
              }}
            >
              <Download size={14} /> Salva Audio WAV
            </a>
          </div>
        )}
      </div>
    </div>
  );
}
