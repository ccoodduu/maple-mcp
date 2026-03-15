import xml.etree.ElementTree as ET
from pathlib import Path


WORKSHEET_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<Worksheet xmlns="http://www.maplesoft.com/2007/Maple" version="2025">
<MapleNet version="16">
</MapleNet>
</Worksheet>"""

NS = {"mw": "http://www.maplesoft.com/2007/Maple"}


def _register_namespaces():
    ET.register_namespace("", "http://www.maplesoft.com/2007/Maple")


def _make_group(statement: str) -> ET.Element:
    group = ET.Element("Group")
    inp = ET.SubElement(group, "Input")
    tf = ET.SubElement(inp, "Text-field", attrib={
        "prompt": "> ",
        "style": "Maple Input",
    })
    tf.text = statement
    return group


def read_worksheet(file_path: str) -> list[dict]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    tree = ET.parse(path)
    root = tree.getroot()

    groups = []
    for group in root.iter("{http://www.maplesoft.com/2007/Maple}Group"):
        entry = {"inputs": [], "outputs": []}

        for tf in group.iter("{http://www.maplesoft.com/2007/Maple}Text-field"):
            style = tf.get("style", "")
            if "Maple Input" in style or "2D Input" in style:
                text = (tf.text or "").strip()
                if text:
                    entry["inputs"].append(text)

        for eq in group.iter("{http://www.maplesoft.com/2007/Maple}Equation"):
            ie = eq.get("input-equation", "")
            if ie:
                entry["outputs"].append(ie)

        for tf in group.iter("{http://www.maplesoft.com/2007/Maple}Text-field"):
            style = tf.get("style", "")
            if "Maple Output" in style or "2D Output" in style:
                text = (tf.text or "").strip()
                if text:
                    entry["outputs"].append(text)

        if entry["inputs"] or entry["outputs"]:
            groups.append(entry)

    if not groups:
        for tf in root.iter("{http://www.maplesoft.com/2007/Maple}Text-field"):
            style = tf.get("style", "")
            if "Maple Input" in style:
                text = (tf.text or "").strip()
                if text:
                    groups.append({"inputs": [text], "outputs": []})

    return groups


def get_inputs(file_path: str) -> list[str]:
    groups = read_worksheet(file_path)
    inputs = []
    for g in groups:
        inputs.extend(g["inputs"])
    return inputs


def create_worksheet(file_path: str, statements: list[str]) -> str:
    _register_namespaces()
    root = ET.fromstring(WORKSHEET_TEMPLATE)
    maple_net = root.find("{http://www.maplesoft.com/2007/Maple}MapleNet")

    for stmt in statements:
        group = _make_group(stmt)
        maple_net.append(group)

    tree = ET.ElementTree(root)
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(str(path), encoding="UTF-8", xml_declaration=True)
    return str(path)


def add_to_worksheet(file_path: str, statements: list[str]) -> str:
    _register_namespaces()
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    tree = ET.parse(path)
    root = tree.getroot()

    maple_net = root.find("{http://www.maplesoft.com/2007/Maple}MapleNet")
    if maple_net is None:
        maple_net = root

    for stmt in statements:
        group = _make_group(stmt)
        maple_net.append(group)

    ET.indent(tree, space="  ")
    tree.write(str(path), encoding="UTF-8", xml_declaration=True)
    return str(path)
