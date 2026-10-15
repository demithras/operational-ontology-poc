"""Gate 3 test rig (Paladin): a world with a clock, governance in force, optional v3 authority and history+anchor."""
from __future__ import annotations

import copy
import itertools
import json
from pathlib import Path

from paladin.core import AUDIENCE
from paladin.variant import PaladinVariant
from r3_shared.authspec import load_auth_spec
from r3_shared.clock import LogicalClock
from r3_shared.governance import load_governance
from r3_shared.identity import IdentityProvider
from r3_shared.opsspec import load_ops_spec
from r3_shared.world import WorldStore, diff

ROOT = Path(__file__).resolve().parents[2]
_n = itertools.count(1)


def load_v3(domain: str) -> dict:
    return json.loads((ROOT / "spec" / "authority" / f"{domain}.v3.json").read_text())


class G3Rig:
    def __init__(self, tmp: Path, domain="project", model="hierarchical", mutants=(), auth=None, governance="fixture",
                 history=None, anchor=None, v3=False):
        self.tmp, self.domain, self.mutants = tmp, domain, tuple(mutants)
        self.ops = load_ops_spec(domain)
        self.auth = auth or (load_v3(domain) if v3 else load_auth_spec(domain))
        self.gov = load_governance(model, domain) if governance == "fixture" else governance
        self.clock, self.idp = LogicalClock(), IdentityProvider("g3-secret")
        self.store = WorldStore(tmp / f"{domain}-{next(_n)}.sqlite", clock=self.clock)
        seed = self.store.handle("seed")
        for o in self.ops["seed"]["objects"]:
            seed.create(o["type"], o["key"], o["props"])
        for lk in self.ops["seed"]["links"]:
            seed.link(lk["link_type"], lk["src"], lk["dst"])
        self.reader = self.store.reader()
        self.history, self.anchor = history, anchor
        self.state_dir = None if history is not None else str(tmp / f"state-{next(_n)}")
        self.dep = self.deploy()
        self.n = 0

    def deploy(self):
        return PaladinVariant(self.mutants).deploy(self.domain, self.store.handle_factory(), self.idp.verifier(), self.ops,
                                                   self.auth, self.clock, state_dir=self.state_dir, history=self.history,
                                                   anchor=self.anchor, governance=self.gov)

    def tok(self, sub: str) -> str:
        return self.idp.issue(sub, AUDIENCE, 10 ** 6, self.clock)

    def rid(self, p="r") -> str:
        self.n += 1
        return f"{p}{self.n}"

    def act(self, sub: str, kind: str, rid=None, **kw):
        return self.dep.constitutional(self.tok(sub), {"kind": kind, **kw}, rid or self.rid())

    def propose(self, sub, case, op, args, obo=None, rid=None):
        return self.act(sub, "propose", rid, case=case, operation=op, args=args, on_behalf_of=obo)

    def judge(self, sub, case, value, stage="decision", merit="m", rid=None):
        return self.act(sub, "judge", rid, case=case, stage=stage, value=value, merit=merit)

    def snap(self):
        return self.reader.snapshot()

    def log(self, after=0):
        return self.reader.log(after)

    def head(self) -> int:
        return self.snap()["log_head"]

    def gov_marks(self, after=0):
        return [m for m in self.log(after) if m["kind"] == "mark" and m["ref"] == "governance"]

    def effects_of(self, fn):
        before = self.snap()
        res = fn()
        return res, diff(before, self.snap())

    def adv(self, n=1):
        self.clock.advance(n)


def renamed(doc: dict, ren) -> dict:
    """The governance document with every body id / matter id / model id passed through `ren` (R25-6 metamorphic test)."""
    d = copy.deepcopy(doc)
    d["model"] = ren(d["model"])
    for b in d["bodies"]:
        b["id"] = ren(b["id"])
    d["superior"] = [[ren(a), ren(b)] for a, b in d["superior"]]
    for m in d["matters"]:
        m["id"] = ren(m["id"])
        m["competent"] = [ren(x) for x in m["competent"]]
        if m["review"]:
            m["review"]["by"] = ren(m["review"]["by"])
    if d["emergency"]:
        d["emergency"]["matter"] = ren(d["emergency"]["matter"])
        d["emergency"]["grantees_from"] = ren(d["emergency"]["grantees_from"])
    return d
