---
name: creative-images
description: Crea, modifica e ingrandisce immagini tramite Creative MCP rispettando modello e sorgenti scelti. Non gestisce film o narrazione.
---

Consulta `list_creative_capabilities` per modelli, task e motori disponibili; usa `list_creative_assets` per le sorgenti esistenti.

Un file scaricato non e' automaticamente eseguibile. Prepara un profilo in Modelli e skill collegando workflow, checkpoint e componenti; i profili verificati sono selezionabili come `workflow:<id>`. Una LoRA richiede un modello base e un workflow che la applichi. GGUF richiede un loader compatibile. Non scambiare componenti di architetture diverse.

Con `generate_image` conserva descrizione, modello e formato richiesti. Passa `backend` solo se e' stato scelto anche il motore. Un errore su una scelta esplicita non autorizza a usare un altro servizio: indica il nodo o componente mancante e correggilo prima di riprovare.

Usa `edit_image` per modificare una sorgente e `upscale_image` per ingrandirla. Verifica il risultato prima di affermare che identita' o dettagli siano preservati. `analyze_image` puo' assistere il controllo se un modello visivo e' disponibile; altrimenti presenta l'anteprima e dichiara il limite.

Concludi solo con successo esplicito, asset valido e URL restituito. Riporta modello e motore effettivi quando rilevanti; connessioni interrotte o stream privi di risultato non sono successi.
