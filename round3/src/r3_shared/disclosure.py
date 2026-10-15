"""Shared Gate 3 FORMS (PROTOCOL-P1e P1e-5, PROT-H26 s3-s4): tool_schema derivation, low-channel response/event/
provenance-view forms and their checkers. Forms only - NO visibility logic (ruling Q4): each variant implements its
own, the oracle (r3_oracle/disclosure.py) its own. Checkers raise ValueError describing the first violation."""
from __future__ import annotations

import re
from typing import Any

MARKER_KINDS = ("actor", "digest", "edge", "args")
EVENT_KINDS = ("create", "update", "delete", "link", "unlink")
DECISION_KEYS = ("decision_id", "kind", "subject", "on_behalf_of", "operation", "args_digest", "status", "reason",
                 "effect_digest", "world_seq", "tick", "authority_path")
_JSON_TYPE = {"resource": "string", "integer": "integer", "string": "string"}  # `json` inputs: no type keyword (any JSON)
_REF = re.compile(r"^[^:|]+:.+$")


def tool_schema(op_def: dict) -> dict:
    """P1e-5 frozen derivation. Deterministic: tools() descriptors MUST use it verbatim (no description/enum/example)."""
    props: dict[str, dict] = {}
    for i in op_def["inputs"]:
        p: dict[str, Any] = {} if i["type"] == "json" else {"type": _JSON_TYPE[i["type"]]}
        if i["type"] == "resource":
            p["resource_type"] = i["resource_type"]
        props[i["name"]] = p
    return {"type": "object", "additionalProperties": False,
            "required": sorted(i["name"] for i in op_def["inputs"] if i.get("required")), "properties": props}


def marker(kind: str) -> dict:
    if kind not in MARKER_KINDS:
        raise ValueError(f"bad marker kind {kind!r}")
    return {"redacted": kind}


def is_marker(x: Any) -> bool:
    return isinstance(x, dict) and set(x) == {"redacted"} and x["redacted"] in MARKER_KINDS


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(msg)


def _body(b: Any, keys: set[str], what: str) -> dict:
    _need(isinstance(b, dict), f"{what}: body must be an object")
    _need(set(b) == keys, f"{what}: body keys {sorted(b)} != {sorted(keys)}")
    return b


def _refs(x: Any, what: str) -> None:
    _need(isinstance(x, list) and all(isinstance(r, str) and _REF.match(r) for r in x) and x == sorted(x),
          f"{what}: must be a sorted list of refs")


def check_event(e: Any) -> None:
    _need(isinstance(e, dict), "event must be an object")
    _need(e.get("kind") in EVENT_KINDS, "event kind")
    link = e["kind"] in ("link", "unlink")
    _need(set(e) == {"seq", "tick", "kind", "link" if link else "ref", "props"}, f"event keys {sorted(e)}")
    _need(all(isinstance(e[k], int) and not isinstance(e[k], bool) for k in ("seq", "tick")), "event seq/tick ints")
    if link:
        _need(isinstance(e["link"], list) and len(e["link"]) == 3 and all(isinstance(s, str) for s in e["link"]), "event link")
    else:
        _need(isinstance(e["ref"], str) and _REF.match(e["ref"]) is not None, "event ref")
    _need(isinstance(e["props"], dict), "event props")


def check_decision(d: Any) -> None:
    _need(isinstance(d, dict) and set(d) == set(DECISION_KEYS), "decision must carry exactly the PROT-H27 s1 scalars")
    for k, v in d.items():
        # structure only: WHICH fields may be redacted is decided by the oracle's expected view, not by this form
        _need(is_marker(v) or not (isinstance(v, dict) and "redacted" in v), f"decision.{k}: malformed marker")


def check_low_result(method: str, result) -> None:
    """Validate a CallResult of a low-channel method against its frozen form (OK body or the frozen refusal)."""
    st, b = result.status, result.body
    if st != "OK":
        _need(isinstance(b.get("reason"), str), f"{method}: refusal needs a reason")
        if method == "read_object":
            _need((st, b) == ("INVALID", {"reason": "not_found"}), "read_object: only INVALID not_found")
        elif method == "list_objects":
            _need((st, b) == ("INVALID", {"reason": "unknown_type"}), "list_objects: only INVALID unknown_type")
        elif method in ("prov_decision", "authority_used_as"):
            _need((st, b) == ("INVALID", {"reason": "unknown_decision"}), f"{method}: only INVALID unknown_decision")
        return
    if method == "read_object":
        _body(b, {"ref", "props"}, method)
        _need(isinstance(b["ref"], str) and isinstance(b["props"], dict), "read_object ref/props")
    elif method == "list_objects":
        _refs(_body(b, {"refs"}, method)["refs"], "refs")
    elif method == "list_links":
        _body(b, {"out", "in"}, method)
        _refs(b["out"], "out")
        _refs(b["in"], "in")
    elif method == "query":
        _body(b, {"value"}, method)
    elif method == "subscribe":
        _need(isinstance(_body(b, {"sub"}, method)["sub"], str), "sub id")
    elif method == "poll":
        evs = _body(b, {"events"}, method)["events"]
        _need(isinstance(evs, list), "events list")
        for e in evs:
            check_event(e)
        _need([e["seq"] for e in evs] == sorted(e["seq"] for e in evs), "events not in commit order")
    elif method == "prov_decision":
        _body(b, {"partial", "decision"}, method)
        _need(b["partial"] is True, "partial must be constant true")
        check_decision(b["decision"])
    elif method == "prov_object":
        _body(b, {"partial", "decisions"}, method)
        _need(b["partial"] is True and isinstance(b["decisions"], list)
              and all(isinstance(x, str) for x in b["decisions"]), "prov_object form")
    elif method == "authority_used_as":
        _body(b, {"partial", "on_behalf_of", "path", "authority_version", "world_seq", "tick"}, method)
        _need(b["partial"] is True, "partial must be constant true")
        _need(isinstance(b["path"], list) and all(is_marker(x) and x["redacted"] == "edge" or isinstance(x, str)
                                                  for x in b["path"]), "path entries: edge id or edge marker")
        _need(b["authority_version"] == {"redacted": "digest"}, "authority_version is always redacted")
        _need(all(isinstance(b[k], int) for k in ("world_seq", "tick")), "world_seq/tick")
        _need(b["on_behalf_of"] is None or isinstance(b["on_behalf_of"], str) or is_marker(b["on_behalf_of"]),
              "on_behalf_of")
    else:
        raise ValueError(f"not a low-channel method: {method}")


LOW_METHODS = ("read_object", "list_objects", "list_links", "query", "subscribe", "poll", "prov_decision",
               "prov_object", "authority_used_as")
