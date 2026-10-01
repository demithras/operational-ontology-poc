"""Strict JSON (de)serialisation of a record: duplicate keys are a surface ambiguity, not 'last wins'."""
from __future__ import annotations

import json

from .errors import Ambiguous, Invalid


def _pairs(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise Ambiguous("record_duplicate_key", f"record key {k!r} appears twice")
        out[k] = v
    return out


def _no_const(name):
    raise Invalid("record_syntax", f"non-JSON constant {name}")


def load_record(text: str) -> dict:
    try:
        data = json.loads(text, object_pairs_hook=_pairs, parse_constant=_no_const)
    except json.JSONDecodeError as e:
        raise Invalid("record_syntax", str(e)) from None
    if not isinstance(data, dict):
        raise Invalid("record_type", "record must be a JSON object")
    return data


def dump_record(record: dict) -> str:
    def key(k):
        a, b = k[1:].split(".a")
        return (int(a), int(b))
    return json.dumps({k: record[k] for k in sorted(record, key=key)}, ensure_ascii=False, indent=1) + "\n"
