"""Hypothesis strategies for referentially consistent IR packages.

``valid_packages()`` generates packages that pass ``eoo_ir.validate``; see
tests/h15/test_oracle_coverage.py for the table of what a run reaches. Mutation and rewrite
strategies live in ``mutations.py`` / ``rewrites.py`` and are re-exported here.
"""
from __future__ import annotations

from hypothesis import strategies as st

from .gen_atoms import atoms, bools, maybe_empty, metadata, texts
from .kinds import (AUTH_PREFIX, AUTHORITY_EFFECTS, DETERMINISM, EFFECT_OPERATIONS, IDEMPOTENCY, POLICY_DECISIONS,
                    POLICY_PREFIX, PRIMITIVES, PURITY, RESOURCE_ARRAYS, SEVERITIES, TRUTH_STATUS)
from .validate import READS_KINDS, Index


def _ulist(draw, lo: int, hi: int, exclude=frozenset(), empty_ok: bool = False) -> list[str]:
    a = maybe_empty(atoms()) if empty_ok else atoms()
    return draw(st.lists(a.filter(lambda x: x not in exclude), unique=True, min_size=lo, max_size=hi))


def _opt(draw, d: dict, key: str, strat) -> None:
    if draw(bools()):
        d[key] = draw(strat)


def _maybe_list(draw, strat, hi: int) -> list:
    return [] if strat is None else draw(st.lists(strat, max_size=hi))


def _ref_strategy(local: list[str], imports: list[str], prefix: str = ""):
    parts = []
    if local:
        parts.append(st.sampled_from(local).map(lambda x: prefix + x))
    if imports:
        parts.append(st.builds(lambda i, n: i + "#" + n, st.sampled_from(imports), atoms()))
    return st.one_of(*parts) if parts else None


def _type_expr(refs):
    base = st.sampled_from(PRIMITIVES)
    if refs is not None:
        base = st.one_of(base, refs.map(lambda r: {"ref": r}))
    return st.recursive(base, lambda c: st.one_of(c.map(lambda x: {"list": x}), c.map(lambda x: {"optional": x})), max_leaves=3)


def _props(draw, tx, lo: int = 0, hi: int = 3, names=None) -> list[dict]:
    names = names if names is not None else _ulist(draw, lo, hi)
    out = []
    for nm in names:
        p = {"name": nm, "type": draw(tx), "required": draw(bools())}
        _opt(draw, p, "immutable", bools())
        _opt(draw, p, "description", maybe_empty(texts()))
        _opt(draw, p, "constraints", st.lists(maybe_empty(texts()), max_size=2))
        out.append(p)
    return out


def _params(draw, tx) -> list[dict]:
    out = []
    for nm in _ulist(draw, 0, 3, empty_ok=True):  # parameter names have no minLength in the schema
        p = {"name": nm, "type": draw(tx)}
        _opt(draw, p, "required", bools())
        out.append(p)
    return out


def _cardinality(draw) -> dict:
    mx = draw(st.one_of(st.integers(1, 5), st.just("*")))
    mn = draw(st.integers(0, mx if isinstance(mx, int) else 3))
    return {"min": mn, "max": mx}


@st.composite
def valid_packages(draw, max_resources: int = 3):
    r = max_resources
    ot_ids = _ulist(draw, 0, r)
    if_ids = _ulist(draw, 0, max(r - 1, 1), exclude=set(ot_ids))
    imports = draw(st.lists(atoms(), max_size=2)) if draw(bools()) else []
    imp_decl = imports
    ep_refs = _ref_strategy(ot_ids + if_ids, imports)
    tx = _type_expr(ep_refs)

    objs = []
    for oid in ot_ids:
        props = _props(draw, tx, 1, 4)
        o = {"id": oid, "primary_key": draw(st.sampled_from([p["name"] for p in props])), "properties": props,
             "implements": _maybe_list(draw, _ref_strategy(if_ids, imports), 3)}
        _opt(draw, o, "description", maybe_empty(texts()))
        objs.append(o)

    links = []
    lids = _ulist(draw, 0, r) if ep_refs is not None else []
    if lids and ot_ids and draw(bools()) and ot_ids[0] not in lids:
        lids[0] = ot_ids[0]  # object type and link type sharing an id: refs that could mean either are ambiguous
    for lid in lids:
        lk = {"id": lid, "from": draw(ep_refs), "to": draw(ep_refs),
              "from_cardinality": _cardinality(draw), "to_cardinality": _cardinality(draw)}
        _opt(draw, lk, "directed", bools())
        _opt(draw, lk, "properties", st.just(None))
        if "properties" in lk:
            lk["properties"] = _props(draw, tx, 0, 2)
        links.append(lk)
    lt_ids = [x["id"] for x in links]

    ifaces = []
    for iid in if_ids:
        ifaces.append({"id": iid, "required_properties": _props(draw, tx, 0, 3),
                       "required_links": _maybe_list(draw, _ref_strategy(lt_ids, imports), 3),
                       "capabilities": draw(st.lists(maybe_empty(atoms()), max_size=3))})

    obs = []
    for oid in _ulist(draw, 0, r, empty_ok=True) if ot_ids or imports else []:
        sub = draw(_ref_strategy(ot_ids, imports))
        obs.append({"id": oid, "subject_type": sub, "properties": _props(draw, tx, 0, 3),
                    "source_binding": draw(maybe_empty(texts())), "truth_status": TRUTH_STATUS})
    ob_ids = [x["id"] for x in obs]

    pkg = {"package_id": draw(atoms()), "version": draw(atoms()), "object_types": objs, "link_types": links,
           "interfaces": ifaces, "functions": [], "actions": [], "policies": [], "authority_rules": [],
           "observation_types": obs, "constraints": []}
    if imports or draw(bools()):
        pkg["imports"] = imp_decl
    ix = Index({**pkg, "imports": imp_decl})

    def uniq(cands, kinds, **kw):
        return [c for c in cands if len(ix.resolve(c, kinds, **kw)) == 1]

    read_c = []
    for kind in READS_KINDS:
        for res in pkg[kind]:
            read_c.append(res["id"])
            read_c += [res["id"] + "." + p["name"] for p in res.get("properties", [])]
    reads_ref = _ref_strategy(sorted(set(uniq(read_c, READS_KINDS, allow_prop=True))), imports)

    for fid in _ulist(draw, 0, r):
        f = {"id": fid, "inputs": _params(draw, tx), "output": draw(tx), "purity": PURITY,
             "reads": _maybe_list(draw, reads_ref, 3), "implementation_ref": draw(texts())}
        _opt(draw, f, "determinism", st.sampled_from(DETERMINISM))
        pkg["functions"].append(f)

    pkg["policies"] = [{"id": i, "decision": draw(st.sampled_from(POLICY_DECISIONS)), "expression_ref": draw(maybe_empty(texts())),
                        "version": draw(maybe_empty(atoms()))} for i in _ulist(draw, 0, r, empty_ok=True)]
    pkg["authority_rules"] = []
    for i in _ulist(draw, 0, r, empty_ok=True):
        a = {"id": i, "principal_selector": draw(maybe_empty(texts())), "capability": draw(maybe_empty(texts())),
             "resource_selector": draw(maybe_empty(texts())), "effect": draw(st.sampled_from(AUTHORITY_EFFECTS))}
        _opt(draw, a, "delegation_allowed", bools())
        pkg["authority_rules"].append(a)
    pkg["constraints"] = [{"id": i, "scope": draw(maybe_empty(texts())), "expression_ref": draw(maybe_empty(texts())),
                           "severity": draw(st.sampled_from(SEVERITIES))} for i in _ulist(draw, 0, r, empty_ok=True)]

    ac_ids = _ulist(draw, 0, r)
    fn_ids = [x["id"] for x in pkg["functions"]]
    if fn_ids and ac_ids and draw(bools()) and fn_ids[0] not in ac_ids:
        ac_ids[0] = fn_ids[0]  # Function and Action sharing an id (distinct kinds) must stay distinguishable
    auth_ref = _ref_strategy([x["id"] for x in pkg["authority_rules"]], imports, AUTH_PREFIX)
    pol_ref = _ref_strategy([x["id"] for x in pkg["policies"]], imports, POLICY_PREFIX)
    comp_ref = _ref_strategy(ac_ids, imports)
    ot_u = uniq(ot_ids, ("object_types",))
    lt_u = uniq(lt_ids, ("link_types",))
    for aid in ac_ids:
        a = {"id": aid, "inputs": _params(draw, tx), "authority_refs": _maybe_list(draw, auth_ref, 3),
             "policy_refs": _maybe_list(draw, pol_ref, 3), "preconditions": draw(st.lists(maybe_empty(texts()), max_size=3)),
             "effects": [_effect(draw, ix, ot_u, lt_u, imports) for _ in range(draw(st.integers(1, 3)))],
             "idempotency": draw(st.sampled_from(IDEMPOTENCY)), "outcome_predicate": draw(texts()),
             "version": draw(atoms())}
        if draw(bools()):
            a["compensation_action"] = None if comp_ref is None or draw(bools()) else draw(comp_ref)
        pkg["actions"].append(a)

    if draw(bools()):
        pkg["domain_id"] = draw(atoms())
    if draw(bools()):
        pkg["metadata"] = draw(metadata())
    return pkg


def _effect(draw, ix: Index, ot_u: list[str], lt_u: list[str], imports: list[str]) -> dict:
    opts = [("external_call", None)]
    for op, ids, kind in (("create", ot_u, "object_types"), ("update", ot_u, "object_types"),
                          ("delete", ot_u, "object_types"), ("link", lt_u, "link_types"),
                          ("unlink", lt_u, "link_types")):
        if ids:
            opts.append((op, (ids, kind)))
    both = [i for i in ot_u + lt_u if len(ix.resolve(i, ("object_types", "link_types"))) == 1]
    if both:
        opts.append(("git_change", (both, None)))
    if imports:
        opts += [(op, ([], None)) for op in EFFECT_OPERATIONS if op != "external_call"]
    op, spec = draw(st.sampled_from(opts))
    e = {"operation": op}
    if spec is None:  # external_call: opaque system name, opaque field names
        e["target"] = draw(maybe_empty(atoms()))
        _opt(draw, e, "fields", st.lists(maybe_empty(atoms()), max_size=3))
        return e
    ids = spec[0]
    ext = _ref_strategy([], imports)
    tgt = st.one_of(*([st.sampled_from(ids)] if ids else []), *([ext] if ext is not None else []))
    e["target"] = draw(tgt)
    m = ix.resolve(e["target"], ("object_types", "link_types"))
    names = sorted(ix.props.get((m[0][0], m[0][1]), set())) if len(m) == 1 and m[0][0] != "import" else []
    if m and m[0][0] == "import":
        _opt(draw, e, "fields", st.lists(atoms(), max_size=3))
    elif names:
        _opt(draw, e, "fields", st.lists(st.sampled_from(names), max_size=3))
    elif draw(bools()):
        e["fields"] = []
    return e


from .mutations import single_mutation  # noqa: E402,F401
from .rewrites import allowed_rewrite  # noqa: E402,F401
