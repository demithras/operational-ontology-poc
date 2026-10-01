"""Resource bodies: object/link/interface/function/action/policy/authority/observation/constraint."""
from __future__ import annotations

from eoo_ir.kinds import AUTH_PREFIX, POLICY_PREFIX
from eoo_ir.validate import READS_KINDS

from .ctx import _ABSENT, EFFECT_KINDS, ENDPOINT, _C
from .errors import Ambiguous, Invalid


def _opt(c: _C, out: dict, a: str, f: str) -> None:
    v = c.one(a, f, required=False)
    if v is not _ABSENT:
        out[f] = v


def _effect(c: _C, a: str, path: str) -> dict:
    op = c.one(a, "op")
    op_line = c.line(c.raw(a, "op")[0][0])
    e: dict = {}
    target_addr = None
    if op == "external_call":
        e["target"] = c.rec[f"L{op_line.lineno}.a1"]  # opaque system name (Gate-0 ruling 2)
    else:
        target_addr = next(v[1] for v in op_line.slots if v[0] == "ref")
        e["target"] = c.ref(target_addr, EFFECT_KINDS[op], path=path + ".target")
    e["operation"] = op
    flds, empty = c.raw(a, "fields"), c.all(a, "fields_empty")
    if flds and empty or len(empty) > 1:
        raise Ambiguous("conflict:fields", f"{a!r} states both empty and listed fields")
    if empty:
        e["fields"] = []
    elif flds:
        local = target_addr is not None and c.decl(target_addr).what != "external"
        out = []
        for lineno, v in flds:
            if local != (c.line(lineno).tid == "eff.field"):
                raise Invalid("reference_role", f"{path}.fields: a {'local' if local else 'external/imported'} "
                              f"target needs {'property addresses' if local else 'opaque atoms (sona ni)'}", lineno)
            out.append(c.own_prop(v, target_addr, path + ".fields") if local else v)
        e["fields"] = out
    return e


def _action(c: _C, a: str, path: str) -> dict:
    out = {"id": c.decl(a).atom, "inputs": c.params(a, path + ".inputs"),
           "authority_refs": [c.ref(r, ("authority_rules",), AUTH_PREFIX, path=path + ".authority_refs")
                              for r in c.all(a, "authority_refs")],
           "policy_refs": [c.ref(r, ("policies",), POLICY_PREFIX, path=path + ".policy_refs")
                           for r in c.all(a, "policy_refs")],
           "preconditions": c.all(a, "preconditions"),
           "effects": [_effect(c, e, f"{path}.effects[{i}]") for i, e in enumerate(c.children(a, "effect"))],
           "idempotency": c.one(a, "idempotency"), "outcome_predicate": c.one(a, "outcome_predicate")}
    ca = c.one(a, "compensation_action", required=False)
    if ca is not _ABSENT:
        out["compensation_action"] = None if ca is None else c.ref(ca, ("actions",), path=path + ".compensation_action")
    out["version"] = c.one(a, "version")
    return out


def _resource(c: _C, kind: str, a: str, path: str) -> dict:
    rid = c.decl(a).atom
    if kind == "object_types":
        o = {"id": rid}
        o["primary_key"] = c.own_prop(c.one(a, "primary_key"), a, path + ".primary_key")
        o["properties"] = c.props(a, path + ".properties")
        o["implements"] = [c.ref(r, ("interfaces",), path=path + ".implements") for r in c.all(a, "implements")]
        _opt(c, o, a, "description")
        return o
    if kind == "link_types":
        to, frm = c.one(a, "ends")
        lk = {"id": rid, "from": c.ref(frm, ENDPOINT, path=path + ".from"), "to": c.ref(to, ENDPOINT, path=path + ".to"),
              "from_cardinality": c.card(a, "from"), "to_cardinality": c.card(a, "to")}
        _opt(c, lk, a, "directed")
        ps, empty = c.children(a, "property"), c.all(a, "props_empty")
        if ps and empty or len(empty) > 1:
            raise Ambiguous("conflict:properties", f"{a!r} states both empty and listed properties")
        if empty:
            lk["properties"] = []
        elif ps:
            lk["properties"] = c.props(a, path + ".properties")
        return lk
    if kind == "interfaces":
        return {"id": rid, "required_properties": c.props(a, path + ".required_properties"),
                "required_links": [c.ref(r, ("link_types",), path=path + ".required_links")
                                   for r in c.all(a, "required_links")],
                "capabilities": c.all(a, "capabilities")}
    if kind == "functions":
        f = {"id": rid, "inputs": c.params(a, path + ".inputs"), "output": c.type_(c.one(a, "output"), path + ".output"),
             "purity": c.one(a, "purity"),
             "reads": [c.ref(r, READS_KINDS, allow_prop=True, path=path + ".reads") for r in c.all(a, "reads")],
             "implementation_ref": c.one(a, "implementation_ref")}
        _opt(c, f, a, "determinism")
        return f
    if kind == "actions":
        return _action(c, a, path)
    if kind == "policies":
        return {"id": rid, "decision": c.one(a, "decision"), "expression_ref": c.one(a, "expression_ref"),
                "version": c.one(a, "version")}
    if kind == "authority_rules":
        r = {"id": rid}
        for f in ("principal_selector", "capability", "resource_selector", "effect"):
            r[f] = c.one(a, f)
        _opt(c, r, a, "delegation_allowed")
        return r
    if kind == "observation_types":
        return {"id": rid, "subject_type": c.ref(c.one(a, "subject_type"), ("object_types",), path=path + ".subject_type"),
                "properties": c.props(a, path + ".properties"), "source_binding": c.one(a, "source_binding"),
                "truth_status": c.one(a, "truth_status")}
    return {"id": rid, "scope": c.one(a, "scope"), "expression_ref": c.one(a, "expression_ref"),
            "severity": c.one(a, "severity")}
