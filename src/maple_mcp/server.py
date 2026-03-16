import base64
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent, ImageContent

from maple_mcp.maple_engine import engine
from maple_mcp.maple_reload import reload_in_maple, reload_in_maple_async, save_in_maple, get_open_document_path
from maple_mcp.image_decode import decode_maple_image
from maple_mcp import document

mcp = FastMCP("maple-mcp")
_document_path: Path | None = None


def _get_path() -> Path | str:
    if _document_path and _document_path.exists():
        return _document_path
    return "No document set. Use set_document_path first."


_needs_save = True


def _save_and_edit(edit_fn) -> str:
    global _needs_save
    path = _get_path()
    if isinstance(path, str):
        return path

    if _needs_save:
        save_in_maple()
        _needs_save = False

    edit_fn(str(path))

    # Fire-and-forget reload - LLM continues immediately
    reload_in_maple_async(str(path))
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
                b64 = base64.b64encode(png_data).decode("ascii")
                result.append(ImageContent(
                    type="image", data=b64, mimeType="image/png"
                ))
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
    Does NOT modify the document.

    Args:
        statement: Maple expression (e.g. "int(x^2, x)", "solve(x^2-1, x)")
    """
    return engine.execute(statement)


@mcp.tool()
def insert_after(match: str, items: list[dict],
                 section: str | None = None, occurrence: int | None = None) -> str:
    """Insert content after a matched block.

    Finds a block containing the match text and inserts new content after it.

    MATCHING: Copy a long, unique substring (15+ chars) directly from
    read_document output. Never use short generic matches like "a)"
    or "sin". For section headings, include the # prefix (e.g. "## b)"
    instead of "b)").

    SECTION HEADING vs TEXT BLOCK:
    - Match a section heading (e.g. "## b)") → inserts AFTER the
      entire section including all its children.
    - Match a text block → inserts after just that block, inside
      the same parent.
    To insert INSIDE an existing section, match a text block within
    it — not the heading.

    Each item is a dict with 'type' and 'content':
      - {"type": "text", "content": "Text with {{inline_math}} and **bold**"}
      - {"type": "code", "content": "solve(x^2-1, x)"}
      - {"type": "heading", "content": "Section Title", "level": 1}
      - {"type": "image", "path": "C:/path/to/image.png"}

    This is a Maple Document mode editor. There are NO code blocks.
    Type "code" creates a single executable 2D Math equation.
    For multiple statements, use multiple {"type": "code"} items.

    Formatting in text content (MAPLE syntax, NOT LaTeX):
      {{expr}}  - non-executable inline 2D Math
      {!expr!}  - executable 2D Math, output below
      {=expr=}  - executable 2D Math, inline output
      **bold**  *italic*  __underline__
      {color:R,G,B}text{/color}  - highlight background
      [[unit]]  - Maple unit in equations

    IMPORTANT: Use MAPLE syntax in equations, NOT LaTeX!
    Equations are NOT evaluated, they display exactly what you write.
    CRITICAL: Each {{}} must contain at most ONE = sign.
    {{a = b = c}} WILL FAIL and show as raw text.
    WRONG: {{x = Pi - Pi/6 = 5*Pi/6}}
    RIGHT: {{x = Pi - Pi/6}} ⇔ {{x = 5*Pi/6}}

    Safe equation examples:
      {{x^2 + 3*x - 4}}          - polynomial
      {{int(x^2, x)}}            - integral symbol
      {{Int(x^2, x = 0..3)}}     - definite integral with limits
      {{solve(x^2 - 1, x)}}      - solve expression
      {{f(x) = cos(x)}}          - equality
      {{3*4}}                     - shows 3·4 (not evaluated to 12)
      {{a/b + c/d}}               - fractions
      {{500*[[Omega]]}}           - with unit
      {{4180*[[J/(kg*degC)]]}}    - compound unit

    Highlight with equations:
      {color:255,255,0}**Svar: {{x = 42}}**{/color}
      → yellow highlighted bold text with inline equation

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
    return _save_and_edit(
        lambda p: document.delete_block(p, match, section, occurrence, delete_section)
    )


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
    reload_in_maple_async(str(path))
    return f"Restored from backup. Document reloaded."


@mcp.resource("maple://help/{topic}")
def maple_help(topic: str) -> str:
    """Get Maple help for a topic."""
    return engine.get_help(topic)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
