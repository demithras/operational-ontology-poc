"""Tiny helpers shared by both domain packs (no Engine imports; logic only sees the read-only view)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from eoo_engine.canon import to_plain


def parse_dt(value: Any) -> datetime | None:
    """ISO-8601 string -> aware UTC datetime; None for anything unparsable (callers fail closed)."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def canonical_json(obj: Any) -> str:
    """Same canonical form as services.decision_service.hashing.canonical_json (sorted keys, no spaces)."""
    return json.dumps(to_plain(obj), sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def keyed(records) -> dict:
    """{key: props} for a tuple of read-view records."""
    return {r["key"]: r["props"] for r in records}
