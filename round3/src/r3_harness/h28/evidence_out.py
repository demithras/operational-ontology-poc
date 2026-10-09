"""The five contract evidence files + manifest for one variant (hypotheses/h28/contract.json required_evidence)."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

from r3_shared import extcap, evidence
from r3_shared.extadapter import canon_json

from . import judge
from .runner import FILES

ROUND3 = Path(__file__).resolve().parents[3]
MANIFEST = "manifest.json"
FREEZE_G4 = ROUND3 / "protocol" / "FREEZE_G4.json"


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=1, sort_keys=True, default=str) + "\n")


def tree_sha(pkg: str) -> str:
    h = hashlib.sha256()
    for f in sorted((ROUND3 / "src" / pkg).rglob("*.py")):
        h.update(f.relative_to(ROUND3).as_posix().encode() + f.read_bytes())
    return h.hexdigest()


def git_head() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(ROUND3), "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return "0" * 40


def _cap_view(cap: str) -> dict:
    try:
        return {"chain_id": extcap.chain_id(cap), "caveats": extcap.caveats_of(cap)}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def corpus_file(J: dict, pre: dict) -> dict:
    cases = []
    for cid, d in sorted(J["cases"].items()):
        B = J["recs"].get(cid, {}).get("byz") or {}
        rec = {k: v for k, v in B.get("recorder", {}).items()}
        cases.append({"case": d, "dep": B.get("dep"), "twin_dep": (J["recs"].get(cid, {}).get("twin") or {}).get("dep"),
                      "start_tick": B.get("start_tick"), "world_digest": B.get("world_digest"), "attempts": [{k: v for k, v in a.items() if k != "cap"} for a in (B.get("attempts") or [])],
                      "recorder": {s: [{**{k: v for k, v in e.items() if k != "cap"}, "cap": _cap_view(e["cap"])} for e in log]
                                   for s, log in rec.items()}})
    return {"seed": pre["seed"], "generator": pre["stats"], "cases": cases}


def diff_file(J: dict, agg: dict) -> dict:
    per = []
    for r in J["rows"]:
        B = J["recs"][r["case"]]["byz"]
        per.append({**{k: r[k] for k in ("case", "domain", "system", "prims", "classes", "harness", "detect", "dups", "points", "equal",
                                           "scope_rows", "observed_effects")},
                    "gov": r["gov"], "mismatch": r["mismatch"], "false": r["false"], "progress": r["progress"],
                    "decisions": [{k: q.get(k) for k in ("rid", "i", "replay", "tick", "status", "reason", "oracle", "oracle_reason")} |
                                  {"intents": [i["correlation"] for i in q["intents"]]} for q in B["requests"]],
                    "oracle_final": {}, "ledger": {"effects": [{k: v for k, v in e.items() if k != "payload_json"} for e in J["ledger"]["effects"]
                                                                if e["deployment"] == B["dep"]]}})
    return {"summary": agg, "cases": per, "scope_rows": [{k: v for k, v in e.items() if k != "payload_json"} for e in J["scope_all"]],
            "ledger_head": {"effects": len(J["ledger"]["effects"]), "audit": len(J["ledger"]["audit"])}}


def independence_file(J: dict, agg: dict) -> dict:
    tops, shared, digests = {}, [], hashlib.sha256()
    for cid, kinds in sorted(J["recs"].items()):
        for k, R in sorted(kinds.items()):
            t = R.get("topology")
            if t:
                if t["shared_trust_root"]:
                    shared.append({"case": cid, "kind": k, "reasons": t["reasons"]})
                tops.setdefault("example", t)
            for rc in R["recon"]:
                digests.update(canon_json(rc["transcript"]).encode())
    return {"topology": tops.get("example"), "shared_trust_root": bool(shared), "shared_cases": shared[:50],
            "transcript_sha256": digests.hexdigest(), "positive_controls": agg["floors"]["controls_observed"],
            "honest_controls": agg["floors"]["honest_controls"]}


def write_all(out: Path, J: dict, agg: dict, pre: dict, gov_audit: dict, mutation: dict) -> dict:
    _dump(out / FILES[0], corpus_file(J, pre))
    _dump(out / FILES[1], diff_file(J, agg))
    _dump(out / FILES[2], independence_file(J, agg))
    _dump(out / FILES[3], gov_audit)
    _dump(out / FILES[4], mutation)
    return {f: hashlib.sha256((out / f).read_bytes()).hexdigest() for f in FILES + ("cases.jsonl",)}


def seal(out: Path, exp_id: str, vname: str, pre: dict, hashes: dict, closes: dict, candidate_pkg: str | None, dev: dict,
         extra: dict) -> None:
    freeze = json.loads(FREEZE_G4.read_text())["files"] if FREEZE_G4.is_file() else {}
    cur = {f: hashlib.sha256((ROUND3 / f).read_bytes()).hexdigest() for f in freeze if (ROUND3 / f).is_file()}
    env = evidence.build_envelope(
        experiment_id=exp_id, hypothesis_id="H28", git_commit=git_head(),
        environment={"python": sys.version.split()[0], "platform": platform.platform(), "variant": vname},
        seed=pre["seed"], attack_class="A7", oracle_version=tree_sha("r3_oracle"),
        candidate_version=f"{vname}:{tree_sha(candidate_pkg) if candidate_pkg else 'test-fake'}",
        raw_observations={"evidence_sha256": hashes, "variant": vname, "freeze_g4_sha256": cur, "freeze_g4_frozen": freeze,
                          "closes": closes, "dev_overrides": dev, "sizes": {"cases": pre["cases"], "controls": pre["controls"]},
                          "adapter_catalogue_sha256": hashlib.sha256((ROUND3 / "src/r3_harness/h28/adapters.py").read_bytes()).hexdigest(),
                          **extra})
    p = out / MANIFEST
    p.write_text(json.dumps(env, indent=1, sort_keys=True) + "\n")
