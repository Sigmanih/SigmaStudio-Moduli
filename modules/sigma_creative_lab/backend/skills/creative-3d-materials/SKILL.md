---
name: creative-3d-materials
description: Genera modelli 3D, materiali e render con Creative MCP verificando tipo delle sorgenti e motore disponibile. Non genera video.
---

Consulta `list_creative_capabilities` e `list_creative_assets`. Distingui immagini, mesh e materiali: i loro identificativi non sono intercambiabili.

Usa `generate_3d` con l'immagine scelta oppure con una descrizione se e' richiesta anche la creazione della sorgente. Un generatore immagini disponibile non implica un motore 3D disponibile. Per nuovi pesi usa un workflow appropriato e verifica il profilo, senza cambiare backend per nascondere errori.

`generate_material` crea o deriva mappe; distingui mappe derivate da proprieta' fisiche misurate. Usa `render_3d` con una mesh valida e Blender disponibile, conservando i parametri richiesti.

Verifica gli asset restituiti prima di concatenare operazioni. Nel viewer usa statistiche reali della geometria. Un errore WebGL limita l'anteprima, non dimostra che il file sia corrotto: conserva il download e descrivi il problema osservato.

Conserva sorgenti e provenienza. Un render fallito non va presentato come riuscito ne' sostituito con una generica immagine sintetica.
