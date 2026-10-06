"""Project-domain helpers, implemented independently from the PROSE in spec/ops/project.json (helpers + reads).
One function each. First argument is always the View. Resource arguments are Refs (type, key); results are Refs,
lists of Refs, strings, bools or None.
"""
from __future__ import annotations

import hashlib
import json

from .view import HelperError, Ref, View

PHASES = ["DRAFT", "PREREGISTERED", "RUNNING", "EVALUATED", "SUPERSEDED"]
EVALUATORS = {"neutral:evidence-present-v1"}


def _blank(v) -> bool:
    return v is None or str(v).strip() == ""


def _canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hypothesis_id_for_claim(v: View, claim) -> str:
    return "hyp-" + hashlib.sha256(str(claim).encode("utf-8")).hexdigest()[:10]


def hypotheses_of_experiment(v: View, experiment: Ref) -> list[Ref]:
    seen, cur = set(), experiment
    while cur is not None and cur not in seen:
        seen.add(cur)
        hs = v.linked_to("TESTED_BY", "Hypothesis", cur)
        if hs:
            return hs
        nxt = v.out("NEW_VERSION_OF", cur)
        cur = nxt[0] if nxt else None
    return []


def hypotheses_of_threshold(v: View, threshold: Ref) -> list[Ref]:
    out: list[Ref] = []
    for m in v.linked_to("GOVERNED_BY", "Metric", threshold):
        for e in v.linked_to("MEASURES", "Experiment", m):
            for h in hypotheses_of_experiment(v, e):
                if h not in out:
                    out.append(h)
    return out


def contract_complete(v: View, hypothesis: Ref) -> bool:
    if not v.exists(hypothesis) or _blank(v.field(hypothesis, "claim")):
        return False
    if not (v.out("HAS_RIVAL", hypothesis) and v.out("PREDICTS", hypothesis) and v.out("FALSIFIED_BY", hypothesis)):
        return False
    return any(not _blank(v.field(e, "evidence_schema_ref")) and not _blank(v.field(e, "evaluator_ref"))
               for e in v.out("TESTED_BY", hypothesis))


def new_experiment_version_number(v: View, experiment: Ref) -> str:
    ver = v.field(experiment, "version")
    s = "" if ver is None else str(ver)
    return str(int(s) + 1) if s.isdigit() else s + ".1"


def new_experiment_id(v: View, experiment: Ref) -> str:
    return experiment[1].split("@v")[0] + "@v" + new_experiment_version_number(v, experiment)


def new_contract_version_id(v: View, experiment: Ref, contract_version: Ref) -> str:
    return contract_version[1] + "+" + new_experiment_version_number(v, experiment)


def existing_contract_version(v: View, experiment: Ref, contract_version: Ref):
    cid = new_contract_version_id(v, experiment, contract_version)
    return cid if v.exists(("ContractVersion", cid)) else None


def head_commit(v: View) -> str:
    commits = [(str(v.field(c, "committed_at")), c[1]) for c in v.refs_of("Commit")]
    if not commits:
        raise HelperError("no Commit")
    return max(commits)[1]


def evidence_experiment(v: View, hypothesis: Ref, evidence: Ref):
    if not v.exists(evidence):
        return None
    ver = v.field(evidence, "experiment_version")
    hits = [e for e in v.out("TESTED_BY", hypothesis) if v.field(e, "version") == ver]
    return hits[0] if len(hits) == 1 else None


def evidence_pinned(v: View, hypothesis: Ref, evidence: Ref) -> bool:
    if not v.exists(evidence):
        return False
    if any(_blank(v.field(evidence, f)) for f in ("payload_hash", "git_commit", "experiment_version", "environment")):
        return False
    return evidence_experiment(v, hypothesis, evidence) is not None


def evidence_rebinding(v: View, evidence: Ref) -> bool:
    ver = v.field(evidence, "experiment_version")
    return any(v.field(e, "version") != ver for e in v.inc("PRODUCES", evidence) if e[0] == "Experiment")


def evidence_count(v: View, hypothesis: Ref) -> int:
    return len([e for e in v.inc("SUPPORTS_OR_REFUTES", hypothesis) if e[0] == "Evidence"])


def next_verdict_id(v: View, hypothesis: Ref) -> str:
    n = len([x for x in v.inc("EVALUATES", hypothesis) if x[0] == "Verdict"])
    return f"verdict-{hypothesis[1]}-{n + 1}"


def _version_sort(ver) -> tuple:
    s = "" if ver is None else str(ver)
    return (1, int(s), "") if s.isdigit() else (0, 0, s)


def verdict_inputs(v: View, hypothesis: Ref) -> dict:
    """The five booleans plus the experiment/evidence used (prose of derive_verdict)."""
    freeze_ok = not _blank(v.field(hypothesis, "freeze_hash"))
    exps = v.out("TESTED_BY", hypothesis)
    if not exps:
        return {"b": dict(protocol_valid=True, required_evidence_complete=False, sample_sufficient=False,
                          reject_hit=False, support_hit=False), "experiment": None, "evidence": []}
    latest = max(exps, key=lambda e: _version_sort(v.field(e, "version")))
    ver = v.field(latest, "version")
    ev = [e for e in v.out("PRODUCES", latest) if v.field(e, "experiment_version") == ver]
    if not ev:
        return {"b": dict(protocol_valid=freeze_ok, required_evidence_complete=False, sample_sufficient=False,
                          reject_hit=False, support_hit=False), "experiment": latest, "evidence": []}
    ref = v.field(latest, "evaluator_ref")
    if ref not in EVALUATORS:
        raise HelperError(f"unknown evaluator {ref!r}")
    ok = evidence_count(v, hypothesis) >= 1
    return {"b": dict(protocol_valid=freeze_ok, required_evidence_complete=ok, sample_sufficient=ok,
                      reject_hit=False, support_hit=ok), "experiment": latest, "evidence": ev}


def derive_verdict(v: View, hypothesis: Ref) -> str:
    b = verdict_inputs(v, hypothesis)["b"]
    if not b["protocol_valid"]:
        return "INVALID"
    if b["reject_hit"]:
        return "REJECTED"
    if not b["required_evidence_complete"] or not b["sample_sufficient"]:
        return "INCONCLUSIVE"
    return "SUPPORTED" if b["support_hit"] else "INCONCLUSIVE"


def verdict_reason(v: View, hypothesis: Ref) -> str:
    """Prose leaves the exact text open; the oracle only requires a non-blank string (compared loosely)."""
    vi = verdict_inputs(v, hypothesis)
    return f"experiment={vi['experiment'][1] if vi['experiment'] else None}; evidence={len(vi['evidence'])}; {vi['b']}"


def verdict_derivation_hash(v: View, hypothesis: Ref) -> str:
    """Prose names the fields but not the exact JSON layout: compared loosely (64 lowercase hex) by the oracle."""
    vi = verdict_inputs(v, hypothesis)
    exp = None if vi["experiment"] is None else [vi["experiment"][1], v.field(vi["experiment"], "version"),
                                                  v.field(vi["experiment"], "evaluator_ref")]
    body = {"hypothesis": hypothesis[1], "experiment": exp, "booleans": vi["b"],
            "evidence": sorted([e[1], v.field(e, "payload_hash")] for e in vi["evidence"]),
            "freeze_hash": v.field(hypothesis, "freeze_hash")}
    return hashlib.sha256(_canon(body).encode()).hexdigest()


def compute_freeze_hash(v: View, experiment: Ref) -> str:
    th: dict[str, object] = {}
    for m in v.out("MEASURES", experiment):
        for t in v.out("GOVERNED_BY", m):
            th[t[1]] = v.field(t, "value")
    body = {"evidence_schema_ref": v.field(experiment, "evidence_schema_ref"),
            "evaluator_ref": v.field(experiment, "evaluator_ref"), "thresholds": [[k, th[k]] for k in sorted(th)]}
    return hashlib.sha256(_canon(body).encode()).hexdigest()


def find_orphan_components(v: View) -> list[str]:
    out = []
    for c in v.refs_of("Component"):
        live = [h for h in v.out("EXISTS_FOR", c) if v.field(h, "phase") != "SUPERSEDED"]
        if not live:
            out.append(c[1])
    return sorted(out)


def is_legal_transition(v: View, hypothesis: Ref, target_phase: str) -> bool:
    cur = v.field(hypothesis, "phase")
    return cur in PHASES and PHASES.index(cur) + 1 < len(PHASES) and PHASES[PHASES.index(cur) + 1] == target_phase


def canonical_state_hash(v: View) -> str:
    types = ("Hypothesis Rival Prediction Falsifier Experiment Metric Threshold Evidence Verdict Component "
             "ContractVersion Commit Test Decision Failure").split()
    rows = sorted(([t, k, v.objects[f"{t}:{k}"]] for t in types for k in v.keys_of(t)), key=lambda r: (r[0], str(r[1])))
    return hashlib.sha256(_canon(rows).encode()).hexdigest()


PROJECT_HELPERS = {f.__name__: f for f in (
    hypothesis_id_for_claim, hypotheses_of_experiment, hypotheses_of_threshold, contract_complete,
    new_experiment_version_number, new_experiment_id, new_contract_version_id, existing_contract_version,
    head_commit, evidence_experiment, evidence_pinned, evidence_rebinding, next_verdict_id, verdict_reason,
    verdict_derivation_hash, evidence_count, compute_freeze_hash, derive_verdict, find_orphan_components,
    canonical_state_hash, is_legal_transition)}
