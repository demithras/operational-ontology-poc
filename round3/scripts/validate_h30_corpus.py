#!/usr/bin/env python
"""Frozen H30 corpus validator (TASK-CORPUS-SPEC s3-s5). Run by the TASK AUTHOR before sealing; needs no variant code.
usage: validate_h30_corpus.py PATH [PATH ...] [--exclude-sources PATH ...] [--write-schema] [--json]
  PATH: a task .json file, a corpus .jsonl (one canonical task per line) or a directory of those.
  --exclude-sources: corpora whose cited sources are barred from the validated one (the dev corpus vs the sealed corpora, s4).
  --write-schema: (re)generate spec/gate6/task.schema.json from the rule table and exit.
Exit 0 iff every task is admissible and the corpus rules (unique ids, one source -> one class, <= 2 tasks per source) hold.
Every rejection prints `<task_id>: <CODE>: <reason>`; codes: V1_schema V1_unknown_id V1_unknown_step_kind V2_envelope V3_unreachable_step
V3_vacuous_attack V3_floor V4_citation V4_source V5_adaptation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROUND3 / "src"))

from r3_harness.h30 import validate as C  # noqa: E402
from r3_harness.h30 import rules as D  # noqa: E402


def load_tasks(paths) -> list:
    tasks = []
    for p in map(Path, paths):
        files = sorted(p.rglob("*.json*")) if p.is_dir() else [p]
        for f in files:
            if f.suffix == ".jsonl":
                for n, line in enumerate(f.read_text().splitlines(), 1):
                    if line.strip():
                        tasks.append(json.loads(line))
            elif f.suffix == ".json":
                d = json.loads(f.read_text())
                tasks += d if isinstance(d, list) else [d]
    return tasks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--exclude-sources", nargs="*", default=[])
    ap.add_argument("--write-schema", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.write_schema:
        p = ROUND3 / "spec" / "gate6" / "task.schema.json"
        p.write_text(json.dumps(D.build_schema(), indent=1, sort_keys=True, ensure_ascii=False) + "\n")
        print(f"wrote {p}")
        return 0
    if not a.paths:
        ap.error("no corpus path given")
    tasks = load_tasks(a.paths)
    excluded = {C.source_key(t) for t in load_tasks(a.exclude_sources)} if a.exclude_sources else set()
    issues = []
    for t in tasks:
        issues += C.check_task(t, ROUND3)
    good = [t for t in tasks if isinstance(t, dict) and "source" in t and "primary_class" in t]
    issues += C.check_corpus(good, excluded)
    if a.json:
        print(json.dumps({"tasks": len(tasks), "issues": [i.__dict__ for i in issues]}, indent=1))
    else:
        for i in issues:
            print(i)
        print(f"{len(tasks)} tasks, {len(issues)} issues")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
