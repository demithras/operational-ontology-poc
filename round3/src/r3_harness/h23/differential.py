"""Variant differential (ruling R-5): replay ONE variant's recorded seeded corpus against another variant and report
every call whose measured world diff differs. Informational only: the evaluator never reads the output.

An oracle cannot catch an error it shares with a variant (dev3: oracle and conventional shared the R-1 defect),
so two variants are compared with each other directly. Replay uses the concrete recorded steps (corpus.py records
every sequence concretely), one fresh deployment per sequence, exactly like the original run."""
from __future__ import annotations

import json
from pathlib import Path

from r3_oracle import ops_model

from .corpus import load_specs, new_env, run_steps

MAX_LISTED = 200


def diff_key(measured: list[dict]) -> list[str]:
    """Canonical, order-insensitive form of one call's measured world diff (same normalisation as the oracle match)."""
    return sorted(ops_model._norm(m) for m in measured)  # noqa: SLF001 - the one record normaliser


def load_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def replay(variant, records: list[dict], specs: dict | None = None) -> dict[str, list[dict]]:
    """seq_id -> the calls produced by replaying that record's steps on `variant` (empty-step records skipped)."""
    specs = specs or load_specs()
    out: dict[str, list[dict]] = {}
    for rec in records:
        if not rec["steps"]:
            continue
        env = new_env(variant, rec["domain"], specs, f"diff-{rec['seq_id']}")
        try:
            out[rec["seq_id"]] = run_steps(env, rec["steps"])
        finally:
            env.close()
    return out


def compare(records: list[dict], replayed: dict[str, list[dict]], ref_name: str, other_name: str) -> dict:
    """Per-call comparison of the reference records' calls against the replay; first MAX_LISTED differences listed."""
    total = differing = 0
    listed: list[dict] = []
    for rec in records:
        if rec["seq_id"] not in replayed:
            continue
        a_calls, b_calls = rec["calls"], replayed[rec["seq_id"]]
        for i in range(max(len(a_calls), len(b_calls))):
            a = a_calls[i] if i < len(a_calls) else None
            b = b_calls[i] if i < len(b_calls) else None
            total += 1
            ka = None if a is None else diff_key(a["measured"])
            kb = None if b is None else diff_key(b["measured"])
            if ka == kb:
                continue
            differing += 1
            if len(listed) < MAX_LISTED:
                ref = a or b
                listed.append({"seq_id": rec["seq_id"], "domain": rec["domain"], "call_index": i, "rule": ref["rule"],
                               "operation": ref["operation"], "subject": ref["subject"], "oracle": ref["oracle"],
                               ref_name: None if a is None else a["measured"],
                               other_name: None if b is None else b["measured"]})
    return {"reference": ref_name, "other": other_name, "calls_compared": total, "differing_calls": differing,
            "listed": len(listed), "differences": listed}


def write_report(path: Path, pairs: list[dict], seed: int, sequences: int) -> None:
    doc = {"informational": True, "note": "no verdict clause reads this file (ruling R-5)", "seed": seed,
           "sequences": sequences, "pairs": pairs}
    Path(path).write_text(json.dumps(doc, indent=1, sort_keys=True, default=str) + "\n")
