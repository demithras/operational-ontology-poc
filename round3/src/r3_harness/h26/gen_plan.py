"""Observation plans (PROT-H26 B2): the same list is executed in both worlds. Items are plain dicts; `m` is the channel."""
from __future__ import annotations

import copy

from r3_harness.h23.chooser import RandChooser
from r3_harness.h23.goodargs import random_args
from r3_oracle import authority, ops_model
from r3_oracle.disclosure import low_view

from . import sim
from .gen_vary import canary_key


def _pick(rng, xs, n):
    xs = sorted(xs)
    return xs if len(xs) <= n else sorted(rng.sample(xs, n))


def _typed_default(t: str):
    return {"integer": 1, "number": 1, "boolean": True}.get(t, "x")


def build_plan(rng, ops, auth, observer, snaps, hidden_refs, own_rids, hid_rids, hid_edges, hid_cases, n_d4=3):
    """snaps: the two predicted end-of-high-phase snapshots (list of 2). Returns (plan, d4_attempted, d4_replaced)."""
    s = snaps[0]
    lv = low_view(s, auth, observer, ops)
    vis = sorted(lv.objects)
    hid = sorted(set(r for r in s["objects"] if r not in lv.objects) | set(hidden_refs))
    never = [f"{t['name']}:{canary_key(rng)}" for t in rng.sample(ops["resource_types"], min(3, len(ops["resource_types"])))]
    refs = _pick(rng, vis, 5) + _pick(rng, hid, 6) + never
    plan = [{"m": "tools"}]
    plan += [{"m": "read_object", "ref": r} for r in refs]
    plan += [{"m": "list_objects", "type": t["name"]} for t in ops["resource_types"]] + [{"m": "list_objects", "type": "NoSuchType"}]
    lts = [l["name"] for l in ops["link_types"]]
    plan += [{"m": "list_links", "ref": r, "lt": rng.choice(lts)} for r in refs[:8]]
    for rd in ops["reads"]:
        rin = [i for i in rd["inputs"] if i["type"] == "resource"]
        for r in _pick(rng, vis + hid, 3):
            args = {i["name"]: (r.split(":", 1)[1] if i["type"] == "resource" else _typed_default(i["type"]))
                    for i in rd["inputs"]}  # G3-E20: bare keys; other args typed per the ops spec
            if rin and r.split(":", 1)[0] == rin[0]["resource_type"]:
                plan.append({"m": "query", "name": rd["name"], "args": args})
    plan.append({"m": "query", "name": rd_name(ops), "args": {}})
    plan.append({"m": "poll", "sub": 0})
    cur = [copy.deepcopy(x) for x in snaps]  # cumulative oracle pre-simulation: every accepted write is applied to both worlds
    state = {"tried": 0, "replaced": 0}  # tried = committing candidates (real D4 write attempts); replaced = rejected by the D4 rule

    def probe(op, args, rid, via, want_write):
        """Add a mutating probe iff it is safe under the oracle: a refused call is always safe; a committing call must have an
        equal outcome in both predicted worlds and keep them low-equivalent (D4, s2.4); otherwise it is replaced (counted)."""
        outs = [ops_model.evaluate(ops, auth, observer, None, op["name"], args, sn, 0, frozenset(), rid) for sn in cur]
        commits = [o.commits for o in outs]
        if not any(commits):
            if want_write:
                return False
            plan.append({"m": "mutate", "op": op["name"], "args": args, "rid": rid, "via": via, "kind": "unauth"})
            return True
        state["tried"] += 1
        if (outs[0].kind == outs[1].kind and len(outs[0].effects) == len(outs[1].effects) and all(commits)):
            nxt = [sim.apply_effects(sn, o.effects) for sn, o in zip(cur, outs)]
            if low_view(nxt[0], auth, observer, ops).to_doc() == low_view(nxt[1], auth, observer, ops).to_doc():
                cur[:] = nxt
                plan.append({"m": "mutate", "op": op["name"], "args": args, "rid": rid, "via": "direct", "kind": "d4"})
                own_rids.append(rid)
                return True
        state["replaced"] += 1
        return False

    for _ in range(4):  # unauthorized / hidden-naming probes
        op = rng.choice(ops["operations"])
        args = random_args(op, s, RandChooser(rng))
        for i in op["inputs"]:
            if i["type"] == "resource" and hid and rng.random() < 0.7:
                args[i["name"]] = rng.choice([h for h in hid if h.startswith(i["resource_type"] + ":")] or [f"{i['resource_type']}:x"]).split(":", 1)[1]
        probe(op, args, f"probe-{len(plan)}", rng.choice(["direct", "call_tool"]), False)
    for r in _pick(rng, hidden_refs, 3):  # targeted probes: name the varied hidden refs (error-detail channel)
        t, key = r.split(":", 1)
        for op in ops["operations"]:
            names = [i["name"] for i in op["inputs"] if i["type"] == "resource" and i["resource_type"] == t]
            if names:
                args = random_args(op, s, RandChooser(rng))
                args[names[0]] = key
                probe(op, args, f"tp-{len(plan)}", "direct", False)
                break
    ops_ok = [o for o in ops["operations"] if authority.could_ever_allow(observer, o["name"], auth)]
    for k in range(n_d4):  # authorised D4 probes
        if not ops_ok:
            break
        for _ in range(12):
            op = rng.choice(ops_ok)
            if probe(op, random_args(op, cur[0], RandChooser(rng)), f"d4-{k}", "direct", True):
                break
    tried, replaced = state["tried"], state["replaced"]
    for eid in hid_edges:
        plan.append({"m": "delegate", "edge": {"id": f"mine-{eid}", "issuer": observer, "child": observer, "parent": eid,
                                               "scope": {"operations": [], "resources": []}, "expires_at": None,
                                               "redelegable": False, "issued_at": 0}, "rid": f"dl-{eid}"})
        plan.append({"m": "revoke", "edge_id": eid, "rid": f"rv-{eid}"})
    for c in hid_cases:
        plan.append({"m": "constitutional", "rid": f"cj-{c}",
                     "action": {"kind": "judge", "case": c, "stage": "decision", "value": "concur", "merit": "x"}})
    for did in _pick(rng, own_rids + hid_rids, 8) + ["unknown-1"]:
        plan += [{"m": "prov_decision", "id": did}, {"m": "authority_used_as", "rid": did}]
    plan += [{"m": "prov_object", "ref": r} for r in _pick(rng, vis + hid, 4)]
    plan.append({"m": "poll", "sub": 0})
    return plan, tried, replaced


def rd_name(ops) -> str:
    return "no_such_query"
