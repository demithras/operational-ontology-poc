"""Observable summary of one subject hypothesis, read from canonical artifact files (same layout for every variant)."""
from __future__ import annotations

import json

OBJ, LNK = "ontology/objects/", "ontology/links/"


def _recs(files: dict, prefix: str) -> list[dict]:
    return [json.loads(b) for p, b in sorted(files.items()) if p.startswith(prefix)]


def summarize(files: dict, subject: str, case: dict) -> dict:
    objs = {(r["type"], r["key"]): r["props"] for r in _recs(files, OBJ)}
    links = [(r["type"], r["src"][1], r["dst"][1]) for r in _recs(files, LNK)]
    h = objs[("Hypothesis", subject)]
    exp_ids = sorted(k for (t, k) in objs if t == "Experiment" and (k == case["facts"]["exp"] or str(k).startswith(case["facts"]["exp"] + "@v")))
    verdicts = sorted(((int(str(k).rsplit("-", 1)[1]), p["value"]) for (t, k), p in objs.items()
                       if t == "Verdict" and ("EVALUATES", k, subject) in links and str(k).startswith(f"verdict-{subject}-")))
    succ = [d for (t, s, d) in links if t == "SUPERSEDED_BY" and s == subject]
    dec = case["decision"]["id"] if case.get("decision") else None
    return {"phase": h["phase"], "frozen": bool(str(h.get("freeze_hash") or "").strip()),
            "threshold": objs[("Threshold", case["facts"]["threshold"])]["value"],
            "attached": sorted(s for (t, s, d) in links if t == "SUPPORTS_OR_REFUTES" and d == subject and str(s).startswith("ev-gen-")),
            "versions": sorted(objs[("Experiment", k)]["version"] for k in exp_ids), "verdicts": [v for _, v in verdicts],
            "successor": succ[0] if succ else None,
            "flagged": sorted(k for (t, k), p in objs.items() if t == "Component" and p.get("orphan_flagged") is True),
            "decided": bool(dec and any(t == "CHANGES" and s == dec for (t, s, d) in links)),
            "created_n": sum(1 for (t, k) in objs if t == "Hypothesis" and str(k).startswith("hyp-"))}
