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


def _new_pdf_path() -> str:
    """Reserve a unique temp PDF name (and remove it so Maple can create it)."""
    fd, out_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    os.unlink(out_path)
    return out_path


def _export_pdf_via_agent(mw_path: str, timeout: int) -> str | None:
    """Render via the in-JVM agent (the user's running Maple). FAST — it reuses
    the already-warm JVM (no ~4s cold start) and keeps its display even when the
    screen is locked. Returns a PDF path, or None if the agent is unreachable
    (Maple not running / export command unavailable). Raises TimeoutError if the
    agent is reachable but the export hangs (e.g. a doc with live embedded
    components) — the standalone route would hang identically, so don't retry it."""
    import socket
    from maple_mcp.maple_reload import AGENT_PORT

    out_path = _new_pdf_path()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(("127.0.0.1", AGENT_PORT))
        s.sendall(f"export {mw_path}|{out_path}\n".encode())
        resp = s.recv(4096).decode().strip()
        s.close()
    except socket.timeout:
        if os.path.exists(out_path):
            os.unlink(out_path)
        raise TimeoutError("Maple export hung")
    except (ConnectionRefusedError, OSError):
        resp = None

    if resp == "ok" and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return out_path
    if os.path.exists(out_path):
        os.unlink(out_path)
    return None


def export_pdf(mw_path: str, timeout: int = 60) -> str:
    """Render a .mw to a temp PDF via Maple's export classes. Returns the PDF path.

    Prefers the in-JVM agent (the running Maple): ~3x faster (no JVM cold start)
    and works even with the screen locked. Falls back to a standalone export JVM
    when Maple isn't running. Raises RuntimeError if all routes fail.
    """
    try:
        via_agent = _export_pdf_via_agent(mw_path, timeout)
    except TimeoutError:
        raise RuntimeError(
            "Maple's export hung — the document may contain live embedded "
            "components (e.g. an embedded table). Try a smaller part with "
            "match= or pages=.")
    if via_agent:
        return via_agent
    return _export_pdf_standalone(mw_path, timeout)


def _export_pdf_standalone(mw_path: str, timeout: int = 60) -> str:
    """Render a .mw to a temp PDF in a throwaway Maple JVM. Needs an active,
    unlocked desktop session. Raises RuntimeError on failure."""
    if not os.path.exists(_JAVA):
        raise RuntimeError(f"Maple JVM not found at {_JAVA}")
    if not os.path.exists(_LAUNCHER_JAR):
        raise RuntimeError(f"maple-export.jar not found at {_LAUNCHER_JAR}")

    out_path = _new_pdf_path()

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
        combined = ((proc.stderr or "") + "\n" + (proc.stdout or ""))
        low = combined.lower()
        if ("headless" in low or "no screen device" in low
                or "does not have desktop access" in low):
            raise RuntimeError(
                "Maple's PDF export needs an active, unlocked desktop session, but "
                "none is available (the screen is locked, or this process has no "
                "display). Unlock the screen / keep the Windows session active and "
                "retry.")
        # Surface the FIRST exception line (the real cause), not the truncated tail.
        cause = next((ln.strip() for ln in combined.splitlines()
                      if "Exception" in ln or "Error" in ln), "")
        detail = cause or combined.strip()[:300] or f"exit {proc.returncode}"
        raise RuntimeError(f"PDF export produced no output: {detail}")
    return out_path


# Maple's PDF export embeds a per-document font SUBSET with no ToUnicode map for
# "exotic" glyphs, so the text layer mangles them — and the mangling is
# position-in-subset dependent, NOT a fixed per-char map: the SAME em-dash extracts
# as 'R' in one document and 'å' in another, and '·' can become ',' or 's' within a
# single doc. ASCII and Latin-1 letters (incl. æøå) extract fine; dashes, math
# operators (× · ± ≈ ≤ ≥ ≠ √ ∞ ∫ ∑ → ⇒), Greek (α…Ω) and symbols (© § €) do not —
# some even collapse to a space. So we can't substitute a known character; instead we
# match fuzzily, turning every non-ASCII char (plus the ASCII hyphen, which users
# conflate with — –) into a single-char wildcard anchored by the surrounding ASCII
# text, which always extracts correctly.
_DASHY = set("-‐‑‒–—―−")   # ASCII hyphen + dashes: users type these interchangeably


def _char_stream(page):
    """Flatten a page's chars into (text, [bbox]) in reading order (rawdict)."""
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    chars, boxes = [], []
    for block in page.get_text("rawdict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for c in span.get("chars", []):
                    chars.append(c["c"])
                    boxes.append(fitz.Rect(c["bbox"]))
    return "".join(chars), boxes


def _fuzzy_rects(page, needle: str) -> list:
    """Locate `needle` on the page, tolerating Maple's dash/minus glyph mangling.
    Returns a one-element list with the union bbox of the match, or []."""
    import re as _re
    s, boxes = _char_stream(page)
    if not s:
        return []
    parts = []
    for ch in needle:
        if ch.isspace():
            parts.append(r"\s+")
        elif ord(ch) > 0x7E or ch in _DASHY:
            parts.append(r".")           # whatever the glyph mangled to (incl. a space)
        else:
            parts.append(_re.escape(ch))
    m = _re.compile("".join(parts)).search(s)
    if not m or m.end() == m.start():
        return []
    span = boxes[m.start():m.end()]
    rect = span[0]
    for b in span[1:]:
        rect |= b
    return [rect]


def _anchor_segments(needle: str) -> list[str]:
    """Longest-first runs of reliably-extracted ASCII text (split on any non-ASCII
    char, '/', or '|'), for a last-ditch exact search when fuzzy matching fails."""
    import re as _re
    return sorted(
        {s.strip() for s in _re.split(r'(?:[^\x00-\x7E]|[/|])+', needle)
         if len(s.strip()) >= 4},
        key=len, reverse=True)


def _match_rects_on_page(page, needles: list[str], decoded: str) -> list:
    """Rects for the first strategy that hits on this page: exact search of the
    given needles, then glyph-mangling-aware fuzzy match, then longest ASCII run."""
    for cand in needles:
        r = page.search_for(cand)
        if r:
            return r
    r = _fuzzy_rects(page, decoded)
    if r:
        return r
    for seg in _anchor_segments(decoded):
        r = page.search_for(seg)
        if r:
            return r
    return []


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
            # Try the literal match, then a version with \uXXXX escapes decoded
            # (a client may pass "bevægelse" un-decoded instead of "bevægelse").
            import re as _re
            decoded = _re.sub(r'\\u([0-9a-fA-F]{4})',
                              lambda m: chr(int(m.group(1), 16)), match)
            needles = [match] + ([decoded] if decoded != match else [])
            # Per page, try exact search, then dash-aware fuzzy match (em-dash etc.
            # mangle in the PDF text layer), then a dash-free segment.
            found = [(i, rects) for i in range(n)
                     for rects in [_match_rects_on_page(doc[i], needles, decoded)]
                     if rects]
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
