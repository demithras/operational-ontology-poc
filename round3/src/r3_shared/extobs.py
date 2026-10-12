"""ObservationClient: the ONLY outcome evidence a variant may use (PROT-H28 1.6, R28-9; P1f-5). Read-only SQLite connection
(mode=ro) to the ExternalWorld ledger with its own observation key; never an action cap, socket or adapter reply.
Constructed by the harness and handed to the variant inside ExternalBinding; a variant never builds one."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import faultplane

import jsonschema

DB_NAME = "external.db"
_SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "schemas" / "external-ledger.schema.json").read_text())
EFF_COLS = ("seq", "tick", "system", "operation", "target", "payload_digest", "cap_chain", "correlation", "adapter_id")
AUD_COLS = EFF_COLS + ("outcome", "reason")


class ObserverUnavailable(Exception):
    """The injected fault (or a failed connection) makes this read unavailable (PROT-H28 R28-10)."""


class ObserverAuthError(Exception):
    """Unknown or foreign observation key."""


@dataclass(frozen=True)
class ObserverFault:
    """Harness-only. kind 'unavailable': reads whose 0-based index is in `reads` (all reads if empty) raise ObserverUnavailable.
    kind 'lagging': complete_through_tick := watermark - k and rows above it are withheld."""
    kind: str
    k: int = 0
    reads: frozenset = frozenset()

    def __post_init__(self):
        if self.kind not in ("unavailable", "lagging"):
            raise ValueError(f"unknown observer fault {self.kind!r}")
        if self.kind == "lagging" and (not isinstance(self.k, int) or isinstance(self.k, bool) or self.k < 0):
            raise ValueError("lagging needs k >= 0")

    @classmethod
    def unavailable(cls, reads=()):
        return cls("unavailable", 0, frozenset(reads))

    @classmethod
    def lagging(cls, k: int):
        return cls("lagging", k)


@dataclass(frozen=True)
class EffRow:
    seq: int; tick: int; system: str; operation: str; target: str
    payload_digest: str; cap_chain: str; correlation: str; adapter_id: str

    def as_dict(self) -> dict:
        return {c: getattr(self, c) for c in EFF_COLS}


@dataclass(frozen=True)
class AudRow:
    seq: int; tick: int; system: str; operation: str; target: str
    payload_digest: str; cap_chain: str; correlation: str; adapter_id: str
    outcome: str; reason: str

    def as_dict(self) -> dict:
        return {c: getattr(self, c) for c in AUD_COLS}


@dataclass(frozen=True)
class ObsSnapshot:
    watermark: int
    effects: list
    audit: list
    complete_through_tick: int

    def as_dict(self) -> dict:
        return {"watermark": self.watermark, "complete_through_tick": self.complete_through_tick,
                "effects": [r.as_dict() for r in self.effects], "audit": [r.as_dict() for r in self.audit]}


def validate_snapshot(d: dict) -> dict:
    """Strict observation-record form (schemas/external-ledger.schema.json)."""
    try:
        jsonschema.validate(d, {"$ref": "#/$defs/snapshot", "$defs": _SCHEMA["$defs"]})
    except jsonschema.ValidationError as exc:
        raise ValueError(f"snapshot: {exc.message}") from exc
    if any(isinstance(d[k], bool) for k in ("watermark", "complete_through_tick")):
        raise ValueError("snapshot: bool is not an int")
    return d


def validate_effect_row(d: dict) -> dict:
    try:
        jsonschema.validate(d, {"$ref": "#/$defs/effect_row", "$defs": _SCHEMA["$defs"]})
    except jsonschema.ValidationError as exc:
        raise ValueError(f"effect_row: {exc.message}") from exc
    return d


def validate_audit_row(d: dict) -> dict:
    try:
        jsonschema.validate(d, {"$ref": "#/$defs/audit_row", "$defs": _SCHEMA["$defs"]})
    except jsonschema.ValidationError as exc:
        raise ValueError(f"audit_row: {exc.message}") from exc
    return d


def key_hash(observer_key: str) -> str:
    return hashlib.sha256(observer_key.encode()).hexdigest()


class ObservationClient:
    def __init__(self, ext_dir: str, observer_key: str, systems: dict, fault: ObserverFault | None = None):
        self._path, self._key, self._systems, self.fault = str(Path(ext_dir) / DB_NAME), observer_key, systems, fault
        self.transcript: list[dict] = []   # harness record: one entry per read (watermark, complete_through_tick, row seqs)
        self._reads = 0

    def _connect(self) -> sqlite3.Connection:
        try:
            con = sqlite3.connect(f"file:{self._path}?mode=ro", uri=True, timeout=15, isolation_level=None)
            con.execute("PRAGMA query_only=ON")
            return con
        except sqlite3.Error as exc:
            raise ObserverUnavailable(f"ledger not readable: {exc}") from exc

    def read(self, watermark: int) -> ObsSnapshot:
        if not isinstance(watermark, int) or isinstance(watermark, bool) or watermark < 0:
            raise ValueError("watermark must be a non-negative int")
        idx, self._reads = self._reads, self._reads + 1
        f = self.fault
        if f is not None and f.kind == "unavailable" and (not f.reads or idx in f.reads):
            raise ObserverUnavailable("injected: observer unavailable")
        lag = f.k if f is not None and f.kind == "lagging" else 0
        con = self._connect()
        try:
            srv = int(con.execute("SELECT v FROM meta WHERE k='tick'").fetchone()[0])
            ct = max(-1, min(watermark - lag, srv))   # G4-E8/E24: a watermark ahead of the server never overstates completeness
            dep = con.execute("SELECT deployment FROM obs_keys WHERE key_hash=?", (key_hash(self._key),)).fetchone()
            if dep is None:
                raise ObserverAuthError("observation key not accepted")
            vis = [s for s, d in self._systems["systems"].items() if d["observability"] != "none"]
            full = [s for s in vis if self._systems["systems"][s]["observability"] == "full"]
            q = lambda t, cols, names: (  # noqa: E731
                f"SELECT {','.join(cols)} FROM {t} WHERE deployment=? AND tick<=? AND system IN ({','.join('?' * len(names))}) ORDER BY seq")
            con.execute("BEGIN")
            eff = [EffRow(*r) for r in con.execute(q("effects", EFF_COLS, vis), (dep[0], ct, *vis))] if vis else []
            aud = [AudRow(*r) for r in con.execute(q("audit", AUD_COLS, full), (dep[0], ct, *full))] if full else []
            con.execute("COMMIT")
        except sqlite3.Error as exc:
            raise ObserverUnavailable(f"ledger read failed: {exc}") from exc
        finally:
            con.close()
        snap = ObsSnapshot(watermark, eff, aud, ct)
        self.transcript.append({"watermark": watermark, "complete_through_tick": ct,
                                "effects": [r.seq for r in eff], "audit": [r.seq for r in aud]})
        faultplane.crashpoint("CP7_reconcile_after_read", faultplane.context_key())  # G5: no-op unless armed
        return snap
