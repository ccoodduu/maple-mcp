"""Vectors and matrices: <a,b>, <a|b>, Matrix([[..],[..]]), vec(a), a . b, a &x b.

The encoder must emit the SAME markup Maple's palette writes into a 2D-input
block (mtable + msemantics ColVector/RowVector/Matrix inside
maction(rtableaddress); mover + &RightArrow; for the arrow accent) — that is
what the GUI parses back into a Vector when executed. The decoder must turn
that markup, as found in real assignments, into re-parseable Maple syntax.
"""
import base64
import json
from pathlib import Path

import pytest

from maple_mcp.maple_engine import MapleEngine
from maple_mcp.document import _replace_units_in_expr

FIXTURE = Path(__file__).parent / "fixtures" / "vector_blobs.json"


def _norm(s: str) -> str:
    return s.replace(" ", "")


class TestVectorSyntaxPurePython:
    """No kernel needed."""

    @pytest.mark.parametrize("expr,n_ops", [
        ("<1,2>", 0),
        ("<1,2> = <3,4>", 1),
        ("<x,y> = <1,2> + t*<3,4>", 1),
        ("2*<1,2>", 0),
        ("<1,2> . <3,4>", 0),
        ("<1,2,3> &x <4,5,6>", 0),
        ("<<1,2>|<3,4>>", 0),
        ("x < 2", 1),
        ("f(x) < 2", 1),
        ("0 <= x <= 1", 2),
        ("a := <1,2>", 1),
    ])
    def test_angle_brackets_are_not_relations(self, expr, n_ops):
        operands, ops = MapleEngine._split_relations(expr)
        assert len(ops) == n_ops, (operands, ops)

    @pytest.mark.parametrize("expr", [
        "Matrix([[1,2],[3,4]])",
        "M := Matrix([[a,b],[c,d]])",
    ])
    def test_nested_lists_are_not_units(self, expr):
        assert _replace_units_in_expr(expr) == expr

    def test_units_still_replaced(self):
        assert _replace_units_in_expr("3[[(m)/(s^2)]]") == "3*Unit(('m')/('s'^2))"
        assert _replace_units_in_expr("v = 3*[[(m)/(s)]]*<1,0>") == \
            "v = 3*Unit(('m')/('s'))*<1,0>"


@pytest.fixture(scope="module")
def eng(engine):
    return engine


class TestVectorRoundTrip:
    """encode -> decode gives the same Maple syntax back."""

    @pytest.mark.parametrize("expr", [
        "<1,2>", "<1|2>", "<-1.5,2>", "<1,2,3>",
        "a := <1,2>", "vec(a) := <1,2>", "vec(a)", "vec(AB)",
        "vec(a) . vec(b)", "abs(vec(a))", "a . b",
        "<1,2> . <3,4>", "2*<1,2>", "<x,y> = <1,2> + t*<3,4>",
        "<1,2,3> &x <4,5,6>",
        "Matrix([[1,2],[3,4]])", "A := Matrix([[1,2],[3,4]])",
        "Matrix([[1,2],[3,4]]) . <1,2>",
        "vec(a) . vec(b) = abs(vec(a))*abs(vec(b))*cos(v)",
        "<1,2> => evaluate",
        "vec(r)[G] = <1,2>",
        "<<1,2>|<3,4>>",
    ])
    def test_round_trip(self, eng, expr):
        eng._last_encode_error = None
        _, b64 = eng.encode_equation(expr)
        assert b64, f"encode failed: {eng._last_encode_error}"
        assert _norm(eng.decode_equation(b64)) == _norm(expr)

    @pytest.mark.parametrize("expr,marker", [
        ("<1,2>", b"ColVector"),
        ("<1|2>", b"RowVector"),
        ("Matrix([[1,2],[3,4]])", b"Matrix"),
        ("vec(a)", b"&RightArrow;"),
    ])
    def test_palette_markup(self, eng, expr, marker):
        """The blob carries the palette's tags (mtable inside
        maction/rtableaddress, or the accent mover) — not InertForm's inline
        <,> nor a Matrix(...) function call."""
        _, b64 = eng.encode_equation(expr)
        raw = base64.b64decode(b64)
        assert marker in raw
        if marker == b"&RightArrow;":
            assert b"mover" in raw
        else:
            assert b"rtableaddress" in raw and b"mtable" in raw
        assert b"&lang;" not in raw
        assert b"ApplyFunction" not in raw

    def test_assignment_path_applies_fixup(self, eng):
        _, b64 = eng.encode_equation("a := <1,2>")
        assert b"ColVector" in base64.b64decode(b64)

    def test_units_path_applies_fixup(self, eng):
        _, b64 = eng.encode_equation("v = 3*Unit('m'/'s')*<1,0>")
        assert b64
        raw = base64.b64decode(b64)
        assert b"ColVector" in raw and b"Unit" in raw
        assert "[[(m)/(s)]]" in eng.decode_equation(b64)
        assert "<1,0>" in eng.decode_equation(b64)

    def test_relation_arrow_is_not_a_vector_accent(self, eng):
        _, b64 = eng.encode_equation("x^2 - 4 => factor")
        assert _norm(eng.decode_equation(b64)) == _norm("x^2-4 => factor")


class TestRealPaletteBlobs:
    """Blobs Maple's GUI wrote (palette vectors, accent arrows, typed &x / .)."""

    def _cases():
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        return [pytest.param(b["blob"], b["expected"], id=f"{b['source']}:{b['marker']}")
                for b in data["blobs"]]

    @pytest.mark.parametrize("blob,expected", _cases())
    def test_decodes_to_maple_syntax(self, eng, blob, expected):
        assert eng.decode_equation(blob) == expected

    def _output_cases():
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        return [pytest.param(b, id=f"{b['source']}:{i}")
                for i, b in enumerate(data.get("output_blobs", []))]

    @pytest.mark.parametrize("out", _output_cases())
    def test_output_display_decodes(self, eng, out):
        """Maple's OUTPUT of a vector computation (mscrolltable) reads as <a,b>."""
        assert eng.decode_equation(out["display"]) == out["expected"]
        assert "kilobytes used" not in out["expected"]

    @pytest.mark.parametrize("out", _output_cases())
    def test_read_prefers_display_for_outputs(self, eng, out):
        """The element text of an output is the kernel value ('[]' for an
        rtable); read_document must show the typeset display instead."""
        import xml.etree.ElementTree as ET
        from maple_mcp.document import _decode_equation_text
        el = ET.fromstring(
            f'<Equation executable="false" style="2D Output" '
            f'display="{out["display"]}">{out["content"]}</Equation>')
        assert _decode_equation_text(el) == out["expected"]

    @pytest.mark.parametrize("blob,expected", _cases())
    def test_decoded_form_re_encodes(self, eng, blob, expected):
        """What read_document shows must be writable back through the encoder
        (a trailing ':' and units go through the same pre-processing as edits)."""
        expr = _replace_units_in_expr(expected)
        eng._last_encode_error = None
        _, b64 = eng.encode_equation(expr)
        assert b64, f"{expected!r}: {eng._last_encode_error}"
