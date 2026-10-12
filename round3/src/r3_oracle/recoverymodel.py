"""H29 independent lifecycle / replay model (PROT-H29 s4; ORACLE-AND-HARNESS-G5 s1). PURE: r3_shared forms + r3_oracle only.
Candidate state (HistoryStore, state_dir, CallResults, recovery_view) is only COMPARED here, never used to predict. The shared world
store's world_log is used ONLY (a) to learn which requests committed and (b) as the object of checks (Q11, cross-checked against the
anchor log by the judge). Total: absent -> explicit value, no exceptions."""
from __future__ import annotations

import copy
import hashlib

from r3_shared.extadapter import canon_json

from . import approvals, extoracle, ops_model
from .continuity import authority_in_force, doc_of, grant_until

FINAL = ("RECONCILED_SUCCESS", "RECONCILED_FAILED", "DIVERGED")


# ---- world replay ---------------------------------------------------------------------------------------------------
def apply_effects(snap: dict, effects: list) -> dict:
    s = copy.deepcopy(snap)
    for e in effects:
        k = e.get("kind")
        if k == "create":
            s["objects"][e["ref"]] = {"props": dict(e["props"]), "version": 1}
        elif k == "update" and e["ref"] in s["objects"]:
            s["objects"][e["ref"]]["props"].update({f: v[1] for f, v in e["changes"].items()})
        elif k == "delete":
            s["objects"].pop(e["ref"], None)
        elif k == "link":
            t = e["ref"].split("|", 2)
            if t not in s["links"]:
                s["links"].append(t)
        elif k == "unlink":
            t = e["ref"].split("|", 2)
            if t in s["links"]:
                s["links"].remove(t)
    return s


def world_digest(snap: dict) -> str:
    """Digest of canonical objects (props) + links: version counters and log heads are not part of the canonical state."""
    objs = {k: v["props"] for k, v in sorted(snap["objects"].items())}
    return hashlib.sha256(canon_json({"objects": objs, "links": sorted(map(list, snap["links"]))}).encode()).hexdigest()


def commit_marks(world_log: list) -> list:
    """OK commit marks of the shared world_log, in world_seq order: the committed list of the canonical history (Q11)."""
    return [{"request_id": r["data"].get("request_id"), "world_seq": r["seq"], "authority_version": r["data"].get("authority_version"),
             "tick": r["tick"]} for r in world_log if r.get("kind") == "mark" and r.get("ref") == "commit"]


class Replayer:
    """Applies the oracle decision of each actual commit, in world_seq order, to the seed snapshot."""

    def __init__(self, ops: dict, seed_snap: dict):
        self.ops, self.snap, self.committed = ops, copy.deepcopy(seed_snap), set()
        self.appr: dict = {}
        self.fp: dict = {}

    def approve(self, auth: dict, approver, requester, obo, op: str, args) -> bool:
        ok, _ = approvals.validate(self.ops, auth, approver, requester, op, args)
        if ok:
            k = approvals.key(requester, obo, op, args)
            self.appr[k] = self.appr.get(k, 0) + 1
            # G5-E11: canonical approval fingerprint
            self.fp[k] = hashlib.sha256(canon_json({"subject": requester, "on_behalf_of": obo or None, "operation": op, "inputs": args}).encode()).hexdigest()
        return ok

    def decide(self, auth: dict, subject, obo, op, args, tick: int, rid):
        """Oracle decision for a request against the CURRENT predicted state (no mutation)."""
        akey = approvals.key(subject, obo, op, args) if isinstance(args, dict) else ""
        return extoracle.decide(self.ops, auth, subject, obo, op, args, self.snap, tick, frozenset(self.committed), rid,
                                approved=self.appr.get(akey, 0) > 0), akey

    def commit(self, dec, akey: str, rid) -> None:
        """The world really committed this request: apply its effects (oracle form) and consume the approval."""
        if rid in self.committed:
            return
        if dec.kind == "OK" and dec.outcome is not None:
            self.snap = apply_effects(self.snap, dec.outcome.effects)
            if dec.outcome.used_approval:
                self.appr[akey] = self.appr.get(akey, 0) - 1
        self.committed.add(rid)

    def open_approvals(self) -> list:
        return sorted({self.fp[k] for k, n in self.appr.items() if n > 0 and k in self.fp})


# ---- outcome chain (P1f-6 via extoracle; reused unchanged) ------------------------------------------------------------
def predict_outcomes(intents: list, reads: list, dep_ledger: dict, systems: dict, tick0: int, window: int) -> dict:
    """intents: extoracle.intended() dicts of ONE request. reads: harness-recorded reconcile calls that returned a reply, in order:
    {watermark, tick, fault: None|{kind,k}}. -> {effect_index: (state, confidence, evidence, rule_trace)} after the last read."""
    prev: dict = {}
    prev_wm: dict = {}
    res: dict = {}
    for rd in reads:
        f = rd.get("fault")
        unavailable = bool(f) and f["kind"] == "unavailable"
        lag = int(f["k"]) if f and f["kind"] == "lagging" else 0
        snap = None if unavailable else extoracle.observer_view(dep_ledger, dep_ledger["_dep"], systems, rd["watermark"], lag, rd["tick"])
        for I in intents:
            key = I["effect_index"]
            tr: list = []
            st, cf, ev = extoracle.outcome_state(I, snap, prev.get(key, (None, []))[0], prev.get(key, (None, []))[1], I["idempotency"],
                                                 I["observability"], tick0 + window, prev_wm.get(key), tr)
            if snap is not None:
                prev_wm[key] = max(prev_wm.get(key, -1), snap["watermark"])
            prev[key] = (st, ev)
            res[key] = (st, cf, ev, tr[0] if tr else "")
    return res


def initial_state(I: dict) -> tuple:
    """State of an intent no reconcile ever applied: PENDING (UNKNOWN when the system is unobservable); confidence per observability."""
    obs = I["observability"]
    return ("UNKNOWN" if obs == "none" else "PENDING"), ("full" if obs == "full" else "low")


def chain_count(dep_ledger: dict, I: dict) -> int:
    """Distinct cap chains the ledger shows for this intent's correlation; one chain is minted per effect even when unused."""
    ch = {r["cap_chain"] for r in dep_ledger["effects"] + dep_ledger["audit"] if r.get("correlation") == I["correlation"]}
    return max(1, len(ch))


# ---- RECOVERY_VIEW prediction ---------------------------------------------------------------------------------------
def predict_view(marks: list, intent_states: dict, versions: list, t_probe: int, approvals_open: list, lease: int = 4) -> dict:
    """RC2 (R29-11). intent_states: {(rid, idx): {system, chain_ids, state, confidence}}."""
    return {"form": "r3-recovery-1",
            "committed": [{"request_id": m["request_id"], "world_seq": m["world_seq"], "authority_version": m["authority_version"]} for m in marks],
            "intents": [{"request_id": r, "effect_index": i, "system": v["system"], "chain_ids": v["chain_ids"], "state": v["state"],
                         "confidence": v["confidence"]} for (r, i), v in sorted(intent_states.items())],
            "authority": {"version": authority_in_force(versions, t_probe), "lease_until": grant_until(versions, t_probe, lease)},
            "approvals_open": sorted(set(approvals_open))}


def view_diff(a: dict, b: dict, path: str = "") -> list:
    """Field paths where two views differ (canonical comparison). Empty list == byte-equal canonical JSON."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            out += view_diff(a.get(k), b.get(k), f"{path}.{k}" if path else k) if (k in a and k in b) else [f"{path}.{k}" if path else k]
        return out
    if isinstance(a, list) and isinstance(b, list):
        out = [] if len(a) == len(b) else [f"{path}[len {len(a)}!={len(b)}]"]
        for i, (x, y) in enumerate(zip(a, b)):
            out += view_diff(x, y, f"{path}[{i}]")
        return out
    return [] if canon_json(a) == canon_json(b) else [path or "<root>"]


def rc1_admissible(view: dict, marks: list, intents_expected: dict, versions: list, t: int) -> list:
    """R29-10. -> list of violation strings (empty = admissible). intents_expected: {(rid, idx): {admissible_states:set, confidence,
    system}}; marks = oracle committed list at the RC1 point."""
    out = []
    want = [{"request_id": m["request_id"], "world_seq": m["world_seq"], "authority_version": m["authority_version"]} for m in marks]
    if view.get("committed") != want:
        out.append("committed list != oracle committed set")
    got = {(i["request_id"], i["effect_index"]): i for i in view.get("intents", [])}
    for k in sorted(set(got) | set(intents_expected), key=str):
        if k not in got or k not in intents_expected:
            out.append(f"intent {k}: {'missing from view' if k not in got else 'not expected by the oracle'}")
            continue
        g, e = got[k], intents_expected[k]
        if g["state"] not in e["admissible_states"]:
            out.append(f"intent {k}: state {g['state']} not in {sorted(e['admissible_states'])}")
        if g["confidence"] != e["confidence"] or g["system"] != e["system"]:
            out.append(f"intent {k}: confidence/system differ")
    a = (view.get("authority") or {}).get("version")
    if a is not None and a != authority_in_force(versions, t):
        out.append("authority version in the view is not in force at the RC1 tick (stale_authority_after_restart)")
    return out


def doc_for(versions: list, t: int):
    d = authority_in_force(versions, t)
    return None if d is None else doc_of(versions, d)
