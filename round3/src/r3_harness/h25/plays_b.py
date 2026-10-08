"""Emergency and noise plays of the H25 case generator."""
from __future__ import annotations

import copy

from r3_harness.h23.goodargs import pick_args
from r3_oracle import authority, ops_model
from r3_oracle import const_eval as E
from r3_shared.authspec import validate_strict

from . import gen_model, plays_a

INF = 10 ** 9
DECL = "emergency:declare"


def _scope_for(g, op_name):
    op = ops_model.op_of(g.ops, op_name)
    types = sorted({i["resource_type"] for i in op["inputs"] if i["type"] == "resource"})
    return {"operations": [op_name], "resources": [{"type": t, "keys": None} for t in types]}


def emergency_play(g, with_acts=True):
    em, r = g.doc["emergency"], g.rng
    if not em:
        return
    declarers = [p for p in g.principals() if g.M.base_allows(p, None, DECL, [], INF, g.tick()).allow]
    if not declarers:
        return
    ops_in = [o for o in em["ceiling"]["operations"] if ops_model.op_of(g.ops, o)]
    if not ops_in:
        return
    gm = E.body_of(g.M.doc, em["grantees_from"])["members"]
    outsiders = [p for p in g.principals() if p not in gm]
    op_name = r.choice(ops_in)
    variant = r.choices(["legal", "broad", "long", "grantee", "noauth"], weights=[50, 12, 12, 12, 14])[0]
    scope = _scope_for(g, op_name)
    if variant == "broad":
        scope["operations"] = scope["operations"] + ["not_in_ceiling_op"]
    tick = g.tick()
    exp = tick + r.randint(2, em["max_duration"]) if variant != "long" else tick + em["max_duration"] + r.randint(1, 3)
    grantees = r.sample(gm, min(len(gm), r.randint(1, 2)))
    if variant == "grantee" and outsiders:
        grantees = grantees + [r.choice(outsiders)]
    eid, cid = f"em{g.i}-{g.n}", f"d{g.i}-{g.n}"
    g.n += 1
    who = r.choice(declarers) if variant != "noauth" else r.choice([p for p in g.principals() if p not in declarers] or declarers)
    args = {"emergency": eid, "scope": scope, "expires_at": exp, "grantees": grantees}
    rec, v = g.step(who, {"kind": "propose", "case": cid, "operation": DECL, "args": args, "on_behalf_of": None})
    if v.status == "OK":
        plays_a.run_stage(g, cid, "decision", r.choices(["complete", "partial", "dissent", "none"], weights=[70, 10, 10, 10])[0])
        d = plays_a.stage_of(g, cid, "decision")
        rv = d["matter"]["review"] if d["matter"] else None
        if d["outcome"] != E.AWAIT and rv is not None:
            g.env.advance(rv["window"] + 1)
    if with_acts:
        acts(g, eid, op_name, grantees, outsiders, exp, gm)


def acts(g, eid, op_name, grantees, outsiders, exp, gm):
    r = g.rng
    for _ in range(r.randint(3, 7)):
        k = r.choices(["act", "outsider", "outside_scope", "advance", "expire", "end", "end_out", "retry"],
                      weights=[30, 8, 8, 12, 12, 10, 6, 6])[0]
        who = r.choice(grantees)
        if k == "act" or k == "retry":
            op = ops_model.op_of(g.ops, op_name)
            args = pick_args(g.env, op, g.ch, who, "commit")
            rec, _v = g.step(who, {"kind": "act", "emergency": eid, "operation": op_name, "args": args})
            if k == "retry":
                g.retry(rec)
        elif k == "outsider" and outsiders:
            op = ops_model.op_of(g.ops, op_name)
            g.step(r.choice(outsiders), {"kind": "act", "emergency": eid, "operation": op_name,
                                         "args": pick_args(g.env, op, g.ch, who, "commit")})
        elif k == "outside_scope":
            other = [o["name"] for o in g.ops["operations"] if o["name"] != op_name]
            if other:
                op = ops_model.op_of(g.ops, r.choice(other))
                g.step(who, {"kind": "act", "emergency": eid, "operation": op["name"],
                             "args": pick_args(g.env, op, g.ch, who, "commit")})
        elif k == "advance":
            g.env.advance(r.randint(1, 3))
        elif k == "expire":
            g.env.advance(max(0, exp - g.tick() + r.choice([-1, 0, 0, 1])))
        elif k == "end":
            g.step(r.choice(gm), {"kind": "end", "emergency": eid})
        elif k == "end_out" and outsiders:
            g.step(r.choice(outsiders), {"kind": "end", "emergency": eid})


def noise_play(g):
    r = g.rng
    acts_ = [ordinary_governed, ordinary_free, ungoverned_propose, dup_case, unknown_case, bad_token, schema_junk,
             revoke_then_execute, mid_case_governance, crash_retry, idempotent_retry, exec_by_other, exec_by_other, order_fuzz]
    for f in r.sample(acts_, r.randint(2, 5)):
        f(g)


def ordinary_governed(g):
    req = g.pick_request(True)
    if req:
        who, op, args = req
        names = {t.name for t in g.env.dep.tools(g.env.token(who))} if hasattr(g.env.dep, "tools") else set()
        g.env.request(who, op, args, g.rid("q"), via="call_tool" if op in names and g.rng.random() < 0.5 else "direct")
        g.tags.add("request:DENIED:case_required")


def ordinary_free(g):
    req = g.pick_request(False)
    if req:
        who, op, args = req
        g.env.request(who, op, args, g.rid("q"), via="direct")


def ungoverned_propose(g):
    req = g.pick_request(False)
    if req:
        who, op, args = req
        g.step(who, {"kind": "propose", "case": f"u{g.i}-{g.n}", "operation": op, "args": args, "on_behalf_of": None})
        g.n += 1


def dup_case(g):
    if g.cases:
        cid = g.rng.choice(g.cases)
        c = g.M.case(cid)
        if c:
            g.step(c["requester"], {"kind": "propose", "case": cid, "operation": c["operation"], "args": c["args"],
                                    "on_behalf_of": None})


def unknown_case(g):
    who = g.rng.choice(g.principals())
    k = g.rng.choice(["judge", "appeal", "execute"])
    a = {"kind": k, "case": f"nope{g.i}-{g.n}"}
    if k == "judge":
        a |= {"stage": "decision", "value": "concur", "merit": g.merit()}
    g.step(who, a)


def bad_token(g):
    cid = g.rng.choice(g.cases) if g.cases else "zz"
    g.step(g.rng.choice(g.principals()), {"kind": "execute", "case": cid}, bad_token=True)


def schema_junk(g):
    who = g.rng.choice(g.principals())
    junk = [{"kind": "execute"}, {"kind": "execute", "case": "c", "extra": 1}, {"kind": "judge", "case": "c", "stage": "decision",
            "value": "uphold", "merit": "x"}, {"kind": "nope"}, {"kind": "propose", "case": "c", "operation": "x", "args": [],
            "on_behalf_of": None}, {"kind": "end", "emergency": 7}]
    g.step(who, g.rng.choice(junk))


def revoke_then_execute(g):
    live = [c for c in g.cases if g.M.case(c) and g.M.case(c)["executed"] is None]
    if not live:
        return
    c = g.M.case(g.rng.choice(live))
    spec = validate_strict(authority.revoke(g.env.auth, c["requester"], c["operation"]), g.ops)
    rec = g.env.set_authority(spec)
    if rec["status"] == "OK":
        g.ms += 1
        g.M = g.M.apply({"kind": "authority", "op": "set_authority", "payload": {"spec": spec}, "seq": g.ms, "tick": g.tick()})
    g.step(c["requester"], {"kind": "execute", "case": c["case"]})


def mid_case_governance(g):
    inst = {"doc": g.M.doc, "auth": g.env.auth, "ops": g.ops}
    if g.rng.random() < 0.4:
        bad, _name = gen_model.invalid_doc(inst, g.rng)
        g.env.set_governance(bad)  # must be refused; the judge flags invalid_doc_accepted otherwise
        return
    doc = gen_model.valid_variant(inst, g.rng)
    rec = g.env.set_governance(copy.deepcopy(doc))
    if rec["status"] == "OK" or not rec["raised"]:
        g.ms += 1
        g.M = g.M.apply({"kind": "set_governance", "doc": doc, "seq": g.ms, "tick": g.tick()})
        g.doc = doc
        if g.rng.random() < 0.7:
            plays_a.decision_play(g)  # exercise the new document (precedence ties, changed quorums)


def exec_by_other(g):
    live = [c for c in g.cases if g.M.case(c)]
    if not live:
        return
    cid = g.rng.choice(live)
    c = g.M.case(cid)
    vis = [p for p in g.principals() if p != c["requester"] and E.sees(g.M.doc, g.ops, c, p)]
    if vis:
        g.step(g.rng.choice(vis), {"kind": "execute", "case": cid})


def crash_retry(g):
    live = [c for c in g.cases if g.M.case(c)]
    if not live:
        return
    cid = g.rng.choice(live)
    who = g.rng.choice(plays_a.members(g, cid, "decision") or g.principals())
    a = {"kind": "judge", "case": cid, "stage": "decision", "value": "concur", "merit": g.merit()}
    rec, _ = g.step(who, a, crash=g.rng.choice(["before_commit", "after_commit"]))
    g.retry(rec)


def idempotent_retry(g):
    ok = [c for c in g.env.calls if c["kind"] == "constitutional" and c["status"] == "OK" and c.get("rid")]
    if ok:
        rec = g.rng.choice(ok)
        g.step(rec["actor"], rec["action"], rid=rec["rid"], replay=True)


def order_fuzz(g):
    """Check-order probes (C25-2): schema-valid actions on real/unknown cases by random principals with random fields,
    so that several checks of PROT-H25 s3 fail at once; the oracle names the first one."""
    r = g.rng
    cases = list(g.cases) + [f"nope{g.i}-{g.n}"]
    for _ in range(r.randint(3, 6)):
        k = r.choice(["judge", "judge", "appeal", "execute", "end", "act"])
        who = r.choice(g.principals())
        cid = r.choice(cases)
        if k == "judge":
            st = r.choice(["decision", "review"])
            a = {"kind": "judge", "case": cid, "stage": st, "value": r.choice(plays_a.VALUES[st] + ("abstain",)),
                 "merit": g.merit()}
        elif k in ("appeal", "execute"):
            a = {"kind": k, "case": cid}
        elif k == "end":
            a = {"kind": "end", "emergency": f"em{g.i}-{r.randint(0, 9)}"}
        else:
            ops = [o["name"] for o in g.ops["operations"]]
            a = {"kind": "act", "emergency": f"em{g.i}-{r.randint(0, 9)}", "operation": r.choice(ops), "args": {}}
        g.step(who, a, bad_token=r.random() < 0.05)
