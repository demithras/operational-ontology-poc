"""Type expressions, links, interfaces, functions, actions, policies, authority, observation, constraints."""
from __future__ import annotations

from .kinds import (AUTHORITY_EFFECTS, DETERMINISM, EFFECT_OPERATIONS, IDEMPOTENCY, POLICY_DECISIONS, PRIMITIVES,
                    PURITY, SEVERITIES)
from .mutations import alt, pick, register
from .mutations_fields import _enum, _flag, _lst, _owners, _str

# --- type slots -------------------------------------------------------------------------------


def _type_slots(p):
    out = [(x, "type") for lst in _owners(p) for x in lst]
    out += [(x, "type") for kind in ("functions", "actions") for f in p[kind] for x in f["inputs"]]
    out += [(f, "output") for f in p["functions"]]
    return out


def _type_mut(pred, change):
    def fn(p, r):
        c = pick(r, [(c, k) for c, k in _type_slots(p) if pred(c[k])])
        if c is None:
            return None
        c[0][c[1]] = change(c[0][c[1]])
        return p
    return fn


def _is_prim(t):
    return isinstance(t, str)


def _ctor(t):
    return isinstance(t, dict) and ("list" in t or "optional" in t)


def _swap_ctor(t):
    return {"optional": t["list"]} if "list" in t else {"list": t["optional"]}


def _next_prim(t):
    return PRIMITIVES[(PRIMITIVES.index(t) + 1) % len(PRIMITIVES)]


register("type_primitive", "type", ".type|.output", "primitive type changed", _type_mut(_is_prim, _next_prim))
register("type_ref_target", "type", ".type|.output", "ref target changed",
         _type_mut(lambda t: isinstance(t, dict) and "ref" in t, lambda t: {"ref": alt(t["ref"])}))
register("type_wrap_optional", "type", ".type|.output", "type wrapped in optional", _type_mut(lambda t: True, lambda t: {"optional": t}))
register("type_wrap_list", "type", ".type|.output", "type wrapped in list", _type_mut(lambda t: True, lambda t: {"list": t}))
register("type_unwrap", "type", ".type|.output", "list/optional constructor removed", _type_mut(_ctor, lambda t: t.get("list", t.get("optional"))))
register("type_ctor_swap", "type", ".type|.output", "list <-> optional", _type_mut(_ctor, _swap_ctor))
register("type_primitive_to_ref", "type", ".type|.output", "primitive replaced by a ref", _type_mut(_is_prim, lambda t: {"ref": t}))

# --- links ------------------------------------------------------------------------------------
register("link_from", "link_type", "from", "link from changed", _str("link_types", "from"))
register("link_to", "link_type", "to", "link to changed", _str("link_types", "to"))
register("link_directed", "link_type", "directed", "link directed flipped", _flag("link_types", "directed", True))


def _card(which, part):
    def fn(p, r):
        c = pick(r, p["link_types"])
        if c is None:
            return None
        card = c[which]
        if part == "min":
            card["min"] += 1
        elif card["max"] == "*":
            card["max"] = 1
        elif card["max"] == 1:
            card["max"] = "*"
        else:
            card["max"] += 1
        return p
    return fn


for _w in ("from_cardinality", "to_cardinality"):
    register(f"{_w}_min", "link_type", f"{_w}.min", f"{_w} min changed", _card(_w, "min"))
    register(f"{_w}_max", "link_type", f"{_w}.max", f"{_w} max changed (1 / n / '*')", _card(_w, "max"))


def _max_star_vs_int(p, r):  # the headline known-negative: max 1 <-> "*" only
    c = pick(r, [x for x in p["link_types"] if x["to_cardinality"]["max"] in (1, "*")])
    if c is None:
        return None
    c["to_cardinality"]["max"] = "*" if c["to_cardinality"]["max"] == 1 else 1
    return p


register("cardinality_one_vs_star", "link_type", "to_cardinality.max", "max 1 <-> '*'", _max_star_vs_int)

# --- interfaces -------------------------------------------------------------------------------
register("interface_required_link_add", "interface", "required_links", "required_links gains an element",
         _lst("interfaces", "required_links", "add"))
register("interface_required_link_remove", "interface", "required_links", "required_links loses an element",
         _lst("interfaces", "required_links", "rm"))
register("interface_capability_add", "interface", "capabilities", "capability added", _lst("interfaces", "capabilities", "add"))
register("interface_capability_change", "interface", "capabilities", "capability changed", _lst("interfaces", "capabilities", "chg"))

# --- policies / authority / observation / constraints -------------------------------------------
register("policy_decision", "policy", "decision", "policy decision changed", _enum("policies", "decision", POLICY_DECISIONS))
register("policy_expression", "policy", "expression_ref", "policy expression_ref changed", _str("policies", "expression_ref"))
register("policy_version", "policy", "version", "policy version changed", _str("policies", "version"))
register("authority_principal", "authority_rule", "principal_selector", "principal_selector changed", _str("authority_rules", "principal_selector"))
register("authority_capability", "authority_rule", "capability", "capability changed", _str("authority_rules", "capability"))
register("authority_resource", "authority_rule", "resource_selector", "resource_selector changed", _str("authority_rules", "resource_selector"))
register("authority_effect", "authority_rule", "effect", "authority effect allow <-> deny", _enum("authority_rules", "effect", AUTHORITY_EFFECTS))
register("authority_delegation", "authority_rule", "delegation_allowed", "delegation_allowed flipped/added",
         _flag("authority_rules", "delegation_allowed", False))
register("observation_subject", "observation_type", "subject_type", "subject_type changed", _str("observation_types", "subject_type"))
register("observation_source", "observation_type", "source_binding", "source_binding changed", _str("observation_types", "source_binding"))
register("constraint_scope", "constraint", "scope", "scope changed", _str("constraints", "scope"))
register("constraint_expression", "constraint", "expression_ref", "expression_ref changed", _str("constraints", "expression_ref"))
register("constraint_severity", "constraint", "severity", "constraint severity hard <-> soft", _enum("constraints", "severity", SEVERITIES))

from . import mutations_fields3  # noqa: E402,F401


def _star_vs_large(p, r):  # an oracle that equates "*" with a huge integer would not notice this
    site = pick(r, [(c[w], "max") for c in p["link_types"] for w in ("from_cardinality", "to_cardinality") if c[w]["max"] == "*"])
    if site is None:
        return None
    site[0]["max"] = 10**6
    return p


register("cardinality_star_vs_large_int", "link_type", "cardinality.max", "max '*' -> 1000000", _star_vs_large)
