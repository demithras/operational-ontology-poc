"""Single-field semantic mutations of an IR package (oracle self-test material).

Every class changes exactly one structural field so that the result is semantically different
from the input (under the oracle). A mutation may break referential integrity (renaming an id
leaves dangling references); the oracle compares IR structure only, it never validates.
``field`` is a substring that must occur in at least one reported diff path.
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from typing import Callable, NamedTuple, Optional

from hypothesis import strategies as st

from .kinds import RESOURCE_ARRAYS

MutFn = Callable[[dict, random.Random], Optional[dict]]


@dataclass(frozen=True)
class MutationClass:
    id: str
    family: str
    field: str
    description: str
    fn: MutFn


REGISTRY: dict[str, MutationClass] = {}


def register(id: str, family: str, field: str, description: str, fn: MutFn) -> None:
    assert id not in REGISTRY, id
    REGISTRY[id] = MutationClass(id, family, field, description, fn)


class Mutation(NamedTuple):
    class_id: str
    package: dict


def apply_class(class_id: str, pkg: dict, seed: int = 0) -> Optional[dict]:
    """Apply one class to a deep copy of ``pkg``; None when the class is not applicable."""
    return REGISTRY[class_id].fn(copy.deepcopy(pkg), random.Random(seed))


def pick(rnd: random.Random, seq):
    return seq[rnd.randrange(len(seq))] if seq else None


def alt(s: str) -> str:
    return s + "~"


def cycle(values, cur):
    return values[(values.index(cur) + 1) % len(values)]


# --- package level ----------------------------------------------------------------------------

def _scalar(key: str) -> MutFn:
    def fn(p, r):
        if key not in p:
            p[key] = "zz"
        else:
            p[key] = alt(p[key])
        return p
    return fn


def _imports(p, r):
    if p.get("imports"):
        i = r.randrange(len(p["imports"]))
        p["imports"][i] = alt(p["imports"][i])
    else:
        p["imports"] = p.get("imports", []) + ["zz"]
    return p


def _metadata(p, r):
    md = p.setdefault("metadata", {})
    md["zz_mut"] = 1 if "zz_mut" not in md or md["zz_mut"] != 1 else 2
    return p


def _bool_int_sites(x, out):
    items = x.items() if isinstance(x, dict) else enumerate(x) if isinstance(x, list) else ()
    for k, v in items:
        if isinstance(v, bool) or (type(v) is int and v in (0, 1)):
            out.append((x, k))
        else:
            _bool_int_sites(v, out)


def _metadata_bool_int(p, r):
    sites = []
    _bool_int_sites(p.get("metadata") or {}, sites)
    site = pick(r, sites)
    if site is None:
        return None
    c, k = site
    v = c[k]
    c[k] = 1 if v is True else 0 if v is False else (v == 1)
    return p


register("package_id", "package", "package_id", "package_id changed", _scalar("package_id"))
register("package_version", "package", "version", "package version changed", _scalar("version"))
register("domain_id", "package", "domain_id", "domain_id changed or added", _scalar("domain_id"))
register("imports", "package", "imports", "import element changed or added", _imports)
register("metadata", "package", "metadata", "metadata key added/changed", _metadata)
register("metadata_bool_vs_int", "package", "metadata", "metadata true<->1 / false<->0", _metadata_bool_int)


def _remove(kind: str) -> MutFn:
    def fn(p, r):
        i = r.randrange(len(p[kind])) if p[kind] else None
        if i is None:
            return None
        del p[kind][i]
        return p
    return fn


def _add(kind: str) -> MutFn:
    def fn(p, r):
        if not p[kind]:
            return None
        c = copy.deepcopy(pick(r, p[kind]))
        c["id"] = alt(c["id"]) + "+"
        p[kind].append(c)
        return p
    return fn


def _rename(kind: str) -> MutFn:
    def fn(p, r):
        c = pick(r, p[kind])
        if c is None:
            return None
        c["id"] = alt(c["id"])
        return p
    return fn


for _k in RESOURCE_ARRAYS:
    register(f"remove_{_k}", "resource", _k + "[", f"a {_k} resource removed", _remove(_k))
    register(f"add_{_k}", "resource", _k + "[", f"a {_k} resource added (copy, new id)", _add(_k))
    register(f"rename_{_k}", "resource", _k + "[", f"a {_k} id renamed (identity change)", _rename(_k))


# --- strategy ---------------------------------------------------------------------------------
from . import mutations_fields  # noqa: E402,F401  (registers the field-level classes)


@st.composite
def _single_mutation(draw, pkg: dict):
    ids = sorted(REGISTRY)
    start = draw(st.integers(0, len(ids) - 1))
    seed = draw(st.integers(0, 2**31))
    for off in range(len(ids)):
        cid = ids[(start + off) % len(ids)]
        out = apply_class(cid, pkg, seed)
        if out is not None:
            return Mutation(cid, out)
    raise AssertionError("package_id mutation is always applicable")


def single_mutation(pkg: dict) -> st.SearchStrategy[Mutation]:
    """Strategy for (class id, package differing from ``pkg`` in exactly one structural field)."""
    return _single_mutation(pkg)
