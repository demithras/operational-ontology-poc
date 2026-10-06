"""Tiny constructors for the neutral predicate/expression vocabulary (see r3_shared/opsspec.py for semantics)."""


def inp(name): return {"input": name}
def lit(v): return {"lit": v}
def now(): return {"now": True}
def field(of, name): return {"field": [of, name]}
def unique(type_, **links): return {"unique": {"type": type_, "where": [{"link": k, "to": v} for k, v in links.items()]}}
def newest(type_, name): return {"newest": {"type": type_, "field": name}}
def read(name, **args): return {"read": name, "args": args}
def add(*a): return {"add": list(a)}
def sub(a, b): return {"sub": [a, b]}
def eq(a, b): return {"op": "eq", "args": [a, b]}
def ne(a, b): return {"op": "ne", "args": [a, b]}
def ge(a, b): return {"op": "ge", "args": [a, b]}
def gt(a, b): return {"op": "gt", "args": [a, b]}
def le(a, b): return {"op": "le", "args": [a, b]}
def lt(a, b): return {"op": "lt", "args": [a, b]}
def in_(a, vals): return {"op": "in", "args": [a, lit(list(vals))]}
def and_(*a): return {"op": "and", "args": list(a)}
def or_(*a): return {"op": "or", "args": list(a)}
def not_(a): return {"op": "not", "args": [a]}
def is_int(a): return {"op": "is_int", "args": [a]}
def nonblank(a): return {"op": "nonblank", "args": [a]}
def exists(a): return {"op": "exists", "args": [a]}
def actor_holds(relation, on): return {"op": "actor_holds", "relation": relation, "on": on}


def rule(id_, text, pred): return {"id": id_, "description": text, "predicate": pred}


def i(name, type_, required=True, ref=None):
    d = {"name": name, "type": type_, "required": required}
    if ref:
        d["resource_type"] = ref
    return d


def ir_input(x):
    t = x["type"]
    if isinstance(t, dict) and "ref" in t:
        return i(x["name"], "resource", x.get("required", True), t["ref"])
    return i(x["name"], t if isinstance(t, str) else "json", x.get("required", True))
