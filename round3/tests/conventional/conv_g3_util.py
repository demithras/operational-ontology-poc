"""Gate 3 test helpers (conventional): a v3-authority rig with a governance document and optional history. Hand-written
expectations only (frozen texts PROT-H25/PROT-H26); nothing here imports the oracle or the harness."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from conventional.variant import AUDIENCE, ConventionalVariant
from r3_shared.clock import LogicalClock
from r3_shared.governance import load_governance
from r3_shared.identity import IdentityProvider
from r3_shared.opsspec import load_ops_spec
from r3_shared.world import WorldStore, diff

ROOT = Path(__file__).resolve().parents[2]
RESCHEDULE = {"work_order_id": "WO-43", "new_planned_start": 35}
EXPEDITE = {"po_id": "PO-991", "expedite_fee": 100}


def v3_spec(domain: str) -> dict:
    return json.loads((ROOT / "spec" / "authority" / f"{domain}.v3.json").read_text())


@dataclass
class G3Rig:
    domain: str
    store: WorldStore
    reader: object
    clock: LogicalClock
    idp: IdentityProvider
    dep: object
    ops: dict
    auth: dict
    gov: dict | None
    variant: object
    n: int = 0
    hist: object = None

    def token(self, sub: str, ttl: int = 100000) -> str:
        return self.idp.issue(sub, AUDIENCE, ttl, self.clock)

    def snap(self):
        return self.reader.snapshot()

    def marks(self, ref="governance"):
        return [r for r in self.reader.log() if r["kind"] == "mark" and r["ref"] == ref]

    def rid(self, tag="r") -> str:
        self.n += 1
        return f"{tag}-{self.n}"

    def act(self, who: str, action: dict, rid: str | None = None):
        return self.dep.constitutional(self.token(who), action, rid or self.rid())

    def propose(self, who, case, op, args, obo=None, rid=None):
        return self.act(who, {"kind": "propose", "case": case, "operation": op, "args": args, "on_behalf_of": obo}, rid)

    def judge(self, who, case, stage, value, merit="m", rid=None):
        return self.act(who, {"kind": "judge", "case": case, "stage": stage, "value": value, "merit": merit}, rid)

    def simple(self, who, kind, rid=None, **kw):
        return self.act(who, {"kind": kind, **kw}, rid)

    def advance(self, n=1):
        self.clock.advance(n)


def make_g3(tmp_path, model="hierarchical", domain="manufacturing", mutants=(), governance="fixture", start=2,
            history=False, auth=None, sub="") -> G3Rig:
    tmp_path = Path(tmp_path) / sub
    tmp_path.mkdir(parents=True, exist_ok=True)
    ops, auth = load_ops_spec(domain), auth or v3_spec(domain)
    gov = load_governance(model, domain) if governance == "fixture" else governance
    clock = LogicalClock(start)
    store = WorldStore(Path(tmp_path) / "w.db", clock=clock)
    h = store.handle("seed")
    for o in ops["seed"]["objects"]:
        h.create(o["type"], o["key"], o["props"])
    for lk in ops["seed"]["links"]:
        h.link(lk["link_type"], lk["src"], lk["dst"])
    h.close()
    idp, variant = IdentityProvider("test-secret-123"), ConventionalVariant(mutants)
    dep = variant.deploy(domain, store.handle_factory(), idp.verifier(), ops, auth, clock, None, None, None, gov)
    return G3Rig(domain, store, store.reader(), clock, idp, dep, ops, auth, gov, variant)


def refused(res, status, reason):
    assert (res.status, res.body) == (status, {"reason": reason}), res


def no_effect_refusal(rig, fn, status, reason):
    """The call is refused with the exact frozen body and leaves NO world change (objects, links, log)."""
    before, head = rig.snap(), len(rig.reader.log())
    res = fn()
    refused(res, status, reason)
    assert diff(before, rig.snap()) == [] and len(rig.reader.log()) == head, "a refused action left world effects"
