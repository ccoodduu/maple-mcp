"""Tests for block matching, replace, delete, and content operations."""
import pytest


@pytest.fixture
def multi_mw(tmp_path):
    """Document with multiple sections and blocks for matching tests."""
    content = '''<?xml version="1.0" encoding="UTF-8"?>
<Worksheet>
<Section collapsed="false" isCollapsible="true" drawButton="true" MultipleChoiceAnswerIndex="-1" MultipleChoiceRandomizeChoices="false" TrueFalseAnswerIndex="-1" EssayAnswerRows="5" EssayAnswerColumns="60">
<Title><Text-field style="Heading 1" layout="Heading 1">Opgave 1</Text-field></Title>
<Presentation-Block>
<Group view="presentation" hide-input="false" hide-output="false" inline-output="false" labelreference="L1" drawlabel="true" applyint="true" applyrational="true" applyexponent="false">
<Input><Text-field style="Text" layout="Normal">a) First problem statement.</Text-field></Input>
</Group></Presentation-Block>
<Presentation-Block>
<Group view="presentation" hide-input="false" hide-output="false" inline-output="false" labelreference="L2" drawlabel="true" applyint="true" applyrational="true" applyexponent="false">
<Input><Text-field style="Text" layout="Normal">b) Second problem statement.</Text-field></Input>
</Group></Presentation-Block>
<Presentation-Block>
<Group view="presentation" hide-input="false" hide-output="false" inline-output="false" labelreference="L3" drawlabel="true" applyint="true" applyrational="true" applyexponent="false">
<Input><Text-field style="Text" layout="Normal">Repeated text here.</Text-field></Input>
</Group></Presentation-Block>
</Section>
<Section collapsed="false" isCollapsible="true" drawButton="true" MultipleChoiceAnswerIndex="-1" MultipleChoiceRandomizeChoices="false" TrueFalseAnswerIndex="-1" EssayAnswerRows="5" EssayAnswerColumns="60">
<Title><Text-field style="Heading 1" layout="Heading 1">Opgave 2</Text-field></Title>
<Presentation-Block>
<Group view="presentation" hide-input="false" hide-output="false" inline-output="false" labelreference="L4" drawlabel="true" applyint="true" applyrational="true" applyexponent="false">
<Input><Text-field style="Text" layout="Normal">Repeated text here.</Text-field></Input>
</Group></Presentation-Block>
<Presentation-Block>
<Group view="presentation" hide-input="false" hide-output="false" inline-output="false" labelreference="L5" drawlabel="true" applyint="true" applyrational="true" applyexponent="false">
<Input><Text-field style="Text" layout="Normal">Unique block in section 2.</Text-field></Input>
</Group></Presentation-Block>
</Section>
</Worksheet>'''
    p = tmp_path / "multi.mw"
    p.write_text(content, encoding="utf-8")
    return str(p)


class TestReplaceBlock:
    def test_replace_text(self, multi_mw):
        from maple_mcp.document import replace_block, read_document
        readback = replace_block(multi_mw, "First problem statement", [
            {"type": "text", "content": "Replaced content."},
        ])
        assert "Replaced content" in readback
        entries = read_document(multi_mw)
        contents = " ".join(e.get("content", "") for e in entries)
        assert "Replaced content" in contents
        assert "First problem" not in contents

    def test_replace_refuses_section_with_children(self, multi_mw):
        from maple_mcp.document import replace_block
        with pytest.raises(ValueError, match="SECTION"):
            replace_block(multi_mw, "# Opgave 1", [
                {"type": "text", "content": "Bad replace."},
            ])

    def test_replace_preserves_xml_validity(self, multi_mw, engine):
        import xml.etree.ElementTree as ET
        from maple_mcp.document import replace_block
        replace_block(multi_mw, "First problem statement", [
            {"type": "text", "content": "New **bold** with {{m = 200}}."},
        ])
        tree = ET.parse(multi_mw)
        assert tree.getroot().tag == "Worksheet"


class TestDeleteBlock:
    def test_delete_text_block(self, multi_mw):
        from maple_mcp.document import delete_block, read_document
        delete_block(multi_mw, "First problem statement")
        entries = read_document(multi_mw)
        contents = " ".join(e.get("content", "") for e in entries)
        assert "First problem" not in contents
        assert "Second problem" in contents

    def test_delete_refuses_section(self, multi_mw):
        from maple_mcp.document import delete_block
        with pytest.raises(ValueError, match="SECTION"):
            delete_block(multi_mw, "# Opgave 1")

    def test_delete_section_with_flag(self, multi_mw):
        from maple_mcp.document import delete_block, read_document
        delete_block(multi_mw, "# Opgave 2", delete_section=True)
        entries = read_document(multi_mw)
        contents = " ".join(e.get("content", "") for e in entries)
        assert "Opgave 2" not in contents
        assert "Opgave 1" in contents


class TestMatchLogic:
    def test_ambiguous_match_raises(self, multi_mw):
        from maple_mcp.document import insert_after
        with pytest.raises(ValueError, match="Ambiguous"):
            insert_after(multi_mw, "Repeated text here", [
                {"type": "text", "content": "test"},
            ])

    def test_occurrence_disambiguates(self, multi_mw):
        from maple_mcp.document import insert_after
        readback = insert_after(multi_mw, "Repeated text here", [
            {"type": "text", "content": "After first repeat."},
        ], occurrence=1)
        assert "After first repeat" in readback

    def test_section_scoping(self, multi_mw):
        from maple_mcp.document import insert_after
        readback = insert_after(multi_mw, "Repeated text here", [
            {"type": "text", "content": "Scoped insert."},
        ], section="# Opgave 2")
        assert "Scoped insert" in readback

    def test_no_match_raises(self, multi_mw):
        from maple_mcp.document import insert_after
        with pytest.raises(ValueError, match="No block found"):
            insert_after(multi_mw, "nonexistent text that is long enough", [
                {"type": "text", "content": "test"},
            ])

    def test_heading_level_validation(self, multi_mw):
        """Inserting level 2 heading at depth 0 should fail."""
        from maple_mcp.document import insert_after
        with pytest.raises(ValueError, match="level mismatch"):
            insert_after(multi_mw, "# Opgave 1", [
                {"type": "heading", "content": "bad", "level": 2},
            ])


class TestInsertBefore:
    def test_insert_before_block(self, multi_mw):
        from maple_mcp.document import insert_before, read_document
        insert_before(multi_mw, "Second problem statement", [
            {"type": "text", "content": "Before second."},
        ])
        entries = read_document(multi_mw)
        texts = [e.get("content", "") for e in entries if e.get("type") == "text"]
        # Find positions
        before_idx = next(i for i, t in enumerate(texts) if "Before second" in t)
        second_idx = next(i for i, t in enumerate(texts) if "Second problem" in t)
        assert before_idx < second_idx


class TestAppendContent:
    def test_append_at_end(self, multi_mw):
        from maple_mcp.document import insert_content, read_document
        insert_content(multi_mw, [
            {"type": "heading", "content": "Opgave 3", "level": 1},
            {"type": "text", "content": "New section content."},
        ])
        entries = read_document(multi_mw)
        contents = " ".join(e.get("content", "") for e in entries)
        assert "Opgave 3" in contents
        assert "New section content" in contents


class TestReadbackFormat:
    """Readback from edit tools should match read_document format."""

    def test_readback_matches_read(self, multi_mw, engine):
        from maple_mcp.document import insert_after, read_document
        readback = insert_after(multi_mw, "First problem statement", [
            {"type": "text", "content": "Test readback."},
        ])
        entries = read_document(multi_mw)
        # The readback text should appear in read_document output
        assert "Test readback" in readback
        contents = " ".join(e.get("content", "") for e in entries)
        assert "Test readback" in contents

    def test_readback_shows_equations(self, multi_mw, engine):
        from maple_mcp.document import insert_after
        readback = insert_after(multi_mw, "First problem statement", [
            {"type": "text", "content": "Equation: {{x^2 + 1}}."},
        ])
        assert "{{" in readback
        assert "x" in readback
