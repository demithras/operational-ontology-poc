"""Oracle-backed request drawing for the H29 generator: every request is evaluated by the ORACLE on the predicted snapshot and re-drawn
until it has the intended class. Never raises: an exhausted draw returns None (counted as a redraw failure by the caller)."""
from __future__ import annotations

from r3_harness.h23.goodargs import random_args
from r3_oracle import approvals, ops_model
from r3_oracle.disclosure import low_view
from r3_oracle.disclosure_reads import expected_read_object

MAX_TRIES = 250
STR_POOL = {"visibility": ["internal", "public"], "reviewer": ["rev-a", "rev-b", "rev-c"]}
SYSTEM_OP = {"WMS": "transfer_inventory", "ERP": "expedite_purchase_order", "MES": "reschedule_work_order",
             "REGISTRY": "publish_result", "NOTIFY": "notify_reviewer"}


def _args(op: dict, snap: dict, ch) -> dict:
    a = random_args(op, snap, ch)
    for i in op["inputs"]:
        if i["name"] in STR_POOL and (i["required"] or i["name"] in a):
            a[i["name"]] = ch.choice(STR_POOL[i["name"]])
    return a


def principals(plan, kinds=None, exclude=()) -> list:
    return [p["id"] for p in plan.auth0["principals"] if p["id"] not in exclude and (kinds is None or p["kind"] in kinds)]


def has_external(dec) -> bool:
    return bool(dec.outcome is not None and any(e.get("kind") == "external" for e in dec.outcome.effects))


def draw(plan, ch, want: str, op: str | None = None, system: str | None = None, who=None, auth=None):
    """-> {principal, operation, args, dec, akey, approver} or None. want: ok | ok_ext | ok_local | approved | deny | invalid."""
    auth = auth or plan.doc()
    opnames = [o["name"] for o in plan.ops["operations"]]
    for _ in range(MAX_TRIES):
        name = SYSTEM_OP[system] if system else (op or ch.choice(opnames))
        spec = ops_model.op_of(plan.ops, name)
        if spec is None:
            return None
        sub = who if who else ch.choice(principals(plan))
        args = _args(spec, plan.rep.snap, ch)
        if want == "invalid":
            args = {k: v for k, v in args.items() if k != spec["inputs"][0]["name"]} if spec["inputs"] else {"zz": 1}
            return {"principal": sub, "operation": name, "args": args, "dec": None, "akey": "", "approver": None}
        dec, akey = plan.rep.decide(auth, sub, None, name, args, plan.t, None)
        if want in ("ok", "ok_ext", "ok_local") and dec.kind == "OK" and dec.outcome.effects and not dec.outcome.used_approval:
            if want == "ok_ext" and not has_external(dec) or want == "ok_local" and has_external(dec):
                continue
            return {"principal": sub, "operation": name, "args": args, "dec": dec, "akey": akey, "approver": None}
        if want == "deny" and dec.kind == "DENIED" and dec.outcome is not None and dec.outcome.kind != ops_model.NEEDS_APPROVAL:
            return {"principal": sub, "operation": name, "args": args, "dec": dec, "akey": akey, "approver": None}
        if want == "approved" and dec.outcome is not None and dec.outcome.kind == ops_model.NEEDS_APPROVAL:
            for ap in principals(plan):
                if approvals.validate(plan.ops, auth, ap, sub, name, args)[0]:
                    return {"principal": sub, "operation": name, "args": args, "dec": dec, "akey": akey, "approver": ap}
    plan.stats["redraw"] = plan.stats.get("redraw", 0) + 1
    return None


def stale_pair(plan, ch, k: int):
    """A request OK under version 0 and DENIED under version k (the removed grant): stale-sensitive by construction."""
    d0, dk = plan.fam[0], plan.fam[k] if k < len(plan.fam) else None
    if dk is None:
        return None
    for _ in range(MAX_TRIES):
        name = ch.choice([o["name"] for o in plan.ops["operations"]])
        spec = ops_model.op_of(plan.ops, name)
        sub = ch.choice(principals(plan))
        args = _args(spec, plan.rep.snap, ch)
        a, ak = plan.rep.decide(d0, sub, None, name, args, plan.t, None)
        if not (a.kind == "OK" and a.outcome.effects and not a.outcome.used_approval):
            continue
        b, _ = plan.rep.decide(dk, sub, None, name, args, plan.t, None)
        if b.kind != "OK":
            return {"principal": sub, "operation": name, "args": args, "dec": a, "akey": ak, "approver": None}
    return None


def read_pair(plan, ch, k: int):
    """A read whose oracle low view differs between version 0 and version k (R29-3 stale-sensitive), else None."""
    if k >= len(plan.fam):
        return None
    refs = sorted(plan.rep.snap["objects"])
    for _ in range(MAX_TRIES // 2):
        sub, ref = ch.choice(principals(plan)), ch.choice(refs)
        e0 = expected_read_object(low_view(plan.rep.snap, plan.fam[0], sub, plan.ops), ref)
        ek = expected_read_object(low_view(plan.rep.snap, plan.fam[k], sub, plan.ops), ref)
        if e0 != ek:
            t, key = ref.split(":", 1)
            return {"principal": sub, "operation": "get", "args": {"type": t, "key": key}}
    return None


def any_read(plan, ch):
    refs = sorted(plan.rep.snap["objects"])
    ref = ch.choice(refs)
    t, key = ref.split(":", 1)
    return {"principal": ch.choice(principals(plan)), "operation": "get", "args": {"type": t, "key": key}}
