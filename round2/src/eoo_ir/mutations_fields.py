"""Field-level mutation classes (properties, types, links, functions, actions, ...)."""
from __future__ import annotations

from .kinds import (AUTHORITY_EFFECTS, DETERMINISM, EFFECT_OPERATIONS, IDEMPOTENCY, POLICY_DECISIONS, PRIMITIVES,
                    SEVERITIES)
from .mutations import alt, cycle, pick, register


def _str(kind, key):
    def fn(p, r):
        c = pick(r, [x for x in p[kind] if isinstance(x.get(key), str)])
        if c is None:
            return None
        c[key] = alt(c[key])
        return p
    return fn


def _enum(kind, key, values):
    def fn(p, r):
        c = pick(r, [x for x in p[kind] if x.get(key) in values])
        if c is None:
            return None
        c[key] = cycle(list(values), c[key])
        return p
    return fn


def _flag(kind, key, default):
    def fn(p, r):
        c = pick(r, p[kind])
        if c is None:
            return None
        c[key] = (not default) if key not in c else (not c[key])
        return p
    return fn


def _lst(kind, key, how):
    def fn(p, r):
        c = pick(r, [x for x in p[kind] if isinstance(x.get(key), list) and (how == "add" or x[key])])
        if c is None:
            return None
        if how == "add":
            c[key].append("zz")
        elif how == "rm":
            del c[key][r.randrange(len(c[key]))]
        else:
            i = r.randrange(len(c[key]))
            c[key][i] = alt(c[key][i]) if isinstance(c[key][i], str) else c[key][i]
        return p
    return fn


# objects ---------------------------------------------------------------------------------------
register("object_primary_key", "object_type", "primary_key", "primary_key changed", _str("object_types", "primary_key"))
register("object_description", "object_type", "description", "description added/changed/removed",
         lambda p, r: _desc(p, r, "object_types"))
register("object_implements_add", "object_type", "implements", "implements gains an element", _lst("object_types", "implements", "add"))
register("object_implements_remove", "object_type", "implements", "implements loses an element", _lst("object_types", "implements", "rm"))
register("object_implements_change", "object_type", "implements", "implements element changed", _lst("object_types", "implements", "chg"))


def _desc(p, r, kind):
    c = pick(r, p[kind])
    if c is None:
        return None
    if "description" in c and r.random() < 0.5:
        del c["description"]
    else:
        c["description"] = alt(c.get("description", "d"))
    return p


# properties (object types, link properties, interface required_properties, observation properties)
def _owners(p):
    out = [o["properties"] for o in p["object_types"]]
    out += [lk["properties"] for lk in p["link_types"] if isinstance(lk.get("properties"), list)]
    out += [i["required_properties"] for i in p["interfaces"]]
    out += [o["properties"] for o in p["observation_types"]]
    return out


def _prop_site(p, r, pred=lambda x: True):
    cs = [x for lst in _owners(p) for x in lst if pred(x)]
    return pick(r, cs)


def _prop(key, how):
    def fn(p, r):
        c = _prop_site(p, r, (lambda x: key in x) if how != "flag" else (lambda x: True))
        if c is None:
            return None
        if how == "str":
            c[key] = alt(c[key])
        elif how == "flag":
            c[key] = (not c[key]) if key in c else True
        return p
    return fn


def _prop_constraints(how):
    def fn(p, r):
        c = _prop_site(p, r, (lambda x: bool(x.get("constraints"))) if how != "add" else (lambda x: True))
        if c is None:
            return None
        cs = c.setdefault("constraints", [])
        if how == "add":
            cs.append("zz")
        elif how == "rm":
            del cs[r.randrange(len(cs))]
        else:
            i = r.randrange(len(cs))
            cs[i] = alt(cs[i])
        return p
    return fn


register("property_name", "property", "properties[", "property name changed", _prop("name", "str"))
register("property_required", "property", ".required", "property required flipped", _prop("required", "flag"))
register("property_immutable", "property", ".immutable", "property immutable flipped/added", _prop("immutable", "flag"))
register("property_description", "property", ".description", "property description changed", _prop("description", "str"))
register("property_constraint_add", "property", ".constraints", "property constraint added", _prop_constraints("add"))
register("property_constraint_remove", "property", ".constraints", "property constraint removed", _prop_constraints("rm"))
register("property_constraint_change", "property", ".constraints", "property constraint changed", _prop_constraints("chg"))


def _property_add(p, r):
    lst = pick(r, _owners(p))
    if lst is None:
        return None
    lst.append({"name": "zz_new", "type": "string", "required": False})
    return p


def _property_remove(p, r):
    lst = pick(r, [x for x in _owners(p) if x])
    if lst is None:
        return None
    del lst[r.randrange(len(lst))]
    return p


register("property_add", "property", "properties[", "a property added to some owner", _property_add)
register("property_remove", "property", "properties[", "a property removed from some owner", _property_remove)


from . import mutations_fields2  # noqa: E402,F401
