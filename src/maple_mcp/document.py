import re
import xml.etree.ElementTree as ET
from pathlib import Path

from maple_mcp.maple_engine import engine
from maple_mcp.image_decode import decode_maple_image, encode_maple_image


def _next_label_num(root: ET.Element) -> int:
    max_num = 0
    for el in root.iter():
        ref = el.get("labelreference", "")
        m = re.match(r"L(\d+)", ref)
        if m:
            max_num = max(max_num, int(m.group(1)))
    return max_num + 1


def _next_label_num_from_text(content: str) -> int:
    """Next L-label over the already-read file text — avoids a second full
    ET.parse per edit (the edit functions have already read `content`)."""
    nums = [int(n) for n in re.findall(r'labelreference="L(\d+)"', content)]
    return (max(nums) + 1) if nums else 1


def _group_attribs(label_num: int, inline_output: bool = False) -> dict:
    return {
        "view": "presentation",
        "hide-input": "false",
        "hide-output": "false",
        "inline-output": "true" if inline_output else "false",
        "labelreference": f"L{label_num}",
        "drawlabel": "true",
        "applyint": "true",
        "applyrational": "true",
        "applyexponent": "false",
    }


def _replace_units_in_expr(expr: str) -> str:
    """Replace [[unit]] with Maple Unit('unit') inside expressions.

    [[Omega]] → Unit('Omega')  (renders as Ω)
    [[degC]]  → Unit('degC')   (renders as °C)
    [[V]]     → Unit('V')      (renders as V)
    [[J/(kg*degC)]] → Unit('J'/('kg'*'degC'))

    Maple's Units package handles all unit names and rendering.
    """
    def _replace(m):
        unit = m.group(1)
        if any(c in unit for c in '/*^()'):
            tokens = re.findall(r'[a-zA-Z]+|\d+|[/*()\^]', unit)
            parts = []
            for tok in tokens:
                if re.match(r'^[a-zA-Z]+$', tok):
                    parts.append(f"'{tok}'")
                else:
                    parts.append(tok)
            return f"Unit({''.join(parts)})"
        return f"Unit('{unit}')"
    # Normalize "number [[unit]]" → "number*[[unit]]" (space → multiplication)
    expr = re.sub(r'(\w)\s+\[\[', r'\1*[[', expr)
    return re.sub(r'\[\[(.+?)\]\]', _replace, expr)


def _latex_to_maple(expr: str) -> str:
    """Convert common LaTeX patterns to Maple syntax."""
    import re
    # Detect LaTeX and convert
    if '\\' in expr:
        expr = expr.replace('\\cdot', '*')
        expr = expr.replace('\\times', '*')
        expr = expr.replace('\\,', '')
        expr = expr.replace('\\;', '')
        expr = expr.replace('\\left', '')
        expr = expr.replace('\\right', '')
        # Handle \frac with possibly nested braces
        while '\\frac{' in expr:
            idx = expr.find('\\frac{')
            # Find matching braces for numerator
            depth = 0
            start = idx + 6  # after \frac{
            end = start
            for j in range(start, len(expr)):
                if expr[j] == '{': depth += 1
                elif expr[j] == '}':
                    if depth == 0:
                        end = j
                        break
                    depth -= 1
            num = expr[start:end]
            # Find matching braces for denominator
            start2 = end + 2  # skip }{
            depth = 0
            end2 = start2
            for j in range(start2, len(expr)):
                if expr[j] == '{': depth += 1
                elif expr[j] == '}':
                    if depth == 0:
                        end2 = j
                        break
                    depth -= 1
            den = expr[start2:end2]
            expr = expr[:idx] + f'({num})/({den})' + expr[end2+1:]
        expr = re.sub(r'\\sqrt\{([^}]+)\}', r'sqrt(\1)', expr)
        expr = re.sub(r'\\int_\{([^}]+)\}\^\{([^}]+)\}', r'Int(', expr)
        expr = expr.replace('\\int', 'int')
        expr = expr.replace('\\pi', 'Pi')
        expr = expr.replace('\\infty', 'infinity')
        expr = expr.replace('\\alpha', 'alpha')
        expr = expr.replace('\\beta', 'beta')
        expr = expr.replace('\\gamma', 'gamma')
        expr = expr.replace('\\delta', 'delta')
        expr = expr.replace('\\theta', 'theta')
        expr = expr.replace('\\omega', 'omega')
        expr = expr.replace('\\Omega', 'Omega')
        expr = expr.replace('\\sum', 'sum')
        expr = expr.replace('\\prod', 'product')
        expr = expr.replace('\\ln', 'ln')
        expr = expr.replace('\\log', 'log')
        expr = expr.replace('\\sin', 'sin')
        expr = expr.replace('\\cos', 'cos')
        expr = expr.replace('\\tan', 'tan')
        expr = expr.replace('\\exp', 'exp')
        expr = expr.replace('\\lim', 'limit')
        # Clean up remaining backslashes
        expr = expr.replace('\\', '')
    return expr


def _equation_xml(expr: str, executable: bool = True, style: str = "2D Math",
                   background: str | None = None) -> str:
    original_expr = expr
    expr = _latex_to_maple(expr)
    expr = _replace_units_in_expr(expr)

    engine._last_encode_error = None
    display_b64, content_b64 = engine.encode_equation(
        expr, background=background)
    if not content_b64:
        maple_err = engine._last_encode_error or "unknown error"
        raise ValueError(
            f"Equation encoding failed for: {original_expr}\n"
            f"Maple error: {maple_err}"
        )

    exe = "true" if executable else "false"
    return (
        f'<Equation executable="{exe}" style="{style}" '
        f'input-equation="" display="{display_b64}">'
        f'{content_b64}</Equation>'
    )


def _font_xml(text: str, bold=False, italic=False, underline=False,
               color=None, size=None, raw=False) -> str:
    attrs = []
    if bold:
        attrs.append('bold="true"')
    if italic:
        attrs.append('italic="true"')
    if underline:
        attrs.append('underline="true"')
    if color:
        attrs.append(f'background="{color}"')
        attrs.append('opaque="true"')
    if size:
        attrs.append(f'size="{size}"')
    if not raw:
        from xml.sax.saxutils import escape
        text = escape(text)
    attr_str = " ".join(attrs)
    return f'<Font {attr_str}>{text}</Font>'






def _parse_markup(text: str) -> str:
    """Parse inline markup in text.

    Equations:
      {{expr}}  - non-executable inline math (display only)
      {!expr!}  - executable, output on new line
      {=expr=}  - executable, inline output (same line)

    Formatting:
      **bold**        - bold text
      *italic*        - italic text
      __underline__   - underlined text
      {color:name}text{/color} - colored text (red, blue, green, etc.)
    """
    import re
    from xml.sax.saxutils import escape

    _active_bg = [None]
    _placeholders = {}
    _ph_counter = [0]

    def _protect(m, executable=False):
        """Replace equation markup with placeholder to protect from formatting."""
        key = f"\x00EQ{_ph_counter[0]}\x00"
        _ph_counter[0] += 1
        _placeholders[key] = (m.group(1), executable)
        return key

    def _restore_equations(text):
        """Replace placeholders with actual equation XML."""
        for key, (expr, exe) in _placeholders.items():
            eq_xml = _equation_xml(expr, executable=exe, background=_active_bg[0])
            text = text.replace(key, eq_xml)
        return text

    # Step 1: Protect equations with placeholders (so * inside isn't treated as italic)
    result = re.sub(r'\{\{(.+?)\}\}', lambda m: _protect(m, False), text)
    result = re.sub(r'\{!(.+?)!\}', lambda m: _protect(m, True), result)
    result = re.sub(r'\{=(.+?)=\}', lambda m: _protect(m, True), result)

    # Step 2: Process formatting (safe now - equations are placeholders)
    # Flatten nested same-color blocks: {color:X}a {color:X}b{/color} c{/color} → {color:X}a b c{/color}
    def _flatten_colors(text):
        i, depth, current_color, parts = 0, 0, None, []
        while i < len(text):
            m_open = re.match(r'\{color:([0-9,]+)\}', text[i:])
            if m_open:
                if depth == 0:
                    current_color = m_open.group(1)
                    parts.append(m_open.group())
                depth += 1
                i += len(m_open.group())
            elif text[i:].startswith('{/color}'):
                depth -= 1
                if depth == 0:
                    parts.append('{/color}')
                    current_color = None
                i += len('{/color}')
            else:
                parts.append(text[i])
                i += 1
        return ''.join(parts)

    result = _flatten_colors(result)

    def _replace_color(m):
        rgb = m.group(1)
        color_val = f"[{rgb}]"
        _active_bg[0] = color_val
        inner = _restore_equations(m.group(2))
        inner = re.sub(r'\*\*(.+?)\*\*', lambda m2: _font_xml(m2.group(1), bold=True, raw=True), inner)
        _active_bg[0] = None
        return _font_xml(inner, color=color_val, raw=True)

    result = re.sub(r'\{color:([0-9,]+)\}(.+?)\{/color\}', _replace_color, result)
    result = re.sub(r'\*\*(.+?)\*\*', lambda m: _font_xml(m.group(1), bold=True, raw=True), result)
    result = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', lambda m: _font_xml(m.group(1), italic=True, raw=True), result)
    result = re.sub(r'__(.+?)__', lambda m: _font_xml(m.group(1), underline=True, raw=True), result)

    # Step 3: Restore remaining equations (outside color blocks)
    _active_bg[0] = None
    result = _restore_equations(result)

    return result


def _has_exec_inline(text: str) -> bool:
    return '{=' in text and '=}' in text


def _has_any_markup(text: str) -> bool:
    return ('{{' in text or '{!' in text or '{=' in text
            or '**' in text or '__' in text
            or '{color:' in text
            or re.search(r'(?<!\*)\*(?!\*).+?(?<!\*)\*(?!\*)', text) is not None)


def _extract_color_from_text(text: str) -> str | None:
    """Extract RGB color if entire text is wrapped in {color:R,G,B}...{/color}."""
    import re
    m = re.match(r'^\{color:([0-9,]+)\}.*\{/color\}$', text)
    return f"[{m.group(1)}]" if m else None


def _make_text_block(text: str, label_num: int, align: str = "left") -> str:
    inline_output = _has_exec_inline(text)
    attribs = _group_attribs(label_num, inline_output=inline_output)
    attrs_str = " ".join(f'{k}="{v}"' for k, v in attribs.items())

    # Check if entire block has a background color
    bg_color = _extract_color_from_text(text)

    if _has_any_markup(text):
        inner = _parse_markup(text)
    else:
        from xml.sax.saxutils import escape
        inner = escape(text)

    alignment = {"left": "left", "center": "centred", "right": "right"}.get(align, "left")

    # Add background to Text-field itself (like Maple does for highlighted text)
    tf_attrs = f'style="Text" layout="Normal" alignment="{alignment}"'
    if bg_color:
        tf_attrs += f' opaque="true" background="{bg_color}"'

    return (
        f'<Presentation-Block>'
        f'<Group {attrs_str}>'
        f'<Input><Text-field {tf_attrs}>'
        f'{inner}'
        f'</Text-field></Input>'
        f'</Group></Presentation-Block>'
    )


def _make_code_block(code: str, label_num: int) -> str:
    attribs = _group_attribs(label_num)
    attrs_str = " ".join(f'{k}="{v}"' for k, v in attribs.items())
    eq_xml = _equation_xml(code, executable=True)
    return (
        f'<Presentation-Block>'
        f'<Group {attrs_str}>'
        f'<Input><Text-field style="Text" layout="Normal">'
        f'{eq_xml}'
        f'</Text-field></Input>'
        f'</Group></Presentation-Block>'
    )


DRAWING_ROOT_DATA = (
    "LSUrQU5OT1RBVElPTkc2Jy0lKUJPVU5EU19YRzYjLCQtJSZGbG9hdEc2IyUp"
    "aW5maW5pdHlHISIiLSUpQk9VTkRTX1lHRictJS1CT1VORFNfV0lEVEhHRict"
    "JS5CT1VORFNfSEVJR0hUR0YnLSUpQ0hJTERSRU5HNiI="
)


def _make_image_block(image_data: bytes, label_num: int, width: int = 0, height: int = 0, align: str = "center") -> str:
    if not width or not height:
        width, height = _get_png_dimensions(image_data)

    encoded = encode_maple_image(image_data)
    alignment = {"left": "left", "center": "centred", "right": "right"}.get(align, "centred")

    return (
        '<Presentation-Block>'
        f'<Group view="presentation" inline-output="false" '
        f'labelreference="L{label_num}" drawlabel="true" '
        f'applyint="true" applyrational="true" applyexponent="false">'
        f'<Input><Text-field style="Text" layout="Normal" alignment="{alignment}">'
        f'<Image height="{height}" width="{width}" zoomable="false" '
        f'drawcaption="false" captionalignment="0" '
        f'captionposition="1" bookmark="">'
        f'{encoded}'
        f'<Drawing-Root>{DRAWING_ROOT_DATA}</Drawing-Root>'
        f'</Image></Text-field></Input>'
        f'</Group></Presentation-Block>'
    )


def _get_png_dimensions(data: bytes) -> tuple[int, int]:
    if data[:4] == b'\x89PNG' and len(data) >= 24:
        import struct
        w, h = struct.unpack(">II", data[16:24])
        return w, h
    return 400, 300


def _make_section(title: str, level: int, content_blocks: list) -> str:
    style = f"Heading {level}" if 1 <= level <= 4 else "Heading 1"
    from xml.sax.saxutils import escape
    inner = "".join(_block_to_xml(b) for b in content_blocks)
    return (
        f'<Section collapsed="false" isCollapsible="true" drawButton="true"'
        f' MultipleChoiceAnswerIndex="-1" MultipleChoiceRandomizeChoices="false"'
        f' TrueFalseAnswerIndex="-1" EssayAnswerRows="5" EssayAnswerColumns="60">'
        f'<Title><Text-field style="{style}" layout="{style}">'
        f'{escape(title)}</Text-field></Title>'
        f'{inner}'
        f'</Section>'
    )


def _make_title_block(text: str, label_num: int) -> str:
    attribs = _group_attribs(label_num)
    attrs_str = " ".join(f'{k}="{v}"' for k, v in attribs.items())
    from xml.sax.saxutils import escape
    return (
        f'<Presentation-Block>'
        f'<Group {attrs_str}>'
        f'<Input><Text-field style="Title" layout="Title">'
        f'{escape(text)}</Text-field></Input>'
        f'</Group></Presentation-Block>'
    )


def _block_to_xml(block) -> str:
    if isinstance(block, str):
        return block
    return ET.tostring(block, encoding="unicode")


def _backup(file_path: str) -> str | None:
    """Push the current file onto the out-of-tree rotating backup ring and return
    the new backup path. Backups live OUTSIDE the document folder (see backup.py)
    so the user's assignment directory stays clean — no .bak clutter."""
    from maple_mcp import backup as _bk
    return _bk.push(file_path)


def _commit(file_path: str, content: str, backup_path: str | None = None) -> None:
    """Write `content` ONLY if the whole document is still well-formed XML.

    Every edit splices a raw string; a mis-computed offset or an unescaped char
    would otherwise silently corrupt the .mw — the tool would report success and
    Maple would later refuse to open the file. We validate the entire spliced
    document first (read_document already ET-parses the file, so this is a fair,
    cheap invariant). On failure the file is left untouched and the just-made
    backup is discarded, so no phantom undo step is left behind.
    """
    try:
        # Encode to bytes: the .mw carries an XML encoding declaration, which
        # ET.fromstring rejects on a str ("encoding declaration not supported").
        ET.fromstring(content.encode("utf-8"))
    except ET.ParseError as e:
        from maple_mcp import backup as _bk
        _bk.discard(backup_path)
        raise ValueError(
            f"Edit aborted — the result would not be a well-formed Maple document "
            f"(XML error: {e}). The file was left unchanged."
        ) from e
    Path(file_path).write_text(content, encoding="utf-8")


def _append_blocks(file_path: str, blocks, backup_path: str | None = None) -> str:
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")

    close_tag = "</Worksheet>"
    idx = content.rfind(close_tag)
    if idx == -1:
        raise ValueError("No </Worksheet> found in file")

    new_xml = "\n".join(_block_to_xml(b) for b in blocks)
    content = content[:idx] + new_xml + "\n" + content[idx:]

    _commit(file_path, content, backup_path)
    return str(path)


def _decode_equation_text(eq_el: ET.Element) -> str:
    b64 = eq_el.text
    if not b64:
        return "[CORRUPT EQUATION]"
    try:
        result = engine.decode_equation(b64.strip())
        return result if result else "[CORRUPT EQUATION]"
    except Exception:
        return "[CORRUPT EQUATION]"


def _decode_entities(text: str) -> str:
    from maple_mcp.maple_engine import normalize_decoded_glyphs
    return normalize_decoded_glyphs(text)


def _extract_text(el: ET.Element) -> str:
    # Check if the Text-field itself has a background color
    tf_bg = None
    if el.get("opaque") == "true" and el.get("background"):
        tf_bg = el.get("background", "").strip("[]")

    parts = []

    def _process_children(element):
        if element.text:
            parts.append(element.text.strip())
        for child in element:
            if child.tag == "Equation":
                exe = child.get("executable", "false") == "true"
                decoded = _decode_equation_text(child)
                eq_bg = getattr(engine, '_last_eq_background', None)
                if decoded and decoded != "[CORRUPT EQUATION]":
                    if exe:
                        eq_markup = f"{{!{decoded}!}}"
                    else:
                        eq_markup = f"{{{{{decoded}}}}}"
                    # Only add per-equation color if different from parent
                    if eq_bg and eq_bg != tf_bg:
                        eq_markup = f"{{color:{eq_bg}}}{eq_markup}{{/color}}"
                    parts.append(eq_markup)
                else:
                    parts.append("[CORRUPT EQUATION]")
            elif child.tag == "Font":
                bold = child.get("bold") == "true"
                italic = child.get("italic") == "true"
                underline = child.get("underline") == "true"
                has_bg = child.get("opaque") == "true" and child.get("background")
                bg_color = child.get("background", "")

                old_parts = list(parts)
                parts.clear()
                _process_children(child)
                inner_text = " ".join(p for p in parts if p)
                parts.clear()
                parts.extend(old_parts)

                if inner_text:
                    if bold:
                        inner_text = f"**{inner_text}**"
                    if italic:
                        inner_text = f"*{inner_text}*"
                    if underline:
                        inner_text = f"__{inner_text}__"
                    # Only wrap in color if different from parent Text-field
                    if has_bg and bg_color.strip("[]") != tf_bg:
                        rgb = bg_color.strip("[]")
                        inner_text = f"{{color:{rgb}}}{inner_text}{{/color}}"
                    parts.append(inner_text)
            elif child.tag == "Image":
                pass  # Images handled separately
            if child.tail:
                parts.append(child.tail.strip())

    _process_children(el)
    text = " ".join(p for p in parts if p)

    # Wrap entire text in parent's background color (one block, not fragmented)
    if tf_bg:
        text = f"{{color:{tf_bg}}}{text}{{/color}}"

    return _decode_entities(_decode_maple_text(text))


def block_count(file_path: str) -> int:
    content = Path(file_path).read_text(encoding="utf-8")
    return len(_find_block_positions(content))


def read_document(file_path: str, start: int = 0, end: int | None = None) -> list[dict]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    tree = ET.parse(path)
    root = tree.getroot()
    entries = []

    def _process_group(group: ET.Element):
        texts = []
        inputs = []
        outputs = []
        images = []
        group_style = None
        group_align = None

        for tf in group.iter("Text-field"):
            style = tf.get("style", "")
            content = _extract_text(tf)

            # Track alignment
            align = tf.get("alignment", "")
            if align == "centred":
                group_align = "center"
            elif align == "right":
                group_align = "right"

            for img_el in tf.iter("Image"):
                w = img_el.get("width", "0")
                h = img_el.get("height", "0")
                img_entry = {"width": int(w), "height": int(h)}
                if img_el.text:
                    img_entry["encoded"] = img_el.text
                images.append(img_entry)

            if not content:
                continue

            if style == "Maple Input":
                inputs.append(content)
            elif "Output" in style:
                outputs.append(content)
            elif style == "Title":
                group_style = "title"
                texts.append(content)
            elif style in ("Heading 1", "Heading 2", "Heading 3", "Heading 4"):
                group_style = style
                texts.append(content)
            elif style in ("Text", "Normal", ""):
                texts.append(content)

        for eq in group.iter("Equation"):
            if eq.get("style") in ("2D Output", "Maple Output"):
                ie = eq.get("input-equation", "")
                if ie:
                    outputs.append(ie)

        if images:
            for img in images:
                entries.append({
                    "type": "image",
                    "width": img["width"],
                    "height": img["height"],
                    "encoded": img.get("encoded", ""),
                })
        if inputs:
            entries.append({"type": "code", "content": inputs, "output": outputs})
        elif texts:
            if group_style == "title":
                entries.append({"type": "title", "content": " ".join(texts)})
            elif group_style and group_style.startswith("Heading"):
                entries.append({
                    "type": "heading",
                    "content": " ".join(texts),
                    "level": int(group_style[-1]),
                })
            else:
                entry = {"type": "text", "content": " ".join(texts)}
                if outputs:
                    entry["output"] = outputs
                if group_align:
                    entry["align"] = group_align
                entries.append(entry)

    block_idx = [0]
    eff_end = end if end is not None else float("inf")
    nesting_depth = [0]

    def _walk(parent: ET.Element):
        for child in parent:
            if child.tag == "Section":
                nesting_depth[0] += 1
                if start <= block_idx[0] < eff_end:
                    for title_el in child.iter("Title"):
                        for tf in title_el.iter("Text-field"):
                            content = _extract_text(tf)
                            if content:
                                entries.append({
                                    "block": block_idx[0],
                                    "type": "section",
                                    "content": content,
                                    "level": nesting_depth[0],
                                })
                        break
                block_idx[0] += 1
                _walk(child)
                nesting_depth[0] -= 1
            elif child.tag == "Presentation-Block":
                if start <= block_idx[0] < eff_end:
                    pre_len = len(entries)
                    for group in child.iter("Group"):
                        _process_group(group)
                    new_entries = entries[pre_len:]
                    if len(new_entries) > 1:
                        parts = []
                        for e in new_entries:
                            c = e.get("content", "")
                            if isinstance(c, list):
                                c = "; ".join(c)
                            if c:
                                parts.append(c)
                        del entries[pre_len:]
                        entries.append({"type": "text", "content": " ".join(parts)})
                    # If no entries produced, it's an empty line
                    if len(entries) == pre_len:
                        entries.append({"type": "empty"})
                    for entry in entries[pre_len:]:
                        if "block" not in entry:
                            entry["block"] = block_idx[0]
                        entry["depth"] = nesting_depth[0]
                block_idx[0] += 1

    _walk(root)

    # Surface (don't silently drop) blocks whose equation failed to decode: a
    # dropped block makes the user risk editing/deleting the wrong neighbour. Relabel
    # to a clearer, still-targetable marker; the block keeps its [N] index in read.
    def _relabel(c):
        if isinstance(c, list):
            return [x.replace("[CORRUPT EQUATION]", "[unreadable equation]")
                    if isinstance(x, str) else x for x in c]
        if isinstance(c, str):
            return c.replace("[CORRUPT EQUATION]", "[unreadable equation]")
        return c
    for e in entries:
        if "content" in e:
            e["content"] = _relabel(e["content"])
    # Strip trailing empty blocks (genuinely blank lines)
    while entries and entries[-1].get("type") == "empty":
        entries.pop()

    return entries if entries else []


def _find_block_positions(content: str) -> list[dict]:
    """Find start/end positions of all Presentation-Blocks and Sections in order.

    Finds nested PBs inside Sections too, so edits target the most specific block.
    """
    blocks = []
    pb_tag_open = "<Presentation-Block"
    pb_tag_close = "</Presentation-Block>"
    sec_tag_open = "<Section "
    sec_tag_close = "</Section>"

    i = 0
    while i < len(content):
        pb_pos = content.find(pb_tag_open, i)
        sec_pos = content.find(sec_tag_open, i)

        if pb_pos == -1 and sec_pos == -1:
            break

        if pb_pos != -1 and (sec_pos == -1 or pb_pos < sec_pos):
            end_pos = content.find(pb_tag_close, pb_pos)
            if end_pos == -1:
                break
            end_pos += len(pb_tag_close)
            blocks.append({"start": pb_pos, "end": end_pos, "tag": "pb"})
            i = end_pos
        else:
            # Find matching close tag for the section
            depth = 0
            j = sec_pos
            sec_end = -1
            while j < len(content):
                next_open = content.find(sec_tag_open, j + 1)
                next_close = content.find(sec_tag_close, j + 1)
                if next_close == -1:
                    break
                if next_open != -1 and next_open < next_close:
                    depth += 1
                    j = next_open
                elif depth > 0:
                    depth -= 1
                    j = next_close
                else:
                    sec_end = next_close + len(sec_tag_close)
                    break

            if sec_end == -1:
                break

            blocks.append({"start": sec_pos, "end": sec_end, "tag": "section"})
            # Continue searching INSIDE the section for nested PBs and sub-sections
            i = sec_pos + len(sec_tag_open)

    return blocks


def _decode_maple_text(text: str) -> str:
    """Decode Maple's escaped UTF-8 sequences like \\303\\270 → ø."""
    result = []
    i = 0
    while i < len(text):
        if text[i] == '\\' and i + 3 < len(text) and text[i+1:i+4].isdigit():
            # Collect consecutive octal escapes (UTF-8 multi-byte)
            raw_bytes = bytearray()
            while i < len(text) and text[i] == '\\' and i + 3 < len(text) and text[i+1:i+4].isdigit():
                raw_bytes.append(int(text[i+1:i+4], 8))
                i += 4
            try:
                result.append(raw_bytes.decode('utf-8'))
            except UnicodeDecodeError:
                result.append(raw_bytes.decode('latin-1'))
        else:
            result.append(text[i])
            i += 1
    return "".join(result)


def _get_block_text(content: str, block: dict) -> str:
    """Extract decoded text from a raw XML block for matching.

    Uses the same _extract_text as read_document so match strings
    correspond exactly to what the LLM sees in read output.
    """
    raw = content[block["start"]:block["end"]]
    try:
        el = ET.fromstring(raw)
    except ET.ParseError:
        return raw[:200]

    if block["tag"] == "section":
        # Sections: return "## title" with depth prefix (matches read_document format)
        # +1 to include the section's own <Section> tag in the count
        depth = _count_section_depth(content, block["start"] + len("<Section "))
        for title in el.iter("Title"):
            for tf in title.iter("Text-field"):
                title_text = _extract_text(tf)
                return f"{'#' * depth} {title_text}"
        return ""

    # PB blocks: extract from non-output Text-fields
    parts = []
    for tf in el.iter("Text-field"):
        style = tf.get("style", "")
        if "Output" in style:
            continue
        parts.append(_extract_text(tf))

    return " ".join(p for p in parts if p)


def _block_ordinal(blocks: list[dict], block: dict) -> int:
    """The block's index in document order (matches read_document's [N] labels)."""
    for i, b in enumerate(blocks):
        if b["start"] == block["start"]:
            return i
    return -1


def _block_preview(content: str, block: dict, width: int = 60) -> str:
    txt = " ".join(_get_block_text(content, block).split())
    return txt[:width] + ("…" if len(txt) > width else "")


def _candidate_list(content: str, blocks: list[dict], candidates: list[dict]) -> str:
    return "\n".join(
        f"  {i + 1}: [#{_block_ordinal(blocks, b)}] {_block_preview(content, b)!r}"
        for i, b in enumerate(candidates))


def _find_matching_block(
    content: str,
    blocks: list[dict],
    match: str,
    section: str | None = None,
    occurrence: int | None = None,
) -> dict:
    """Find a block by content matching, or by explicit index via match='#N'
    (the [N] shown by read_document)."""
    idx_match = re.fullmatch(r'#(\d+)', match.strip())
    if idx_match:
        n = int(idx_match.group(1))
        if not (0 <= n < len(blocks)):
            raise ValueError(
                f"Block index #{n} is out of range (document has {len(blocks)} "
                f"blocks, 0..{len(blocks) - 1}). Re-read — indices shift after edits."
            )
        return blocks[n]

    # Memoize block text — _get_block_text ET-parses and kernel-decodes each
    # equation, so computing it once per block (not once per block PAIR) turns the
    # section-scoped search from O(B^2) into O(B). The decode cache compounds this.
    _text_cache: dict[int, str] = {}

    def _text(b: dict) -> str:
        key = b["start"]
        if key not in _text_cache:
            _text_cache[key] = _get_block_text(content, b)
        return _text_cache[key]

    # Resolve the matching section span(s) ONCE, then test each block by interval.
    section_spans = None
    if section:
        section_spans = [(b["start"], b["end"]) for b in blocks
                         if b["tag"] == "section" and section in _text(b)]

    candidates = []
    for block in blocks:
        if section_spans is not None and not any(
                s <= block["start"] < e for s, e in section_spans):
            continue
        if match in _text(block):
            candidates.append(block)

    # Filter out Sections when a PB inside them also matches
    # (Section text includes all nested content, so it always matches too)
    if len(candidates) > 1:
        non_section = [b for b in candidates if b["tag"] != "section"]
        if non_section:
            candidates = non_section

    if not candidates:
        raise ValueError(f"No block found matching '{match}'"
                         + (f" in section '{section}'" if section else ""))

    if occurrence is None:
        if len(candidates) > 1:
            raise ValueError(
                f"Ambiguous: {len(candidates)} blocks match '{match}'. Pass "
                f"occurrence=N (1-based), match='#<block index>', or a longer, "
                f"more unique match. Candidates:\n"
                + _candidate_list(content, blocks, candidates)
            )
        return candidates[0]

    if occurrence > len(candidates):
        raise ValueError(
            f"Occurrence {occurrence} requested but only {len(candidates)} block(s) "
            f"match '{match}':\n" + _candidate_list(content, blocks, candidates)
        )

    return candidates[occurrence - 1]


def find_block(file_path: str, match: str, section: str | None = None,
               occurrence: int | None = None) -> dict:
    """Resolve a match to a block WITHOUT mutating (a dry-run locate). Returns the
    block index, tag, and current text — so an edit can be checked before writing."""
    content = Path(file_path).read_text(encoding="utf-8")
    blocks = _find_block_positions(content)
    block = _find_matching_block(content, blocks, match, section, occurrence)
    return {
        "block": _block_ordinal(blocks, block),
        "tag": block["tag"],
        "text": _get_block_text(content, block),
    }


def _count_section_depth(content: str, position: int) -> int:
    """Count how many <Section> elements contain this position."""
    depth = 0
    i = 0
    while i < position:
        sec_open = content.find("<Section ", i)
        sec_close = content.find("</Section>", i)

        if sec_open == -1 and sec_close == -1:
            break

        # Take whichever comes first
        if sec_open != -1 and (sec_close == -1 or sec_open < sec_close):
            if sec_open < position:
                depth += 1
                i = sec_open + len("<Section ")
            else:
                break
        else:
            if sec_close < position:
                depth -= 1
                i = sec_close + len("</Section>")
            else:
                break

    return max(0, depth)


def _validate_heading_depth(content: str, position: int, items: list[dict]):
    """Validate that heading levels match the insertion depth."""
    depth = _count_section_depth(content, position)
    for item in items:
        if item.get("type") == "heading":
            expected_level = depth + 1
            actual_level = item.get("level", 1)
            if actual_level != expected_level:
                raise ValueError(
                    f"Heading level mismatch: inserting level {actual_level} "
                    f"heading but insertion point is at depth {depth} "
                    f"(expected level {expected_level}). "
                    f"This would create wrong nesting in the document."
                )


def _readback(new_xml: str) -> str:
    """Parse inserted XML back to readable text to verify encoding."""
    try:
        root = ET.fromstring(f"<R>{new_xml}</R>")
    except ET.ParseError:
        return ""

    parts = []

    def _walk(parent):
        for child in parent:
            if child.tag == "Section":
                for title in child.iter("Title"):
                    for tf in title.iter("Text-field"):
                        text = _extract_text(tf)
                        if text:
                            style = tf.get("style", "")
                            level = int(style[-1]) if style.startswith("Heading") else 1
                            parts.append(f"{'#' * level} {text}")
                    break
                _walk(child)
            elif child.tag == "Presentation-Block":
                for group in child.iter("Group"):
                    for tf in group.iter("Text-field"):
                        style = tf.get("style", "")
                        if "Output" in style:
                            continue
                        text = _extract_text(tf)
                        if text:
                            if style == "Title":
                                parts.append(f"TITLE: {text}")
                            else:
                                parts.append(text)
                        for img in tf.iter("Image"):
                            parts.append("[IMAGE]")

    _walk(root)
    return "\n".join(parts)


def insert_after(file_path: str, match: str, items: list[dict],
                 section: str | None = None, occurrence: int | None = None) -> str:
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")
    blocks = _find_block_positions(content)
    block = _find_matching_block(content, blocks, match, section, occurrence)

    _validate_heading_depth(content, block["end"], items)

    label = _next_label_num_from_text(content)
    new_blocks, _, _ = _build_nested(items, 0, label)
    new_xml = "\n".join(_block_to_xml(b) for b in new_blocks)

    new_content = content[:block["end"]] + "\n" + new_xml + content[block["end"]:]
    bkp = _backup(file_path)
    _commit(file_path, new_content, bkp)
    return _readback(new_xml)


def insert_before(file_path: str, match: str, items: list[dict],
                  section: str | None = None, occurrence: int | None = None) -> str:
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")
    blocks = _find_block_positions(content)
    block = _find_matching_block(content, blocks, match, section, occurrence)

    _validate_heading_depth(content, block["start"], items)

    label = _next_label_num_from_text(content)
    new_blocks, _, _ = _build_nested(items, 0, label)
    new_xml = "\n".join(_block_to_xml(b) for b in new_blocks)

    new_content = content[:block["start"]] + new_xml + "\n" + content[block["start"]:]
    bkp = _backup(file_path)
    _commit(file_path, new_content, bkp)
    return _readback(new_xml)


def replace_block(file_path: str, match: str, items: list[dict],
                  section: str | None = None, occurrence: int | None = None) -> str:
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")
    blocks = _find_block_positions(content)
    block = _find_matching_block(content, blocks, match, section, occurrence)

    if block["tag"] == "section":
        child_count = sum(1 for b in blocks
                         if b["start"] > block["start"] and b["end"] <= block["end"]
                         and b is not block)
        if child_count > 0:
            block_text = _get_block_text(content, block)[:80]
            raise ValueError(
                f"Matched a SECTION: '{block_text}' with {child_count} child blocks. "
                f"Replacing would destroy all content. Match a specific block inside instead."
            )

    label = _next_label_num_from_text(content)
    new_blocks, _, _ = _build_nested(items, 0, label)
    new_xml = "\n".join(_block_to_xml(b) for b in new_blocks)

    new_content = content[:block["start"]] + new_xml + content[block["end"]:]
    bkp = _backup(file_path)
    _commit(file_path, new_content, bkp)
    return _readback(new_xml)


def delete_block(file_path: str, match: str,
                 section: str | None = None, occurrence: int | None = None,
                 delete_section: bool = False) -> str:
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")
    blocks = _find_block_positions(content)
    block = _find_matching_block(content, blocks, match, section, occurrence)

    if block["tag"] == "section" and not delete_section:
        # Count child blocks
        child_count = sum(1 for b in blocks
                         if b["start"] > block["start"] and b["end"] <= block["end"]
                         and b is not block)
        block_text = _get_block_text(content, block)[:80]
        raise ValueError(
            f"Matched a SECTION: '{block_text}' containing {child_count} child blocks. "
            f"This would delete the entire section and all its content. "
            f"Set delete_section=True if this is intended, or use a more specific match."
        )

    new_content = content[:block["start"]] + content[block["end"]:]
    bkp = _backup(file_path)
    _commit(file_path, new_content, bkp)


def _extract_align(text: str) -> tuple[str, str | None]:
    """Pull a trailing `[align:left|center|right]` tag off the text. This is the
    exact form read_document prints for an aligned block, so what you read can be
    written straight back (read/write symmetry)."""
    import re
    m = re.search(r'\s*\[align:(left|center|right)\]\s*$', text)
    if m:
        return text[:m.start()].rstrip(), m.group(1)
    return text, None


def _make_block(item: dict, label_num: int) -> str:
    t = item.get("type", "text")
    if t == "empty":
        return _make_text_block("", label_num)
    elif t == "code":
        return _make_code_block(item["content"], label_num)
    elif t == "title":
        return _make_title_block(item["content"], label_num)
    elif t == "heading":
        return _make_section(item["content"], item.get("level", 1), [])
    elif t == "image" and item.get("path"):
        img_data = Path(item["path"]).read_bytes()
        return _make_image_block(img_data, label_num)
    else:
        content, inline_align = _extract_align(item.get("content", ""))
        align = inline_align or item.get("align", "left")
        return _make_text_block(content, label_num, align=align)


def _make_block_ctx(items: list[dict], i: int, label_num: int) -> str:
    """_make_block, but on failure name the offending item (index + content) so an
    atomic batch failure is debuggable instead of a bare snippet error."""
    try:
        return _make_block(items[i], label_num)
    except ValueError as e:
        it = items[i]
        content = str(it.get("content", it))
        if len(content) > 80:
            content = content[:80] + "…"
        raise ValueError(
            f"item {i} (type={it.get('type', 'text')!r}, content={content!r}): {e}"
        ) from e


def _build_nested(items: list[dict], start: int, label_start: int,
                   parent_level: int = 0) -> tuple[list[str], int, int]:
    """Build blocks with nested section support.

    Returns (blocks, next_index, next_label).
    """
    blocks = []
    label = label_start
    i = start

    while i < len(items):
        item = items[i]
        t = item.get("type", "text")

        if t == "heading":
            level = item.get("level", 1)
            if level <= parent_level:
                break

            i += 1
            section_content = []

            while i < len(items):
                nt = items[i].get("type", "text")
                if nt == "heading":
                    nl = items[i].get("level", 1)
                    if nl <= level:
                        break
                    sub, i, label = _build_nested(items, i, label, level)
                    section_content.extend(sub)
                else:
                    section_content.append(_make_block_ctx(items, i, label))
                    label += 1
                    i += 1

            blocks.append(_make_section(item["content"], level, section_content))
        else:
            blocks.append(_make_block_ctx(items, i, label))
            label += 1
            i += 1

    return blocks, i, label


def insert_content(file_path: str, items: list[dict]) -> str:
    content = Path(file_path).read_text(encoding="utf-8")
    label = _next_label_num_from_text(content)
    blocks, _, _ = _build_nested(items, 0, label)   # may raise before any backup
    bkp = _backup(file_path)
    _append_blocks(file_path, blocks, bkp)
    new_xml = "\n".join(_block_to_xml(b) for b in blocks)
    return _readback(new_xml)
