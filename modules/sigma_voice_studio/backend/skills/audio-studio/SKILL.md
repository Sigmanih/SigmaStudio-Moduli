---
name: audio-studio
description: Compone basi strumentali in AudioStudio con preset lo-fi, ambient, piano e cyber ambient; segue i lavori e consegna anteprime WAV e MP3.
---

Leggi `list_music_presets` per generi e disponibilità del motore locale. Per una richiesta di prova usa `generate_study_music` con `duration=120`; rispetta una durata diversa scelta esplicitamente dall'utente. Le durate supportate sono 120, 300, 900 e 1800 secondi.

Segui la composizione con `music_jobs`. Un identificativo di job o uno stato in coda non sono un risultato: consegna i percorsi WAV e MP3 solo dopo `status=done`. In caso di errore indica la causa; non avviare automaticamente altre composizioni identiche.

Le basi sono strumentali. Scegli il preset richiesto e usa `prompt`, BPM e seed solo per le indicazioni musicali dell'utente. I controlli tecnici su durata, silenzi e ripetizioni non dimostrano qualità artistica o benefici per la concentrazione: proponi l'ascolto dell'anteprima.

Il tema visivo del risultato descrive l'accompagnamento previsto; non dichiarare generato un video se è presente soltanto l'audio. Le sessioni lunghe e l'eventuale pubblicazione seguono la richiesta dell'utente.

Per cambiare una base usa `revise_study_music` con `source_job`: `feedback` ricompone un nuovo brano, mentre `treatment=soft|warm|slower` applica una rifinitura alla registrazione esistente. Entrambi conservano l'originale. Non promettere isolamento di strumenti o conservazione della melodia quando ricomponi con feedback.
