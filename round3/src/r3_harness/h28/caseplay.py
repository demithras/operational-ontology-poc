"""Player: executes the generated step list against one deployment and records raw observations (see caserun.run_case)."""
from __future__ import annotations

from r3_oracle import approvals, extoracle
from r3_shared.extadapter import canon_json
from r3_shared.extobs import ObserverFault
from r3_shared.variant import g4_call
from r3_shared.world import WorldLockTimeout


TTL = 10 ** 6


def _fault(f):
    if not f:
        return None
    return ObserverFault.unavailable() if f["kind"] == "unavailable" else ObserverFault.lagging(int(f["k"]))


class Player:
    def __init__(self, ctx, variant, case, rec, sp, dep, clock, idp, aud, reader, sched, observer, recs, comps):
        self.ctx, self.case, self.rec, self.sp, self.dep, self.clock, self.idp, self.aud = ctx, case, rec, sp, dep, clock, idp, aud
        self.reader, self.sched, self.observer, self.recs, self.comps = reader, sched, observer, recs, comps
        self.toks: dict = {}
        self.committed: set = set()
        self.appr: dict = {}
        self.intents: dict[int, list] = {}
        self.done_final = False

    def tok(self, sub):
        if sub not in self.toks:
            self.toks[sub] = self.idp.issue(sub, self.aud, TTL, self.clock)
        return self.toks[sub]

    def tick_to(self, target: int) -> None:
        while self.clock.now() < target:
            t = self.clock.advance(1)
            self.ctx.ctl.advance(t)
            for _, fn in self.sched.due(t):
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001 - harness-side adapter write failure is recorded, not raised
                    self.rec["errors"].append(f"delayed write: {type(exc).__name__}: {exc}")

    def call(self, name, fn, *a, **k):
        """A variant call: exceptions are data; NotImplementedError('... G4') -> unsupported."""
        try:
            return fn(*a, **k), None
        except NotImplementedError as exc:
            self.rec["unsupported"] += 1
            return None, f"unsupported: {exc}"
        except WorldLockTimeout as exc:
            self.rec["world_lock_timeout"] += 1
            return None, f"world_lock_timeout: {exc}"
        except Exception as exc:  # noqa: BLE001
            return None, f"{type(exc).__name__}: {exc}"

    # ---- schedule ------------------------------------------------------------------------------------------------
    def play(self) -> None:
        for st in self.case["steps"]:
            getattr(self, "s_" + st["op"])(st)
        self.finish()

    def s_approve(self, st):
        r = self.case["requests"][st["i"]]
        sp = self.sp
        ok, why = approvals.validate(sp["ops"], sp["auth"], r["approver"], r["subject"], r["operation"], r["args"])
        res, err = self.call("approve", self.dep.approve, self.tok(r["approver"]), r["operation"], dict(r["args"]), r["subject"], r["obo"])
        self.rec["approvals"].append({"i": r["i"], "oracle_valid": ok, "status": res.status if res else None, "error": err})
        if ok:
            k = approvals.key(r["subject"], r["obo"], r["operation"], r["args"])
            self.appr[k] = self.appr.get(k, 0) + 1

    def s_arm_crash(self, st):
        self.call("arm_crash", self.dep.arm_crash, st["point"])

    def s_restart(self, st):
        last = self.rec["requests"][-1] if self.rec["requests"] else {}
        if last.get("status") != "UNKNOWN":                       # the armed crash did not trigger: clear it (crash + restart)
            self.call("crash", self.dep.crash)
        self.call("restart", self.dep.restart)

    def snapshot(self):
        try:
            return self.reader.snapshot()
        except WorldLockTimeout:
            self.rec["world_lock_timeout"] += 1
            return None

    def s_request(self, st):
        r = self.case["requests"][st["i"]]
        sp, now = self.sp, self.clock.now()
        snap = self.snapshot()
        akey = approvals.key(r["subject"], r["obo"], r["operation"], r["args"])
        dec = None
        if snap is not None:
            dec = extoracle.decide(sp["ops"], sp["auth"], r["subject"], r["obo"], r["operation"], r["args"], snap, now,
                                   frozenset(self.committed), r["rid"], approved=self.appr.get(akey, 0) > 0)
        intents = extoracle.intended(sp["systems"], dec, r["rid"]) if dec is not None else []
        fn = self.dep.call_tool if r["via"] == "call_tool" else self.dep.direct
        res, err = self.call("request", fn, self.tok(r["subject"]), r["operation"], dict(r["args"]), r["obo"], r["rid"])
        row = {"i": r["i"], "rid": r["rid"], "replay": bool(st.get("replay")), "tick": now, "via": r["via"], "subject": r["subject"],
               "operation": r["operation"], "status": res.status if res else None, "reason": (res.body or {}).get("reason") if res else None,
               "error": err, "oracle": dec.kind if dec else None, "oracle_reason": dec.reason if dec else None,
               "oracle_kind": dec.outcome.kind if dec and dec.outcome else None, "intents": intents,
               "used_approval": bool(dec and dec.outcome and dec.outcome.used_approval), "expect": r["expect"]}
        self.rec["requests"].append(row)
        if dec is not None and dec.kind == "OK" and dec.outcome.effects:
            self.committed.add(r["rid"])
            if dec.outcome.used_approval:
                self.appr[akey] = self.appr.get(akey, 0) - 1
            if not st.get("replay"):
                self.intents[r["i"]] = intents
        if res is not None and res.status == "OK" and not st.get("replay") and intents:
            self.rec.setdefault("auditor_env", {})[r["rid"]] = self._auditor_env(r["rid"])
        if res is not None and res.status == "OK" and not st.get("replay"):
            au, aerr = self.call("authority_used", lambda: self.dep.authority_used(r["rid"]))
            row["authority_used"] = {"status": au.status, "body": au.body} if au is not None else None

    def _auditor_env(self, rid):
        """G4-E23: the auditor envelope of the decision = the VERIFIED envelope of dep.replay(rid); None when replay yields none."""
        try:
            rp = self.dep.replay(rid)
        except Exception:  # noqa: BLE001 - a variant without replay simply has no auditor envelope
            return None
        return rp.envelope if getattr(rp, "status", None) == "VERIFIED" and isinstance(rp.envelope, dict) else None

    def s_script(self, st):
        """Conformance C28-2: the HARNESS writes a scripted ledger row with its own broad cap (system+operation+correlation only)."""
        from r3_shared import extcap
        from r3_shared.extadapter import correlation as corr
        r = self.case["requests"][st["i"]]
        ints = self.intents.get(r["i"])
        if not ints:
            return
        I = ints[0]
        root = self.ctx.ctl.issue_root(self.rec["dep"], I["system"])
        cap = extcap.attenuate(root, system=I["system"], operation=I["operation"], correlation=corr(r["rid"], I["effect_index"]))
        tgt = I["target"] if st["what"] != "write_other" else I["target"] + "~other"
        self.ctx.ctl.data_only().write(cap, I["operation"], tgt, I["payload"], "script")

    def s_dispatch(self, st):
        res, err = self.call("dispatch", g4_call, self.dep, "dispatch_pending")
        self.rec["dispatch"].append({"tick": self.clock.now(), "status": res.status if res else None,
                                     "submitted": (res.body or {}).get("submitted") if res else None, "error": err})

    def s_advance(self, st):
        self.tick_to(self.clock.now() + st["n"])

    def reconcile_all(self, fault, only_intents=True):
        self.observer.fault = _fault(fault)
        for r in self.case["requests"]:
            if only_intents and r["i"] not in self.intents:
                continue
            self.reconcile_one(r, fault)
        self.observer.fault = None
        self.tick_to(self.clock.now() + 1)      # every read above is tick-complete: no later write can land at a tick <= its watermark

    def reconcile_one(self, r, fault):
        n0, now = len(self.observer.transcript), self.clock.now()
        wm = now                  # G4-E24: the shared observer clamps complete_through_tick to the server tick
        res, err = self.call("reconcile", g4_call, self.dep, "reconcile", r["rid"], wm)
        self.rec["recon"].append({"i": r["i"], "rid": r["rid"], "tick": now, "watermark": wm, "fault": fault,
                                  "status": res.status if res else None, "reason": (res.body or {}).get("reason") if res else None,
                                  "outcomes": (res.body or {}).get("outcomes") if res else None, "error": err,
                                  "transcript": [dict(e) for e in self.observer.transcript[n0:]]})

    def s_reconcile(self, st):
        self.tick_to(self.clock.now() + 1)
        self.reconcile_all(st.get("fault"))

    def s_final(self, st):
        ticks = [q["tick"] for q in self.rec["requests"] if q["intents"]]
        target = (max(ticks) if ticks else self.clock.now()) + self.rec["window"] + 2
        self.tick_to(max(target, self.clock.now()))
        self.reconcile_all(None, only_intents=False)
        self.done_final = True

    def finish(self):
        self.rec["end_tick"] = self.clock.now()
        sn = self.snapshot()
        self.rec["world_external_rows"] = None if sn is None else len(sn["effects"])
        snap = self.snapshot()
        self.rec["world_digest"] = None if snap is None else __import__("hashlib").sha256(
            canon_json({"objects": {k: ({**o, "props": {**o["props"], "snapshotObservedAt": o["props"]["snapshotObservedAt"] - self.rec["start_tick"]}}
                                        if k.startswith("EvidenceSnapshot:") and "snapshotObservedAt" in o["props"] else o)
                                    for k, o in snap["objects"].items()}, "links": snap["links"]}).encode()).hexdigest()
        self.rec["recorder"] = {s: r.log for s, r in self.recs.items() if r.log}
        self.rec["attempts"] = [a for c in self.comps.values() for a in c.attempts]
        outs = {}
        for q in self.rec["requests"]:
            if q["i"] in self.intents:
                o, _ = self.call("outcome", g4_call, self.dep, "outcome", q["rid"])
                outs[q["rid"]] = o.body.get("outcomes") if o is not None and o.status == "OK" else None
        self.rec["self_report"] = outs
        self.rec["fault_active_final"] = False
