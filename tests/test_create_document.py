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
