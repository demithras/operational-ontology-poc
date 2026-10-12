"""FROZEN rule table (ORACLE-AND-HARNESS-G5 s2/s3): the step kinds of a sequence ARE the rules of the Hypothesis state machine
(machine.py). The generator, the machine and the driver all take their vocabulary from here, so they cannot drift (a test asserts the
set equality). Changing this file changes the FREEZE_G5 hash (invalid_if c)."""
from __future__ import annotations

RULES = ("request", "approve", "delegate", "revoke", "read", "redeliver", "publish_authority", "fault_start", "fault_heal",
         "crash", "resume", "recovery_schedule", "tamper", "advance", "dispatch", "reconcile")

# exact keys of each step kind (besides "op"); optional keys are listed in OPTIONAL
FIELDS = {
    "request": ("i", "principal", "obo", "operation", "args", "rid", "surface"),
    "approve": ("approver", "requester", "obo", "operation", "args"),
    "delegate": ("principal", "edge", "rid"),
    "revoke": ("principal", "edge_id", "rid"),
    "read": ("i", "principal", "operation", "args"),
    "redeliver": ("rid", "copies", "concurrent"),
    "publish_authority": ("version",),
    "fault_start": ("fid", "cls", "node", "mode", "duration"),
    "fault_heal": ("fid",),
    "crash": ("point", "key"),
    "resume": (),
    "recovery_schedule": (),
    "tamper": ("what",),
    "advance": ("n",),
    "dispatch": (),
    "reconcile": ("rid", "watermark"),
}
OPTIONAL = {"request": ("tag", "invalid_probe", "attacker"), "read": ("tag",), "fault_start": ("k",), "reconcile": ("lag",),
            "approve": (), "redeliver": ()}
SURFACES = ("call_tool", "direct")
FAULT_MODES = ("drop", "reply_lost")
TAMPER_KINDS = ("forge_approval", "delete_idempotency", "rewrite_meta")
BOUNDARY_TAMPER = ("delete_store",)       # B4 only (PROT-H29 s9): world store + HistoryStore deleted
CLASSES = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8")


def validate_step(st: dict) -> None:
    """ValueError on a step outside the frozen vocabulary or with keys other than FIELDS + OPTIONAL."""
    op = st.get("op")
    if op not in RULES:
        raise ValueError(f"unknown step kind {op!r}")
    allowed = set(FIELDS[op]) | set(OPTIONAL.get(op, ())) | {"op"}
    if set(st) - allowed:
        raise ValueError(f"{op}: unexpected keys {sorted(set(st) - allowed)}")
    missing = set(FIELDS[op]) - set(st)
    if missing:
        raise ValueError(f"{op}: missing keys {sorted(missing)}")
