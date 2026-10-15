"""Shared test helpers: valid request templates, zero-effect assertion, a mapping that changes under the reader."""
from contextlib import contextmanager

from r3_shared.world import diff

VALID = {
    "transfer_inventory": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 10},
    "expedite_purchase_order": {"po_id": "PO-991", "expedite_fee": 100},
    "reschedule_work_order": {"work_order_id": "WO-43", "new_planned_start": 35},
    "create_hypothesis": {"claim": "a new claim"},
    "edit_threshold": {"threshold": "T-A", "value": {"min": 11}},
    "preregister_hypothesis": {"hypothesis": "H-A", "freeze_hash": "abc123"},
    "new_experiment_version": {"experiment": "E-B@v1", "contract_version": "CV-1"},
    "start_run": {"hypothesis": "H-B"},
    "attach_evidence": {"hypothesis": "H-C", "evidence": "EV-C2"},
    "evaluate_hypothesis": {"hypothesis": "H-C"},
    "supersede_hypothesis": {"hypothesis": "H-D", "successor": "H-E"},
    "record_decision": {"decision": "DEC-1", "contract_version": "CV-1"},
    "flag_orphan_component": {"component": "cmp-orphan"},
}
MFG_OPS = ("transfer_inventory", "expedite_purchase_order", "reschedule_work_order")
SAFE_TRANSFER = VALID["transfer_inventory"]


@contextmanager
def zero_effects(rig):
    before = rig.snap()
    yield
    assert diff(before, rig.snap()) == [], "a refused request left world effects"


class FlipDict(dict):
    """A caller-held args object: reads good values the first time, evil ones afterwards (post-authorization edit)."""

    def __init__(self, good: dict, evil: dict):
        super().__init__(good)
        self._evil, self._reads = dict(evil), {}

    def __getitem__(self, k):
        n = self._reads[k] = self._reads.get(k, 0) + 1
        return self._evil[k] if n > 1 and k in self._evil else super().__getitem__(k)
