"""The CI invariants: ``violations(before, after, evaluators)`` over two parsed repository states."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from .derive import derive

SCHEMAS = {p.stem.split(".")[0]: json.loads(p.read_text()) for p in (Path(__file__).parent / "schemas").glob("*.schema.json")}
NEXT = {"DRAFT": "PREREGISTERED", "PREREGISTERED": "RUNNING", "RUNNING": "EVALUATED", "EVALUATED": "SUPERSEDED"}
AUTH = ("PREREGISTERED", "RUNNING", "EVALUATED", "SUPERSEDED")
IMMUTABLE = {"Evidence": ("payload_hash", "git_commit", "experiment_version", "environment"), "Verdict": ("value", "derivation_hash", "git_commit"),
             "Experiment": ("version",), "ContractVersion": ("sha256", "git_commit")}


def blank(v) -> bool:
    return not str(v if v is not None else "").strip()


def hyps(m) -> dict:
    return {k: m.props("Hypothesis", k) for k in m.keys("Hypothesis")}


def complete(m, h) -> bool:
    exps = [m.props("Experiment", e) for e in m.out("TESTED_BY", h)]
    return (not blank(m.props("Hypothesis", h)["claim"]) and all(m.out(l, h) for l in ("HAS_RIVAL", "PREDICTS", "FALSIFIED_BY"))
            and any(not blank(e["evidence_schema_ref"]) and not blank(e["evaluator_ref"]) for e in exps))


def owners_of_threshold(m, t):
    return sorted({h for me in m.inn("GOVERNED_BY", t) for e in m.inn("MEASURES", me) for h in m.inn("TESTED_BY", e)})


def lifecycle(b, a):
    out = []
    for h, p in hyps(a).items():
        old = b.props("Hypothesis", h)
        if old is None and p["phase"] != "DRAFT":
            out.append(f"{h}: a new hypothesis must be DRAFT")
        elif old is not None and old["phase"] != p["phase"] and NEXT.get(old["phase"]) != p["phase"]:
            out.append(f"{h}: illegal transition {old['phase']} -> {p['phase']}")
    return out


def preregistration(b, a):
    return [f"{h}: {p['phase']} without a complete contract" for h, p in hyps(a).items() if p["phase"] in AUTH and not complete(a, h)]


def freeze(b, a):
    return [f"{h}: {p['phase']} without a freeze hash" for h, p in hyps(a).items() if p["phase"] in AUTH and blank(p.get("freeze_hash"))]


def frozen_edits(b, a):
    out = []
    for (t, k), new in a.objs.items():
        old = b.props(t, k)
        if old is None or old == new:
            continue
        if t == "Threshold":
            out += [f"{k}: threshold edited while {h} is {b.props('Hypothesis', h)['phase']}" for h in owners_of_threshold(b, k)
                    if b.props("Hypothesis", h)["phase"] != "DRAFT"]
        if t == "Experiment":
            out += [f"{k}: experiment edited while {h} is {b.props('Hypothesis', h)['phase']}" for h in b.inn("TESTED_BY", k)
                    if b.props("Hypothesis", h)["phase"] != "DRAFT"]
        if t == "Falsifier":
            out += [f"{k}: falsifier edited after preregistration" for h in b.inn("FALSIFIED_BY", k) if b.props("Hypothesis", h)["phase"] != "DRAFT"]
        out += [f"{t}[{k}].{f}: immutable" for f in IMMUTABLE.get(t, ()) if old.get(f) != new.get(f)]
    return out


def evidence(b, a):
    out = []
    for (t, e, h) in sorted(a.links - b.links):
        if t == "PRODUCES":
            hs = [x for x in a.inn("TESTED_BY", e)]
            if any(b.props("Hypothesis", x)["phase"] != "RUNNING" for x in hs):
                out.append(f"{e}: evidence attached while its hypothesis is not RUNNING")
    for e in a.keys("Evidence"):
        for exp in a.inn("PRODUCES", e):
            p = a.props("Evidence", e)
            if any(blank(p[f]) for f in IMMUTABLE["Evidence"]) or p["experiment_version"] != a.props("Experiment", exp)["version"]:
                out.append(f"{e}: evidence not bound to experiment version, commit and environment")
    return out


def verdicts(b, a, ev):
    out = []
    for h, p in hyps(a).items():
        vs = [v for v in a.keys("Verdict") if (("EVALUATES", v, h) in a.links)]
        if p["phase"] in ("EVALUATED", "SUPERSEDED") and not vs:
            out.append(f"{h}: {p['phase']} without a verdict")
        if p["phase"] in ("EVALUATED", "SUPERSEDED") and not a.inn("SUPPORTS_OR_REFUTES", h) and not any(a.props("Verdict", v)["value"] in ("INCONCLUSIVE", "INVALID") for v in vs):
            out.append(f"{h}: evaluated without evidence")
        for v in vs:
            new = b.props("Verdict", v) is None
            if new and (b.props("Hypothesis", h) or {}).get("phase") != "RUNNING":
                out.append(f"{v}: verdict created while {h} is not RUNNING")
            if new and a.props("Verdict", v)["value"] != derive(a, h, ev):
                out.append(f"{v}: verdict is not the machine-derived value")
    return out


def supersession(b, a):
    out = []
    for (t, s, d) in sorted(a.links - b.links):
        if t == "SUPERSEDED_BY" and (s == d or a.props("Hypothesis", d) is None or len(a.inn("SUPERSEDED_BY", d)) > 1):
            out.append(f"{s}: invalid successor {d}")
    return out + [f"{h}: SUPERSEDED without a successor" for h, p in hyps(a).items() if p["phase"] == "SUPERSEDED" and not a.out("SUPERSEDED_BY", h)]


def orphan(m, c):
    return not [h for h in m.out("EXISTS_FOR", c) if m.props("Hypothesis", h)["phase"] != "SUPERSEDED"]


def orphans(b, a):
    out = [f"{c}: component deleted" for c in b.keys("Component") if a.props("Component", c) is None]
    return out + [f"{c}: flagged but not an orphan" for c in a.keys("Component")
                  if a.props("Component", c)["orphan_flagged"] and not (b.props("Component", c) or {}).get("orphan_flagged") and not orphan(b, c)]


def decisions(b, a):
    out = []
    for (t, d, cv) in sorted(a.links - b.links):
        if t == "CHANGES" and (blank(a.props("Decision", d)["rationale"]) or blank(a.props("ContractVersion", cv)["git_commit"])):
            out.append(f"{d}: decision without rationale or on an unbound contract version")
    return out


def new_versions(b, a):
    out = []
    for e in a.keys("Experiment"):
        base, _, v = str(e).partition("@v")
        if v and b.props("Experiment", e) is None and any(b.props("Hypothesis", h)["phase"] in ("DRAFT", "SUPERSEDED") for h in b.inn("TESTED_BY", base)):
            out.append(f"{e}: new experiment version while the hypothesis is DRAFT or SUPERSEDED")
    return out


def schema(b, a):
    out = []
    for (t, k), p in a.objs.items():
        if b.props(t, k) != p and t.lower() in SCHEMAS:
            out += [f"{t}[{k}]: {e.message}" for e in jsonschema.Draft202012Validator(SCHEMAS[t.lower()]).iter_errors(p)]
    return out


def violations(b, a, ev) -> list[str]:
    return (schema(b, a) + lifecycle(b, a) + preregistration(b, a) + freeze(b, a) + frozen_edits(b, a) + evidence(b, a)
            + verdicts(b, a, ev) + supersession(b, a) + orphans(b, a) + decisions(b, a) + new_versions(b, a))
