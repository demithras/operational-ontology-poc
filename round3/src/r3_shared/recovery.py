"""Gate 5 forms ONLY (PROTOCOL-P1g P1g-5, P1g-8): reply vocabulary for dependency loss, RECOVERY_VIEW form + validator,
canonical JSON re-export. No behaviour: oracle and variants implement the semantics separately."""
from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema

from .extadapter import canon_json  # noqa: F401  (G4-E1 canonical JSON, re-exported for byte-equality of views)
from .outcome import CONFIDENCES, STATES

_SCH = Path(__file__).resolve().parents[2] / "schemas"
_VIEW_SCHEMA = json.loads((_SCH / "recovery-view.schema.json").read_text())
_REPLY_SCHEMA = json.loads((_SCH / "dependency-reply.schema.json").read_text())

DEP_UNAVAILABLE = "dependency_unavailable"
IN_DOUBT = "in_doubt"
CRASHED = "crashed"
STATE_LOST = "state_lost"
INPUT_INVALID_REASONS = ("schema_invalid", "unknown_operation", "unknown_tool", "bad_args")
DEPENDENCY_REASONS = (DEP_UNAVAILABLE, IN_DOUBT, CRASHED, STATE_LOST)
RECOVERY_VIEW_KEYS = ("form", "committed", "intents", "authority", "approvals_open")
FORM = "r3-recovery-1"
_HEX = re.compile(r"^[0-9a-f]{64}$")


class RecoveryFormError(ValueError):
    """A RECOVERY_VIEW or H29 reply violated the frozen form."""


def validate_reply(status: str, body: dict) -> None:
    """Exact keys for the H29 reply forms: UNAVAILABLE {reason: dependency_unavailable, dependency: node}, UNKNOWN
    {reason: in_doubt}, UNAVAILABLE {reason: state_lost}. DENIED must name no dependency and use no dependency reason.
    The legacy CRASHED reason is validated by its own (existing) callers. Raises ValueError."""
    if not isinstance(body, dict):
        raise RecoveryFormError("reply body: not an object")
    if status == "DENIED":
        if "dependency" in body or body.get("reason") in DEPENDENCY_REASONS:
            raise RecoveryFormError("DENIED must not name a dependency nor use a dependency reason")
        return
    if status not in ("UNAVAILABLE", "UNKNOWN"):
        raise RecoveryFormError(f"no H29 reply form for status {status!r}")
    if body.get("reason") == CRASHED:
        if set(body) != {"reason"}:
            raise RecoveryFormError("crashed reply carries exactly {reason}")
        return
    try:
        jsonschema.validate({"status": status, "body": body}, _REPLY_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise RecoveryFormError(f"reply: {exc.message}") from exc


def validate_recovery_view(v: dict) -> dict:
    """Exact keys, vocabulary and ordering of RECOVERY_VIEW (P1g-8). Returns v."""
    if not isinstance(v, dict):
        raise RecoveryFormError("recovery view: not an object")
    if tuple(sorted(v)) != tuple(sorted(RECOVERY_VIEW_KEYS)):
        raise RecoveryFormError(f"recovery view keys {sorted(v)} != {sorted(RECOVERY_VIEW_KEYS)}")
    try:
        jsonschema.validate(v, _VIEW_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise RecoveryFormError(f"recovery view: {exc.message}") from exc
    for c in v["committed"]:
        if isinstance(c["world_seq"], bool):
            raise RecoveryFormError("world_seq is a bool")
    seqs = [c["world_seq"] for c in v["committed"]]
    if seqs != sorted(seqs) or len(set(seqs)) != len(seqs):
        raise RecoveryFormError("committed must be strictly sorted by world_seq")
    rids = [c["request_id"] for c in v["committed"] if c["request_id"] is not None]
    if len(set(rids)) != len(rids):
        raise RecoveryFormError("committed: duplicate request_id")
    keys = [(i["request_id"], i["effect_index"]) for i in v["intents"]]
    if any(isinstance(i["effect_index"], bool) or isinstance(i["chain_ids"], bool) for i in v["intents"]):
        raise RecoveryFormError("bool where int expected")
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        raise RecoveryFormError("intents must be strictly sorted by (request_id, effect_index)")
    for i in v["intents"]:
        if i["state"] not in STATES or i["confidence"] not in CONFIDENCES:
            raise RecoveryFormError("intent state/confidence outside the P1f vocabulary")
    a = v["approvals_open"]
    if a != sorted(a) or len(set(a)) != len(a):
        raise RecoveryFormError("approvals_open must be strictly sorted")
    if any(isinstance(x, bool) for x in (v["authority"]["lease_until"],)):
        raise RecoveryFormError("lease_until is a bool")
    return v


def view_bytes(v: dict) -> bytes:
    """Canonical bytes of a validated view: the unit of A/B and oracle equality (R29-9, R29-11)."""
    return canon_json(validate_recovery_view(v)).encode()
