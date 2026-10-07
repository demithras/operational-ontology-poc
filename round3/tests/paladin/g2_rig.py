"""Gate 2 test rig (Paladin): a world WITH a clock (tx.tick), v2 authority fixtures, optional HistoryStore + anchor process."""
from __future__ import annotations

import copy
import itertools
from pathlib import Path

from paladin.core import AUDIENCE
from paladin.variant import PaladinVariant
from r3_shared.anchor import start_anchor
from r3_shared.authspec import load_auth_spec
from r3_shared.clock import LogicalClock
from r3_shared.histstore import HistoryStore, TamperView
from r3_shared.identity import IdentityProvider
from r3_shared.opsspec import load_ops_spec
from r3_shared.world import WorldStore, diff

TR = {"source_warehouse": "WH-C", "destination_warehouse": "WH-B", "part": "PX-900", "quantity": 60}
SCOPE_TR = {"operations": ["transfer_inventory"], "resources": [{"type": "Warehouse", "keys": None}, {"type": "Part", "keys": None},
                                                                 {"type": "WorkOrder", "keys": None}]}
_n = itertools.count(1)


def v2_mfg() -> dict:
    """manufacturing authority + 6 fresh principals (ag-1..ag-6) + a delegable transfer grant for planners."""
    a = copy.deepcopy(load_auth_spec("manufacturing"))
    a["spec"], a["max_delegation_depth"], a["capabilities"], a["revoked"] = "r3-authority-2", 8, [], []
    for i in range(1, 7):
        a["principals"].append({"id": f"ag-{i}", "kind": "agent", "roles": [], "relations": [], "delegated_by": None})
    a["grants"].append({"id": "g24-planner-transfer", "operation": "transfer_inventory", "effect": "allow", "delegable": True,
                        "origin": "neutral-extension", "principal": {"on_type": "Warehouse", "relation": "planner"},
                        "resource": {"type": "Warehouse"}})
    return a


def edge(eid, issuer, child, parent=None, ops=None, resources=None, expires=None, redelegable=True, issued=0) -> dict:
    sc = {"operations": list(ops or ["transfer_inventory"]), "resources": copy.deepcopy(resources or SCOPE_TR["resources"])}
    return {"id": eid, "issuer": issuer, "child": child, "parent": parent, "scope": sc, "expires_at": expires,
            "redelegable": redelegable, "issued_at": issued}


class G2Rig:
    def __init__(self, tmp: Path, domain="manufacturing", mutants=(), auth=None, history=False, anchor=None):
        self.tmp, self.domain, self.mutants = tmp, domain, tuple(mutants)
        self.ops, self.auth = load_ops_spec(domain), auth or (v2_mfg() if domain == "manufacturing" else load_auth_spec(domain))
        self.clock, self.idp = LogicalClock(), IdentityProvider("g2-secret")
        self.store = WorldStore(tmp / f"{domain}.sqlite", clock=self.clock)
        seed = self.store.handle("seed")
        for o in self.ops["seed"]["objects"]:
            seed.create(o["type"], o["key"], o["props"])
        for l in self.ops["seed"]["links"]:
            seed.link(l["link_type"], l["src"], l["dst"])
        self.reader = self.store.reader()
        self.anchor = anchor
        self.hpath = tmp / "history.sqlite"
        self.history = HistoryStore(str(self.hpath)) if history else None
        self.state_dir = None if history else str(tmp / "state")
        self.dep = self.deploy()

    def deploy(self, history=None, anchor=None, state_dir="same"):
        h = history if history is not None else self.history
        return PaladinVariant(self.mutants).deploy(
            self.domain, self.store.handle_factory(), self.idp.verifier(), self.ops, self.auth, self.clock,
            state_dir=(self.state_dir if state_dir == "same" else state_dir), history=h,
            anchor=anchor if anchor is not None else self.anchor)

    def tamper(self) -> TamperView:
        return TamperView(str(self.hpath))

    def token(self, sub: str) -> str:
        return self.idp.issue(sub, AUDIENCE, 100000, self.clock)

    def rid(self) -> str:
        return f"g2-{next(_n)}"

    def snap(self) -> dict:
        return self.reader.snapshot()

    def log(self, after=0):
        return self.reader.log(after)

    def effects_of(self, fn):
        before = self.snap()
        res = fn()
        return res, diff(before, self.snap())

    def delegate(self, issuer, e, rid=None):
        return self.dep.delegate(self.token(issuer), e, rid or self.rid())

    def revoke(self, who, eid, rid=None):
        return self.dep.revoke(self.token(who), eid, rid or self.rid())

    def transfer(self, sub, obo, rid=None, args=None):
        return self.dep.direct(self.token(sub), "transfer_inventory", args or TR, on_behalf_of=obo, request_id=rid or self.rid())


def new_anchor(tmp: Path):
    import tempfile  # AF_UNIX paths are short: the socket lives in a short temp dir, the log under tmp
    return start_anchor(tmp / "anchor", str(Path(tempfile.mkdtemp(prefix="r3s")) / "s"))
