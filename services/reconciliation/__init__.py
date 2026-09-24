"""Independent reality-check (H12) — a SEPARATE consumer from
services/action_worker that re-verifies (never blindly trusts) an
ActionExecution's outcome against CDC-observed reality, converges
AWAITING_OBSERVATION decisions once delayed CDC catches up (F18), and
raises a reconciliation-alert record on genuine divergence.
"""
