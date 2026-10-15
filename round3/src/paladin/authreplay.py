"""Authority re-evaluation over a BOUND authority artifact (PROT-H27 s6): the PROT-H23 rule / PROT-H24 s3 rule evaluated by the
vendored Engine's authority gate on a model compiled from the artifact itself - never from the current spec (R27-2).
Engines are cached by the artifact digest (a function of the verified bytes, so the cache cannot hold anything else)."""
from __future__ import annotations

from paladin import capgraph
from paladin.authcompile import delegation_table
from paladin.boot import boot
from paladin.engine import Principal
from paladin.engine.authority import Resource
from r3_shared.authgraph import authority_digest

# reason codes of refusals that were an AUTHORITY verdict (everything else passed the authority gate)
AUTH_DENY = {"authority", "delegation", "no_valid_path"}


class Reauth:
    def __init__(self, domain: str, ops_spec: dict):
        self.domain, self.ops, self._cache = domain, ops_spec, {}

    def _boot(self, doc: dict):
        key = authority_digest(doc)
        if key not in self._cache:
            self._cache[key] = boot(self.domain, self.ops, doc, lambda _w: None, None, lambda: 0)
        return self._cache[key]

    def _decide(self, b, who: Principal, op: str, resources: tuple):
        spec = b.engine.model.get("actions", op)
        res = tuple(resources) + tuple(Resource(e.target, None, e.target) for e in spec.effects)
        return b.engine.dispatch("authority_rules", "decide", None, refs=spec.auth_refs, principal=who,
                                 capability=f"action:{op}", resources=res, view=None)

    def allowed(self, doc: dict, sub: str, obo, op: str, refs: list, tick: int, path: list) -> bool:
        """refs: ["T:k", ...] of the bound evidence (absent objects omitted); path: the recorded edge ids."""
        b = self._boot(doc)
        if op not in {a for a in b.engine.model.all("actions")} or sub not in b.principals:
            return False
        resources = tuple(Resource(t, k, t) for t, k in (r.split(":", 1) for r in refs))
        delegator = {p["id"]: p["delegated_by"] for p in doc["principals"]}.get(sub)
        if delegator is not None:  # PROT-H23 static delegate: always evaluated as its delegator's delegate
            if obo is not None and obo != delegator or op not in delegation_table(doc).get((sub, delegator), ()):
                return False
            d = b.principals.get(delegator)
            return d is not None and self._decide(b, Principal(sub, b.principals[sub].roles, b.principals[sub].relations, d),
                                                  op, resources).allowed
        if obo is None:
            return self._decide(b, b.principals[sub], op, resources).allowed
        if obo not in b.principals:
            return False
        R = [(r.actual, r.key) for r in resources]
        got = capgraph.find_path(doc, capgraph.candidates(doc, sub, obo), op, R, tick,
                                 lambda pid: bool(pid in b.principals and self._decide(b, b.principals[pid], op, resources).deny))
        if got is None or (path and got != list(path) and list(path) not in [[e["id"] for e in p]
                                                                           for p in capgraph.candidates(doc, sub, obo)]):
            return False
        return self._decide(b, b.principals[obo], op, resources).allowed
