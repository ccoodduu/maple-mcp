r"""Out-of-tree rotating backup store for .mw documents.

Backups live under %LOCALAPPDATA%\maple-mcp\backups\<doc-id>\ — deliberately NOT
next to the document — so the user's assignment folder (often a synced OneDrive
directory) stays clean and free of .bak clutter. Each edit pushes the pre-edit
file as a sequenced, timestamped copy; undo pops the newest. A bounded ring keeps
the last RING_SIZE versions, giving multi-level undo without touching the work dir.
"""
import hashlib
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

RING_SIZE = 20


def _store_root() -> Path:
    # MAPLE_MCP_BACKUP_ROOT lets tests redirect the store away from the real
    # %LOCALAPPDATA% (set by the test suite to a temp dir).
    override = os.environ.get("MAPLE_MCP_BACKUP_ROOT")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "maple-mcp" / "backups"


def _doc_id(file_path: str) -> str:
    """Stable per-document folder name: sanitized stem + hash of the abs path
    (so two files with the same name never share a backup ring)."""
    abs_path = str(Path(file_path).resolve()).lower()
    digest = hashlib.md5(abs_path.encode("utf-8")).hexdigest()[:10]
    safe_stem = re.sub(r"[^A-Za-z0-9_-]", "_", Path(file_path).stem)[:40]
    return f"{safe_stem}-{digest}"


def _doc_dir(file_path: str) -> Path:
    d = _store_root() / _doc_id(file_path)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ring(file_path: str) -> list[Path]:
    """Backups for this document, OLDEST first. Names are zero-padded sequence +
    timestamp, so lexical order == chronological order."""
    return sorted(_doc_dir(file_path).glob("*.mw"), key=lambda p: p.name)


def _next_seq(backups: list[Path]) -> int:
    mx = 0
    for p in backups:
        m = re.match(r"(\d+)-", p.name)
        if m:
            mx = max(mx, int(m.group(1)))
    return mx + 1


def push(file_path: str) -> str | None:
    """Copy the current file onto the ring (sequenced + timestamped) and prune to
    RING_SIZE. Returns the new backup path, or None if the source doesn't exist."""
    src = Path(file_path)
    if not src.exists():
        return None
    backups = _ring(file_path)
    seq = _next_seq(backups)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = _doc_dir(file_path) / f"{seq:06d}-{ts}.mw"
    shutil.copy2(src, dst)
    for old in _ring(file_path)[:-RING_SIZE]:   # prune oldest beyond the ring
        try:
            old.unlink()
        except OSError:
            pass
    return str(dst)


def latest(file_path: str) -> str | None:
    backups = _ring(file_path)
    return str(backups[-1]) if backups else None


def restore_latest(file_path: str) -> bool:
    """Copy the newest backup over the document WITHOUT removing it (rollback)."""
    backups = _ring(file_path)
    if not backups:
        return False
    shutil.copy2(backups[-1], file_path)
    return True


def pop(file_path: str) -> str | None:
    """Restore the newest backup over the document and remove it from the ring
    (multi-level undo). Returns the restored-from name, or None if the ring is empty."""
    backups = _ring(file_path)
    if not backups:
        return None
    newest = backups[-1]
    shutil.copy2(newest, file_path)
    try:
        newest.unlink()
    except OSError:
        pass
    return newest.name


def discard(backup_path: str | None) -> None:
    """Delete a specific backup (used when an edit aborts and nothing changed, so
    no phantom undo step is left behind)."""
    if not backup_path:
        return
    try:
        Path(backup_path).unlink()
    except OSError:
        pass
