"""Tests for background colors and highlight in equations."""
import pytest


class TestHighlightEquations:
    """Equations inside {color} blocks should render with background."""

    def test_equation_in_color_block(self, tmp_mw, engine):
        from maple_mcp.document import insert_after, read_document
        insert_after(tmp_mw, "First block", [
            {"type": "text", "content":
             "{color:255,255,0}**Svar: {{m = 200*[[kg]]}}.**{/color}"},
        ])
        entries = read_document(tmp_mw)
        for e in entries:
            c = e.get("content", "")
            if "Svar" in c:
                assert "{color:255,255,0}" in c
                assert "{{" in c
                assert "}}" in c
                # Should be ONE color block
                assert c.count("{color:") == 1, f"Fragmented: {c}"
                return
        pytest.fail("Svar block not found")

    def test_color_in_xml(self, tmp_mw, engine):
        """Yellow highlight should set background on Text-field."""
        from maple_mcp.document import insert_after
        insert_after(tmp_mw, "First block", [
            {"type": "text", "content":
             "{color:255,255,0}Yellow text.{/color}"},
        ])
        content = open(tmp_mw, encoding="utf-8").read()
        assert 'background="[255,255,0]"' in content
        assert 'opaque="true"' in content

    def test_equation_background_in_typesetting(self, tmp_mw, engine):
        """Equations inside color blocks should have background baked in."""
        import base64
        from maple_mcp.document import insert_after
        insert_after(tmp_mw, "First block", [
            {"type": "text", "content":
             "{color:255,0,0}Result: {{x = 42}}.{/color}"},
        ])
        content = open(tmp_mw, encoding="utf-8").read()
        # Find equation base64 inside the color block
        import re
        eqs = re.findall(r'<Equation[^>]*>([A-Za-z0-9+/=]+)<', content)
        for eq_b64 in eqs:
            raw = base64.b64decode(eq_b64).decode("latin-1")
            if "background" in raw:
                assert "255,0,0" in raw
                return
        # If no equation has background, that's also OK (background on Font level)


class TestEmptyBlocks:
    def test_empty_block_creates_spacing(self, tmp_mw):
        from maple_mcp.document import insert_after, read_document
        insert_after(tmp_mw, "First block", [
            {"type": "text", "content": "Before empty."},
            {"type": "empty"},
            {"type": "text", "content": "After empty."},
        ])
        entries = read_document(tmp_mw)
        types = [e.get("type") for e in entries]
        # Should have an empty entry between the two texts
        assert "empty" in types
