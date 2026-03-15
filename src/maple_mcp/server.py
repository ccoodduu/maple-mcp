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


def _save_edit_reload(edit_fn) -> str:
    path = _get_path()
    if isinstance(path, str):
        return path

    import time

    save_in_maple()
    time.sleep(0.5)

    edit_fn(str(path))

    if reload_in_maple(str(path)):
        return "Done. Reloaded in Maple."
    return "Done. Reopen the file in Maple to see changes."


def _format_entries(entries: list[dict]) -> list[TextContent | ImageContent]:
    result = []
    for entry in entries:
        t = entry.get("type")
        block_num = entry.get("block", "?")

        if t == "image" and entry.get("encoded"):
            try:
                png_data = decode_maple_image(entry["encoded"])
                b64 = base64.b64encode(png_data).decode("ascii")
                result.append(TextContent(type="text", text=f"[{block_num}] IMAGE:"))
                result.append(ImageContent(
                    type="image", data=b64, mimeType="image/png"
                ))
            except Exception:
                result.append(TextContent(
                    type="text", text=f"[{block_num}] IMAGE: (decode failed)"
                ))
        else:
            content = entry.get("content", "")
            if isinstance(content, list):
                content = "; ".join(content)
            prefix = ""
            if t == "title":
                prefix = "TITLE: "
            elif t == "section":
                prefix = f"{'#' * entry.get('level', 1)} "
            elif t == "heading":
                prefix = f"{'#' * entry.get('level', 1)} "
            elif t == "code":
                prefix = "MAPLE> "
            text = f"[{block_num}] {prefix}{content}"
            if entry.get("output"):
                text += f" -> {'; '.join(entry['output'])}"
            result.append(TextContent(type="text", text=text))

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

    Returns numbered blocks. Block numbers are for reference only —
    use content matching (match parameter) for editing operations.

    Args:
        start: First block to read (default: 0)
        end: Block to stop at (exclusive). None = read to end.
    """
    path = _get_path()
    if isinstance(path, str):
        return path

    save_in_maple()

    total = document.block_count(str(path))
    entries = document.read_document(str(path), start, end)
    if not entries:
        return "Document is empty."

    result = [TextContent(
        type="text",
        text=f"[Blocks {start}-{(end or total) - 1} of {total} total]"
    )]
    result.extend(_format_entries(entries))
    return result


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
    Match must be a substring of the block's text content.

    Each item is a dict with 'type' and 'content':
      - {"type": "text", "content": "Explanation with {{inline_math}} and **bold**"}
      - {"type": "code", "content": "solve(x^2-1, x)"}
      - {"type": "heading", "content": "Section Title", "level": 1}
      - {"type": "image", "path": "C:/path/to/image.png"}

    Formatting in text content:
      {{expr}}  - non-executable inline math
      {!expr!}  - executable math, output below
      {=expr=}  - executable math, inline output
      **bold**  *italic*  __underline__
      {color:red}text{/color}

    Args:
        match: Text substring to find the target block
        items: Content blocks to insert
        section: Scope search to blocks inside this section title
        occurrence: Which match to use if multiple (1-based)
    """
    return _save_edit_reload(
        lambda p: document.insert_after(p, match, items, section, occurrence)
    )


@mcp.tool()
def insert_before(match: str, items: list[dict],
                  section: str | None = None, occurrence: int | None = None) -> str:
    """Insert content before a matched block.

    Same as insert_after but inserts before the matched block.

    Args:
        match: Text substring to find the target block
        items: Content blocks to insert
        section: Scope search to blocks inside this section title
        occurrence: Which match to use if multiple (1-based)
    """
    return _save_edit_reload(
        lambda p: document.insert_before(p, match, items, section, occurrence)
    )


@mcp.tool()
def replace_block(match: str, items: list[dict],
                  section: str | None = None, occurrence: int | None = None) -> str:
    """Replace a matched block with new content.

    Args:
        match: Text substring to find the block to replace
        items: New content blocks (same format as insert_after)
        section: Scope search to blocks inside this section title
        occurrence: Which match to use if multiple (1-based)
    """
    return _save_edit_reload(
        lambda p: document.replace_block(p, match, items, section, occurrence)
    )


@mcp.tool()
def delete_block(match: str, section: str | None = None,
                 occurrence: int | None = None) -> str:
    """Delete a matched block.

    Args:
        match: Text substring to find the block to delete
        section: Scope search to blocks inside this section title
        occurrence: Which match to use if multiple (1-based)
    """
    return _save_edit_reload(
        lambda p: document.delete_block(p, match, section, occurrence)
    )


@mcp.tool()
def append_content(items: list[dict]) -> str:
    """Append content at the end of the document.

    Supports nested sections: use type "heading" to create sections.
    Sub-headings (higher level number) nest inside parent sections.

    Args:
        items: Content blocks to append (same format as insert_after)
    """
    return _save_edit_reload(
        lambda p: document.insert_content(p, items)
    )


@mcp.resource("maple://help/{topic}")
def maple_help(topic: str) -> str:
    """Get Maple help for a topic."""
    return engine.get_help(topic)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
