"""Golden baseline for the equation pipeline, so a Maple upgrade becomes a diff.

The existing harnesses (edgecase_harness, reverse_roundtrip) print aggregate
percentages. A percentage cannot answer the only question that matters after a
Maple upgrade: *which* equations changed. This records a per-item result and
diffs two runs, so a port reports "these 7 regressed, these 3 improved" instead
of "84% -> 81%".

Suites:
  prepare   pure-Python preprocessing (LaTeX -> Maple, unit substitution).
            Needs no kernel, so it is always recorded.
  encode    tools/edgecase_corpus.json -> encode_equation. Needs the kernel.
  reverse   tests/fixtures/blob_corpus.json (real Maple-authored blobs) ->
            decode -> re-encode. Needs the kernel. This is the direction that
            says whether Maple still RENDERS an equation the same after we read
            and rewrite it.

    python tools/baseline.py --freeze-corpus   # rebuild the blob fixture (kernel-free)
    python tools/baseline.py --record          # write the golden snapshot
    python tools/baseline.py --check           # diff current behaviour vs golden

--record refuses to write a kernel suite it could not measure, rather than
recording it as all-failing. A baseline of zeros would make any later run look
like a clean sweep, which is the one failure mode that would quietly destroy the
value of the whole exercise.
"""
import sys
import os
import json
import glob
import html
import hashlib
import argparse
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

def _force_utf8_subprocess():
    """Same neutralization as edgecase_harness: _execute_clean re-encodes as
    cp1252 and would crash the harness on unicode input. Applied from main() only,
    so importing this module (e.g. from tests) has no global side effect."""
    orig = subprocess.run

    def patched(*a, **k):
        if k.get("text") and "encoding" not in k:
            k["encoding"] = "utf-8"
            k["errors"] = "replace"
        return orig(*a, **k)

    subprocess.run = patched


from maple_mcp.maple_engine import engine, MAPLE_ROOT  # noqa: E402
from maple_mcp.document import _replace_units_in_expr, _latex_to_maple  # noqa: E402

CORPUS = os.path.join(HERE, "edgecase_corpus.json")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "blob_corpus.json")
GOLDEN = os.path.join(ROOT, "tests", "golden", "maple-baseline.json")

# Best to worst. A move down this list is a regression, up is an improvement.
BUCKETS = ["BYTE_IDENTICAL", "RENDER_STABLE", "DRIFTED", "REENCODE_FAIL", "DECODE_BAD"]


def maple_version():
    """Read the Maple version without starting the kernel (so it works unlicensed)."""
    try:
        with open(os.path.join(MAPLE_ROOT, "license", "version.txt"), encoding="utf-8") as fh:
            return fh.readline().strip()
    except OSError:
        return "unknown"


def kernel_available():
    try:
        engine._ensure_ts2str()
        return True, None
    except (FileNotFoundError, RuntimeError, OSError) as e:
        return False, str(e).splitlines()[0] if str(e) else repr(e)


def _pre(expr):
    return _replace_units_in_expr(_latex_to_maple(html.unescape(expr)))


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def _bad_decode(t):
    return (not t or t == "[CORRUPT EQUATION]" or t in ("[]", "()")
            or any(x in t for x in ("InertForm", "NoSimpl", "�", "↦")))


def _load_corpus_exprs():
    with open(CORPUS, encoding="utf-8") as fh:
        items = json.load(fh)["equations"]
    seen, out = set(), []
    for it in items:
        if it["expr"] in seen:
            continue
        seen.add(it["expr"])
        out.append(it["expr"])
    return out


# --------------------------------------------------------------------------- suites

def run_prepare(exprs):
    """Pure-Python preprocessing. Kernel-free, so this is always measurable."""
    out = {}
    for e in exprs:
        try:
            out[e] = {"out": _pre(e)}
        except Exception as ex:
            out[e] = {"out": None, "error": repr(ex)[:120]}
    return out


def run_encode(exprs):
    out = {}
    for i, e in enumerate(exprs):
        engine._last_encode_error = None
        try:
            _, b64 = engine.encode_equation(_pre(e))
            if b64:
                out[e] = {"ok": True, "blob": _sha(b64)}
            else:
                out[e] = {"ok": False, "error": str(getattr(engine, "_last_encode_error", ""))[:120]}
        except Exception as ex:
            out[e] = {"ok": False, "error": "CRASH " + repr(ex)[:100]}
        if i % 25 == 0:
            print("  encode %d/%d" % (i, len(exprs)), flush=True)
    return out


def run_reverse(blobs):
    out = {}
    for i, b in enumerate(blobs):
        key = _sha(b)
        try:
            t1 = engine.decode_equation(b)
        except Exception:
            t1 = ""
        if _bad_decode(t1):
            out[key] = {"bucket": "DECODE_BAD", "decoded": t1[:120]}
        else:
            try:
                engine._last_encode_error = None
                _, b2 = engine.encode_equation(_pre(t1))
            except Exception:
                b2 = ""
            if not b2:
                out[key] = {"bucket": "REENCODE_FAIL", "decoded": t1[:120]}
            else:
                try:
                    t2 = engine.decode_equation(b2)
                except Exception:
                    t2 = ""
                bucket = ("BYTE_IDENTICAL" if b2 == b
                          else "RENDER_STABLE" if t2 == t1 else "DRIFTED")
                out[key] = {"bucket": bucket, "decoded": t1[:120]}
        if i % 20 == 0:
            print("  reverse %d/%d" % (i, len(blobs)), flush=True)
    return out


# --------------------------------------------------------------------------- diff

def _rank(bucket):
    return BUCKETS.index(bucket) if bucket in BUCKETS else len(BUCKETS)


def diff_suite(name, old, new):
    """Classify each item. Returns (regressions, improvements, drift, missing)."""
    regressions, improvements, drift, missing = [], [], [], []
    for key, was in old.items():
        now = new.get(key)
        if now is None:
            missing.append(key)
            continue
        if name == "reverse":
            if _rank(now["bucket"]) > _rank(was["bucket"]):
                regressions.append((key, was["bucket"], now["bucket"], now.get("decoded", "")))
            elif _rank(now["bucket"]) < _rank(was["bucket"]):
                improvements.append((key, was["bucket"], now["bucket"], ""))
        elif name == "encode":
            if was.get("ok") and not now.get("ok"):
                regressions.append((key, "ok", "FAIL", now.get("error", "")))
            elif not was.get("ok") and now.get("ok"):
                improvements.append((key, "FAIL", "ok", ""))
            elif was.get("ok") and now.get("ok") and was.get("blob") != now.get("blob"):
                # Still encodes, but to different bytes: Maple may render it
                # differently. Informational, not a failure.
                drift.append((key, was.get("blob"), now.get("blob"), ""))
        else:
            if was.get("out") != now.get("out"):
                regressions.append((key, str(was.get("out"))[:60], str(now.get("out"))[:60], ""))
    return regressions, improvements, drift, missing


def _show(title, rows, limit=25):
    if not rows:
        return
    print("\n  %s (%d):" % (title, len(rows)))
    for key, a, b, extra in rows[:limit]:
        print("    %-46s %s -> %s" % (key[:46], a, b))
        if extra:
            print("      %s" % extra[:100])
    if len(rows) > limit:
        print("    ... and %d more" % (len(rows) - limit))


# --------------------------------------------------------------------------- corpus

def freeze_corpus(n, search_root):
    """Snapshot real Maple-authored equation blobs into a committed fixture.

    reverse_roundtrip.py globbed the user's home directory, so its corpus lived
    only on one machine and its result was not reproducible or comparable across
    versions. Freezing it is what makes a 2025-vs-2026 diff mean anything.
    """
    files = glob.glob(os.path.join(search_root, "**", "*.mw"), recursive=True)
    blobs = {}
    for f in files:
        try:
            root = ET.parse(f).getroot()
        except Exception:
            continue
        for el in root.iter():
            if el.tag.split("}")[-1] != "Equation":
                continue
            if "Output" in (el.get("style") or ""):
                continue
            b = (el.text or "").strip()
            if b:
                blobs[b] = blobs.get(b, 0) + 1
    uniq = sorted(blobs)
    if not uniq:
        print("no equation blobs found under %s" % search_root)
        return 1
    step = max(1, len(uniq) // n)
    sample = uniq[::step][:n]
    os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
    # Deliberately no source filenames: the fixture needs the maths, not a list
    # of the user's assignments.
    payload = {
        "note": "Real Maple-authored equation blobs, frozen so the reverse "
                "round-trip is reproducible across machines and Maple versions.",
        "sampled_from_unique": len(uniq),
        "scanned_files": len(files),
        "blobs": [{"id": _sha(b), "blob": b, "seen": blobs[b]} for b in sample],
    }
    with open(FIXTURE, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    print("froze %d of %d unique blobs (%d files) -> %s"
          % (len(sample), len(uniq), len(files), os.path.relpath(FIXTURE, ROOT)))
    return 0


def load_fixture():
    if not os.path.exists(FIXTURE):
        return None
    with open(FIXTURE, encoding="utf-8") as fh:
        return [b["blob"] for b in json.load(fh)["blobs"]]


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--record", action="store_true", help="write the golden snapshot")
    ap.add_argument("--check", action="store_true", help="diff current behaviour vs golden")
    ap.add_argument("--freeze-corpus", action="store_true",
                    help="rebuild tests/fixtures/blob_corpus.json from local .mw files")
    ap.add_argument("--n", type=int, default=200, help="blobs to freeze (default 200)")
    ap.add_argument("--search-root", default=os.path.expanduser("~"),
                    help="where to scan for .mw files when freezing")
    args = ap.parse_args()
    _force_utf8_subprocess()

    if args.freeze_corpus:
        return freeze_corpus(args.n, args.search_root)
    if not (args.record or args.check):
        ap.print_help()
        return 2

    version = maple_version()
    have_kernel, why = kernel_available()
    print("Maple: %s   kernel: %s" % (version, "yes" if have_kernel else "NO (%s)" % why))

    exprs = _load_corpus_exprs()
    blobs = load_fixture()
    if blobs is None:
        print("no blob fixture yet; run --freeze-corpus first (reverse suite skipped)")

    suites = {"prepare": run_prepare(exprs)}
    if have_kernel:
        suites["encode"] = run_encode(exprs)
        if blobs:
            suites["reverse"] = run_reverse(blobs)

    if args.record:
        snap = {
            "maple_version": version,
            "kernel_measured": have_kernel,
            "counts": {k: len(v) for k, v in suites.items()},
            "suites": suites,
        }
        if not have_kernel:
            snap["unmeasured"] = ["encode", "reverse"]
            print("\nWARNING: no kernel, so 'encode' and 'reverse' were NOT measured.")
            print("They are recorded as absent, not as failing. Re-run --record")
            print("with a licensed Maple to complete the baseline.")
        os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
        with open(GOLDEN, "w", encoding="utf-8") as fh:
            json.dump(snap, fh, ensure_ascii=False, indent=1, sort_keys=True)
        print("\nwrote %s" % os.path.relpath(GOLDEN, ROOT))
        for k, v in suites.items():
            if k == "reverse":
                print("  %-8s %d items  %s" % (k, len(v), dict(Counter(i["bucket"] for i in v.values()))))
            elif k == "encode":
                print("  %-8s %d items  ok=%d" % (k, len(v), sum(1 for i in v.values() if i["ok"])))
            else:
                print("  %-8s %d items" % (k, len(v)))
        return 0

    # --check
    if not os.path.exists(GOLDEN):
        print("no golden snapshot at %s; run --record first" % os.path.relpath(GOLDEN, ROOT))
        return 2
    with open(GOLDEN, encoding="utf-8") as fh:
        golden = json.load(fh)
    print("golden recorded on: %s" % golden.get("maple_version", "?"))

    total_reg = 0
    for name in ("prepare", "encode", "reverse"):
        old = golden.get("suites", {}).get(name)
        if old is None:
            print("\n[%s] not in golden (never measured) - skipped" % name)
            continue
        new = suites.get(name)
        if new is None:
            print("\n[%s] cannot measure now (no kernel) - skipped" % name)
            continue
        reg, imp, drift, missing = diff_suite(name, old, new)
        total_reg += len(reg)
        print("\n[%s] %d items: %d regressed, %d improved, %d drifted, %d missing"
              % (name, len(old), len(reg), len(imp), len(drift), len(missing)))
        _show("REGRESSED", reg)
        _show("improved", imp, limit=10)
        _show("byte-drift (still encodes)", drift, limit=10)

    print("\n%s" % ("REGRESSIONS: %d" % total_reg if total_reg else "no regressions"))
    return 1 if total_reg else 0


if __name__ == "__main__":
    sys.exit(main())
