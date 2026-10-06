"""H20 oracle for generated synthetic definitions: expected outcome of one scenario from the definition alone.

Stdlib only; never imports eoo_engine / eoo_toolchain / domains/*/logic. The expected values are derived from the
written lifecycle (docs/engine_semantics.md section 6) and the knobs of the definition, never from engine output.
"""

PROFILES = {  # principal profile -> (registered, has role, has relation)
    "actor": (True, True, True), "roleonly": (True, True, False), "relonly": (True, False, True),
    "outsider": (True, False, False), "ghost": (False, False, False)}
EXTERNAL = ("external", "update+external")
STORE = ("create", "update", "update+external", "link")


def n_effects(effect: str) -> int:
    return 2 if effect == "update+external" else 1


def expected(d: dict) -> dict:
    """{"state", "gate" (failed gate or None), "committed", "store_changes", "external_calls", "approved", "soft"}."""
    a, s = d["action"], d["scenario"]
    out = {"state": None, "gate": None, "committed": False, "store_changes": False, "external_calls": 0, "approved": False,
           "soft": False}

    def deny(gate):
        out.update(state="DENIED", gate=gate)
        return out
    registered, role, rel = PROFILES[s["principal"]]
    if not registered:
        return deny("identity")
    if a["idempotency"] == "required" and s["key"] == "missing":
        return deny("request")
    if a["effect"] != "create" and s["ref"] == "bad":
        return deny("inputs")
    allowed = (rel and a["effect"] != "create") if a["authority"] == "relation" else role
    if not allowed:
        return deny("authority")
    if a["precondition"] == "positive" and not s["n"] > 0:
        return deny("preconditions")
    applies = s["n"] > a["policy_t"]
    pol = a["policy"]
    if pol == "deny" and applies:
        return deny("policy")
    if pol == "allow" and not applies:
        return deny("policy")
    if pol == "approval" and applies:
        if s["approval"] in ("self", "unauthorized"):
            out["state"] = "PENDING_APPROVAL"
            return out
        if s["approval"] == "reject":
            return deny("approval")
        out["approved"] = True
    out["state"] = "APPROVED"
    store = a["effect"] in STORE
    if a["effect"] == "create" and s["ref"] == "dup" and store:
        return deny("integrity")
    wouldbe_n = s["n"] if a["effect"] in ("create", "update", "update+external") else None
    if a["constraint"] == "hard" and wouldbe_n is not None and wouldbe_n > a["cap"]:
        return deny("hard_constraints")
    out["soft"] = a["constraint"] == "soft" and wouldbe_n is not None and wouldbe_n > a["cap"]
    if a["effect"] in EXTERNAL:
        out["external_calls"] = 1
        if s["adapter"] == "raise":
            out["state"] = "OUTCOME_UNKNOWN"
            return out
    out["committed"] = True
    out["store_changes"] = store
    if a["effect"] in EXTERNAL:
        out["state"] = {"confirm": "RECONCILED_SUCCESS", "fail": "RECONCILED_FAILED", "silent": "OUTCOME_UNKNOWN"}[s["adapter"]]
    else:
        out["state"] = "RECONCILED_SUCCESS"
    return out


def function_value(f: dict, n: int) -> int:
    return n + f["k"] if f["kind"] == "plus" else (n if f["kind"] == "get_n" else 0)
