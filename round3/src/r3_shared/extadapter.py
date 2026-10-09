"""Action adapter protocol and request/reply forms (PROT-H28 1.2, P1f-7). Variants import this module; they never import
the ExternalWorld service. AdapterReply is UNTRUSTED: a variant may use it only to decide whether to resubmit (R28-8)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import jsonschema

from . import extcap

_SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "schemas" / "external-request.schema.json").read_text())
ADAPTER_IDS = ("H0", "L1", "L2", "L3", "T1", "T2", "T3", "R1", "R2", "O1", "O2", "G1", "G2", "G3")
REPLY_OK, REPLY_FAILED, REPLY_TIMEOUT = "OK", "FAILED", "TIMEOUT"


class FormError(ValueError):
    """A P1f form failed strict validation."""


def canon_json(x: Any) -> str:
    """Canonical JSON text: sorted keys, compact separators, non-ASCII kept (the form of r3_shared.anchor.canon)."""
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_digest(payload: dict) -> str:
    """sha256 hex of canon_json(payload) (L5: byte-exact, no semantic equivalence)."""
    return hashlib.sha256(canon_json(payload).encode()).hexdigest()


def correlation(request_id: str, effect_index: int) -> str:
    return f"{request_id}#{effect_index}"


def parse_correlation(c: str) -> tuple[str, int]:
    rid, sep, idx = c.rpartition("#")
    if not sep or not rid or not idx.isdigit():
        raise FormError(f"bad correlation {c!r}")
    return rid, int(idx)


@dataclass(frozen=True)
class ExternalRequest:
    request_id: str
    effect_index: int
    system: str
    operation: str
    target: str
    payload: dict
    envelope_text: str
    cap: str

    def __post_init__(self):
        validate_request(self.as_dict(), strict_cap=False)

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("request_id", "effect_index", "system", "operation", "target", "payload",
                                              "envelope_text", "cap")}


@dataclass(frozen=True)
class AdapterReply:
    status: str
    body: dict = field(default_factory=dict)


@runtime_checkable
class ActionAdapter(Protocol):
    adapter_id: str

    def submit(self, req: ExternalRequest) -> AdapterReply:
        """May raise; a variant treats any exception as TIMEOUT."""


def _validate(obj: Any, name: str) -> None:
    try:
        jsonschema.validate(obj, {"$ref": f"#/$defs/{name}", "$defs": _SCHEMA["$defs"]})
    except jsonschema.ValidationError as exc:
        raise FormError(f"{name}: {exc.message}") from exc
    for k, v in obj.items():
        if isinstance(v, bool) and k in ("effect_index", "seq"):
            raise FormError(f"{name}.{k}: bool is not an int")


def validate_request(d: dict, strict_cap: bool = True) -> dict:
    """Strict ExternalRequest form. strict_cap (used by the recorder and conformance C28-3, NOT by the constructor, so a
    defective variant can still be observed handing out a bad cap): the cap must parse, be a per-effect cap (has a chain
    id; never a root cap, R28-13) and carry correlation == request_id#effect_index."""
    if not isinstance(d, dict):
        raise FormError("request: not an object")
    _validate(d, "request")
    if not strict_cap:
        return d
    try:
        cav = extcap.caveats_of(d["cap"])
        cid = extcap.chain_id(d["cap"])
    except extcap.CapError as exc:
        raise FormError(f"request.cap: {exc}") from exc
    if not cid:
        raise FormError("request.cap: a root cap must never reach an adapter (R28-13)")
    cors = {v for n, v in cav if n == "correlation"}
    if cors != {correlation(d["request_id"], d["effect_index"])}:
        raise FormError("request.cap: correlation caveat does not equal request_id#effect_index")
    return d


def validate_reply(d: dict) -> dict:
    if not isinstance(d, dict):
        raise FormError("reply: not an object")
    _validate(d, "reply")
    return d


def validate_receipt(d: dict) -> dict:
    if not isinstance(d, dict):
        raise FormError("receipt: not an object")
    _validate(d, "write_receipt")
    return d
