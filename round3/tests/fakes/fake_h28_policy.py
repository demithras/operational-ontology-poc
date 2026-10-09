"""ADAPTER-SIDE business policy of the `policy_gate_in_adapter` mutant (PROT-H28 s9, Q10): the approval rule moved out of the
decision plane into code that runs just before submit. Test fake only - a separate module so the static audit can be pointed at it."""
FEE_LIMIT = 500


def blocked(operation: str, payload: dict, approved: bool) -> bool:
    """Refuse to dispatch an expedite above the fee limit / a public publish without approval (the rule the decision plane no
    longer enforces: the request commits OK, the external effect is silently not carried out)."""
    if operation == "expedite" and payload.get("expedite_fee", 0) > FEE_LIMIT and not approved:
        return True
    if operation == "publish" and payload.get("visibility") == "public" and not approved:
        return True
    return False
