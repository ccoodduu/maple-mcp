"""Edge-case regression harness for the Maple MCP equation pipeline.

Runs every equation in edgecase_corpus.json (extracted from real LLM solutions
to assignment problems) through encode + decode, and reports the WRITE-FAIL
rate with a breakdown by Maple parser error. Use it to track permissiveness:
the target is write-fail -> ~0 on what an LLM naturally writes.

    python tools/edgecase_harness.py            # display/inline math (default)
    python tools/edgecase_harness.py --all      # also include exec equations
    python tools/edgecase_harness.py --fails     # only list the failures
"""
import sys
import os
import json
import subprocess
import html
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Neutralize the cp1252 _execute_clean bug locally so re-encode of unicode text
# doesn't crash the harness (the real fix belongs in maple_engine._execute_clean).
_orig_run = subprocess.run
def _patched_run(*a, **k):
    if k.get("text") and "encoding" not in k:
        k["encoding"] = "utf-8"
        k["errors"] = "replace"
    return _orig_run(*a, **k)
subprocess.run = _patched_run

from maple_mcp.maple_engine import engine
from maple_mcp.document import _replace_units_in_expr, _latex_to_maple


def _pre(expr):
    return _replace_units_in_expr(_latex_to_maple(html.unescape(expr)))


def _errsig(err):
    err = err or ""
    for key in ("`=` unexpected", "`?` unexpected", "`<=` unexpected", "`>=` unexpected",
                "`|` unexpected", "`-` unexpected", "`{` unexpected", "invalid subscript",
                "missing operator", "reserved word"):
        if key in err:
            return key
    return (err[:40] if err else "EMPTY")


def main():
    include_exec = "--all" in sys.argv
    only_fails = "--fails" in sys.argv
    here = os.path.dirname(__file__)
    corpus = json.load(open(os.path.join(here, "edgecase_corpus.json"), encoding="utf-8"))["equations"]

    seen, eqs = set(), []
    for it in corpus:
        if it.get("mode") == "exec" and not include_exec:
            continue
        if it["expr"] in seen:
            continue
        seen.add(it["expr"])
        eqs.append(it)

    print("running %d equations (%s) ..." % (len(eqs), "all modes" if include_exec else "display/inline"))
    fails, n_ok = [], 0
    for i, it in enumerate(eqs):
        engine._last_encode_error = None
        try:
            _, b64 = engine.encode_equation(_pre(it["expr"]))
            if b64:
                n_ok += 1
            else:
                fails.append((it["expr"], str(getattr(engine, "_last_encode_error", ""))[:120]))
        except Exception as ex:
            fails.append((it["expr"], "CRASH " + repr(ex)[:100]))
        if i % 25 == 0:
            print("  %d/%d" % (i, len(eqs)), flush=True)

    tot = len(eqs)
    print("\n=== ENCODE SCOREBOARD ===")
    print("  ENCODED    %d/%d" % (n_ok, tot))
    print("  WRITE-FAIL %d/%d  (%d%%)" % (len(fails), tot, round(100 * len(fails) / tot)))
    if fails:
        print("\n  by parser error:")
        for sig, c in Counter(_errsig(e) for _, e in fails).most_common():
            print("    %-22s %d" % (sig, c))
        if only_fails or len(fails) <= 40:
            print("\n  failures:")
            for expr, err in fails:
                print("    %-55s | %s" % (expr[:55], err[:48]))
    return len(fails)


if __name__ == "__main__":
    sys.exit(0 if main() == 0 else 1)
