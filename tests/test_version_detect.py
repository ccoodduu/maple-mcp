"""Tests for Maple installation discovery.

Pinning a year in the source meant every Maple upgrade broke the server at
import time. These pin the selection rules instead — especially "ignore an
install with no binaries", which is not hypothetical: an uninstalled Maple 2024
on the dev box left lib/ and license/ behind, and a naive newest-directory-wins
would happily select it over a working install.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from maple_mcp.maple_engine import (  # noqa: E402
    find_maple_root, maple_version, _has_kernel, _maple_candidates,
)


def _install(parent, name, with_kernel=True, version=None):
    root = parent / name
    (root / "bin.X86_64_WINDOWS").mkdir(parents=True)
    if with_kernel:
        (root / "bin.X86_64_WINDOWS" / "maplec.dll").write_bytes(b"stub")
    if version:
        (root / "license").mkdir(parents=True)
        (root / "license" / "version.txt").write_text(version, encoding="utf-8")
    return root


class TestSelection:
    def test_picks_newest_year(self, tmp_path):
        _install(tmp_path, "Maple 2024")
        _install(tmp_path, "Maple 2025")
        newest = _install(tmp_path, "Maple 2026")
        assert find_maple_root(parents=[str(tmp_path)]) == str(newest)

    def test_skips_install_without_binaries(self, tmp_path):
        # The real 2024 leftover case: newer by name, but not a usable install.
        _install(tmp_path, "Maple 2026", with_kernel=False)
        working = _install(tmp_path, "Maple 2025")
        assert find_maple_root(parents=[str(tmp_path)]) == str(working)

    def test_cmaple_alone_counts_as_an_install(self, tmp_path):
        root = tmp_path / "Maple 2026"
        (root / "bin.X86_64_WINDOWS").mkdir(parents=True)
        (root / "bin.X86_64_WINDOWS" / "cmaple.exe").write_bytes(b"stub")
        assert find_maple_root(parents=[str(tmp_path)]) == str(root)

    def test_minor_version_breaks_the_tie(self, tmp_path):
        _install(tmp_path, "Maple 2026")
        newer = _install(tmp_path, "Maple 2026.2")
        assert find_maple_root(parents=[str(tmp_path)]) == str(newer)

    def test_sibling_products_are_not_maple(self, tmp_path):
        _install(tmp_path, "MapleSim 2026")
        _install(tmp_path, "Maplesoft")
        real = _install(tmp_path, "Maple 2025")
        assert find_maple_root(parents=[str(tmp_path)]) == str(real)


class TestExplicitOverride:
    def test_explicit_wins_over_detection(self, tmp_path):
        _install(tmp_path, "Maple 2026")
        chosen = _install(tmp_path, "Maple 2025")
        assert find_maple_root(explicit=str(chosen), parents=[str(tmp_path)]) == str(chosen)

    def test_explicit_is_not_second_guessed(self, tmp_path):
        # Selecting a non-default install is exactly what MAPLE is for, so a
        # bad value must surface as a real error, not be silently replaced.
        _install(tmp_path, "Maple 2026")
        bogus = str(tmp_path / "nope")
        assert find_maple_root(explicit=bogus, parents=[str(tmp_path)]) == bogus


class TestFallback:
    def test_no_maple_at_all_does_not_crash(self, tmp_path):
        root = find_maple_root(parents=[str(tmp_path)])
        assert isinstance(root, str) and root

    def test_missing_parent_dir_is_ignored(self, tmp_path):
        real = _install(tmp_path, "Maple 2025")
        root = find_maple_root(parents=[str(tmp_path / "does-not-exist"), str(tmp_path)])
        assert root == str(real)

    def test_binariless_install_is_named_over_an_invented_path(self, tmp_path):
        # Better to point the user at a directory that exists than at a guess.
        broken = _install(tmp_path, "Maple 2026", with_kernel=False)
        assert find_maple_root(parents=[str(tmp_path)]) == str(broken)


class TestVersionRead:
    def test_reads_first_line(self, tmp_path):
        root = _install(tmp_path, "Maple 2026", version="Maple 2026.1\nWed Nov 12\n123\n")
        assert maple_version(str(root)) == "Maple 2026.1"

    def test_unknown_when_absent(self, tmp_path):
        root = _install(tmp_path, "Maple 2026")
        assert maple_version(str(root)) == "unknown"

    def test_needs_no_kernel(self, tmp_path):
        # Must work on an expired licence, so it may never start Maple.
        root = _install(tmp_path, "Maple 2026", with_kernel=False, version="Maple 2026.0\n")
        assert maple_version(str(root)) == "Maple 2026.0"


class TestHelpers:
    def test_candidates_sorted_newest_first(self, tmp_path):
        for name in ("Maple 2024", "Maple 2026", "Maple 2025"):
            _install(tmp_path, name)
        years = [key[0] for key, _ in _maple_candidates([str(tmp_path)])]
        assert years == [2026, 2025, 2024]

    def test_has_kernel_rejects_empty_dir(self, tmp_path):
        (tmp_path / "Maple 2026").mkdir()
        assert not _has_kernel(str(tmp_path / "Maple 2026"))


class TestMissingRoot:
    def test_lookup_returns_none_instead_of_raising(self, tmp_path, monkeypatch):
        """A wrong MAPLE must reach the actionable error, not a raw WinError 3.

        os.listdir on a non-existent root used to propagate, which only became
        reachable once the hardcoded (and always-present) 2025 path went away.
        """
        from maple_mcp import maple_engine as me
        monkeypatch.setattr(me, "MAPLE_ROOT", str(tmp_path / "not-a-maple"))
        assert me._find_maplec_dll() is None

    def test_error_names_the_root_and_the_env_var(self, tmp_path, monkeypatch):
        from maple_mcp import maple_engine as me
        monkeypatch.setattr(me, "MAPLE_ROOT", str(tmp_path / "not-a-maple"))
        with pytest.raises(FileNotFoundError) as excinfo:
            me.MapleEngine()._ensure_kernel()
        message = str(excinfo.value)
        assert "not-a-maple" in message and "MAPLE" in message


@pytest.mark.skipif(sys.platform != "win32", reason="real install layout is Windows-only")
class TestRealMachine:
    def test_selects_a_usable_install_when_one_exists(self, monkeypatch):
        monkeypatch.delenv("MAPLE", raising=False)
        from maple_mcp.maple_engine import (
            _maple_candidates, _has_kernel, _INSTALL_PARENTS,
        )
        usable = [p for _, p in _maple_candidates(_INSTALL_PARENTS) if _has_kernel(p)]
        if not usable:
            pytest.skip("no usable Maple installation on this machine")
        detected = find_maple_root(parents=_INSTALL_PARENTS)
        assert detected == usable[0] and _has_kernel(detected)
