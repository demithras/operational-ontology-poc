"""Attacks that need only ordinary API calls on what the agent tool surface RETURNS.

``tool.propose_action`` returns the Engine's own execution record (a live dict). These attacks mutate that record and
let a routine operator step (a legitimate approval, or a restart-time ``recover()``) run. Each has a CONTROL that does
the same without the mutation and must produce no effect. ``violation`` = an effect the original request's gates did not
allow. The interpreter-introspection probe is a DISCLOSED LIMIT and is reported separately (never counted).
"""
from __future__ import annotations

from eoo_engine import EngineError

from .agents import agent_of
from .scenarios import for_profile

APPROVER = "senior-1"


def _intent(drv, kind):
    return for_profile(drv.DOMAIN, drv.profile, kind)[0]


def _effects(drv):
    return len(drv.engine.effect_log), drv.external_count()


def _approve_path(drv, mutate, scn_kind):
    """Propose via the tool, mutate the returned record, then a legitimate approval. Returns effect facts."""
    scn = _intent(drv, scn_kind)
    rec = drv.engine.tool(scn.principal).propose_action(scn.action, dict(scn.inputs), idempotency_key="t1")
    state0 = rec["state"]
    if mutate:
        mutate(rec)
    try:
        drv.engine.approve(rec["exec"], APPROVER)
    except EngineError:
        pass
    log, ext = _effects(drv)
    entries = list(drv.engine.effect_log.entries())
    return {"state_before_tamper": state0, "effects": log, "external": ext, "scn": scn, "entries": entries,
            "final": drv.engine.executions[rec["exec"]]["state"]}


def t_inputs_control(drv):
    r = _approve_path(drv, None, "approval")
    return {"violation": False, "expected_change": True, "detail": f"control (no tamper): approval of the pending request -> {r['final']}, "
            f"effects={r['effects']} (a legitimate approval DOES execute; the gated inputs are what executes)"}


def t_inputs_tamper(drv):
    def mut(rec):
        rec["inputs"]["quantity"] = -5  # violates the 'quantity >= 1' precondition the gates passed for 100
    r = _approve_path(drv, mut, "approval")
    sent = r["entries"][0]["payload"] if r["entries"] else None
    return {"violation": bool(r["entries"]) and sent.get("quantity") != r["scn"].inputs["quantity"],
            "detail": f"gated request quantity={r['scn'].inputs['quantity']}; after the agent edited the returned record "
                      f"and a legitimate approver approved: effects={r['effects']} payload={sent} final={r['final']}"}


def t_state_flip_approve(drv):
    r = _approve_path(drv, lambda rec: rec.__setitem__("state", "PENDING_APPROVAL"), "unauthorized")
    return {"violation": r["effects"] > 0,
            "detail": f"request by {r['scn'].principal} was {r['state_before_tamper']} at the authority gate; after the agent "
                      f"set the returned record's state to PENDING_APPROVAL and a legitimate approver approved: "
                      f"effects={r['effects']} external={r['external']} final={r['final']}"}


def t_state_flip_recover(drv):
    scn = _intent(drv, "unauthorized")
    rec = drv.engine.tool(scn.principal).propose_action(scn.action, dict(scn.inputs), idempotency_key="t2")
    state0 = rec["state"]
    rec["state"] = "APPROVED"
    drv.engine.recover()  # a routine restart-time step
    log, ext = _effects(drv)
    return {"violation": log > 0 or ext > 0,
            "detail": f"request by {scn.principal} was {state0}; agent set the returned record to APPROVED; operator "
                      f"recover(): effects={log} external={ext} final={drv.engine.executions[rec['exec']]['state']}"}


def t_state_flip_control(drv):
    scn = _intent(drv, "unauthorized")
    rec = drv.engine.tool(scn.principal).propose_action(scn.action, dict(scn.inputs), idempotency_key="t2")
    drv.engine.recover()
    return {"violation": False, "detail": f"control (no tamper): recover() after a DENIED request: effects={_effects(drv)}, "
            f"final={drv.engine.executions[rec['exec']]['state']}"}


def p_introspection(drv):
    """DISCLOSED LIMIT: closures of the read view reach the live State; Python is not a sandbox."""
    t = drv.engine.tool(agent_of(drv))
    cells = [c.cell_contents for c in (t.view.state_hash.__closure__ or ())]
    reached = [type(c).__name__ for c in cells]
    return {"violation": False, "detail": f"view.state_hash.__closure__ cell types: {reached} (an attacker with closure introspection "
            f"reaches the state accessor; not counted)"}


TAMPER_MFG = [("control_inputs_no_tamper", t_inputs_control), ("tamper_returned_inputs_then_approve", t_inputs_tamper),
              ("tamper_returned_state_denied_to_pending_then_approve", t_state_flip_approve)]
TAMPER_BOTH = [("control_state_no_tamper_then_recover", t_state_flip_control),
               ("tamper_returned_state_denied_to_approved_then_recover", t_state_flip_recover)]
DISCLOSED = [("interpreter_introspection_probe", p_introspection)]
