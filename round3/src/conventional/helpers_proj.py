"""Project-domain helper reads, implemented from the prose in spec/ops/project.json (`helpers`)."""
from __future__ import annotations

import hashlib
import json

from .interp import Ctx, HelperError, ref_key
from .worldview import key_of

PHASES = ["DRAFT", "PREREGISTERED", "RUNNING", "EVALUATED", "SUPERSEDED"]


def _blank(v) -> bool:
    return v is None or str(v).strip() == ""


def _cj(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"))


def hypothesis_id_for_claim(ctx: Ctx, claim) -> str:
    return "hyp-" + hashlib.sha256(str(claim).encode("utf-8")).hexdigest()[:10]


def hypotheses_of_experiment(ctx: Ctx, experiment) -> list[str]:
    cur, seen = ref_key(experiment), set()
    while cur is not None and cur not in seen:
        seen.add(cur)
        hits = [key_of(s) for s in ctx.view.sources("TESTED_BY", "Experiment", cur)]
        if hits:
            return hits
        nxt = ctx.view.targets("NEW_VERSION_OF", "Experiment", cur)
        cur = key_of(nxt[0]) if nxt else None
    return []


def hypotheses_of_threshold(ctx: Ctx, threshold) -> list[str]:
    out: list[str] = []
    for m in ctx.view.sources("GOVERNED_BY", "Threshold", ref_key(threshold)):
        for e in ctx.view.sources("MEASURES", "Metric", key_of(m)):
            out += [h for h in hypotheses_of_experiment(ctx, key_of(e)) if h not in out]
    return out


def contract_complete(ctx: Ctx, hypothesis) -> bool:
    h, v = ref_key(hypothesis), ctx.view
    p = v.props("Hypothesis", h)
    if p is None or _blank(p.get("claim")):
        return False
    if not all(v.targets(link, "Hypothesis", h) for link in ("HAS_RIVAL", "PREDICTS", "FALSIFIED_BY")):
        return False
    return any(not _blank(v.field("Experiment", key_of(e), "evidence_schema_ref"))
               and not _blank(v.field("Experiment", key_of(e), "evaluator_ref"))
               for e in v.targets("TESTED_BY", "Hypothesis", h))


def new_experiment_version_number(ctx: Ctx, experiment) -> str:
    ver = ctx.view.field("Experiment", ref_key(experiment), "version")
    if ver is None:
        raise HelperError("experiment has no version")
    ver = str(ver)
    return str(int(ver) + 1) if ver.isdigit() else ver + ".1"


def new_experiment_id(ctx: Ctx, experiment) -> str:
    return ref_key(experiment).split("@v")[0] + "@v" + new_experiment_version_number(ctx, experiment)


def new_contract_version_id(ctx: Ctx, experiment, contract_version) -> str:
    return ref_key(contract_version) + "+" + new_experiment_version_number(ctx, experiment)


def existing_contract_version(ctx: Ctx, experiment, contract_version):
    nid = new_contract_version_id(ctx, experiment, contract_version)
    return nid if ctx.view.props("ContractVersion", nid) is not None else None


def head_commit(ctx: Ctx) -> str:
    rows = [(str(p.get("committed_at") if p.get("committed_at") is not None else ""), k)
            for k, p in ctx.view.items("Commit")]
    if not rows:
        raise HelperError("no Commit exists")
    return max(rows)[1]


def evidence_experiment(ctx: Ctx, hypothesis, evidence):
    ver = ctx.view.field("Evidence", ref_key(evidence), "experiment_version")
    hits = [key_of(e) for e in ctx.view.targets("TESTED_BY", "Hypothesis", ref_key(hypothesis))
            if ctx.view.field("Experiment", key_of(e), "version") == ver]
    return hits[0] if len(hits) == 1 else None


def evidence_pinned(ctx: Ctx, hypothesis, evidence) -> bool:
    p = ctx.view.props("Evidence", ref_key(evidence))
    return (p is not None and not any(_blank(p.get(f)) for f in ("payload_hash", "git_commit", "experiment_version", "environment"))
            and evidence_experiment(ctx, hypothesis, evidence) is not None)


def evidence_rebinding(ctx: Ctx, evidence) -> bool:
    ek = ref_key(evidence)
    ver = ctx.view.field("Evidence", ek, "experiment_version")
    return any(ctx.view.field("Experiment", key_of(e), "version") != ver
               for e in ctx.view.sources("PRODUCES", "Evidence", ek))


def evidence_count(ctx: Ctx, hypothesis) -> int:
    return len(ctx.view.sources("SUPPORTS_OR_REFUTES", "Hypothesis", ref_key(hypothesis)))


def next_verdict_id(ctx: Ctx, hypothesis) -> str:
    h = ref_key(hypothesis)
    return f"verdict-{h}-{len(ctx.view.sources('EVALUATES', 'Hypothesis', h)) + 1}"


def _vkey(ver):
    s = str(ver)
    return (1, int(s), "") if s.isdigit() else (0, 0, s)


def _derivation(ctx: Ctx, h: str) -> dict:
    v = ctx.view
    exps = [key_of(e) for e in v.targets("TESTED_BY", "Hypothesis", h)]
    latest = max(exps, key=lambda e: _vkey(v.field("Experiment", e, "version"))) if exps else None
    fz = not _blank(v.field("Hypothesis", h, "freeze_hash"))
    b = dict(protocol_valid=True, required_evidence_complete=False, sample_sufficient=False, reject_hit=False,
             support_hit=False)
    ev: list[str] = []
    if latest is not None:
        ver = v.field("Experiment", latest, "version")
        ev = [key_of(e) for e in v.targets("PRODUCES", "Experiment", latest)
              if v.field("Evidence", key_of(e), "experiment_version") == ver]
        if not ev:
            b["protocol_valid"] = fz
        else:
            name = v.field("Experiment", latest, "evaluator_ref")
            if name not in ctx.config["evaluators"] or name != "neutral:evidence-present-v1":
                raise HelperError(f"unknown evaluator_ref {name!r}")
            ok = len(ev) >= 1
            b = dict(protocol_valid=fz, required_evidence_complete=ok, sample_sufficient=ok, reject_hit=False,
                     support_hit=ok)
    return {"experiment": latest, "evidence": sorted(ev), "booleans": b, "freeze_hash": v.field("Hypothesis", h, "freeze_hash")}


def derive_verdict(ctx: Ctx, hypothesis) -> str:
    b = _derivation(ctx, ref_key(hypothesis))["booleans"]
    if not b["protocol_valid"]:
        return "INVALID"
    if b["reject_hit"]:
        return "REJECTED"
    if not b["required_evidence_complete"] or not b["sample_sufficient"]:
        return "INCONCLUSIVE"
    return "SUPPORTED" if b["support_hit"] else "INCONCLUSIVE"


def verdict_reason(ctx: Ctx, hypothesis) -> str:
    d = _derivation(ctx, ref_key(hypothesis))
    flags = ", ".join(f"{k}={str(v).lower()}" for k, v in d["booleans"].items())
    return f"experiment={d['experiment'] or 'none'}; evidence_count={len(d['evidence'])}; {flags}"


def verdict_derivation_hash(ctx: Ctx, hypothesis) -> str:
    h = ref_key(hypothesis)
    d, v = _derivation(ctx, h), ctx.view
    exp = None
    if d["experiment"]:
        e = d["experiment"]
        exp = [e, v.field("Experiment", e, "version"), v.field("Experiment", e, "evaluator_ref")]
    ev = sorted([e, v.field("Evidence", e, "payload_hash")] for e in d["evidence"])
    return hashlib.sha256(_cj({"hypothesis": h, "experiment": exp, "evidence": ev, "booleans": d["booleans"],
                               "freeze_hash": d["freeze_hash"]}).encode()).hexdigest()


def compute_freeze_hash(ctx: Ctx, experiment) -> str:
    e, v = ref_key(experiment), ctx.view
    th: dict[str, object] = {}
    for m in v.targets("MEASURES", "Experiment", e):
        for t in v.targets("GOVERNED_BY", "Metric", key_of(m)):
            th[key_of(t)] = v.field("Threshold", key_of(t), "value")
    doc = {"evidence_schema_ref": v.field("Experiment", e, "evidence_schema_ref"),
           "evaluator_ref": v.field("Experiment", e, "evaluator_ref"), "thresholds": [[k, th[k]] for k in sorted(th)]}
    return hashlib.sha256(_cj(doc).encode()).hexdigest()


def find_orphan_components(ctx: Ctx) -> list[str]:
    v = ctx.view
    return [c for c in v.keys("Component")
            if not any(v.field("Hypothesis", key_of(h), "phase") not in (None, "SUPERSEDED")
                       for h in v.targets("EXISTS_FOR", "Component", c))]


def canonical_state_hash(ctx: Ctx) -> str:
    rows = [[t, k, p] for t in sorted(ctx.resources_all) for k, p in ctx.view.items(t)]
    return hashlib.sha256(_cj(sorted(rows, key=lambda r: (r[0], str(r[1])))).encode()).hexdigest()


def is_legal_transition(ctx: Ctx, hypothesis, target_phase) -> bool:
    cur = ctx.view.field("Hypothesis", ref_key(hypothesis), "phase")
    return cur in PHASES and target_phase in PHASES and PHASES.index(target_phase) == PHASES.index(cur) + 1


HELPERS = {f.__name__: f for f in (
    hypothesis_id_for_claim, hypotheses_of_experiment, hypotheses_of_threshold, contract_complete,
    new_experiment_version_number, new_experiment_id, new_contract_version_id, existing_contract_version,
    head_commit, evidence_experiment, evidence_pinned, evidence_rebinding, evidence_count, next_verdict_id,
    derive_verdict, verdict_reason, verdict_derivation_hash, compute_freeze_hash, find_orphan_components,
    canonical_state_hash, is_legal_transition)}
