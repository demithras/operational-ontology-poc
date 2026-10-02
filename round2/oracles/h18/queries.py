"""Independent expected answers for the three fixed TC2 queries, computed from raw committed files (no runtime)."""
from __future__ import annotations

import json


def _records(files: dict, prefix: str) -> list:
    return [json.loads(b) for p, b in sorted(files.items()) if p.startswith(prefix)]


def q1(reader, hid: str = "H15", exp: str = "exp-h15-002") -> dict:
    """Evidence files + commit behind the committed verdict of ``hid``: read from experiments/h15/<exp>/ in the repo."""
    verdict = json.loads(reader(f"experiments/h15/{exp}/verdict.json"))
    names = sorted(verdict["evidence_payload_hashes"])
    commits = sorted({json.loads(reader(f"experiments/h15/{exp}/{n}"))["git_commit"] for n in names})
    return {"verdict": verdict["verdict"], "experiment": exp, "evidence": [f"{exp}/{n}" for n in names], "commits": commits}


def q2(files: dict) -> list:
    """Components with no EXISTS_FOR link to a hypothesis that is not SUPERSEDED."""
    phase = {r["key"]: r["props"]["phase"] for r in _records(files, "ontology/objects/Hypothesis/")}
    linked = {}
    for r in _records(files, "ontology/links/EXISTS_FOR/"):
        linked.setdefault(r["src"][1], []).append(r["dst"][1])
    return sorted(r["key"] for r in _records(files, "ontology/objects/Component/")
                  if not [h for h in linked.get(r["key"], []) if phase[h] != "SUPERSEDED"])


def q3(files: dict, reader) -> list:
    """Hypotheses with an upstream dependency (from the committed contracts) whose latest verdict is not SUPPORTED."""
    verdicts = {}
    value = {r["key"]: r["props"]["value"] for r in _records(files, "ontology/objects/Verdict/")}
    for r in _records(files, "ontology/links/EVALUATES/"):
        verdicts.setdefault(r["dst"][1], []).append(r["src"][1])
    blocked = []
    for n in range(15, 23):
        c = json.loads(reader(f"hypotheses/h{n}/contract.json"))
        for up in c.get("upstream_dependencies", []):
            vs = sorted(verdicts.get(up, []), key=lambda v: int(v.rsplit("-", 1)[1]))
            if not vs or value[vs[-1]] != "SUPPORTED":
                blocked.append(c["id"])
                break
    return sorted(blocked)
