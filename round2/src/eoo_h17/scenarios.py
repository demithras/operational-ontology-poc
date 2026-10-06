"""Scenario tables: concrete Engine requests with the GATE TOKENS the author declares for each.

The tokens are the scenario author's statement of which gates the request satisfies (identity, request, inputs,
fresh, authority, preconditions, policy). They are NOT computed by the Engine; the oracle consumes them and the
harness compares the Engine's behaviour with the oracle's prediction. ``tests/h17/test_scenarios.py`` also checks
that each scenario fails exactly the gate it declares, so a mis-declared token is a harness bug, not a finding.
"""
from __future__ import annotations

from dataclasses import dataclass, field

TOK_OK = {"identity": True, "request": True, "inputs": True, "fresh": True, "authority": True,
          "preconditions": True, "policy": "allow"}


@dataclass(frozen=True)
class Scn:
    id: str
    domain: str
    profiles: tuple
    action: str
    principal: str
    inputs: dict
    kind: str  # ok | approval | unauthorized | invalid
    tokens: dict = field(default_factory=lambda: dict(TOK_OK))
    n_effects: int = 1
    key: bool = True
    expected_versions: dict | None = None
    clock: str | None = None  # "LATER" = stale evidence time
    alt_inputs: dict | None = None  # same key + these inputs = a different intent
    approvers_ok: tuple = ()
    approvers_bad: tuple = ()


def tok(**over) -> dict:
    t = dict(TOK_OK)
    t.update(over)
    return t


def _mt(**over) -> dict:
    base = {"source_warehouse": "WH-C", "destination_warehouse": "WH-B", "part": "PX-900", "quantity": 60}
    base.update(over)
    return base


M = "manufacturing"
MFG = [
    Scn("m_ok_planner", M, ("std",), "transfer_inventory", "planner-1", _mt(), "ok", alt_inputs=_mt(quantity=61)),
    Scn("m_ok_agent", M, ("std",), "transfer_inventory", "agent-1", _mt(quantity=7), "ok"),
    Scn("m_ok_junior_small", M, ("std",), "transfer_inventory", "junior-1", _mt(quantity=5), "ok"),
    Scn("m_approval", M, ("std",), "transfer_inventory", "junior-1", _mt(quantity=100), "approval",
        tokens=tok(policy="approval"), approvers_ok=("senior-1",), approvers_bad=("supervisor-1", "junior-1", "ghost")),
    Scn("m_unauth_stranger", M, ("std",), "transfer_inventory", "stranger", _mt(), "unauthorized", tokens=tok(authority=False)),
    Scn("m_unauth_orphan", M, ("std",), "transfer_inventory", "agent-orphan", _mt(), "unauthorized", tokens=tok(authority=False)),
    Scn("m_unauth_ghost", M, ("std",), "transfer_inventory", "ghost", _mt(), "unauthorized", tokens=tok(identity=False)),
    Scn("m_inv_unknown_part", M, ("std",), "transfer_inventory", "planner-1", _mt(part="NOPE"), "invalid", tokens=tok(inputs=False)),
    Scn("m_inv_qty_zero", M, ("std",), "transfer_inventory", "planner-1", _mt(quantity=0), "invalid", tokens=tok(preconditions=False)),
    Scn("m_inv_same_wh", M, ("std",), "transfer_inventory", "planner-1", _mt(destination_warehouse="WH-C"), "invalid",
        tokens=tok(preconditions=False)),
    Scn("m_inv_over_available", M, ("std",), "transfer_inventory", "planner-1", _mt(quantity=501), "invalid",
        tokens=tok(preconditions=False)),
    Scn("m_pol_quarantine", M, ("std",), "transfer_inventory", "planner-1", _mt(destination_warehouse="WH-A"), "invalid",
        tokens=tok(policy="deny")),
    Scn("m_pol_safety_stock", M, ("std",), "transfer_inventory", "planner-1",
        _mt(source_warehouse="WH-B", destination_warehouse="WH-C", part="PX-17", quantity=100), "invalid", tokens=tok(policy="deny")),
    Scn("m_pol_highprio_junior", M, ("std",), "transfer_inventory", "junior-1",
        _mt(source_warehouse="WH-B", destination_warehouse="WH-A", part="PX-17"), "invalid", tokens=tok(policy="deny")),
    Scn("m_pol_stale_evidence", M, ("std",), "transfer_inventory", "planner-1", _mt(), "invalid", tokens=tok(policy="deny"),
        clock="LATER"),
    Scn("m_inv_no_key", M, ("std",), "transfer_inventory", "planner-1", _mt(), "invalid", tokens=tok(request=False), key=False),
    Scn("m_inv_stale_version", M, ("std",), "transfer_inventory", "planner-1", _mt(), "invalid", tokens=tok(fresh=False),
        expected_versions={"('Part', 'PX-900')": 99}),
]

P = "project"
_EV = "exp-h15-002/real-domain-roundtrip.json"
PRJ = [
    Scn("p_ok_create", P, ("std", "nopre", "running"), "create_hypothesis", "researcher-1", {"claim": "c"}, "ok",
        alt_inputs={"claim": "c2"}),
    Scn("p_ok_start_run", P, ("std", "running"), "start_run", "researcher-1", {"hypothesis": "H16"}, "ok"),
    Scn("p_ok_start_run_h17", P, ("nopre",), "start_run", "researcher-1", {"hypothesis": "H17"}, "ok"),
    Scn("p_ok_attach", P, ("running",), "attach_evidence", "researcher-1", {"hypothesis": "H15", "evidence": _EV}, "ok",
        n_effects=3),
    Scn("p_unauth_viewer", P, ("std", "nopre", "running"), "create_hypothesis", "viewer-1", {"claim": "c"}, "unauthorized",
        tokens=tok(authority=False)),
    Scn("p_unauth_ghost", P, ("std", "nopre", "running"), "create_hypothesis", "ghost", {"claim": "c"}, "unauthorized",
        tokens=tok(identity=False)),
    Scn("p_inv_unknown_hyp", P, ("std", "running"), "start_run", "researcher-1", {"hypothesis": "H99"}, "invalid",
        tokens=tok(inputs=False)),
    Scn("p_inv_not_preregistered", P, ("std",), "start_run", "researcher-1", {"hypothesis": "H15"}, "invalid",
        tokens=tok(preconditions=False)),
    Scn("p_inv_not_running", P, ("std",), "attach_evidence", "researcher-1", {"hypothesis": "H15", "evidence": _EV}, "invalid",
        tokens=tok(preconditions=False), n_effects=3),
    Scn("p_pol_no_freeze_hash", P, ("nopre",), "start_run", "researcher-1", {"hypothesis": "H16"}, "invalid",
        tokens=tok(policy="deny")),
    Scn("p_inv_no_key", P, ("std", "nopre", "running"), "create_hypothesis", "researcher-1", {"claim": "c"}, "invalid",
        tokens=tok(request=False), key=False),
    Scn("p_inv_stale_version", P, ("std", "running"), "start_run", "researcher-1", {"hypothesis": "H16"}, "invalid",
        tokens=tok(fresh=False), expected_versions={"('Hypothesis', 'H16')": 99}),
]

ALL = {M: MFG, P: PRJ}
PROFILES = {M: ("std",), P: ("std", "nopre", "running")}


def for_profile(domain: str, profile: str, *kinds: str) -> list:
    return [s for s in ALL[domain] if profile in s.profiles and (not kinds or s.kind in kinds)]
