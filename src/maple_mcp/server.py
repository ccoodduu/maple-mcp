import base64
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent, ImageContent

from maple_mcp.maple_engine import engine
from maple_mcp.maple_reload import reload_in_maple, save_in_maple, get_open_document_path
from maple_mcp.image_decode import decode_maple_image
from maple_mcp import document

mcp = FastMCP("maple-mcp")
_document_path: Path | None = None


def _get_path() -> Path | str:
    if _document_path and _document_path.exists():
        return _document_path
    return "No document set. Use set_document_path first."



def _png_to_image_content(png_data: bytes, max_width: int = 800,
                          quality: int = 70, small_px: int = 200_000) -> ImageContent:
    """PNG bytes -> ImageContent. Small images stay PNG (sharp text); large
    images downscale to max_width and re-encode as JPEG to keep payloads small."""
    from PIL import Image
    import io

    img = Image.open(io.BytesIO(png_data))
    if img.size[0] * img.size[1] < small_px:
        b64 = base64.b64encode(png_data).decode("ascii")
        return ImageContent(type="image", data=b64, mimeType="image/png")

    if img.size[0] > max_width:
        ratio = max_width / img.size[0]
        img = img.resize((max_width, int(img.size[1] * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return ImageContent(type="image", data=b64, mimeType="image/jpeg")


def _save_and_edit(edit_fn) -> str:
    path = _get_path()
    if isinstance(path, str):
        return path

    readback = edit_fn(str(path))
    reload_in_maple(str(path))

    if readback:
        return f"Done, reads as:\n{readback}"
    return "Done."


def _format_entries(entries: list[dict]) -> list[TextContent | ImageContent]:
    result = []
    text_lines = []

    def _flush_text():
        if text_lines:
            result.append(TextContent(type="text", text="\n".join(text_lines)))
            text_lines.clear()

    for entry in entries:
        t = entry.get("type")
        depth = entry.get("depth", 0)
        indent = "  " * depth

        if t == "image" and entry.get("encoded"):
            _flush_text()
            try:
                png_data = decode_maple_image(entry["encoded"])
                result.append(_png_to_image_content(png_data))
            except Exception:
                text_lines.append(f"{indent}[IMAGE: decode failed]")
        elif t == "section":
            level = entry.get("level", 1)
            section_indent = "  " * (level - 1)
            text_lines.append(f"{section_indent}{'#' * level} {entry.get('content', '')}")
        elif t == "title":
            text_lines.append(f"TITLE: {entry.get('content', '')}")
        elif t == "empty":
            text_lines.append("")
        else:
            content = entry.get("content", "")
            if isinstance(content, list):
                content = "; ".join(content)

            if len(content) > 500 or '<Equation' in content:
                content = content[:100] + "... [TRUNCATED]"

            prefix = "MAPLE> " if t == "code" else ""
            suffix = ""
            if entry.get("output"):
                suffix += f" -> {'; '.join(entry['output'])}"
            if entry.get("align"):
                suffix += f" [align:{entry['align']}]"

            text_lines.append(f"{indent}{prefix}{content}{suffix}")

    _flush_text()
    return result


@mcp.tool()
def set_document_path(file_path: str | None = None) -> str:
    """Set the path to the Maple document you're working on.

    If no path is given, automatically detects the currently open
    document from Maple's window title.

    Args:
        file_path: Full path to the .mw file, or None for auto-detect
    """
    global _document_path

    if file_path is None:
        detected = get_open_document_path()
        if detected:
            _document_path = Path(detected)
            return f"Auto-detected document: {detected}"
        return "Could not detect open document. Provide the file path manually."

    path = Path(file_path)
    if not path.exists():
        return f"File not found: {file_path}"
    if path.suffix.lower() != ".mw":
        return f"Not a .mw file: {file_path}"
    _document_path = path
    return f"Document set to: {path}"


@mcp.tool()
def read_document(start: int = 0, end: int | None = None) -> list[TextContent | ImageContent] | str:
    """Read the current Maple document.

    Auto-saves the document first, then returns the content as
    indented text showing section hierarchy:
      # Section        (level 1)
        text block     (inside section)
        ## Subsection  (level 2)
          text block   (inside subsection)

    Equations show as {{expr}}, executable as {!expr!},
    highlights as {color:R,G,B}text{/color}.
    Images are returned as inline image content.

    Args:
        start: First block to read (default: 0)
        end: Block to stop at (exclusive). None = read to end.
    """
    path = _get_path()
    if isinstance(path, str):
        return path

    save_in_maple()
    entries = document.read_document(str(path), start, end)
    if not entries:
        return "Document is empty."

    return _format_entries(entries)


@mcp.tool()
def execute(statement: str) -> str:
    """Execute a Maple statement and return the result.

    Persistent session — variables are preserved between calls.
    Does NOT modify the document. Use this to COMPUTE (differentiate, solve,
    integrate, evaluate); then write the RESULT into the document as display
    math. Commands like diff/solve/int/eval belong HERE, never inside {{}}.

    Args:
        statement: Maple expression (e.g. "diff(x^3-4*x+1, x)", "solve(x^2-1, x)")
    """
    return engine.execute(statement)


@mcp.tool()
def insert_after(match: str, items: list[dict],
                 section: str | None = None, occurrence: int | None = None) -> str:
    """Insert content after a matched block.

    MATCHING: Copy a long, unique substring (15+ chars) directly from
    read_document output. For section headings, include the # prefix.
    Matching a section heading inserts AFTER the entire section.
    Matching a text block inserts after just that block, inside its parent.

    Each item is a dict with 'type' and 'content':
      - {"type": "text", "content": "Text with {{inline_math}} and **bold**"}
      - {"type": "code", "content": "m = 1000*200/1000"}
      - {"type": "heading", "content": "a)", "level": 2}
      - {"type": "image", "path": "C:/path/to/image.png"}
      - {"type": "empty"}  (blank line)

    This is Maple Document mode — there are no code blocks.
    Use type "code" for executable 2D Math equations.
    Code must show a full calculation, NEVER bare numbers.

    Markup syntax (MAPLE syntax, NOT LaTeX):
      {{expr}}                      non-executable inline 2D Math
      {!expr!}                      executable 2D Math, output below
      {=expr=}                      executable 2D Math, inline output
      **bold**  *italic*  __underline__
      {color:R,G,B}text{/color}    highlight background
      [[unit]]                      unit in equations: [[kg]], [[J/(kg*degC)]]

    ALL math must use {{}} — never write math as plain text.
    ALL numbers with units must use {{200*[[kg]]}}, never "200 kg".
    Equations are NOT evaluated — {{3*4}} displays 3·4, not 12.
    Greek letters use Maple names: Delta, rho, Omega (not \\delta).
    Subscripts use [...]: c[p], V[water] (not c_p, V_water).
    Combine Greek+variable with *: Delta*T shows Δ·T (DeltaT shows literal text).
    Derivatives display as primes: f'(x), g''(x).

    Math blocks DISPLAY expressions; they do NOT run commands. To differentiate,
    solve, integrate, or evaluate, call `execute` FIRST, then write the RESULT
    as math. Do NOT put diff(), solve(), int(), or eval() inside {{}} or code —
    they do not typeset correctly. (Int(...) / Sum(...) with a CAPITAL letter are
    fine: they are inert display notation, not commands.)
    Coordinates/points: write in text ("punktet (2, 1)"), not as {{(2,1)}}.

    CRITICAL: Each {{}} must contain at most ONE = sign.
    {{a = b = c}} WILL FAIL. Use: {{a = b}} ⇔ {{c = d}}

    Maple syntax examples (DISPLAY, not commands):
      {{f(x) = x^3 - 4*x + 1}}    function expression
      {{f'(x) = 3*x^2 - 4}}        derivative result (computed via execute)
      {{Int(x^2, x = 0..3)}}      definite integral (capital I = display only)
      {{500*[[Omega]]}}           number with unit
      {{4180*[[J/(kg*degC)]]}}    compound unit

    Fractions: ALWAYS use (numerator)/(denominator) with parentheses.

    Args:
        match: Text substring to find the target block
        items: Content blocks to insert
        section: Scope search to blocks inside this section title
        occurrence: Which match to use if multiple (1-based)
    """
    return _save_and_edit(
        lambda p: document.insert_after(p, match, items, section, occurrence)
    )


@mcp.tool()
def insert_before(match: str, items: list[dict],
                  section: str | None = None, occurrence: int | None = None) -> str:
    """Insert content before a matched block.

    Same as insert_after but inserts BEFORE the matched block.
    Matching a section heading inserts before the entire section.

    Args:
        match: Text substring to find the target block
        items: Content blocks to insert
        section: Scope search to blocks inside this section title
        occurrence: Which match to use if multiple (1-based)
    """
    return _save_and_edit(
        lambda p: document.insert_before(p, match, items, section, occurrence)
    )


@mcp.tool()
def replace_block(match: str, items: list[dict],
                  section: str | None = None, occurrence: int | None = None) -> str:
    """Replace a matched block with new content.

    SAFETY: Refuses to replace a section that has children.
    Match a specific block inside the section instead.
    A .mw.bak backup is created before every edit.

    Args:
        match: Text substring to find the block to replace
        items: New content blocks (same format as insert_after)
        section: Scope search to blocks inside this section title
        occurrence: Which match to use if multiple (1-based)
    """
    return _save_and_edit(
        lambda p: document.replace_block(p, match, items, section, occurrence)
    )


@mcp.tool()
def delete_block(match: str, section: str | None = None,
                 occurrence: int | None = None,
                 delete_section: bool = False) -> str:
    """Delete a matched block.

    SAFETY: If the match hits a section heading, this will REFUSE to
    delete (to prevent accidentally removing an entire section with
    all its content). Set delete_section=True to explicitly confirm.

    Args:
        match: Text substring to find the block to delete
        section: Scope search to blocks inside this section title
        occurrence: Which match to use if multiple (1-based)
        delete_section: Must be True to delete an entire section
    """
    path = _get_path()
    if isinstance(path, str):
        return path
    document.delete_block(str(path), match, section, occurrence, delete_section)
    reload_in_maple(str(path))
    return "Done."


@mcp.tool()
def append_content(items: list[dict]) -> str:
    """Append content at the end of the document.

    Supports nested sections: use type "heading" to create sections.
    Sub-headings (higher level number) nest inside parent sections.

    Args:
        items: Content blocks to append (same format as insert_after)
    """
    return _save_and_edit(
        lambda p: document.insert_content(p, items)
    )


@mcp.tool()
def undo() -> str:
    """Undo the last edit (any insert, replace, or delete operation).

    Restores the document from the .mw.bak backup file.
    A backup is created before every edit operation.
    """
    path = _get_path()
    if isinstance(path, str):
        return path

    backup = path.with_suffix(".mw.bak")
    if not backup.exists():
        return "No backup found. Nothing to undo."

    import shutil
    shutil.copy2(backup, path)
    reload_in_maple(str(path))
    return f"Restored from backup. Document reloaded."


@mcp.tool()
def screenshot_maple(match: str | None = None, pages: str | None = None,
                     max_pages: int | None = None,
                     crop_to_match: bool = False) -> list[TextContent | ImageContent] | str:
    """Render the current document to images to verify how it looks in Maple.

    Renders the SAVED document through Maple's PDF export engine — the same
    output as File > Export As > PDF — and returns one image per page. This
    reflects exactly how equations, units, and layout appear in Maple, and works
    even if the Maple window is hidden, behind other windows, or closed.

    Use this after editing to visually confirm that formulas, units, and
    formatting rendered correctly.

    To save context, render only PART of the document:
      - match: render only the page(s) containing this text. Typeset math has no
        text layer, so match on a heading, label, or prose (e.g. "Opgave 1.5.7",
        "Beregning:", "C) Plus-minus") near the part you want to see.
      - pages: explicit 1-based page spec — "2", "2-3", or "1,3" (ignored if match).
      - crop_to_match: with match, render from the matched line downward instead
        of the whole page (tighter image, least context).
    With no arguments, returns every page.

    Args:
        match: Render only page(s) whose text contains this string.
        pages: 1-based page selection like "2", "2-3", "1,3".
        max_pages: Cap the number of pages returned.
        crop_to_match: Crop to the matched region (only with match).
    """
    path = _get_path()
    if isinstance(path, str):
        return path

    save_in_maple()

    from maple_mcp import maple_render
    try:
        rendered = maple_render.render_pages(
            str(path), match=match, pages=pages,
            max_pages=max_pages, crop_to_match=crop_to_match)
    except ValueError as e:
        return str(e)
    except Exception as e:
        msg = str(e)
        # A locked/headless session breaks both PDF export AND a screen grab,
        # so surface the actionable message rather than a black fallback image.
        if "desktop session" in msg:
            return msg
        return _window_grab_fallback(msg)

    if not rendered:
        return "Render produced no pages."
    return [_png_to_image_content(p, max_width=1100, quality=80) for p in rendered]


def _window_grab_fallback(reason: str) -> list[TextContent | ImageContent] | str:
    """Last-resort screen grab of the Maple window, used only if PDF rendering
    is unavailable. Fragile: captures whatever pixels occupy the window's screen
    rectangle, so it only shows the visible area and fails if Maple is occluded,
    minimized, or closed."""
    note = (f"PDF render unavailable ({reason}); showing a live-window screenshot "
            f"instead. This captures only the visible part of the Maple window.")
    try:
        import ctypes
        from ctypes import wintypes
        from PIL import ImageGrab
        import io

        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW("AutoHotkeyGUI", None) or \
            user32.FindWindowW("SunAwtFrame", None)
        if not hwnd:
            return f"Could not render document ({reason}) and no Maple window to grab."

        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        img = ImageGrab.grab((rect.left, rect.top, rect.right, rect.bottom))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return [
            TextContent(type="text", text=note),
            ImageContent(type="image", data=b64, mimeType="image/png"),
        ]
    except Exception:
        return f"Could not render document: {reason}"


@mcp.resource("maple://help/{topic}")
def maple_help(topic: str) -> str:
    """Get Maple help for a topic."""
    return engine.get_help(topic)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
