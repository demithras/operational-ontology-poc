"""H28 test fakes (never registered). FakeHonest = oracle-backed reference (decide with r3_oracle, outbox + per-effect attenuated caps,
observer-only outcomes): it exists to prove the harness can say SUPPORTED. The H28 mutants (r3_shared.mutants.KNOWN["H28"]) are
honoured through the constructor, each at its real site; the known-negative fakes of ORACLE-AND-HARNESS-G4 s8 are named builds of them.
It reuses the oracle on purpose (like tests/fakes/h23_fakes.py): reference, not an independent check."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from r3_oracle import approvals as oracle_approvals
from r3_shared import mutants as mutants_mod
from r3_shared.extadapter import ExternalRequest, correlation, payload_digest
from r3_shared.extobs import ObserverUnavailable
from r3_shared.extsystems import idempotency, observability, render_target
from r3_shared.variant import CallResult
from tests.fakes import fake_h28_adapt as A
from tests.fakes import fake_h28_policy as P
from tests.fakes.h23_fakes import FakeDep

APPROVAL_RULES = ("expedite-large-fee-needs-approval", "publish-public-needs-approval")


class Blanket(dict):
    """FakeConsumesArtefact: an adapter-supplied approval satisfies every approval check."""
    on = False

    def __missing__(self, k):
        return 0

    def get(self, k, d=None):
        return 1 if self.on else super().get(k, d)


class H28Dep(FakeDep):
    audience = "fake"

    def __init__(self, domain, factory, verifier, ops, auth, clock, mutants, state_dir, external, mode):
        ops = copy.deepcopy(ops)
        if "policy_gate_in_adapter" in mutants:     # decision plane no longer enforces the approval rules (moved to P.blocked)
            for o in ops["operations"]:
                o["business_rules"] = [r for r in o["business_rules"] if r["id"] not in APPROVAL_RULES]
        super().__init__("correct", domain, factory, verifier, ops, auth, clock, mutants, state_dir)
        self.approved, self.external, self.mode, self._pending = Blanket(), external, mode, []
        self._g4_load()

    # ---- decision plane: reuse FakeDep, but external effects go to the outbox AFTER the world commit ---------------------
    def _apply(self, effects):
        ext = [e for e in effects if e["kind"] == "external"]
        super()._apply([e for e in effects if e["kind"] != "external"] if self.external is not None else effects)
        if self.external is not None:
            self._pending = ext

    def _run_locked(self, token, op, args, obo, rid, backstop):
        self._pending = []
        sub = self._sub(token)
        had = sub is not None and isinstance(args, dict) and self.approved.get(oracle_approvals.key(sub, obo, op, args), 0) > 0
        res = super()._run_locked(token, op, args, obo, rid, backstop)
        if res.status == "INVALID" and str((res.body or {}).get("why", "")).startswith("approval_required"):
            res = CallResult("DENIED", {"reason": "approval_required"})      # Variant protocol: needs approval -> DENIED approval_required
        elif res.status != "OK" and "reason" not in (res.body or {}):
            res = CallResult(res.status, {**(res.body or {}), "reason": str((res.body or {}).get("why", "refused"))})
        pend, self._pending = self._pending, []
        if pend and rid is not None:
            self._g4_record(rid, pend, had)
        return res

    # ---- outbox ----------------------------------------------------------------------------------------------------------
    def _g4_file(self):
        return Path(self.state_dir) / "g4.json" if self.state_dir else None

    def _g4_load(self):
        self.g4 = {"intents": [], "outcomes": {}}
        p = self._g4_file()
        if self.external is not None and p is not None and p.exists():
            self.g4 = json.loads(p.read_text())

    def _g4_save(self):
        p = self._g4_file()
        if p is not None:
            p.write_text(json.dumps(self.g4, sort_keys=True))

    def _g4_record(self, rid, ext, had_approval=False):
        b, tick = self.external, self.clock.now()
        for i, e in enumerate(ext):
            s, op = e["adapter"], e["target"]
            target = render_target(b.systems["systems"][s]["operations"][op]["target_rule"], e["payload"])
            it = {"request_id": rid, "effect_index": i, "system": s, "operation": op, "target": target, "payload": e["payload"],
                  "class": idempotency(b.systems, s, op), "commit_tick": tick, "attempts": 0, "done": False,
                  "approved": bool(had_approval), "reply": None}
            it["cap"] = A.cap_for(b.root_caps[s], it, tick, b.window, broadened="credential_scope_broadened" in self.mutants)
            self.g4["intents"].append(it)
            obs = observability(b.systems, s)
            self.g4["outcomes"][f"{rid}#{i}"] = {"request_id": rid, "effect_index": i, "system": s, "evidence": [],
                                                 "state": "UNKNOWN" if obs == "none" else "PENDING",
                                                 "confidence": "full" if obs == "full" else "low"}
        self._g4_save()

    def dispatch_pending(self):
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            if self.external is None or self.mode == "never_dispatch":
                return CallResult("OK", {"submitted": 0})
            n, b = 0, self.external
            for it in self.g4["intents"]:
                if it["done"] or it["attempts"] >= A.MAX_ATTEMPTS:
                    continue
                if "policy_gate_in_adapter" in self.mutants and P.blocked(it["operation"], it["payload"], it.get("approved", False)):
                    it["done"] = True                                   # adapter-side policy: the effect is silently not carried out
                    continue
                it["attempts"] += 1
                if "idempotency_disabled" in self.mutants and it["attempts"] > 1:   # fresh cap on every re-submission
                    it["cap"] = A.cap_for(b.root_caps[it["system"]], it, it["commit_tick"], b.window, fresh=it["attempts"])
                n += 1
                req = ExternalRequest(it["request_id"], it["effect_index"], it["system"], it["operation"], it["target"], it["payload"],
                                      "", it["cap"])
                try:
                    reply = b.adapters[it["system"]].submit(req)
                    it["done"] = reply.status == "OK"                    # the reply only decides re-submission (R28-8)
                    it["reply"] = {"status": reply.status, "observed": bool((reply.body or {}).get("observed", {}).get("applied"))}
                    if "FakeConsumesArtefact" == self.mode and isinstance(reply.body, dict) and "approval" in reply.body:
                        self.approved.on = True                         # known negative: honours an adapter-minted approval
                except Exception:  # noqa: BLE001
                    pass
            self._g4_save()
            return CallResult("OK", {"submitted": n})

    def _outs(self, rid):
        return sorted((o for o in self.g4["outcomes"].values() if o["request_id"] == rid), key=lambda o: o["effect_index"])

    def reconcile(self, request_id, watermark):
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            if not self._outs(request_id):
                return CallResult("INVALID", {"reason": "unknown_request"})
            try:
                snap = self.external.observer.read(watermark=watermark)
            except ObserverUnavailable:
                snap = None
            for it in (i for i in self.g4["intents"] if i["request_id"] == request_id):
                o = self.g4["outcomes"][f"{request_id}#{it['effect_index']}"]
                obs = observability(self.external.systems, it["system"])
                st, conf, ev = A.outcome({"operation": it["operation"], "target": it["target"], "payload_digest": payload_digest(it["payload"]),
                                          "correlation": correlation(request_id, it["effect_index"])}, snap, o["state"], o["evidence"],
                                         it["class"], obs, it["commit_tick"] + self.external.window,
                                         any_row_success="divergence_rewritten" in self.mutants)
                rep = it.get("reply") or {}
                if "adapter_success_trusted" in self.mutants and rep.get("status") == "OK":
                    st, conf = "RECONCILED_SUCCESS", ("full" if obs == "full" else "low")
                if "observation_coupled" in self.mutants and rep.get("observed"):
                    st, conf = "RECONCILED_SUCCESS", ("full" if obs == "full" else "low")
                if self.mode == "always_unknown":
                    st, conf = "UNKNOWN", "low"
                o.update(state=st, confidence=conf, evidence=[x for x in ev if isinstance(x, int)])
            self._g4_save()
            return CallResult("OK", {"outcomes": [dict(o) for o in self._outs(request_id)]})

    def outcome(self, request_id):
        outs = self._outs(request_id)
        return CallResult("OK", {"outcomes": [dict(o) for o in outs]}) if outs else CallResult("INVALID", {"reason": "unknown_request"})

    def crash(self):
        super().crash()
        self.g4 = {"intents": [], "outcomes": {}}

    def restart(self):
        super().restart()
        self.approved = Blanket(self.approved)
        self._g4_load()

    def authority_used(self, request_id):
        return CallResult("OK", {"path": [], "on_behalf_of": None})


class H28Fake:
    """Variant wrapper. mode: honest | never_dispatch | always_unknown | FakeConsumesArtefact."""
    audience = "fake"

    def __init__(self, mode="honest", mutants=()):
        self.mode, self.mutants, self.name = mode, mutants_mod.validate(mutants), f"fake-h28-{mode}"

    def deploy(self, domain, factory, verifier, ops_spec, auth_spec, clock, state_dir=None, history=None, anchor=None,
               governance=None, external=None):
        return H28Dep(domain, factory, verifier, ops_spec, auth_spec, clock, self.mutants, state_dir, external, self.mode)


NEGATIVES = {   # name -> (mode, mutants): the known-negative fakes of ORACLE-AND-HARNESS-G4 s8
    "FakeHonest": ("honest", ()), "FakeTrustsReply": ("honest", ("adapter_success_trusted",)),
    "FakeRootCapToAdapter": ("honest", ("credential_scope_broadened",)), "FakeAdapterPolicy": ("honest", ("policy_gate_in_adapter",)),
    "FakeFreshCapRetry": ("honest", ("idempotency_disabled",)), "FakeReadsAdapterObservations": ("honest", ("observation_coupled",)),
    "FakeAnyRowSuccess": ("honest", ("divergence_rewritten",)), "FakeConsumesArtefact": ("FakeConsumesArtefact", ()),
    "FakeAlwaysUnknown": ("always_unknown", ()), "FakeNeverDispatch": ("never_dispatch", ()),
}


def load(name: str, mutants=()):
    key = name.split("fake-", 1)[1] if name.startswith("fake-") else name
    mode, m = NEGATIVES[key]
    return H28Fake(mode, tuple(m) + tuple(mutants))
