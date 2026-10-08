"""The governed Action lifecycle, identical for every action (see docs/engine_semantics.md):

PROPOSED -> identity -> request (idempotency key) -> inputs -> stale -> authority -> preconditions
-> policies -> DENIED | PENDING_APPROVAL | APPROVED -> EXECUTING (WriteGrant) -> EFFECTS_COMMITTED
-> observe outcome -> RECONCILED_SUCCESS | RECONCILED_FAILED | OUTCOME_UNKNOWN
"""
from __future__ import annotations

from typing import Any, Optional

from . import effects, gatepass, gates, outcome
from .authority import Principal
from .canon import digest, to_plain
from .errors import CapabilityError, InvalidRequest

TERMINAL = ("DENIED", "RECONCILED_SUCCESS", "RECONCILED_FAILED")
TRANSITIONS = {
    None: {"PROPOSED"},
    "PROPOSED": {"DENIED", "PENDING_APPROVAL", "APPROVED"},
    "PENDING_APPROVAL": {"APPROVED", "DENIED"},
    "APPROVED": {"EXECUTING", "DENIED"},  # DENIED only when the journal holds no matching gate-pass (v1.1)
    "EXECUTING": {"EXECUTING", "EFFECTS_COMMITTED", "DENIED", "OUTCOME_UNKNOWN"},
    "EFFECTS_COMMITTED": {"EFFECTS_COMMITTED", "RECONCILED_SUCCESS", "RECONCILED_FAILED", "OUTCOME_UNKNOWN"},
    "OUTCOME_UNKNOWN": {"OUTCOME_UNKNOWN", "RECONCILED_SUCCESS", "RECONCILED_FAILED"},
    "DENIED": set(), "RECONCILED_SUCCESS": set(), "RECONCILED_FAILED": set(),
}


def _intent_digest(spec, inputs, pid) -> str:
    return digest({"action": spec.rid, "action_version": spec.version, "inputs": inputs, "pid": pid})


def _deny(eng, rec, g: dict) -> dict:
    rec["gates"].append(g)
    return eng.record(rec, "DENIED", note=f"denied at {g['gate']}")


def propose(eng, spec, inputs: Any, principal: Any, idempotency_key: Optional[str] = None,
            expected_versions: Optional[dict] = None) -> dict:
    try:
        plain_inputs = to_plain(dict(inputs))
    except (TypeError, ValueError) as exc:
        raise InvalidRequest(f"inputs are not JSON values: {exc}") from None
    pid = principal if isinstance(principal, str) else getattr(principal, "pid", None)
    intent = _intent_digest(spec, plain_inputs, pid)
    if idempotency_key is not None:
        prior = eng.idempotency.get(f"{spec.rid}\x1f{idempotency_key}")
        if prior is not None:
            prev = eng._executions[prior]
            if prev["digest"] == intent:
                eng.note_retry(prev)
                return prev
    presented = principal.to_plain() if isinstance(principal, Principal) else (
        principal if isinstance(principal, str) else {"unsupported": repr(principal)})
    rec = eng.new_execution(spec, plain_inputs, pid, idempotency_key, intent, expected_versions, presented)
    return run_gates(eng, spec, rec, principal)


def run_gates(eng, spec, rec: dict, principal: Any) -> dict:
    """PROPOSED -> DENIED | PENDING_APPROVAL | APPROVED (-> execute). Also used by crash recovery."""
    idempotency_key, plain_inputs, expected_versions = rec["key"], rec["inputs"], rec["expected_versions"]
    if idempotency_key is not None and rec["key_conflict"]:
        return _deny(eng, rec, gates.gate("idempotency", False, "key reused for a different intent"))
    who, why = eng.identify(principal)
    if who is None:
        return _deny(eng, rec, gates.gate("identity", False, why))
    rec["principal"] = who.to_plain()
    rec["gates"].append(gates.gate("identity", True, who.pid))
    if spec.idempotency == "required" and idempotency_key is None:
        return _deny(eng, rec, gates.gate("request", False, "idempotency key required"))
    problems = gates.check_inputs(eng, spec, plain_inputs)
    if problems:
        return _deny(eng, rec, gates.gate("inputs", False, problems))
    rec["gates"].append(gates.gate("inputs", True))
    resources = gates.resources_of(eng, spec, plain_inputs)
    st = eng.state()
    rec["base_versions"] = {repr((r.actual, r.key)): st.version(r.actual, r.key) for r in resources if r.key is not None
                            and st.version(r.actual, r.key) is not None}
    stale = [k for k, v in (expected_versions or {}).items() if rec["base_versions"].get(k) != v]
    if stale:
        return _deny(eng, rec, gates.gate("stale", False, {"objects": stale}))
    view = eng.read_view()
    dec = eng.dispatch("authority_rules", "decide", None, refs=spec.auth_refs, principal=who,
                       capability=f"action:{spec.rid}", resources=resources, view=view)
    if not dec.allowed:
        return _deny(eng, rec, gates.gate("authority", False, dec.to_plain()))
    rec["gates"].append(gates.gate("authority", True, dec.to_plain()))
    ctx = gates.make_ctx(eng, spec, rec)
    # G3-E17: deny business rules -> existence (inputs gate, above) -> preconditions -> approvals. A clean policy DENY is
    # decided before the preconditions; a policy evaluation ERROR still waits for them (V3).
    verdict, pol = gates.evaluate_policies(eng, spec, ctx)
    if verdict == "DENIED" and not pol["detail"]["errors"]:
        rec["gates"].append(pol)
        return eng.record(rec, "DENIED", note="denied at policy")
    pre = gates.run_logic_gate("preconditions", [(t, eng.bindings.get("precondition", t)) for t in spec.preconditions], ctx)
    if not pre["passed"]:
        return _deny(eng, rec, pre)
    rec["gates"].append(pre)
    rec["gates"].append(pol)
    if verdict == "DENIED":
        return eng.record(rec, "DENIED", note="denied at policy")
    if verdict == "APPROVED":
        gatepass.record_pass(eng, rec, "gates")
    eng.record(rec, verdict)
    return execute(eng, spec, execution=rec["exec"]) if verdict == "APPROVED" else rec


def approval_capabilities(eng, spec) -> list[str]:
    caps = []
    for _text, rid in spec.auth_refs:
        rule = eng.model.get("authority_rules", rid) if rid else None
        if rule is not None and rule.effect == "allow" and rule.capability.startswith("approval:"):
            caps.append(rule.capability)
    return sorted(set(caps))


def decide_approval(eng, spec, execution: str, approver: Any, approve: bool) -> dict:
    rec = eng._executions.get(execution)
    if rec is None or rec["action"] != spec.rid or rec["state"] != "PENDING_APPROVAL":
        raise InvalidRequest(f"{execution!r} is not a pending execution of {spec.rid}")
    who, why = eng.identify(approver)
    if who is None:
        eng.note_attempt(rec, approver, f"identity: {why}")
        raise CapabilityError(f"approver identity rejected: {why}")
    proposer = eng.principal_of(rec["principal"]["pid"])
    if {p.pid for p in who.chain()} & {p.pid for p in proposer.chain()}:
        eng.note_attempt(rec, who.pid, "approver shares the proposer's delegation chain")
        raise CapabilityError("approval needs a second principal")
    resources = gates.resources_of(eng, spec, rec["inputs"])
    grants = [c for c in approval_capabilities(eng, spec)
              if eng.dispatch("authority_rules", "decide", None, refs=spec.auth_refs, principal=who, capability=c,
                              resources=resources, view=eng.read_view()).allowed]
    if not grants:
        eng.note_attempt(rec, who.pid, "no approval capability")
        raise CapabilityError(f"{who.pid} holds no approval capability for {spec.rid}")
    rec["approvals"].append({"pid": who.pid, "approve": approve, "granted": grants, "at": eng.now()})
    if not approve:
        return _deny(eng, rec, gates.gate("approval", False, {"rejected_by": who.pid}))
    rec["gates"].append(gates.gate("approval", True, {"approved_by": who.pid}))
    gatepass.record_pass(eng, rec, "approval", approved_by=who.pid)
    eng.record(rec, "APPROVED")
    return execute(eng, spec, execution=execution)


def _applicable_constraints(eng, spec) -> list:
    """Every constraint except those scoped to a different action (state invariants hold after every commit)."""
    out = []
    for cid, c in sorted(eng.model.all("constraints").items()):
        if c.scope in eng.model.all("actions") and c.scope != spec.rid:
            continue
        out.append(c)
    return out


def execute(eng, spec, execution: str) -> dict:
    """APPROVED (or EXECUTING after a crash) -> effects. Each step is journaled before it is visible."""
    rec = eng._executions[execution]
    if rec["state"] not in ("APPROVED", "EXECUTING"):
        raise InvalidRequest(f"{execution!r} is {rec['state']}, not executable")
    refused = gatepass.problem(eng, rec)  # journal-only check, before EXECUTING is entered (and again on recovery)
    if refused is not None:
        return _deny(eng, rec, gates.gate("gate_pass", False, refused))
    if rec["state"] == "APPROVED":
        eng.record(rec, "EXECUTING")
    st = eng.state()
    stale = [k for k, v in rec["base_versions"].items() if st.version(*eng.parse_ref(k)) != v]
    if stale:
        return _deny(eng, rec, gates.gate("stale", False, {"objects": stale}))
    ctx = gates.make_ctx(eng, spec, rec)
    payloads, ops, problems = {}, [], []
    for eff in spec.effects:
        try:
            payloads[eff.index] = effects.build_payload(spec, eff, rec["inputs"], ctx, eng.bindings)
        except Exception as exc:
            problems.append(f"effect {eff.index} payload: {type(exc).__name__}: {exc}")
            continue
        problems += effects.payload_problems(eff, payloads[eff.index])
        if not effects.routes_to_adapter(eff):
            ops.append(effects.store_op(eff, payloads[eff.index], eng.model, rec["base_versions"]))
    if problems:
        return _deny(eng, rec, gates.gate("effects", False, problems))
    would, errs = eng.store.plan(ops)
    if errs:
        return _deny(eng, rec, gates.gate("integrity", False, errs))
    planned = [{"index": i, "operation": spec.effects[i].operation, "target": spec.effects[i].target, "payload": p}
               for i, p in sorted(payloads.items())]
    wctx = gates.make_ctx(eng, spec, rec, state=would, planned=planned)
    hard_fail, soft = [], []
    for c in _applicable_constraints(eng, spec):
        try:
            holds = eng.dispatch("constraints", "evaluate", c.rid, ctx=wctx)
            err = None
        except Exception as exc:
            holds, err = False, f"{type(exc).__name__}: {exc}"
        if not holds:
            (hard_fail if c.severity == "hard" else soft).append({"constraint": c.rid, "error": err})
    if hard_fail:
        return _deny(eng, rec, gates.gate("hard_constraints", False, hard_fail))
    rec["gates"].append(gates.gate("hard_constraints", True))
    rec["soft_flags"] = soft
    grant = eng.minter.mint(execution)
    try:
        for eff in spec.effects:
            if not effects.routes_to_adapter(eff):
                continue
            eid = f"{execution}/e{eff.index}"
            if eid in rec["responses"]:
                continue  # already answered before a crash: never call the adapter twice
            env = eng.envelope(rec, spec, eff)  # Engine-composed provenance, journaled with the intent (v1.2)
            rec.setdefault("envelopes", {})[eid] = env.to_plain()
            rec["intents"].append(eid)
            eng.record(rec, "EXECUTING", note=f"intent {eid}", fault="ext_intent")
            try:
                resp = eng.call_adapter(grant, rec, spec, eff, payloads[eff.index], env)
            except Exception as exc:
                rec["adapter_errors"].append({"effect": eid, "error": f"{type(exc).__name__}: {exc}"})
                return eng.record(rec, "OUTCOME_UNKNOWN", note=f"adapter failed on {eid}; effect uncertain")
            rec["responses"][eid] = to_plain(resp)
            eng.record(rec, "EXECUTING", note=f"response {eid}", fault="ext_response")
        entries = [{"effect_id": f"{execution}/e{e.index}", "execution": execution, "action": spec.rid,
                    "operation": e.operation, "target": e.target, "payload": payloads[e.index],
                    "response": rec["responses"].get(f"{execution}/e{e.index}")} for e in spec.effects]
        eng.store.apply(grant, execution, ops)
        rec["effect_ids"] = [x["effect_id"] for x in entries]
        eng.record(rec, "EFFECTS_COMMITTED", commit={"ops": ops, "entries": entries})
    finally:
        eng.minter.revoke(grant)
    return outcome.observe_and_reconcile(eng, spec, rec)
