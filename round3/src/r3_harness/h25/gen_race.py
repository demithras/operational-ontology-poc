"""H25 race cases (ORACLE-AND-HARNESS-G3 A2): two or more constitutional actions started behind a barrier from separate
threads, after a sequential setup that puts the case on the boundary (window edge, expiry, last judgment). Invoke/return
order comes from the harness counter. The judge accepts any real-time-consistent linearization (PROT-H25 s4)."""
from __future__ import annotations

import threading
import time

from r3_oracle import const_eval as E

from . import plays_a, plays_b
from .gen_case import INF, Case
from .gen_model import valid_variant

TYPES = ("EA", "EA_EDGE", "EA_ADV", "AE", "AX", "AX_EDGE", "JJ", "ES", "SEQ")
JOIN_S = 30.0
JITTER_S = 0.0015


class Race(Case):
    def __init__(self, variant, seed: int, i: int, rtype: str, **kw):
        super().__init__(variant, seed, i, tag=f"race{rtype}", **kw)
        self.rtype, self.hung, self.pair = rtype, False, None

    def threads(self, fns):
        bar, out = threading.Barrier(len(fns)), [None] * len(fns)
        recent = sorted(c["lat_ms"] for c in self.env.calls[-8:] if c.get("lat_ms"))
        cap = min(JITTER_S, 0.25 * recent[len(recent) // 2] / 1000.0) if recent else JITTER_S
        delays = [self.rng.random() * cap for _ in fns]

        def wrap(k, f, d):
            def go():
                bar.wait()
                time.sleep(d)
                out[k] = f()
            return go
        ths = [threading.Thread(target=wrap(k, f, d), daemon=True) for k, (f, d) in enumerate(zip(fns, delays))]
        for t in ths:
            t.start()
        for t in ths:
            t.join(JOIN_S)
        self.hung = self.hung or any(t.is_alive() for t in ths)
        self.pair = (out[0], out[1]) if out[0] is not None and out[1] is not None else None
        return out

    # -- setups ------------------------------------------------------------------------------------------
    def decided_case(self, with_review=True):
        for _ in range(8):
            req = self.pick_request(True)
            if req is None:
                return None
            who, op, args = req
            cid = f"c{self.i}-{len(self.cases) + 1}"
            self.cases.append(cid)
            _, v = self.step(who, {"kind": "propose", "case": cid, "operation": op, "args": args, "on_behalf_of": None})
            if v.status != "OK":
                continue
            plays_a.run_stage(self, cid, "decision", "complete")
            d = plays_a.stage_of(self, cid, "decision")
            rv = d["matter"]["review"] if d["matter"] else None
            if d["outcome"] == E.ALLOW and (rv is not None or not with_review):
                return who, cid, d, rv
            self.redraws += 1
        return None

    def active_emergency(self):
        if not self.doc["emergency"]:
            return None
        for _ in range(6):
            plays_b.emergency_play(self, with_acts=False)
            for c in self.M.s["cases"].values():
                if c["operation"] == plays_b.DECL and isinstance(c["args"], dict):
                    a = self.M.emergency_active(c["args"]["emergency"], INF, self.tick())
                    if a and a["expires_at"] > self.tick() + 1:
                        return a
            self.redraws += 1
        return None

    # -- bodies -------------------------------------------------------------------------------------------
    def script(self):
        t, r = self.rtype, self.rng
        if t in ("EA", "EA_EDGE", "EA_ADV", "ES", "SEQ"):
            s = self.decided_case(with_review=t != "ES")
            if s is None:
                return plays_a.decision_play(self)
            who, cid, d, rv = s
            ex = {"kind": "execute", "case": cid}
            if rv is not None:
                edge = d["tick"] + rv["window"]
                self.env.advance(max(0, edge - self.tick() - (0 if t == "EA_EDGE" else 1)))
            ap = {"kind": "appeal", "case": cid}
            if t == "ES":
                doc = valid_variant({"doc": self.M.doc, "auth": self.env.auth, "ops": self.ops}, r)
                self.threads([lambda: self.env.act(who, ex, self.rid("x")), lambda: self.env.set_governance(doc)])
            elif t == "EA_ADV":
                self.threads([lambda: self.env.act(who, ap, self.rid("a")), lambda: self.env.advance(1)])
            elif t == "SEQ":
                a = self.env.act(who, ap, self.rid("a"))
                self.pair = (a, self.env.act(who, ex, self.rid("x")))
            else:
                self.threads([lambda: self.env.act(who, ex, self.rid("x")), lambda: self.env.act(who, ap, self.rid("a"))])
        elif t in ("AE", "AX", "AX_EDGE"):
            em = self.active_emergency()
            if em is None:
                return plays_b.emergency_play(self)
            who = r.choice(em["grantees"])
            from r3_harness.h23.goodargs import pick_args
            from r3_oracle import ops_model
            op = ops_model.op_of(self.ops, em["scope"]["operations"][0])
            args = pick_args(self.env, op, self.ch, who, "commit")
            act = {"kind": "act", "emergency": em["id"], "operation": op["name"], "args": args}
            if t == "AE":
                member = E.body_of(self.M.doc, em["bodies"][0])["members"][0]
                self.threads([lambda: self.env.act(who, act, self.rid("a")),
                              lambda: self.env.act(member, {"kind": "end", "emergency": em["id"]}, self.rid("e"))])
            else:
                self.env.advance(max(0, em["expires_at"] - self.tick() - (0 if t == "AX_EDGE" else 1)))
                self.threads([lambda: self.env.act(who, act, self.rid("a")), lambda: self.env.advance(1)])
        else:  # JJ: the last judgments of a quorum / duplicate judges race
            for _ in range(6):
                req = self.pick_request(True)
                if req is None:
                    return plays_a.decision_play(self)
                who, op, args = req
                cid = f"c{self.i}-{len(self.cases) + 1}"
                self.cases.append(cid)
                _, v = self.step(who, {"kind": "propose", "case": cid, "operation": op, "args": args, "on_behalf_of": None})
                if v.status == "OK":
                    break
            else:
                return plays_a.decision_play(self)
            el = list(plays_a.members(self, cid, "decision"))
            r.shuffle(el)
            ks = [E.body_of(self.M.doc, b)["rule"].get("k", 1) for b in plays_a.bodies_of(self, cid, "decision")]
            for m in el[:max(0, (max(ks) if ks else 1) - 1)]:
                plays_a.cast(self, cid, "decision", m, "concur")
            rest = [m for m in el if not self.M.case(cid) or all(j["judge"] != m for j in self.M.case(cid)["judgments"])]
            if len(rest) >= 2:
                a, b = rest[0], rest[1]
            elif rest:
                a = b = rest[0]
            else:
                return
            mk = lambda who_, val: {"kind": "judge", "case": cid, "stage": "decision", "value": val, "merit": self.merit()}  # noqa: E731
            self.threads([lambda: self.env.act(a, mk(a, "concur"), self.rid("j")),
                          lambda: self.env.act(b, mk(b, r.choice(["concur", "dissent"])), self.rid("j"))])
            self.env.act(a, {"kind": "execute", "case": cid}, self.rid("x"))


def run_race(variant, seed: int, i: int, rtype: str) -> dict:
    g = Race(variant, seed, i, rtype)
    try:
        g.script()
        out = g.env.judge()
        from .rows import row_of
        calls = [c for c in g.env.calls if c["kind"] != "advance"]
        rows = [row_of(c, out["calls"][c["n"]]) for c in calls]
        cls = {k for r in rows for k in r["classes"]} | set(out["case_classes"])
        if g.hung:
            cls.add("world_lock_timeout")
        from .gen_case import input_digest
        ov = bool(g.pair) and g.pair[0]["inv"] < g.pair[1]["ret"] and g.pair[1]["inv"] < g.pair[0]["ret"]
        return {"id": f"race-{seed}-{i}-{rtype}", "type": rtype, "model": g.model, "domain": g.domain,
                "digest": input_digest(g.domain, g.model, g.env.calls), "calls": rows, "case_classes": out["case_classes"],
                "classes": sorted(cls), "redraws": g.redraws, "tags": sorted(g.tags), "n_actions": len(calls),
                "overlap": ov, "race": rtype != "SEQ", "final": g._final_summary(out)}
    finally:
        if not g.hung:
            g.env.close()
