"""Immutable reference authority DAG (spec/protections/PROT-H24.md ss1-5). Pure functions over frozen facts.

`RefAuthority.from_spec(v2_spec)` -> immutable value. `apply(event)` returns a NEW value. Every event carries the
world_log `seq` of its commit point and the commit `tick` (both stamped by the world store, never by a variant).
`issue_*` give the issuance verdict of PROT-H24 s2/s5; `decide` gives the use verdict of s3 for a commit point
(seq, tick): (allow, reason, valid_paths). Reads no clock, imports no variant (tests/test_h24_oracle.py scans this file).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import NamedTuple

from . import authority
from . import scope_v2 as sc

INF = 10 ** 18
V2 = "r3-authority-2"


class Verdict(NamedTuple):
    ok: bool
    status: str  # OK | DENIED | INVALID
    reason: str


class Decision(NamedTuple):
    allow: bool
    reason: str
    valid_paths: tuple  # tuple of tuples of edge ids, root edge first


@dataclass(frozen=True)
class Event:
    seq: int
    tick: int
    kind: str  # delegate | revoke | set_authority
    payload: str  # canonical JSON (immutable): {"edge": {...}} | {"edge_id": id} | {"spec": {...}}

    @property
    def data(self) -> dict:
        return json.loads(self.payload)


def event(seq: int, tick: int, kind: str, payload: dict) -> Event:
    if kind not in ("delegate", "revoke", "set_authority"):
        raise ValueError(f"bad event kind {kind}")
    return Event(seq, tick, kind, json.dumps(payload, sort_keys=True, separators=(",", ":")))


class _State(NamedTuple):
    base: dict
    edges: dict  # id -> edge, issuance order
    revoked: frozenset
    max_depth: int


def _split(spec: dict) -> tuple[dict, list, list]:
    base = {k: v for k, v in spec.items() if k not in ("capabilities", "revoked")}
    return base, list(spec.get("capabilities", [])), list(spec.get("revoked", []))


@lru_cache(maxsize=512)
def _state(base_json: str, events: tuple, seq: int) -> _State:
    base = json.loads(base_json)
    edges: dict = {}
    revoked: set = set()
    for ev in events:
        if ev.seq >= seq:
            break
        d = ev.data
        if ev.kind == "delegate":
            edges[d["edge"]["id"]] = d["edge"]
        elif ev.kind == "revoke":
            revoked.add(d["edge_id"])
        else:
            base, _, _ = _split(d["spec"])
    return _State(base, edges, frozenset(revoked), base.get("max_delegation_depth", 8))


def _path(edges: dict, eid: str) -> list[dict]:
    out, cur, seen = [], eid, set()
    while cur is not None and cur in edges and cur not in seen:
        seen.add(cur)
        out.append(edges[cur])
        cur = edges[cur]["parent"]
    return out[::-1]


def _static_match(sel: dict, p: dict) -> bool:
    if sel.get("any"):
        return True
    if "role" in sel:
        return sel["role"] in p["roles"]
    if "id" in sel:
        return sel["id"] == p["id"]
    if "relation" in sel:
        return any(r["type"] == sel["on_type"] and r["relation"] == sel["relation"] for r in p["relations"])
    return False


def _root_covered(base: dict, issuer: str, ops: list[str]) -> bool:
    """PROT-H24 2.5 (root): every op matched by an allow grant with delegable:true whose principal selector can match
    the issuer, and not statically denied for the issuer (static upper bound)."""
    p = authority._principal(base, issuer)
    if p is None:
        return False
    for op in ops:
        if any(g["effect"] == "deny" and authority._op_match(g["operation"], op) and _static_match(g["principal"], p)
               for g in base["grants"]):
            return False
        if not any(g["effect"] == "allow" and g["delegable"] and authority._op_match(g["operation"], op)
                   and _static_match(g["principal"], p) for g in base["grants"]):
            return False
    return True


@dataclass(frozen=True)
class RefAuthority:
    base_json: str
    events: tuple = ()

    @classmethod
    def from_spec(cls, spec: dict) -> "RefAuthority":
        if spec.get("spec") != V2:
            raise ValueError("RefAuthority needs an r3-authority-2 spec")
        base, caps, rev = _split(spec)
        evs = [event(0, 0, "delegate", {"edge": e}) for e in caps] + [event(0, 0, "revoke", {"edge_id": r}) for r in rev]
        return cls(json.dumps(base, sort_keys=True, separators=(",", ":")), tuple(evs))

    def apply(self, ev: Event) -> "RefAuthority":
        if self.events and ev.seq <= self.events[-1].seq and ev.seq != 0:
            raise ValueError(f"event seq {ev.seq} not after {self.events[-1].seq}")
        return RefAuthority(self.base_json, self.events + (ev,))

    # -- views at a commit point ----------------------------------------------------------------------
    def view(self, seq: int | None = None) -> _State:
        return _state(self.base_json, self.events, INF if seq is None else seq)

    def digest_at(self, seq: int | None = None) -> str:
        st = self.view(seq)
        return sc.digest(st.base, list(st.edges.values()), st.revoked)

    def edge_path(self, edge_id: str, seq: int | None = None) -> list[dict]:
        return _path(self.view(seq).edges, edge_id)

    # -- issuance (PROT-H24 s2) -----------------------------------------------------------------------
    def issue_delegate(self, edge, seq: int, tick: int) -> Verdict:
        """Verdict for Deployment.delegate decided at the commit point (seq, tick). Token validity is the caller's."""
        if not sc.well_formed(edge):
            return Verdict(False, "INVALID", "schema")
        st = self.view(seq)
        if edge["id"] in st.edges:
            return Verdict(False, "INVALID", "duplicate_edge")
        iss, child, par = edge["issuer"], edge["child"], edge["parent"]
        pe = st.edges.get(par) if par is not None else None
        ppath = _path(st.edges, par) if pe is not None else []
        if iss == child or child in {e["issuer"] for e in ppath}:
            return Verdict(False, "INVALID", "delegation_cycle")
        pdef = {p["id"]: p for p in st.base["principals"]}
        if any(x in pdef and pdef[x]["delegated_by"] is not None for x in (iss, child)):
            return Verdict(False, "INVALID", "static_delegate")
        if iss not in pdef or child not in pdef:
            return Verdict(False, "INVALID", "unknown_principal")
        if par is not None:
            if pe is None:
                return Verdict(False, "INVALID", "unknown_parent")
            if iss != pe["child"]:
                return Verdict(False, "DENIED", "not_parent_holder")
            if any(e["id"] in st.revoked for e in ppath) or any(
                    e["expires_at"] is not None and tick >= e["expires_at"] for e in ppath):
                return Verdict(False, "DENIED", "parent_invalid")
            if not pe["redelegable"]:
                return Verdict(False, "DENIED", "not_redelegable")
            if len(ppath) + 1 > st.max_depth:
                return Verdict(False, "INVALID", "depth_exceeded")
            if not sc.subset(edge["scope"], pe["scope"]):
                return Verdict(False, "DENIED", "scope_amplification")
            if pe["expires_at"] is not None and (edge["expires_at"] is None or edge["expires_at"] > pe["expires_at"]):
                return Verdict(False, "DENIED", "expiry_amplification")
        elif not _root_covered(st.base, iss, edge["scope"]["operations"]):
            return Verdict(False, "DENIED", "scope_amplification")
        if edge["expires_at"] is not None and edge["expires_at"] <= tick:
            return Verdict(False, "INVALID", "already_expired")
        return Verdict(True, "OK", "")

    def issue_revoke(self, actor: str, edge_id: str, seq: int) -> Verdict:
        """PROT-H24 s5. OK with reason `already` writes no mark (the caller must expect none)."""
        st = self.view(seq)
        if edge_id not in st.edges:
            return Verdict(False, "INVALID", "unknown_edge")
        if actor not in {e["issuer"] for e in _path(st.edges, edge_id)}:
            return Verdict(False, "DENIED", "not_revoker")
        return Verdict(True, "OK", "already" if edge_id in st.revoked else "")

    # -- use (PROT-H24 s3) ------------------------------------------------------------------------------
    def decide(self, subject: str, obo: str | None, op: str, resources, seq: int | None, tick: int) -> Decision:
        """Is the request effective at commit point (seq, tick)? `seq` None = after every known event."""
        st = self.view(seq)
        res = [tuple(r) for r in resources]
        me = authority._principal(st.base, subject)
        if me is None:
            return Decision(False, "unknown_principal", ())
        if me["delegated_by"] is not None or obo is None:  # H23 rule unchanged; edges never apply
            d = authority.decide(subject, obo, op, res, st.base)
            return Decision(d.allow, d.reason, ())
        root_ok = authority.decide(obo, None, op, res, st.base).allow  # (e) root re-check
        paths = []
        for e in st.edges.values():
            if e["child"] != subject:
                continue
            p = _path(st.edges, e["id"])
            if p[0]["issuer"] != obo:  # (a)
                continue
            if any(x["id"] in st.revoked for x in p):  # (b)
                continue
            if any(x["expires_at"] is not None and tick >= x["expires_at"] for x in p):  # (c) strict
                continue
            if not all(sc.covers(x["scope"], op, res) for x in p):  # (d) intersection
                continue
            who = [subject] + [x["issuer"] for x in p]
            if any(authority._matching(st.base, "deny", authority._principal(st.base, w), op, res)
                   for w in who if authority._principal(st.base, w) is not None):  # (f)
                continue
            paths.append(tuple(x["id"] for x in p))
        if not root_ok:
            return Decision(False, "root_lost_authority" if paths else "no_valid_path", ())
        if not paths:
            return Decision(False, "no_valid_path", ())
        return Decision(True, "valid_path", tuple(sorted(paths)))

    def was_ever_valid(self, subject, obo, op, resources, seq: int, tick: int) -> bool:
        """True iff the request was allowed at some earlier commit point (seq' <= seq, tick' <= tick, not both equal):
        the stale-path test that separates post_boundary_effect from a plain forbidden_effect."""
        seqs = {e.seq + 1 for e in self.events if e.seq < seq} | {1}
        ticks = {e.tick for e in self.events if e.tick <= tick} | {0, max(tick - 1, 0)}
        for s in sorted(seqs):
            for t in sorted(ticks):
                if (s, t) != (seq, tick) and s <= seq and t <= tick and self.decide(subject, obo, op, resources, s, t).allow:
                    return True
        return False

    def depth_of(self, edge_id: str) -> int:
        return len(self.edge_path(edge_id))
