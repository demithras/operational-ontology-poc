"""Variation builders: each returns (delta_w1, delta_w2) of EQUAL SHAPE (same number of seed batches, same change counts,
same number of high calls) so both worlds keep an identical seq/tick schedule (D2). A delta is
{"batches": [[change...]], "high": [{"actor","op","args","rid"}], "edges": [edge], "cases": [{"actor","action","rid"}]}.
Each builder returns None when the world offers no candidate (the generator then re-draws)."""
from __future__ import annotations

import random

from r3_harness.h23.chooser import RandChooser
from r3_harness.h23.goodargs import random_args
from r3_oracle import authority, ops_model
from r3_oracle.disclosure_reads import CANARY_INT_MIN

KINDS = ("F", "E", "L", "D", "C", "G")


def empty() -> dict:
    return {"batches": [], "high": [], "edges": [], "cases": []}


def canary_str(rng) -> str:
    return f"cv-{rng.getrandbits(48):012x}"


def canary_key(rng) -> str:
    return f"ck-{rng.getrandbits(32):08x}"


def canary_int(rng) -> int:
    return CANARY_INT_MIN + rng.randrange(10 ** 6)


def _kf(ops, t):
    return next(x for x in ops["resource_types"] if x["name"] == t)


def _effects(ops):
    return [e for op in ops["operations"] for e in op["effects"]]


def store_managed(ops) -> bool:
    """True when some operation writes the store itself (create/update/link/unlink effects). In a domain whose operations
    are all external (manufacturing: WMS/ERP/MES own the data) the store mirrors external systems and any in-type value is
    an observable external state; invariants already bound it."""
    return any(e["kind"] in ("create", "update", "link", "unlink") for e in _effects(ops))


def reachable_link_types(ops) -> set:
    """Link types some operation creates (kind link) or removes (kind unlink) - derived from the ops spec (G3-E30)."""
    return {e["link_type"] for e in _effects(ops) if e["kind"] in ("link", "unlink")}


def updatable_fields(ops) -> set:
    """(type, field) pairs written by an update effect (an existing object's field can only change that way). A field
    co-written with a literal lifecycle value (e.g. freeze_hash with phase=PREREGISTERED) is written once, at the
    transition, so an object that already holds it cannot be re-written: excluded."""
    return {(e["type"], f) for e in _effects(ops) if e["kind"] == "update" and not any("lit" in v for v in (e.get("props") or {}).values()
                                                                                      if isinstance(v, dict) and not isinstance(v.get("lit"), bool))
            for f in (e.get("props") or {})}


def kind_feasible(ops, kind: str) -> bool:
    if kind == "L":
        return bool(reachable_link_types(ops))
    if kind == "F":
        return not store_managed(ops) or any(
            f["type"] in ("string", "integer") and not f.get("enum") and not f.get("immutable") and (t["name"], f["name"]) in updatable_fields(ops)
            for t in ops["resource_types"] for f in t["fields"])
    return True


def creatable(ops) -> dict:
    """type -> {field: effect value expr} of the create effects; hidden creations may only carry these fields."""
    out: dict = {}
    for e in _effects(ops):
        if e["kind"] == "create":
            out.setdefault(e["type"], {}).update(e.get("props") or {})
    return out


def vary_F(rng, ops, lv, snap):
    managed, upd = store_managed(ops), updatable_fields(ops)
    cand = []
    for ref, props in snap["objects"].items():
        t = ref.split(":", 1)[0]
        hid = [f["name"] for f in _kf(ops, t)["fields"] if f["name"] in props["props"]
               and f["name"] not in lv.objects.get(ref, {}) and not f.get("enum") and not f.get("immutable")
               and f["type"] in ("string", "integer") and (not managed or (t, f["name"]) in upd)]
        cand += [(ref, f, props["props"][f]) for f in hid]
    if not cand:
        return None
    ref, f, cur = rng.choice(sorted(cand, key=str))
    t, k = ref.split(":", 1)
    mk = (lambda: canary_int(rng)) if isinstance(cur, int) else (lambda: canary_str(rng))
    a, b = mk(), mk()
    while b == a:
        b = mk()
    mkd = lambda v: {**empty(), "batches": [[{"op": "update", "type": t, "key": k, "props": {f: v}}]]}  # noqa: E731
    return mkd(a), mkd(b), {"ref": ref, "field": f, "canaries": [a, b]}


def vary_E(rng, ops, lv, snap):
    managed, cr = store_managed(ops), creatable(ops)
    hidden = sorted(r for r in snap["objects"] if r not in lv.objects and (not managed or r.split(":", 1)[0] in cr))
    if not hidden:
        return None
    ref = rng.choice(hidden)
    t, k = ref.split(":", 1)
    td = _kf(ops, t)
    props = snap["objects"][ref]["props"]
    if managed:  # only fields the creating operation writes; literal-valued ones take the literal (e.g. phase DRAFT)
        props = {f: (cr[t][f]["lit"] if "lit" in cr[t].get(f, {}) else v)
                 for f, v in props.items() if f in cr[t] or f == td["key_field"]}
    cands = [f["name"] for f in td["fields"] if f["type"] == "string" and f["name"] != td["key_field"]
             and not f.get("enum") and f["name"] in props and (not managed or "lit" not in cr[t].get(f["name"], {}))]
    out, keys, cans = [], [canary_key(rng), canary_key(rng)], []
    for key in keys:
        p = dict(props)
        p[td["key_field"]] = key
        if cands:
            p[cands[0]] = canary_str(rng)
            cans.append(p[cands[0]])
        out.append({**empty(), "batches": [[{"op": "create", "type": t, "key": key, "props": p}]]})
    return out[0], out[1], {"ref": ref, "keys": [f"{t}:{k_}" for k_ in keys], "canaries": keys + cans}


def vary_L(rng, ops, lv, snap):
    """Link presence: w1 links (s1, d1), w2 links (s2, d2); both pairs are unlinked in the base and at least one endpoint is
    hidden from the observer, so the link itself is invisible. Equal batch shape (one link each)."""
    ok = reachable_link_types(ops)
    lts = [x for x in ops["link_types"] if x["name"] in ok]  # G3-E30: only link types some operation creates/removes
    rng.shuffle(lts)
    for l in lts:
        src = sorted(r for r in snap["objects"] if r.split(":", 1)[0] in (l.get("from_types") or [l["from"]]))
        dst = sorted(r for r in snap["objects"] if r.split(":", 1)[0] in (l.get("to_types") or [l["to"]]))
        cands = [(s_, d_) for s_ in src for d_ in dst if [l["name"], s_, d_] not in snap["links"]
                 and (s_ not in lv.objects or d_ not in lv.objects)]
        if len(cands) < 2:
            continue
        (s1, d1), (s2, d2) = rng.sample(cands, 2)
        mk = lambda s_, d_: {**empty(), "batches": [[{"op": "link", "link_type": l["name"], "src": s_, "dst": d_}]]}  # noqa: E731
        return mk(s1, d1), mk(s2, d2), {"link": [l["name"], s1, s2], "dsts": [d1, d2]}
    return None

def vary_D(rng, ops, auth, lv, snap, observer, n):
    """Hidden decisions. Mode "swap" (60% when a scalars-level resource exists): the SAME op/args are run by two different
    hidden actors on a resource the observer sees at provenance level `scalars`, so the observer may see the decision but
    never its actors (this is what the actor-redaction mutants break). Mode "args": different args/targets."""
    hs = [p["id"] for p in auth["principals"] if p["id"] != observer and p["delegated_by"] is None]
    scal = sorted(r for r, lvl in lv.prov.items() if lvl == "scalars")
    want_swap = bool(scal) and rng.random() < 0.8 and len(hs) >= 2
    for attempt in range(60):
        op = rng.choice(ops["operations"])
        swap = want_swap and attempt < 30
        rid = f"hid-{n}"
        if swap:
            args = random_args(op, snap, RandChooser(rng))
            names = [i for i in op["inputs"] if i["type"] == "resource" and any(r.startswith(i["resource_type"] + ":") for r in scal)]
            if not names:
                continue
            for i in names:
                args[i["name"]] = rng.choice([r for r in scal if r.startswith(i["resource_type"] + ":")]).split(":", 1)[1]
            h1, h2 = rng.sample(hs, 2)
            os_ = [ops_model.evaluate(ops, auth, h, None, op["name"], args, snap, 0, frozenset(), None) for h in (h1, h2)]
            if not (os_[0].commits and os_[1].commits) or os_[0].effects != os_[1].effects:
                continue
            mk = lambda h: {**empty(), "high": [{"actor": h, "op": op["name"], "args": args, "rid": rid}]}  # noqa: E731
            return mk(h1), mk(h2), {"actor": [h1, h2], "op": op["name"], "rid": rid, "args": [args, args], "mode": "swap"}
        h = rng.choice(hs)
        outs = []
        val = bool(scal) and attempt >= 30 and rng.random() < 0.7  # "valdiff": same actor + visible scalars-level resource, different values
        for _w in (0, 1):
            args = random_args(op, snap, RandChooser(rng))
            if val:
                for i in op["inputs"]:
                    pool = [r for r in scal if i["type"] == "resource" and r.startswith(i["resource_type"] + ":")]
                    if pool:
                        args[i["name"]] = pool[0].split(":", 1)[1]
            o = ops_model.evaluate(ops, auth, h, None, op["name"], args, snap, 0, frozenset(), None)
            outs.append((args, o))
        (a1, o1), (a2, o2) = outs
        if a1 == a2 or not (o1.commits and o2.commits) or len(o1.effects) != len(o2.effects):
            continue
        mk = lambda a: {**empty(), "high": [{"actor": h, "op": op["name"], "args": a, "rid": rid}]}  # noqa: E731
        return mk(a1), mk(a2), {"actor": h, "op": op["name"], "rid": rid, "args": [a1, a2], "mode": "valdiff" if val else "args"}
    return None


def vary_C(rng, ops, auth, lv, snap, observer, n):
    pl = [p["id"] for p in auth["principals"] if p["delegated_by"] is None]
    for _ in range(20):
        iss = rng.choice(pl)
        ch = rng.sample([p for p in pl if p != iss and p != observer], 2) if len(pl) > 3 else None
        if ch is None or iss == observer:
            continue
        allowed = [o["name"] for o in ops["operations"] if authority.could_ever_allow(iss, o["name"], auth)]
        if not allowed:
            continue
        opn = rng.choice(allowed)
        mk = lambda c: {**empty(), "edges": [{"id": f"hedge-{n}", "issuer": iss, "child": c, "parent": None,  # noqa: E731
                                                "scope": {"operations": [opn], "resources": [{"type": ops["resource_types"][0]["name"], "keys": None}]},
                                                "expires_at": None, "redelegable": False, "issued_at": 0}]}
        return mk(ch[0]), mk(ch[1]), {"edge": f"hedge-{n}", "issuer": iss, "children": ch, "op": opn}
    return None


def _case_arg(rng, i, snap):
    if i["type"] == "string":
        return canary_str(rng)
    if i["type"] == "integer":
        return canary_int(rng)
    if i["type"] == "resource" and snap:
        keys = sorted(r.split(":", 1)[1] for r in snap["objects"] if r.startswith(i["resource_type"] + ":"))
        return rng.choice(keys) if keys else canary_key(rng)
    return canary_str(rng)


def vary_G(rng, ops, auth, gov, observer, n, snap=None):
    if gov is None:
        return None
    members = {m for b in gov["bodies"] for m in b["members"]}
    reqs = [p["id"] for p in auth["principals"] if p["id"] != observer and p["delegated_by"] is None]
    if observer in members or not reqs:
        return None
    op = rng.choice(ops["operations"])
    mk = lambda tag: {**empty(), "cases": [{"actor": reqs[0], "rid": f"hcase-{n}", "action": {  # noqa: E731
        "kind": "propose", "case": f"hcase-{n}", "operation": op["name"],
        "args": {i["name"]: _case_arg(rng, i, snap) for i in op["inputs"] if i["required"]},
        "on_behalf_of": None}}]}
    return mk(0), mk(1), {"case": f"hcase-{n}", "requester": reqs[0], "members": sorted(members)}
