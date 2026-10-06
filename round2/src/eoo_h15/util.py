"""Small shared helpers: canonical JSON/hash, IR shape masks, line counts."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # round2/
REPO = ROOT.parent
ENUM_KEYS = {"operation", "decision", "effect", "severity", "idempotency", "determinism", "purity", "truth_status"}
TYPE_KEYS = {"type", "output", "list", "optional"}
PRIMS = {"string", "integer", "number", "boolean", "datetime", "date", "json", "bytes"}
KINDS = ("object_types", "link_types", "interfaces", "functions", "actions", "policies", "authority_rules",
         "observation_types", "constraints")


def canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_json(rel: str):
    return json.loads((ROOT / rel).read_text())


def resource_counts(ir: dict) -> dict:
    return {k: len(ir.get(k, [])) for k in KINDS}


def loc(path: Path) -> int:
    """Non-blank, non-comment-only physical lines."""
    return sum(1 for ln in path.read_text().splitlines() if ln.strip() and not ln.strip().startswith("#"))


def mask_numbers(x):
    """IR with every non-boolean number replaced by '#' (numeric literal slots are the only free numbers)."""
    if isinstance(x, dict):
        return {k: mask_numbers(v) for k, v in x.items()}
    if isinstance(x, list):
        return [mask_numbers(v) for v in x]
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, (int, float)):
        return "#"
    return x


def atom_strings(x, key: str = "", meta: bool = False):
    """Yield every string at a position that is an atom (identifier / opaque text / literal) rather than a
    structural enum, primitive-type name or the unbounded marker '*'. Metadata keys are atoms."""
    if isinstance(x, dict):
        for k, v in x.items():
            if meta:
                yield k
            yield from atom_strings(v, k, meta or k == "metadata" and not meta)
    elif isinstance(x, list):
        for v in x:
            yield from atom_strings(v, key, meta)
    elif isinstance(x, str):
        if meta:
            yield x
        elif key in ENUM_KEYS or (key in TYPE_KEYS and x in PRIMS) or (key == "max" and x == "*"):
            return
        else:
            yield x


def tokens_ws(text: str) -> int:
    return len(text.split())


_TOK = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def tokens_re(text: str) -> int:
    return len(_TOK.findall(text))
