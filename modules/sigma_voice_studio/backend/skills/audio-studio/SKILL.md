---
name: audio-studio
description: Compone basi strumentali in AudioStudio con preset studio e palestra; monta le tracce e collega i video ai brani della libreria.
---

Leggi `list_music_presets` per generi e disponibilità del motore locale. Per una richiesta di prova usa `generate_study_music` con `duration=120`; rispetta una durata diversa scelta esplicitamente dall'utente. Le durate supportate sono 120, 300, 900 e 1800 secondi.

Segui la composizione con `music_jobs`. Un identificativo di job o uno stato in coda non sono un risultato: consegna i percorsi WAV e MP3 solo dopo `status=done`. In caso di errore indica la causa; non avviare automaticamente altre composizioni identiche.

Le basi sono strumentali. Scegli il preset richiesto e usa `prompt`, BPM e seed solo per le indicazioni musicali dell'utente. I controlli tecnici su durata, silenzi e ripetizioni non dimostrano qualità artistica o benefici per la concentrazione: proponi l'ascolto dell'anteprima.

Il tema visivo del risultato descrive l'accompagnamento previsto; non dichiarare generato un video se è presente soltanto l'audio. Le sessioni lunghe e l'eventuale pubblicazione seguono la richiesta dell'utente.

`gym_energy` crea musica energica per l'allenamento (128 BPM predefiniti). Per una sessione completa chiedi o concorda la durata; non sostituirla con una breve anteprima. Usa riferimenti di genere e arrangiamento senza copiare melodie, testi o registrazioni esistenti. I video collegati appaiono in `music_jobs` con stato e URL solo quando disponibili; una bozza o un render in corso non sono una consegna completa.

Quando il video deve mostrare studio attivo o esercizi, usa `audio_to_video` con `mode=varied` e `activity=study|workout`. Il piano prepara otto azioni distinte, inquadrature adatte e luci diverse; il montaggio riusa le clip verificate in un ordine variato, senza ripetizioni consecutive. Non descriverlo come trenta minuti di riprese tutte uniche. `mode=loop` è adatto solo quando l'utente vuole esplicitamente un ambiente ripetuto. Prima del render rileggi le azioni in VideoStudio; non accettare clip ferme o con azioni sbagliate come risultato riuscito. Le musiche già approvate restano conservate.

Controlla la posa del primo fotogramma separatamente dal movimento richiesto. Per una clip dubbia ricontrolla il video esistente prima di rigenerarlo. La revisione visiva motivata è ammessa soltanto dopo aver esaminato la clip o una sequenza adeguata dei suoi fotogrammi; non usarla per superare un errore reale o sbloccare una produzione senza verifica. Dichiara quando la verifica è dell'agente, conserva il dissenso del giudice AI e la motivazione.

Per cambiare una base usa `revise_study_music` con `source_job`: `feedback` ricompone un nuovo brano, mentre `treatment=soft|warm|slower` applica una rifinitura alla registrazione esistente. Entrambi conservano l'originale. Non promettere isolamento di strumenti o conservazione della melodia quando ricomponi con feedback.

Per montare audio usa `audio_projects` e `create_audio_project`. Prima di `edit_audio_project` leggi la revisione corrente: taglio, posizione, volume in dB, pan, dissolvenze, muto, split, duplicazione e annullamento conservano le sorgenti. `settings` imposta BPM e tonalità come riferimenti per le generazioni successive; non traspone né modifica il tempo della registrazione esistente.

Per aggiungere uno strumento usa `render_audio_project` con `kind=layer`, prompt, posizione e durata da 5 a 120 secondi. Il modello genera audio nuovo usando i riferimenti musicali del progetto: non è separazione delle tracce e non garantisce isolamento o sincronizzazione perfetta con la registrazione. Fai ascoltare il risultato e regola il mix prima di proseguire.

Esporta con `render_audio_project` e `kind=mix`, attendi `music_jobs` completato e proponi l'ascolto. `audio_to_video` richiede il mix aggiornato e una descrizione della scena: prepara una produzione VideoStudio con una copia della colonna sonora approvata. La bozza non è un video generato. Il render si avvia da VideoStudio; il montaggio finale deve conservare il mix e coincidere con la sua durata.
