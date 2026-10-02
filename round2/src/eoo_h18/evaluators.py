"""Experiment evaluators registered for the generated corpus (a library both variants may call; not EOO runtime).

``gen:evaluator`` is the registered synthetic evaluator of the generated experiments: it returns the five booleans of
``hdd.verdict.CommonEvaluation`` from the attached evidence rows (hash prefix tag: s = supports, r = refutes, n = neutral).
The H15 evaluator is memoised on its full input (committed blobs are immutable): same input, same booleans.
"""
from __future__ import annotations

import json

from domains.project.evaluators import h15_evaluator

# a path committed in the real repo (the freeze hash reads it); "#..." names the synthetic evaluator
GEN = "src/hdd/verdict.py#gen-evaluator"


def gen_evaluator(experiment: dict, evidence: list, hypothesis: dict) -> dict:
    tags = [str(e["payload_hash"])[:1] for e in evidence]
    n = len(tags)
    return {"protocol_valid": True, "required_evidence_complete": n >= 2, "sample_sufficient": True,
            "reject_hit": any(t == "r" for t in tags), "support_hit": n >= 1 and all(t == "s" for t in tags)}


def memoised(fn):
    cache: dict = {}

    def run(experiment, evidence, hypothesis):
        key = json.dumps([dict(experiment), [dict(e) for e in evidence]], sort_keys=True, default=str)
        if key not in cache:
            cache[key] = fn(experiment, evidence, hypothesis)
        return dict(cache[key])
    return run


def registry(reader, memo_h15: bool = True) -> dict:
    from domains.project.seed_from_repo import H15_EVALUATOR
    h15 = h15_evaluator(reader)
    return {GEN: gen_evaluator, H15_EVALUATOR: memoised(h15) if memo_h15 else h15}
