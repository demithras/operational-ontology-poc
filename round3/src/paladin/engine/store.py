"""Canonical store: versioned objects + links with optimistic versions. Writes need a live WriteGrant.

Op shapes (JSON-able):
  {"op": "create", "type": T, "key": k, "props": {...}}
  {"op": "update", "type": T, "key": k, "props": {...partial...}, "expect": version?}
  {"op": "delete", "type": T, "key": k, "expect": version?}
  {"op": "link"|"unlink", "type": L, "src": k|[T,k], "dst": k|[T,k], "props": {...}?}
Integrity rules are generic, derived from the IR: declared properties only, required present,
values type-check, primary key matches, immutable properties never change, references resolve,
no dangling links/references after delete, link endpoints conform, max cardinality per end.
"""
from __future__ import annotations

from typing import Any, Callable

from .canon import to_plain
from .errors import IntegrityError
from .state import State
from .typecheck import check, ref_values


def _endpoint(st: State, declared: str, given: Any) -> tuple[tuple | None, str | None]:
    if isinstance(given, (list, tuple)) and len(given) == 2:
        t, k = given[0], given[1]
        if (t, k) in st.objects and st.model.conforms(t, declared):
            return (t, k), None
        return None, f"endpoint {given!r} does not exist as {declared}"
    if st.model.is_import(declared):
        return (declared, given), None
    hits = st.locate(declared, given)
    if len(hits) != 1:
        return None, f"endpoint {given!r} does not resolve uniquely to {declared}"
    return hits[0], None


def _check_props(st: State, props_spec: dict, props: dict, where: str, full: bool) -> list[str]:
    errs = []
    for k, v in props.items():
        spec = props_spec.get(k)
        if spec is None:
            errs.append(f"{where}: undeclared property {k!r}")
            continue
        if v is None and spec["required"]:
            errs.append(f"{where}: required property {k!r} is null")
            continue
        p = None if v is None else check(spec["type"], v, st.resolve_problem)
        if p:
            errs.append(f"{where}.{k}: {p}")
    if full:
        for k, spec in props_spec.items():
            if spec["required"] and props.get(k) is None:
                errs.append(f"{where}: missing required property {k!r}")
    return errs


def _apply_one(st: State, op: dict, touched: set) -> list[str]:
    kind, t = op.get("op"), op.get("type")
    m = st.model
    if kind in ("create", "update", "delete"):
        spec = m.get("object_types", t)
        if spec is None:
            return [f"{kind}: {t!r} is not an object type of this package"]
        key, where = op.get("key"), f"{t}[{op.get('key')!r}]"
        cur = st.objects.get((t, key))
        if kind == "create":
            if cur is not None:
                return [f"{where}: already exists"]
            props = to_plain(op.get("props") or {})
            errs = _check_props(st, spec.props, props, where, full=True)
            if props.get(spec.pk) != key or isinstance(key, bool) or not isinstance(key, (str, int)):
                errs.append(f"{where}: primary key {spec.pk!r} must equal the scalar key")
            if not errs:
                st.objects[(t, key)] = {"props": props, "ver": 1}
            return errs
        if cur is None:
            return [f"{where}: does not exist"]
        if op.get("expect") is not None and op["expect"] != cur["ver"]:
            return [f"{where}: stale write (expected version {op['expect']}, current {cur['ver']})"]
        if kind == "delete":
            if any(s == (t, key) or d == (t, key) for (_, s, d) in st.links):
                return [f"{where}: still linked"]
            del st.objects[(t, key)]
            touched.add(("deleted", t, key))
            return []
        upd = to_plain(op.get("props") or {})
        errs = _check_props(st, spec.props, upd, where, full=False)
        for k, v in upd.items():
            if spec.props.get(k, {}).get("immutable") and cur["props"].get(k) != v:
                errs.append(f"{where}: immutable property {k!r} cannot change")
        if spec.pk in upd and upd[spec.pk] != key:
            errs.append(f"{where}: primary key cannot change")
        if not errs:
            st.objects[(t, key)] = {"props": {**cur["props"], **upd}, "ver": cur["ver"] + 1}
        return errs
    if kind in ("link", "unlink"):
        spec = m.get("link_types", t)
        if spec is None:
            return [f"{kind}: {t!r} is not a link type of this package"]
        s, e1 = _endpoint(st, spec.src, op.get("src"))
        d, e2 = _endpoint(st, spec.dst, op.get("dst"))
        if e1 or e2:
            return [x for x in (e1, e2) if x]
        lk = (t, s, d)
        if kind == "unlink":
            if lk not in st.links:
                return [f"{t}: link {s}->{d} does not exist"]
            del st.links[lk]
            return []
        if lk in st.links:
            return [f"{t}: link {s}->{d} already exists"]
        props = to_plain(op.get("props") or {})
        errs = _check_props(st, spec.props, props, f"{t}:{s}->{d}", full=True)
        if not errs:
            st.links[lk] = {"props": props, "ver": 1}
            touched.add(("link", t, s, d))
        return errs
    return [f"unknown store op {kind!r}"]


def _post_checks(st: State, touched: set) -> list[str]:
    errs = []
    m = st.model
    for tag, *rest in sorted(touched, key=repr):
        if tag == "link":
            lt, s, d = rest
            spec = m.get("link_types", lt)
            out_deg = len(st.links_of(lt, s, outgoing=True))
            in_deg = len(st.links_of(lt, d, outgoing=False))
            if spec.src_max != "*" and out_deg > spec.src_max:
                errs.append(f"{lt}: {s} has {out_deg} outgoing links, max {spec.src_max}")
            if spec.dst_max != "*" and in_deg > spec.dst_max:
                errs.append(f"{lt}: {d} has {in_deg} incoming links, max {spec.dst_max}")
        elif tag == "deleted":
            t, key = rest
            for (ot, ok), rec in st.objects.items():
                ospec = m.get("object_types", ot)
                for pn, pv in rec["props"].items():
                    for declared, k in ref_values(ospec.props[pn]["type"], pv):
                        if k == key and m.conforms(t, declared):
                            errs.append(f"{ot}[{ok!r}].{pn}: dangling reference to deleted {t}[{key!r}]")
    return errs


def would_be(base: State, ops: list) -> tuple[State, list[str]]:
    """The state after ``ops`` (applied in order on a fork) and every integrity problem found."""
    st, touched, errs = base.fork(), set(), []
    for i, op in enumerate(ops):
        errs += [f"op[{i}] {e}" for e in _apply_one(st, op, touched)]
    if not errs:
        errs += _post_checks(st, touched)
    return st, errs


class Store:
    """Holds the current State. ``apply`` is the only write path and needs a live grant."""

    def __init__(self, model, verify: Callable[[Any, str], None]):
        self._verify = verify
        self.current = State(model)

    def plan(self, ops: list) -> tuple[State, list[str]]:
        return would_be(self.current, ops)

    def apply(self, grant, execution: str, ops: list) -> State:
        self._verify(grant, execution)
        nxt, errs = would_be(self.current, ops)
        if errs:
            raise IntegrityError("; ".join(errs))
        self.current = nxt
        return nxt
