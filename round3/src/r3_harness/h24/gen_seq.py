"""A2 sequential state machine: one SEQUENCE = one generated authority graph + 20-60 steps, executed against a fresh
deployment with a seeded RNG, then judged by the oracle from the world_log. Steps: delegate | revoke | advance |
set_authority | request | retry | crash/restart | authority_used | expiry_probe."""
from __future__ import annotations

import random

from r3_harness.h23.chooser import RandChooser
from r3_oracle import authority
from r3_oracle import ops_model
from r3_shared.authspec import validate_strict

from . import gen_graph
from .env import G2Env
from .rows import (approver_for, input_digest, mirror_apply, mirror_delegate, mirror_revoke, row_of, scoped_args)

DOMAINS = ("manufacturing", "project")


def composed(env, narrowed_base: dict | None = None) -> dict:
    """set_authority document (E-5): the (optionally narrowed) BASE layer only. Edges/revocations change solely through
    delegate/revoke, so the document carries none (and anything it carried would be ignored by oracle and variants)."""
    base = narrowed_base if narrowed_base is not None else env.mirror.view(None).base
    return {**base, "capabilities": [], "revoked": []}


class Seq:
    def __init__(self, variant, specs, seed: int, i: int):
        self.i, self.domain = i, DOMAINS[i % len(DOMAINS)]
        self.rng = random.Random(f"h24-seq-{seed}-{i}")
        self.ch = RandChooser(self.rng)
        self.ops, auth1 = specs[self.domain]
        self.world, self.info = gen_graph.make_world(self.ops, auth1, self.rng)
        self.env = G2Env(variant, self.domain, self.ops, self.world, f"seq{seed}-{i}")
        self.plan = gen_graph.plan_edges(self.ops, self.world, self.info, self.rng, 0, self.rng.randint(6, 14),
                                         force_deep=i % 10 == 0)
        self.n = 0
        self.by_id = {st["edge"]["id"]: st["edge"] for st in self.plan if st["intent"] != "illegal:dup_id"}
        self.accepted_illegal: list = []  # illegal edges the VARIANT accepted: requests through them probe the use rule
        self.oplist = [o["name"] for o in self.ops["operations"]]

    def rid(self, p="r"):
        self.n += 1
        return f"{p}{self.i}-{self.n}"

    # -- step implementations ---------------------------------------------------------------------------
    def s_delegate(self):
        st = self.plan.pop(0)
        r = self.env.delegate(st["edge"], self.rid("d"), intent=st["intent"])
        r["depth"] = st["depth"]
        mirror_delegate(self.env, st["edge"])
        if st["intent"] != "legal" and r["status"] == "OK" and st["intent"] != "illegal:dup_id":
            self.accepted_illegal.append(st["edge"])

    def _root_of(self, e):
        seen = 0
        while e["parent"] in self.by_id and seen < 12:
            e, seen = self.by_id[e["parent"]], seen + 1
        return e["issuer"]

    def _edge_request(self, stale=False):
        env, rng = self.env, self.rng
        edges = list(env.mirror.view(None).edges.values())
        if not edges and not self.accepted_illegal:
            return False
        st, now = env.mirror.view(None), env.clock.now()
        live = [x for x in edges if all(y["id"] not in st.revoked and (y["expires_at"] is None or now < y["expires_at"])
                                        for y in env.mirror.edge_path(x["id"]))]
        e = rng.choice(live if live and rng.random() < 0.75 else (edges or self.accepted_illegal))
        if self.accepted_illegal and rng.random() < 0.3:
            e = rng.choice(self.accepted_illegal)
        root = self._root_of(e)
        # sweep operations so every operation gets exercised; fall back to the scope's own operations
        names = sorted(e["scope"]["operations"])
        sweep = self.oplist[self.i % len(self.oplist)]
        pick = sweep if sweep in names and rng.random() < 0.6 else rng.choice(names)
        op = next(o for o in self.ops["operations"] if o["name"] == pick)
        a, kind = scoped_args(env, self.ch, op, root, e["scope"])
        approved = False
        if kind == ops_model.NEEDS_APPROVAL or (kind != ops_model.COMMIT and rng.random() < 0.2):
            ap = approver_for(env, e["child"], root, op["name"], a)
            if ap and env.approve(ap, e["child"], root, op["name"], a).status == "OK":
                approved = True
        rid = self.rid()
        r = env.request(e["child"], root, op["name"], a, rid, approved=approved)
        if r["status"] == "OK":
            env.committed.add(rid)
        return True

    def s_request(self):
        r = self.rng.random()
        env = self.env
        if r < 0.7 and self._edge_request():
            return
        holders = sorted(self.info["holders"])
        q = self.rng.choice(holders)
        op = self.rng.choice([o for o in self.ops["operations"] if o["name"] in self.info["holders"][q]])
        a, _ = scoped_args(env, self.ch, op, q, None)
        who = self.rng.choice(["base", "wrong_obo", "leaf_obo"])
        actor, obo = {"base": (q, None), "wrong_obo": (self.rng.choice(sorted(self.info["holders"])), q),
                      "leaf_obo": (self.rng.choice(self.info["leaves"] or [q]), q)}[who]
        rid = self.rid()
        if env.request(actor, obo, op["name"], a, rid)["status"] == "OK":
            env.committed.add(rid)

    def s_revoke(self):
        env, rng = self.env, self.rng
        edges = list(env.mirror.view(None).edges.values())
        if not edges:
            return
        e = rng.choice(edges)
        path = env.mirror.edge_path(e["id"])
        actor = rng.choice([x["issuer"] for x in path] + ([rng.choice(self.info["leaves"])] if rng.random() < 0.15 else []))
        env.revoke(actor, e["id"] if rng.random() > 0.05 else "e-nope", self.rid("v"))
        mirror_revoke(env, actor, e["id"])

    def s_advance(self):
        self.env.advance(self.rng.choice([1, 1, 2, 5, 10, 30]))

    def s_expiry_probe(self):
        env = self.env
        now = env.clock.now()
        cand = [e for e in env.mirror.view(None).edges.values() if e["expires_at"] and e["expires_at"] > now]
        if not cand:
            return self.s_advance()
        e = self.rng.choice(cand)
        env.advance(e["expires_at"] - 1 - now)  # request at expires_at - 1 (usable) then at expires_at (not usable)
        for _ in range(2):
            self._edge_request_on(e)
            env.advance(1)

    def _edge_request_on(self, e):
        env = self.env
        root = env.mirror.edge_path(e["id"])[0]["issuer"]
        pick = self.rng.choice(sorted(e["scope"]["operations"]))
        op = next(o for o in self.ops["operations"] if o["name"] == pick)
        a, _ = scoped_args(env, self.ch, op, root, e["scope"])
        rid = self.rid()
        if env.request(e["child"], root, op["name"], a, rid)["status"] == "OK":
            env.committed.add(rid)

    def s_set_authority(self):
        env = self.env
        edges = list(env.mirror.view(None).edges.values())
        if not edges:
            return
        e = self.rng.choice(edges)
        root = env.mirror.edge_path(e["id"])[0]["issuer"]
        op = self.rng.choice(sorted(e["scope"]["operations"]))
        base = env.mirror.view(None).base
        try:
            spec = validate_strict(composed(env, authority.revoke(base, root, op)), self.ops)
        except ValueError:
            return
        r = env.set_authority(spec)
        mirror_apply(env, "set_authority", {"spec": spec}, r["status"] == "OK")

    def s_retry(self):
        ok = [c for c in self.env.calls if c["kind"] == "request" and c["status"] == "OK" and not c["replay"]]
        if ok:
            c = self.rng.choice(ok)
            self.env.request(c["actor"], c["obo"], c["op"], c["args"], c["rid"], replay=True)

    def s_used(self):
        ok = [c for c in self.env.calls if c["kind"] == "request" and c["status"] == "OK"]
        if ok:
            self.env.authority_used(self.rng.choice(ok)["rid"])

    def s_crash(self):
        env = self.env
        if self.rng.random() < 0.4:
            env.crash_restart()
            return
        point = self.rng.choice(["before_commit", "after_commit"])
        edges = list(env.mirror.view(None).edges.values())
        if not edges:
            return
        e = self.rng.choice(edges)
        env.arm(point)
        r = env.revoke(e["issuer"], e["id"], self.rid("v"), crash=point)
        env.crash_restart()  # also clears an armed crash that did not trigger
        if r["status"] == "OK" or point == "after_commit":
            mirror_revoke(env, e["issuer"], e["id"])
        if r["status"] == "UNKNOWN":
            retry = env.revoke(e["issuer"], e["id"], r["rid"], crash=None)
            if retry["status"] == "OK":  # effective via the retry (or already effective via the crashed send): mirror = reality
                mirror_revoke(env, e["issuer"], e["id"])

    # -- driver ------------------------------------------------------------------------------------------------
    def run(self) -> dict:
        rng, steps = self.rng, 0
        total = self.rng.randint(20, 60)
        table = [(30, "request"), (9, "revoke"), (9, "advance"), (2, "set_authority"), (6, "retry"), (6, "used"),
                 (4, "crash"), (3, "expiry_probe")]
        try:
            while steps < total or self.plan:
                steps += 1
                if self.plan and (rng.random() < 0.5 or steps > total):
                    self.s_delegate()
                    continue
                x, acc = rng.random() * sum(w for w, _ in table), 0
                for w, name in table:
                    acc += w
                    if x < acc:
                        getattr(self, "s_" + name)()
                        break
            out = self.env.judge()
            calls = [c for c in self.env.calls if c["kind"] != "advance"]
            rows = [row_of(c, out["calls"][c["n"]]) for c in calls]
            for r, c in zip(rows, calls):
                if c.get("depth"):
                    r["depth"] = c["depth"]
            return {"id": f"seq-{self.i}", "domain": self.domain, "digest": input_digest(self.domain, self.env.calls),
                    "calls": rows, "case_classes": out["case_classes"], "max_depth": max(
                        [r.get("depth") or 0 for r in rows] + [0])}
        finally:
            self.env.close()


def run_sequence(variant, specs, seed: int, i: int) -> dict:
    return Seq(variant, specs, seed, i).run()
