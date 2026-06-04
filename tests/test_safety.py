"""Safety foundation: whole-document validation before write + out-of-tree backup ring.

These tests are kernel-free (text-only edits), so they run without Maple installed.
"""
import xml.etree.ElementTree as ET
from pathlib import Path
import pytest


class TestBackupRing:
    def test_backup_goes_outside_workdir(self, tmp_mw):
        from maple_mcp.document import insert_after
        from maple_mcp import backup
        insert_after(tmp_mw, "First block", [{"type": "text", "content": "A."}])
        workdir = Path(tmp_mw).parent
        # No .bak clutter next to the document (the whole point of the change)
        assert not list(workdir.glob("*.bak"))
        assert not Path(tmp_mw).with_suffix(".mw.bak").exists()
        # Backup landed in the out-of-tree ring
        assert backup._ring(tmp_mw), "expected a backup in the ring"

    def test_multilevel_undo(self, tmp_mw):
        from maple_mcp.document import insert_after, read_document
        from maple_mcp import backup

        def text():
            return " ".join(str(e.get("content", "")) for e in read_document(tmp_mw))

        insert_after(tmp_mw, "First block", [{"type": "text", "content": "EDIT ONE"}])
        insert_after(tmp_mw, "EDIT ONE", [{"type": "text", "content": "EDIT TWO"}])
        assert "EDIT ONE" in text() and "EDIT TWO" in text()

        assert backup.pop(tmp_mw)                       # undo edit two
        assert "EDIT TWO" not in text() and "EDIT ONE" in text()
        assert backup.pop(tmp_mw)                       # undo edit one
        assert "EDIT ONE" not in text()

    def test_ring_pruned_to_size(self, tmp_mw):
        from maple_mcp import backup
        for _ in range(backup.RING_SIZE + 5):
            backup.push(tmp_mw)
        assert len(backup._ring(tmp_mw)) == backup.RING_SIZE

    def test_pop_empty_returns_none(self, tmp_mw):
        from maple_mcp import backup
        assert backup.pop(tmp_mw) is None


class TestValidateBeforeWrite:
    def test_malformed_splice_rejected_and_file_untouched(self, tmp_mw):
        from maple_mcp import document, backup
        before = Path(tmp_mw).read_text(encoding="utf-8")
        bkp = backup.push(tmp_mw)
        with pytest.raises(ValueError, match="well-formed"):
            document._commit(tmp_mw, "<Worksheet><unclosed></Worksheet>", bkp)
        assert Path(tmp_mw).read_text(encoding="utf-8") == before   # untouched
        assert not Path(bkp).exists()                                # phantom backup discarded

    def test_unescaped_ampersand_rejected(self, tmp_mw):
        from maple_mcp import document
        before = Path(tmp_mw).read_text(encoding="utf-8")
        bad = before.replace(
            "</Worksheet>",
            "<Presentation-Block>raw A & B</Presentation-Block></Worksheet>")
        with pytest.raises(ValueError):
            document._commit(tmp_mw, bad)
        assert Path(tmp_mw).read_text(encoding="utf-8") == before

    def test_valid_content_written(self, tmp_mw):
        from maple_mcp import document
        good = Path(tmp_mw).read_text(encoding="utf-8")
        document._commit(tmp_mw, good)   # must not raise
        assert Path(tmp_mw).read_text(encoding="utf-8") == good

    def test_real_edit_stays_parseable(self, tmp_mw):
        from maple_mcp.document import insert_after
        insert_after(tmp_mw, "First block",
                     [{"type": "text", "content": "Ny tekst med æøå."}])
        ET.parse(tmp_mw)   # the whole document must still parse
