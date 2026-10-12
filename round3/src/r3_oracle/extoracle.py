"""External-effect oracle for H28 (PROT-H28; ORACLE-AND-HARNESS-G4 s1). PURE: imports r3_shared and r3_oracle only - never a
variant, never r3_harness, never HistoryStore/world_log marks, never adapter replies or variant CallResults (C28-0 AST scan).

Inputs: ops spec, auth spec, systems doc, the harness request log, harness world snapshots, and the ExternalWorld ledger read
through its own read-only connection after close() (plus the revealed root key). Total: absent -> explicit value, no exceptions.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from r3_shared import extcap, extsem, extsystems
from r3_shared.extadapter import correlation, payload_digest

from . import ops_model
from .extoutcome import outcome_state, observer_view  # noqa: F401  (re-export)

OK, DENIED, INVALID = "OK", "DENIED", "INVALID"
REFUSALS = ("bad_signature", "unknown_root", "system_mismatch", "operation_mismatch", "target_mismatch", "payload_mismatch",
            "correlation_missing", "expired", "uses_exhausted")


@dataclass
class Decision:
    kind: str                  # OK | DENIED | INVALID
    reason: str                # oracle detail (rule id / approval_required: <rule> / precondition ...)
    outcome: object = None     # ops_model.Outcome
    intents: list = field(default_factory=list)


def decide(ops_spec, auth_spec, subject, on_behalf_of, operation, args, snapshot, now, committed=frozenset(), request_id=None,
           approved=False) -> Decision:
    """One decision oracle across gates: delegates to ops_model.evaluate (H23 oracle)."""
    try:
        o = ops_model.evaluate(ops_spec, auth_spec, subject, on_behalf_of, operation, args, snapshot, now, committed, request_id,
                               approved=approved)
    except Exception as exc:  # noqa: BLE001 - total
        return Decision(INVALID, f"oracle error: {type(exc).__name__}")
    kind = {ops_model.COMMIT: OK, ops_model.DENIED_AUTHORITY: DENIED, ops_model.DENIED_RULE: DENIED,
            ops_model.NEEDS_APPROVAL: DENIED}.get(o.kind, INVALID)
    return Decision(kind, o.detail, o)


def intended(systems: dict, decision: Decision, request_id: str) -> list[dict]:
    """I(d) per P1f-3: one per external effect of a committing decision (empty otherwise)."""
    if decision.kind != OK or decision.outcome is None or not decision.outcome.effects:
        return []
    out = []
    for e in (x for x in decision.outcome.effects if x.get("kind") == "external"):
        sysd = systems["systems"].get(e.get("adapter"))
        opd = sysd["operations"].get(e.get("target")) if sysd else None
        if opd is None:
            continue
        try:
            target = extsystems.render_target(opd["target_rule"], e["payload"])
        except ValueError:
            continue
        i = len(out)
        out.append({"request_id": request_id, "effect_index": i, "system": e["adapter"], "operation": e["target"],
                    "target": target, "payload": e["payload"], "payload_digest": payload_digest(e["payload"]),
                    "correlation": correlation(request_id, i), "idempotency": opd["idempotency"],
                    "observability": sysd["observability"]})
    return out


def key5(r: dict) -> tuple:
    return (r["system"], r["operation"], r["target"], r["payload_digest"], r["correlation"])


def load_ledger(ext_dir) -> dict:
    """Read the CLOSED ledger (journal_mode=DELETE after close, G4-E13) through a fresh read-only connection."""
    con = sqlite3.connect(f"file:{Path(ext_dir) / 'external.db'}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = lambda q: [dict(r) for r in con.execute(q)]  # noqa: E731
        led = {"effects": rows("SELECT * FROM effects ORDER BY seq"), "audit": rows("SELECT * FROM audit ORDER BY seq"),
               "sysstate": {(r["system"], r["key"]): json.loads(r["props_json"]) for r in rows("SELECT * FROM sysstate")},
               "issued": rows("SELECT * FROM issued")}
        # G5-E4: `unavailable` audit rows attribute nothing; the (unverified) claim of the cap sits in a side table, joined here by audit seq
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='unverified_claim'").fetchone() is not None:
            claims = {r["audit_seq"]: json.loads(r["claim_json"]) for r in rows("SELECT * FROM unverified_claim")}
        else:
            claims = {}
        led["unverified"] = [{**a, "claim": claims[a["seq"]]} for a in led["audit"] if a["seq"] in claims]
    finally:
        con.close()
    return led


def scope_check(ledger: dict, intents_by_dep: dict[str, list[dict]]) -> list[dict]:
    """R28-14: applied rows (any system) equal to no I(d) of any oracle-committed decision of THEIR deployment."""
    bad = []
    for r in ledger["effects"]:
        want = {key5(i) for i in intents_by_dep.get(r["deployment"], [])}
        if key5(r) not in want:
            bad.append(r)
    return bad


def applied_for(ledger: dict, deployment: str, i: dict) -> list[dict]:
    return [r for r in ledger["effects"] if r["deployment"] == deployment and key5(r) == key5(i)]


def duplicates(ledger: dict, deployment: str, i: dict) -> int:
    """R28-7: rows matching I beyond the class allowance (at_most_once/exactly_once_required: rows-1; idempotent_set: 0)."""
    n = len(applied_for(ledger, deployment, i))
    return max(0, n - 1) if i["idempotency"] in ("at_most_once", "exactly_once_required") else 0


def sysstate_expected(systems: dict, ledger: dict, seed: dict) -> dict:
    """Replay of applied rows by the frozen `semantics` onto the seed; must equal the ledger's sysstate (harness-fault check)."""
    applied = [{"system": r["system"], "operation": r["operation"], "target": r["target"], "payload": json.loads(r["payload_json"])}
               for r in ledger["effects"]]
    return extsem.replay(systems, applied, seed)


def predict_write(root_key: bytes, systems: dict, cap: str, operation: str, target: str, payload: dict, tick: int,
                  used: int, issued: set[tuple[str, str, str]]) -> str:
    """C28-5: the oracle's own model of ExternalWorld's frozen refusal order. Returns "applied" or the refusal reason.
    issued = {(nonce, system, deployment)}; used = applied rows already on this cap's chain."""
    dig = payload_digest(payload)
    try:
        cav = extcap.verify(root_key, cap)
    except extcap.CapError:
        return "bad_signature"
    dep, system = cav[1][1], cav[0][1]
    if (extcap.root_nonce(cap), system, dep) not in issued:
        return "unknown_root"
    vals = lambda n: [v for k, v in cav if k == n]  # noqa: E731
    sysd = systems["systems"].get(system)
    if sysd is None or any(v != system for v in vals("system")):
        return "system_mismatch"
    if operation not in sysd["operations"] or any(v != operation for v in vals("operation")):
        return "operation_mismatch"
    if any(v != target for v in vals("target")):
        return "target_mismatch"
    if any(v != dig for v in vals("payload_digest")):
        return "payload_mismatch"
    if len(set(vals("correlation"))) != 1:
        return "correlation_missing"
    if any(tick > v for v in vals("not_after_tick")):
        return "expired"
    if vals("max_uses") and used >= min(vals("max_uses")):
        return "uses_exhausted"
    return "applied"


def caveat_expectation(i: dict, commit_tick: int, window: int) -> dict:
    """C28-3: the exact P1f-4 caveats a correctly scoped per-effect cap carries (max_uses per PROT-H28 s4 / R28-8)."""
    return {"system": i["system"], "operation": i["operation"], "target": i["target"], "payload_digest": i["payload_digest"],
            "correlation": i["correlation"], "not_after_tick": commit_tick + window,
            "max_uses_allowed": (1,) if i["idempotency"] != "idempotent_set" else (1, 2, 3)}


def transcript_matches(snap: dict, entry: dict) -> bool:
    """The observer transcript entry of one read must equal the oracle's replay of that read (else ext_transcript_mismatch)."""
    return (entry["complete_through_tick"] == snap["complete_through_tick"]
            and entry["effects"] == [r["seq"] for r in snap["effects"]] and entry["audit"] == [r["seq"] for r in snap["audit"]])
