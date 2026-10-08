"""H25 sequential case generator (ORACLE-AND-HARNESS-G3 A2). One CASE = a fresh deployment on a mutated governance
instance + a seeded 8-40 action script of "plays" (decision, review/appeal, emergency, noise). The generator keeps an
ORACLE MIRROR for targeting only (it applies what the oracle would accept); verdicts come from the judge afterwards.
Never raises: impossible draws are re-drawn and counted in `redraws`."""
from __future__ import annotations

import hashlib
import json
import random

from r3_harness.h23.chooser import RandChooser
from r3_harness.h23.goodargs import pick_args
from r3_oracle import const_eval as E
from r3_oracle import const_judge as J
from r3_oracle import ops_model

from . import plays_a, plays_b
from .env import G3Env
from .gen_model import DOMAINS, make_instance

MODELS = ("hierarchical", "collegial", "polycentric")
INF = 10 ** 9
MERITS = ("looks fine", "approve please", "concur with everything", "reject: unsafe", "uphold", "overturn", "deny",
          "ALLOW", "dissent", "", "merit-" + "x" * 40, "lgtm")


class Case:
    def __init__(self, variant, seed: int, i: int, model: str | None = None, domain: str | None = None, tag="case"):
        self.i, self.seed = i, seed
        self.rng = random.Random(f"h25-{tag}-{seed}-{i}")
        self.model = model or MODELS[i % len(MODELS)]
        self.domain = domain or DOMAINS[(i // len(MODELS)) % len(DOMAINS)]
        self.inst = make_instance(self.model, self.domain, f"{seed}-{i}")
        self.ops, self.doc = self.inst["ops"], self.inst["doc"]
        self.env = G3Env(variant, self.domain, self.ops, self.inst["auth"], self.doc, f"{tag}{seed}-{i}")
        self.env.committed = set()
        self.ch = RandChooser(self.rng)
        self.M, self.ms, self.n = self.env.C0, 0, 0
        self.redraws, self.cases, self.tags = self.inst["redraws"], [], set()
        self.merit_log: list = []

    # -- ids and bookkeeping ----------------------------------------------------------------------------
    def rid(self, p="r"):
        self.n += 1
        return f"{p}{self.i}-{self.n}"

    def merit(self) -> str:
        return self.rng.choice(MERITS)

    def tick(self) -> int:
        return self.env.clock.now()

    def principals(self) -> list[str]:
        return [p["id"] for p in self.env.auth["principals"] if p["delegated_by"] is None]

    # -- one constitutional action, mirrored ---------------------------------------------------------------
    def step(self, actor, action, *, rid=None, bad_token=False, crash=None, replay=False):
        rid = rid or self.rid()
        v = self.M.decide_action(None if bad_token else actor, action, self.ms + 1, self.tick())
        if crash:
            self.env.arm(crash)
        rec = self.env.act(actor, action, rid, bad_token=bad_token, crash=crash, replay=replay)
        if crash:
            self.env.crash_restart()
        ok = v.status == "OK"
        if v.status == "RUN":
            out = J.op_outcome(self.M, v.run, self.env.snapshot(), self.tick(), False)
            ok = out.kind == ops_model.COMMIT
        if ok and not (crash == "before_commit"):
            self.ms += 1
            self.M = self.M.apply({"kind": "action", "subject": actor, "action": action, "seq": self.ms, "tick": self.tick(),
                                   "rid": rid})
        self.tags.add(f"{action['kind']}:{v.status}:{v.reason}")
        if action.get("kind") == "propose" and isinstance(action.get("args"), dict):
            ms = E.covering(self.M.doc, action["operation"], E.resources_for(self.ops, action["operation"], action["args"]))
            if len({c for m in ms for c in m["competent"]}) > 1 and not (ms and ms[0]["concurrence"]):
                self.tags.add("prec_conflict")
            if action["operation"] == "emergency:declare":
                self.tags.add(f"declare:{v.status}:{v.reason}")
        return rec, v

    def retry(self, rec):
        """Same request_id again (after a crash or as an idempotency probe)."""
        return self.step(rec["actor"], rec["action"], rid=rec["rid"], replay=True)

    # -- request selection ---------------------------------------------------------------------------------
    def governed_ops(self) -> list[tuple[str, dict]]:
        out = []
        for m in self.doc["matters"]:
            if self.doc["emergency"] and m["id"] == self.doc["emergency"]["matter"]:
                continue
            for o in m["scope"]["operations"]:
                if ops_model.op_of(self.ops, o):
                    out.append((o, m))
        return out

    def pick_request(self, governed=True):
        """-> (requester, operation, args) with base authority; redraws counted; None if impossible."""
        cands = self.governed_ops()
        for _ in range(12):
            if governed and cands:
                name, m = self.rng.choice(cands)
            else:
                free = [o["name"] for o in self.ops["operations"] if not E.covering(self.doc, o["name"], [])]
                if not free:
                    return None
                name, m = self.rng.choice(free), None
            op = ops_model.op_of(self.ops, name)
            who = self.rng.choice(self.principals())
            args = pick_args(self.env, op, self.ch, who, "commit")
            if m is not None:
                for inp in op["inputs"]:
                    ent = next((e for e in m["scope"]["resources"] if inp["type"] == "resource"
                                and e["type"] == inp["resource_type"]), None)
                    if ent and ent["keys"] and inp["name"] in args:
                        args[inp["name"]] = self.rng.choice(ent["keys"])
            res = E.resources_for(self.ops, name, args)
            if not ops_model.schema_valid_args(op, args):
                self.redraws += 1
                continue
            allowed = [p for p in self.principals() if self.M.base_allows(p, None, name, res, INF, self.tick()).allow]
            gov = bool(E.covering(self.M.doc, name, res))
            if gov == governed and allowed:
                return self.rng.choice(allowed), name, args
            self.redraws += 1
        return None

    # -- the script -------------------------------------------------------------------------------------------
    def run(self) -> dict:
        try:
            self.script()
            out = self.env.judge()
            calls = [c for c in self.env.calls if c["kind"] != "advance"]
            from .rows import row_of
            rows = [row_of(c, out["calls"][c["n"]]) for c in calls]
            cls = {k for r in rows for k in r["classes"]} | set(out["case_classes"])
            return {"id": f"case-{self.seed}-{self.i}", "model": self.model, "domain": self.domain,
                    "digest": input_digest(self.domain, self.model, self.env.calls), "calls": rows,
                    "case_classes": out["case_classes"], "classes": sorted(cls), "redraws": self.redraws,
                    "tags": sorted(self.tags), "n_actions": len(calls), "final": self._final_summary(out)}
        finally:
            self.env.close()

    def _final_summary(self, out) -> dict:
        C, seq, tick = out["final"], 10 ** 9, self.tick()
        out = {}
        for cid, c in C.s["cases"].items():
            f = C.final(cid, seq, tick)
            out[cid] = [f["state"], f["outcome"], f["rule"], c["executed"] is not None, c["appeal"] is not None]
        return out

    def script(self):
        r = self.rng
        plays = [plays_a.decision_play]
        if r.random() < 0.55:
            plays.append(plays_a.decision_play)
        if r.random() < 0.40:
            plays.append(plays_b.emergency_play)
        if r.random() < 0.80:
            plays.append(plays_b.noise_play)
        r.shuffle(plays)
        for p in plays:
            p(self)


def input_digest(domain, model, calls) -> str:
    keys = ("kind", "rid", "actor", "action", "op", "args", "obo", "to", "token_ok")
    body = json.dumps([domain, model, [{k: c.get(k) for k in keys} for c in calls]], sort_keys=True,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def run_case(variant, seed: int, i: int, **kw) -> dict:
    return Case(variant, seed, i, **kw).run()
