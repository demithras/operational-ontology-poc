"""Gate 2 test helpers (conventional): a v2-authority rig with optional HistoryStore + anchor process. Hand-written
expectations only: nothing here imports the oracle or the harness."""
from __future__ import annotations

import copy
import os
import shutil
import tempfile
from dataclasses import dataclass

from conventional.variant import AUDIENCE, ConventionalVariant
from r3_shared.anchor import start_anchor
from r3_shared.authspec import load_auth_spec
from r3_shared.clock import LogicalClock
from r3_shared.histstore import HistoryStore
from r3_shared.identity import IdentityProvider
from r3_shared.opsspec import load_ops_spec
from r3_shared.world import WorldStore

TRANSFER = {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 10}
WH, PART = {"type": "Warehouse", "keys": None}, {"type": "Part", "keys": None}


def v2_spec(domain: str = "manufacturing", extra_edges=(), revoked=()) -> dict:
    """The H23 spec + a delegable planner grant (a root edge needs one) + an empty (or given) delegation table."""
    a = copy.deepcopy(load_auth_spec(domain))
    a["grants"].append({"id": "transfer-planner-delegable", "effect": "allow", "operation": "transfer_inventory",
                        "principal": {"on_type": "Warehouse", "relation": "planner"}, "resource": {"type": "Warehouse"},
                        "delegable": True, "origin": "neutral-extension"})
    return {**a, "spec": "r3-authority-2", "max_delegation_depth": 8, "capabilities": list(extra_edges),
            "revoked": list(revoked)}


def edge(eid, issuer, child, parent=None, ops=("transfer_inventory",), res=(WH, PART), expires=None, redel=True,
         issued=0):
    return {"id": eid, "issuer": issuer, "child": child, "parent": parent,
            "scope": {"operations": list(ops), "resources": [dict(r) for r in res]},
            "expires_at": expires, "redelegable": redel, "issued_at": issued}


@dataclass
class G2Rig:
    store: WorldStore
    reader: object
    clock: LogicalClock
    idp: IdentityProvider
    dep: object
    ops: dict
    auth: dict
    variant: object
    history: HistoryStore | None = None
    anchor: object | None = None
    anchor_proc: object | None = None
    tmp: str = ""

    def token(self, sub: str, ttl: int = 100000) -> str:
        return self.idp.issue(sub, AUDIENCE, ttl, self.clock)

    def snap(self):
        return self.reader.snapshot()

    def log(self, after=0):
        return self.reader.log(after)

    def marks(self, ref=None):
        return [r for r in self.log() if r["kind"] == "mark" and (ref is None or r["ref"] == ref)]

    def redeploy(self, history=None):
        """A FRESH deployment over the same world (and history/anchor), empty state."""
        return self.variant.deploy("manufacturing", self.store.handle_factory(), self.idp.verifier(), self.ops, self.auth,
                                   self.clock, None, history or self.history, self.anchor)

    def close(self):
        if self.anchor_proc is not None and self.anchor_proc.proc.poll() is None:
            self.anchor_proc.proc.kill()
        shutil.rmtree(self.tmp, ignore_errors=True)


def make_g2(tmp_path, mutants=(), with_history=False, spec=None, start=2, domain="manufacturing") -> G2Rig:
    ops, auth = load_ops_spec(domain), spec or v2_spec(domain)
    clock = LogicalClock(start)
    store = WorldStore(tmp_path / "w.db", clock=clock)
    h = store.handle("seed")
    for o in ops["seed"]["objects"]:
        h.create(o["type"], o["key"], o["props"])
    for lk in ops["seed"]["links"]:
        h.link(lk["link_type"], lk["src"], lk["dst"])
    h.close()
    idp, variant = IdentityProvider("test-secret-123"), ConventionalVariant(mutants)
    hist = anc = proc = None
    tmp = tempfile.mkdtemp(prefix="g2c")
    if with_history:
        hist = HistoryStore(str(tmp_path / "hist.db"))
        proc = start_anchor(os.path.join(tmp, "anchor"), os.path.join(tmp, "s"))
        anc = proc.client()
    dep = variant.deploy(domain, store.handle_factory(), idp.verifier(), ops, auth, clock, None, hist, anc)
    return G2Rig(store, store.reader(), clock, idp, dep, ops, auth, variant, hist, anc, proc, tmp)
