# Maple MCP Server

MCP server that lets Claude read, write, and edit Maple Document mode (.mw) assignments.
Version-independent: verified on Maple 2025 and 2026 (see "Porting to a new Maple version").

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

### screenshot_maple renders via PDF, not a screen grab
`screenshot_maple` spawns a throwaway Maple JVM (`maple-export.jar` → `WmiWorksheetExportUtils.exportPDF`) that parses the SAVED .mw from disk into a fresh model and exports a PDF — the same path as File ▸ Export As ▸ PDF. PyMuPDF then rasterizes each page to an image. This is window-independent (works with Maple hidden, occluded, or closed) and full-fidelity. Must run NON-headless (the PDF formatter builds invisible Swing owner frames; headless throws `HeadlessException`). If export fails/times out it falls back to a live-window `ImageGrab`.

## Critical Rules

### NEVER use ET.write or ET.indent on .mw files
ElementTree re-serializes XML and corrupts base64 data (images, equations, Drawing-Root). Always use raw string insertion: find position in file text, splice in new XML, write back.

### Validate the whole document before every write
Raw-splice edits are fast but a mis-computed offset or unescaped char would silently corrupt the .mw. `document._commit()` runs `ET.fromstring(content.encode())` on the *entire* spliced document before `write_text`; on a parse error it discards the just-made backup and raises, leaving the file untouched. The backup is pushed (via `backup.push`) only AFTER all read-only match resolution succeeds, so a no-match never leaves a phantom undo step.

### New documents are authored by Maple, not by a template
`create_document` builds the .mw with `DocumentTools:-Layout:-Worksheet(Version(major=<installed year>))`
and serializes it with `XMLTools:-PrintToString`, so Maple writes its own format —
it fills in `minor` and every default attribute itself. A hand-written template
would instead pin one Maple version and risk emitting a file Maple refuses to
open (the same trap that keeps table authoring deferred). `tests/test_create_document.py`
proves the output is openable by round-tripping it through the PDF export loader,
which is the same parse path as File ▸ Open.

### Content matching, not position-based
All edit operations use content matching (like Edit tool's old_string). Match text corresponds exactly to what read_document outputs. For sections, include `#` prefix (e.g. `"## b)"`).

### InertForm for equation encoding
Use `InertForm:-Typeset(InertForm:-Parse(expr), inert=false)` to typeset equations without evaluating them (`3*4` stays as `3·4`, not `12`). Strip `mcomplete`/`_Hold` artifacts with `subsindets` before storing.

### Units need special handling
`Unit('Omega')` renders literally unless wrapped in proper Typesetting with `msemantics="Unit"`. The encoder builds `mfenced+msemantics` markup. `with(Units[Standard])` breaks `Int`/`Sum` typesetting - use `InertForm` instead of `unwith` hack.

### Vectors and matrices use the palette's markup, not InertForm's
`InertForm:-Typeset` renders `<1,2>` as an inline `⟨1,2⟩` (`mfenced` with
`msemantics="<,>"`). Real assignments show what Maple's Matrix palette writes
into a 2D-input block instead, and that is what the GUI parses back into a
Vector when the block is executed:
`maction(mfenced(mrow(mtable(mtr(mtd(mrow(el)))…)), msemantics="ColVector", open="[", close="]"), actiontype="rtableaddress")`
(`RowVector` / `Matrix` likewise). `vec(a)` becomes the Accents palette's
`mover(mrow(mi("a")), mo("&RightArrow;"), accent="true")`, which Maple treats as
the atomic name `` `#mover(mi("a"),mo("&rarr;"))` ``. `_vector_fixup` rewrites
InertForm's output into these forms; `TS2Str` decodes them (and the output-side
`mscrolltable`) back to `<a,b>` / `<a|b>` / `Matrix([[…]])` / `vec(a)`.
`tests/fixtures/vector_blobs.json` pins the decoder to blobs Maple itself wrote.

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
<a,b>  <a|b>          column / row vector (renders as the palette's bracketed column)
Matrix([[a,b],[c,d]]) matrix (renders as a bracketed grid)
vec(a)                arrow accent over a name (a⃗); Maple treats it as one atomic name
a . b   a &x b        dot product, cross product (&x evaluates only after with(LinearAlgebra))
abs(vec(a))           length |a⃗| as DISPLAY; executed it is elementwise — compute
                      with Gym's længde(v) / vinkel(u,v) or LinearAlgebra's Norm(v,2)
{{expr => op}}        Context-panel operation: input ──op──▶ computed result
                      (op: solve, factor, simplify, expand, evaluate). The
                      result is computed by the kernel; renders as an mover
                      arrow (&rarr; + mtext label), like Maple's context panel.
```

Equations use MAPLE syntax, not LaTeX. Auto-conversion from LaTeX is attempted but not perfect.

## Tools

| Tool | Purpose |
|------|---------|
| `create_document` | Create a new empty .mw, open it in Maple, and select it |
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
├── reload-agent.jar           # Java agent for Maple JVM
├── maple-export.jar           # Standalone PDF-export launcher (for screenshot_maple)
├── java/ReloadAgent.java      # Agent source
├── java/MapleExport.java      # PDF-export launcher source (reflective; version-independent)
├── tools/baseline.py          # Golden baseline: record/check the equation pipeline
├── tests/fixtures/blob_corpus.json   # 200 frozen real Maple blobs (reverse round-trip)
├── tests/golden/maple-baseline.json  # Recorded per-item baseline
├── pyproject.toml
└── src/maple_mcp/
    ├── server.py              # MCP tools
    ├── document.py            # .mw XML read/write/match
    ├── maple_engine.py        # Kernel + equation encode/decode
    ├── maple_reload.py        # Save/reload/open via the agent (TCP)
    ├── maple_render.py        # .mw -> PDF -> page images (screenshot_maple)
    ├── image_decode.py        # Wheeler + Base64 image codec
```

Rebuild `maple-export.jar` after editing `MapleExport.java`. It resolves Maple's
export API reflectively, so it needs **no Maple classpath** and one jar serves
every Maple version:
```
javac -d _b java/MapleExport.java
jar cfe maple-export.jar MapleExport -C _b MapleExport.class
```
(use Maple's bundled JDK at `<MAPLE>/jre/bin` — it matches Maple's Java 21 runtime).

`--probe` checks the WHOLE private-API surface the project binds to — this
launcher's export call plus every `com.maplesoft.*` class `ReloadAgent` reaches
by reflection (17 members over 14 classes). Needs no licence and no desktop
session, since it only resolves classes and members, so it is the cheapest first
check when porting. Exit 0 = all resolved; each failure line says whether the
class vanished, the arity changed, or only the parameter types differ:
```
java -cp "<MAPLE>/java/*;maple-export.jar" MapleExport --probe
```
It also prints the 13 members it CANNOT check — those resolved off live objects,
whose class is only known while Maple runs. Cover those by exercising
save / reload / `run_executable` against a running Maple.

`tests/test_probe_manifest.py` cross-checks the manifest against the Java
sources in both directions, so a new `Class.forName` cannot silently escape the
port check and a stale entry cannot fail a port for an API no longer used.

Rebuilding `reload-agent.jar` (after editing `java/ReloadAgent.java`) requires a
manifest with `Premain-Class`/`Agent-Class`/`Can-Redefine-Classes`, and **Maple must
be CLOSED** — a running Maple JVM locks the jar (build to a `.staged.jar` and swap it
in after closing if needed). Compile against `<MAPLE>/java/worksheet.jar` with Maple's
bundled JDK.

## Setup

Prefer `install.ps1` — it computes the project dir and writes the correct `-javaagent`
line. Manual steps (replace `<PROJECT_DIR>` with this repo's path):

1. Maple installed under `C:\Program Files\Maple <year>`. Both `install.ps1` and
   `maple_engine.find_maple_root()` pick the newest install that actually has
   kernel binaries (so uninstall leftovers are skipped); `MAPLE` overrides the
   choice and is never second-guessed. `maple_engine.maple_version()` reads the
   version without starting the kernel, so it works on an expired licence.
2. `launch.ini`: add `java_args=-javaagent:<PROJECT_DIR>/reload-agent.jar`
3. Restart Maple, then Claude Desktop.

That is the whole setup. Talking to a running Maple goes through the agent's TCP
port only — no window manager, wrapper, or GUI automation is involved, and
nothing depends on Maple's window layout or focus.

## Porting to a new Maple version

The dangerous failures are the silent ones. A moved Java API or a missing DLL
throws; the equation decode layer just returns something subtly different, and
nothing complains. So the port is run as a diff, not as a smoke test.

1. `java -cp "<MAPLE>/java/*;maple-export.jar" MapleExport --probe` — do all 17
   required members of Maple's private Java API still exist? No licence or
   desktop session needed, so run it before installing anything else.
2. `python tools/baseline.py --check` — per-item diff of the equation pipeline
   against `tests/golden/maple-baseline.json`. Exits non-zero on any regression
   and names the equations that moved.
3. `python -m pytest` — the kernel-backed tests unskip once a licence works.

Record the baseline BEFORE switching versions (`--record`), on a licensed
install. `--record` refuses to store a kernel suite it could not measure rather
than writing it as all-failing — a baseline of zeros would make the next run
look like a clean sweep.

`tests/fixtures/blob_corpus.json` is 200 real Maple-authored equation blobs,
frozen from local .mw files so the reverse round-trip is reproducible on any
machine. Rebuild only deliberately (`--freeze-corpus`): re-freezing under a new
Maple would silently redefine what is being compared.

## Known Issues / Future Work

- `tests/golden/maple-baseline.json` is now recorded in full on **Maple 2026.1**
  (all three suites): `prepare` 272 items, `encode` 272 items (266 ok),
  `reverse` 200 items (82 render-stable, 4 byte-identical, 67 drifted,
  46 re-encode-fail, 1 decode-bad; re-recorded 2026-08-26 after the
  vector/matrix decoder landed — it moved 5 blobs to render-stable and turned
  `with(Student(Calculus1))` into the correct `with(Student[Calculus1])`).
  Caveat for whoever ports next: only
  `prepare` was ever measured on 2025, and it crossed 2025 → 2026 with 0
  regressions. `encode`/`reverse` have no 2025 side — the 2025 licence expired
  01-aug-2026 before they could be recorded — so 2026.1 is their reference
  zero, and a regression 2026 may have introduced relative to 2025 would be
  baked in as "expected" rather than reported
- Equation round-trip is lossy: decoded equations (e.g. `∫x²dx`) don't always re-encode to identical XML
- Pre-existing (NOT vector-related): `with(Units:-Simple):` decodes as `withUnits:-Simple:` (parens dropped) on the FIRST `decode_equation` after a cold kernel start — a `:-` member inside an mfenced with a trailing suppress-`:` mis-handled while `Typesetting` is only partly loaded. It self-heals from the 2nd call. Confirmed on committed HEAD, so not introduced here; `eval(Typesetting)` in the warmup looked like a fix but made it non-self-healing, so it was reverted. Cosmetic (the STORED blob is correct, Maple executes it fine); to avoid the read glitch entirely write `with(Units[Simple]):`, which decodes correctly cold. Note also that `{!with(Units:-Simple):!}` executed inline in the GUI is reduced by Maple's own parser to `:` (while `{!with(Gym):!}` / `{!with(LinearAlgebra):!}` survive) — another reason to prefer `with(Units[Simple]):`
- `launch.ini` holds ONE `java_args=` line. Another tool's installer (seen: `MaplePrintFix`, 2026-08-20) can overwrite it with its own `-javaagent`, which silently drops `reload-agent.jar` — Maple runs, but port 19876 is dead and every reload/`run_executable` fails. Fix by putting BOTH agents on the same line: `java_args=-javaagent:<other>.jar -javaagent:<PROJECT_DIR>/reload-agent.jar`, then restart Maple. `install.ps1` only appends a second line, which is not merged.
- Output equations: `read_document` decodes the `display` attribute of a `2D Output` equation (the typeset form) and falls back to the element text (the kernel value, which decodes as `[]` for rtables and most other values)
- `_count_section_depth` scans XML linearly - could be slow on very large documents
- LaTeX auto-conversion is basic - complex LaTeX may need manual conversion to Maple syntax
- Plots: a plot is the rendered OUTPUT of a plot command — `<Output><Text-field style="Maple Plot"><Plot type="two-dimensional" …>%m CURVES base64</Plot>`. Author one by writing an executable `{!plot(f(x), x=a..b)!}` / `{!pointplot(X,Y)!}` and calling `run_executable` (Maple generates the Plot data — it's not synthesizable). read_document surfaces it as `[PLOT: graph]` (detection verified against real assignments: tag `Plot`).
- Tables: READ is supported — `<Table>`/`<Table-Row>`/`<Table-Cell>` (a cell holds a Presentation-Block/Equation or a bare Text-field) surfaces as a `[TABLE r×c]` grid, whether the table is a direct child or wrapped in a `Presentation-Block`/`TaskRegion` (which read_document now recurses into). Read-only: the grid has no `[N]` index; edit cell text by substring. Verified against 5 real assignments.
- Deferred (need a real `.mw` round-trip to validate the emitted XML, else risk files Maple can't open): authoring TABLES (template known: `<Table width=…>`+`<Table-Column weight=…/>`×N+`<Table-Row>`/`<Table-Cell>`, cells reuse `_make_text_block`), equation-label numbers + cross-references, per-block `run_executable` results (needs a reload-agent protocol change)
- `screenshot_maple` hangs (then times out → window-grab fallback) on documents with live embedded components (`EC-RTableBrowser` etc.): `WmiECRTableBrowserView.layoutView` sleeps waiting for the interactive component during off-window layout. Rare (~1/75 real assignments); such widget-heavy docs can't be rendered statically anyway.
- `screenshot_maple` needs an ACTIVE, UNLOCKED desktop session: Maple's PDF formatter builds a Swing dialog (`WmiSectionOptionsDialog`) that requires a screen device, so export throws `HeadlessException`/"no screen devices" when the screen is locked or the process has no display. Works in normal interactive use (user at the machine); fails when the session is locked or run unattended. `export_pdf` detects this and returns an actionable message.
- PDF export spawns a fresh Maple JVM (~5s cold start per call)
