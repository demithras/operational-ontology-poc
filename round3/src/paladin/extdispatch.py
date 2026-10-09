"""Adapter-side plane of the Paladin variant (PROT-H28 1.3 ADAPTER_MODULES): per-effect capability attenuation, the
ExternalRequest, submit, retry policy, and reconciliation against the OBSERVER. It contains no authority, policy, approval or
governance logic and reads nothing from an adapter reply except its STATUS string (to decide whether to resubmit).

The decision plane (Engine + Core) is final before anything here runs: `register` is called after the world commit, `dispatch`
only from `dispatch_pending`.
"""
from __future__ import annotations

import importlib

from paladin import extoutcome
from paladin.extoutbox import Outbox
from r3_shared import extadapter, extcap, extsystems
from r3_shared.extobs import EffRow, ObserverUnavailable, ObsSnapshot

MAX_ATTEMPTS = 3          # total submissions of one intent (R28-8; the cap itself bounds applied rows)
USES = {"at_most_once": 1, "exactly_once_required": 1, "idempotent_set": 3}
_OK, _FAILED, _TIMEOUT = extadapter.REPLY_OK, extadapter.REPLY_FAILED, extadapter.REPLY_TIMEOUT


class ExtPlane:
    def __init__(self, binding, ledger, ops_spec, mutants=frozenset()):
        self.b, self.box, self.mutants = binding, Outbox(ledger), frozenset(mutants)
        self.ops_spec = ops_spec
        self._gate = None
        if "policy_gate_in_adapter" in self.mutants:   # mutant-only module, loaded by name (see variant.adapter_modules)
            self._gate = importlib.import_module("paladin.extgate_mut")

    # ---- registration (after the world commit) --------------------------------------------------------------------
    def attenuate(self, intent: dict, attempt: int) -> str:
        """R28-13: system+operation+target+payload digest+correlation+max_uses+expiry, narrowed from the system's root cap."""
        root = self.b.root_caps[intent["system"]]
        cav = dict(operation=intent["operation"], target=intent["target"], payload_digest=intent["payload_digest"],
                   correlation=intent["correlation"], max_uses=USES[intent["idempotency"]], not_after_tick=intent["expiry"])
        if "credential_scope_broadened" in self.mutants:       # MUTANT: no target / payload binding (G4-E5: correlation kept)
            cav.pop("target"), cav.pop("payload_digest")
        if "idempotency_disabled" in self.mutants:            # MUTANT: every (re)submission mints a different chain, unbounded uses
            cav["max_uses"] = 1000 + attempt
        return extcap.attenuate(root, system=intent["system"], **cav)

    def register(self, rid: str, tick: int, plans: list[dict]) -> list[dict]:
        sysd, window, effs = self.b.systems, self.b.window, []
        for p in sorted(plans, key=lambda x: x["effect_index"]):
            s, op = p["system"], p["operation"]
            payload = p["payload"]
            i = {"index": p["effect_index"], "request_id": rid, "action": p["action"], "system": s, "operation": op,
                 "target": extsystems.render_target(sysd["systems"][s]["operations"][op]["target_rule"], payload),
                 "payload": payload, "payload_digest": extadapter.payload_digest(payload), "inputs": p["inputs"],
                 "correlation": extadapter.correlation(rid, p["effect_index"]), "tick": tick, "expiry": tick + window,
                 "idempotency": extsystems.idempotency(sysd, s, op), "observability": extsystems.observability(sysd, s),
                 "attempts": 0, "replies": []}
            i["cap"] = self.attenuate(i, 0)
            i["outcome"] = extoutcome.initial(i)
            effs.append(i)
        self.box.put(rid, effs)
        return [self.public(e) for e in effs]

    @staticmethod
    def public(e: dict) -> dict:
        o = e["outcome"]
        return {"request_id": e["request_id"], "effect_index": e["index"], "system": e["system"], "state": o["state"],
                "confidence": o["confidence"], "evidence": list(o["evidence"])}

    # ---- dispatch -------------------------------------------------------------------------------------------------
    def due(self, e: dict) -> bool:
        if e["outcome"]["state"] in ("RECONCILED_SUCCESS", "DIVERGED") or e["attempts"] >= MAX_ATTEMPTS:
            return False
        return not e["replies"] or e["replies"][-1] != _OK

    def dispatch(self, envelope_of) -> int:
        """Submit every due intent; `envelope_of(request_id)` -> the byte-exact decision envelope text, or None when a
        provable envelope is not available yet (the intent then waits)."""
        n = 0
        for rid in self.box.rids():
            for e in self.box.get(rid) or []:
                if not self.due(e):
                    continue
                env = envelope_of(rid)
                if env is None:
                    continue
                n += self._submit(rid, e, env)
        return n

    def _submit(self, rid: str, e: dict, env: str) -> int:
        if self._gate is not None and self._gate.refuses(e, self.ops_spec):        # MUTANT policy_gate_in_adapter
            self.box.update(rid, e["index"], attempts=MAX_ATTEMPTS)
            return 0
        cap = self.attenuate(e, e["attempts"]) if "idempotency_disabled" in self.mutants else e["cap"]
        req = extadapter.ExternalRequest(rid, e["index"], e["system"], e["operation"], e["target"], e["payload"], env, cap)
        try:
            reply = self.b.adapters[e["system"]].submit(req)
            st = reply.status if isinstance(reply, extadapter.AdapterReply) else _FAILED
            st = st if st in (_OK, _FAILED, _TIMEOUT) else _FAILED
        except Exception:                                            # noqa: BLE001 - any exception is a TIMEOUT (P1f-7)
            st = _TIMEOUT
        self.box.update(rid, e["index"], attempts=e["attempts"] + 1, replies=[*e["replies"], st], cap=cap)
        return 1

    # ---- reconciliation (observer is the only evidence) -----------------------------------------------------------
    def _snapshot(self, effs: list[dict], watermark: int):
        if "observation_coupled" in self.mutants:       # MUTANT: adapter-reported "observations" instead of the observer
            rows = [EffRow(10_000 + k, e["tick"], e["system"], e["operation"], e["target"], e["payload_digest"], "", e["correlation"],
                           "reported") for k, e in enumerate(effs) if e["replies"] and e["replies"][-1] == _OK]
            return ObsSnapshot(watermark, rows, [], watermark)
        return self.b.observer.read(watermark=watermark)

    def reconcile(self, rid: str, watermark: int) -> list[dict] | None:
        effs = self.box.get(rid)
        if not effs:
            return None
        try:
            snap = self._snapshot(effs, watermark)
        except ObserverUnavailable:
            snap = None
        for e in effs:
            new = extoutcome.outcome_state(e, snap, e["outcome"], self.mutants)
            if "adapter_success_trusted" in self.mutants and e["replies"] and e["replies"][-1] == _OK \
                    and new["state"] not in ("DIVERGED",):
                new = {**new, "state": "RECONCILED_SUCCESS"}             # MUTANT: the adapter's OK is believed
            self.box.update(rid, e["index"], outcome=new)
        return [self.public(e) for e in self.box.get(rid) or []]

    def outcomes(self, rid: str) -> list[dict] | None:
        effs = self.box.get(rid)
        return None if not effs else [self.public(e) for e in sorted(effs, key=lambda x: x["index"])]
