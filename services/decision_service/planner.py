"""Deterministic rule-based planner — docs/experiment/spec/01_hypotheses.md
H10 ("the canonical incident and all core acceptance tests pass with a
deterministic rule-based planner ... no LLM"). Reads ONLY the Phase 4 hot
projections (work_order_risk, transfer_candidates — never invents its own
query path) and picks a mitigation using a fixed, explainable rule: the
transfer_candidates row with the LARGEST candidate_quantity (ties broken by
candidate_id for determinism), transferring exactly `min(candidate_quantity,
shortage)`.

This function does not itself call propose() — it returns a ready-to-submit
ProposeRequest-shaped dict; the caller (a human, a script, or a test) is the
one who decides whether/how to submit it, keeping "recommend" and "govern"
as separate steps per spec 06 "Separation of proposal and execution".
"""

from __future__ import annotations

from typing import Any

import psycopg

from services.projection_builder import reader


def recommend_transfer_for_work_order(conn: psycopg.Connection, work_order_id: str) -> dict[str, Any] | None:
    risk = reader.get_work_order_risk(conn, work_order_id)
    if risk is None or not risk["at_risk"]:
        return None
    candidates = reader.get_transfer_candidates(conn, work_order_id)
    if not candidates:
        return None
    best = sorted(candidates, key=lambda c: (-c["candidate_quantity"], c["candidate_id"]))[0]
    quantity = min(best["candidate_quantity"], risk["shortage"])
    return {
        "action_type": "transfer_inventory",
        "parameters": {
            "source_warehouse": best["source_warehouse"],
            "destination_warehouse": best["destination_warehouse"],
            "part": best["part"],
            "quantity": quantity,
        },
        "context": {"work_order_id": work_order_id},
    }
