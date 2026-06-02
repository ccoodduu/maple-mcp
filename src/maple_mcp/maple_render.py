"""Render a Maple .mw document to images via Maple's own PDF export pipeline.

Unlike a screen grab, this renders the SAVED document through Maple's GUI export
classes (File > Export As > PDF) in a throwaway JVM. It reads the .mw from disk
into a fresh model, so it works even when the Maple window is hidden, occluded,
or closed entirely — and never steals focus.

    pages = render_pages("C:/path/doc.mw")   # -> list[bytes] (one PNG per page)
"""
import os
import subprocess
import tempfile
from pathlib import Path

from maple_mcp.maple_engine import MAPLE_ROOT

_JAVA = os.path.join(MAPLE_ROOT, "jre", "bin", "java.exe")
_JAVA_DIR = os.path.join(MAPLE_ROOT, "java")
_BIN = os.path.join(MAPLE_ROOT, "bin.X86_64_WINDOWS")
_LAUNCHER_JAR = str(Path(__file__).resolve().parent.parent.parent / "maple-export.jar")


def export_pdf(mw_path: str, timeout: int = 60) -> str:
    """Render a .mw to a temp PDF via Maple's export classes. Returns the PDF path.

    Raises RuntimeError if the export fails. Caller owns the returned temp file.
    """
    if not os.path.exists(_JAVA):
        raise RuntimeError(f"Maple JVM not found at {_JAVA}")
    if not os.path.exists(_LAUNCHER_JAR):
        raise RuntimeError(f"maple-export.jar not found at {_LAUNCHER_JAR}")

    fd, out_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    os.unlink(out_path)  # let Maple create it; we just reserved a unique name

    classpath = os.path.join(_JAVA_DIR, "*") + os.pathsep + _LAUNCHER_JAR
    env = dict(os.environ)
    env["PATH"] = _BIN + os.pathsep + env.get("PATH", "")

    # NON-headless: the PDF formatter builds invisible Swing owner frames and
    # throws HeadlessException otherwise. No visible window appears.
    proc = subprocess.run(
        [_JAVA, f"-Djava.library.path={_BIN}", "-cp", classpath,
         "MapleExport", mw_path, out_path],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, env=env,
    )

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        if os.path.exists(out_path):
            os.unlink(out_path)
        tail = (proc.stderr or proc.stdout or "").strip()[-600:]
        raise RuntimeError(f"PDF export failed (exit {proc.returncode}): {tail}")
    return out_path


def _parse_page_spec(spec: str, n: int) -> list[int]:
    """Parse a 1-based page spec ('2', '2-3', '1,3,5') to sorted 0-based indices."""
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            for i in range(int(a), int(b) + 1):
                out.add(i - 1)
        else:
            out.add(int(part) - 1)
    idxs = sorted(i for i in out if 0 <= i < n)
    if not idxs:
        raise ValueError(f"Page spec {spec!r} selects no pages (document has {n}).")
    return idxs


def render_pages(mw_path: str, match: str | None = None, pages: str | None = None,
                 max_pages: int | None = None, crop_to_match: bool = False,
                 zoom: float = 2.0, timeout: int = 60) -> list[bytes]:
    """Export the .mw to PDF and rasterize selected pages to PNG bytes.

    match         render only page(s) whose text contains this string. Note that
                  typeset MATH has no text layer — match on headings, labels, or
                  prose near the part you want.
    pages         explicit 1-based page spec ('2', '2-3', '1,3') — ignored if match.
    max_pages     cap the number of returned pages.
    crop_to_match render from the matched text downward instead of the whole page.

    Raises ValueError for no-match / empty selection; RuntimeError if export fails.
    """
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz

    pdf_path = export_pdf(mw_path, timeout=timeout)
    try:
        doc = fitz.open(pdf_path)
        n = doc.page_count
        mat = fitz.Matrix(zoom, zoom)
        out: list[bytes] = []

        if match:
            found = [(i, doc[i].search_for(match)) for i in range(n)]
            found = [(i, rects) for i, rects in found if rects]
            if not found:
                raise ValueError(
                    f"No page contains text matching {match!r}. Typeset math has no "
                    f"text layer — match on a heading, label, or prose instead.")
            if max_pages is not None:
                found = found[:max_pages]
            for i, rects in found:
                page = doc[i]
                clip = None
                if crop_to_match:
                    top = max(0, min(r.y0 for r in rects) - 12)
                    clip = fitz.Rect(0, top, page.rect.width, page.rect.height)
                out.append(page.get_pixmap(matrix=mat, clip=clip).tobytes("png"))
        else:
            idxs = _parse_page_spec(pages, n) if pages else list(range(n))
            if max_pages is not None:
                idxs = idxs[:max_pages]
            for i in idxs:
                out.append(doc[i].get_pixmap(matrix=mat).tobytes("png"))

        doc.close()
        return out
    finally:
        try:
            os.unlink(pdf_path)
        except OSError:
            pass
