"""Random lifecycle cases guided by the independent oracle world (so deep paths are reached, not only illegal ones)."""
from __future__ import annotations

import copy
import hashlib
import json
import random

from eoo_exp.util import load_oracle

from .fixture import SUBJECTS, facts_for

W = load_oracle("h18", "world")
CLAIMS = ("a new falsifiable claim", "another claim", "", "   ", "third claim")
OP_KINDS = ("preregister", "edit_threshold", "new_version", "start", "attach", "evaluate", "forced_verdict", "supersede",
            "flag", "decision", "create")


def make_case(rnd: random.Random, base_ops: list, commit: str) -> dict:
    subject = rnd.choice(SUBJECTS)
    phase0 = rnd.choices(("DRAFT", "PREREGISTERED", "RUNNING"), (4, 2, 4))[0]
    complete = {k: (True if phase0 != "DRAFT" else rnd.random() < 0.85) for k in W.CORE_LINKS}
    pins = rnd.choices(("good", "version", "env", "commit", "hash"), (14, 3, 2, 2, 2), k=rnd.randint(1, 4))
    mode = rnd.choice(("all_s", "all_s", "mixed", "with_r"))  # what the evaluator will see: supports / mixed / one refutation
    tag = lambda i: "s" if mode == "all_s" else ("r" if mode == "with_r" and i == 0 else rnd.choices("snr", (5, 2, 2))[0])  # noqa: E731
    ev = [{"id": f"ev-gen-{i}", "pin": p, "tag": tag(i)} for i, p in enumerate(pins)]
    dec = {"id": "dec-gen", "rationale": rnd.choice(("because the evidence changed", "", "  "))} if rnd.random() < 0.4 else None
    comps = [{"id": "cmp-gen-0"}] if rnd.random() < 0.6 else []
    return {"subject": subject, "phase0": phase0, "complete": complete, "evidence": ev, "decision": dec, "components": comps,
            "facts": facts_for(base_ops, subject, commit), "ops": []}


def _progress(w, case: dict, rnd: random.Random) -> dict:
    ph = w.phase
    if ph == "DRAFT":
        return rnd.choice((_prereg(rnd), _prereg(rnd), {"k": "edit_threshold", "value": _val(case, rnd)}))
    if ph == "PREREGISTERED":
        return rnd.choice(({"k": "start"}, {"k": "start"}, {"k": "new_version", "exp": rnd.choice(("base", "latest"))}))
    if ph == "RUNNING":
        pend = [i for i, e in enumerate(case["evidence"]) if e["id"] not in w.attached]
        if pend and rnd.random() < 0.85:
            return {"k": "attach", "ev": case["evidence"][rnd.choice(pend)]["id"]}
        return {"k": "evaluate"}
    if ph == "EVALUATED":
        return {"k": "supersede", "succ": "other"}
    opts = [{"k": "create", "claim": rnd.choice(CLAIMS)}, _flag(case, rnd)] + ([{"k": "decision"}] if case["decision"] else [])
    return rnd.choice(opts)


def _val(case, rnd) -> int:
    v = rnd.randint(100, 199)
    return v + 1 if v == case["facts"]["threshold_value"] else v


def _prereg(rnd) -> dict:
    return {"k": "preregister", "freeze": "junk", "freeze_value": f"fh-{rnd.randint(0, 9999)}"}


def _flag(case, rnd) -> dict:
    cmps = sorted(case["facts"]["components"]) + [c["id"] for c in case["components"]]
    return {"k": "flag", "cmp": rnd.choice(cmps)}


def _random_op(case: dict, rnd: random.Random, w) -> dict:
    k = rnd.choice(OP_KINDS)
    if k == "preregister":
        return _prereg(rnd) if rnd.random() < 0.8 else {"k": k, "freeze": "blank", "freeze_value": ""}
    if k == "edit_threshold":
        return {"k": k, "value": _val(case, rnd)}
    if k == "new_version":
        return {"k": k, "exp": rnd.choice(("base", "latest"))}
    if k == "attach":
        return {"k": k, "ev": rnd.choice(case["evidence"])["id"]} if case["evidence"] else {"k": "start"}
    if k == "supersede":
        return {"k": k, "succ": rnd.choice(("self", "other", "other"))}
    if k == "flag":
        return _flag(case, rnd)
    if k == "create":
        return {"k": k, "claim": rnd.choice(CLAIMS)}
    if k == "decision" and not case["decision"]:
        return {"k": "evaluate"}
    if k == "forced_verdict":
        exp = W.expected_verdict(w.tags())
        return {"k": k, "value": rnd.choice([v for v in ("SUPPORTED", "REJECTED", "INCONCLUSIVE", "INVALID") if v != exp])}
    return {"k": k}


def classify(w, op: dict, legal: bool) -> list[str]:
    """Hostile / interesting classes of an op, from the oracle world BEFORE the op."""
    k, out = op["k"], []
    if k == "edit_threshold" and w.phase != "DRAFT":
        out.append("post_freeze_threshold_edit")
    if k == "attach":
        pin = w.ev[op["ev"]]["pin"]
        out.append("evidence_wrong_version" if pin == "version" else "evidence_unpinned" if pin != "good" else "evidence_pinned_ok")
    if k == "evaluate":
        out.append("evaluate_without_evidence" if not w.attached else "evaluate_with_evidence")
    if k == "forced_verdict":
        out += ["forced_verdict", "verdict_without_evidence" if not w.attached else "verdict_with_evidence"]
    if k == "supersede":
        out.append("supersede_self" if op["succ"] == "self" else "supersede_non_evaluated" if w.phase != "EVALUATED" else "supersede_ok")
    if k == "flag":
        out.append("flag_orphan" if op["cmp"] in w.orphans() else "flag_non_orphan")
    if k == "preregister":
        out.append("blank_freeze" if op["freeze"] == "blank" else "incomplete_preregistration" if not w.complete else "preregister")
    if k == "new_version" and w.phase not in ("DRAFT", "SUPERSEDED"):
        out.append("new_version_overwrite" if not legal else "new_version_chain" if op["exp"] == "latest" and len(w.versions) > 1 else "new_version_ok")
    if k == "start" and w.phase != "PREREGISTERED":
        out.append("start_out_of_order")
    if k == "decision":
        out.append("decision_blank_rationale" if not legal else "decision_ok")
    return out + [f"{k}:{'legal' if legal else 'illegal'}"]


def gen_case(rnd: random.Random, base_ops: list, commit: str, max_ops: int = 10) -> dict:
    case = make_case(rnd, base_ops, commit)
    w = W.World(case)
    for _ in range(rnd.randint(1, max_ops)):
        op = _progress(w, case, rnd) if rnd.random() < 0.7 else _random_op(case, rnd, w)
        case["ops"].append(op)
        w.step(op)
    return case


def case_hash(case: dict) -> str:
    c = {k: v for k, v in case.items() if k != "facts"}
    return hashlib.sha256(json.dumps(c, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]


def replay_classes(case: dict) -> list[dict]:
    """[{op, legal, classes}] for the whole case from the oracle alone (used for coverage and for tests)."""
    w, out = W.World(copy.deepcopy(case)), []
    for op in case["ops"]:
        pre = copy.deepcopy(w)
        legal, _ = w.step(op)
        out.append({"op": op, "legal": legal, "classes": classify(pre, op, legal)})
    return out
