"""Maple's empty math regions read back as empty lines, not as unreadable.

Maple puts one in every new Document-mode file as the cursor's region, so a
document from create_document started with a block read_document reported as
"[unreadable equation]". It decodes to "[]" like a structure TS2Str cannot read,
so the check has to look at the Typesetting tree — and must stay strict, since
a real equation shown as empty would be one the model could delete unseen.
"""
import json
from pathlib import Path

import pytest

BLOBS = json.loads(
    (Path(__file__).parent / "fixtures" / "blank_math_blobs.json").read_text(encoding="utf-8")
)["blobs"]
BY_NAME = {b["name"]: b["blob"] for b in BLOBS}


def _block(inner: str, label: int) -> str:
    return (
        '<Presentation-Block><Group view="presentation" inline-output="false" '
        f'labelreference="L{label}" drawlabel="true"><Input>'
        f'<Text-field style="Text" layout="Normal">{inner}</Text-field>'
        '</Input></Group></Presentation-Block>'
    )


def _math(blob: str) -> str:
    return (f'<Equation executable="true" style="2D Math" input-equation="" '
            f'display="{blob}">{blob}</Equation>')


def _mw(tmp_path, *blocks: str) -> str:
    target = tmp_path / "blank.mw"
    target.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<Worksheet>'
        '<Version major="2026" minor="1"/>'
        '<View-Properties presentation="true"/>'
        f'{"".join(blocks)}</Worksheet>',
        encoding="utf-8")
    return str(target)


@pytest.mark.parametrize("blob", BLOBS, ids=[b["name"] for b in BLOBS])
def test_blank_check_matches_fixture(engine, blob):
    from maple_mcp.document import _is_blank_math
    assert _is_blank_math(blob["blob"]) is blob["blank"]


def test_new_document_placeholder_reads_as_empty(engine, tmp_path):
    from maple_mcp.document import read_document
    path = _mw(tmp_path, _block(_math(BY_NAME["new_document_placeholder"]), 1))
    assert read_document(path) == []


def test_placeholder_before_content_is_an_empty_line(engine, tmp_path):
    from maple_mcp.document import read_document
    path = _mw(tmp_path,
               _block(_math(BY_NAME["new_document_placeholder"]), 1),
               _block("Opgave 1", 2))
    entries = read_document(path)
    assert [e["type"] for e in entries] == ["empty", "text"]
    assert entries[1]["content"] == "Opgave 1"
    assert "unreadable" not in json.dumps(entries)


def test_blank_math_beside_text_adds_nothing(engine, tmp_path):
    from maple_mcp.document import read_document
    path = _mw(tmp_path, _block("Se her " + _math(BY_NAME["empty_mi"]), 1))
    assert read_document(path)[0]["content"] == "Se her"


def test_real_equation_still_reads(engine, tmp_path):
    from maple_mcp.document import read_document
    path = _mw(tmp_path, _block(_math(BY_NAME["pi"]), 1))
    assert read_document(path)[0]["content"] == "{!Pi!}"
