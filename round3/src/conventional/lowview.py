"""THE read-side authorization filter (EQUIVALENCE-G3 'conventional'; PROT-H26 s1-s2): policy-as-data (the v3
`disclosure` document) evaluated into one observer-specific LOW VIEW. Every low channel (read_object, list_objects,
list_links, query, subscribe/poll, provenance, constitutional refusals) is answered from this view and nothing else, so
"hidden == absent" is one code path. The view is a pure function of (world, authority document, observer, tick): no
channel-specific trimming exists anywhere else (a DTO-only redaction would be the strawman).
"""
from __future__ import annotations

from r3_shared.authspec import effective_disclosure

PROV_RANK = {"none": 0, "own": 1, "scalars": 2, "actors": 3}


class LowView:
    def __init__(self):
        self.vis: set[str] = set()
        self.fields: dict[str, set[str]] = {}
        self.link_types: dict[str, set[str]] = {}  # ref -> link types its covering rules reveal
        self.prov: dict[str, str] = {}
        self.links: set[tuple[str, str, str]] = set()
        self.props: dict[str, dict] = {}

    def has(self, ref: str) -> bool:
        return ref in self.vis


def _tk(ref: str) -> tuple[str, str]:
    t, k = ref.split(":", 1)
    return t, k


class ViewBuilder:
    """Builds LowViews for one (policy, ops spec). `world` is a WorldView; links = {link_type: [(src, dst)]}."""

    def __init__(self, ops_spec: dict):
        self._types = {t["name"]: [f["name"] for f in t["fields"]] for t in ops_spec["resource_types"]}
        self._ops = ops_spec["operations"]
        self._ops_spec = ops_spec

    # -- rule matching ---------------------------------------------------------------------------------
    @staticmethod
    def _sel(pol, sel: dict, pid: str, obj: tuple[str, str]) -> bool:
        if sel.get("any"):
            return True
        if "role" in sel:
            return sel["role"] in pol._principals[pid]["roles"]
        if "id" in sel:
            return sel["id"] == pid
        if "relation" in sel:
            return sel["on_type"] == obj[0] and pol.holds(pid, obj[0], obj[1], sel["relation"])
        return False

    def _via_objects(self, rule_via: dict, ref: str, world, vis: set[str]) -> list[str]:
        out = []
        for a, b in world.all_links(rule_via["link"]):
            other = None
            if rule_via["dir"] == "out" and a == ref:
                other = b
            elif rule_via["dir"] == "in" and b == ref:
                other = a
            if other is not None and _tk(other)[0] == rule_via["type"] and other in vis:
                out.append(other)
        return out

    def _covering(self, pol, disc: dict, pid: str, ref: str, world, vis: set[str]) -> list[dict]:
        t, k = _tk(ref)
        hit = []
        for r in disc["rules"]:
            o = r["object"]
            if o["type"] != t or (o["keys"] is not None and k not in o["keys"]):
                continue
            if o["via"] is None:
                ok = self._sel(pol, r["principal"], pid, (t, k))
            else:
                ok = any(self._sel(pol, r["principal"], pid, _tk(v)) for v in self._via_objects(o["via"], ref, world, vis))
            if ok:
                hit.append(r)
        return hit

    def _reveal(self, rules: list[dict], t: str) -> tuple[bool, set[str], set[str], str]:
        ex, fields, links, prov = False, set(), set(), "none"
        allf = set(self._types[t])
        for r in (x for x in rules if x["effect"] == "allow"):
            rv = r["reveals"]
            ex |= rv["exists"]
            fields |= allf if rv["fields"] == "*" else set(rv["fields"])
            links |= set(rv["links"])
            if PROV_RANK[rv["provenance"]] > PROV_RANK[prov]:
                prov = rv["provenance"]
        for r in (x for x in rules if x["effect"] == "deny"):  # deny overrides allow
            rv = r["reveals"]
            if rv["exists"]:
                ex, fields, links, prov = False, set(), set(), "none"
                continue
            fields -= allf if rv["fields"] == "*" else set(rv["fields"])
            links -= set(rv["links"])
            if rv["provenance"] != "none":
                prov = "none"
        return ex, fields, links, prov

    # -- the fixpoint (PROT-H26 s2.1) --------------------------------------------------------------------
    def build(self, pol, observer: str | None, world, tick: int) -> LowView:
        disc = effective_disclosure(pol.doc, self._ops_spec)
        lv = LowView()
        pub = set(disc["public_types"])
        objs = {f"{t}:{k}": p for t in self._types for k, p in world.items(t)}
        known = observer is not None and pol.known(observer)
        implied = self._act_implies(pol, observer, objs, tick) if known else set()
        for ref in objs:
            if _tk(ref)[0] in pub:
                lv.vis.add(ref)
        lv.vis |= implied
        while known:  # least fixpoint over rules (via-rules grow the set)
            grew = False
            for ref in objs:
                if ref in lv.vis:
                    continue
                ex, *_ = self._reveal(self._covering(pol, disc, observer, ref, world, lv.vis), _tk(ref)[0])
                if ex:
                    lv.vis.add(ref)
                    grew = True
            if not grew:
                break
        for ref in lv.vis:
            t = _tk(ref)[0]
            if t in pub:
                lv.fields[ref], lv.link_types[ref], lv.prov[ref] = set(self._types[t]), set(disc["public_links"]), "none"
                continue
            rules = self._covering(pol, disc, observer, ref, world, lv.vis) if known else []
            _, f, ls, pv = self._reveal(rules, t)
            lv.fields[ref], lv.link_types[ref], lv.prov[ref] = f, ls, pv
        public_links = set(disc["public_links"])
        for lt in {x["name"] for x in self._ops_spec["link_types"]}:
            for a, b in world.all_links(lt):
                if a in lv.vis and b in lv.vis and (lt in public_links or lt in lv.link_types[a] or lt in lv.link_types[b]):
                    lv.links.add((lt, a, b))
        for ref in lv.vis:
            lv.props[ref] = {f: v for f, v in objs[ref].items() if f in lv.fields[ref]}
        return lv

    def _act_implies(self, pol, observer: str, objs: dict, tick: int) -> set[str]:
        """PROT-H26 2.2: base/edge authority (world-independent) over a request naming T:k makes E(T:k) low."""
        out: set[str] = set()
        roots = [None] + [e["issuer"] for e in pol.doc.get("capabilities", []) if e["child"] == observer]
        for op in self._ops:
            for inp in op["inputs"]:
                if inp["type"] != "resource":
                    continue
                for ref in objs:
                    t, k = _tk(ref)
                    if t != inp["resource_type"] or ref in out:
                        continue
                    if any(pol.decide(observer, q, op["name"], [(t, k)], tick).allowed for q in roots):
                        out.add(ref)
        return out
