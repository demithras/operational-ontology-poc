"""Policy decision point: a small ABAC/ReBAC engine over the neutral authority spec (spec/authority/<domain>.json).

Pure and stateless per authority version: decide() depends only on (spec, subject, on_behalf_of, operation, resources).
Deny overrides allow; no matching allow means deny. The acting subject is always the verified token subject.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Iterable

from r3_shared.authgraph import authority_digest

Resource = tuple[str, str]  # (type, key)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    subject: str
    on_behalf_of: str | None
    operation: str
    authority_version: int
    path: tuple = ()  # PROT-H24: edge ids of the delegation path the decision relied on ([] = base authority / H23 rule)


def op_match(pattern: str, op: str) -> bool:
    return pattern == op or pattern == "*" or (pattern.endswith(":*") and op.startswith(pattern[:-1]))


class PolicyEngine:
    def __init__(self, auth_spec: dict, version: int = 1):
        spec = copy.deepcopy(auth_spec)  # the engine owns its copy; later mutation of the caller's dict changes nothing
        self.version = version
        self.doc = spec
        self.digest = authority_digest(spec)  # PROT-H24: v2 documents hash with capabilities in issuance order
        self._principals = {p["id"]: p for p in spec["principals"]}
        self._grants = list(spec["grants"])
        self._delegations = list(spec["delegations"])
        self._relations = {pid: {(r["type"], r["key"], r["relation"]) for r in p["relations"]}
                           for pid, p in self._principals.items()}

    # -- principal / resource selectors ------------------------------------------------------
    def known(self, pid: str) -> bool:
        return pid in self._principals

    def holds(self, pid: str, type_: str, key: str, relation: str) -> bool:
        return (type_, key, relation) in self._relations.get(pid, ())

    def _principal_match(self, sel: dict, pid: str, resources: Iterable[Resource] | None) -> bool:
        p = self._principals[pid]
        if sel.get("any"):
            return True
        if "role" in sel:
            return sel["role"] in p["roles"]
        if "id" in sel:
            return sel["id"] == pid
        if "relation" in sel:
            if resources is None:  # static view (tool exposure): the relation is held on at least one resource
                return any(r["type"] == sel["on_type"] and r["relation"] == sel["relation"] for r in p["relations"])
            of_type = [k for t, k in resources if t == sel["on_type"]]
            return bool(of_type) and all(self.holds(pid, sel["on_type"], k, sel["relation"]) for k in of_type)
        return False

    @staticmethod
    def _resource_match(sel: dict, resources: Iterable[Resource] | None) -> bool:
        if resources is None or sel.get("any"):
            return True
        if "state" in sel:  # state-conditioned pseudo-operation grants never govern a request's own resources
            return False
        return any(t == sel.get("type") for t, _ in resources)

    def _matching(self, pid: str, op: str, resources: list[Resource] | None, effect: str) -> list[dict]:
        return [g for g in self._grants
                if g["effect"] == effect and op_match(g["operation"], op)
                and self._principal_match(g["principal"], pid, resources)
                and self._resource_match(g["resource"], resources)]

    # -- decisions -------------------------------------------------------------------------------
    def _self_allowed(self, pid: str, op: str, resources: list[Resource]) -> tuple[bool, list[dict]]:
        allows = self._matching(pid, op, resources, "allow")
        denies = self._matching(pid, op, resources, "deny")
        return bool(allows) and not denies, allows

    def decide(self, subject: str, on_behalf_of: str | None, op: str, resources: list[Resource]) -> Decision:
        def d(ok: bool, why: str) -> Decision:
            return Decision(ok, why, subject, on_behalf_of, op, self.version)

        if not self.known(subject):
            return d(False, "unknown_principal")
        delegator = self._principals[subject]["delegated_by"]
        if on_behalf_of is not None and on_behalf_of != delegator:  # also covers delegated_by null + on_behalf_of
            return d(False, "on_behalf_of_not_delegator")
        if delegator is None:
            ok, _ = self._self_allowed(subject, op, resources)
            return d(ok, "allowed" if ok else "no_matching_allow_or_denied")
        # a delegate is ALWAYS evaluated as its delegator's delegate (rules a-d), with or without on_behalf_of
        on_behalf_of = delegator
        if not self.known(on_behalf_of):
            return d(False, "unknown_delegator")
        if not any(x["agent"] == subject and x["on_behalf_of"] == on_behalf_of and op in x["operations"]
                   for x in self._delegations):
            return d(False, "no_delegation")
        if self._matching(subject, op, resources, "deny") or self._matching(on_behalf_of, op, resources, "deny"):
            return d(False, "denied_by_deny_grant")
        if not any(g.get("delegable") for g in self._matching(subject, op, resources, "allow")):
            return d(False, "no_delegable_grant")
        ok, _ = self._self_allowed(on_behalf_of, op, resources)
        return d(ok, "allowed" if ok else "delegator_not_allowed")

    def effective_principal(self, subject: str) -> str:
        """The principal business rules see: the delegator for a delegate, else the subject itself."""
        p = self._principals.get(subject)
        return p["delegated_by"] if p and p["delegated_by"] else subject

    def chain(self, pid: str) -> set[str]:
        out, cur = set(), pid
        while cur is not None and cur in self._principals and cur not in out:
            out.add(cur)
            cur = self._principals[cur]["delegated_by"]
        return out

    def can_approve(self, approver: str, requester: str, on_behalf_of: str | None, approval_op: str,
                    resources: list[Resource], extra_forbidden: Iterable[str] = ()) -> bool:
        if not self.known(approver) or not self.known(requester):
            return False
        forbidden = {requester} | self.chain(requester) | ({on_behalf_of} | self.chain(on_behalf_of) if on_behalf_of else set())
        forbidden |= set(extra_forbidden)  # PROT-H24 s3: Q and every issuer on any edge path from Q to the requester
        if approver in forbidden:
            return False
        return self._self_allowed(approver, approval_op, resources)[0]

    def exposed_operations(self, subject: str, operations: Iterable[str], _depth: int = 0) -> list[str]:
        """Operations the subject (or, for a delegate, its delegator chain) could be granted on SOME resource (static
        upper bound). Not a protection: the service re-decides every request."""
        if not self.known(subject) or _depth > 16:
            return []
        delegator = self._principals[subject]["delegated_by"]
        out = []
        for op in operations:
            allows = self._matching(subject, op, None, "allow")
            if not allows or self._matching(subject, op, None, "deny"):
                continue
            if delegator is not None and not (  # a delegate sees only what its delegation entry lists (same as decide())
                    any(x["agent"] == subject and x["on_behalf_of"] == delegator and op in x["operations"]
                        for x in self._delegations)
                    and any(g.get("delegable") for g in allows)
                    and self.exposed_operations(delegator, [op], _depth + 1)):
                continue
            out.append(op)
        return out
