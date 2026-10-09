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
    anchor_proc: object = None

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


LIVE_ANCHORS: list = []  # anchors started by make_g3(history=True); killed after each test by the autouse fixture in conftest.py


def stop_live_anchors():
    while LIVE_ANCHORS:
        p = LIVE_ANCHORS.pop().proc
        if p.poll() is None:
            p.kill()
        p.wait()
        for f in (p.stdout, p.stderr):
            if f:
                f.close()


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
    hist = anc = proc = None
    if history:
        import os
        import tempfile
        from r3_shared.anchor import start_anchor
        from r3_shared.histstore import HistoryStore
        tmp = tempfile.mkdtemp(prefix="g3c")
        hist = HistoryStore(str(tmp_path / "hist.db"))
        proc = start_anchor(os.path.join(tmp, "anchor"), os.path.join(tmp, "s"))
        anc = proc.client()
        LIVE_ANCHORS.append(proc)
    dep = variant.deploy(domain, store.handle_factory(), idp.verifier(), ops, auth, clock, None, hist, anc, gov)
    rig = G3Rig(domain, store, store.reader(), clock, idp, dep, ops, auth, gov, variant, hist=hist)
    rig.anchor_proc = proc
    return rig


def refused(res, status, reason):
    assert (res.status, res.body) == (status, {"reason": reason}), res


def no_effect_refusal(rig, fn, status, reason):
    """The call is refused with the exact frozen body and leaves NO world change (objects, links, log)."""
    before, head = rig.snap(), len(rig.reader.log())
    res = fn()
    refused(res, status, reason)
    assert diff(before, rig.snap()) == [] and len(rig.reader.log()) == head, "a refused action left world effects"


def canon(res) -> str:
    """Canonical bytes of one observation (status + full body); lists of descriptors/events are canonicalised too."""
    if isinstance(res, list):
        return json.dumps([{"name": t.name, "input_schema": t.input_schema} for t in res], sort_keys=True)
    return json.dumps({"status": res.status, "body": res.body}, sort_keys=True)


def vary(rig, ref: str, **props):
    """Change protected facts in the world store as ONE autocommit transaction (equal schedule shape in paired worlds)."""
    t, k = ref.split(":", 1)
    h = rig.store.handle("seed")
    h.update(t, k, props)
    h.close()
