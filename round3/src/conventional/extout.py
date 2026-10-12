"""Transactional outbox + dispatcher for external effects (PROT-H28 R28-1, R28-8, R28-13; P1f-1, P1f-7).

Adapter-side code (ADAPTER_MODULES). In the request's world transaction the service enqueues one intent per ops-spec
`external` effect: the intent, its per-effect attenuated capability (token exchange: root cap -> downscoped cap) and the
initial outcome record. After the commit the dispatcher submits each intent to the harness-supplied adapter of its system.
The root cap never leaves this module; an adapter reply decides ONLY whether a resubmission (same cap) is allowed.
Nothing here imports the decision plane (authority / policy / approval / governance / disclosure).
"""
from __future__ import annotations

import importlib
import json

from r3_shared.faultplane import DependencyUnavailable

from r3_shared import extcap
from r3_shared.extadapter import ExternalRequest, correlation, payload_digest
from r3_shared.extsystems import idempotency, observability, render_target

from . import extrecon

MAX_ATTEMPTS = 3          # resubmissions of ONE intent (same cap) across all dispatch calls
IDEMPOTENT_SET_USES = 3   # frozen upper bound for idempotent_set (R28-8)
DDL = """
CREATE TABLE IF NOT EXISTS conv_outbox(
  request_id TEXT NOT NULL, effect_index INTEGER NOT NULL, system TEXT NOT NULL, operation TEXT NOT NULL,
  target TEXT NOT NULL, payload_json TEXT NOT NULL, cap TEXT NOT NULL, cls TEXT NOT NULL, observability TEXT NOT NULL,
  commit_tick INTEGER NOT NULL, expiry INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0,
  reply TEXT NOT NULL DEFAULT '', held INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(request_id, effect_index));
CREATE TABLE IF NOT EXISTS conv_outcome(
  request_id TEXT NOT NULL, effect_index INTEGER NOT NULL, system TEXT NOT NULL, state TEXT NOT NULL,
  confidence TEXT NOT NULL, evidence_json TEXT NOT NULL DEFAULT '[]', wm INTEGER NOT NULL DEFAULT -1, PRIMARY KEY(request_id, effect_index));
CREATE TRIGGER IF NOT EXISTS conv_outcome_monotone BEFORE UPDATE OF state ON conv_outcome
WHEN OLD.state IN ('RECONCILED_SUCCESS','RECONCILED_FAILED','DIVERGED') AND NEW.state NOT IN (OLD.state,'DIVERGED')
BEGIN SELECT RAISE(ABORT, 'outcome transition not allowed'); END;
"""
COLS = ("request_id", "effect_index", "system", "operation", "target", "payload_json", "cap", "cls", "observability",
        "commit_tick", "expiry", "attempts", "done", "reply", "held")


def init(h) -> None:
    h._con.executescript(DDL)


def synthetic_request_id(world_seq: int) -> str:
    """Deterministic correlation base for a commit that carried no request_id (no replay protection either)."""
    return f"anon-tx{world_seq}"


class Outbox:
    def __init__(self, binding, mutants=frozenset()):
        self.b, self.mut = binding, frozenset(mutants)
        self.guard = None   # G5: per-node breakers (g5deps.Guard); None on the legacy path

    # -- enqueue: runs INSIDE the request's world transaction (R28-1: the decision is final before any adapter call) ----------
    def _caveats(self, system, op, target, payload, rid, idx, cls, tick) -> dict:
        cav = dict(system=system, operation=op, target=target, payload_digest=payload_digest(payload),
                   correlation=correlation(rid, idx), max_uses=1 if cls != "idempotent_set" else IDEMPOTENT_SET_USES,
                   not_after_tick=tick + self.b.window)
        if "credential_scope_broadened" in self.mut:  # BUG (G4-E5): target + payload binding dropped; correlation kept
            del cav["target"], cav["payload_digest"]
        return cav

    def _gate_hold(self, system: str, op: str, payload: dict, cleared: bool) -> bool:
        """BUG (policy_gate_in_adapter): the moved approval rules live in a mutant-only module, loaded by name only here."""
        if "policy_gate_in_adapter" not in self.mut or cleared:
            return False
        return importlib.import_module("conventional.extgate_mut").holds(system, op, payload)

    def enqueue(self, h, rid: str, planned: list[dict], tick: int, cleared: bool = True) -> int:
        n = 0
        for idx, e in enumerate(planned):
            system, op, payload = e["adapter"], e["target"], e["payload"]
            decl = self.b.systems["systems"][system]["operations"][op]
            target = render_target(decl["target_rule"], payload)
            cls, obs = idempotency(self.b.systems, system, op), observability(self.b.systems, system)
            cap = extcap.attenuate(self.b.root_caps[system], **self._caveats(system, op, target, payload, rid, idx, cls, tick))
            h._con.execute("INSERT INTO conv_outbox(request_id,effect_index,system,operation,target,payload_json,cap,cls,"
                           "observability,commit_tick,expiry,held) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (rid, idx, system, op, target, json.dumps(payload, sort_keys=True), cap, cls, obs, tick,
                            tick + self.b.window, 1 if self._gate_hold(system, op, payload, cleared) else 0))
            st, conf = extrecon.initial_state(obs)
            h._con.execute("INSERT INTO conv_outcome(request_id,effect_index,system,state,confidence) VALUES(?,?,?,?,?)",
                           (rid, idx, system, st, conf))
            n += 1
        return n

    # -- reads ------------------------------------------------------------------------------------------------------------
    def intents(self, h, rid: str | None = None) -> list[dict]:
        q = "SELECT " + ",".join(COLS) + " FROM conv_outbox" + (" WHERE request_id=?" if rid else "") + \
            " ORDER BY request_id, effect_index"
        return [dict(zip(COLS, r)) for r in h._con.execute(q, (rid,) if rid else ())]

    def outcomes(self, h, rid: str) -> list[dict]:
        rows = h._con.execute("SELECT request_id,effect_index,system,state,confidence,evidence_json FROM conv_outcome "
                              "WHERE request_id=? ORDER BY effect_index", (rid,)).fetchall()
        return [{"request_id": a, "effect_index": b, "system": c, "state": d, "confidence": e,
                 "evidence": json.loads(f)} for a, b, c, d, e, f in rows]

    # -- dispatch: AFTER the world commit ---------------------------------------------------------------------------------
    def _fresh_cap(self, it: dict) -> str:
        """BUG (idempotency_disabled): every (re)submission mints a new cap with unbounded uses (distinct caveats, new chain)."""
        payload = json.loads(it["payload_json"])
        cav = self._caveats(it["system"], it["operation"], it["target"], payload, it["request_id"], it["effect_index"],
                            it["cls"], it["commit_tick"])
        cav["max_uses"] = 1000 + it["attempts"]
        return extcap.attenuate(self.b.root_caps[it["system"]], **cav)

    def _eligible(self, it: dict, now: int) -> bool:
        if it["done"] or it["held"] or it["attempts"] >= MAX_ATTEMPTS:
            return False
        return "idempotency_disabled" in self.mut or now <= it["expiry"]

    @staticmethod
    def _settled(h, it: dict) -> bool:
        """The observer already showed a final truth: nothing to resubmit."""
        r = h._con.execute("SELECT state FROM conv_outcome WHERE request_id=? AND effect_index=?",
                           (it["request_id"], it["effect_index"])).fetchone()
        return r is not None and r[0] in ("RECONCILED_SUCCESS", "DIVERGED")

    def dispatch(self, h, envelope_for, now: int, rid: str | None = None) -> int:
        """Submit every eligible intent (R28-8: same cap on resubmission). Returns the number of submit() calls."""
        n = 0
        tripped: set[str] = set()   # systems whose breaker opened in THIS pass: one half-open trial per system per pass
        for it in self.intents(h, rid):
            if not self._eligible(it, now) or self._settled(h, it) or it["system"] in tripped:
                continue
            payload = json.loads(it["payload_json"])
            cap = self._fresh_cap(it) if "idempotency_disabled" in self.mut else it["cap"]
            req = ExternalRequest(it["request_id"], it["effect_index"], it["system"], it["operation"], it["target"], payload,
                                  envelope_for(it["request_id"]), cap)
            status = "TIMEOUT"
            node = f"EXT:{it['system']}"
            try:
                status = self.b.adapters[it["system"]].submit(req).status       # UNTRUSTED: only decides resubmission
                if self.guard is not None:
                    self.guard.up(node)
            except DependencyUnavailable:   # G5: the system is down - not an attempt (the intent stays deliverable)
                if self.guard is not None:
                    self.guard.down(node)
                    tripped.add(it["system"])
                    continue
            except Exception:  # noqa: BLE001 - any exception is a TIMEOUT (P1f-7)
                pass
            n += 1
            ok = status == "OK"
            h._con.execute("UPDATE conv_outbox SET attempts=attempts+1, done=?, reply=? WHERE request_id=? AND effect_index=?",
                           (1 if ok else 0, status, it["request_id"], it["effect_index"]))
            if ok and "adapter_success_trusted" in self.mut:   # BUG: the adapter's OK becomes the outcome
                h._con.execute("UPDATE conv_outcome SET state='RECONCILED_SUCCESS' WHERE request_id=? AND effect_index=? "
                               "AND state IN ('PENDING','UNKNOWN')", (it["request_id"], it["effect_index"]))
        return n
