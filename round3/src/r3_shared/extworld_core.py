"""ExternalWorld state machine (PROT-H28 R28-9, R28-14; P1f-2). HARNESS ONLY - variant packages never import this module
or extworld_server. Owns <dir>/external.db (SQLite WAL) and a random root key held in memory until close()."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
from pathlib import Path

from . import extcap
from .extadapter import canon_json, payload_digest
from .extobs import DB_NAME, key_hash
from .extsem import SEMANTICS
from .extsystems import validate_systems

REFUSALS_G5 = ("unavailable",)  # P1g-3/Q12: appended AFTER the frozen P1f-2 reasons, but evaluated FIRST
REFUSALS = ("bad_signature", "unknown_root", "system_mismatch", "operation_mismatch", "target_mismatch", "payload_mismatch",
            "correlation_missing", "expired", "uses_exhausted")
KEY_NAME, HEAD_NAME = "KEY.revealed", "HEAD.final"
_DDL = """
CREATE TABLE effects(seq INTEGER PRIMARY KEY AUTOINCREMENT, tick INTEGER NOT NULL, deployment TEXT NOT NULL, system TEXT NOT NULL,
  operation TEXT NOT NULL, target TEXT NOT NULL, payload_json TEXT NOT NULL, payload_digest TEXT NOT NULL, cap_chain TEXT NOT NULL,
  correlation TEXT NOT NULL, adapter_id TEXT NOT NULL);
CREATE TABLE audit(seq INTEGER PRIMARY KEY AUTOINCREMENT, tick INTEGER NOT NULL, deployment TEXT NOT NULL, system TEXT NOT NULL,
  operation TEXT NOT NULL, target TEXT NOT NULL, payload_digest TEXT NOT NULL, cap_chain TEXT NOT NULL, correlation TEXT NOT NULL,
  adapter_id TEXT NOT NULL, outcome TEXT NOT NULL CHECK(outcome IN ('applied','refused')), reason TEXT NOT NULL);
CREATE TABLE sysstate(system TEXT NOT NULL, key TEXT NOT NULL, props_json TEXT NOT NULL, version INTEGER NOT NULL,
  PRIMARY KEY(system, key));
CREATE TABLE obs_keys(key_hash TEXT PRIMARY KEY, deployment TEXT NOT NULL);
CREATE TABLE issued(nonce TEXT PRIMARY KEY, system TEXT NOT NULL, deployment TEXT NOT NULL, tick INTEGER NOT NULL,
  UNIQUE(system, deployment));
CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


class Unavailable(Exception):
    """Raised by ExternalWorldCore.write under an armed outage/partition window; the server maps it to an `unavailable` reply."""


class ExternalWorldCore:
    def __init__(self, ext_dir, systems: dict, root_key: bytes | None = None):
        self.dir, self.systems = Path(ext_dir), validate_systems(systems)
        self.dir.mkdir(parents=True, exist_ok=True)
        db = self.dir / DB_NAME
        if db.exists():
            raise FileExistsError(f"{db} already exists: refusing to reuse an external ledger")
        self.key, self.lock, self.tick, self.closed = root_key or os.urandom(32), threading.RLock(), 0, False
        self.faults: list[dict] = []  # G5 outage/partition windows (P1g-3); empty -> write() is exactly the G4 path
        self.con = sqlite3.connect(str(db), isolation_level=None, check_same_thread=False)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(_DDL)
        self.con.execute("INSERT INTO meta VALUES('tick','0')")

    # ---- control plane (harness only) ----------------------------------------------------------------------------
    def advance(self, tick: int) -> int:
        with self.lock:
            if not isinstance(tick, int) or isinstance(tick, bool) or tick < self.tick:
                raise ValueError(f"tick must be an int >= current tick {self.tick}")
            self.tick = tick
            self.con.execute("UPDATE meta SET v=? WHERE k='tick'", (str(tick),))
            return tick

    def issue_root(self, deployment: str, system: str) -> str:
        with self.lock:
            if system not in self.systems["systems"]:
                raise ValueError(f"unknown system {system!r}")
            nonce = hashlib.sha256(f"r3root|{deployment}|{system}".encode()).hexdigest()[:32]
            self.con.execute("INSERT OR IGNORE INTO issued VALUES(?,?,?,?)", (nonce, system, deployment, self.tick))
            return extcap.mint_root(self.key, nonce, system, deployment)

    def observer_key(self, deployment: str) -> str:
        with self.lock:
            k = hmac.new(self.key, b"r3obs|" + deployment.encode(), hashlib.sha256).hexdigest()
            self.con.execute("INSERT OR IGNORE INTO obs_keys VALUES(?,?)", (key_hash(k), deployment))
            return k

    def seed(self, system: str, key: str, props: dict) -> None:
        with self.lock:
            self._put(system, key, props)

    def close(self) -> dict:
        with self.lock:
            self.closed = True
            head = {"effects": self.con.execute("SELECT count(*) FROM effects").fetchone()[0],
                    "audit": self.con.execute("SELECT count(*) FROM audit").fetchone()[0]}
            self.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.con.execute("PRAGMA journal_mode=DELETE")  # a closed ledger stays readable read-only without -wal/-shm
            self.con.close()
            (self.dir / HEAD_NAME).write_text(json.dumps(head))
            (self.dir / KEY_NAME).write_text(self.key.hex())
            return {"root_key_hex": self.key.hex(), "head": head}

    # ---- data plane ------------------------------------------------------------------------------------------------
    def _get(self, system: str, key: str) -> dict:
        r = self.con.execute("SELECT props_json FROM sysstate WHERE system=? AND key=?", (system, key)).fetchone()
        return json.loads(r[0]) if r else {}

    def _put(self, system: str, key: str, props: dict) -> None:
        self.con.execute("INSERT INTO sysstate VALUES(?,?,?,1) ON CONFLICT(system,key) DO UPDATE SET props_json=excluded.props_json,"
                         " version=version+1", (system, key, canon_json(props)))

    def _audit(self, dep, system, op, target, dig, chain, cor, adapter, outcome, reason) -> int:
        return self.con.execute("INSERT INTO audit(tick,deployment,system,operation,target,payload_digest,cap_chain,correlation,"
                                "adapter_id,outcome,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                (self.tick, dep, system, op, target, dig, chain, cor, adapter, outcome, reason)).lastrowid

    # ---- G5 fault controls (control plane only) ---------------------------------------------------------------------
    def fault(self, cmd: dict) -> int:
        """outage/partition window for (target system, deployment); validated form faultplane.validate_fault_command.
        outage = mode drop; partition = drop or reply_lost. Logged in fault_log (created lazily: G4 ledgers keep their DDL)."""
        from .faultplane import validate_fault_command
        with self.lock:
            validate_fault_command(cmd)
            if cmd.get("target") not in self.systems["systems"]:
                raise ValueError(f"fault target must be a declared system, got {cmd.get('target')!r}")
            if cmd["op"] == "outage" and cmd["mode"] != "drop":
                raise ValueError("an outage is mode drop")
            self.con.execute("CREATE TABLE IF NOT EXISTS fault_log(seq INTEGER PRIMARY KEY AUTOINCREMENT, tick INTEGER NOT NULL,"
                             " deployment TEXT NOT NULL, system TEXT NOT NULL, op TEXT NOT NULL, mode TEXT NOT NULL,"
                             " from_tick INTEGER NOT NULL, to_tick INTEGER NOT NULL)")
            self.con.execute("INSERT INTO fault_log(tick,deployment,system,op,mode,from_tick,to_tick) VALUES(?,?,?,?,?,?,?)",
                             (self.tick, cmd["deployment"], cmd["target"], cmd["op"], cmd["mode"], cmd["from_tick"], cmd["to_tick"]))
            self.faults.append(dict(cmd))
            return len(self.faults)

    def clear_faults(self) -> None:
        with self.lock:
            self.faults = []

    def fault_log(self) -> list[dict]:
        with self.lock:
            if self.con.execute("SELECT 1 FROM sqlite_master WHERE name='fault_log'").fetchone() is None:
                return []
            cols = ("seq", "tick", "deployment", "system", "op", "mode", "from_tick", "to_tick")
            return [dict(zip(cols, r)) for r in self.con.execute("SELECT " + ",".join(cols) + " FROM fault_log ORDER BY seq")]

    def _window(self, cap: str):
        """Active fault window for the (system, deployment) a cap CLAIMS (unverified peek: a down system authenticates nothing)."""
        try:
            cav = extcap.caveats_of(cap)
            system, dep = cav[0][1], cav[1][1]
        except (extcap.CapError, IndexError, TypeError):
            return None, "", ""
        for w in self.faults:
            if w["target"] == system and w["deployment"] == dep and w["from_tick"] <= self.tick < w["to_tick"]:
                return w, system, dep
        return None, system, dep

    @staticmethod
    def _claim(cap: str, system: str, dep: str) -> dict:
        """What an UNVERIFIED cap says about itself. Never an attribution field (G5-E4)."""
        try:
            cav = [[n, v] for n, v in extcap.caveats_of(cap)]
        except (extcap.CapError, TypeError, IndexError):
            cav = []
        return {"system": system, "deployment": dep, "caveats": cav}

    def unverified_claims(self) -> dict:
        """audit seq -> unverified_claim for `unavailable` rows (separate from the attributed audit columns)."""
        with self.lock:
            if self.con.execute("SELECT 1 FROM sqlite_master WHERE name='unverified_claim'").fetchone() is None:
                return {}
            return {r[0]: json.loads(r[1]) for r in self.con.execute("SELECT audit_seq, claim_json FROM unverified_claim")}

    def write(self, cap: str, operation: str, target: str, payload: dict, adapter_id: str) -> dict:
        if not self.faults:
            return self._write(cap, operation, target, payload, adapter_id)
        with self.lock:
            w, system, dep = self._window(cap) if not self.closed else (None, "", "")
            if w is None:
                return self._write(cap, operation, target, payload, adapter_id)
            if w["mode"] == "drop":  # evaluated BEFORE bad_signature (Q12): no effect, one refused/unavailable audit row
                # G5-E4: the claim is unverified, so the row attributes NOTHING (deployment/system/chain/correlation empty);
                # the claimed (system, deployment, caveats) are kept apart under "unverified_claim".
                seq = self._audit("", "", operation, target, payload_digest(payload), "", "", adapter_id, "refused", "unavailable")
                self.con.execute("CREATE TABLE IF NOT EXISTS unverified_claim(audit_seq INTEGER PRIMARY KEY, claim_json TEXT NOT NULL)")
                self.con.execute("INSERT INTO unverified_claim VALUES(?,?)", (seq, canon_json(self._claim(cap, system, dep))))
                raise Unavailable(system)
            self._write(cap, operation, target, payload, adapter_id)  # reply_lost: applied (or refused) as usual, reply dropped
            raise Unavailable(system)

    def _write(self, cap: str, operation: str, target: str, payload: dict, adapter_id: str) -> dict:
        """Verify the cap chain and every caveat; apply or refuse; ALWAYS append one audit row. Frozen refusal order:
        bad_signature, unknown_root, system_mismatch, operation_mismatch, target_mismatch, payload_mismatch, correlation_missing,
        expired, uses_exhausted."""
        with self.lock:
            if self.closed:
                raise ValueError("external world closed")
            dig = payload_digest(payload)
            try:
                cav = extcap.verify(self.key, cap)
            except extcap.CapError:  # unauthenticated claims are never used for attribution: row stays unattributed
                return self._refuse("", "", operation, target, dig, "", "", adapter_id, "bad_signature")
            dep, system, chain = cav[1][1], cav[0][1], extcap.chain_id(cap)
            cors = sorted({v for n, v in cav if n == "correlation"})
            cor = cors[0] if len(cors) == 1 else (",".join(cors) if cors else "")
            ref = lambda why: self._refuse(dep, system, operation, target, dig, chain, cor, adapter_id, why)  # noqa: E731
            if self.con.execute("SELECT 1 FROM issued WHERE nonce=? AND system=? AND deployment=?",
                                (extcap.root_nonce(cap), system, dep)).fetchone() is None:
                return ref("unknown_root")
            vals = lambda name: [v for n, v in cav if n == name]  # noqa: E731
            sysd = self.systems["systems"].get(system)
            if sysd is None or any(v != system for v in vals("system")):
                return ref("system_mismatch")
            if operation not in sysd["operations"] or any(v != operation for v in vals("operation")):
                return ref("operation_mismatch")
            if any(v != target for v in vals("target")):
                return ref("target_mismatch")
            if any(v != dig for v in vals("payload_digest")):
                return ref("payload_mismatch")
            if len(cors) != 1:
                return ref("correlation_missing")
            if any(self.tick > v for v in vals("not_after_tick")):
                return ref("expired")
            used = self.con.execute("SELECT count(*) FROM effects WHERE cap_chain=?", (chain,)).fetchone()[0]
            if vals("max_uses") and used >= min(vals("max_uses")):
                return ref("uses_exhausted")
            eseq = self.con.execute("INSERT INTO effects(tick,deployment,system,operation,target,payload_json,payload_digest,"
                                    "cap_chain,correlation,adapter_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                                    (self.tick, dep, system, operation, target, canon_json(payload), dig, chain, cor,
                                     adapter_id)).lastrowid
            self._audit(dep, system, operation, target, dig, chain, cor, adapter_id, "applied", "")
            sem = SEMANTICS[sysd["operations"][operation]["semantics"]]
            for k, props in sem(lambda key: self._get(system, key), target, payload).items():
                self._put(system, k, props)
            return {"status": "applied", "reason": "", "seq": eseq}

    def _refuse(self, dep, system, op, target, dig, chain, cor, adapter, reason) -> dict:
        return {"status": "refused", "reason": reason,
                "seq": self._audit(dep, system, op, target, dig, chain, cor, adapter, "refused", reason)}
