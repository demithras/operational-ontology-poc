"""Finalize phase (OUTSIDE the sandbox, after the services closed): the oracle reads the closed ledgers / anchor logs / authority logs,
every raw record is judged, the aggregate is computed. Everything the evaluator needs is recomputable from cases.jsonl + the closed
service directories (svc/ext-i, svc/anchor-i, svc/auth-i)."""
from __future__ import annotations

import json
from pathlib import Path

from r3_oracle import extoracle
from r3_shared.anchor import LOG_NAME, verify_anchor_log
from r3_shared.authsvc import verify_log

from . import aggregate, judge, specs
from .runner import RAW


def load_raw(vdir: Path) -> list:
    return [json.loads(l) for l in (Path(vdir) / RAW).read_text().splitlines() if l.strip()]


def load_services(svc_root: Path, W: int, closes: dict | None = None) -> dict:
    """Closed ledgers (merged: deployments are world-private), anchor entries, integrity verdicts of the three service kinds."""
    ledgers, anchor, integ = [], set(), {"anchor": [], "auth": [], "ext": []}
    for i in range(W):
        led = extoracle.load_ledger(Path(svc_root) / f"ext-{i}")
        ledgers.append(led)
        ad = Path(svc_root) / f"anchor-{i}"
        for line in (ad / LOG_NAME).read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                anchor.add((e["stream"], e["decision_id"]))
        exp = ((closes or {}).get("anchor") or [{}] * W)[i].get("head") if closes else None
        integ["anchor"].append(verify_anchor_log(ad, expected_head=exp) if exp else verify_anchor_log(ad))
        authv = verify_log(Path(svc_root) / f"auth-{i}")
        integ["auth"].append({"ok": authv["ok"], "errors": authv["errors"]})
    merged = {"effects": [r for l in ledgers for r in l["effects"]], "audit": [r for l in ledgers for r in l["audit"]],
              "sysstate": {}, "issued": [r for l in ledgers for r in l["issued"]]}
    return {"ledgers": ledgers, "merged": merged, "anchor": anchor, "integrity": integ}


def sysstate_check(ledgers: list, sysseed: dict) -> dict:
    from r3_harness.h28.finalize import sysstate_check as s28
    return s28(ledgers, sysseed)


def judge_all(vdir: Path, svc_root: Path, W: int, pre: dict, closes: dict | None = None, reason_map: dict | None = None) -> dict:
    from r3_harness.h28.judge import LedgerIndex
    raws = load_raw(vdir)
    sv = load_services(svc_root, W, closes)
    ctx = judge.Ctx(LedgerIndex(sv["merged"]), sv["anchor"], reason_map)
    rows = [judge.judge_seq(R, ctx) for R in raws]
    for r, R in zip(rows, raws):
        r["planned_cps"] = (R.get("seq_def") or {}).get("cp", [])
    return {"raws": raws, "rows": rows, "agg": aggregate.aggregate(rows), "services": sv,
            "sysstate": sysstate_check(sv["ledgers"], pre["sysseed"])}
