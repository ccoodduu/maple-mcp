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
    return re.sub(r'\[\[(.+?)\]\]', _replace, expr)


def _equation_xml(expr: str, executable: bool = True, style: str = "2D Math") -> str:
    expr = _replace_units_in_expr(expr)
    display_b64, content_b64 = engine.encode_equation(expr)
    exe = "true" if executable else "false"
    return (
        f'<Equation executable="{exe}" style="{style}" '
        f'input-equation="" display="{display_b64}">'
        f'{content_b64}</Equation>'
    )


def _font_xml(text: str, bold=False, italic=False, underline=False,
               color=None, size=None) -> str:
    attrs = []
    if bold:
        attrs.append('bold="true"')
    if italic:
        attrs.append('italic="true"')
    if underline:
        attrs.append('underline="true"')
    if color:
        attrs.append(f'foreground="{color}"')
    if size:
        attrs.append(f'size="{size}"')
    from xml.sax.saxutils import escape
    attr_str = " ".join(attrs)
    return f'<Font {attr_str}>{escape(text)}</Font>'


UNIT_MAP = {
    "ohm": "Ω", "Omega": "Ω", "Ω": "Ω",
    "degC": "°C", "degF": "°F", "deg": "°",
    "mu": "μ", "micro": "μ",
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
    "Delta": "Δ", "epsilon": "ε", "theta": "θ", "lambda": "λ",
    "pi": "π", "rho": "ρ", "sigma": "σ", "tau": "τ",
    "phi": "φ", "omega": "ω", "eta": "η", "nu": "ν",
    "inf": "∞", "neq": "≠", "approx": "≈",
    "leq": "≤", "geq": "≥", "pm": "±",
    "cdot": "·", "times": "×", "sqrt": "√",
    "sum": "∑", "prod": "∏", "int": "∫",
    "in": "∈", "notin": "∉", "subset": "⊂",
    "forall": "∀", "exists": "∃",
    "Rarr": "→", "Larr": "←", "Harr": "↔", "dArr": "⇕", "hArr": "⇔",
}


COLOR_MAP = {
    "red": "[255,0,0]", "blue": "[0,0,255]", "green": "[0,128,0]",
    "orange": "[255,165,0]", "purple": "[128,0,128]", "gray": "[128,128,128]",
    "black": "[0,0,0]", "white": "[255,255,255]",
}


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

    def _replace_display(m):
        return _equation_xml(m.group(1), executable=False)

    def _replace_exec(m):
        return _equation_xml(m.group(1), executable=True)

    def _replace_color(m):
        color_name = m.group(1).lower()
        color_val = COLOR_MAP.get(color_name, f"[{color_name}]")
        return _font_xml(m.group(2), color=color_val)

    # Equations first (before escaping)
    result = re.sub(r'\{\{(.+?)\}\}', _replace_display, text)
    result = re.sub(r'\{!(.+?)!\}', _replace_exec, result)
    result = re.sub(r'\{=(.+?)=\}', _replace_exec, result)

    # Text formatting
    result = re.sub(r'\*\*(.+?)\*\*', lambda m: _font_xml(m.group(1), bold=True), result)
    result = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', lambda m: _font_xml(m.group(1), italic=True), result)
    result = re.sub(r'__(.+?)__', lambda m: _font_xml(m.group(1), underline=True), result)
    result = re.sub(r'\{color:(\w+)\}(.+?)\{/color\}', _replace_color, result)

    return result


def _has_exec_inline(text: str) -> bool:
    return '{=' in text and '=}' in text


def _has_any_markup(text: str) -> bool:
    return ('{{' in text or '{!' in text or '{=' in text
            or '**' in text or '__' in text
            or '{color:' in text
            or re.search(r'(?<!\*)\*(?!\*).+?(?<!\*)\*(?!\*)', text) is not None)


def _make_text_block(text: str, label_num: int, align: str = "left") -> str:
    inline_output = _has_exec_inline(text)
    attribs = _group_attribs(label_num, inline_output=inline_output)
    attrs_str = " ".join(f'{k}="{v}"' for k, v in attribs.items())

    if _has_any_markup(text):
        inner = _parse_markup(text)
    else:
        from xml.sax.saxutils import escape
        inner = escape(text)

    alignment = {"left": "left", "center": "centred", "right": "right"}.get(align, "left")

    return (
        f'<Presentation-Block>'
        f'<Group {attrs_str}>'
        f'<Input><Text-field style="Text" layout="Normal" alignment="{alignment}">'
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
        f'<Section collapsed="false" isCollapsible="true">'
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


def _append_blocks(file_path: str, blocks) -> str:
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")

    close_tag = "</Worksheet>"
    idx = content.rfind(close_tag)
    if idx == -1:
        raise ValueError("No </Worksheet> found in file")

    new_xml = "\n".join(_block_to_xml(b) for b in blocks)
    content = content[:idx] + new_xml + "\n" + content[idx:]

    path.write_text(content, encoding="utf-8")
    return str(path)


def _decode_equation_text(eq_el: ET.Element) -> str:
    b64 = eq_el.text
    if not b64:
        return "[math]"
    try:
        return engine.decode_equation(b64.strip())
    except Exception:
        return "[math]"


HTML_ENTITIES = {
    "&sdot;": "·", "&times;": "×", "&minus;": "−",
    "&DoubleLeftRightArrow;": "⇔", "&LeftRightArrow;": "↔",
    "&RightArrow;": "→", "&LeftArrow;": "←",
    "&GreaterEqual;": "≥", "&LessEqual;": "≤",
    "&deg;": "°", "&ohm;": "Ω", "&Omega;": "Ω",
    "&alpha;": "α", "&beta;": "β", "&gamma;": "γ",
    "&delta;": "δ", "&Delta;": "Δ", "&epsilon;": "ε",
    "&theta;": "θ", "&lambda;": "λ", "&mu;": "μ",
    "&pi;": "π", "&rho;": "ρ", "&sigma;": "σ",
    "&tau;": "τ", "&phi;": "φ", "&omega;": "ω",
    "&eta;": "η", "&nu;": "ν",
    "&in;": "∈", "&notin;": "∉",
    "&infin;": "∞", "&plusmn;": "±",
    "&sum;": "∑", "&prod;": "∏", "&int;": "∫",
    "&sqrt;": "√", "&ne;": "≠", "&approx;": "≈",
}


def _decode_entities(text: str) -> str:
    import re
    for entity, char in HTML_ENTITIES.items():
        text = text.replace(entity, char)
    text = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)
    text = re.sub(r'&#x([0-9a-fA-F]+);', lambda m: chr(int(m.group(1), 16)), text)
    return text


def _extract_text(el: ET.Element) -> str:
    parts = []
    if el.text:
        parts.append(el.text.strip())
    for child in el:
        if child.tag == "Equation":
            ie = child.get("input-equation", "")
            if ie:
                parts.append(ie)
            else:
                parts.append(_decode_equation_text(child))
        elif child.tag == "Font":
            if child.text:
                parts.append(child.text.strip())
        if child.tail:
            parts.append(child.tail.strip())
    text = " ".join(p for p in parts if p)
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

        for tf in group.iter("Text-field"):
            style = tf.get("style", "")
            content = _extract_text(tf)

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
                entries.append(entry)

    block_idx = [0]
    eff_end = end if end is not None else float("inf")

    def _walk(parent: ET.Element):
        for child in parent:
            if child.tag == "Section":
                if start <= block_idx[0] < eff_end:
                    for title_el in child.iter("Title"):
                        for tf in title_el.iter("Text-field"):
                            content = _extract_text(tf)
                            if content:
                                style = tf.get("style", "")
                                level = int(style[-1]) if style.startswith("Heading") else 1
                                entries.append({
                                    "block": block_idx[0],
                                    "type": "section",
                                    "content": content,
                                    "level": level,
                                })
                        break
                block_idx[0] += 1
                _walk(child)
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
                    for entry in entries[pre_len:]:
                        if "block" not in entry:
                            entry["block"] = block_idx[0]
                block_idx[0] += 1

    _walk(root)
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
    """Extract decoded text from a raw XML block for matching."""
    raw = content[block["start"]:block["end"]]
    try:
        el = ET.fromstring(raw)
    except ET.ParseError:
        return raw[:200]

    parts = []
    for tf in el.iter("Text-field"):
        style = tf.get("style", "")
        if "Output" in style:
            continue
        parts.append(_extract_text(tf))

    for title in el.iter("Title"):
        for tf in title.iter("Text-field"):
            parts.append(_extract_text(tf))

    return " ".join(p for p in parts if p)


def _find_matching_block(
    content: str,
    blocks: list[dict],
    match: str,
    section: str | None = None,
    occurrence: int | None = None,
) -> dict:
    """Find a block by content matching."""
    candidates = []

    for block in blocks:
        text = _get_block_text(content, block)

        if section:
            in_section = False
            for other in blocks:
                if other["tag"] != "section":
                    continue
                sec_text = _get_block_text(content, other)
                if section in sec_text:
                    if other["start"] <= block["start"] < other["end"]:
                        in_section = True
                        break
            if not in_section:
                continue

        if match in text:
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
                f"Ambiguous: {len(candidates)} blocks match '{match}'. "
                f"Use 'section' or 'occurrence' to disambiguate."
            )
        return candidates[0]

    if occurrence > len(candidates):
        raise ValueError(
            f"Occurrence {occurrence} requested but only {len(candidates)} "
            f"matches found for '{match}'"
        )

    return candidates[occurrence - 1]


def insert_after(file_path: str, match: str, items: list[dict],
                 section: str | None = None, occurrence: int | None = None) -> str:
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")
    blocks = _find_block_positions(content)
    block = _find_matching_block(content, blocks, match, section, occurrence)

    root = ET.parse(file_path).getroot()
    label = _next_label_num(root)
    new_blocks, _, _ = _build_nested(items, 0, label)
    new_xml = "\n".join(_block_to_xml(b) for b in new_blocks)

    content = content[:block["end"]] + "\n" + new_xml + content[block["end"]:]
    path.write_text(content, encoding="utf-8")
    return str(path)


def insert_before(file_path: str, match: str, items: list[dict],
                  section: str | None = None, occurrence: int | None = None) -> str:
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")
    blocks = _find_block_positions(content)
    block = _find_matching_block(content, blocks, match, section, occurrence)

    root = ET.parse(file_path).getroot()
    label = _next_label_num(root)
    new_blocks, _, _ = _build_nested(items, 0, label)
    new_xml = "\n".join(_block_to_xml(b) for b in new_blocks)

    content = content[:block["start"]] + new_xml + "\n" + content[block["start"]:]
    path.write_text(content, encoding="utf-8")
    return str(path)


def replace_block(file_path: str, match: str, items: list[dict],
                  section: str | None = None, occurrence: int | None = None) -> str:
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")
    blocks = _find_block_positions(content)
    block = _find_matching_block(content, blocks, match, section, occurrence)

    root = ET.parse(file_path).getroot()
    label = _next_label_num(root)
    new_blocks, _, _ = _build_nested(items, 0, label)
    new_xml = "\n".join(_block_to_xml(b) for b in new_blocks)

    content = content[:block["start"]] + new_xml + content[block["end"]:]
    path.write_text(content, encoding="utf-8")
    return str(path)


def delete_block(file_path: str, match: str,
                 section: str | None = None, occurrence: int | None = None) -> str:
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")
    blocks = _find_block_positions(content)
    block = _find_matching_block(content, blocks, match, section, occurrence)

    content = content[:block["start"]] + content[block["end"]:]
    path.write_text(content, encoding="utf-8")
    return str(path)


def _make_block(item: dict, label_num: int) -> str:
    t = item.get("type", "text")
    if t == "code":
        return _make_code_block(item["content"], label_num)
    elif t == "title":
        return _make_title_block(item["content"], label_num)
    elif t == "heading":
        return _make_section(item["content"], item.get("level", 1), [])
    elif t == "image" and item.get("path"):
        img_data = Path(item["path"]).read_bytes()
        return _make_image_block(img_data, label_num)
    else:
        return _make_text_block(
            item.get("content", ""), label_num,
            align=item.get("align", "left")
        )


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
                    section_content.append(_make_block(items[i], label))
                    label += 1
                    i += 1

            blocks.append(_make_section(item["content"], level, section_content))
        else:
            blocks.append(_make_block(item, label))
            label += 1
            i += 1

    return blocks, i, label


def insert_content(file_path: str, items: list[dict]) -> str:
    root = ET.parse(file_path).getroot()
    label = _next_label_num(root)
    blocks, _, _ = _build_nested(items, 0, label)
    return _append_blocks(file_path, blocks)
