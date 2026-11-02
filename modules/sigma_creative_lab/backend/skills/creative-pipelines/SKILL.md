---
name: creative-pipelines
description: Progetta ed esegue pipeline di Creative MCP verificando nodi, dipendenze ed esiti. Non installa nodi esterni o modifica configurazioni implicitamente.
---

Leggi `list_creative_capabilities` per i nodi registrati e `list_creative_assets` per gli ingressi. Un file di pesi non aggiunge automaticamente un esecutore.

Prima di `run_creative_pipeline`, controlla sorgenti, porte, assenza di cicli e compatibilita' dei passaggi. Mantieni le scelte esplicite dei modelli. I profili ComfyUI devono superare la verifica di nodi, file e parametri prima dell'inferenza.

Avvia una sola esecuzione per richiesta. Se un nodo fallisce, conserva gli asset gia' prodotti e indica il punto fallito: non dichiarare completata l'intera automazione. Correggi la causa prima di riprovare; riusa i risultati validi quando il motore lo consente.

Interrompere l'attesa nel browser non equivale a fermare il calcolo. Controlla lo stato del motore prima di una nuova esecuzione. Distingui risultati parziali, operazioni ancora attive e completamento verificato.
