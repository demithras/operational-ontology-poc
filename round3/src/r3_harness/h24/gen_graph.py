"""A2 authority-DAG generator (seeded; never calls a variant). make_world() builds the v2 authority document for one
sequence (fixture + 6-14 fresh principals + neutral-extension delegable grants, validated with validate_strict);
plan_edges() emits ordered delegate steps: legal chains depth 1..8 (>= 25% target depth >= 4), fan-out up to 3, principals
reachable by several paths, scopes as subsets, plus intent-tagged illegal attempts (widening, cycle, static mixing,
depth overflow, duplicate id, unknown parent/principal, non-holder, non-redelegable, already expired)."""
from __future__ import annotations

import copy

from r3_oracle import authority
from r3_shared.authspec import validate_strict

MAXD = 8
ILLEGAL = ("extra_op", "extra_key", "keys_null", "later_expiry", "cycle", "static", "depth", "dup_id", "unknown_parent",
           "not_holder", "not_redelegable", "unknown_principal", "expired")


def op_types(ops: dict, name: str) -> list[str]:
    o = next(o for o in ops["operations"] if o["name"] == name)
    return sorted({i["resource_type"] for i in o["inputs"] if i["type"] == "resource"})


def seed_keys(ops: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for o in ops["seed"]["objects"]:
        out.setdefault(o["type"], []).append(o["key"])
    return out


def make_world(ops: dict, auth1: dict, rng) -> tuple[dict, dict]:
    """-> (v2 authority document, info {holders: {pid: [ops it can base-do]}, leaves: [pid], static: [pid]})."""
    spec = copy.deepcopy(auth1)
    spec.update({"spec": "r3-authority-2", "max_delegation_depth": MAXD, "capabilities": [], "revoked": []})
    spec.pop("delegation_note", None)
    names = [o["name"] for o in ops["operations"]]
    humans = [p for p in spec["principals"] if p["delegated_by"] is None and p["kind"] == "human"]
    templates = [p for p in humans if sum(authority.could_ever_allow(p["id"], n, spec) for n in names) >= 1]
    holders, leaves = {}, []
    for i in range(rng.randint(6, 14)):
        pid = f"dp-{i}"
        if rng.random() < 0.45:
            t = rng.choice(templates)
            spec["principals"].append({"id": pid, "kind": "human", "roles": list(t["roles"]),
                                       "relations": copy.deepcopy(t["relations"]), "delegated_by": None})
        else:
            spec["principals"].append({"id": pid, "kind": "agent", "roles": [], "relations": [], "delegated_by": None})
            leaves.append(pid)
    for p in spec["principals"]:
        if p["delegated_by"] is None and p["kind"] == "human":
            can = [n for n in names if authority.could_ever_allow(p["id"], n, spec)]
            if can:
                holders[p["id"]] = can
    for pid, can in sorted(holders.items()):
        for n in can:
            if rng.random() < 0.8:  # some ops stay non-delegable: root-edge widening attempts target those
                spec["grants"].append({"id": f"g24-{pid}-{n}", "effect": "allow", "principal": {"id": pid},
                                       "resource": {"any": True}, "operation": n, "delegable": True,
                                       "origin": "neutral-extension"})
    validate_strict(spec, ops)
    static = [p["id"] for p in spec["principals"] if p["delegated_by"] is not None]
    deleg = {pid: [g["operation"] for g in spec["grants"] if g["id"].startswith(f"g24-{pid}-")] for pid in holders}
    return spec, {"holders": {p: o for p, o in deleg.items() if o}, "leaves": leaves, "static": static}


def _scope(ops, op_names, rng, parent=None):
    """Legal scope: for a root, any subset; for a child, a syntactic subset of `parent`."""
    keys = seed_keys(ops)
    pool = sorted(parent["operations"]) if parent else op_names
    chosen = sorted(rng.sample(pool, rng.randint(1, min(3, len(pool)))))
    types = sorted({t for n in chosen for t in op_types(ops, n)})
    res = []
    for t in types:
        pk = None
        if parent:
            pe = next((e for e in parent["resources"] if e["type"] == t), None)
            pk = pe["keys"] if pe else []
        allk = keys.get(t, [])
        if pk is None or pk == []:
            ks = None if (pk is None and rng.random() < 0.5) else rng.sample(allk, rng.randint(1, min(3, len(allk))))
        else:
            ks = rng.sample(pk, rng.randint(1, len(pk)))
        res.append({"type": t, "keys": sorted(ks) if ks is not None else None})
    return {"operations": chosen, "resources": res}


def _expiry(rng, now, parent_exp, parent_exists):
    if not parent_exists or parent_exp is None:
        return None if rng.random() < 0.5 else now + rng.randint(12, 200)
    return rng.randint(now + 1, parent_exp)


def plan_edges(ops: dict, world: dict, info: dict, rng, now: int, budget: int, force_deep: bool = False) -> list[dict]:
    """Ordered delegate steps {kind, edge, intent}. Fresh edge ids e<k>. Legal edges assume the variant accepts them."""
    steps, k, edges = [], [0], []

    def new_id():
        k[0] += 1
        return f"e{k[0]}"

    roots = sorted(info["holders"])
    names = [o["name"] for o in ops["operations"]]
    pool = [p["id"] for p in world["principals"] if p["delegated_by"] is None]
    while len(edges) < budget:
        root = rng.choice(roots)
        sc = _scope(ops, info["holders"][root], rng)
        depth_target = MAXD if (force_deep and not edges) else (rng.randint(4, MAXD) if rng.random() < 0.45 else rng.randint(1, 3))
        parent, issuer, chain_issuers = None, root, [root]
        for d in range(depth_target):
            cands = [p for p in pool if p not in chain_issuers]
            child = rng.choice(cands)
            e = {"id": new_id(), "issuer": issuer, "child": child, "parent": parent["id"] if parent else None,
                 "scope": sc if parent is None else _scope(ops, names, rng, parent["scope"]),
                 "expires_at": _expiry(rng, now, parent["expires_at"] if parent else None, parent is not None),
                 "redelegable": d < depth_target - 1 or rng.random() < 0.3, "issued_at": now}
            steps.append({"kind": "delegate", "edge": e, "intent": "legal", "depth": d + 1})
            edges.append(e)
            if rng.random() < 0.3 and len(edges) < budget:  # fan-out: a sibling edge from the same parent
                sib = rng.choice([p for p in pool if p not in chain_issuers and p != child] or [child])
                e2 = {**copy.deepcopy(e), "id": new_id(), "child": sib}
                if sib != child:
                    steps.append({"kind": "delegate", "edge": e2, "intent": "legal", "depth": d + 1})
                    edges.append(e2)
            if force_deep and d + 1 == MAXD:
                steps += _illegal(rng, ops, info, e, parent, edges, names, now, new_id, pool, kind="depth")
            elif rng.random() < (0.2 if parent is not None else 0.08):
                steps += _illegal(rng, ops, info, e, parent, edges, names, now, new_id, pool)
            if not e["redelegable"]:
                break
            parent, issuer = e, child
            chain_issuers.append(child)
    return steps


def _illegal(rng, ops, info, e, parent, edges, names, now, new_id, pool, kind=None) -> list[dict]:
    kind = kind or rng.choice(ILLEGAL)
    c = copy.deepcopy(e)
    c["id"] = new_id()
    pscope = parent["scope"] if parent else None
    if kind == "extra_op":
        if parent is not None:
            extra = [n for n in names if n not in pscope["operations"]]
        else:
            extra = [n for n in names if n not in info["holders"].get(e["issuer"], [])]
        if not extra:
            return []
        n = rng.choice(extra)
        c["scope"]["operations"] = sorted(c["scope"]["operations"] + [n])
        for t in op_types(ops, n):
            if not any(r["type"] == t for r in c["scope"]["resources"]):
                c["scope"]["resources"].append({"type": t, "keys": None})
    elif kind in ("extra_key", "keys_null"):
        if parent is None:
            return []
        ent = [r for r in pscope["resources"] if r["keys"] is not None]
        if not ent:
            return []
        t = rng.choice(ent)["type"]
        cr = next((r for r in c["scope"]["resources"] if r["type"] == t), None)
        if cr is None:
            return []
        if kind == "keys_null":
            cr["keys"] = None
        else:
            extra = [x for x in seed_keys(ops).get(t, []) if x not in next(r for r in pscope["resources"] if r["type"] == t)["keys"]]
            if not extra:
                return []
            cr["keys"] = sorted((cr["keys"] or []) + [rng.choice(extra)])
    elif kind == "later_expiry":
        if parent is None or parent["expires_at"] is None:
            return []
        c["expires_at"] = rng.choice([None, parent["expires_at"] + rng.randint(1, 50)])
    elif kind == "cycle":
        ancestors = [x["issuer"] for x in _ancestors(edges, e)]
        if not ancestors:
            return []
        c["issuer"], c["child"], c["parent"] = e["child"], rng.choice(ancestors), e["id"]
        c["scope"], c["expires_at"] = _scope(ops, names, rng, e["scope"]), e["expires_at"]
    elif kind == "static":
        if not info["static"]:
            return []
        c["child"] = rng.choice(info["static"])
    elif kind == "depth":
        anc = _ancestors(edges, e)
        free = [p for p in pool if p not in {x["issuer"] for x in anc} | {e["child"]}]
        if len(anc) != MAXD or not free:
            return []
        c["issuer"], c["child"], c["parent"] = e["child"], rng.choice(free), e["id"]
        c["scope"], c["expires_at"] = _scope(ops, names, rng, e["scope"]), e["expires_at"]
    elif kind == "dup_id":
        c["id"] = rng.choice(edges)["id"]
    elif kind == "unknown_parent":
        c["parent"] = "e-missing"
    elif kind == "not_holder":
        taken = {e["child"], e["issuer"]} | ({parent["child"]} if parent else set())
        others = [p for p in info["leaves"] if p not in taken]
        if not others:
            return []
        c["issuer"] = rng.choice(others)
    elif kind == "not_redelegable":
        free = [p for p in pool if p not in {x["issuer"] for x in _ancestors(edges, e)} | {e["child"]}]
        if e["redelegable"] or not free:
            return []
        c["issuer"], c["child"], c["parent"] = e["child"], rng.choice(free), e["id"]
    elif kind == "unknown_principal":
        c["child"] = "ghost-1"
    elif kind == "expired":
        c["expires_at"] = now
    return [{"kind": "delegate", "edge": c, "intent": f"illegal:{kind}", "depth": None}]


def _ancestors(edges, e):
    by, out, cur = {x["id"]: x for x in edges}, [], e
    while cur is not None:
        out.append(cur)
        cur = by.get(cur["parent"])
    return out[::-1]
