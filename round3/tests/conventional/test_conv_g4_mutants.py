"""P1f-9 / PROT-H28 s9: each H28 mutant is killed by a test through its OWN class; the clean build is 0 on that class."""
import pytest

from conv_g4_util import (BIG_EXPEDITE, EXPEDITE, PUBLISH_PUBLIC, Dup, FalseSuccess, Honest, TargetSubst, TimeoutAfterApply, make_g4)
from r3_shared.extadapter import AdapterReply
from r3_shared.mutants import KNOWN


class TargetPlusIntended(Honest):                 # T3
    adapter_id = "T3"

    def submit(self, req):
        super().submit(req)
        self.client.write(req.cap, req.operation, req.target + "-evil", req.payload, self.adapter_id)
        return AdapterReply("OK", {})


def _run(tmp_path, mutants, adapter, op="expedite_purchase_order", args=EXPEDITE, who="planner-1"):
    r = make_g4(tmp_path, mutants=mutants, default=adapter)
    res = r.dep.call_tool(r.token(who), op, args, request_id="m1")
    return r, res


def _state(r, wm_add=0):
    return r.dep.reconcile("m1", r.clock.now() + wm_add).body["outcomes"][0]["state"]


@pytest.mark.parametrize("mut", [(), ("adapter_success_trusted",)], ids=["clean", "adapter_success_trusted"])
def test_adapter_success_trusted_false_reconciled_success(tmp_path, mut):
    r, _ = _run(tmp_path, mut, FalseSuccess)                       # L1: reply OK, nothing written
    assert r.ledger() == []
    false_success = r.dep.outcome("m1").body["outcomes"][0]["state"] == "RECONCILED_SUCCESS" or _state(r) == "RECONCILED_SUCCESS"
    assert false_success == bool(mut)


@pytest.mark.parametrize("mut", [(), ("observation_coupled",)], ids=["clean", "observation_coupled"])
def test_observation_coupled_false_reconciled_success(tmp_path, mut):
    r, _ = _run(tmp_path, mut, FalseSuccess)
    assert (_state(r) == "RECONCILED_SUCCESS") == bool(mut)


@pytest.mark.parametrize("mut", [(), ("credential_scope_broadened",)], ids=["clean", "credential_scope_broadened"])
def test_credential_scope_broadened_effect_outside_scope(tmp_path, mut):
    r, _ = _run(tmp_path, mut, TargetSubst)
    outside = [e for e in r.ledger() if e["target"] != "po:PO-991"]
    assert bool(outside) == bool(mut)


@pytest.mark.parametrize("mut", [(), ("idempotency_disabled",)], ids=["clean", "idempotency_disabled"])
@pytest.mark.parametrize("adapter", [Dup, TimeoutAfterApply], ids=lambda a: a.adapter_id)
def test_idempotency_disabled_duplicate_effect(tmp_path, mut, adapter):
    r, _ = _run(tmp_path, mut, adapter)
    r.dep.dispatch_pending()
    assert (len(r.ledger()) > 1) == bool(mut)


@pytest.mark.parametrize("mut", [(), ("divergence_rewritten",)], ids=["clean", "divergence_rewritten"])
@pytest.mark.parametrize("adapter", [TargetSubst, TargetPlusIntended], ids=lambda a: a.adapter_id)
def test_divergence_rewritten_misses_target_mutation(tmp_path, mut, adapter):
    r, _ = _run(tmp_path, mut, adapter)
    assert (_state(r, 20) == "DIVERGED") == (not mut)


@pytest.mark.parametrize("mut", [(), ("policy_gate_in_adapter",)], ids=["clean", "policy_gate_in_adapter"])
def test_policy_gate_in_adapter_manufacturing(tmp_path, mut):
    r, res = _run(tmp_path, mut, Honest, args=BIG_EXPEDITE)       # the oracle says DENIED (approval_required)
    assert (res.status == "OK") == bool(mut)                      # mutant: decision plane commits OK ...
    assert r.sent("ERP") == [] and r.ledger() == []                # ... and the adapter-side gate blocks the dispatch


def test_policy_gate_in_adapter_still_dispatches_when_approved(tmp_path):
    r = make_g4(tmp_path, mutants=("policy_gate_in_adapter",))
    assert r.dep.approve(r.token("admin-1"), "expedite_purchase_order", BIG_EXPEDITE, "planner-1").status == "OK"
    assert r.dep.call_tool(r.token("planner-1"), "expedite_purchase_order", BIG_EXPEDITE, request_id="m1").status == "OK"
    assert len(r.sent("ERP")) == 1


@pytest.mark.parametrize("mut", [(), ("policy_gate_in_adapter",)], ids=["clean", "policy_gate_in_adapter"])
def test_policy_gate_in_adapter_project_overlay(tmp_path, mut):
    r = make_g4(tmp_path / str(len(mut)), "project", mutants=mut)
    res = r.dep.call_tool(r.token("researcher-1"), "publish_result", PUBLISH_PUBLIC, request_id="m1")
    assert (res.status == "OK") == bool(mut) and r.sent("REGISTRY") == []


def test_every_h28_mutant_is_constructible_and_covered_by_a_test_here():
    from conventional.variant import ConventionalVariant
    for m in KNOWN["H28"]:
        assert ConventionalVariant((m,)).mutant_switches == {m}
    src = open(__file__).read()
    assert all(f"test_{m}" in src for m in KNOWN["H28"])
