"""B2 history generator: sequential, seeded; 5-30 governed decisions mixing OK / DENIED / INVALID-rule, approvals,
H24 delegate/revoke (v2 histories), set_authority between decisions, evidence refresh, >= 1 committed request_id."""
from __future__ import annotations

import copy
import random

from r3_harness.h23.chooser import RandChooser
from r3_harness.h23.goodargs import random_args
from r3_oracle import approvals, ops_model
from r3_shared.authspec import validate_strict

from .stream import Stream

V2_DEPTH = 8


def to_v2(auth: dict, ops: dict) -> dict:
    """v2 document with one neutral-extension DELEGABLE grant (so a legitimate root edge exists). Validated strictly."""
    spec = copy.deepcopy(auth)
    g = next(g for g in spec["grants"] if g["effect"] == "allow" and g["operation"] != "*" and "role" in g["principal"]
             and not g["operation"].startswith("approval:"))
    spec["grants"].append({**copy.deepcopy(g), "id": "h27-delegable", "origin": "neutral-extension", "delegable": True})
    v2 = {**spec, "spec": "r3-authority-2", "max_delegation_depth": V2_DEPTH, "capabilities": [], "revoked": []}
    validate_strict(v2, ops)
    return v2


def _principals(auth: dict) -> list[dict]:
    return auth["principals"]


def _try_op(s: Stream, ch, want: str, tries: int = 25):
    """(subject, op, args, obo, outcome) with the oracle verdict class `want`: commit|auth|rule."""
    snap = s.snapshot()
    for _ in range(tries):
        sub = ch.choice([p["id"] for p in _principals(s.auth)])
        op = ch.choice(s.ops["operations"])
        args = random_args(op, snap, ch)
        o = ops_model.evaluate(s.ops, s.auth, sub, None, op["name"], args, snap, s.clock.now(), frozenset(s.committed),
                               None, approved=False)
        if (want == "commit" and o.kind == ops_model.COMMIT and o.effects and not o.used_approval) or \
           (want == "auth" and o.kind == ops_model.DENIED_AUTHORITY) or \
           (want == "rule" and o.kind in (ops_model.DENIED_RULE, ops_model.INVALID, ops_model.NEEDS_APPROVAL)
                and not o.detail.startswith("missing") and "not " not in o.detail[:12]):
            return sub, op["name"], args, None
    return None


def _approval_flow(s: Stream, ch):
    snap = s.snapshot()
    for op in [o for o in s.ops["operations"] if o.get("approval")]:
        for _ in range(30):
            req = ch.choice([p["id"] for p in _principals(s.auth)])
            args = random_args(op, snap, ch)
            o = ops_model.evaluate(s.ops, s.auth, req, None, op["name"], args, snap, s.clock.now(), frozenset(), None,
                                   approved=True)
            if o.kind != ops_model.COMMIT or not o.used_approval:
                continue
            for ap in [p["id"] for p in _principals(s.auth)]:
                if approvals.validate(s.ops, s.auth, ap, req, op["name"], args)[0]:
                    return req, ap, op["name"], args
    return None


def _delegation_steps(s: Stream, ch) -> None:
    """Legal root edge, a legal child edge, an amplifying edge (DENIED), then a revoke (all governed decisions)."""
    g = next(g for g in s.auth["grants"] if g["id"] == "h27-delegable")
    op = next(o for o in s.ops["operations"] if o["name"] == g["operation"])
    humans = [p for p in _principals(s.auth) if not p.get("delegated_by") and p["kind"] == "human"]
    role = g["principal"]["role"]
    issuer = next((p["id"] for p in humans if role in p["roles"]), None)
    others = [p["id"] for p in humans if p["id"] != issuer]
    if issuer is None or len(others) < 2:
        return
    rtypes = sorted({i["resource_type"] for i in op["inputs"] if i["type"] == "resource"})
    scope = {"operations": [op["name"]], "resources": [{"type": t, "keys": None} for t in rtypes]}
    now = s.clock.now()
    e1 = {"id": f"e-{s.n}-1", "issuer": issuer, "child": others[0], "parent": None, "scope": scope,
          "expires_at": None, "redelegable": True, "issued_at": now}
    s.mutate("delegate", issuer, None, e1)
    e2 = {"id": f"e-{s.n}-2", "issuer": others[0], "child": others[1], "parent": e1["id"], "scope": scope,
          "expires_at": now + 50, "redelegable": False, "issued_at": now}
    s.mutate("delegate", others[0], None, e2)
    bad = {**e2, "id": f"e-{s.n}-3", "scope": {"operations": [op["name"], "*extra*"], "resources": scope["resources"]}}
    s.mutate("delegate", others[0], None, bad)
    s.mutate("revoke", issuer, None, e2["id"] if ch.chance(0.5) else e1["id"])


def build_history(variant, domain: str, ops: dict, auth: dict, root: str, anchor, seed: int, target: int,
                  v2: bool = False) -> Stream:
    rng = random.Random(seed)
    ch = RandChooser(rng)
    base = to_v2(auth, ops) if v2 else auth
    s = Stream(variant, domain, ops, base, root, anchor, tag=f"{seed}")
    if v2:
        s.auth = {k: v for k, v in base.items() if k not in ("capabilities", "revoked")}
    s.refresh_evidence()
    done_delegation = False
    guard = 0
    while len(s.decisions) < target and guard < target * 12:
        guard += 1
        r = rng.random()
        if r < 0.40 or not s.decisions:
            pick = _try_op(s, ch, "commit")
            if pick:
                sub, op, args, obo = pick
                s.mutate(rng.choice(["call_tool", "direct"]), sub, op, args, obo)
        elif r < 0.55:
            pick = _try_op(s, ch, "auth")
            if pick:
                s.mutate(rng.choice(["call_tool", "direct"]), pick[0], pick[1], pick[2])
        elif r < 0.68:
            pick = _try_op(s, ch, "rule")
            if pick:
                s.mutate("direct", pick[0], pick[1], pick[2])
        elif r < 0.82:
            flow = _approval_flow(s, ch)
            if flow:
                req, ap, op, args = flow
                s.mutate("approve", ap, op, args, requester=req)
                s.mutate(rng.choice(["call_tool", "direct"]), req, op, args)
        elif r < 0.88:
            s.refresh_evidence()
        elif r < 0.93:
            s.clock.advance(rng.randint(1, 3))
        elif r < 0.97 and v2 and not done_delegation:
            _delegation_steps(s, ch)
            done_delegation = True
        elif r < 0.99 and not s.caps:
            spec = copy.deepcopy(base if not v2 else {**s.auth, "capabilities": list(s.caps), "revoked": sorted(s.revoked)})
            spec["grants"] = spec["grants"] + [{**copy.deepcopy(spec["grants"][0]), "id": f"h27-x{s.n}-{guard}",
                                                "origin": "neutral-extension"}]
            try:
                validate_strict(spec, ops)
                s.set_authority(spec)
            except ValueError:
                pass
    if not any(d["status"] == "OK" and d["kind"] in ("call_tool", "direct") for d in s.decisions):
        pick = _try_op(s, ch, "commit", 200)
        if pick:
            s.mutate("direct", pick[0], pick[1], pick[2])
    s.finish()
    return s
