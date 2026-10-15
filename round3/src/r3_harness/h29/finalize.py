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


def note_anchor_seq(aseq: dict, e: dict) -> None:
    """(stream, decision_id) -> sorted list of the anchor seqs of EVERY entry carrying that decision_id. A request_id the corpus reuses (deny, then
    succeed) is anchored once per decision; the judge picks the entry that records the OK decision by position relative to the head read before
    the call (G5-E20, exact match; the entry carries stream, seq, decision_id, root - only decision_id + seq are usable by the harness)."""
    aseq.setdefault((e["stream"], e["decision_id"]), []).append(e["seq"])
    aseq[(e["stream"], e["decision_id"])].sort()


def verify_ext(ext_dir, led: dict, expected: dict | None = None) -> dict:
    """G5-E35 B8 (invalid_if d): ExternalWorld close() keys and ledger verification, as for the anchor and AuthorityService (G4 root-key re-verification).
    The revealed root key is present and well-formed, HEAD.final records exactly the closed ledger's row counts (and the close() output the
    harness received, when given), and every applied effect row has its applied audit row (one audit row per effect, same chain + correlation)."""
    d, errors = Path(ext_dir), []
    kp, hp = d / "KEY.revealed", d / "HEAD.final"
    key = kp.read_text().strip() if kp.exists() else None
    if key is None:
        errors.append("key not revealed")
    else:
        try:
            if len(bytes.fromhex(key)) < 16:
                errors.append("revealed key too short")
        except ValueError:
            errors.append("revealed key is not hex")
        if expected and expected.get("root_key_hex") not in (None, key):
            errors.append("revealed key differs from the close() output")
    if not hp.exists():
        errors.append("HEAD.final missing")
    else:
        head = json.loads(hp.read_text())
        if head != {"effects": len(led["effects"]), "audit": len(led["audit"])}:
            errors.append(f"HEAD.final {head} differs from the ledger ({len(led['effects'])} effects, {len(led['audit'])} audit rows)")
        if expected and expected.get("head") not in (None, head):
            errors.append("HEAD.final differs from the close() output")
    applied = sorted((r["cap_chain"], r["correlation"], r["system"], r["target"], r["payload_digest"]) for r in led["audit"] if r["outcome"] == "applied")
    eff = sorted((r["cap_chain"], r["correlation"], r["system"], r["target"], r["payload_digest"]) for r in led["effects"])
    if applied != eff:
        errors.append("applied audit rows do not match the effect rows")
    return {"ok": not errors, "errors": errors}


def load_services(svc_root: Path, W: int, closes: dict | None = None) -> dict:
    """Closed ledgers (merged: deployments are world-private), anchor entries, integrity verdicts of the three service kinds."""
    ledgers, anchor, aseq, integ = [], {}, {}, {"anchor": [], "auth": [], "ext": []}
    for i in range(W):
        led = extoracle.load_ledger(Path(svc_root) / f"ext-{i}")
        ledgers.append(led)
        ad = Path(svc_root) / f"anchor-{i}"
        anchor[i], aseq[i] = set(), {}                                  # G5-E30 (e): indexed per anchor instance
        for line in (ad / LOG_NAME).read_text().splitlines():
            if line.strip():
                e = json.loads(line)
                anchor[i].add((e["stream"], e["decision_id"]))
                note_anchor_seq(aseq[i], e)
        exp = ((closes or {}).get("anchor") or [{}] * W)[i].get("head") if closes else None
        integ["anchor"].append(verify_anchor_log(ad, expected_head=exp) if exp else verify_anchor_log(ad))
        authv = verify_log(Path(svc_root) / f"auth-{i}")
        integ["auth"].append({"ok": authv["ok"], "errors": authv["errors"]})
        integ["ext"].append(verify_ext(Path(svc_root) / f"ext-{i}", led, ((closes or {}).get("ext") or [None] * W)[i] if closes else None))
    merged = {"effects": [r for l in ledgers for r in l["effects"]], "audit": [r for l in ledgers for r in l["audit"]],
              "sysstate": {}, "issued": [r for l in ledgers for r in l["issued"]],
              "unverified": [r for l in ledgers for r in l.get("unverified", [])]}
    return {"ledgers": ledgers, "merged": merged, "anchor": anchor, "anchor_seq": aseq, "integrity": integ}


def sysstate_check(ledgers: list, sysseed: dict) -> dict:
    from r3_harness.h28.finalize import sysstate_check as s28
    return s28(ledgers, sysseed)


def judge_all(vdir: Path, svc_root: Path, W: int, pre: dict, closes: dict | None = None, reason_map: dict | None = None) -> dict:
    from r3_harness.h28.judge import LedgerIndex
    raws = load_raw(vdir)
    sv = load_services(svc_root, W, closes)
    ctx = judge.Ctx(LedgerIndex(sv["merged"]), sv["anchor"], reason_map, sv["anchor_seq"], workers=W)
    rows = [judge.judge_seq(R, ctx) for R in raws]
    for r, R in zip(rows, raws):
        r["planned_cps"] = (R.get("seq_def") or {}).get("cp", [])
    return {"raws": raws, "rows": rows, "agg": aggregate.aggregate(rows), "services": sv,
            "sysstate": sysstate_check(sv["ledgers"], pre["sysseed"])}
