"""create_document: a new .mw must be one Maple actually accepts.

The whole point of generating the file through DocumentTools:-Layout instead of
a hand-written template is that Maple authors it. So the tests that matter are
the ones that check the file is well-formed, carries the INSTALLED version, and
— in the integration test — can be parsed back by Maple's own loader.
"""
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


class TestGuards:
    """Refusals happen before anything is written."""

    def test_refuses_non_mw_suffix(self, tmp_path):
        from maple_mcp.document import create_document
        target = tmp_path / "notes.txt"
        with pytest.raises(ValueError, match="Not a .mw path"):
            create_document(str(target))
        assert not target.exists()

    def test_refuses_to_overwrite_existing(self, tmp_path):
        from maple_mcp.document import create_document
        target = tmp_path / "taken.mw"
        target.write_text("ORIGINAL", encoding="utf-8")
        with pytest.raises(ValueError, match="already exists"):
            create_document(str(target))
        # The refusal must not have touched the file.
        assert target.read_text(encoding="utf-8") == "ORIGINAL"

    def test_refuses_missing_directory(self, tmp_path):
        from maple_mcp.document import create_document
        with pytest.raises(ValueError, match="Directory does not exist"):
            create_document(str(tmp_path / "nope" / "doc.mw"))


class TestGeneratedDocument:
    """Needs the kernel: Maple generates the XML."""

    def test_creates_wellformed_worksheet(self, engine, tmp_path):
        from maple_mcp.document import create_document
        target = tmp_path / "fresh.mw"
        created = create_document(str(target))

        assert target.exists()
        assert created == str(target)

        root = ET.parse(target).getroot()
        assert root.tag == "Worksheet"
        assert root.find("Version") is not None

    def test_version_matches_installed_maple(self, engine, tmp_path):
        """A document stamped with the wrong year is the exact failure a
        hand-written template would produce after an upgrade."""
        import re
        from maple_mcp.document import create_document
        from maple_mcp.maple_engine import maple_version

        target = tmp_path / "versioned.mw"
        create_document(str(target))

        installed = re.search(r"(\d{4})", maple_version()).group(1)
        version = ET.parse(target).getroot().find("Version")
        assert version.get("major") == installed

    def test_document_is_empty(self, engine, tmp_path):
        """'Empty' means empty — no stray groups the user has to delete."""
        from maple_mcp.document import create_document
        target = tmp_path / "empty.mw"
        create_document(str(target))

        root = ET.parse(target).getroot()
        assert root.findall("Group") == []
        assert root.findall(".//Equation") == []

    def test_is_document_mode(self, engine, tmp_path):
        """Without these flags Maple opens the file as a worksheet, and every
        region it creates later is a '>' prompt."""
        from maple_mcp.document import create_document
        target = tmp_path / "docmode.mw"
        create_document(str(target))

        root = ET.parse(target).getroot()
        assert root.find("View-Properties").get("presentation") == "true"
        assert root.find("MapleNet-Properties").get("format") == "document"
        text = target.read_text(encoding="utf-8")
        assert "worksheet'" not in text and 'worksheet"' not in text
        assert "presentation='false'" not in text and 'presentation="false"' not in text

    def test_written_document_raises_no_mode_warning(self, engine, tmp_path):
        from maple_mcp.document import (create_document, insert_content,
                                        worksheet_mode_warning)
        target = tmp_path / "nowarn.mw"
        create_document(str(target))
        insert_content(str(target), [{"type": "text", "content": "Hej"}])
        assert worksheet_mode_warning(str(target)) is None

    def test_declares_utf8(self, engine, tmp_path):
        from maple_mcp.document import create_document
        target = tmp_path / "enc.mw"
        create_document(str(target))
        assert target.read_text(encoding="utf-8").startswith(
            '<?xml version="1.0" encoding="UTF-8"?>'
        )

    def test_is_readable_by_read_document(self, engine, tmp_path):
        """A new document must be immediately usable by the read path, not just
        parseable as XML."""
        from maple_mcp.document import create_document, read_document
        target = tmp_path / "readable.mw"
        create_document(str(target))
        read_document(str(target))  # must not raise

    def test_maple_can_open_the_generated_file(self, engine, tmp_path):
        """The claim the whole feature rests on: Maple accepts what we wrote.

        Exercised through the PDF export path, which parses the .mw from disk
        with the same loader as File > Open — so a file Maple would refuse fails
        here rather than in the user's hands. Skipped without a desktop session,
        since the export formatter needs a screen device.
        """
        from maple_mcp.document import create_document
        from maple_mcp.maple_render import export_pdf

        target = tmp_path / "openable.mw"
        create_document(str(target))

        try:
            pdf = export_pdf(str(target), timeout=120)
        except RuntimeError as e:
            if "desktop" in str(e).lower() or "headless" in str(e).lower():
                pytest.skip(f"needs a desktop session: {e}")
            raise
        assert Path(pdf).is_file() and Path(pdf).stat().st_size > 0

    def test_accepts_content_after_creation(self, engine, tmp_path):
        """The point of creating a document is writing to it."""
        from maple_mcp.document import create_document, insert_content
        target = tmp_path / "writable.mw"
        create_document(str(target))

        insert_content(str(target), [{"type": "text", "content": "Hello from the test"}])
        assert "Hello from the test" in target.read_text(encoding="utf-8")


DOC_BLOCK = (
    '<Presentation-Block><Group view="presentation" labelreference="L1">'
    '<Input><Text-field style="Text" layout="Normal">Hej</Text-field></Input>'
    '</Group></Presentation-Block>'
)
EMPTY_PROMPT = (
    '<Group labelreference="L2" drawlabel="true"><Input>'
    '<Text-field prompt="&gt; " style="Maple Input" layout="Normal">'
    '<Equation executable="true" style="2D Input" input-equation="" display="QQ==">QQ==</Equation>'
    '</Text-field></Input></Group>'
)
RUN_PROMPT = (
    '<Group labelreference="L3"><Input>'
    '<Text-field prompt="&gt; " style="Maple Input" layout="Normal">'
    '<Equation executable="true" style="2D Input" input-equation="x := 1" display="QQ==">QQ==</Equation>'
    '</Text-field></Input>'
    '<Output><Text-field style="2D Output" layout="Normal"/></Output></Group>'
)


def _mw(tmp_path, header: str, body: str):
    target = tmp_path / "mode.mw"
    target.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Worksheet><Version major="2026" minor="1"/>{header}{body}</Worksheet>',
        encoding="utf-8")
    return str(target)


class TestWorksheetModeWarning:
    """The file's mode decides what kind of region Maple creates next."""

    DOC = ('<View-Properties presentation="true"/>'
           '<MapleNet-Properties format="document"/>')
    SHEET = ('<View-Properties presentation="false"/>'
             '<MapleNet-Properties format="worksheet"/>')

    def test_document_mode_is_silent(self, tmp_path):
        from maple_mcp.document import worksheet_mode_warning
        assert worksheet_mode_warning(_mw(tmp_path, self.DOC, DOC_BLOCK)) is None

    def test_single_quoted_header_is_read(self, tmp_path):
        """XMLTools:-PrintToString quotes with ', so a file create_document
        wrote and Maple has not yet re-saved looks like this."""
        from maple_mcp.document import worksheet_mode_warning
        header = ("<View-Properties presentation='true'/>"
                  "<MapleNet-Properties format='document'/>")
        assert worksheet_mode_warning(_mw(tmp_path, header, DOC_BLOCK)) is None

    def test_pure_worksheet_is_silent(self, tmp_path):
        """A real worksheet is not a mistake to warn about."""
        from maple_mcp.document import worksheet_mode_warning
        assert worksheet_mode_warning(_mw(tmp_path, self.SHEET, RUN_PROMPT)) is None

    def test_document_blocks_in_worksheet_warn(self, tmp_path):
        from maple_mcp.document import worksheet_mode_warning
        body = DOC_BLOCK + f'<Section><Title/>{DOC_BLOCK}{EMPTY_PROMPT}</Section>' + RUN_PROMPT
        warning = worksheet_mode_warning(_mw(tmp_path, self.SHEET, body))
        assert warning is not None
        assert 'presentation="false"' in warning and 'format="worksheet"' in warning
        assert "2 execution group(s)" in warning
        assert "1 of them empty prompts" in warning

    def test_format_worksheet_alone_warns(self, tmp_path):
        from maple_mcp.document import worksheet_mode_warning
        header = ('<View-Properties presentation="true"/>'
                  '<MapleNet-Properties format="worksheet"/>')
        assert worksheet_mode_warning(_mw(tmp_path, header, DOC_BLOCK)) is not None

    def test_missing_header_warns(self, tmp_path):
        """What create_document wrote before it set the header: Maple opened
        these as worksheets."""
        from maple_mcp.document import worksheet_mode_warning
        warning = worksheet_mode_warning(_mw(tmp_path, "", DOC_BLOCK))
        assert warning is not None and "no View-Properties" in warning

    def test_warning_does_not_touch_the_file(self, tmp_path):
        from maple_mcp.document import worksheet_mode_warning
        path = _mw(tmp_path, self.SHEET, DOC_BLOCK + EMPTY_PROMPT)
        before = Path(path).read_bytes()
        worksheet_mode_warning(path)
        assert Path(path).read_bytes() == before
