"""Byzantine action-adapter catalogue (P1f-7 ids, ORACLE-AND-HARNESS-G4 s3). Adapters are HARNESS code: they get an
ExternalRequest only (never a root cap, never a variant object) and write through the data-plane client. Compositions of up to
3 primitives are one `Composite`. Every write ATTEMPT is logged harness-side in `attempts` (ground truth for the detection
clause); the Recorder logs every ExternalRequest the variant hands over (-> byzantine-adapter-corpus.json)."""
from __future__ import annotations

import copy
import random

from r3_shared import extcap
from r3_shared.extadapter import AdapterReply, canon_json, payload_digest

PRIMS = ("H0", "L1", "L2", "L3", "T1", "T2", "T3", "R1", "R2", "O1", "O2", "G1", "G2", "G3")
POLICY_BODY = {"reason": "policy: fee exceeds limit", "decision": "deny"}
ARTEFACT_BODY = {"approval": {"approver": "harness-fake", "status": "approved"}, "grant": {"operation": "*", "resource": "*"},
                 "on_behalf_of": "harness-fake", "status": "approved", "policy": "allow"}


class Scheduler:
    """Delayed adapter writes (O2): the harness executes them at the scheduled tick through the same write() call."""
    def __init__(self):
        self.pending: list[tuple[int, int, object]] = []
        self._n = 0

    def at(self, tick: int, fn) -> None:
        self._n += 1
        self.pending.append((tick, self._n, fn))

    def due(self, now: int) -> list:
        ready = sorted(p for p in self.pending if p[0] <= now)
        self.pending = [p for p in self.pending if p[0] > now]
        return [(t, fn) for t, _, fn in ready]


def mutate_payload(payload: dict) -> dict:
    out = copy.deepcopy(payload)
    for k in sorted(out):
        v = out[k]
        if isinstance(v, int) and not isinstance(v, bool):
            out[k] = v * 10 + 1
            return out
    k = sorted(out)[0] if out else "x"
    out[k] = f"{out.get(k, '')}~mut"
    return out


class Composite:
    def __init__(self, client, prims, seed: int, sched: Scheduler, now, alt_targets=(), cap_pool=None, k: int = 2, reps: int = 2):
        bad = [p for p in prims if p not in PRIMS]
        if bad:
            raise ValueError(f"unknown primitives {bad}")
        self.client, self.prims, self.k, self.reps = client, tuple(prims), k, reps
        self.adapter_id = "+".join(prims) if prims else "H0"
        self.sched, self.now, self.alt, self.pool = sched, now, list(alt_targets), cap_pool if cap_pool is not None else []
        self.rng, self.calls, self.attempts, self.receipts = random.Random(seed), 0, [], []

    def has(self, p: str) -> bool:
        return p in self.prims

    def _write(self, req, cap, op, target, payload, kind: str, tick: int | None = None):
        rec = self.client.write(cap, op, target, payload, self.adapter_id)
        self.attempts.append({"request_id": req.request_id, "effect_index": req.effect_index, "system": req.system, "op": op,
                              "target": target, "payload_digest": payload_digest(payload), "kind": kind,
                              "cap_chain": extcap.chain_id(cap) if cap.startswith(extcap.PREFIX) else "",
                              "tick": self.now() if tick is None else tick, "cap": cap, "status": rec.status, "reason": rec.reason})
        self.receipts.append(rec)
        return rec

    def _alt_target(self, req) -> str:
        cands = [t for t in self.alt if t != req.target]
        return cands[self.rng.randrange(len(cands))] if cands else req.target + "~alt"

    def submit(self, req) -> AdapterReply:
        self.calls += 1
        has = self.has
        intended = not (has("L1") or has("O1") or has("G1") or has("O2") or has("T1") or has("T2"))
        first, last = None, None
        if intended and not has("O1"):
            first = last = self._write(req, req.cap, req.operation, req.target, req.payload, "intended")
        if has("O2"):
            tick = self.now() + self.k
            self.sched.at(tick, lambda r=req, t=tick: self._write(r, r.cap, r.operation, r.target, r.payload, "delayed", t))
        if has("T1") or has("T3"):
            last = self._write(req, req.cap, req.operation, self._alt_target(req), req.payload, "target_substitution")
        if has("T2"):
            last = self._write(req, req.cap, req.operation, req.target, mutate_payload(req.payload), "payload_mutation")
        if has("T3") and first is None:
            first = self._write(req, req.cap, req.operation, req.target, req.payload, "intended")
        if has("R1"):
            for _ in range(self.reps):
                last = self._write(req, req.cap, req.operation, req.target, req.payload, "duplicate")
        if has("R2") and self.pool:
            last = self._write(req, self.pool[-1], req.operation, req.target, req.payload, "cap_replay")
        if has("G3"):
            self._g3(req)
        if has("L1") or has("G1") or has("O1"):
            pass                                                               # no write at all for the intended effect
        self.pool.append(req.cap)
        return self._reply(req, first or last)

    def _g3(self, req) -> None:
        """Widening is impossible by construction: try (a) a hand-edited token without the target caveat, (b) a guessed root cap."""
        nonce, steps, sig = extcap._decode(req.cap)
        cut = [[c for c in st if c[0] != "target"] for st in steps]
        forged = extcap._encode(nonce, cut, bytes.fromhex(sig))
        self._write(req, forged, req.operation, self._alt_target(req), req.payload, "cap_forge")
        guess = extcap.mint_root(self.rng.randbytes(32), nonce, req.system, "guess")
        self._write(req, guess, req.operation, self._alt_target(req), req.payload, "root_guess")

    def _reply(self, req, rec) -> AdapterReply:
        has = self.has
        if has("O1"):
            raise TimeoutError("adapter dropped the request")
        if has("L3"):
            raise TimeoutError("adapter timed out after applying")
        if has("L2"):
            return AdapterReply("FAILED", {"reason": "backend error"})
        if has("G1"):
            return AdapterReply("FAILED", dict(POLICY_BODY))
        if has("L1"):
            return AdapterReply("OK", {"observed": {"applied": True}})
        if has("O2") or has("T1") or has("T2") or has("T3"):
            return AdapterReply("OK", {"observed": {"applied": True}})
        ok = rec is not None and rec.status == "applied"
        body = {"seq": rec.seq if rec else 0, "observed": {"applied": ok}}
        if has("G2"):
            body.update(copy.deepcopy(ARTEFACT_BODY))
        return AdapterReply("OK" if ok else "FAILED", body)


class Recorder:
    """Harness-side wrapper OUTSIDE the variant: logs every ExternalRequest the adapter receives."""
    def __init__(self, inner, system: str, now):
        self.inner, self.adapter_id, self.system, self.now, self.log = inner, inner.adapter_id, system, now, []

    def submit(self, req):
        self.log.append({**req.as_dict(), "tick": self.now()})
        return self.inner.submit(req)


def corpus_adapter_spec(prims, k=2, reps=2) -> dict:
    return {"prims": list(prims), "k": k, "reps": reps, "adapter_id": "+".join(prims) if prims else "H0"}
