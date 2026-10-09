"""Reference behaviour for the Gate 4 Deployment surface (fakes only; never registered): deploy(external=...), dispatch_pending,
reconcile, outcome. Honest about the P1f protocol (decide-then-dispatch outbox, per-effect attenuated cap, same-cap resubmission,
observer-only outcomes, replayed request_id never re-dispatches) but it has no ops-spec/authority semantics: the fake's `put`
operation takes an optional args["ext"] = [{"system","operation","payload"}...] standing in for the ops-spec `external` effects.
With external=None the legacy in-transaction WorldHandle.external_write path runs, unchanged."""
from __future__ import annotations

import json
from pathlib import Path

from r3_shared import extcap
from r3_shared.extadapter import ExternalRequest, correlation, payload_digest
from r3_shared.extobs import ObserverUnavailable
from r3_shared.extsystems import idempotency, observability, render_target
from r3_shared.outcome import validate_outcome
from r3_shared.variant import CallResult
from tests.fakes.ext_ref import outcome_state

MAX_ATTEMPTS = 3


class G4Mixin:
    def _g4_init(self, external):
        self.external = external
        self.g4 = {"intents": [], "outcomes": {}}
        p = self._g4_path()
        if external is not None and p is not None and p.exists():
            self.g4 = json.loads(p.read_text())

    def _g4_path(self):
        return Path(self.state_dir) / "g4.json" if self.state_dir else None

    def _g4_save(self):
        p = self._g4_path()
        if p is not None:
            p.write_text(json.dumps(self.g4, sort_keys=True))

    def _g4_record(self, rid, ext, tick):
        """Called inside the request's commit path AFTER the world commit: persist the intents (R28 outbox) with their caps."""
        b = self.external
        for i, e in enumerate(ext):
            sysd, op = b.systems["systems"][e["system"]], e["operation"]
            target = render_target(sysd["operations"][op]["target_rule"], e["payload"])
            cls = idempotency(b.systems, e["system"], op)
            cap = extcap.attenuate(b.root_caps[e["system"]], system=e["system"], operation=op, target=target,
                                   payload_digest=payload_digest(e["payload"]), correlation=correlation(rid, i),
                                   max_uses=1 if cls != "idempotent_set" else 3, not_after_tick=tick + b.window)
            self.g4["intents"].append({"request_id": rid, "effect_index": i, "system": e["system"], "operation": op,
                                       "target": target, "payload": e["payload"], "cap": cap, "class": cls,
                                       "commit_tick": tick, "attempts": 0, "done": False})
            self.g4["outcomes"][f"{rid}#{i}"] = {"request_id": rid, "effect_index": i, "system": e["system"],
                                                 "state": "PENDING", "confidence": "full" if observability(b.systems, e["system"]) == "full" else "low",
                                                 "evidence": []}
            if observability(b.systems, e["system"]) == "none":
                self.g4["outcomes"][f"{rid}#{i}"].update(state="UNKNOWN", confidence="low")
        self._g4_save()

    def dispatch_pending(self):
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            if self.external is None:
                return CallResult("OK", {"submitted": 0})
            n = 0
            for it in self.g4["intents"]:
                if it["done"] or it["attempts"] >= MAX_ATTEMPTS:
                    continue
                it["attempts"] += 1
                n += 1
                req = ExternalRequest(it["request_id"], it["effect_index"], it["system"], it["operation"], it["target"],
                                      it["payload"], "", it["cap"])
                try:
                    reply = self.external.adapters[it["system"]].submit(req)
                    it["done"] = reply.status == "OK"                        # the reply only decides resubmission (R28-8)
                except Exception:
                    pass
            self._g4_save()
            return CallResult("OK", {"submitted": n})

    def _g4_outs(self, rid):
        outs = [o for k, o in self.g4["outcomes"].items() if o["request_id"] == rid]
        return sorted(outs, key=lambda o: o["effect_index"])

    def reconcile(self, request_id, watermark):
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            if not self._g4_outs(request_id):
                return CallResult("INVALID", {"reason": "unknown_request"})
            try:
                snap = self.external.observer.read(watermark=watermark)
            except ObserverUnavailable:
                snap = None
            for it in (i for i in self.g4["intents"] if i["request_id"] == request_id):
                o = self.g4["outcomes"][f"{request_id}#{it['effect_index']}"]
                st, conf, ev = outcome_state(
                    {"operation": it["operation"], "target": it["target"], "payload_digest": payload_digest(it["payload"]),
                     "correlation": correlation(request_id, it["effect_index"])}, snap, o["state"], o["evidence"], it["class"],
                    observability(self.external.systems, it["system"]), it["commit_tick"] + self.external.window)
                o.update(state=st, confidence=conf, evidence=ev)
            self._g4_save()
            return CallResult("OK", {"outcomes": [validate_outcome(dict(o)) for o in self._g4_outs(request_id)]})

    def outcome(self, request_id):
        outs = self._g4_outs(request_id)
        if not outs:
            return CallResult("INVALID", {"reason": "unknown_request"})
        return CallResult("OK", {"outcomes": [validate_outcome(dict(o)) for o in outs]})
