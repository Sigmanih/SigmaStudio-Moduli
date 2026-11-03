# AudioStudio — Musica e Voci

Modulo per la sintesi vocale neurale e voice cloning integrato in Sigma Studio. Include motori Kokoro 82M e XTTS-v2.

La sezione Musica compone basi strumentali locali attraverso ACE-Step 1.5 turbo di Creative Lab/ComfyUI.
Sono disponibili Lo-Fi Study Beats, Deep Focus Ambient, Neoclassical Piano, Cyber Ambient / Coding Music e Palestra / Workout Energy,
con anteprime di due minuti e sessioni di 5, 15 o 30 minuti, BPM e seed personalizzabili.

Le composizioni hanno una coda persistente con annullamento e ripresa, segmenti verificati e dissolvenze.
L'uscita include WAV, MP3 e `composition.json` sotto `works/audio_studio/`, con player e download nell'interfaccia.
I controlli rilevano durata insufficiente, silenzi prolungati e loop quasi identici; la valutazione musicale
resta affidata all'ascolto. Ogni genere associa un tema per il successivo video.

La sezione Voci mantiene configurazione dell'assistente, sintesi e libreria vocale. L'identificativo interno
`sigma_voice_studio` e le API TTS restano compatibili; le nuove rotte sono `/api/audio-studio/music/*`.
I tool MCP `list_music_presets`, `generate_study_music` e `music_jobs` espongono lo stesso flusso agli agenti.

La scheda Radio usa il lettore già presente in Sigma Studio. Il comando Audio e radio si trova negli Strumenti AI;
il player non viene più imposto nell'angolo della pagina. Le composizioni si possono ricomporre con feedback
oppure rifinire su una nuova copia (alti più morbidi, timbro caldo o tempo ridotto del 5%) senza perdere l'originale.
`revise_study_music` espone queste operazioni agli agenti. La ricomposizione può cambiare melodia e arrangiamento;
la rifinitura DSP agisce sull'audio esistente e non separa i singoli strumenti.

L'Editor audio importa file o composizioni della libreria in progetti multitraccia con forme d'onda.
Permette taglio, divisione, duplicazione, spostamento, volume, pan, dissolvenze, muto e annullamento.
Le modifiche sono non distruttive: le sorgenti restano conservate e il mix WAV viene esportato separatamente.
Il limite è 32 clip e un'ora per progetto; l'upload a blocchi accetta fino a 1 GB per file.

Le nuove tracce da prompt usano ACE-Step e i riferimenti BPM/tonalità del progetto (5–120 secondi).
Questi riferimenti non modificano le registrazioni già presenti. La generazione non separa gli strumenti
e può includere altri suoni: ascoltare e regolare i livelli prima di esportare.

Da un mix aggiornato si prepara una produzione VideoStudio: scena breve ripetuta o sequenza di scene.
La colonna sonora approvata viene copiata nel progetto video e non rigenerata; il montaggio finale deve
coincidere con la sua durata. Il render si avvia in VideoStudio e la bozza non consuma la GPU.
Gli agenti dispongono di `audio_projects`, `create_audio_project`, `edit_audio_project`,
`render_audio_project` e `audio_to_video`, con gli stessi controlli sulle revisioni e gli stessi job persistenti.

La libreria musicale mostra anche il video associato: player, download MP4 e apertura della produzione.
La preparazione del video permette di scegliere Anime, Realistico, Illustrato o Cartone 3D;
il genere configura anche il modello del fotogramma iniziale.
«Modifica nell'editor» riprende il progetto già collegato al brano. Il preset Palestra usa un arrangiamento
elettronico energico e 128 BPM predefiniti, mantenendo controlli di durata, silenzio e ripetizioni.
I video con una scena ripetuta raccordano il confine del ciclo con una breve dissolvenza; non viene
moltiplicata la generazione video per coprire ogni minuto della sessione.
