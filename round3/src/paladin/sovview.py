"""Knowledge sovereignty, part 1: the observer's LOW view (PROT-H26 s1-s2). Paladin's own implementation (ruling Q4: no shared
helper; the oracle has a third, independent one).

`low_view(...)` is a pure function of (disclosure document, authority, world snapshot, observer): a least fixpoint over
public types, non-via rules, own/act-implies-exists objects, then via-rules through already-visible objects. Every low
channel (paladin.sovchan) answers ONLY from this value, so a protected fact that is absent from it cannot reach any output.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from r3_shared.authgraph import scope_covers


@dataclass
class LowView:
    objects: dict = field(default_factory=dict)    # ref -> {field: value}  (hidden fields ABSENT)
    links: set = field(default_factory=set)        # {(lt, src, dst)} visible links
    level: dict = field(default_factory=dict)      # ref -> provenance level of the covering rules: none|own|scalars|actors
    fields_of: dict = field(default_factory=dict)  # ref -> frozenset of visible field names
    linkable: dict = field(default_factory=dict)   # ref -> link types the covering rules reveal


LEVELS = {"none": 0, "own": 1, "scalars": 2, "actors": 3}


def ref_of(t: str, k: str) -> str:
    return f"{t}:{k}"


def split(ref: str):
    t, _, k = ref.partition(":")
    return t, k


def _psel(sel: dict, p: dict, on: tuple | None) -> bool:
    """Principal selector of a disclosure rule. `on` = (type, key) of the object (or via object) for relation selectors."""
    if sel.get("any"):
        return True
    if "role" in sel:
        return sel["role"] in p["roles"]
    if "id" in sel:
        return sel["id"] == p["id"]
    if "relation" in sel:
        return on is not None and on[0] == sel["on_type"] and any(
            r["type"] == on[0] and r["key"] == on[1] and r["relation"] == sel["relation"] for r in p["relations"])
    return False


def low_view(disc: dict, observer: dict, snap_objs: dict, snap_links: set, implied: set) -> LowView:
    """disc: effective disclosure document; observer: principal dict of the auth spec; snap_objs: {ref: props};
    snap_links: {(lt, src, dst)}; implied: refs made existence-visible by act-implies-exists / own facts (s2.1-2.3)."""
    pub_t, pub_l, rules = set(disc["public_types"]), set(disc["public_links"]), disc["rules"]
    vis = {r for r in snap_objs if split(r)[0] in pub_t} | {r for r in implied if r in snap_objs}
    adj_out: dict = {}
    adj_in: dict = {}
    for lt, a, b in snap_links:
        adj_out.setdefault(a, []).append((lt, b))
        adj_in.setdefault(b, []).append((lt, a))

    def covers(rule: dict, ref: str, visible: set):
        """Does the rule cover `ref` for the observer? -> (True, on_ref_for_relation) / (False, None)."""
        o = rule["object"]
        t, k = split(ref)
        if o["type"] != t or (o["keys"] is not None and k not in o["keys"]):
            return False, None
        via = o["via"]
        if via is None:
            return (_psel(rule["principal"], observer, (t, k)), ref)
        nbrs = adj_out.get(ref, []) if via["dir"] == "out" else adj_in.get(ref, [])
        for lt, other in nbrs:
            if lt == via["link"] and split(other)[0] == via["type"] and other in visible \
                    and _psel(rule["principal"], observer, split(other)):
                return True, other
        return False, None

    changed = True
    while changed:
        changed = False
        for ref in snap_objs:
            if ref in vis:
                continue
            for rule in rules:
                if rule["effect"] == "allow" and rule["reveals"]["exists"] and covers(rule, ref, vis)[0]:
                    if not any(d["effect"] == "deny" and d["reveals"]["exists"] and covers(d, ref, vis)[0] for d in rules):
                        vis.add(ref)
                        changed = True
                        break
    out = LowView()
    for ref in sorted(vis):
        t, _k = split(ref)
        props = snap_objs[ref]
        if t in pub_t:
            out.objects[ref], out.level[ref] = dict(props), "actors"
            out.fields_of[ref] = frozenset(props)
            continue
        allow_f, deny_f, lvl, linkable = set(), set(), "none", set()
        for rule in rules:
            if not covers(rule, ref, vis)[0]:
                continue
            rv = rule["reveals"]
            fs = set(props) if rv["fields"] == "*" else set(rv["fields"])
            if rule["effect"] == "allow":
                allow_f |= fs
                linkable |= set(rv["links"])
                if LEVELS[rv["provenance"]] > LEVELS[lvl]:
                    lvl = rv["provenance"]
            else:
                deny_f |= fs
                linkable -= set(rv["links"])
                if rv["provenance"] != "none":
                    lvl = "none"
        keep = (allow_f - deny_f) & set(props)
        out.objects[ref] = {f: props[f] for f in sorted(keep)}
        out.fields_of[ref] = frozenset(keep)
        out.level[ref] = lvl
        out.linkable[ref] = linkable
    for lt, a, b in sorted(snap_links):
        if a not in out.objects or b not in out.objects:
            continue
        if lt in pub_l or lt in out.linkable.get(a, ()) or lt in out.linkable.get(b, ()):
            out.links.add((lt, a, b))
    return out


def implied_refs(ops_spec: dict, auth: dict, observer: dict, snap_objs: dict, extra_scopes: list) -> set:
    """PROT-H26 s2.2: T:k is existence-visible when base/edge authority (world-independent) allows the observer some
    operation on a request naming it. `extra_scopes`: [(scope, root principal dict)] of live edges held + active emergencies."""
    ops = {o["name"]: o for o in ops_spec["operations"]}
    by_id = {p["id"]: p for p in auth["principals"]}
    out = set()
    for ref in snap_objs:
        t, k = split(ref)
        for name, o in ops.items():
            if not any(i["type"] == "resource" and i["resource_type"] == t for i in o["inputs"]):
                continue
            if _allows(auth, by_id, observer, name, t, k) or any(
                    scope_covers(sc, name, [(t, k)]) and (root is None or _allows(auth, by_id, root, name, t, k))
                    for sc, root in extra_scopes):
                out.add(ref)
                break
    return out


def _chain(by_id: dict, p: dict) -> list:
    out, seen = [], set()
    while p is not None and p["id"] not in seen:
        out.append(p)
        seen.add(p["id"])
        p = by_id.get(p["delegated_by"])
    return out


def _gmatch(g: dict, p: dict, op: str, t: str, k: str) -> bool:
    pat = g["operation"]
    if not (pat == op or pat == "*" or (pat.endswith(":*") and op.startswith(pat[:-1]))):
        return False
    r = g["resource"]
    if not (r.get("any") or ("type" in r and "state" not in r and r["type"] == t)):
        return False
    s = g["principal"]
    if s.get("any"):
        return True
    if "role" in s:
        return s["role"] in p["roles"]
    if "id" in s:
        return s["id"] == p["id"]
    if "relation" in s:
        if s["on_type"] == t:
            return any(x["type"] == t and x["key"] == k and x["relation"] == s["relation"] for x in p["relations"])
        return any(x["type"] == s["on_type"] and x["relation"] == s["relation"] for x in p["relations"])
    return False


def _allows(auth: dict, by_id: dict, p: dict, op: str, t: str, k: str, depth: int = 0) -> bool:
    chain = _chain(by_id, p)
    if any(g["effect"] == "deny" and _gmatch(g, who, op, t, k) for who in chain for g in auth["grants"]):
        return False
    for g in auth["grants"]:
        if g["effect"] == "allow" and _gmatch(g, p, op, t, k):
            if p["delegated_by"] is None:
                return True
            if g["delegable"] and depth < 16 and _allows(auth, by_id, by_id[p["delegated_by"]], op, t, k, depth + 1):
                return True
    return False
