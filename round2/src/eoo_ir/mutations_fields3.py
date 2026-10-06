"""Function / Action field-level mutation classes, including Function<->Action kind collapse."""
from __future__ import annotations

import copy

from .kinds import DETERMINISM, EFFECT_OPERATIONS, IDEMPOTENCY, PURITY
from .mutations import alt, cycle, pick, register
from .mutations_fields import _enum, _flag, _lst, _str
from .normalize import jkey

# --- inputs (order significant) ---------------------------------------------------------------


def _input(kind, how):
    def fn(p, r):
        f = pick(r, [x for x in p[kind] if how == "add" or (how == "swap" and len(x["inputs"]) >= 2) or
                     (how == "rm" and x["inputs"]) or (how == "req" and x["inputs"])])
        if f is None:
            return None
        ins = f["inputs"]
        if how == "add":
            ins.append({"name": "zz_in", "type": "string", "required": True})
        elif how == "rm":
            del ins[r.randrange(len(ins))]
        elif how == "swap":
            ins[0], ins[1] = ins[1], ins[0]
        else:
            q = pick(r, ins)
            q["required"] = (not q["required"]) if "required" in q else False  # default is true
        return p
    return fn


for _kind, _tag in (("functions", "function"), ("actions", "action")):
    register(f"{_tag}_input_add", _tag, "inputs", f"{_tag} input appended", _input(_kind, "add"))
    register(f"{_tag}_input_remove", _tag, "inputs", f"{_tag} input removed", _input(_kind, "rm"))
    register(f"{_tag}_input_swap", _tag, "inputs", f"{_tag} first two inputs swapped (order is significant)", _input(_kind, "swap"))
    register(f"{_tag}_input_required", _tag, "required", f"{_tag} input required flipped", _input(_kind, "req"))

# --- function ---------------------------------------------------------------------------------
register("function_reads_add", "function", "reads", "function reads gains an element", _lst("functions", "reads", "add"))
register("function_reads_remove", "function", "reads", "function reads loses an element", _lst("functions", "reads", "rm"))
register("function_reads_change", "function", "reads", "function reads element changed", _lst("functions", "reads", "chg"))
register("function_implementation", "function", "implementation_ref", "implementation_ref changed", _str("functions", "implementation_ref"))


def _determinism(p, r):
    f = pick(r, p["functions"])
    if f is None:
        return None
    f["determinism"] = cycle(list(DETERMINISM), f["determinism"]) if "determinism" in f else "deterministic"
    return p


register("function_determinism", "function", "determinism", "determinism changed/added", _determinism)


def _function_to_action(p, r):
    f = pick(r, p["functions"])
    if f is None:
        return None
    p["functions"].remove(f)
    p["actions"].append({"id": f["id"], "inputs": f["inputs"], "authority_refs": [], "policy_refs": [], "preconditions": [],
                         "effects": [{"target": "zz", "operation": "external_call"}], "idempotency": "not_applicable",
                         "outcome_predicate": "zz", "version": "zz"})
    return p


def _action_to_function(p, r):
    a = pick(r, p["actions"])
    if a is None:
        return None
    p["actions"].remove(a)
    p["functions"].append({"id": a["id"], "inputs": a["inputs"], "output": "string", "purity": PURITY, "reads": [],
                           "implementation_ref": "zz"})
    return p


register("kind_function_to_action", "kind", "functions[", "a Function re-declared as an Action of the same id", _function_to_action)
register("kind_action_to_function", "kind", "actions[", "an Action re-declared as a Function of the same id", _action_to_function)

# --- action -----------------------------------------------------------------------------------
for _key in ("authority_refs", "policy_refs", "preconditions"):
    register(f"action_{_key}_add", "action", _key, f"action {_key} gains an element", _lst("actions", _key, "add"))
    register(f"action_{_key}_remove", "action", _key, f"action {_key} loses an element", _lst("actions", _key, "rm"))
    register(f"action_{_key}_change", "action", _key, f"action {_key} element changed", _lst("actions", _key, "chg"))
register("action_idempotency", "action", "idempotency", "idempotency changed", _enum("actions", "idempotency", IDEMPOTENCY))
register("action_outcome_predicate", "action", "outcome_predicate", "outcome_predicate changed", _str("actions", "outcome_predicate"))
register("action_version", "action", "version", "action version changed", _str("actions", "version"))


def _compensation(p, r):
    a = pick(r, p["actions"])
    if a is None:
        return None
    cur = a.get("compensation_action", "<absent>")
    a["compensation_action"] = None if cur == "<absent>" else ("zz" if cur is None else None)
    return p


register("action_compensation", "action", "compensation_action", "compensation_action absent->null->'zz'->null", _compensation)


def _effect(how):
    def fn(p, r):
        a = pick(r, [x for x in p["actions"] if (how in ("add", "op", "target", "fields")) or
                     (how == "rm" and len(x["effects"]) > 1) or
                     (how == "swap" and len(x["effects"]) > 1 and jkey(x["effects"][0]) != jkey(x["effects"][1]))])
        if a is None:
            return None
        ef = a["effects"]
        if how == "add":
            ef.append({"target": "zz", "operation": "external_call"})
        elif how == "rm":
            del ef[r.randrange(len(ef))]
        elif how == "swap":
            ef[0], ef[1] = ef[1], ef[0]
        else:
            e = pick(r, ef)
            if how == "op":
                e["operation"] = cycle(list(EFFECT_OPERATIONS), e["operation"])
            elif how == "target":
                e["target"] = alt(e["target"])
            else:
                e["fields"] = e["fields"] + ["zz"] if "fields" in e else ["zz"]
        return p
    return fn


for _how, _desc in (("add", "effect appended"), ("rm", "effect removed"), ("swap", "first two effects swapped (order is significant)"),
                    ("op", "effect operation changed"), ("target", "effect target changed"), ("fields", "effect fields extended")):
    register(f"action_effect_{_how}", "action", "effects", _desc, _effect(_how))


def _set_list_duplicate(p, r):
    """Set-valued lists KEEP duplicates: [a] and [a, a] are different packages."""
    sites = [(c, k) for kind, keys in (("object_types", ["implements"]), ("interfaces", ["required_links", "capabilities"]),
                                       ("functions", ["reads"]), ("actions", ["authority_refs", "policy_refs", "preconditions"]))
             for c in p[kind] for k in keys if c[k]]
    sites += [(p, "imports")] if p.get("imports") else []
    sites += [(e, "fields") for a in p["actions"] for e in a["effects"] if e.get("fields")]
    sites += [(q, "constraints") for kind in ("object_types", "observation_types") for o in p[kind] for q in o["properties"]
              if q.get("constraints")]
    site = pick(r, sites)
    if site is None:
        return None
    c, k = site
    c[k].append(c[k][r.randrange(len(c[k]))])
    return p


register("set_list_duplicate", "set_list", "implements|required_links|capabilities|reads|authority_refs|policy_refs|"
         "preconditions|constraints|fields|imports", "an element of a set-valued list duplicated (duplicates are kept)",
         _set_list_duplicate)
