# ==============================================================================
# sigma_knowledge/backend/file_extractor.py — Extraction, Validation & Auto-saving of Files
# Sigma Studio — Modulo Argomenti & Knowledge
# ==============================================================================
"""Extracts code blocks, markdown documents, and scripts from LLM responses,
performs AST syntax validation on Python files, creates automatic backups,
computes diffs, and writes to disk inside sandbox boundaries (data/).
"""

import os
import re
import ast
from core.logger import get_logger
from core.data_handler import rebuild_modules_meta
from core.backup_manager import create_backup
from core.task_handler import _compute_diff

log = get_logger(__name__)


def _normalize_data_path(raw_path: str) -> str:
    """Normalize extracted raw path ensuring it starts with data/."""
    clean = raw_path.strip().strip("`'\"").replace("\\", "/")
    clean = re.sub(r"^\.?/+", "", clean)
    clean = re.sub(r"^(?:📄\s*)", "", clean).strip()
    if not clean.startswith("data/"):
        clean = f"data/{clean}"
    return clean


def _ensure_module_subfolders(file_path: str) -> None:
    """Ensure the target directory for file_path exists dynamically."""
    parent_dir = os.path.dirname(os.path.abspath(file_path))
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)


def _determine_default_module_path(topic_slug: str, folder: str, fname: str) -> str:
    """Determine clean dynamic path for a topic file."""
    return f"data/{topic_slug}/{fname}"


def _generate_files_summary(created_paths: list[str], full_response: str) -> str:
    """Generate an elegant markdown summary description of the created files."""
    if not created_paths:
        return ""
    
    summary_parts = []
    summary_parts.append("📁 **File creati e salvati su disco:**")
    
    for path in created_paths:
        file_desc = ""
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    content = fh.read()
                h_match = re.search(r'^#\s+(.+)', content, re.MULTILINE)
                title = h_match.group(1).strip() if h_match else os.path.basename(path)
                
                para_match = re.search(r'^(?:#+\s+[^\n]+\n+)+([\s\S]{20,120}?)(?=\n#|\Z)', content)
                short_text = para_match.group(1).replace('\n', ' ').strip() if para_match else ""
                if short_text:
                    file_desc = f" — *{short_text[:100]}...*"
                summary_parts.append(f"- **{title}**: `{path}`{file_desc}")
            except Exception:
                summary_parts.append(f"- `{path}`")
        else:
            summary_parts.append(f"- `{path}`")
            
    return "\n\n" + "\n".join(summary_parts)


def _format_file_creation_summary(ai_response, created_paths) -> str:
    """Format final user message preserving full code blocks and appending disk save summary."""
    if isinstance(ai_response, list) and isinstance(created_paths, str):
        ai_response, created_paths = created_paths, ai_response
    
    if not isinstance(ai_response, str):
        ai_response = str(ai_response or "")
    if not isinstance(created_paths, list):
        created_paths = [str(created_paths)] if created_paths else []

    if not created_paths:
        return ai_response
    
    clean_text = ai_response.strip()
    file_summary = _generate_files_summary(created_paths, ai_response)
    
    if "File creati e salvati su disco" in clean_text or "File salvati con successo su disco" in clean_text:
        return clean_text
    
    return f"{clean_text}\n\n{file_summary}".strip()


def _strip_reasoning_monologue(text: str) -> str:
    """Strip AI thinking monologues so file extraction operates on the final generated response text."""
    if not text:
        return ""
    text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE)
    return text.strip()


def _extract_and_create_files_from_text(clean_response: str, prompt_topic: str = "", force_save: bool = False) -> tuple[list[str], list[dict]]:
    """Extract multiple files from markdown text response, save them with backup, AST validation, and diff tracking."""
    clean_response = _strip_reasoning_monologue(clean_response)
    created_paths = []
    actions_log = []

    def _save_file_with_backup(clean_path: str, file_content: str):
        if not clean_path or not file_content.strip():
            return
        
        clean_path = _normalize_data_path(clean_path)
        filename = os.path.basename(clean_path)
        
        # Strict validation: reject placeholders, dot-only extensions, double slashes
        if (
            '<' in clean_path or '>' in clean_path
            or filename.startswith('.')
            or len(filename.split('.')[0]) < 1
            or clean_path.endswith('/.md')
            or clean_path.endswith('/.py')
            or clean_path.endswith('/.html')
            or '01_...' in clean_path
            or clean_path in created_paths
        ):
            log.warning("Rejected invalid/placeholder file path extraction: %s", clean_path)
            return

        # AST syntax check for Python files to avoid saving corrupt code
        if clean_path.endswith('.py'):
            try:
                ast.parse(file_content.strip(), filename=clean_path)
            except SyntaxError as syn_err:
                log.warning("Rejected Python file with SyntaxError (%s): %s", syn_err, clean_path)
                return

        backup_id = create_backup(clean_path, "chat_save")
        old_content = ""
        if os.path.exists(clean_path):
            try:
                with open(clean_path, "r", encoding="utf-8") as f:
                    old_content = f.read()
            except Exception:
                pass

        _ensure_module_subfolders(clean_path)
        with open(clean_path, "w", encoding="utf-8") as f:
            f.write(file_content)

        created_paths.append(clean_path)
        diff_text = _compute_diff(old_content, file_content)
        actions_log.append({
            "type": "edit_file" if old_content else "create_file",
            "path": clean_path,
            "success": True,
            "backup_id": backup_id,
            "diff": diff_text
        })
        log.info("Auto-extracted & backed-up file: %s (%d chars)", clean_path, len(file_content))

    # Pattern 1: Fenced codeblock with path in info-string or header
    pattern_fenced = re.findall(r'(?:(?:Path|File|Percorso):\s*`?(?:📄\s*)?([^\n`\(\)]+\.[a-zA-Z0-9]+)`?\s*\n+)?```([a-zA-Z0-9_-]*)(?:\s+(?:file=|path=)?([^\n\r`]+))?\n([\s\S]*?)```', clean_response)
    for header_path, lang, inline_path, code in pattern_fenced:
        target_path = (inline_path or header_path or "").strip()
        if target_path and len(code.strip()) > 10:
            _save_file_with_backup(target_path, code)

    if created_paths:
        try:
            rebuild_modules_meta()
        except Exception as exc:
            log.warning("Failed to rebuild modules_meta after extraction: %s", exc)

    return created_paths, actions_log
