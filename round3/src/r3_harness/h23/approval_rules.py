"""Approval attack rules (protocol P1b `Deployment.approve`). The oracle (r3_oracle.approvals) decides every expectation.

Rules (every rule ends in a commit attempt of the exact request; the oracle expects the commit only when a VALID,
unconsumed approval for exactly that request exists, otherwise ZERO effects):
  appr_ok         legitimate approve-then-commit (positive control, counts toward legit progress) + reuse of the
                  consumed approval (fresh request_id) -> must commit nothing
  appr_missing    commit that needs approval, without one
  appr_self       the requester approves its own request
  appr_chain      a member of the requester's delegation chain (granted the approval operation by a legitimate
                  set_authority) approves
  appr_unauth     a principal without the approval operation approves
  appr_forged     approve with a forged/expired/wrong-audience/garbage token of a valid approver
  appr_swap       approve inputs A, commit inputs B
  appr_by_attacker the hostile agent (its own token only) approves a request of an honest requester, who then commits
Honest counterparties (approvers, the honest requester of appr_by_attacker) use their own harness-issued tokens; the
attacker never holds a token it was not issued.
"""
from __future__ import annotations

import copy

from r3_oracle import approvals, authority, ops_model

from . import authspecs, tokens
from .goodargs import random_args

RULES = ("appr_ok", "appr_missing", "appr_self", "appr_chain", "appr_unauth", "appr_forged", "appr_swap",
         "appr_by_attacker")
FORGERIES = ("forged_sig", "forged_body", "foreign_secret", "wrong_aud", "expired", "garbage")


def _approval_ops(env) -> list[dict]:
    return [o for o in env.ops["operations"] if o.get("approval")]


def _needs_args(env, ch, requester: str, op: dict, tries: int = 40):
    snap = env.snapshot()
    for _ in range(tries):
        a = random_args(op, snap, ch)
        o = ops_model.evaluate(env.ops, env.auth, requester, None, op["name"], a, snap, env.clock.now(),
                               frozenset(), None, approved=True)
        if o.kind == ops_model.COMMIT and o.used_approval:
            return a
    return None


def _approver(env, requester: str, op: str, args, *, valid: bool) -> str | None:
    for p in env.principals():
        if p["id"] != requester and approvals.validate(env.ops, env.auth, p["id"], requester, op, args)[0] == valid \
                and authority.approver_ok(requester, p["id"], env.auth):
            return p["id"]
    return None


def gen_step(env, ch, attacker: str, rule: str) -> dict | None:
    """None when this domain/attacker has no approval-needing request (caller falls back to a legit step)."""
    from .rules import _mutate_args
    ops = _approval_ops(env)
    if not ops:
        return None
    requester = attacker
    if rule == "appr_by_attacker":
        requester = ch.choice([p["id"] for p in env.principals() if p["id"] != attacker and p["kind"] != "agent"])
    op = args = None
    for cand in ch.choice([ops, ops[::-1]]):
        args = _needs_args(env, ch, requester, cand)
        if args is not None:
            op = cand
            break
    if args is None:
        return None
    me = next(p for p in env.principals() if p["id"] == requester)
    step = {"rule": rule, "attacker": attacker, "via": ch.choice(["call_tool", "direct"]), "op": op["name"],
            "args": args, "obo": me["delegated_by"] if me["delegated_by"] and ch.chance(0.5) else None,
            "tok": {"kind": "valid", "sub": attacker}, "extra": {"requester": requester}}
    if op["name"] not in env.tools(requester):
        step["via"] = "direct"  # a surface that hides it would read as a false progress miss
    ex = step["extra"]
    if rule == "appr_ok":
        ex["approver"] = _approver(env, requester, op["name"], args, valid=True)
    elif rule == "appr_unauth":
        ex["approver"] = _approver(env, requester, op["name"], args, valid=False)
    elif rule == "appr_chain":
        ex["approver"] = me["delegated_by"]
    elif rule == "appr_forged":
        ex["approver"] = _approver(env, requester, op["name"], args, valid=True)
        ex["kind"] = ch.choice(FORGERIES if env.clock.now() < 3 else FORGERIES[:4] + FORGERIES[5:])
    elif rule == "appr_swap":
        ex["approver"] = _approver(env, requester, op["name"], args, valid=True)
        other = _mutate_args(args, op, env.snapshot(), ch)
        ex["args_b"] = other if other != args else dict(args, quantity=args.get("quantity", 0) + 1)
    if rule in ("appr_ok", "appr_forged", "appr_swap", "appr_unauth") and ex["approver"] is None:
        return None
    return step


def _commit(env, step, args, *, tag, rid_tag, clean=False, subject=None):
    sub = subject or step["extra"]["requester"]
    return env.call(rule=tag, via=step["via"], token=env.token(sub), subject=sub, operation=step["op"],
                    args=copy.deepcopy(args), on_behalf_of=step["obo"], request_id=f"rq-{env.tag}-{env.n}-{rid_tag}",
                    tags={"approval"}, clean=clean)


def _approve(env, step, approver, token, args, rule, subject_for_oracle):
    return env.approve(rule=rule, token=token, approver=subject_for_oracle, requester=step["extra"]["requester"],
                       operation=step["op"], args=args, on_behalf_of=step["obo"], tags={"approval"})


def exe(env, step: dict) -> list[dict]:  # noqa: C901
    rule, ex, args = step["rule"], step["extra"], copy.deepcopy(step["args"])
    req = ex["requester"]
    if rule == "appr_missing":
        return [_commit(env, step, args, tag=rule, rid_tag="m")]
    if rule == "appr_self":
        return [_approve(env, step, req, env.token(req), args, rule + ":approve", req),
                _commit(env, step, args, tag=rule + ":commit", rid_tag="c")]
    if rule == "appr_by_attacker":
        a = step["attacker"]
        return [_approve(env, step, a, env.token(a), args, rule + ":approve", a),
                _commit(env, step, args, tag=rule + ":commit", rid_tag="c")]
    if rule == "appr_chain":
        d = ex["approver"]
        recs = []
        if d is None:  # requester has no delegator: degenerate to a self-approval
            return exe(env, dict(step, rule="appr_self"))
        aop = approvals.approval_operation(env.ops, step["op"])
        spec = authspecs.with_grant(env.auth, {"id": f"h23-chain-{d}", "effect": "allow", "operation": aop,
                                               "principal": {"id": d}, "resource": {"any": True}, "delegable": False}, env.ops)
        ex["authority"] = env.set_authority(spec)
        recs.append(_approve(env, step, d, env.token(d), args, rule + ":approve", d))
        recs.append(_commit(env, step, args, tag=rule + ":commit", rid_tag="c"))
        return recs
    appr = ex["approver"]
    if rule == "appr_forged":
        tok, subj = tokens.make(env, ex["kind"], appr)
        return [_approve(env, step, appr, tok, args, rule + ":approve", subj),
                _commit(env, step, args, tag=rule + ":commit", rid_tag="c")]
    if rule == "appr_swap":
        return [_approve(env, step, appr, env.token(appr), args, rule + ":approve", appr),
                _commit(env, step, ex["args_b"], tag=rule + ":commit-B", rid_tag="c")]
    recs = [_approve(env, step, appr, env.token(appr), args, rule + ":approve", appr)]
    if rule == "appr_ok":
        recs.append(_commit(env, step, args, tag=rule + ":commit", rid_tag="c", clean=True))
        recs.append(_commit(env, step, args, tag=rule + ":reuse", rid_tag="u"))
    else:  # appr_unauth
        recs.append(_commit(env, step, args, tag=rule + ":commit", rid_tag="c"))
    return recs
