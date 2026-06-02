"""Reverse round-trip: real Maple .mw blob -> our syntax -> re-encode -> blob.

This is the direction that tells whether Maple will RENDER an equation the same
after the LLM reads and rewrites it. It starts from a real Maple-authored blob
(which renders correctly by definition) and checks whether decoding + re-encoding
preserves it.

Buckets per sampled equation:
  BYTE_IDENTICAL  re-encoded blob == original  (Maple renders it identically)
  RENDER_STABLE   decode(blob2) == decode(blob1)  (same to a reader; renders equivalently)
  DRIFTED         decode changed  (appearance/meaning drifted)
  REENCODE_FAIL   decoded text could not be re-encoded (would break on rewrite)
  DECODE_BAD      original blob could not be read (empty/garbage)

    SAMPLE=150 python tools/reverse_roundtrip.py
"""
import sys
import os
import glob
import xml.etree.ElementTree as ET
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from maple_mcp.maple_engine import engine
from maple_mcp.document import _replace_units_in_expr, _latex_to_maple

SAMPLE = int(os.environ.get("SAMPLE", "150"))


def _pre(e):
    return _replace_units_in_expr(_latex_to_maple(e))


def _bad(t):
    return (not t or t == "[CORRUPT EQUATION]" or t in ("[]", "()")
            or any(x in t for x in ("InertForm", "NoSimpl", "�", "↦")))


def main():
    files = glob.glob(r"C:\Users\ccoodduu\**\*.mw", recursive=True)
    blobs = {}
    for f in files:
        try:
            root = ET.parse(f).getroot()
        except Exception:
            continue
        for el in root.iter():
            if el.tag.split("}")[-1] != "Equation":
                continue
            if "Output" in el.get("style", ""):
                continue
            b = (el.text or "").strip()
            if b:
                blobs[b] = blobs.get(b, 0) + 1
    uniq = sorted(blobs)
    step = max(1, len(uniq) // SAMPLE)
    sample = uniq[::step][:SAMPLE]
    print("%d unique input blobs; sampling %d" % (len(uniq), len(sample)), flush=True)

    buckets = Counter()
    examples = {}
    for i, b in enumerate(sample):
        try:
            t1 = engine.decode_equation(b)
        except Exception:
            t1 = ""
        if _bad(t1):
            cat = "DECODE_BAD"
        else:
            try:
                engine._last_encode_error = None
                _, b2 = engine.encode_equation(_pre(t1))
            except Exception:
                b2 = ""
            if not b2:
                cat = "REENCODE_FAIL"
            else:
                try:
                    t2 = engine.decode_equation(b2)
                except Exception:
                    t2 = ""
                cat = "BYTE_IDENTICAL" if b2 == b else ("RENDER_STABLE" if t2 == t1 else "DRIFTED")
        buckets[cat] += 1
        examples.setdefault(cat, [])
        if len(examples[cat]) < 8:
            examples[cat].append(t1[:64])
        if i % 20 == 0:
            print("  %d/%d" % (i, len(sample)), flush=True)

    tot = sum(buckets.values())
    print("\n=== REVERSE ROUND-TRIP (real .mw blob -> syntax -> blob) ===")
    for c in ["BYTE_IDENTICAL", "RENDER_STABLE", "DRIFTED", "REENCODE_FAIL", "DECODE_BAD"]:
        print("  %-15s %3d  (%d%%)" % (c, buckets[c], round(100 * buckets[c] / tot)))
    good = buckets["BYTE_IDENTICAL"] + buckets["RENDER_STABLE"]
    print("  --> RENDERS-THE-SAME (byte-identical + render-stable): %d%%" % round(100 * good / tot))
    for c in ["DRIFTED", "REENCODE_FAIL"]:
        if examples.get(c):
            print("\n  %s examples (decoded text):" % c)
            for e in examples[c]:
                print("    " + e)


if __name__ == "__main__":
    main()
