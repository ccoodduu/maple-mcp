# Maple MCP Server

MCP server that lets Claude read, write, and edit **Maple Document mode** (.mw) assignments — with proper 2D Math, units, sections, formatting, and images.

![Maple MCP Demo](https://img.shields.io/badge/Maple-2025%20%7C%202026-green) ![Tests](https://img.shields.io/badge/tests-passing-brightgreen) ![Python](https://img.shields.io/badge/python-3.10+-blue)

## What it does

Claude Desktop can directly edit your open Maple document:

- **Read** the document with full equation decoding (2D Math → readable markup)
- **Write** text, equations, code blocks, sections, images, and highlights
- **Edit** by matching content — insert, replace, or delete blocks
- **Execute** Maple code and use results in the document
- **Verify** rendering via Maple's PDF export — window-independent, full fidelity

All equations are encoded as native Maple 2D Math — they render identically to hand-typed math in Document mode.

## Architecture

```
Claude Desktop ←→ MCP Server (Python/stdio) ←→ Maple .mw file (XML)
                         ↓                             ↓
             maplec.dll (warm kernel:           Java Agent (reload,
             compute + encode + decode)         open, save) on TCP 19876
```

The server edits the .mw XML file directly (never `ET.write` — that corrupts base64), then tells Maple to reload via a Java Agent injected into Maple's JVM.

## Installation

### Prerequisites

- **Maple** installed under `C:\Program Files\Maple <year>`. The newest install is
  auto-detected; set the `MAPLE` environment variable to pick a specific one
- **Python 3.10+**
- **uv** (`pip install uv`)

### Quick install

```powershell
git clone https://github.com/ccoodduu/maple-mcp.git
cd maple-mcp
powershell -ExecutionPolicy Bypass -File install.ps1
```

This will:
1. Install the Python package
2. Add the Java Agent to Maple's `launch.ini` (for in-place document reload)
3. Add `maple` to Claude Desktop's MCP config
4. Run the test suite

### Manual setup

```bash
pip install -e .
```

Add to Claude Desktop config (`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "maple": {
      "command": "uv",
      "args": ["--directory", "C:\\path\\to\\maple-mcp", "run", "maple-mcp"]
    }
  }
}
```

Add the Java Agent to `<MAPLE>\bin.X86_64_WINDOWS\launch.ini` (e.g.
`C:\Program Files\Maple 2026\bin.X86_64_WINDOWS\launch.ini`):

```
java_args=-javaagent:C:/path/to/maple-mcp/reload-agent.jar
```

Restart both Maple and Claude Desktop.

## Tools

| Tool | Description |
|------|-------------|
| `create_document` | Create a new empty .mw, open it in Maple, and select it |
| `set_document_path` | Select document (auto-detects from Maple window) |
| `read_document` | Save + read with indented section hierarchy |
| `execute` | Run Maple code in persistent kernel session |
| `insert_after` | Insert content after a matched block |
| `insert_before` | Insert content before a matched block |
| `replace_block` | Replace a matched block with new content |
| `delete_block` | Delete a matched block (with safety checks) |
| `append_content` | Append at document end with nested sections |
| `find_block` | Dry-run: resolve a match to its block index + text (no changes) |
| `run_executable` | Compute the unrun {!…!}/{=…=} blocks so results appear |
| `undo` | Restore the prior version (multi-level, out-of-tree backup ring) |
| `screenshot_maple` | Render the document via Maple's PDF export to verify it |

## Markup syntax

The server uses a round-trip markup format — what you read is what you write:

```
{{expr}}              non-executable inline 2D Math
{!expr!}              executable 2D Math (Maple evaluates it)
{=expr=}              executable with inline output
**bold**              bold text
*italic*              italic text
__underline__         underlined text
{color:R,G,B}...{/color}   highlight background
[[unit]]              Maple unit: [[kg]], [[J/(kg*degC)]], [[m^3]]
```

### Automatic conversions

| You write | Maple shows | How |
|-----------|-------------|-----|
| `DeltaT` | ΔT | Greek prefix + uppercase letter |
| `c_p` | c with subscript p | Underscore → bracket subscript |
| `1000 [[kg]]` | 1000 ⟦kg⟧ | Space before unit auto-normalized |

### Examples

```
Text:  "The mass is {{m = rho*V}}, where {{rho = 1000*[[kg/m^3]]}}."
Code:  {"type": "code", "content": "m = 1000*[[kg/m^3]]*0.2*[[m^3]]"}
Svar:  "{color:255,255,0}**Answer: {{m = 200*[[kg]]}}.**{/color}"
```

## How it works

### Equation encoding
Equations are encoded using `InertForm:-Typeset`, preserving the unevaluated form (`3*4` shows as `3·4`, not `12`). The statement runs in the warm in-process kernel wrapped in an anonymous proc, so its temp names stay scoped and never contaminate the user's session; package-loading statements (`with(Units:-Standard)`) run in a throwaway `cmaple.exe` instead, so they can't persist in the shared kernel.

Units use a placeholder-based approach: each `[[unit]]` is replaced with a temporary name, encoded with InertForm, then the placeholders are substituted with native Maple unit Typesetting (`mfenced` + `msemantics="Unit"`).

### Document editing
All edits use content-based matching (like a text editor's find-and-replace). The match text corresponds exactly to `read_document` output. Edits splice raw XML strings into the file — never using `ET.write` which corrupts base64 data in images and equations.

### In-place reload
A Java Agent (`reload-agent.jar`) injected via `-javaagent` in Maple's `launch.ini` provides a TCP server on port 19876. After each edit, the server sends a `reload` command that uses `WmiWorksheetFileLoader.loadContents()` on the EDT — Maple updates instantly without focus stealing or save dialogs.

## Testing

```bash
pytest tests/ -v
```

Covering:
- Equation encode/decode round-trip (basic math, units, multi-unit, Greek letters)
- Document operations (insert, replace, delete, match logic, section scoping)
- Format preservation (bold, italic, color, highlight, nested colors)
- XML validity (valid XML output, required Maple attributes)
- Edge cases (empty documents, long equations, Danish characters, undo/backup)
- Image codec (Wheeler compression round-trip)

## Known limitations

- Equation round-trip is lossy for complex expressions (decoded equations don't always re-encode to identical XML)
- `InertForm:-Parse` doesn't handle all Maple syntax (e.g. some procedural constructs)
- LaTeX auto-conversion is basic — use Maple syntax for best results
- Windows only (maplec.dll, Java Agent paths)

## License

MIT
