---
name: creative-pipelines
description: Esegue pipeline creative a nodi e restauri video completi con traduzioni e pacchetto YouTube, verificando dipendenze e risultati. Non installa nodi esterni implicitamente.
---

Leggi `list_creative_capabilities` per i nodi registrati e `list_creative_assets` per gli ingressi. Un file di pesi non aggiunge automaticamente un esecutore.

Prima di `run_creative_pipeline`, controlla sorgenti, porte, assenza di cicli e compatibilita' dei passaggi. Mantieni le scelte esplicite dei modelli. I profili ComfyUI devono superare la verifica di nodi, file e parametri prima dell'inferenza.

Avvia una sola esecuzione per richiesta. Se un nodo fallisce, conserva gli asset gia' prodotti e indica il punto fallito: non dichiarare completata l'intera automazione. Correggi la causa prima di riprovare; riusa i risultati validi quando il motore lo consente.

Interrompere l'attesa nel browser non equivale a fermare il calcolo. Controlla lo stato del motore prima di una nuova esecuzione. Distingui risultati parziali, operazioni ancora attive e completamento verificato.

Per un film importato usa `video_restore_pipeline`: il preset del canale definisce lingue, cartella di uscita e sigle. Scegli `content_type=silent` per i muti, `documentary` per conservare e trascrivere il parlato originale. Titolo, anno e fonte sono dati del singolo film, non del preset; non inventarli.

Il successo richiede master multilingua, audio separati, sottotitoli, miniatura, file di titolo e descrizione per lingua e `youtube_package.json`. Riusa i checkpoint verificati dopo un errore. Il pacchetto è locale: la pubblicazione sul canale richiede una richiesta esplicita e i doppiaggi vengono aggiunti tramite YouTube Studio → Lingue.
