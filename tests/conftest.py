"""Shared fixtures for maple-mcp tests."""
import sys
import pytest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture(scope="session")
def engine():
    """Use the module-level singleton (only one kernel per process)."""
    from maple_mcp.maple_engine import engine as eng
    eng._ensure_ts2str()
    return eng


@pytest.fixture
def tmp_mw(tmp_path):
    """Create a minimal .mw file for testing."""
    from maple_mcp.document import _make_text_block, _make_section

    content = '''<?xml version="1.0" encoding="UTF-8"?>
<Worksheet>
<Section collapsed="false" isCollapsible="true" drawButton="true" MultipleChoiceAnswerIndex="-1" MultipleChoiceRandomizeChoices="false" TrueFalseAnswerIndex="-1" EssayAnswerRows="5" EssayAnswerColumns="60">
<Title><Text-field style="Heading 1" layout="Heading 1">Test Section</Text-field></Title>
<Presentation-Block>
<Group view="presentation" hide-input="false" hide-output="false" inline-output="false" labelreference="L1" drawlabel="true" applyint="true" applyrational="true" applyexponent="false">
<Input><Text-field style="Text" layout="Normal">First block.</Text-field></Input>
</Group></Presentation-Block>
<Presentation-Block>
<Group view="presentation" hide-input="false" hide-output="false" inline-output="false" labelreference="L2" drawlabel="true" applyint="true" applyrational="true" applyexponent="false">
<Input><Text-field style="Text" layout="Normal">Second block.</Text-field></Input>
</Group></Presentation-Block>
</Section>
</Worksheet>'''

    p = tmp_path / "test.mw"
    p.write_text(content, encoding="utf-8")
    return str(p)
