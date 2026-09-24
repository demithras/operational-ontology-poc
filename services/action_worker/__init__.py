"""Temporal-driven durable action runtime (docs/experiment/spec/06_decision_and_action_runtime.md
"Execute algorithm") — Phase 6.

Owns the ONLY code path that calls WMS/ERP/MES to APPLY an approved
Decision's action, and the evaluation of that action's outcome predicate
against CDC-observed reality (never the command response alone — H3/H12).
"""
