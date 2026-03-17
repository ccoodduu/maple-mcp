"""Tests for type: "code" executable equation blocks."""
import pytest


class TestCodeBlockEncoding:
    """Code blocks should create executable 2D Math equations."""

    @pytest.mark.parametrize("code_content", [
        "m = 1000*200/1000",
        "Q = 200*4180*(60-15)",
        "t = 37620000/2000",
        "solve(x^2-5*x+6, x)",
        "Int(x^2, x = 0..3)",
    ])
    def test_code_block_encodes(self, tmp_mw, engine, code_content):
        from maple_mcp.document import insert_after, read_document
        insert_after(tmp_mw, "First block", [
            {"type": "code", "content": code_content},
        ])
        entries = read_document(tmp_mw)
        # Code blocks read back as {!expr!}
        contents = " ".join(e.get("content", "") for e in entries)
        assert "{!" in contents, f"Code block not found in: {contents}"

    def test_code_block_with_units(self, tmp_mw, engine):
        from maple_mcp.document import insert_after, read_document
        insert_after(tmp_mw, "First block", [
            {"type": "code", "content": "m = 1000*[[kg/m^3]]*0.2*[[m^3]]"},
        ])
        entries = read_document(tmp_mw)
        contents = " ".join(e.get("content", "") for e in entries)
        assert "{!" in contents
        assert "[[" in contents, f"Units lost in code block: {contents}"

    def test_code_block_assignment_display(self, tmp_mw, engine):
        """:= should display as = (not strip variable name)."""
        from maple_mcp.document import insert_after, read_document
        insert_after(tmp_mw, "First block", [
            {"type": "code", "content": "m := 200"},
        ])
        entries = read_document(tmp_mw)
        contents = " ".join(e.get("content", "") for e in entries)
        assert "m" in contents, f"Variable lost in := assignment: {contents}"

    def test_code_block_fraction(self, tmp_mw, engine):
        from maple_mcp.document import insert_after, read_document
        insert_after(tmp_mw, "First block", [
            {"type": "code", "content": "(37620000)/(2000)"},
        ])
        entries = read_document(tmp_mw)
        contents = " ".join(e.get("content", "") for e in entries)
        assert "37620000" in contents
        assert "2000" in contents

    def test_code_block_is_executable(self, tmp_mw, engine):
        """Code blocks should have executable='true' in XML."""
        from maple_mcp.document import insert_after
        insert_after(tmp_mw, "First block", [
            {"type": "code", "content": "1+1"},
        ])
        content = open(tmp_mw, encoding="utf-8").read()
        # Find the equation for 1+1
        assert 'executable="true"' in content
