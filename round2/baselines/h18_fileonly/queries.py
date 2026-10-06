"""TC2: the three forensic queries over the repository files."""
from __future__ import annotations

import json

from .derive import latest_experiment
from .rules import orphan


def latest_verdict(m, h):
    vs = [v for v in m.keys("Verdict") if ("EVALUATES", v, h) in m.links]
    return max(vs, key=lambda v: int(v.rsplit("-", 1)[1])) if vs else None


def q1(m, h):
    exp = latest_experiment(m, h)
    ev = m.out("PRODUCES", exp)
    return {"verdict": m.props("Verdict", latest_verdict(m, h))["value"], "experiment": exp, "evidence": ev,
            "commits": sorted({m.props("Evidence", e)["git_commit"] for e in ev})}


def q2(m):
    return [c for c in m.keys("Component") if orphan(m, c)]


def q3(m, reader):
    out = []
    for n in range(15, 23):
        c = json.loads(reader(f"hypotheses/h{n}/contract.json"))
        if any((latest_verdict(m, u) is None or m.props("Verdict", latest_verdict(m, u))["value"] != "SUPPORTED") for u in c.get("upstream_dependencies", [])):
            out.append(c["id"])
    return sorted(out)
