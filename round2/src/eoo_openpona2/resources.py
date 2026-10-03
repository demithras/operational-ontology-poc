"""Resource bodies: object/link/interface/function/action/policy/authority/observation/constraint."""
from __future__ import annotations

from eoo_ir.kinds import AUTH_PREFIX, POLICY_PREFIX
from eoo_ir.validate import READS_KINDS

from .ctx import _ABSENT, EFFECT_KINDS, ENDPOINT, _C
from .errors import Ambiguous


def _opt(c: _C, out: dict, k: tuple, f: str) -> None:
    v = c.one(k, f, required=False)
    if v is not _ABSENT:
        out[f] = v


def _effect(c: _C, k: tuple, path: str) -> dict:
    op = c.one(k, "op")
    tgt = c.one(k, "target")
    e: dict = {}
    if op == "external_call":
        e["target"] = tgt[1]  # opaque system name
    else:
        e["target"] = c.ref(tgt, EFFECT_KINDS[op], path=path + ".target")
    e["operation"] = op
    flds, empty = c.raw(k, "fields"), c.all(k, "fields_empty")
    if flds and empty or len(empty) > 1:
        raise Ambiguous("conflict:fields", f"effect {k[1:]} states both empty and listed fields")
    if empty:
        e["fields"] = []
    elif flds:
        local = tgt[0] == "res"
        owner = ("res", tgt[1], tgt[2]) if local else None
        e["fields"] = [c.own_prop(owner, v, path + ".fields") if local else v for _, v in flds]
    return e


def _action(c: _C, k: tuple, path: str) -> dict:
    out = {"id": k[2], "inputs": c.params(k, path + ".inputs"),
           "authority_refs": [c.ref(r, ("authority_rules",), AUTH_PREFIX, path=path + ".authority_refs")
                              for r in c.all(k, "authority_refs")],
           "policy_refs": [c.ref(r, ("policies",), POLICY_PREFIX, path=path + ".policy_refs")
                           for r in c.all(k, "policy_refs")],
           "preconditions": c.all(k, "preconditions"),
           "effects": [_effect(c, e, f"{path}.effects[{i}]") for i, e in enumerate(c.children(k, "effects"))],
           "idempotency": c.one(k, "idempotency"), "outcome_predicate": c.one(k, "outcome_predicate")}
    ca = c.one(k, "compensation_action", required=False)
    if ca is not _ABSENT:
        out["compensation_action"] = None if ca is None else c.ref(ca, ("actions",), path=path + ".compensation_action")
    out["version"] = c.one(k, "version")
    return out


def _resource(c: _C, kind: str, k: tuple, path: str) -> dict:
    rid = k[2]
    if kind == "object_types":
        o = {"id": rid}
        o["primary_key"] = c.own_prop(k, c.one(k, "primary_key"), path + ".primary_key")
        o["properties"] = c.props(k, path + ".properties")
        o["implements"] = [c.ref(r, ("interfaces",), path=path + ".implements") for r in c.all(k, "implements")]
        _opt(c, o, k, "description")
        return o
    if kind == "link_types":
        to, frm = c.one(k, "ends")
        lk = {"id": rid, "from": c.ref(frm, ENDPOINT, path=path + ".from"), "to": c.ref(to, ENDPOINT, path=path + ".to"),
              "from_cardinality": c.card(k, "from"), "to_cardinality": c.card(k, "to")}
        _opt(c, lk, k, "directed")
        ps, empty = c.children(k, "props"), c.all(k, "props_empty")
        if ps and empty or len(empty) > 1:
            raise Ambiguous("conflict:properties", f"{k[1:]} states both empty and listed properties")
        if empty:
            lk["properties"] = []
        elif ps:
            lk["properties"] = c.props(k, path + ".properties")
        return lk
    if kind == "interfaces":
        return {"id": rid, "required_properties": c.props(k, path + ".required_properties"),
                "required_links": [c.ref(r, ("link_types",), path=path + ".required_links")
                                   for r in c.all(k, "required_links")],
                "capabilities": c.all(k, "capabilities")}
    if kind == "functions":
        f = {"id": rid, "inputs": c.params(k, path + ".inputs"), "output": c.type_(c.one(k, "output"), path + ".output"),
             "purity": c.one(k, "purity"),
             "reads": [c.ref(r, READS_KINDS, allow_prop=True, path=path + ".reads") for r in c.all(k, "reads")],
             "implementation_ref": c.one(k, "implementation_ref")}
        _opt(c, f, k, "determinism")
        return f
    if kind == "actions":
        return _action(c, k, path)
    if kind == "policies":
        return {"id": rid, "decision": c.one(k, "decision"), "expression_ref": c.one(k, "expression_ref"),
                "version": c.one(k, "version")}
    if kind == "authority_rules":
        r = {"id": rid}
        for f in ("principal_selector", "capability", "resource_selector", "effect"):
            r[f] = c.one(k, f)
        _opt(c, r, k, "delegation_allowed")
        return r
    if kind == "observation_types":
        return {"id": rid, "subject_type": c.ref(c.one(k, "subject_type"), ("object_types",), path=path + ".subject_type"),
                "properties": c.props(k, path + ".properties"), "source_binding": c.one(k, "source_binding"),
                "truth_status": c.one(k, "truth_status")}
    return {"id": rid, "scope": c.one(k, "scope"), "expression_ref": c.one(k, "expression_ref"),
            "severity": c.one(k, "severity")}
