"""Gate-pass records (Engine v1.1, defence in depth for the Function != Action boundary).

When an execution clears its gates the pipeline journals a ``gate_pass`` record BEFORE the APPROVED state:
  via "gates":    identity, inputs, authority, preconditions and policy passed (policy verdict APPROVED);
  via "approval": the same five gates passed into PENDING_APPROVAL, then a second principal approved.
The record carries the hash of the gated inputs. The executor refuses to enter (or, on recovery, continue)
EXECUTING unless the JOURNAL holds such a record for that execution whose inputs hash equals the inputs about to
execute; the check reads only the journal and the identity directory, never a caller-supplied record.
"""
from __future__ import annotations

from typing import Optional

from .canon import digest

KIND = "gate_pass"
GATED = ("identity", "inputs", "authority", "preconditions", "policy")


def inputs_hash(inputs) -> str:
    return digest({"inputs": inputs})


def record_pass(eng, rec: dict, via: str, approved_by: Optional[str] = None) -> None:
    eng._write({"kind": KIND, "exec": rec["exec"], "action": rec["action"], "principal": rec["principal"]["pid"],
                "inputs_hash": inputs_hash(rec["inputs"]), "via": via,
                "gates": [g["gate"] for g in rec["gates"] if g.get("passed") is True], "approved_by": approved_by})


def _chain_pids(eng, pid) -> Optional[set]:
    p = eng.directory.get(pid) if isinstance(pid, str) else None
    return None if p is None else {q.pid for q in p.chain()}


def _approval_problem(eng, gp: dict, journal: list) -> Optional[str]:
    xid = gp["exec"]
    if "approval" not in gp.get("gates", []):
        return "approval gate-pass without a passed approval gate"
    pending = [r for r in journal if r.get("kind") == "exec" and r["seq"] < gp["seq"]
               and (r.get("rec") or {}).get("exec") == xid and r["rec"].get("state") == "PENDING_APPROVAL"]
    if not pending:
        return "no journaled PENDING_APPROVAL state precedes the approval"
    p = pending[-1]["rec"]
    if inputs_hash(p.get("inputs")) != gp["inputs_hash"]:
        return "approved inputs differ from the inputs that were pending approval"
    passed = {g.get("gate") for g in p.get("gates", []) if g.get("passed") is True}
    if not set(GATED) <= passed:
        return f"pending record lacks passed gates {sorted(set(GATED) - passed)}"
    approver, proposer = _chain_pids(eng, gp.get("approved_by")), _chain_pids(eng, gp.get("principal"))
    if approver is None or proposer is None:
        return "approver or proposer is not a registered principal"
    if approver & proposer:
        return "approval was not given by a second principal"
    return None


def problem(eng, rec: dict) -> Optional[str]:
    """None when the journal authorises executing ``rec`` (the Engine's internal record); else the reason."""
    xid = rec["exec"]
    journal = list(eng.journal)
    passes = [r for r in journal if r.get("kind") == KIND and r.get("exec") == xid]
    if not passes:
        return "no journaled gate-pass record for this execution"
    gp = passes[-1]
    if gp.get("action") != rec["action"] or gp.get("principal") != (rec.get("principal") or {}).get("pid"):
        return "gate-pass record names a different action or principal"
    if gp.get("inputs_hash") != inputs_hash(rec["inputs"]):
        return "inputs about to execute differ from the gated inputs"
    missing = [g for g in GATED if g not in gp.get("gates", [])]
    if missing:
        return f"gate-pass record lacks passed gates {missing}"
    if gp.get("via") == "gates":
        return None
    if gp.get("via") == "approval":
        return _approval_problem(eng, gp, journal)
    return f"unknown gate-pass route {gp.get('via')!r}"
