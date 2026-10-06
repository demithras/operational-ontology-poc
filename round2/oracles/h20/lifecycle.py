"""H20 oracle (frozen generic execution state machine + dispatch contract). Stdlib only.

Never imports eoo_engine, eoo_toolchain or domains/*/logic (static test + evaluator check). Transcribed from the
ENGINE_PREREG H20 wording and docs/engine_semantics.md section 6 (the written lifecycle), not from engine code.
"""

STATES = ("PROPOSED", "PENDING_APPROVAL", "APPROVED", "EXECUTING", "EFFECTS_COMMITTED", "RECONCILED_SUCCESS",
          "RECONCILED_FAILED", "OUTCOME_UNKNOWN", "DENIED")
TERMINAL = ("DENIED", "RECONCILED_SUCCESS", "RECONCILED_FAILED")
# state -> states it may move to (self-transitions are recorded in the journal but never in an execution history)
NEXT = {
    "PROPOSED": {"DENIED", "PENDING_APPROVAL", "APPROVED"},
    "PENDING_APPROVAL": {"APPROVED", "DENIED"},
    "APPROVED": {"EXECUTING", "DENIED"},
    "EXECUTING": {"EFFECTS_COMMITTED", "DENIED", "OUTCOME_UNKNOWN"},
    "EFFECTS_COMMITTED": {"RECONCILED_SUCCESS", "RECONCILED_FAILED", "OUTCOME_UNKNOWN"},
    "OUTCOME_UNKNOWN": {"RECONCILED_SUCCESS", "RECONCILED_FAILED"},
    "DENIED": set(), "RECONCILED_SUCCESS": set(), "RECONCILED_FAILED": set(),
}
# resource kind -> the generic operations the Engine may dispatch on it (kind-keyed; never a resource id)
KIND_OPS = {
    "interfaces": {"query"}, "object_types": {"get", "list"}, "link_types": {"follow"}, "observation_types": {"validate"},
    "functions": {"call"}, "policies": {"evaluate"}, "authority_rules": {"decide"}, "constraints": {"evaluate"},
    "actions": {"propose", "approve", "reject", "execute", "reconcile"},
}
# the capability each registered operation class belongs to (read / Function / governed Action / security)
CLASS_OF = {("object_types", "get"): "read", ("object_types", "list"): "read", ("link_types", "follow"): "read",
            ("interfaces", "query"): "read", ("functions", "call"): "function", ("actions", "propose"): "action",
            ("authority_rules", "decide"): "security", ("policies", "evaluate"): "security"}
PROVENANCE_REQUIRED_FIELDS = ("exec", "state", "action", "principal", "gates", "approvals", "effect_ids", "updated_at")


def history_problem(history: list) -> str | None:
    """None when ``history`` (the distinct consecutive states of one execution) is a legal path, else why not."""
    if not history or history[0] != "PROPOSED":
        return f"does not start at PROPOSED: {history[:2]}"
    for a, b in zip(history, history[1:]):
        if a not in NEXT or b not in NEXT[a]:
            return f"illegal transition {a} -> {b}"
    return None


def dispatch_problem(kind: str, op: str) -> str | None:
    return None if op in KIND_OPS.get(kind, ()) else f"({kind}, {op}) is not a generic dispatch operation"
