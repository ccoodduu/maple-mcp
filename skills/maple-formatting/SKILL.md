---
name: maple-formatting
description: >
  Personal STYLE guide for writing physics/math solutions into Maple .mw documents via the
  Maple MCP. Use whenever solving an opgave/aflevering, writing a solution, or formatting
  content in the user's usual style — or when the user mentions "Maple", "afleveringer",
  "opgave", ".mw". The exact markup SYNTAX and pitfall rules live in the Maple MCP itself
  (its tool instructions and the maple://help/markup resource); this skill defines the
  document structure, solution flow, and physics/math conventions to apply on top of it.
---

# Maple Document Style Skill

This skill defines how to STRUCTURE and present a solution in the user's usual style. The
exact markup syntax is owned by the MCP (see next section) — this is about the workflow.

## Syntax & gotchas — owned by the MCP (single source of truth)

The exact markup syntax and pitfall rules live in the Maple MCP itself: its tool
instructions, and the `maple://help/markup` resource. That is authoritative — follow it,
and read `maple://help/markup` if unsure. The gotchas it covers (don't forget these):

- Write **ASCII input**; it renders as 2D math. Use `:=` (not the glyph `≔`), `*` (not `·`),
  `-` (not `−`), `x^2`, `c[p]`. Never paste rendered glyphs back as input.
- **One `=` per `{{}}`**; put `⇕` between isolation steps.
- `{{}}` only **DISPLAYS**. To COMPUTE, use `{{expr => op}}` (op = solve / factor / simplify /
  expand / evaluate=exact / approximate=decimal / value) or the `execute` tool, then write
  the result. Never put bare `diff()/solve()/int()/eval()` inside a `{{}}`.
- Integrals you want computed: `{{Int(f, x = a..b) => value}}` — NOT `int()` in a code
  block (it becomes an inert `Int` that computes nothing).
- Fractions as `(a)/(b)`; Greek by name (`Delta`, `rho`); `Delta*T` → ΔT; primes `f'(x)`,
  `g''(x)`; numbers+units `{{200*[[kg]]}}`.
- Avoid Maple **protected names** as variables: `I`, `D`, `O`, `gamma`, `Pi`, `Catalan`.
- Mark **unknowns** with `?`: `{{V = ?}}`, `{{E[kin] = ?}}`.
- **Verify** with `screenshot_maple` (whole doc, or `match="Opgave 4"` / `pages="2"` /
  `crop_to_match=True` to save context). read_document may not fully decode arrows/unit
  blocks — confirm with a screenshot.

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
Insert the known values and compute. Use `{=...=}` for an inline result, or
`{{... => approximate}}` for the context-panel arrow:
```
De kendte værdier indsættes:
{=V = (0.005892*[[N]])/(1000*[[(kg)/(m^3)]]*9.82*[[(N)/(kg)]])=}
```
Introduce substitution with "De kendte værdier indsættes:", "Værdierne indsættes:", "Nu udregnes…".

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
Write derivatives with primes: `f'(x)`, `g''(x)`, `h'''(x)`. Compute with `execute` or an
operation arrow, then state the result:
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

## Narrative Language

Write explanatory text in Danish. Keep it concise but clear:
- "Det vides at…" / "Vi kender…" — introducing known facts
- "Først…" / "Derefter…" — sequencing steps
- "Ved at indsætte disse kendte værdier…" — before substitution
- "Nu kan X udregnes:" — transitioning to computation
- "Da [reason], så…" — justifying a step
- "For at finde X skal…" — stating the goal

## Regression and Data Analysis
```
{!X := (2005, 2006, 2007):!}
{!Y := (7540, 8055, 8638):!}
{!with(Gym):!}
{!LinReg(X, Y)!}
```
Follow regression with interpretation of the R² value and model validity.
