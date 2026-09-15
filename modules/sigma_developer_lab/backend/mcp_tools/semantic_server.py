"""Server MCP per la ricerca semantica del codice sorgente.

Implementa una ricerca basata su TF-IDF + cosine similarity (fallback puro,
senza dipendenze esterne) che permette di trovare codice per significato
es. 'gestione errori di rete' anziché solo testo esatto.

L'indice persiste in var/semantic_index/ ed è ricreabile.
"""

import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.logger import get_logger
from core.mcp.base_server import BaseMCPServer

logger = get_logger(__name__)

# Percorso dell'indice (ricreabile, non in data/ o config/)
INDEX_DIR = Path("var/semantic_index")
INDEX_FILE = INDEX_DIR / "index.json"

# Estensioni da indicizzare
CODE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".css", ".html", ".md", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}

# Directory da escludere dall'indicizzazione
EXCLUDE_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build", ".next", ".cache", "store", "config"}


def _tokenize(text: str) -> List[str]:
    """Tokenizza il testo in parole minuscole, rimuovendo punteggiatura."""
    # Estrae parole alfanumeriche di lunghezza >= 2
    tokens = re.findall(r"[a-zA-Z0-9_]{2,}", text.lower())
    return tokens


def _compute_tf(tokens: List[str]) -> Dict[str, float]:
    """Calcola la Term Frequency (frequenza relativa)."""
    counter = Counter(tokens)
    total = len(tokens) if tokens else 1
    return {term: count / total for term, count in counter.items()}


def _compute_idf(documents_tokens: List[List[str]]) -> Dict[str, float]:
    """Calcola l'Inverse Document Frequency."""
    n_docs = len(documents_tokens)
    if n_docs == 0:
        return {}
    
    doc_freq = Counter()
    for tokens in documents_tokens:
        unique_terms = set(tokens)
        for term in unique_terms:
            doc_freq[term] += 1
    
    # IDF con smoothing: log((N + 1) / (df + 1)) + 1
    idf = {}
    for term, df in doc_freq.items():
        idf[term] = math.log((n_docs + 1) / (df + 1)) + 1.0
    return idf


def _tfidf_vector(tf: Dict[str, float], idf: Dict[str, float]) -> Dict[str, float]:
    """Calcola il vettore TF-IDF."""
    return {term: tf_val * idf.get(term, 0.0) for term, tf_val in tf.items()}


def _cosine_similarity(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
    """Calcola la similarità di cosine tra due vettori sparse."""
    if not vec_a or not vec_b:
        return 0.0
    
    # Calcola il prodotto scalare (solo termini comuni)
    common_terms = set(vec_a.keys()) & set(vec_b.keys())
    dot_product = sum(vec_a[term] * vec_b[term] for term in common_terms)
    
    # Norme
    norm_a = math.sqrt(sum(v ** 2 for v in vec_a.values()))
    norm_b = math.sqrt(sum(v ** 2 for v in vec_b.values()))
    
    if norm_a == 0 or norm_b == 0:
        return 0.0
    
    return dot_product / (norm_a * norm_b)


class SemanticMCPServer(BaseMCPServer):
    """Server MCP per la ricerca semantica del codice."""
    
    def __init__(self) -> None:
        super().__init__(name="Semantic Code Search", version="1.0.0", description="Ricerca semantica del codice sorgente")
        self._index: Optional[Dict[str, Any]] = None
        self._load_index()
        
        # Registra i tool con handler
        self.register_tool(
            name="semantic_search",
            description="Cerca nel codice sorgente per significato (non solo testo esatto). "
                       "Esempio: 'gestione errori di rete' o 'validazione input'. "
                       "Restituisce file, righe e snippet ordinati per rilevanza.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "La query semantica in linguaggio naturale"},
                    "top_k": {"type": "integer", "description": "Numero massimo di risultati (default: 10)", "default": 10}
                },
                "required": ["query"]
            },
            handler=lambda query, top_k=10: self._semantic_search(query, top_k)
        )
        
        self.register_tool(
            name="index_codebase",
            description="Costruisce o aggiorna l'indice semantico del codice sorgente. "
                       "Scansiona tutti i file di codice nel workspace e crea un indice TF-IDF.",
            input_schema={
                "type": "object",
                "properties": {},
                "required": []
            },
            handler=lambda: self._build_index()
        )
        
        self.register_tool(
            name="index_status",
            description="Mostra lo stato dell'indice semantico: se esiste, quando è stato creato, quanti file contiene.",
            input_schema={
                "type": "object",
                "properties": {},
                "required": []
            },
            handler=lambda: self._get_index_status()
        )
    
    def _load_index(self) -> None:
        """Carica l'indice dal disco se esiste."""
        if INDEX_FILE.exists():
            try:
                with open(INDEX_FILE, "r", encoding="utf-8") as f:
                    self._index = json.load(f)
                logger.info("Indice semantico caricato da %s (%d documenti)", INDEX_FILE, len(self._index.get("documents", [])))
            except Exception as e:
                logger.warning("Errore nel caricamento dell'indice: %s", e)
                self._index = None
        else:
            self._index = None
    
    def _save_index(self) -> None:
        """Salva l'indice su disco."""
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        with open(INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(self._index, f, ensure_ascii=False, indent=2)
        logger.info("Indice semantico salvato in %s (%d documenti)", INDEX_FILE, len(self._index.get("documents", [])))
    
    def _build_index(self) -> Dict[str, Any]:
        """Costruisce l'indice TF-IDF del codice sorgente."""
        logger.info("Costruzione indice semantico...")
        
        # Raccolta documenti
        documents: List[Dict[str, Any]] = []
        all_tokens: List[List[str]] = []
        
        base = Path(".")
        for file in base.rglob("*"):
            # Filtra directory escluse e file nascosti
            parts = file.parts
            if any(p in EXCLUDE_DIRS or p.startswith(".") for p in parts[:-1]):
                continue
            if not file.is_file():
                continue
            ext = file.suffix.lower()
            if ext not in CODE_EXTENSIONS:
                continue

            # Salta file troppo grandi (> 500KB)
            try:
                if file.stat().st_size > 500 * 1024:
                    continue
            except OSError:
                continue

            # Legge il file
            try:
                content = file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            # Tokenizza
            tokens = _tokenize(content)
            if not tokens:
                continue

            # Estrae snippet (prime 3 righe non vuote)
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            snippet = "\n".join(lines[:3])

            doc = {
                "path": str(file),
                "tokens": tokens,
                "snippet": snippet,
                "size": len(content)
            }
            documents.append(doc)
            all_tokens.append(tokens)
        
        # Calcola IDF
        idf = _compute_idf(all_tokens)
        
        # Calcola vettori TF-IDF per ogni documento
        for doc in documents:
            tf = _tfidf_vector(doc["tokens"], idf)
            doc["vector"] = tf
            del doc["tokens"]  # Libera memoria
        
        self._index = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "documents": documents,
            "idf": idf,
            "total_documents": len(documents)
        }
        
        self._save_index()
        logger.info("Indice costruito: %d documenti", len(documents))
        return self._index
    
    def _semantic_search(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """Esegue la ricerca semantica."""
        if not self._index or not self._index.get("documents"):
            # Costruisce l'indice se non esiste
            self._build_index()
        
        if not self._index or not self._index.get("documents"):
            return []
        
        # Tokenizza la query
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        
        # Calcola TF-IDF della query
        idf = self._index["idf"]
        query_tf = _compute_tf(query_tokens)
        query_vector = {term: tf_val * idf.get(term, 0.0) for term, tf_val in query_tf.items()}
        
        # Calcola similarità con ogni documento
        results = []
        for doc in self._index["documents"]:
            score = _cosine_similarity(query_vector, doc["vector"])
            if score > 0.01:  # Soglia minima
                results.append({
                    "path": doc["path"],
                    "score": round(score, 4),
                    "snippet": doc["snippet"]
                })
        
        # Ordina per score decrescente
        results.sort(key=lambda x: x["score"], reverse=True)
        
        return results[:top_k]
    
    def handle_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Gestisce le chiamate ai tool."""
        if tool_name == "semantic_search":
            query = arguments.get("query", "")
            top_k = arguments.get("top_k", 10)
            results = self._semantic_search(query, top_k)
            return {
                "query": query,
                "results": results,
                "total_results": len(results)
            }
        
        elif tool_name == "index_codebase":
            index = self._build_index()
            return {
                "status": "success",
                "total_documents": index["total_documents"],
                "created_at": index["created_at"]
            }
        
        elif tool_name == "index_status":
            if not self._index:
                return {
                    "exists": False,
                    "message": "Indice non costruito. Usa index_codebase per crearlo."
                }
            
            return {
                "exists": True,
                "created_at": self._index["created_at"],
                "total_documents": self._index["total_documents"]
            }
        
        else:
            raise ValueError(f"Tool sconosciuto: {tool_name}")
