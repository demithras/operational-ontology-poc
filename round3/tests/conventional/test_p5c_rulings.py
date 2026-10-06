"""P5c: rulings R-1 (numeric logical time), R-2 (optional ref existence), R-4 (strict authority validation)."""
import copy

import pytest

from conv_helpers import SAFE_TRANSFER, VALID, zero_effects
from conventional.variant import AUDIENCE, ConventionalVariant
from r3_shared.world import diff


def test_r1_head_commit_is_numeric_not_string_order(proj):
    r = proj.dep.read(proj.token("researcher-1"), "head_commit", {})
    assert r.status == "OK" and r.body["value"] == "c0ffee0001", r  # committed_at 100 vs 50: "50" > "100" as strings


def test_r1_non_numeric_commit_time_is_an_error_not_a_guess(proj):
    h = proj.store.handle("seed")
    h.create("Commit", "c0ffee0002", {"committed_at": "later"})
    h.close()
    r = proj.dep.read(proj.token("researcher-1"), "head_commit", {})
    assert r.status == "INVALID" and r.body["reason"] == "helper_error"


def test_r2_missing_optional_work_order_is_invalid_with_zero_effects(mfg):
    with zero_effects(mfg):
        r = mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory", {**SAFE_TRANSFER, "work_order": "NOPE"},
                           request_id="r2")
    assert r.status == "INVALID" and r.body["reason"] == "target_not_found"


def test_r2_existing_optional_work_order_commits(mfg):
    r = mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory", {**SAFE_TRANSFER, "work_order": "WO-43"},
                       request_id="r2ok")
    assert r.status == "OK"


@pytest.mark.parametrize("domain", ["manufacturing", "project"])
def test_r2_sweep_every_optional_resource_input_of_every_operation(make, domain):
    rig, n = make(domain), 0
    for op in rig.ops["operations"]:
        for inp in op["inputs"]:
            if inp["type"] == "resource" and not inp["required"]:
                n += 1
                who = "admin-1"
                with zero_effects(rig):
                    r = rig.dep.direct(rig.token(who), op["name"], {**VALID[op["name"]], inp["name"]: "NOPE-NOT-THERE"},
                                       request_id=f"sweep-{op['name']}")
                assert r.status == "INVALID", (op["name"], inp["name"], r)
    assert domain != "manufacturing" or n >= 1  # the sweep is not vacuous where optional refs exist


def test_r4_deploy_rejects_invalid_authority(tmp_path, mfg):
    bad = copy.deepcopy(mfg.auth)
    bad["grants"].append(copy.deepcopy(bad["grants"][0]))  # duplicate grant id
    with pytest.raises(ValueError):
        ConventionalVariant().deploy("manufacturing", mfg.store.handle_factory(), mfg.idp.verifier(), mfg.ops, bad, mfg.clock)


def test_r4_set_authority_duplicate_grant_id_raises_and_changes_nothing(mfg):
    v0 = mfg.dep.authority_version()
    bad = copy.deepcopy(mfg.auth)
    bad["grants"].append(copy.deepcopy(bad["grants"][0]))
    with pytest.raises(ValueError, match="duplicate grant"):
        mfg.dep.set_authority(bad)
    assert mfg.dep.authority_version() == v0 and mfg.dep.service.policy.version == 1
    assert mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory", SAFE_TRANSFER, request_id="still").status == "OK"


def test_r4_set_authority_schema_invalid_origin_raises(mfg):
    bad = copy.deepcopy(mfg.auth)
    bad["grants"][0]["origin"] = "made-up-origin"
    v0 = mfg.dep.authority_version()
    with pytest.raises(ValueError):
        mfg.dep.set_authority(bad)
    assert mfg.dep.authority_version() == v0


def test_r4_set_authority_dangling_principal_raises(mfg):
    bad = copy.deepcopy(mfg.auth)
    bad["grants"][0]["principal"] = {"id": "ghost-1"}
    with pytest.raises(ValueError):
        mfg.dep.set_authority(bad)
