"""Tests for the golden-baseline comparator.

The comparator is what a Maple port will be judged on, and it cannot be
validated against real kernel output on an unlicensed box — so its
classification logic is pinned here with synthetic results instead.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import baseline  # noqa: E402


class TestReverseDiff:
    """Bucket moves: down the BUCKETS list is worse, up is better."""

    @pytest.mark.parametrize("was,now", [
        ("BYTE_IDENTICAL", "RENDER_STABLE"),
        ("BYTE_IDENTICAL", "DECODE_BAD"),
        ("RENDER_STABLE", "DRIFTED"),
        ("DRIFTED", "REENCODE_FAIL"),
    ])
    def test_downgrade_is_regression(self, was, now):
        reg, imp, _, _ = baseline.diff_suite(
            "reverse", {"k": {"bucket": was}}, {"k": {"bucket": now}})
        assert len(reg) == 1 and not imp
        assert reg[0][1] == was and reg[0][2] == now

    @pytest.mark.parametrize("was,now", [
        ("DECODE_BAD", "BYTE_IDENTICAL"),
        ("REENCODE_FAIL", "DRIFTED"),
        ("DRIFTED", "RENDER_STABLE"),
    ])
    def test_upgrade_is_improvement(self, was, now):
        reg, imp, _, _ = baseline.diff_suite(
            "reverse", {"k": {"bucket": was}}, {"k": {"bucket": now}})
        assert len(imp) == 1 and not reg

    def test_same_bucket_is_neither(self):
        reg, imp, _, _ = baseline.diff_suite(
            "reverse", {"k": {"bucket": "DRIFTED"}}, {"k": {"bucket": "DRIFTED"}})
        assert not reg and not imp

    def test_unknown_bucket_ranks_worst(self):
        # An unrecognised bucket must not silently read as an improvement.
        reg, imp, _, _ = baseline.diff_suite(
            "reverse", {"k": {"bucket": "DECODE_BAD"}}, {"k": {"bucket": "WAT"}})
        assert len(reg) == 1 and not imp


class TestEncodeDiff:
    def test_ok_to_fail_is_regression(self):
        reg, imp, _, _ = baseline.diff_suite(
            "encode", {"x": {"ok": True, "blob": "aaa"}},
            {"x": {"ok": False, "error": "`=` unexpected"}})
        assert len(reg) == 1 and not imp
        assert "unexpected" in reg[0][3]

    def test_fail_to_ok_is_improvement(self):
        reg, imp, _, _ = baseline.diff_suite(
            "encode", {"x": {"ok": False}}, {"x": {"ok": True, "blob": "bbb"}})
        assert len(imp) == 1 and not reg

    def test_changed_blob_is_drift_not_regression(self):
        reg, imp, drift, _ = baseline.diff_suite(
            "encode", {"x": {"ok": True, "blob": "aaa"}},
            {"x": {"ok": True, "blob": "zzz"}})
        assert not reg and not imp and len(drift) == 1

    def test_identical_blob_is_silent(self):
        reg, imp, drift, _ = baseline.diff_suite(
            "encode", {"x": {"ok": True, "blob": "aaa"}},
            {"x": {"ok": True, "blob": "aaa"}})
        assert not reg and not imp and not drift


class TestPrepareDiff:
    def test_changed_output_is_regression(self):
        reg, _, _, _ = baseline.diff_suite(
            "prepare", {"e": {"out": "x^2"}}, {"e": {"out": "x**2"}})
        assert len(reg) == 1

    def test_stable_output_is_silent(self):
        reg, _, _, _ = baseline.diff_suite(
            "prepare", {"e": {"out": "x^2"}}, {"e": {"out": "x^2"}})
        assert not reg


class TestMissing:
    def test_dropped_item_is_reported_not_ignored(self):
        # An item vanishing from the new run must never read as "no regression".
        reg, imp, drift, missing = baseline.diff_suite(
            "reverse", {"a": {"bucket": "BYTE_IDENTICAL"}}, {})
        assert missing == ["a"] and not reg and not imp and not drift


class TestFixture:
    def test_blob_fixture_is_intact(self):
        """Guards the frozen corpus: an emptied fixture would make --check pass
        trivially and hide every regression it exists to catch."""
        data = json.loads(Path(baseline.FIXTURE).read_text(encoding="utf-8"))
        blobs = data["blobs"]
        assert len(blobs) >= 100
        assert all(b["blob"].strip() for b in blobs)
        assert len({b["id"] for b in blobs}) == len(blobs)

    def test_version_probe_needs_no_kernel(self):
        # Must work on an unlicensed / kernel-less box.
        assert isinstance(baseline.maple_version(), str)
