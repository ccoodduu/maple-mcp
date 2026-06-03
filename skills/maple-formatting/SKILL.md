---
name: maple-formatting
description: >
  Formatting guide for inserting content into Maple .mw documents using the Maple MCP tools.
  Use this skill whenever writing solutions, opgaver, or any content into a Maple worksheet —
  whether the user asks you to solve a physics/math problem, write up a solution, insert into
  a Maple document, or work with the Maple MCP tools (insert_after, set_document_path, etc.).
  Also trigger when the user mentions "Maple", "afleveringer", "opgave", ".mw", or asks to
  format a solution in their usual style. This skill defines the exact markup conventions,
  document structure, and solution flow to use.
---

# Maple Document Formatting Skill

This skill defines how to structure and format content when inserting into Maple `.mw`
worksheets via the Maple MCP tools. The style is based on a consistent pattern used across
physics and mathematics assignments.

## INPUT vs DISPLAY — read this first

You always write markup in **ASCII Maple syntax**; Maple renders it as pretty 2D math.
Never paste the rendered glyphs back as input.

| Write (input) | Renders as |
|---|---|
| `*` | `·` (multiplication dot) |
| `-` | `−` (minus) |
| `:=` | `≔` (assignment) |
| `x^2` | x² (superscript) |
| `c[p]` or `c_p` | c with subscript p |
| `Delta`, `rho`, `Omega` | Δ, ρ, Ω |
| `f'(x)`, `g''(x)` | f′(x), g″(x) (primes) |

So write `{{a = (1/2)*m*v^2}}`, NOT `{{a = ½·m·v²}}`. Write `{!f(x) := x^2:!}`, NOT `≔`.

## Core Markup Reference

| Syntax | Purpose | Example |
|--------|---------|---------|
| `{{expr}}` | Non-executable inline 2D Math (display only) | `{{v^2 - v[0]^2 = 2*a*(s - s[0])}}` |
| `{!expr!}` | Executable 2D Math, **output on the line below** | `{!a = (0^2 - 8.33^2)/(2*6)!}` |
| `{=expr=}` | Executable 2D Math, **output inline (same line)** | `{=r = sqrt(20.36^2 + 464.34)=}` |
| `{{expr => op}}` | **Operation arrow**: `expr ──op──▶ result` (Maple computes the result) | `{{x^2 - 4 => factor}}` |
| `**text**` | Bold | `**Info:**` |
| `*text*` | Italic | `*x-værdien*` |
| `__text__` | Underline | `__**bold underline**__` |
| `[[unit]]` | Unit in equations | `[[m]]`, `[[(kg)/(m^3)]]`, `[[(m)/(s^2)]]` |
| `{color:R,G,B}text{/color}` | Highlight background | `{color:255,255,0}answer{/color}` |
| `[align:right]` | Right-align block | For final answers |
| `⇕` | Equivalence arrow between steps (plain text line) | Between isolation steps |

### Critical Rules
- A plain `{{}}` block DISPLAYS an expression — it does NOT run commands. To show a
  computation **with its result**, use `{{expr => op}}` (below) or compute with `execute`
  and write the result. Do not put bare `diff()/solve()/int()/eval()` inside `{{}}`.
- Keep ONE `=` per `{{}}` and put `⇕` between steps — this always renders
  correctly. A chain `{{a = b = c}}` also encodes, but a Greek letter inside a
  chain (e.g. `Delta*v = ...`) can render as literal text, so prefer the split.
- Fractions ALWAYS use `(numerator)/(denominator)` with parentheses.
- Greek letters use Maple names: `Delta`, `rho`, `Omega` (not `\delta`, not the glyph).
- Subscripts: `v[0]`, `F[op]`, `c[p]` (or `v_0`, `c_p` — the underscore form is converted).
- Combine a Greek letter with a variable using `*`: `Delta*T` renders as ΔT.
- Units always inside `[[...]]`: `[[m]]`, `[[(J)/(kg*degC)]]`. Capital-I `Int(...)` and
  `Sum(...)` are display notation and are fine inside `{{}}`.
- Assignment input is `:=` (renders as ≔). The glyph `≔` does NOT parse as input.
- Avoid Maple's PROTECTED names as variables: `I` (imaginary unit ⅈ), `D`
  (derivative operator), `O`, `gamma`, `Pi`, `Catalan`. Assigning to them errors
  or changes meaning. Use `I[t]`, `current`, `D[1]`, etc. instead.
- Unknowns: mark with `?`, e.g. `{{E[kin] = ?}}` or `{{V = ?}}` (works with
  subscripts too).

## Operation Arrows — `{{expr => op}}`  (preferred for "compute and show")

This renders exactly like Maple's left-hand **context-panel** operations: the input, a
labelled right-arrow, and the **result computed by Maple**:

```
{{x^2 - 5*x + 6 => factor}}      →  x²−5·x+6 ──factor──▶ (x−2)·(x−3)
{{x^2 - 4 = 0 => solve}}         →  x²−4=0 ──solve──▶ ...
{{(x^2 - 9)/(x - 3) => simplify}}→  ... ──simplify──▶ x+3
{{1/3 + 1/6 => evaluate}}        →  ⅓+⅙ ──evaluate──▶ ½       (exact)
{{1/3 + 1/6 => approximate}}     →  ⅓+⅙ ──approximate──▶ 0.5  (decimal)
{{Int(4 - x^2, x = 0..2) => value}}  →  ∫₀²(4−x²)dx ──value──▶ 16/3
{{20000*[[kg]]/(1260*[[kg/m^3]]) => approximate}}  →  ... ──approximate──▶ 15.87 m³
```

- Operations: `solve`, `factor`, `simplify`, `expand`, `evaluate` (EXACT, e.g. ½),
  `approximate` (DECIMAL, e.g. 0.5), `value`. Unknown ops fail loudly.
- For a numeric physics answer with units, use `approximate`. For an exact fraction, use
  `evaluate`. Results keep units. The result is **baked in** at write time (a static
  display); for a block that re-runs live in Maple, use `{=expr=}`.
- INTEGRALS: write `{{Int(f, x = a..b) => value}}` (capital `Int`) — this renders the
  integral and computes the result. Do NOT put `int(...)` in an executable code block: it
  becomes an inert `Int` that computes nothing on Enter.
- This is the cleanest way to present a worked step that needs a computed answer, and it
  matches the hand-authored context-panel style.

## Document Structure

### Heading Hierarchy

```
# Opgave 1                    ← Main task/section (level 1)
  ## a)                        ← Subtask (level 2)
    Content here...
  ## b)
    ...
```

- Use `#` for main opgave headings: `# Opgave 1`, or descriptive names like `# Bremselængde`.
- Use `##` for subtasks: `## a)`, `## b)`, etc.
- Use `{"type": "empty"}` items for vertical spacing where you want it.

### When the document already has a title
If the document has a `TITLE:` block at the top, the first `#` heading is the first
section. Don't add an extra title.

## Solution Flow Pattern (Shared)

Both physics and mathematics follow the same core sequence:

### 1. State the Relevant Formula
Introduce the formula in plain Danish text, then show it:
```
Opdrift er givet ved:
{{F[op] = rho[væske]*g*V}}
```
Common intro phrases: "X er givet ved:", "Formlen for X lyder:", "Ud fra [lov] kan vi…",
"For at finde X bruges denne formel:".

### 2. Isolate Step-by-Step
Show algebraic manipulation with `⇕` between each step:
```
{{F[op] = rho[væske]*g*V}}
⇕
{{V = (F[op])/(rho[væske]*g)}}
```
Each line has exactly one equation in `{{}}`. Show every meaningful step.

### 3. Substitute and Compute
Insert the known values and compute. Use `{=...=}` for an inline result, or `{{... => evaluate}}`
for the context-panel arrow:
```
De kendte værdier indsættes:
{=V = (0.005892*[[N]])/(1000*[[(kg)/(m^3)]]*9.82*[[(N)/(kg)]])=}
```
Introduce substitution with "De kendte værdier indsættes:", "Værdierne indsættes:", "Nu udregnes…".

## Verify the rendering — `screenshot_maple`

After writing (or while working), call `screenshot_maple` to SEE how the document renders
in Maple, and fix anything that looks wrong (units, fractions, Greek, primes, arrows).
- Whole document: `screenshot_maple()`
- Just the part you changed (saves context): `screenshot_maple(match="Opgave 4")`, or
  `screenshot_maple(pages="2")`, or `screenshot_maple(match="Beregning:", crop_to_match=True)`.
- `match` searches the document TEXT (headings, labels, prose) — not the typeset math —
  so match on a heading or label near the part you want.
Treat a screenshot as a real check: read it, confirm the math looks right, then continue.

---

## Physics-Specific Conventions (Fysik)

### Info Block
Start each subtask with a bold `**Info:**` block listing known values and unknowns:
```
**Info:**
{{m = 199.5*[[g]]}}
{{rho = 8.47*[[(g)/(cm^3)]]}}
{{V = ?}}
```
- One value per line, units via `[[...]]`. Mark unknowns with `?`.
- Inline conversions: `{{v[0] =}} {=30*[[(km)/(h)]]*(1*[[(m)/(s)]])/(3.6*[[(km)/(h)]])=}`.

### Final Answer — Yellow Highlight
```
{color:255,255,0}Bremselængden ved 100 km/t er 0.06 km{/color}
```
Write the answer as a natural Danish sentence with value and unit.

### Physics Narrative Style
- Reference laws: "Ifølge Newtons 2. lov…", "Opdrift er givet ved:".
- Heavy use of units throughout. Explain the physical reasoning.

### Complete Physics Example
```
## a)
  **Info:**
  {{m = 5*[[kg]]}}
  {{v[0] = 10*[[(m)/(s)]]}}
  {{F = ?}}
  {{t = 2*[[s]]}}

  Impuls-kraftstødsætningen lyder:
  {{F*t = m*Delta*v}}

  Isoleret for {{F}}:
  {{F*t = m*Delta*v}}
  ⇕
  {{F = (m*Delta*v)/(t)}}

  Da objektet starter med {{v[0] = 10*[[(m)/(s)]]}} og stopper ({{v = 0}}):
  {{Delta*v = v - v[0]}}
  ⇕
  {{Delta*v = -10*[[(m)/(s)]]}}

  De kendte værdier indsættes:
  {=F = (5*[[kg]]*(-10*[[(m)/(s)]]))/(2*[[s]])=}

  {color:255,255,0}Kraften er -25 N.{/color}
```

---

## Mathematics-Specific Conventions (Matematik)

### No Info Block
Mathematics solutions do NOT start with a `**Info:**` block. State the given information
naturally in prose, or re-state the problem directly before solving.

### Derivatives
Write derivatives with primes — they render correctly: `f'(x)`, `g''(x)`, `h'''(x)`.
Compute them with `execute` or show the operation arrow, then state the result:
```
{{g'(x) = 3*x^2 - 6*x}}
{{g''(x) = 6*x - 6}}
```

### Final Answer — Bold+Underline Right-Aligned
```
__**Arealet af det grå område er**__ {{2484*[[cm^2]]}} [align:right]
```

### Graphical Validation
Mathematics solutions frequently include explicit graphical validation after a result:
```
**Grafisk validering:**
{!plot(f(x), x = 0..10)!}
```
Used after geometric calculations, curve fitting, optimization, or wherever a result can be
visually verified.

### Mathematics Narrative Style
- More algebraic and abstract — focuses on derivation and proof steps.
- Often re-states the problem before solving.
- Uses `{!with(Gym):!}` for Gympakken functions like `LinReg`, `PowReg`.
- Interprets results: R² values, model validity, why certain solutions are invalid.

### Complete Mathematics Example
```
## b)
  Da cirklen er symmetrisk omkring y-aksen er x-værdien for centrum 0:
  {{x^2 + (y - b)^2 = r^2}}

  Vi kender 2 punkter på cirklen — punktet (21.5485, 0) og punktet (0, 50).
  (Skriv koordinater i teksten, ikke som {{(2,1)}}.)

  Ud fra det opstilles 2 ligninger:
  {{21.5485^2 + (0 - b)^2 = r^2}}
  {{0^2 + (50 - b)^2 = r^2}}

  Den første ligning løses for b:
  {{21.5485^2 + b^2 = r^2}}
  ⇕
  {{b = sqrt(r^2 - 464.34)}}

  Nu løses ligningssystemet for r:
  {=r = sqrt(20.36^2 + 464.34)=}
  {=b = sqrt(29.64^2 - 464.34)=}

  __**Ligningen for cirklen er**__ {{x^2 + (y - 20.36)^2 = 29.64^2}} [align:right]

  **Grafisk validering:**
  {!plot((x^2 + (y-20.36)^2 = 29.64^2), x = -40..40, y = -20..60)!}
```

## Variable Assignment vs. Computation

- `{!var := expr:!}` — define a function / store a value for later use (colon suppresses output).
- `{=expr=}` — compute a result and show it inline.
- `{!expr!}` — compute and show the result on the line below (e.g. a plot or a command).
- `{{expr => op}}` — show a context-panel operation with its computed result (static).

Examples:
```
{!f(x) := 3*x^2 - 2*x + 1:!}      ← Define function (no output)
{=f(2)=}                           ← Compute and show inline
{!plot(f(x), x = 0..5)!}          ← Plot (output is a graph)
{{f(x) = 0 => solve}}              ← Operation arrow with the roots
```

## Narrative Language

Write explanatory text in Danish. Keep it concise but clear:
- "Det vides at…" / "Vi kender…" — introducing known facts
- "Først…" / "Derefter…" — sequencing steps
- "Ved at indsætte disse kendte værdier…" — before substitution
- "Nu kan X udregnes:" — transitioning to computation
- "Da [reason], så…" — justifying a step
- "For at finde X skal…" — stating the goal

## Units Formatting

- Simple: `[[m]]`, `[[kg]]`, `[[N]]`, `[[V]]`, `[[A]]`, `[[Omega]]`
- Compound: `[[(m)/(s)]]`, `[[(kg)/(m^3)]]`, `[[(N)/(kg)]]`, `[[(J)/(kg*degC)]]`
- Squared/cubed: `[[m^2]]`, `[[m^3]]`, `[[cm^3]]`
- Per unit: `[[(m)/(s^2)]]`, `[[(km)/(h)]]`
- Numbers with units use `*`: `{{200*[[kg]]}}` (renders as 200 kg).

## Regression and Data Analysis

```
{!X := (2005, 2006, 2007):!}
{!Y := (7540, 8055, 8638):!}
{!with(Gym):!}
{!LinReg(X, Y)!}
```
Follow regression with interpretation of the R² value and model validity.

## Solve Patterns

Preferred (context-panel arrow, shows the result):
```
{{equation => solve}}
```
For a live executable solve, or numerical solutions:
```
{=solve(equation, variable)=}
{=fsolve(equation, variable)=}
```
