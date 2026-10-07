"""Policy decision point with the PROT-H24 delegation table (EQUIVALENCE-G2 'conventional').

`Pdp` = the H23 PolicyEngine (base authority, static delegates: unchanged) + capability edges evaluated at the commit
point against the table version in force. The decision is a pure function of (document, subject, on_behalf_of,
operation, resources, commit tick): no token ever carries authority.
"""
from __future__ import annotations

from . import authdoc
from .policy import Decision, PolicyEngine, Resource, op_match


class Pdp(PolicyEngine):
    def __init__(self, doc: dict, version: int = 1, mutants: frozenset[str] = frozenset()):
        super().__init__(doc, version)
        self.mutants = mutants

    def is_static_delegate(self, pid: str) -> bool:
        p = self._principals.get(pid)
        return bool(p and p["delegated_by"] is not None)

    def root_may_delegate(self, issuer: str, ops: list[str]) -> bool:
        """Root edge (PROT-H24 s2.5): every op needs an allow grant with delegable:true whose selector can match the issuer."""
        if not self.known(issuer):
            return False
        return all(any(g["effect"] == "allow" and g.get("delegable") and op_match(g["operation"], op)
                       and self._principal_match(g["principal"], issuer, None) for g in self._grants) for op in ops)

    def decide(self, subject: str, on_behalf_of: str | None, op: str, resources: list[Resource],
               tick: int = 0) -> Decision:
        if not authdoc.is_v2(self.doc) or not self.known(subject) or self.is_static_delegate(subject):
            return super().decide(subject, on_behalf_of, op, resources)  # H23 rule, unchanged
        if on_behalf_of is None:  # edges never apply without on_behalf_of
            ok, _ = self._self_allowed(subject, op, resources)
            return Decision(ok, "allowed" if ok else "no_matching_allow_or_denied", subject, None, op, self.version)
        path = self.valid_path(subject, on_behalf_of, op, resources, tick)
        if path is None:
            return Decision(False, "no_valid_path", subject, on_behalf_of, op, self.version)
        return Decision(True, "allowed", subject, on_behalf_of, op, self.version, tuple(e["id"] for e in path))

    def valid_path(self, subject: str, q: str, op: str, resources: list[Resource], tick: int) -> list[dict] | None:
        """First VALID path (PROT-H24 s3 a-f) for a request by `subject` on behalf of root principal `q`."""
        if not self.known(q) or self.is_static_delegate(q):
            return None
        for p in authdoc.paths_to(self.doc, subject):
            if p[0]["issuer"] != q:                                                                         # (a)
                continue
            if not authdoc.path_valid(self.doc, p, tick, self.mutant("expiry_inclusive")):                  # (b)(c)
                continue
            if not authdoc.in_every_scope(p, op, resources, self.mutant("non_attenuating_delegation")):     # (d)
                continue
            if not self._self_allowed(q, op, resources)[0]:                                                  # (e)
                continue
            if any(self._matching(who, op, resources, "deny") for who in {subject} | {e["issuer"] for e in p}):  # (f)
                continue
            return p
        return None

    def exposed_operations(self, subject: str, operations, _depth: int = 0) -> list[str]:
        base = super().exposed_operations(subject, operations, _depth)
        if not authdoc.is_v2(self.doc) or not self.known(subject) or self.is_static_delegate(subject):
            return base
        held = {o for e in self.doc["capabilities"] if e["child"] == subject for o in e["scope"]["operations"]}
        return [op for op in operations if op in base or op in held]  # static upper bound; decide() re-checks at commit

    def mutant(self, name: str) -> bool:
        return name in self.mutants

    def approval_forbidden(self, requester: str, on_behalf_of: str | None) -> set[str]:
        """Q plus every issuer on any edge path from Q to the requester (PROT-H24 s3, approvals)."""
        out: set[str] = set()
        if on_behalf_of is not None and authdoc.is_v2(self.doc):
            for p in authdoc.paths_to(self.doc, requester):
                if p[0]["issuer"] == on_behalf_of:
                    out |= {e["issuer"] for e in p}
        return out
