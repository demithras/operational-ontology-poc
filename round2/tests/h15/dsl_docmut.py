"""JSON-level mutation helpers for DSL fail-closed tests (not a test module)."""
from __future__ import annotations

import copy
import random


def sites(doc, path=()):
    """Every deletable position: a dict key or a list element."""
    out = []
    if isinstance(doc, dict):
        for k, v in doc.items():
            out.append(path + (k,))
            out += sites(v, path + (k,))
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            out.append(path + (i,))
            out += sites(v, path + (i,))
    return out


def get(doc, path):
    for p in path:
        doc = doc[p]
    return doc


def delete(doc, path):
    d = copy.deepcopy(doc)
    parent = get(d, path[:-1])
    if isinstance(parent, dict):
        del parent[path[-1]]
    else:
        del parent[path[-1]]
    return d


WRONG = [0, 1, -1, 1.5, True, False, None, "", "zz", [], {}, [1], {"a": 1}, "string", "*", "observed", "deterministic"]


def mutate(doc, rnd: random.Random):
    """One random structural edit: delete, replace by a wrong-typed/odd value, or add an unknown key."""
    d = copy.deepcopy(doc)
    ps = sites(d)
    if not ps:
        return d
    path = rnd.choice(ps)
    parent = get(d, path[:-1])
    op = rnd.choice(["delete", "replace", "replace", "unknown", "empty"])
    if op == "delete":
        del parent[path[-1]]
    elif op == "replace":
        parent[path[-1]] = copy.deepcopy(rnd.choice(WRONG))
    elif op == "empty":
        v = parent[path[-1]]
        parent[path[-1]] = "" if isinstance(v, str) else [] if isinstance(v, list) else v
    else:
        tgt = parent[path[-1]]
        if isinstance(tgt, dict):
            tgt["zz_unknown"] = 1
        else:
            d["zz_unknown"] = 1
    return d
