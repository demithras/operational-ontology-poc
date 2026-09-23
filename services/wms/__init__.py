"""Fake WMS source system (docs/experiment/spec/02_scope_and_non_goals.md,
06_decision_and_action_runtime.md "WMS fake API requirements").

Owns: warehouses, inventory lots, on-hand/reserved quantities, inventory
transfers. WMS-local part ids look like SKU-xxxxx. This is the only fake
source with externally-visible side effects the action runtime executes
against, so it is also where idempotency and fault injection live.
"""
