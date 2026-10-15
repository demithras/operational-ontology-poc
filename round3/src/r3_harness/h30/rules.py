"""H30 task DSL vocabulary (TASK-CORPUS-SPEC s2): the ONE rule table of the step kinds a task may contain (src/r3_harness/h30/rules.py, as the
spec names it). Used by the corpus validator (scripts/validate_h30_corpus.py, validate.py) and, later, by the H30 harness machine, which
imports this table instead of redefining it (a test there asserts DSL kinds == machine rules, set difference 0).
Every kind is a union member of the frozen H23-H29 step kinds; the DSL has NO free code and NO new primitive.

A step = {"op": <kind>, "t": <tick>, ...FIELDS[kind]..., optional OPTIONAL[kind] + COMMON_OPTIONAL}.
`t` is the absolute logical tick for attacker.steps and workload.legit; for attacker.continuation it is an OFFSET into the replay window
(the containment probe, PROBE = 4 ticks, then the TAIL), 0 <= t < PROBE for the probe part."""
from __future__ import annotations

import json
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[3]

RULES = ("request", "approve", "delegate", "revoke",
         "read", "list", "query", "subscribe", "poll", "prov",
         "redeliver", "publish_authority", "tamper", "adapter",
         "fault_start", "fault_heal", "crash", "resume",
         "advance", "dispatch", "reconcile")
FIELDS = {
    "request": ("principal", "operation", "args", "rid", "surface"),
    "approve": ("approver", "requester", "operation", "args"),
    "delegate": ("principal", "edge", "rid"),
    "revoke": ("principal", "edge_id", "rid"),
    "read": ("principal", "ref"),
    "list": ("principal", "type"),
    "query": ("principal", "name", "args"),
    "subscribe": ("principal", "sub", "type"),
    "poll": ("principal", "sub"),
    "prov": ("principal", "kind", "ref"),
    "redeliver": ("rid", "copies", "concurrent"),
    "publish_authority": ("drop_grants",),
    "tamper": ("what",),
    "adapter": ("system", "prims", "target"),
    "fault_start": ("fid", "fault"),
    "fault_heal": ("fid",),
    "crash": ("point",),
    "resume": (),
    "advance": ("n",),
    "dispatch": (),
    "reconcile": ("rid", "watermark"),
}
OPTIONAL = {"request": ("obo", "tag"), "approve": ("obo",), "tamper": ("target",), "reconcile": ("lag",)}
COMMON_OPTIONAL = ("group",)                      # attacker step group (V5: >= 1 kept adaptation element per group)
SURFACES = ("call_tool", "direct")
PROV_KINDS = ("decision", "object")
TAMPER_KINDS = ("forge_approval", "delete_idempotency", "rewrite_meta")   # H27 TamperView ops used by H29
CRASH_POINTS = ("CP1_before_commit", "CP2_after_commit", "CP3_after_anchor_append", "CP4_adapter_before_apply",
                "CP5_adapter_after_apply", "CP6_idle", "CP7_reconcile_after_read", "CP8_during_recovery")   # spec/gate5/envelope-ops.json
ADAPTER_PRIMS = ("H0", "L1", "L2", "L3", "T1", "T2", "T3", "R1", "R2", "O1", "O2", "G1", "G2", "G3")          # H28 catalogue (FREEZE_G4)
# which steps an attacker may use (vs the environment/legitimate side): the attacker never publishes authority, injects faults or crashes
ATTACKER_OPS = ("request", "approve", "delegate", "revoke", "read", "list", "query", "subscribe", "poll", "prov", "redeliver",
                "tamper", "adapter")
LEGIT_OPS = ("request", "approve", "delegate", "revoke", "read", "list", "query", "subscribe", "poll", "prov", "redeliver",
             "publish_authority", "fault_start", "fault_heal", "crash", "resume", "advance", "dispatch", "reconcile")
# attacker capabilities = frozen primitives of earlier gates (PROT-H30 s3)
CAPABILITIES = ("h23.direct", "h23.call_tool", "h24.delegate", "h24.revoke", "h26.read", "h26.list", "h26.query", "h26.subscribe",
                "h26.poll", "h26.prov", "h27.tamper", "h28.adapter", "a8.redeliver", "h23.approve")
K_KINDS = ("principal", "adapter", "evidence_store", "authority_version")
EVIDENCE_STORES = ("world_store", "history_store")
SOURCE_KINDS = ("cve", "advisory", "incident_report", "owasp_case", "case_study")
CORPORA = ("primary", "reserve", "dev")
PROBE_TICKS = 4
SANITY = {"copies_max": 3, "crashes_max": 3, "tamper_max": 1, "fault_window_max": 12, "prims_max": 3, "ext_systems_max": 1}   # envelope-ops.json


def capability_of(step: dict) -> str:
    op = step["op"]
    if op == "request":
        return "h23.direct" if step["surface"] == "direct" else "h23.call_tool"
    return {"approve": "h23.approve", "delegate": "h24.delegate", "revoke": "h24.revoke", "read": "h26.read", "list": "h26.list",
            "query": "h26.query", "subscribe": "h26.subscribe", "poll": "h26.poll", "prov": "h26.prov", "redeliver": "a8.redeliver",
            "tamper": "h27.tamper", "adapter": "h28.adapter"}[op]


def validate_step(st) -> None:
    """ValueError on a step outside the frozen vocabulary, with a missing or unexpected key, or with a mistyped field."""
    if not isinstance(st, dict):
        raise ValueError("step is not an object")
    op = st.get("op")
    if op not in RULES:
        raise ValueError(f"unknown step kind {op!r}")
    allowed = set(FIELDS[op]) | set(OPTIONAL.get(op, ())) | set(COMMON_OPTIONAL) | {"op", "t"}
    extra = set(st) - allowed
    if extra:
        raise ValueError(f"{op}: unexpected keys {sorted(extra)}")
    missing = (set(FIELDS[op]) | {"t"}) - set(st)
    if missing:
        raise ValueError(f"{op}: missing keys {sorted(missing)}")
    i = lambda x: isinstance(x, int) and not isinstance(x, bool)   # noqa: E731
    s = lambda x: isinstance(x, str) and x != ""                   # noqa: E731
    if not (i(st["t"]) and st["t"] >= 0):
        raise ValueError(f"{op}: t must be a non-negative int")
    chk = {
        "principal": s, "approver": s, "requester": s, "operation": s, "rid": s, "ref": s, "type": s, "name": s, "sub": s, "system": s,
        "target": s, "edge_id": s, "fid": s, "obo": lambda x: x is None or s(x), "tag": s, "group": s,
        "args": lambda x: isinstance(x, dict), "edge": lambda x: isinstance(x, dict), "fault": lambda x: isinstance(x, dict),
        "surface": lambda x: x in SURFACES, "kind": lambda x: x in PROV_KINDS, "what": lambda x: x in TAMPER_KINDS,
        "point": lambda x: x in CRASH_POINTS, "copies": lambda x: i(x) and 1 <= x <= SANITY["copies_max"], "concurrent": lambda x: isinstance(x, bool),
        "drop_grants": lambda x: isinstance(x, list) and bool(x) and all(s(g) for g in x),
        "prims": lambda x: isinstance(x, list) and 1 <= len(x) <= SANITY["prims_max"] and all(p in ADAPTER_PRIMS for p in x),
        "n": lambda x: i(x) and x >= 1, "watermark": lambda x: i(x) and x >= 0, "lag": lambda x: i(x) and 0 <= x <= 3,
    }
    for k, v in st.items():
        if k not in ("op", "t") and not chk[k](v):
            raise ValueError(f"{op}.{k}: bad value {v!r}")


def _fault_schema() -> dict:
    f = json.loads((ROUND3 / "schemas" / "fault-control.schema.json").read_text())
    return {k: v for k, v in f.items() if k not in ("$schema", "$id", "title")}


def build_schema() -> dict:
    """spec/gate6/task.schema.json (frozen): the task envelope + one step definition per kind generated from FIELDS/OPTIONAL."""
    cls = [c["id"] for c in json.loads((ROUND3 / "threat_model" / "attack_classes.json").read_text())["classes"]]
    sha64 = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    date = {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"}
    nes = {"type": "string", "minLength": 1}
    step_defs = {}
    for k in RULES:
        props = {"op": {"const": k}, "t": {"type": "integer", "minimum": 0}}
        for f in (*FIELDS[k], *OPTIONAL.get(k, ()), *COMMON_OPTIONAL):
            props[f] = {"type": ["string", "null"]} if f == "obo" else {"type": "string", "minLength": 1}
        for f, t in (("args", "object"), ("edge", "object"), ("fault", "object"), ("copies", "integer"), ("concurrent", "boolean"),
                     ("n", "integer"), ("watermark", "integer"), ("lag", "integer")):
            if f in props:
                props[f] = {"type": t}
        if "drop_grants" in props:
            props["drop_grants"] = {"type": "array", "minItems": 1, "items": nes}
        if "prims" in props:
            props["prims"] = {"type": "array", "minItems": 1, "maxItems": SANITY["prims_max"], "items": {"enum": list(ADAPTER_PRIMS)}}
        if "surface" in props:
            props["surface"] = {"enum": list(SURFACES)}
        if "kind" in props:
            props["kind"] = {"enum": list(PROV_KINDS)}
        if "what" in props:
            props["what"] = {"enum": list(TAMPER_KINDS)}
        if "point" in props:
            props["point"] = {"enum": list(CRASH_POINTS)}
        step_defs[k] = {"type": "object", "additionalProperties": False, "required": ["op", "t", *FIELDS[k]], "properties": props}
    step = {"oneOf": [{"$ref": f"#/$defs/step_{k}"} for k in RULES]}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "r3-h30-task-1",
        "title": "H30 blind task (TASK-CORPUS-SPEC s2): one JSON object per task; canonical JSON, sorted keys",
        "type": "object", "additionalProperties": False,
        "required": ["task_id", "corpus", "primary_class", "secondary", "domain", "overlay", "source", "adaptation", "incident_report",
                     "attacker", "workload", "faults", "expected_forbidden", "slack", "horizon"],
        "properties": {
            "task_id": {"type": "string", "pattern": "^h30-A(10|[1-9])-[a-z]?\\d{2}$"},
            "corpus": {"enum": list(CORPORA)},
            "primary_class": {"enum": cls},
            "secondary": {"type": "array", "items": {"enum": cls}, "uniqueItems": True},
            "domain": {"enum": ["manufacturing", "project"]},
            "overlay": sha64,
            "source": {"type": "object", "additionalProperties": False, "required": ["kind", "id", "url", "title", "published", "retrieved",
                                                                                   "excerpt_sha256", "excerpt"],
                       "properties": {"kind": {"enum": list(SOURCE_KINDS)}, "id": {"type": ["string", "null"]},
                                      "url": {"type": ["string", "null"]}, "title": nes, "published": date, "retrieved": date,
                                      "excerpt_sha256": sha64, "excerpt": {"type": "string", "minLength": 1, "maxLength": 600}}},
            "adaptation": {"type": "object", "additionalProperties": False, "required": ["kept", "changed", "dropped"],
                           "properties": {k: {"type": "array", "items": nes} for k in ("kept", "changed", "dropped")}},
            "incident_report": {"type": "object", "additionalProperties": False, "required": ["K", "t_c", "t_d", "indicators"],
                                "properties": {"K": {"type": "object", "additionalProperties": False, "required": ["kind", "id"],
                                                     "properties": {"kind": {"enum": list(K_KINDS)}, "id": nes}},
                                               "t_c": {"type": "integer", "minimum": 1}, "t_d": {"type": "integer", "minimum": 2},
                                               "indicators": {"type": "array", "items": nes}}},
            "attacker": {"type": "object", "additionalProperties": False, "required": ["capabilities", "steps", "continuation"],
                         "properties": {"capabilities": {"type": "array", "items": {"enum": list(CAPABILITIES)}, "uniqueItems": True},
                                        "steps": {"type": "array", "minItems": 1, "items": step},
                                        "continuation": {"type": "array", "minItems": 1, "items": step}}},
            "workload": {"type": "object", "additionalProperties": False, "required": ["legit", "mix_seed_slot"],
                         "properties": {"legit": {"type": "array", "minItems": 1, "items": step}, "mix_seed_slot": {"const": "r"}}},
            "faults": {"type": "array", "items": _fault_schema()},
            "expected_forbidden": {"type": "array", "items": nes},
            "slack": {"type": "object", "additionalProperties": False, "required": ["tick_jitter"],
                      "properties": {"tick_jitter": {"type": "integer", "minimum": 0}}},
            "horizon": {"type": "object", "additionalProperties": False, "required": ["t_end"],
                        "properties": {"t_end": {"type": "integer", "minimum": 3}}},
        },
        "$defs": {f"step_{k}": v for k, v in step_defs.items()},
    }
