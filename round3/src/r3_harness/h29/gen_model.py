"""Generator-side prediction (ORACLE-AND-HARNESS-G5 s2): a model of the AuthorityService publish/lease rule, the scheduled fault windows
(Phi), the predicted world (oracle Replayer) and the clock. Reachability and validity are built in: every request is evaluated by the
ORACLE on the predicted snapshot before it is emitted. This model only PLANS; the judge re-derives everything from the service logs."""
from __future__ import annotations

import copy
import hashlib
import json

from r3_oracle import continuity as C
from r3_oracle.recoverymodel import Replayer

from . import faults, specs


def digest_of(doc: dict) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class ServiceModel:
    """Mirror of authsvc_server.Core.publish/fetch for ONE deployment (versions + leases). Rows use the service log shape."""

    def __init__(self):
        self.versions, self.leases = [], []

    def publish(self, doc: dict, t: int) -> dict:
        dg = digest_of(doc)
        lu = max([l["lease_until"] for l in self.leases if l["digest"] != dg] or [0])
        prev = max([v["effective_tick"] for v in self.versions] or [0])
        f = max(t, lu, prev)
        row = {"seq": len(self.versions) + 1, "digest": dg, "doc": doc, "requested_tick": t, "effective_tick": f}
        self.versions.append(row)
        return row

    def renew(self, t: int) -> None:
        dg = C.authority_in_force(self.versions, t)
        if dg is not None:
            self.leases.append({"digest": dg, "granted_tick": t, "lease_until": C.grant_until(self.versions, t, faults.LEASE)})

    def doc_at(self, t: int):
        return C.doc_of(self.versions, C.authority_in_force(self.versions, t))


class Plan:
    """Mutable plan state while a sequence is being drawn."""

    def __init__(self, domain: str):
        self.domain = domain
        self.ops, self.auth0, self.systems = specs.load(domain)
        self.fam, self.graph = specs.family(domain), specs.graph()
        self.snap0 = specs.seed_snapshot(self.ops)
        for k, o in self.snap0["objects"].items():          # the driver refreshes evidence age to the sequence base (= relative tick 0)
            if k.startswith("EvidenceSnapshot:"):
                o["props"]["snapshotObservedAt"] = 0
        self.rep = Replayer(self.ops, self.snap0)
        self.model = ServiceModel()
        self.model.publish(copy.deepcopy(self.fam[0]), 0)              # G5-E2: version 0 at tick 0, before the first request
        self.steps, self.t, self.windows, self.kills = [], 0, [], []
        self.sends, self.crashed, self.n_req, self.fid = [], set(), 0, 0
        self.intents = {}                                                  # rid -> (tick, [I])
        self.class_windows = {}                                            # cls -> [[from, to)]
        self.approvals_pending = 0
        self.open_rec = False
        self.phi = C.Phi([], [])
        self.stats = {"redraw": 0}

    # ---- steps ---------------------------------------------------------------------------------------------------
    def add(self, st: dict) -> dict:
        self.steps.append(st)
        return st

    def advance(self, n: int) -> None:
        if n > 0:
            self.add({"op": "advance", "n": n})
            self.t += n

    def mark_class(self, cls: str, a: int, b: int) -> None:
        self.class_windows.setdefault(cls, []).append([a, b])

    def fault(self, cls: str, node: str, mode: str, duration: int, k: int | None = None) -> str:
        if self.sends and self.sends[-1]["t"] == self.t:
            self.advance(1)                      # a window never covers the tick of an earlier send (renewal evidence stays unambiguous)
        self.fid += 1
        fid = f"f{self.fid}"
        st = {"op": "fault_start", "fid": fid, "cls": cls, "node": node, "mode": mode, "duration": duration}
        if k is not None:
            st["k"] = k
        self.add(st)
        w = {"node": node, "mode": "drop" if node == "OBS" else mode, "from_tick": self.t, "to_tick": self.t + duration, "cls": cls, "fid": fid}
        self.windows.append(w)
        self.phi = C.Phi(self.windows, self.kills)
        self.mark_class(cls, self.t, self.t + duration)
        return fid

    def heal(self, fid: str) -> None:
        w = next(w for w in self.windows if w["fid"] == fid)
        self.add({"op": "fault_heal", "fid": fid})
        if self.t < w["to_tick"]:
            self.t = w["to_tick"]                       # the driver advances to the end of the window

    def renew_ticks(self) -> list:
        return C.lease_sends(self.sends, self.phi, self.graph, self.domain)

    def classify(self, kind: str, op, rid) -> C.Cls:
        q = {"kind": kind, "op": op, "t": self.t, "rid": rid}
        return C.classify(q, self.phi, self.graph, self.domain, self.renew_ticks(), self.model.versions, self.crashed)

    def note_send(self, kind: str, op, rid, invalid=False) -> C.Cls:
        cls = self.classify(kind, op, rid)
        self.sends.append({"kind": kind, "op": op, "t": self.t, "rid": rid, "invalid_probe": invalid})
        if "AUTH" in C.decision_deps(self.graph, self.domain, kind, op) and self.phi.mode("AUTH", self.t) is None and not invalid:
            self.model.renew(self.t)
        return cls

    def doc(self) -> dict:
        return self.model.doc_at(self.t) or self.fam[0]

    def new_rid(self, tag: str = "r") -> str:
        self.n_req += 1
        return f"{tag}{self.n_req:03d}"
