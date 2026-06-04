# Maple MCP Server

MCP server that lets Claude read, write, and edit Maple 2025 Document mode (.mw) assignments.

## Architecture

```
Claude Desktop ←→ MCP Server (Python) ←→ Maple .mw file (XML)
                         ↓                       ↓
                   maplec.dll (kernel)    Java Agent (reload)
                         ↓
                   PDF render (export)    → PyMuPDF → page images
```

- **Python MCP server** (`src/maple_mcp/server.py`) - 10 tools via FastMCP
- **Maple kernel** (`maple_engine.py`) - ctypes to maplec.dll for computation + equation encoding
- **Document module** (`document.py`) - reads/writes .mw XML with raw string insertion (NEVER ET.write)
- **Backup store** (`backup.py`) - out-of-tree rotating backup ring under `%LOCALAPPDATA%/maple-mcp/backups/<doc-id>/`; powers multi-level `undo` without cluttering the work dir
- **Image codec** (`image_decode.py`) - Wheeler compression + custom Base64 (reverse-engineered from Maple's Java)
- **Render module** (`maple_render.py`) - renders the saved .mw to images for `screenshot_maple` (see below)
- **Java Agent** (`reload-agent.jar`) - injected into Maple's JVM via `-javaagent` in `launch.ini`, provides TCP server on port 19876 for save/reload/getpath without focus stealing
- **AHK fallback** (`maple_reload.ahk`) - ControlSend to SunAwtFrame if agent unavailable

### screenshot_maple renders via PDF, not a screen grab
`screenshot_maple` spawns a throwaway Maple JVM (`maple-export.jar` → `WmiWorksheetExportUtils.exportPDF`) that parses the SAVED .mw from disk into a fresh model and exports a PDF — the same path as File ▸ Export As ▸ PDF. PyMuPDF then rasterizes each page to an image. This is window-independent (works with Maple hidden, occluded, or closed) and full-fidelity. Must run NON-headless (the PDF formatter builds invisible Swing owner frames; headless throws `HeadlessException`). If export fails/times out it falls back to a live-window `ImageGrab`.

## Critical Rules

### NEVER use ET.write or ET.indent on .mw files
ElementTree re-serializes XML and corrupts base64 data (images, equations, Drawing-Root). Always use raw string insertion: find position in file text, splice in new XML, write back.

### Validate the whole document before every write
Raw-splice edits are fast but a mis-computed offset or unescaped char would silently corrupt the .mw. `document._commit()` runs `ET.fromstring(content.encode())` on the *entire* spliced document before `write_text`; on a parse error it discards the just-made backup and raises, leaving the file untouched. The backup is pushed (via `backup.push`) only AFTER all read-only match resolution succeeds, so a no-match never leaves a phantom undo step.

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
{{expr => op}}        Context-panel operation: input ──op──▶ computed result
                      (op: solve, factor, simplify, expand, evaluate). The
                      result is computed by the kernel; renders as an mover
                      arrow (&rarr; + mtext label), like Maple's context panel.
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
| `find_block` | Dry-run: resolve a match (or `#N`) to its block index + text, no changes |
| `run_executable` | Compute the unrun `{!…!}`/`{=…=}` blocks so results appear |
| `list_unrun` | List unrun executable blocks (index + snippet) before running them |
| `undo` | Restore prior version from the out-of-tree backup ring (multi-level) |
| `screenshot_maple` | Render document to page images (Maple PDF export) to verify rendering |

read_document prefixes each line with its `[N]` block index; edit tools accept `match="#N"`.

## Key Files

```
maple-mcp/
├── CLAUDE.md
├── maple_reload.ahk          # AHK v2 fallback for save/reload
├── reload-agent.jar           # Java agent for Maple JVM
├── maple-export.jar           # Standalone PDF-export launcher (for screenshot_maple)
├── java/ReloadAgent.java      # Agent source
├── java/MapleExport.java      # PDF-export launcher source (build with Maple's javac)
├── pyproject.toml
└── src/maple_mcp/
    ├── server.py              # MCP tools
    ├── document.py            # .mw XML read/write/match
    ├── maple_engine.py        # Kernel + equation encode/decode
    ├── maple_reload.py        # Save/reload via agent or AHK
    ├── maple_render.py        # .mw -> PDF -> page images (screenshot_maple)
    ├── image_decode.py        # Wheeler + Base64 image codec
```

Rebuild `maple-export.jar` after editing `MapleExport.java`:
```
javac -cp "<MAPLE>/java/worksheet.jar" -d _b java/MapleExport.java
jar cfe maple-export.jar MapleExport -C _b MapleExport.class
```
(use Maple's bundled JDK at `<MAPLE>/jre/bin` — it matches Maple's Java 21 runtime).

Rebuilding `reload-agent.jar` (after editing `java/ReloadAgent.java`) requires a
manifest with `Premain-Class`/`Agent-Class`/`Can-Redefine-Classes`, and **Maple must
be CLOSED** — a running Maple JVM locks the jar (build to a `.staged.jar` and swap it
in after closing if needed). Compile against `<MAPLE>/java/worksheet.jar` with Maple's
bundled JDK.

## Setup

Prefer `install.ps1` — it computes the project dir and writes the correct `-javaagent`
line. Manual steps (replace `<PROJECT_DIR>` with this repo's path):

1. Maple 2025 installed at `C:\Program Files\Maple 2025`
2. `launch.ini`: add `java_args=-javaagent:<PROJECT_DIR>/reload-agent.jar`
3. AHK v2 at `<LOCALAPPDATA>\Programs\AutoHotkey\v2\AutoHotkey64.exe`
4. User runs Maple inside AHK wrapper (`maple-windows.ahk`) - Maple's SunAwtFrame is child of AutoHotkeyGUI

## Known Issues / Future Work

- Equation round-trip is lossy: decoded equations (e.g. `∫x²dx`) don't always re-encode to identical XML
- `_count_section_depth` scans XML linearly - could be slow on very large documents
- LaTeX auto-conversion is basic - complex LaTeX may need manual conversion to Maple syntax
- Plot read-placeholder keys on a tag starting with `Plot`; verify the exact tag against a real plot-containing `.mw` (read-only, harmless if it doesn't fire)
- Deferred (need a real `.mw` sample to reverse-engineer the XML safely, or they'd risk producing files Maple can't open): authoring plots/tables, equation-label numbers + cross-references, per-block `run_executable` results (needs a reload-agent protocol change)
- `screenshot_maple` hangs (then times out → window-grab fallback) on documents with live embedded components (`EC-RTableBrowser` etc.): `WmiECRTableBrowserView.layoutView` sleeps waiting for the interactive component during off-window layout. Rare (~1/75 real assignments); such widget-heavy docs can't be rendered statically anyway.
- `screenshot_maple` needs an ACTIVE, UNLOCKED desktop session: Maple's PDF formatter builds a Swing dialog (`WmiSectionOptionsDialog`) that requires a screen device, so export throws `HeadlessException`/"no screen devices" when the screen is locked or the process has no display. Works in normal interactive use (user at the machine); fails when the session is locked or run unattended. `export_pdf` detects this and returns an actionable message.
- PDF export spawns a fresh Maple JVM (~5s cold start per call)
