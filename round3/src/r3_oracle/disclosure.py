"""Oracle disclosure lattice: the observer's LOW view (PROT-H26 s1-s2), a least fixpoint. Pure; imports r3_shared and
r3_oracle only; no variant. Interpretations the frozen text leaves open are marked `INTERP` (listed in the H26 report).

low_view(snapshot, auth_spec, observer, ops_spec, facts=None) -> LowView
  snapshot  WorldReader.snapshot() shape {"objects": {ref: {"props"}}, "links": [[lt, a, b]]}
  facts     Facts(decisions, edges, cases) - harness-side records of the protected non-object layers (s1.1 D, C, G)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import authority
from .authority_v2 import RefAuthority  # noqa: F401  (edge-aware act-implies-exists uses scope_v2 via authority_v2)
from . import scope_v2

ORDER = {"none": 0, "own": 1, "scalars": 2, "actors": 3}


@dataclass
class Facts:
    decisions: list[dict] = field(default_factory=list)  # DecisionRec dicts (see disclosure_prov)
    edges: list[dict] = field(default_factory=list)      # PROT-H24 edge dicts {id, issuer, child, parent, scope, ...}
    cases: dict = field(default_factory=dict)            # case id -> {"requester", "members": [pid...], "state": json}


@dataclass
class LowView:
    observer: str
    objects: dict[str, dict]            # visible ref -> {visible field: value}   (hidden fields ABSENT, not null)
    links: set[tuple[str, str, str]]
    prov: dict[str, str]                # visible ref -> provenance level
    facts: Facts
    ops_spec: dict
    auth: dict
    acted_on: set[str] = field(default_factory=set)

    def to_doc(self) -> dict:
        from .disclosure_prov import low_decisions, low_edges, low_cases
        return {"objects": {r: self.objects[r] for r in sorted(self.objects)},
                "links": [list(x) for x in sorted(self.links)],
                "decisions": low_decisions(self),
                "edges": low_edges(self.facts.edges, self.observer),
                "cases": low_cases(self.facts.cases, self.observer)}

    def snapshot(self) -> dict:
        """The low view as a World snapshot (hidden objects/fields/links absent): queries are evaluated over it (s3.3)."""
        return {"objects": {r: {"props": p, "version": 1} for r, p in self.objects.items()},
                "links": [list(x) for x in sorted(self.links)]}


def principal(auth: dict, pid: str) -> dict:
    p = authority._principal(auth, pid)
    return p if p is not None else {"id": pid, "roles": [], "relations": [], "delegated_by": None}


def _split(ref: str) -> tuple[str, str]:
    t, k = ref.split(":", 1)
    return t, k


def _holds(p: dict, relation: str, ref: str) -> bool:
    t, k = _split(ref)
    return any(r["relation"] == relation and r["type"] == t and r["key"] == k for r in p["relations"])


def _sel(sel: dict, p: dict, ref: str, via_ref: str | None, rule_on_type) -> bool:
    if sel.get("any"):
        return True
    if "role" in sel:
        return sel["role"] in p["roles"]
    if "id" in sel:
        return sel["id"] == p["id"]
    if "relation" in sel:
        return _holds(p, sel["relation"], ref) or (via_ref is not None and _holds(p, sel["relation"], via_ref))
    return False


def covering(rules, p: dict, ref: str, links, visible: set[str]) -> list[dict]:
    """Rules covering `ref` for principal p (PROT-H26 s1.2). `links` = set of (lt, a, b); `visible` = existence-visible refs.
    INTERP-1: a via rule is covered by a link in the WORLD between ref and a visible via object (s1.2); s2.1's "visible
    links" is checked against the fixtures by tests/test_h26_oracle.py (both readings must agree on them)."""
    t, k = _split(ref)
    out = []
    for r in rules:
        o = r["object"]
        if o["type"] != t or (o["keys"] is not None and k not in o["keys"]):
            continue
        v = o.get("via")
        if v is None:
            if _sel(r["principal"], p, ref, None, o["type"]):
                out.append(r)
            continue
        if v["dir"] == "out":
            cands = [b for (lt, a, b) in links if lt == v["link"] and a == ref and _split(b)[0] == v["type"]]
        else:
            cands = [a for (lt, a, b) in links if lt == v["link"] and b == ref and _split(a)[0] == v["type"]]
        cands = [c for c in cands if c in visible]
        if any(_sel(r["principal"], p, ref, c, o["type"]) for c in cands):
            out.append(r)
    return out


def act_implies_exists(auth: dict, observer: str, ops_spec: dict, edges: list[dict], refs) -> set[str]:
    """PROT-H26 s2.2: base/edge authority (world-independent) allows the observer some operation naming T:k."""
    ops = ops_spec["operations"]
    out = set()
    for ref in refs:
        t, k = _split(ref)
        for op in ops:
            if not any(i["type"] == "resource" and i["resource_type"] == t for i in op["inputs"]):
                continue
            if authority.decide(observer, None, op["name"], [(t, k)], auth).allow:
                out.add(ref)
                break
            if any(e["child"] == observer and scope_v2.covers(e["scope"], op["name"], [(t, k)])
                   and authority.decide(e["issuer"], None, op["name"], [(t, k)], auth).allow for e in edges):
                out.add(ref)
                break
    return out


def low_view(snapshot: dict, auth_spec: dict, observer: str, ops_spec: dict, facts: Facts | None = None) -> LowView:
    facts = facts or Facts()
    d = auth_spec.get("disclosure") or {"public_types": [t["name"] for t in ops_spec["resource_types"]],
                                        "public_links": [x["name"] for x in ops_spec["link_types"]], "rules": []}
    p = principal(auth_spec, observer)
    objs = {r: o["props"] for r, o in snapshot["objects"].items()}
    links = {tuple(x) for x in snapshot["links"]}
    rules = d["rules"]
    pub_t, pub_l = set(d["public_types"]), set(d["public_links"])
    acted = act_implies_exists(auth_spec, observer, ops_spec, facts.edges, objs)
    visible = {r for r in objs if _split(r)[0] in pub_t} | acted
    while True:  # least fixpoint: via rules need already-visible via objects
        new = set()
        for r in objs:
            if r in visible:
                continue
            cov = covering(rules, p, r, links, visible)
            if any(x["effect"] == "allow" and x["reveals"]["exists"] for x in cov) and \
                    not any(x["effect"] == "deny" and x["reveals"]["exists"] for x in cov):
                new.add(r)
        if not new:
            break
        visible |= new
    fields: dict[str, dict] = {}
    allowed_links: dict[str, set[str]] = {}
    prov: dict[str, str] = {}
    for r in sorted(visible):
        props = objs[r]
        if _split(r)[0] in pub_t:
            fields[r], allowed_links[r], prov[r] = dict(props), set(), "none"
            continue
        cov = covering(rules, p, r, links, visible)
        al = [x for x in cov if x["effect"] == "allow"]
        dn = [x for x in cov if x["effect"] == "deny"]
        names: set[str] = set()
        for x in al:
            f = x["reveals"]["fields"]
            names |= set(props) if f == "*" else set(f)
        for x in dn:
            f = x["reveals"]["fields"]
            names -= set(props) if f == "*" else set(f)
        fields[r] = {n: props[n] for n in sorted(names) if n in props}
        lt = {l for x in al for l in x["reveals"]["links"]} - {l for x in dn for l in x["reveals"]["links"]}
        allowed_links[r] = lt
        lvl = max((ORDER[x["reveals"]["provenance"]] for x in al), default=0)
        if any(x["reveals"]["provenance"] != "none" for x in dn):
            lvl = 0
        prov[r] = next(k for k, v in ORDER.items() if v == lvl)
    vis_links = {(lt, a, b) for (lt, a, b) in links if a in visible and b in visible
                 and (lt in pub_l or lt in allowed_links.get(a, ()) or lt in allowed_links.get(b, ()))}
    return LowView(observer, fields, vis_links, prov, facts, ops_spec, auth_spec, acted)
