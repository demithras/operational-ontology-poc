"""Canonical JSON (with bytes), digests and deep freezing of values handed to logic."""
from __future__ import annotations

import base64
import hashlib
import json
from types import MappingProxyType
from typing import Any

_BYTES_TAG = "$bytes"


def _enc(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray)):
        return {_BYTES_TAG: base64.b64encode(bytes(v)).decode("ascii")}
    if isinstance(v, (dict, MappingProxyType)):
        return {str(k): _enc(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_enc(x) for x in v]
    if isinstance(v, frozenset):
        return sorted((_enc(x) for x in v), key=dumps)
    return v


def _dec(v: Any) -> Any:
    if isinstance(v, dict):
        if set(v) == {_BYTES_TAG}:
            return base64.b64decode(v[_BYTES_TAG])
        return {k: _dec(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_dec(x) for x in v]
    return v


def dumps(v: Any) -> str:
    return json.dumps(_enc(v), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def loads(s: str) -> Any:
    return _dec(json.loads(s))


def to_plain(v: Any) -> Any:
    """Round-trip through canonical JSON: a detached, mutable, JSON-safe copy."""
    return loads(dumps(v))


def digest(v: Any) -> str:
    return hashlib.sha256(dumps(v).encode("utf-8")).hexdigest()


def is_json_value(v: Any) -> bool:
    try:
        dumps(v)
        return True
    except (TypeError, ValueError):
        return False


def freeze(v: Any) -> Any:
    """Immutable view of a JSON-like value: dict -> mappingproxy, list -> tuple."""
    if isinstance(v, (dict, MappingProxyType)):
        return MappingProxyType({k: freeze(x) for k, x in v.items()})
    if isinstance(v, (list, tuple)):
        return tuple(freeze(x) for x in v)
    if isinstance(v, bytearray):
        return bytes(v)
    return v


def thaw(v: Any) -> Any:
    """Mutable deep copy of a (possibly frozen) value."""
    if isinstance(v, (dict, MappingProxyType)):
        return {k: thaw(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [thaw(x) for x in v]
    return v
