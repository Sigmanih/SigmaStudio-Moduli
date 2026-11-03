---
name: creative-pipelines
description: Esegue pipeline creative a nodi e restauri video completi con traduzioni e pacchetto YouTube, verificando dipendenze e risultati. Non installa nodi esterni implicitamente.
---

Leggi `list_creative_capabilities` per i nodi registrati e `list_creative_assets` per gli ingressi. Un file di pesi non aggiunge automaticamente un esecutore.

Prima di `run_creative_pipeline`, controlla sorgenti, porte, assenza di cicli e compatibilita' dei passaggi. Mantieni le scelte esplicite dei modelli. I profili ComfyUI devono superare la verifica di nodi, file e parametri prima dell'inferenza.

Avvia una sola esecuzione per richiesta. Se un nodo fallisce, conserva gli asset gia' prodotti e indica il punto fallito: non dichiarare completata l'intera automazione. Correggi la causa prima di riprovare; riusa i risultati validi quando il motore lo consente.

Interrompere l'attesa nel browser non equivale a fermare il calcolo. Controlla lo stato del motore prima di una nuova esecuzione. Distingui risultati parziali, operazioni ancora attive e completamento verificato.

Per le clip generate, il controllo del movimento non certifica anatomia o qualità. Sono obbligatori controllo tecnico, controllo separato di anatomia/mani/oggetti e revisione di dettaglio registrata prima del montaggio. Il modello locale ha promosso immagini con arti aggiuntivi: non usare il suo voto come prova sufficiente. Guarda i fotogrammi a piena risoluzione e la clip, verificando lateralità, dita, collegamenti degli arti, prese, oggetti e continuità. Usa `video_integrity_check` e poi `video_integrity_review` solo dopo aver verificato direttamente i materiali. Un esito assente/incerto, un difetto o una revisione legata a un file diverso blocca export e pacchetto editoriale. Non conservare il tentativo meno difettoso dopo aver esaurito le rigenerazioni. Non descrivere un video come privo di errori soltanto perché supera controlli automatici campionati.

Ogni render finale o esportazione dell'editor prepara anche i materiali YouTube: miniatura 1280×720, titoli e descrizioni in arabo, inglese, italiano, spagnolo, tedesco, francese, portoghese e cinese, manifest e archivio ZIP. Controlla `publication.publication_ready`, non soltanto il successo del video. Un errore editoriale conserva il master: riprova dalla sezione Materiali per YouTube di VideoStudio senza rigenerare le clip. Le traduzioni riguardano i metadati, non aggiungono doppiaggi o sottotitoli. Per i video generati non usare testi o etichette da restauro. Cambiare il master o i suoi dati invalida la cache dei materiali.

Per un film importato usa `video_restore_pipeline`: il preset del canale definisce lingue, cartella di uscita e sigle. Scegli `content_type=silent` per i muti, `documentary` per conservare e trascrivere il parlato originale. Titolo, anno e fonte sono dati del singolo film, non del preset; non inventarli.

Il successo richiede master multilingua, audio separati, sottotitoli, miniatura, file di titolo e descrizione per lingua e `youtube_package.json`. Riusa i checkpoint verificati dopo un errore. Il pacchetto è locale: la pubblicazione sul canale richiede una richiesta esplicita e i doppiaggi vengono aggiunti tramite YouTube Studio → Lingue.

Usa soltanto sigle con `sigla_template.json` verificato: gli hash dei video devono coincidere con gli asset approvati. Il titolo dell'intro viene renderizzato dai dati del film e confrontato con un fotogramma del master. Non riutilizzare audio estratti da un master precedente all'aggiunta delle sigle. Una verifica tecnica non sostituisce la revisione editoriale di testi, miniatura e resa audiovisiva.
