"""Keeps MapleExport's --probe manifest honest against the Java sources.

The probe is only worth running if it covers what the code actually binds to.
Nothing in Java ties the REQUIRED list to ReloadAgent's reflective calls, so a
new Class.forName would silently escape the port check — the probe would report
a clean bill of health for an API surface it never looked at. This asserts the
two agree in both directions.

Class-level only: methods reached via getMethod() on an object discovered at
runtime have no statically known declaring class (that is exactly the
RUNTIME_ONLY list the probe prints), so they cannot be cross-checked here.
"""
import re
from pathlib import Path

JAVA = Path(__file__).resolve().parent.parent / "java"
RELOAD_AGENT = JAVA / "ReloadAgent.java"
MAPLE_EXPORT = JAVA / "MapleExport.java"

CLASS_RE = re.compile(r"com\.maplesoft\.[A-Za-z0-9.]+")


def _reflected_classes():
    """Every com.maplesoft class the Java sources resolve by name."""
    found = set()
    for src in (RELOAD_AGENT, MAPLE_EXPORT):
        text = src.read_text(encoding="utf-8")
        for literal in re.findall(r'Class\.forName\(\s*"([^"]+)"', text):
            if literal.startswith("com.maplesoft."):
                found.add(literal)
    return found


def _manifest_classes():
    """Every com.maplesoft class named in MapleExport's REQUIRED array."""
    text = MAPLE_EXPORT.read_text(encoding="utf-8")
    block = text.split("REQUIRED = {", 1)[1].split("};", 1)[0]
    return set(CLASS_RE.findall(block))


def test_manifest_covers_every_reflected_class():
    missing = _reflected_classes() - _manifest_classes()
    assert not missing, (
        "These classes are resolved by reflection but are not in MapleExport's "
        "REQUIRED manifest, so --probe would not notice if a new Maple moved "
        "them:\n  " + "\n  ".join(sorted(missing)))


def test_manifest_has_no_stale_entries():
    stale = _manifest_classes() - _reflected_classes()
    assert not stale, (
        "These classes are in the REQUIRED manifest but nothing reflects on "
        "them any more; --probe would fail a port for an API the code no "
        "longer uses:\n  " + "\n  ".join(sorted(stale)))


def test_manifest_is_not_empty():
    # A parsing change that silently emptied the manifest would make both
    # checks above pass vacuously.
    assert len(_manifest_classes()) >= 10


def test_export_call_is_reflective():
    """The jar must not regain a compile-time link to worksheet.jar."""
    text = MAPLE_EXPORT.read_text(encoding="utf-8")
    code = [ln for ln in text.splitlines() if not ln.strip().startswith("//")]
    direct = [ln for ln in code
              if re.search(r"^\s*com\.maplesoft\.[A-Za-z0-9.]+\s*\.\s*[a-zA-Z]+\s*\(", ln)]
    assert not direct, (
        "MapleExport must reach Maple only by reflection, or the build needs a "
        "Maple classpath again and breaks on version changes:\n  "
        + "\n  ".join(direct))
