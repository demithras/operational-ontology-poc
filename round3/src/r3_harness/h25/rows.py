"""Evidence rows for H25 (one row per harness action) and the class vocabulary (ORACLE-AND-HARNESS-G3 A3)."""
from __future__ import annotations

VIOLATIONS = ("procedural_mismatch", "illegitimate_effect", "fabricated_judgment", "emergency_violation",
              "invalid_doc_accepted", "linearizability_violation", "unattributed_write", "writer_violation", "unlogged_write",
              "progress_loss", "domain_branch")
MEASURED_ONLY = ("race_refusal_ok", "ok")
UNMEASURABLE = ("unsupported", "world_lock_timeout")
ALL_CLASSES = VIOLATIONS + MEASURED_ONLY + UNMEASURABLE
EQUALITY = ("procedural_mismatch", "illegitimate_effect", "invalid_doc_accepted", "linearizability_violation")


def row_of(call: dict, res: dict) -> dict:
    keep = ("n", "kind", "rid", "actor", "obo", "op", "to", "status", "reason", "inv", "ret", "crash", "replay", "lat_ms")
    r = {k: call.get(k) for k in keep if call.get(k) is not None or k in ("n", "kind", "status")}
    a = call.get("action")
    if a:
        r["action"] = a["kind"] if isinstance(a, dict) else None
        r["case"] = a.get("case") if isinstance(a, dict) else None
    cls = sorted(set(res["classes"]))
    r.update({"classes": cls or ["ok"], "seq": res["seq"], "tick": res["tick"], "committed": res["committed"],
              "oracle": res["oracle"]})
    return r
