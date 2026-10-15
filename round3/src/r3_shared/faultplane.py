"""Gate 5 fault plane (PROTOCOL-P1g P1g-3): dependency errors, crash points, fault-control command forms.
Everything here is a no-op until a host arms a crash point; H23-H28 paths never arm one."""
from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

import jsonschema

ROUND3 = Path(__file__).resolve().parents[2]
BASE_NODES = ("AUTH", "ANCHOR", "OBS")
CRASH_POINTS = ("CP1_before_commit", "CP2_after_commit", "CP3_after_anchor_append", "CP4_adapter_before_apply",
                "CP5_adapter_after_apply", "CP6_idle", "CP7_reconcile_after_read", "CP8_during_recovery")
MODES = ("drop", "reply_lost")


class DependencyUnavailable(Exception):
    """A shared client could not reach / was refused by a dependency node. str(e) == node id."""

    def __init__(self, node: str):
        super().__init__(node)
        self.node = node


class CanonicalStateLost(Exception):
    """deploy(resume=True) found the durable stores absent or unreadable (PROT-H29 s9 B4). Never start empty."""


def nodes(systems=()) -> tuple[str, ...]:
    return BASE_NODES + tuple(f"EXT:{s}" for s in systems)


_ARMED: tuple[str, str] | None = None


def _kill() -> None:  # replaced by in-process tests only
    """SIGKILL this process and NEVER return. kill() to our own pid is delivered asynchronously to whichever thread the kernel
    picks, so returning would let the calling thread run on (e.g. into COMMIT) before the signal lands. The crash points sit
    on the thread that performs the guarded operation (the CP1/CP2 hooks run inside WorldHandle.transaction on the dispatching
    thread, which alone issues COMMIT), so parking this thread for ever means no thread can complete the in-flight operation."""
    os.kill(os.getpid(), signal.SIGKILL)
    while True:  # SIGKILL cannot be caught or ignored: this loop only runs until the kernel finishes delivering it
        time.sleep(3600)


_CONTEXT_KEY = ""


def set_context_key(key: str) -> None:
    """Host-only: the request_id of the call being dispatched (CP7 key). Cleared by passing ""."""
    global _CONTEXT_KEY
    _CONTEXT_KEY = key


def context_key() -> str:
    return _CONTEXT_KEY


def arm(point: str, key: str) -> None:
    """Host-only: arm exactly one (point, key); replaces any earlier arming."""
    global _ARMED
    if point not in CRASH_POINTS:
        raise ValueError(f"unknown crash point {point!r}")
    if not isinstance(key, str):
        raise ValueError("crash key must be a string")
    _ARMED = (point, key)


def disarm() -> None:
    global _ARMED
    _ARMED = None


def armed() -> tuple[str, str] | None:
    return _ARMED


def crashpoint(point: str, key: str) -> None:
    """No-op unless (point, key) is armed; then SIGKILL this process (the arming is cleared first: fires once)."""
    global _ARMED
    if _ARMED is None or _ARMED != (point, key):
        return
    _ARMED = None
    _kill()


# ---- fault-control command forms (server control sockets; harness only) -----------------------------------------------
_SCHEMA = json.loads((ROUND3 / "schemas" / "fault-control.schema.json").read_text())


def validate_fault_command(cmd: dict) -> dict:
    """Strict form of a control-plane fault command; ValueError on any violation. Returns cmd."""
    if not isinstance(cmd, dict):
        raise ValueError("fault command: not an object")
    try:
        jsonschema.validate(cmd, _SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"fault command: {exc.message}") from exc
    for k in ("from_tick", "to_tick"):
        if isinstance(cmd[k], bool):
            raise ValueError(f"fault command: {k} is a bool")
    if cmd["to_tick"] <= cmd["from_tick"]:
        raise ValueError("fault command: empty window (to_tick <= from_tick)")
    return cmd


def in_window(windows, deployment: str, tick: int, target=None):
    """First window covering (deployment, tick) in an iterable of fault commands, else None. [from, to) semantics."""
    for w in windows:
        if w["deployment"] == deployment and w["from_tick"] <= tick < w["to_tick"] and (target is None or w.get("target") == target):
            return w
    return None
