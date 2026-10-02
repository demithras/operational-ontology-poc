"""Run a case through the file-only baseline (same ops, same oracle, same summary)."""
from __future__ import annotations

import copy

from eoo_exp.util import load_oracle

from .gen import classify
from .ops import baseline_apply
from .summary import summarize

W = load_oracle("h18", "world")


def run_case_baseline(case: dict, files: dict, evaluators: dict) -> list:
    w, rows = W.World(copy.deepcopy(case)), []
    for i, op in enumerate(case["ops"]):
        pre = copy.deepcopy(w)
        legal, want = w.step(op)
        try:
            ok, files, why = baseline_apply(case, op, files, evaluators)
            exc = None
        except Exception as ex:  # noqa: BLE001 - recorded as a failure row
            ok, why, exc = False, [], f"{type(ex).__name__}: {str(ex)[:160]}"
        row = {"i": i, "op": op["k"], "accepted": ok, "oracle_legal": legal, "exception": exc, "reasons": why[:2], "classes": classify(pre, op, legal)}
        if legal and not ok:
            row["divergence"], w, want = "legal_rejected", pre, pre.summary()
        elif not legal and ok:
            row["divergence"] = "illegal_accepted"
        row["summary"] = summarize(files, case["subject"], case)
        row["summary_match"] = row["summary"] == want
        if not row["summary_match"]:
            row["summary_diff"] = sorted(k for k in want if want[k] != row["summary"][k])
        rows.append(row)
        if row.get("divergence") == "illegal_accepted":
            break
    return rows
