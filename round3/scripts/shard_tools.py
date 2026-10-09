#!/usr/bin/env python3
"""Helpers for scripts/run_tests_sharded.sh: plan (balanced file->shard assignment), merge (junit -> one summary),
durations (junit -> tests/.durations.json). Test tooling only; imports nothing from src/."""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DUR = ROOT / "tests" / ".durations.json"


def test_files():
    return sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").rglob("test_*.py"))


def weights(files):
    d = json.loads(DUR.read_text()) if DUR.exists() else {}
    # fallback for files without a measurement: size-scaled guess (~1 s per 4 KB), never below 1 s
    return {f: float(d.get(f, max(1.0, (ROOT / f).stat().st_size / 4096))) for f in files}


def plan(n):
    """LPT greedy: heaviest file first onto the currently lightest shard. Prints one line per shard: space-joined files."""
    w = weights(test_files())
    shards = [[0.0, []] for _ in range(n)]
    for f in sorted(w, key=lambda f: (-w[f], f)):
        s = min(shards, key=lambda s: s[0])
        s[0] += w[f]
        s[1].append(f)
    for load, fs in shards:
        print(" ".join(fs) if fs else "-")
    print("planned loads (s): " + " ".join(f"{s[0]:.0f}" for s in shards), file=sys.stderr)


def cases(xml_path):
    for tc in ET.parse(xml_path).getroot().iter("testcase"):
        cn, name = tc.get("classname", ""), tc.get("name", "")
        # junit classname is the dotted module path (+ class); node id rebuilt as module path + name
        status = "passed"
        for ch in tc:
            if ch.tag in ("failure", "error", "skipped"):
                status = {"failure": "failed", "error": "errors", "skipped": "skipped"}[ch.tag]
                break
        yield cn, name, status, float(tc.get("time") or 0)


def merge(paths):
    tot = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for p in paths:
        c = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
        for _, _, st, _ in cases(p):
            c[st] += 1
        print(f"{Path(p).parent.name}: " + ", ".join(f"{v} {k}" for k, v in c.items()))
        for k in tot:
            tot[k] += c[k]
    print(f"{tot['passed']} passed, {tot['failed']} failed, {tot['errors']} errors, {tot['skipped']} skipped")
    sys.exit(1 if tot["failed"] or tot["errors"] else 0)


def durations(paths):
    files = {f[:-3].replace("/", "."): f for f in test_files()}
    acc = {}
    for p in paths:
        for cn, _, _, t in cases(p):
            mod = cn
            while mod and mod not in files:  # strip trailing Class components
                mod = mod.rpartition(".")[0]
            if mod:
                acc[files[mod]] = acc.get(files[mod], 0.0) + t
    DUR.write_text(json.dumps({k: round(v, 2) for k, v in sorted(acc.items())}, indent=1) + "\n")
    print(f"wrote {DUR} ({len(acc)} files, {sum(acc.values()):.0f}s total)", file=sys.stderr)


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    {"plan": lambda: plan(int(args[0])), "merge": lambda: merge(args), "durations": lambda: durations(args)}[cmd]()
