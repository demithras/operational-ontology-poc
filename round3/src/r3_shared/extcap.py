"""External capability tokens (PROT-H28 1.5, R28-13; P1f-4). Macaroon-style, stdlib only (hmac + hashlib).

Token = "r3cap1." + base64url(canonical JSON {"n": root nonce, "s": steps, "g": signature hex}).
steps[0] is the ROOT step [["system", S], ["deployment", D]]; every attenuate() call appends exactly ONE further step.
Signature chain: g0 = HMAC(root_key, "r3cap1|" + nonce); each caveat c: g = HMAC(g, canon(c)); each step end: g = HMAC(g, b"|step").
Step boundaries are therefore signed (moving one cannot create a fresh chain_id). Only the holder of root_key can verify
(extworld, server side); anyone can read caveats and append narrower ones. Dropping or editing a caveat breaks the signature.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

PREFIX = "r3cap1."
CAVEATS = ("system", "operation", "target", "payload_digest", "correlation", "max_uses", "not_after_tick")
ROOT_CAVEATS = ("system", "deployment")
_STR = ("system", "operation", "target", "payload_digest", "correlation", "deployment")
_INT = ("max_uses", "not_after_tick")


class CapError(ValueError):
    """Malformed token, bad caveat, or failed verification."""


def _canon(x) -> bytes:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _mac(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def _check_caveat(name: str, value: Any, allowed: tuple) -> None:
    if name not in allowed:
        raise CapError(f"unknown caveat {name!r}; allowed {allowed}")
    if name in _STR and not (isinstance(value, str) and value):
        raise CapError(f"caveat {name} needs a non-empty string")
    if name in _INT:
        if not isinstance(value, int) or isinstance(value, bool) or value < (1 if name == "max_uses" else 0):
            raise CapError(f"caveat {name} needs a {'positive' if name == 'max_uses' else 'non-negative'} int")


def _chain(g: bytes, steps: list) -> bytes:
    for step in steps:
        for c in step:
            g = _mac(g, _canon(c))
        g = _mac(g, b"|step")
    return g


def _encode(nonce: str, steps: list, sig: bytes) -> str:
    raw = _canon({"n": nonce, "s": steps, "g": sig.hex()})
    return PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(cap: str) -> tuple[str, list, str]:
    if not isinstance(cap, str) or not cap.startswith(PREFIX):
        raise CapError("not an r3 capability token")
    body = cap[len(PREFIX):]
    try:
        d = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        nonce, steps, sig = d["n"], d["s"], d["g"]
        assert set(d) == {"n", "s", "g"} and isinstance(nonce, str) and isinstance(sig, str)
        assert isinstance(steps, list) and len(steps) >= 1 and all(isinstance(st, list) for st in steps)
        assert all(isinstance(c, list) and len(c) == 2 and isinstance(c[0], str) for st in steps for c in st)
        bytes.fromhex(sig)
    except (ValueError, KeyError, TypeError, IndexError, AssertionError) as exc:
        raise CapError(f"malformed token: {exc}") from exc
    return nonce, steps, sig


def mint_root(root_key: bytes, nonce: str, system: str, deployment: str) -> str:
    """Server side (extworld) only: the root cap for (system, deployment); `nonce` is recorded in issued."""
    steps = [[["system", system], ["deployment", deployment]]]
    for n, v in steps[0]:
        _check_caveat(n, v, ROOT_CAVEATS)
    g0 = _mac(root_key, b"r3cap1|" + nonce.encode())
    return _encode(nonce, steps, _chain(g0, steps))


def attenuate(cap: str, **caveats) -> str:
    """New token = old caveats + the given caveats as ONE new step; sig' = HMAC(sig, c) per caveat (order: CAVEATS order).
    Can only narrow: there is no operation that removes or loosens a caveat."""
    nonce, steps, sig = _decode(cap)
    if not caveats:
        raise CapError("attenuate needs at least one caveat")
    step = []
    for name in sorted(caveats, key=lambda n: CAVEATS.index(n) if n in CAVEATS else 99):
        _check_caveat(name, caveats[name], CAVEATS)
        step.append([name, caveats[name]])
    g = bytes.fromhex(sig)
    for c in step:
        g = _mac(g, _canon(c))
    g = _mac(g, b"|step")
    return _encode(nonce, steps + [step], g)


def caveats_of(cap: str) -> list[tuple[str, Any]]:
    """Every caveat in chain order (root step first). Readable by anyone: a bearer token is not secret-sealed."""
    return [(c[0], c[1]) for step in _decode(cap)[1] for c in step]


def chain_id(cap: str) -> str:
    """sha256 of (root nonce, FIRST attenuation step): identifies one per-effect cap and all its narrowings.
    A root cap (no attenuation step) has no chain id: ''."""
    nonce, steps, _ = _decode(cap)
    return hashlib.sha256(_canon([nonce, steps[1]])).hexdigest() if len(steps) > 1 else ""


def root_nonce(cap: str) -> str:
    return _decode(cap)[0]


def verify(root_key: bytes, cap: str) -> list[tuple[str, Any]]:
    """Server side only. Returns the caveat list when the signature chain is valid; CapError otherwise."""
    nonce, steps, sig = _decode(cap)
    if [c[0] for c in steps[0]] != list(ROOT_CAVEATS):
        raise CapError("bad root step")
    for i, step in enumerate(steps):
        for n, v in step:
            _check_caveat(n, v, ROOT_CAVEATS if i == 0 else CAVEATS)
    want = _chain(_mac(root_key, b"r3cap1|" + nonce.encode()), steps)
    if not hmac.compare_digest(want.hex(), sig):
        raise CapError("signature mismatch")
    return [(c[0], c[1]) for step in steps for c in step]


def validate_cap(cap: str) -> dict:
    """Strict FORM check of a token (schemas/external-cap.schema.json); signature is NOT checked (server side only).
    Returns {"root_nonce","system","deployment","chain_id","caveats"}; CapError on any violation (bool-as-int included)."""
    import jsonschema  # local: keeps the hot path (attenuate/verify) free of the schema machinery
    from pathlib import Path
    nonce, steps, sig = _decode(cap)
    schema = json.loads((Path(__file__).resolve().parents[2] / "schemas" / "external-cap.schema.json").read_text())
    try:
        jsonschema.validate({"n": nonce, "s": steps, "g": sig}, schema)
    except jsonschema.ValidationError as exc:
        raise CapError(f"cap form: {exc.message}") from exc
    if any(isinstance(c[1], bool) for st in steps for c in st):
        raise CapError("cap form: bool caveat value")
    return {"root_nonce": nonce, "system": steps[0][0][1], "deployment": steps[0][1][1], "chain_id": chain_id(cap),
            "caveats": [(c[0], c[1]) for st in steps for c in st]}
