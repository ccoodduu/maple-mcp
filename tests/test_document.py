"""Document read/write tests."""
import pytest


class TestReadDocument:
    """read_document should produce consistent output."""

    def test_reads_sections(self, tmp_mw):
        from maple_mcp.document import read_document
        entries = read_document(tmp_mw)
        sections = [e for e in entries if e.get("type") == "section"]
        assert len(sections) == 1
        assert "Test Section" in sections[0]["content"]

    def test_reads_text_blocks(self, tmp_mw):
        from maple_mcp.document import read_document
        entries = read_document(tmp_mw)
        texts = [e for e in entries if e.get("type") == "text"]
        assert any("First block" in t["content"] for t in texts)
        assert any("Second block" in t["content"] for t in texts)


class TestInsertAfter:
    """insert_after should write valid XML and return readback."""

    def test_insert_text(self, tmp_mw):
        from maple_mcp.document import insert_after, read_document
        readback = insert_after(tmp_mw, "First block", [
            {"type": "text", "content": "Inserted text."},
        ])
        assert "Inserted text" in readback

        entries = read_document(tmp_mw)
        contents = [e.get("content", "") for e in entries]
        assert any("Inserted text" in c for c in contents)

    def test_insert_heading(self, tmp_mw):
        from maple_mcp.document import insert_after, read_document
        insert_after(tmp_mw, "Second block", [
            {"type": "heading", "content": "a)", "level": 2},
            {"type": "text", "content": "Sub content."},
        ])
        entries = read_document(tmp_mw)
        sections = [e for e in entries if e.get("type") == "section"]
        assert any("a)" in s["content"] for s in sections)

    def test_insert_with_equation(self, tmp_mw, engine):
        from maple_mcp.document import insert_after, read_document
        insert_after(tmp_mw, "First block", [
            {"type": "text", "content": "Result: {{x^2 + 1}}."},
        ])
        entries = read_document(tmp_mw)
        contents = " ".join(e.get("content", "") for e in entries)
        assert "x^2" in contents
        assert "{{" in contents  # equation preserved

    def test_insert_with_units(self, tmp_mw, engine):
        from maple_mcp.document import insert_after, read_document
        insert_after(tmp_mw, "First block", [
            {"type": "text", "content": "Mass: {{200*[[kg]]}}."},
        ])
        entries = read_document(tmp_mw)
        contents = " ".join(e.get("content", "") for e in entries)
        assert "[[kg]]" in contents, f"Unit lost in round-trip: {contents}"


class TestFormatRoundTrip:
    """Write markup → read back should match."""

    @pytest.mark.parametrize("markup,expected", [
        ("**bold text**", "**bold text**"),
        ("*italic text*", "*italic text*"),
        ("__underlined__", "__underlined__"),
        ("{color:255,255,0}yellow text{/color}", "{color:255,255,0}"),
        ("{color:255,255,0}**bold yellow**{/color}", "**bold yellow**"),
    ])
    def test_formatting_preserved(self, tmp_mw, markup, expected):
        from maple_mcp.document import insert_after, read_document
        insert_after(tmp_mw, "First block", [
            {"type": "text", "content": markup},
        ])
        entries = read_document(tmp_mw)
        contents = " ".join(e.get("content", "") for e in entries)
        assert expected in contents, f"Expected '{expected}' in: {contents}"

    def test_color_not_fragmented(self, tmp_mw, engine):
        """Color blocks with equations should be ONE block, not fragmented."""
        from maple_mcp.document import insert_after, read_document
        insert_after(tmp_mw, "First block", [
            {"type": "text", "content":
             "{color:255,255,0}**Svar: {{m = 200}} kg.**{/color}"},
        ])
        entries = read_document(tmp_mw)
        for e in entries:
            c = e.get("content", "")
            if "Svar" in c:
                # Should be ONE color block, not multiple
                count = c.count("{color:")
                assert count == 1, f"Fragmented color: {c}"
                break
        else:
            pytest.fail("Svar block not found")

    def test_nested_color_flattened(self, tmp_mw, engine):
        """Nested same-color blocks should be flattened."""
        from maple_mcp.document import insert_after, read_document
        insert_after(tmp_mw, "First block", [
            {"type": "text", "content":
             "{color:255,255,0}text {color:255,255,0}inner{/color} more{/color}"},
        ])
        entries = read_document(tmp_mw)
        for e in entries:
            c = e.get("content", "")
            if "inner" in c:
                count = c.count("{color:")
                assert count == 1, f"Nested color not flattened: {c}"
                break


class TestXMLValidity:
    """Written files must be valid XML (Maple crashes on invalid XML)."""

    def test_insert_produces_valid_xml(self, tmp_mw, engine):
        import xml.etree.ElementTree as ET
        from maple_mcp.document import insert_after
        insert_after(tmp_mw, "First block", [
            {"type": "heading", "content": "a)", "level": 2},
            {"type": "text", "content": "**Bold** with {{m = 200*[[kg]]}}."},
            {"type": "code", "content": "m = 1000*0.2"},
            {"type": "text", "content":
             "{color:255,255,0}**Svar: {{m = 200*[[kg]]}}.**{/color}"},
            {"type": "empty"},
        ])
        # Must not throw
        tree = ET.parse(tmp_mw)
        assert tree.getroot().tag == "Worksheet"

    def test_section_has_required_attributes(self, tmp_mw):
        from maple_mcp.document import insert_after
        insert_after(tmp_mw, "First block", [
            {"type": "heading", "content": "test", "level": 2},
        ])
        content = open(tmp_mw, encoding="utf-8").read()
        assert 'drawButton="true"' in content
        assert 'MultipleChoiceAnswerIndex="-1"' in content
