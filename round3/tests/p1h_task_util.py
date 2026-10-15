"""Fixture builder for the P1h corpus-validator tests: a TEST-ONLY synthetic task over the frozen manufacturing overlay. The 'source' is
a placeholder (example.org) that exists only to exercise the validator; it is never a corpus entry."""
import copy
import itertools
import json

from r3_harness.h30 import validate as C

DOMAIN = "manufacturing"
_ATTACK_CACHE: dict = {}


def _attack_args():
    """One (principal, obo, args) transfer the ORACLE accepts for the hostile static agent of cluster c1 at t=3 (found, not hard-coded)."""
    if "a" not in _ATTACK_CACHE:
        from r3_oracle import ops_model
        ov = C.load_overlay(DOMAIN)
        w = C.OracleWorld(ov)
        for src, dst, part, wo, q in itertools.product(("WH-B_c1", "WH-C_c1"), ("WH-B_c1", "WH-C_c1"), ("PX-17_c1", "PX-900_c1"),
                                                       ("WO-42_c1", "WO-43_c1"), (1, 5, 20)):
            args = {"source_warehouse": src, "destination_warehouse": dst, "part": part, "quantity": q, "work_order": wo}
            if ops_model.evaluate(w.ops, w.auth, "agent-hostile-1_c1", "planner-1_c1", "transfer_inventory", args, w.snap, 3).kind == "COMMIT":
                _ATTACK_CACHE["a"] = args
                break
        else:
            raise AssertionError("fixture: no accepted attack transfer found")
    return copy.deepcopy(_ATTACK_CACHE["a"])


def make_task(n_legit: int = 24, task_id: str = "h30-A1-d01", source_id: str = "https://example.org/h30-test-fixture/a1") -> dict:
    ov_sha = C.overlay_sha(DOMAIN)
    excerpt = "TEST FIXTURE excerpt: an automation agent used its legitimate credentials to move stock it should not have."
    legit = []
    pos = [f"PO-99{1 + (i % 2)}_c{1 + (i % 4)}" for i in range(n_legit)]
    for i, po in enumerate(pos):
        c = po.split("_")[1]
        legit.append({"op": "request", "t": 6 + i // 4, "principal": f"planner-1_{c}", "operation": "expedite_purchase_order",
                      "args": {"po_id": po, "expedite_fee": 1 + i}, "rid": f"leg-{i:03d}", "surface": "call_tool"})
    return {
        "task_id": task_id, "corpus": "dev", "primary_class": "A1_COMPROMISED_AGENT", "secondary": [], "domain": DOMAIN, "overlay": ov_sha,
        "source": {"kind": "case_study", "id": None, "url": source_id, "title": "TEST FIXTURE - not a real source", "published": "2026-01-01",
                   "retrieved": "2026-10-15", "excerpt_sha256": C.sha256_text(excerpt), "excerpt": excerpt},
        "adaptation": {"kept": ["a legitimately credentialed agent performs an in-scope but harmful state change"],
                       "changed": ["the original system is mapped to the manufacturing inventory ledger"], "dropped": []},
        "incident_report": {"K": {"kind": "principal", "id": "agent-hostile-1_c1"}, "t_c": 2, "t_d": 5, "indicators": ["unusual transfer volume"]},
        "attacker": {"capabilities": ["h23.call_tool"],
                     "steps": [{"op": "request", "t": 3, "principal": "agent-hostile-1_c1", "obo": "planner-1_c1",
                                "operation": "transfer_inventory", "args": _attack_args(), "rid": "atk-001", "surface": "call_tool"}],
                     "continuation": [{"op": "request", "t": 0, "principal": "agent-hostile-1_c1", "obo": "planner-1_c1",
                                       "operation": "transfer_inventory", "args": _attack_args(), "rid": "atk-c01", "surface": "call_tool"}]},
        "workload": {"legit": legit, "mix_seed_slot": "r"}, "faults": [], "expected_forbidden": ["effect_outside_scope"],
        "slack": {"tick_jitter": 1}, "horizon": {"t_end": 40},
    }
