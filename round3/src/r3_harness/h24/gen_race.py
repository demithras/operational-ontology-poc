"""A2 race generator. One case = a fresh deployment, a sequential setup (a delegation chain through the variant's own
`delegate`), then two or more calls started behind a barrier from separate threads (RV RA EX SA DP AP CR UN) or the same
pair strictly sequenced both ways (SEQ). Invoke/return order comes from the harness counter, never the wall clock."""
from __future__ import annotations

import copy
import random
import threading
import time

from r3_harness.h23.chooser import RandChooser
from r3_oracle import authority, ops_model
from r3_shared.authspec import validate_strict

from . import gen_graph
from .env import G2Env
from .gen_seq import DOMAINS, composed
from .rows import VIOLATIONS, approver_for, input_digest, mirror_apply, mirror_delegate, mirror_revoke, row_of, scoped_args

TYPES = ("RV", "RA", "EX", "SA", "DP", "AP", "CR", "UN", "SEQ")
JOIN_S = 30.0
JITTER_S = 0.0015


def _scope(ops, op_list, args_list, rng):
    """A scope covering every (op, args): exact keys or null per type."""
    res = {}
    for op, args in zip(op_list, args_list):
        o = next(x for x in ops["operations"] if x["name"] == op)
        for t, k in ops_model.resources_of(o, args):
            res.setdefault(t, set()).add(k)
    return {"operations": sorted(set(op_list)), "resources": [
        {"type": t, "keys": None if rng.random() < 0.4 else sorted(ks | ({rng.choice(gen_graph.seed_keys(ops)[t])}
                                                                         if rng.random() < 0.5 else set()))}
        for t, ks in sorted(res.items())]}


class Race:
    def __init__(self, variant, specs, seed: int, i: int, rtype: str):
        self.i, self.rtype, self.domain = i, rtype, DOMAINS[i % len(DOMAINS)]
        self.rng = random.Random(f"h24-race-{seed}-{i}-{rtype}")
        self.ch = RandChooser(self.rng)
        self.ops, auth1 = specs[self.domain]
        self.world, self.info = gen_graph.make_world(self.ops, auth1, self.rng)
        self.env = G2Env(variant, self.domain, self.ops, self.world, f"race{seed}-{i}")
        self.k, self.hung, self.pair = 0, False, None

    def rid(self, p="x"):
        self.k += 1
        return f"{p}{self.i}-{self.k}"

    def chain(self, root, ops_args, depth, leaf_exp=None, tag="c"):
        """Issue a delegation chain root -> ... -> leaf covering all (op, args); returns the edge list."""
        env, rng = self.env, self.rng
        pool = [p["id"] for p in self.world["principals"] if p["delegated_by"] is None and p["id"] != root]
        used, edges, parent, issuer = {root}, [], None, root
        sc = _scope(self.ops, [o for o, _ in ops_args], [a for _, a in ops_args], rng)
        for d in range(depth):
            child = rng.choice([p for p in pool if p not in used])
            used.add(child)
            e = {"id": f"{tag}{self.i}-{len(edges) + 1}-{self.k}", "issuer": issuer, "child": child,
                 "parent": parent["id"] if parent else None, "scope": copy.deepcopy(sc),
                 "expires_at": leaf_exp if (d == depth - 1) else None, "redelegable": d < depth - 1, "issued_at": 0}
            self.k += 1
            env.delegate(e, self.rid("d"))["depth"] = d + 1
            mirror_delegate(env, e)
            edges.append(e)
            parent, issuer = e, child
        return edges

    def request(self, root, op, args, leaf, **kw):
        return self.env.request(leaf, root, op, args, kw.pop("rid", None) or self.rid(), **kw)

    def threads(self, fns, jitter=True):
        bar, ths, out = threading.Barrier(len(fns)), [], [None] * len(fns)
        cap = JITTER_S
        recent = sorted(c["lat_ms"] for c in self.env.calls[-8:] if c.get("lat_ms"))
        if recent:  # jitter varies the order but must stay well inside a call's own duration, or fast variants never overlap
            cap = min(JITTER_S, 0.25 * recent[len(recent) // 2] / 1000.0)
        delays = [self.rng.random() * cap if jitter else 0.0 for _ in fns]  # same RNG draws as before: corpus unchanged

        def wrap(k, f, d):
            def go():
                bar.wait()
                time.sleep(d)
                out[k] = f()
            return go
        for k, (f, d) in enumerate(zip(fns, delays)):
            t = threading.Thread(target=wrap(k, f, d), daemon=True)
            t.start()
            ths.append(t)
        for t in ths:
            t.join(JOIN_S)
        self.hung = self.hung or any(t.is_alive() for t in ths)
        self.pair = (out[0], out[1]) if out[0] is not None and out[1] is not None else None
        return out

    def pick(self, q, op_name=None):
        name = op_name or self.rng.choice(self.info["holders"][q])
        op = next(o for o in self.ops["operations"] if o["name"] == name)
        return op, scoped_args(self.env, self.ch, op, q, None)[0]

    # -- case bodies -----------------------------------------------------------------------------------------
    def body(self):
        env, rng, t = self.env, self.rng, self.rtype
        q = rng.choice(sorted(self.info["holders"]))
        names = [o["name"] for o in self.ops["operations"] if o["name"] in self.info["holders"][q]]
        opn = names[(self.i // len(TYPES)) % len(names)]
        op, args = self.pick(q, opn)
        if t == "UN":
            return self.un(q, names)
        depth = rng.randint(4, 8) if t == "RA" else (rng.randint(1, 8) if t == "RV" else rng.randint(1, 4))
        now = env.clock.now()
        edges = self.chain(q, [(op["name"], args)], depth, leaf_exp=now + 3 if t == "EX" else None)
        leaf = edges[-1]["child"]
        rid = self.rid()
        if t in ("RV", "RA", "SEQ") and rng.random() < 0.5:  # warm any decision cache with one committed use of the path
            env.request(leaf, q, op["name"], args, self.rid("w"))
        call = lambda **kw: env.request(leaf, q, op["name"], args, rid, **kw)  # noqa: E731
        if t in ("RV", "RA", "DP", "AP", "CR", "SEQ"):
            ek = edges[rng.randrange(max(1, depth - 2))] if t == "RA" else rng.choice(edges)
            revoke = lambda **kw: env.revoke(q, ek["id"], self.rid("v"), **kw)  # noqa: E731
        if t in ("RV", "RA"):
            self.threads([lambda: revoke(), lambda: call()])
        elif t == "EX":
            self.threads([lambda: env.advance(3), lambda: call()])
        elif t == "SA":
            spec = validate_strict(composed(env, authority.revoke(env.mirror.view(None).base, q, op["name"])), self.ops)
            self.threads([lambda: env.set_authority(spec), lambda: call()])
        elif t == "DP":
            par = rng.choice(edges[:-1] or edges)
            free = [p["id"] for p in self.world["principals"] if p["delegated_by"] is None
                    and p["id"] not in {x["issuer"] for x in edges} | {x["child"] for x in edges}]
            e2 = {"id": f"dp{self.i}-{self.k}", "issuer": par["child"], "child": rng.choice(free), "parent": par["id"],
                  "scope": copy.deepcopy(par["scope"]), "expires_at": None, "redelegable": False, "issued_at": 0}
            revoke = lambda **kw: env.revoke(q, par["id"], self.rid("v"), **kw)  # noqa: E731
            self.threads([lambda: revoke(), lambda: env.delegate(e2, self.rid("d"))])
        elif t == "AP":
            ap = approver_for(env, leaf, q, op["name"], args)
            if ap:
                env.approve(ap, leaf, q, op["name"], args)
            self.threads([lambda: revoke(), lambda: call(approved=bool(ap))])
        elif t == "CR":
            point = rng.choice(["before_commit", "after_commit"])
            env.arm(point)
            self.threads([lambda: revoke(crash=point), lambda: call(crash=point)])
            env.crash_restart()
            env.request(leaf, q, op["name"], args, rid, replay=True)  # same request_id after restart
            env.request(leaf, q, op["name"], args, self.rid())  # a new request_id: decided against current authority
        elif t == "SEQ":
            if self.i % 2 == 0:
                a = revoke()
                self.pair = (a, call())
            else:
                b = call()
                self.pair = (revoke(), b)

    def un(self, q, names):
        env, rng = self.env, self.rng
        reqs, used = [], set()
        for k in range(rng.randint(2, 4)):
            for _ in range(6):
                op, a = self.pick(q, names[(self.i + k) % len(names)] if rng.random() < 0.7 else None)
                res = set(ops_model.resources_of(op, a))
                if not res & used:
                    break
            used |= res
            reqs.append((op, a))
        ea = self.chain(q, [(reqs[0][0]["name"], reqs[0][1])], rng.randint(1, 3), tag="a")
        eb = self.chain(q, [(o["name"], a) for o, a in reqs], rng.randint(1, 3), tag="b")
        leaf = eb[-1]["child"]
        fns = [lambda: env.revoke(q, ea[0]["id"], self.rid("v"))]
        fns += [(lambda o=o, a=a: env.request(leaf, q, o["name"], a, self.rid())) for o, a in reqs]
        self.threads(fns)

    def run(self) -> dict:
        try:
            self.body()
            out = self.env.judge()
            calls = [c for c in self.env.calls if c["kind"] != "advance"]
            rows = [row_of(c, out["calls"][c["n"]]) for c in calls]
            cls = {k for r in rows for k in r["classes"]} | set(out["case_classes"])
            if self.hung:
                cls.add("world_lock_timeout")
                out["case_classes"] = sorted(set(out["case_classes"]) | {"world_lock_timeout"})
            return {"id": f"race-{self.i}-{self.rtype}", "type": self.rtype, "domain": self.domain,
                    "digest": input_digest(self.domain, self.env.calls), "calls": rows, "case_classes": out["case_classes"],
                    "classes": sorted(cls), "match": not (cls & set(VIOLATIONS)), **self._shape(out)}
        finally:
            if not self.hung:
                self.env.close()

    def _shape(self, out) -> dict:
        """Overlap of the racing pair (harness counters) and which commit came first (world_log seq)."""
        ex = self.rtype != "SEQ"
        if not self.pair:
            return {"overlap": False, "order": None, "executed": ex}
        other, tgt = self.pair
        ov = other["inv"] < tgt["ret"] and tgt["inv"] < other["ret"]
        so, st = out["calls"].get(other["n"], {}).get("seq"), out["calls"].get(tgt["n"], {}).get("seq")
        order = None if so is None or st is None else ("effect_first" if st < so else "revoke_first")
        return {"overlap": ov, "order": order, "executed": ex}


def run_race(variant, specs, seed: int, i: int, rtype: str) -> dict:
    return Race(variant, specs, seed, i, rtype).run()
