# Argomenti, Knowledge Graph & File Creation MCP — Sigma Studio Module

Modulo modulare per la gestione completa di **Argomenti**, **Knowledge Graph**, **Nodi di Conoscenza** e **Tool MCP di Creazione File** in **Sigma Studio**.

---

## 🎯 Architettura & Responsabilità

Mentre il **Kernel Base di Sigma Studio** mantiene esclusivamente il **SigmaEngine** e la **Chat Pura ad altissime prestazioni**, il modulo `sigma_knowledge` fornisce tutti gli strumenti concettuali e di persistenza dei file su disco:

1. **🛠️ Server MCP di Creazione & Gestione File (`TopicMCPServer`)**:
   - `create_file`: creazione sicura di file in sandbox `data/` con **validazione sintattica AST** per codice Python e **backup automatico**.
   - `edit_file`: modifica file con calcolo differenziale e snapshot di sicurezza.
   - `read_file`: lettura file e documenti della knowledge base.
   - `delete_file`: eliminazione protetta con backup storico.
   - `create_topic`: creazione di nuovi rami e categorie tematiche.
   - `list_topics`: scansione gerarchica in tempo reale di nodi e file.
   - `extract_and_save_files`: estrazione e parsing di file da risposte strutturate.
   - `search_knowledge_graph`: interrogazione semantica del grafo concettuale.
   - `query_vector_db`: ricerca vettoriale RAG locale.
   - `save_episodic_memory`: persistenza memoria episodica delle sessioni agente.

2. **📊 Visualizzazione D3.js & Knowledge Graph**:
   - Grafo interattivo force-directed delle relazioni tra argomenti.
   - Explorer avanzato dei nodi di conoscenza multi-formato (`.md`, `.py`, `.json`, `.pdf`, app interattive).

---

## 🚀 Installazione

Dall'**Hub Moduli & Estensioni** di Sigma Studio:
1. Cerca il modulo **"Argomenti, Knowledge Graph & File Creation MCP"**
2. Clicca su **Installa Modulo**

---

Parte dell'ecosistema modulare [SigmaStudio-Moduli](https://github.com/Sigmanih/SigmaStudio-Moduli).
