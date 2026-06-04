"""Edge cases and TS2Str coverage."""
import pytest


class TestTS2StrCoverage:
    """TS2Str should handle various Typesetting structures."""

    @pytest.mark.parametrize("expr,expected_fragment", [
        ("sqrt(x)", "sqrt"),
        ("x^2", "^2"),
        ("x_n", "x"),
        ("(a+b)/(c+d)", "/("),
        ("Int(x, x = 0..1)", "Int("),  # integrals now reconstruct to re-parseable Int(), not the bare glyph
    ])
    def test_typesetting_structures(self, engine, expr, expected_fragment):
        _, b64 = engine.encode_equation(expr)
        assert b64
        decoded = engine.decode_equation(b64)
        assert decoded, f"Decode failed for {expr}"
        assert expected_fragment in decoded, f"Expected '{expected_fragment}' in '{decoded}'"

    def test_nested_fractions(self, engine):
        _, b64 = engine.encode_equation("(a/b)/(c/d)")
        decoded = engine.decode_equation(b64)
        assert decoded
        assert "a" in decoded and "d" in decoded

    def test_subscript_with_brackets(self, engine):
        """V[water] should produce subscript."""
        _, b64 = engine.encode_equation("V[water]")
        decoded = engine.decode_equation(b64)
        assert "V" in decoded
        assert "water" in decoded

    def test_tuple_keeps_both_elements(self, engine):
        """Coordinate pairs must NOT collapse to the first element."""
        _, b64 = engine.encode_equation("(0, 2)")
        decoded = engine.decode_equation(b64)
        assert "0" in decoded and "2" in decoded, f"tuple collapsed: {decoded}"

    def test_paren_around_unit_not_nested_unit(self, engine):
        """(25*[[m/s]])^2 must not re-serialize as a nested [[25*[[..]]]] block."""
        _, b64 = engine.encode_equation("(25*Unit('m'/'s'))^2")
        decoded = engine.decode_equation(b64)
        assert "[[25" not in decoded, f"paren mis-read as unit block: {decoded}"

    @pytest.mark.parametrize("expr", ["with(Units:-Simple):", "f(x) := 3*x^2:"])
    def test_trailing_colon_preserved(self, engine, expr):
        """A trailing ':' (output suppression) must survive encoding."""
        _, b64 = engine.encode_equation(expr)
        decoded = engine.decode_equation(b64)
        assert decoded.rstrip().endswith(":"), f"colon lost: {decoded}"

    @pytest.mark.parametrize("expr,must", [
        ("abs(x)", "abs("),            # was '(x)' — read as a different value
        ("floor(x/2)", "floor("),
        ("ceil(y)", "ceil("),
        ("Sum(k, k = 1 .. n)", "Sum("),       # was '∑k=1nk' (bounds fused)
        ("Product(i, i = 1 .. m)", "Product("),
        ("limit(sin(x)/x, x = 0)", "limit("),
        ("Diff(sin(x), x)", "diff("),         # was '()/(x)sin(x)' (empty numerator)
        ("Diff(x^3, x)", "diff("),
    ])
    def test_decode_fidelity_and_roundtrip(self, engine, expr, must):
        """abs/floor/ceil/sum/product/limit/derivative must decode to the proper
        function (not bare parens / fused bounds / empty numerator) AND the decoded
        form must itself re-encode (re-parseable Maple)."""
        _, b64 = engine.encode_equation(expr)
        assert b64, f"encode failed: {expr}"
        decoded = engine.decode_equation(b64)
        assert must in decoded, f"{expr} decoded as {decoded!r}, expected {must!r}"
        engine._last_encode_error = None
        _, b64b = engine.encode_equation(decoded)
        assert b64b, f"decoded {decoded!r} did not re-encode: {engine._last_encode_error}"


class TestDashAwareMatch:
    """render_pages must match headings containing em/en-dashes even though
    Maple's PDF text layer mangles those glyphs (— -> 'R', – -> 'Q', − -> 'L')."""

    def _page(self, text):
        fitz = pytest.importorskip("pymupdf")
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=12)
        return doc, page

    def test_emdash_needle_matches_mangled_R(self):
        from maple_mcp.maple_render import _match_rects_on_page
        doc, page = self._page("Opgave 4 R Energi og bevaegelse")
        needle = "Opgave 4 — Energi og bevaegelse"
        rects = _match_rects_on_page(page, [needle], needle)
        assert rects, "em-dash heading must match its mangled 'R' text-layer form"
        doc.close()

    def test_endash_and_minus_match(self):
        from maple_mcp.maple_render import _match_rects_on_page
        for mangled, needle in [("en Q dash", "en – dash"),
                                ("Minus 3 L 1", "Minus 3 − 1")]:
            doc, page = self._page(mangled)
            assert _match_rects_on_page(page, [needle], needle), \
                f"{needle!r} should match {mangled!r}"
            doc.close()

    def test_hyphen_needle_tolerates_emdash_doc(self):
        """User types a hyphen where the doc actually has an em-dash -> still hits."""
        from maple_mcp.maple_render import _match_rects_on_page
        doc, page = self._page("Opgave 4 R Energi")
        needle = "Opgave 4 - Energi"
        assert _match_rects_on_page(page, [needle], needle)
        doc.close()

    def test_greek_letter_mangling(self):
        """Greek mangles to Latin (Δ->'D'); fuzzy wildcard must still match."""
        from maple_mcp.maple_render import _match_rects_on_page
        doc, page = self._page("Beregn D for systemet")
        needle = "Beregn Δ for systemet"
        assert _match_rects_on_page(page, [needle], needle)
        doc.close()

    def test_math_operator_mangling(self):
        """± extracts as some arbitrary letter; wildcard matches it."""
        from maple_mcp.maple_render import _match_rects_on_page
        doc, page = self._page("resultat 3 G 4 enheder")   # ± -> 'G' here
        needle = "resultat 3 ± 4 enheder"
        assert _match_rects_on_page(page, [needle], needle)
        doc.close()

    def test_symbol_collapses_to_space(self):
        """Arrows/sqrt can extract as a space; '.' wildcard matches a space too."""
        from maple_mcp.maple_render import _match_rects_on_page
        doc, page = self._page("from f   g here")          # → -> ' '
        needle = "from f → g here"
        assert _match_rects_on_page(page, [needle], needle)
        doc.close()

    def test_danish_text_keeps_specificity(self):
        """æøå extract correctly, so exact search hits without needing fuzzy."""
        from maple_mcp.maple_render import _match_rects_on_page
        doc, page = self._page("Måling af tæthed og bevægelse")
        needle = "Måling af tæthed og bevægelse"
        assert _match_rects_on_page(page, [needle], needle)
        doc.close()

    def test_no_false_match(self):
        from maple_mcp.maple_render import _match_rects_on_page
        doc, page = self._page("totally different line of text")
        needle = "Opgave 4 — Energi"
        assert not _match_rects_on_page(page, [needle], needle)
        doc.close()


class TestEdgeCases:
    def test_empty_document(self, tmp_path):
        """Empty document should return empty list."""
        from maple_mcp.document import read_document
        p = tmp_path / "empty.mw"
        p.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<Worksheet></Worksheet>',
                      encoding="utf-8")
        entries = read_document(str(p))
        assert entries == []

    def test_very_long_equation(self, engine):
        """Long polynomial should encode without error."""
        terms = " + ".join(f"{i}*x^{i}" for i in range(20))
        _, b64 = engine.encode_equation(terms)
        assert b64
        assert len(b64) > 100

    def test_special_characters_in_text(self, tmp_mw):
        """Danish characters in text should survive."""
        from maple_mcp.document import insert_after, read_document
        insert_after(tmp_mw, "First block", [
            {"type": "text", "content": "Beregn \u00e6ndringen i \u00f8jeblikket."},
        ])
        entries = read_document(tmp_mw)
        contents = " ".join(e.get("content", "") for e in entries)
        assert "\u00e6ndringen" in contents or "ndringen" in contents

    def test_backup_created(self, tmp_mw):
        """Edit operations push a backup onto the out-of-tree ring, NOT a .mw.bak."""
        from maple_mcp.document import insert_after
        from maple_mcp import backup
        from pathlib import Path
        insert_after(tmp_mw, "First block", [
            {"type": "text", "content": "trigger backup"},
        ])
        assert backup._ring(tmp_mw), "edit should create a backup in the ring"
        assert not Path(tmp_mw).with_suffix(".mw.bak").exists()

    def test_undo_restores(self, tmp_mw):
        """After an edit, popping the backup ring restores the original."""
        from maple_mcp.document import insert_after, read_document
        from maple_mcp import backup

        original = read_document(tmp_mw)
        insert_after(tmp_mw, "First block", [
            {"type": "text", "content": "New content."},
        ])
        assert backup.pop(tmp_mw), "ring should hold the prior version"
        restored = read_document(tmp_mw)

        original_text = " ".join(e.get("content", "") for e in original)
        restored_text = " ".join(e.get("content", "") for e in restored)
        assert "New content" not in restored_text
        assert original_text == restored_text


class TestMultipleEdits:
    """Multiple sequential edits should not corrupt the document."""

    def test_three_inserts(self, tmp_mw, engine):
        import xml.etree.ElementTree as ET
        from maple_mcp.document import insert_after, read_document

        insert_after(tmp_mw, "First block", [
            {"type": "text", "content": "Insert 1."},
        ])
        insert_after(tmp_mw, "Insert 1", [
            {"type": "text", "content": "Insert 2."},
        ])
        insert_after(tmp_mw, "Insert 2", [
            {"type": "text", "content": "Insert 3."},
        ])

        # XML should still be valid
        ET.parse(tmp_mw)

        entries = read_document(tmp_mw)
        contents = " ".join(e.get("content", "") for e in entries)
        assert "Insert 1" in contents
        assert "Insert 2" in contents
        assert "Insert 3" in contents

    def test_insert_then_delete(self, tmp_mw):
        from maple_mcp.document import insert_after, delete_block, read_document

        insert_after(tmp_mw, "First block", [
            {"type": "text", "content": "Temporary content."},
        ])
        delete_block(tmp_mw, "Temporary content")
        entries = read_document(tmp_mw)
        contents = " ".join(e.get("content", "") for e in entries)
        assert "Temporary" not in contents

    def test_insert_then_replace(self, tmp_mw):
        from maple_mcp.document import insert_after, replace_block, read_document

        insert_after(tmp_mw, "First block", [
            {"type": "text", "content": "Original insert."},
        ])
        replace_block(tmp_mw, "Original insert", [
            {"type": "text", "content": "Replaced insert."},
        ])
        entries = read_document(tmp_mw)
        contents = " ".join(e.get("content", "") for e in entries)
        assert "Replaced insert" in contents
        assert "Original insert" not in contents
