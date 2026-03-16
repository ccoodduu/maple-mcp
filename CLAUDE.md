# Maple MCP Server

MCP server that lets Claude read, write, and edit Maple 2025 Document mode (.mw) assignments.

## Architecture

```
Claude Desktop ←→ MCP Server (Python) ←→ Maple .mw file (XML)
                         ↓                       ↓
                   maplec.dll (kernel)    Java Agent (reload)
```

- **Python MCP server** (`src/maple_mcp/server.py`) - 9 tools via FastMCP
- **Maple kernel** (`maple_engine.py`) - ctypes to maplec.dll for computation + equation encoding
- **Document module** (`document.py`) - reads/writes .mw XML with raw string insertion (NEVER ET.write)
- **Image codec** (`image_decode.py`) - Wheeler compression + custom Base64 (reverse-engineered from Maple's Java)
- **Java Agent** (`reload-agent.jar`) - injected into Maple's JVM via `-javaagent` in `launch.ini`, provides TCP server on port 19876 for save/reload/getpath without focus stealing
- **AHK fallback** (`maple_reload.ahk`) - ControlSend to SunAwtFrame if agent unavailable

## Critical Rules

### NEVER use ET.write or ET.indent on .mw files
ElementTree re-serializes XML and corrupts base64 data (images, equations, Drawing-Root). Always use raw string insertion: find position in file text, splice in new XML, write back.

### Content matching, not position-based
All edit operations use content matching (like Edit tool's old_string). Match text corresponds exactly to what read_document outputs. For sections, include `#` prefix (e.g. `"## b)"`).

### InertForm for equation encoding
Use `InertForm:-Typeset(InertForm:-Parse(expr), inert=false)` to typeset equations without evaluating them (`3*4` stays as `3·4`, not `12`). Strip `mcomplete`/`_Hold` artifacts with `subsindets` before storing.

### Units need special handling
`Unit('Omega')` renders literally unless wrapped in proper Typesetting with `msemantics="Unit"`. The encoder builds `mfenced+msemantics` markup. `with(Units[Standard])` breaks `Int`/`Sum` typesetting - use `InertForm` instead of `unwith` hack.

### Highlight colors at 3 levels
Maple requires background on: (1) Text-field element, (2) Font elements, (3) inside equation Typesetting data (on each mi/mn/mo via `subsindets`).

## Markup Syntax (read and write)

```
{{expr}}              non-executable inline 2D Math
{!expr!}              executable 2D Math
{=expr=}              executable, inline output
**bold**              bold text
*italic*              italic text
__underline__         underlined text
{color:R,G,B}text{/color}  highlight background
[[unit]]              Maple unit in equations (e.g. [[Omega]], [[J/(kg*degC)]])
```

Equations use MAPLE syntax, not LaTeX. Auto-conversion from LaTeX is attempted but not perfect.

## Tools

| Tool | Purpose |
|------|---------|
| `set_document_path` | Select document (auto-detects from Maple window) |
| `read_document` | Auto-save + read with indented hierarchy |
| `execute` | Run Maple code in persistent kernel |
| `insert_after` | Insert after matched block/section |
| `insert_before` | Insert before matched block/section |
| `replace_block` | Replace matched block (refuses sections with children) |
| `delete_block` | Delete matched block (refuses section headings unless confirmed) |
| `append_content` | Append at document end with nested section support |
| `undo` | Restore from .mw.bak backup |

## Key Files

```
maple-mcp/
├── CLAUDE.md
├── maple_reload.ahk          # AHK v2 fallback for save/reload
├── reload-agent.jar           # Java agent for Maple JVM
├── java/ReloadAgent.java      # Agent source
├── pyproject.toml
└── src/maple_mcp/
    ├── server.py              # MCP tools
    ├── document.py            # .mw XML read/write/match
    ├── maple_engine.py        # Kernel + equation encode/decode
    ├── maple_reload.py        # Save/reload via agent or AHK
    ├── image_decode.py        # Wheeler + Base64 image codec
    ├── live_connection.py     # Legacy bridge (unused)
    └── worksheet.py           # Legacy worksheet mode (unused)
```

## Setup

1. Maple 2025 installed at `C:\Program Files\Maple 2025`
2. `launch.ini`: add `java_args=-javaagent:C:/Users/willi/mcp-servers/maple-mcp/reload-agent.jar`
3. AHK v2 at `C:\Users\willi\AppData\Local\Programs\AutoHotkey\v2\AutoHotkey64.exe`
4. User runs Maple inside AHK wrapper (`maple-windows.ahk`) - Maple's SunAwtFrame is child of AutoHotkeyGUI

## Known Issues / Future Work

- Equation round-trip is lossy: decoded equations (e.g. `∫x²dx`) don't always re-encode to identical XML
- `_count_section_depth` scans XML linearly - could be slow on very large documents
- LaTeX auto-conversion is basic - complex LaTeX may need manual conversion to Maple syntax
- Multi-level undo not supported (single .mw.bak backup)
- `live_connection.py` and `worksheet.py` are legacy code from the bridge approach - can be removed
