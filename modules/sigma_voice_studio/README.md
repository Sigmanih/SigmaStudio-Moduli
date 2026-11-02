# AudioStudio — Musica e Voci

Modulo per la sintesi vocale neurale e voice cloning integrato in Sigma Studio. Include motori Kokoro 82M e XTTS-v2.

La sezione Musica compone basi strumentali locali attraverso ACE-Step 1.5 turbo di Creative Lab/ComfyUI.
Sono disponibili Lo-Fi Study Beats, Deep Focus Ambient, Neoclassical Piano e Cyber Ambient / Coding Music,
con anteprime di due minuti e sessioni di 5, 15 o 30 minuti, BPM e seed personalizzabili.

Le composizioni hanno una coda persistente con annullamento e ripresa, segmenti verificati e dissolvenze.
L'uscita include WAV, MP3 e `composition.json` sotto `works/audio_studio/`, con player e download nell'interfaccia.
I controlli rilevano durata insufficiente, silenzi prolungati e loop quasi identici; la valutazione musicale
resta affidata all'ascolto. Ogni genere associa un tema per il successivo video, che non viene ancora generato.

La sezione Voci mantiene configurazione dell'assistente, sintesi e libreria vocale. L'identificativo interno
`sigma_voice_studio` e le API TTS restano compatibili; le nuove rotte sono `/api/audio-studio/music/*`.
I tool MCP `list_music_presets`, `generate_study_music` e `music_jobs` espongono lo stesso flusso agli agenti.
