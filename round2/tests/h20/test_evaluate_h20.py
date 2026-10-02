"""Evaluator: a known-positive evidence directory is SUPPORTED; for EACH clause a known-negative flips exactly that clause."""
import json

import pytest

from conftest import rewrite
from eoo_h20.evaluate import INCONCLUSIVE, INVALID, REJECT, SUPPORT, evaluate


def vals(v):
    return {r["id"]: r["value"] for rows in v["predicates"].values() for r in rows}


def test_known_positive_is_supported(pos):
    v = evaluate(pos)
    assert v["verdict"] == "SUPPORTED", (v["problems"], vals(v))
    assert [k for k, x in vals(v).items() if x is not (k.startswith("S"))] == []
    n = v["numbers"]
    assert n["synthetic_unique"] >= 3000 and n["lifecycle_conformity"] == 1.0 and n["mutation_kill_rate"] == 1.0 and n["forbidden_core_branches"] == 0


def test_the_real_small_run_is_not_supported_because_it_is_below_the_frozen_sample(small_run):
    v = evaluate(small_run)
    assert v["verdict"] == "INCONCLUSIVE" and vals(v)["I2"] is True and vals(v)["S4"] is False


def flip(pos, fname, fn, expect_true, verdict, expect_false=()):
    rewrite(pos, fname, fn)
    v = evaluate(pos)
    got = vals(v)
    assert v["verdict"] == verdict, (v["verdict"], {k: x for k, x in got.items() if x is not (k.startswith("S"))})
    for k in expect_true:
        assert got[k] is True, (k, got)
    for k in expect_false:
        assert got[k] is False, (k, got)
    return v


def test_s1_and_r1_a_domain_branch_in_the_engine_is_rejected(pos):
    row = {"file": "src/eoo_engine/x.py", "line": 3, "tokens": ["transfer_inventory"], "value": "transfer_inventory", "position": "compare"}
    v = flip(pos, "engine-static-audit.json", lambda p: p["token_hits"].append(row), ["R1"], "REJECTED", ["S1"])
    assert v["numbers"]["forbidden_core_branches"] == 1  # recomputed from the raw hit row, not copied from a summary field


def test_s1_a_plain_literal_of_a_domain_id_in_the_engine_is_rejected_too(pos):
    row = {"file": "src/eoo_engine/x.py", "line": 3, "tokens": ["Part"], "value": "Part", "position": "plain"}
    v = flip(pos, "engine-static-audit.json", lambda p: p["token_hits"].append(row), ["R1"], "REJECTED", ["S1"])
    assert v["numbers"]["forbidden_core_branches"] == 0 and v["numbers"]["forbidden_core_literals"] == 1


def test_s1_identity_branch_without_a_token_is_rejected(pos):
    flip(pos, "engine-static-audit.json", lambda p: p.update(identity_branch_hits=[{"file": "x", "line": 1, "name": "package_id"}]),
         ["R1"], "REJECTED", ["S1"])


def test_s2_a_lifecycle_violation_is_inconclusive_not_supported(pos):
    def bad(p):
        p["domains"]["project"]["executions"]["history_counts"]["PROPOSED > EXECUTING"] = 1
    v = flip(pos, "dispatch-traces.json", bad, ["I3"], "INCONCLUSIVE", ["S2"])
    assert v["numbers"]["nonconforming_histories"]["project"] == ["PROPOSED > EXECUTING"]


def test_s2_an_unexecuted_action_fails_the_100_percent(pos):
    def bad(p):
        a = p["domains"]["manufacturing"]["actions"]
        a["executed_with_conformant_history"] = a["executed_with_conformant_history"][:-1]
    flip(pos, "dispatch-traces.json", bad, [], "INCONCLUSIVE", ["S2"])


def test_s2_a_foreign_dispatch_operation_fails(pos):
    flip(pos, "dispatch-traces.json", lambda p: p["domains"]["project"]["dispatch"].append({"kind": "actions", "op": "teleport", "calls": 1, "generic": True}),
         [], "INCONCLUSIVE", ["S2"])


def test_s3_governance_in_an_adapter_is_rejected(pos):
    def bad(p):
        p["static"]["files"][0]["violations"].append({"line": 5, "kind": "governance_definition", "name": "check_policy", "concern": "policy"})
    v = flip(pos, "adapter-responsibility-audit.json", bad, ["R1"], "REJECTED", ["S3"])
    assert v["numbers"]["adapter_static_violations"] == 1


def test_s3_in_adapter_taint_and_ok_mode_refusal_are_rejected(pos):
    flip(pos, "adapter-responsibility-audit.json", lambda p: p["dynamic"]["governance_calls_inside_adapters"].append({"called": "Journal.append", "adapter": "X.apply"}),
         ["R1"], "REJECTED")


def test_s3_an_untrusted_taint_detector_blocks_support(pos):
    flip(pos, "adapter-responsibility-audit.json", lambda p: p["dynamic"]["taint_known_negative"].update(detected=False), ["I3"], "INCONCLUSIVE", ["S3"])


def test_s3_engine_not_owning_idempotency_blocks_support(pos):
    def bad(p):
        p["dynamic"]["engine_owns_idempotency_probe"][0]["engine_decided"] = False
    flip(pos, "adapter-responsibility-audit.json", bad, [], "INCONCLUSIVE", ["S3"])


def test_s4_an_edited_engine_blocks_support(pos):
    def bad(p):
        k = next(iter(p["engine_files_sha256_after"]))
        p["engine_files_sha256_after"][k] = "0" * 64
    flip(pos, "synthetic-resource-results.json", bad, [], "INCONCLUSIVE", ["S4"])


def test_s4_a_changed_dispatch_table_blocks_support(pos):
    flip(pos, "synthetic-resource-results.json", lambda p: p["dispatch_fingerprint_after"]["actions"].update(ops=["propose"]), [], "INCONCLUSIVE", ["S4"])


def test_s4_engine_oracle_disagreement_is_inconclusive(pos):
    flip(pos, "synthetic-resource-results.json", lambda p: p["definitions"][0].update(mismatches=["state X != Y"]), ["I3"], "INCONCLUSIVE", ["S4"])


def test_r1_alias_dependent_behaviour_is_rejected(pos):
    flip(pos, "synthetic-resource-results.json", lambda p: p["alias_invariance"].update(disagreements=2), ["R1"], "REJECTED", ["S4"])


def test_i2_too_few_unique_definitions_is_inconclusive(pos):
    def bad(p):
        p["definitions"] = p["definitions"][:2999]
    flip(pos, "synthetic-resource-results.json", bad, ["I2"], "INCONCLUSIVE", ["S4"])


def test_i2_duplicate_shas_do_not_count_twice(pos):
    def bad(p):
        for r in p["definitions"]:
            r["sha"] = r["sha"].split("-copy")[0]
    flip(pos, "synthetic-resource-results.json", bad, ["I2"], "INCONCLUSIVE")


def test_s5_a_surviving_mutant_blocks_support(pos):
    def bad(p):
        m = p["mutants"][0]
        m["signals"]["static_flagged"] = m["signals"]["dynamic_flagged"] = False
    v = flip(pos, "mutation-results.json", bad, [], "INCONCLUSIVE", ["S5"])
    assert v["numbers"]["mutation_survivors"] == [json.loads((pos / "mutation-results.json").read_text())["payload"]["mutants"][0]["id"]]


def test_s5_a_single_class_of_mutation_is_not_enough(pos):
    def bad(p):
        p["mutants"] = [m for m in p["mutants"] if m["class"] == "domain_branch_in_engine"]
    flip(pos, "mutation-results.json", bad, [], "INCONCLUSIVE", ["S5"])


@pytest.mark.parametrize("path_key", ["read_dispatches", "function_dispatches", "security_authority_denials", "provenance_records"])
def test_i1_a_domain_missing_a_path_is_inconclusive(pos, path_key):
    flip(pos, "dispatch-traces.json", lambda p: p["domains"]["manufacturing"]["paths"].update({path_key: 0}), ["I1"], "INCONCLUSIVE")


def test_i1_no_completed_governed_action_is_inconclusive(pos):
    def bad(p):
        c = p["domains"]["project"]["executions"]["history_counts"]
        for h in [h for h in c if h.endswith("RECONCILED_SUCCESS")]:
            c.pop(h)
    flip(pos, "dispatch-traces.json", bad, ["I1"], "INCONCLUSIVE")


def test_i3_a_failing_domain_suite_is_inconclusive(pos):
    flip(pos, "dispatch-traces.json", lambda p: p["suites"]["pytest"].update(failed=1, exit_code=1), ["I3"], "INCONCLUSIVE")


def test_v1_an_unscanned_participating_file_is_invalid(pos):
    flip(pos, "engine-static-audit.json", lambda p: p["participation"]["unscanned_participants"].append("src/hidden_hook.py"), ["V1"], "INVALID")


def test_v1_a_dynamic_import_site_in_the_closure_is_invalid(pos):
    flip(pos, "engine-static-audit.json", lambda p: p["closure"]["dynamic_import_sites"].update({"src/eoo_engine/engine.py": [{"line": 1, "name": "exec"}]}), ["V1"], "INVALID")


def test_v2_wrong_protocol_hash_is_invalid(pos):
    rec = json.loads((pos / "adapter-responsibility-audit.json").read_text())
    rec["protocol_freeze_hash"] = "0" * 64
    (pos / "adapter-responsibility-audit.json").write_text(json.dumps(rec))
    v = evaluate(pos)
    assert v["verdict"] == "INVALID" and vals(v)["V2"] is True


def test_v2_wrong_prereg_hash_is_invalid(pos):
    rec = json.loads((pos / "mutation-results.json").read_text())
    rec["engine_prereg_sha256"] = "0" * 64
    (pos / "mutation-results.json").write_text(json.dumps(rec))
    assert evaluate(pos)["verdict"] == "INVALID"


def test_v3_disagreeing_provenance_is_invalid(pos):
    rec = json.loads((pos / "mutation-results.json").read_text())
    rec["seed"] = 999
    (pos / "mutation-results.json").write_text(json.dumps(rec))
    v = evaluate(pos)
    assert v["verdict"] == "INVALID" and vals(v)["V3"] is True


def test_v4_oracle_importing_the_engine_is_invalid(pos):
    flip(pos, "engine-static-audit.json", lambda p: p["oracle"][0].update(forbidden_imports=["eoo_engine"]), ["V4"], "INVALID")


def test_v4_a_changed_oracle_file_is_invalid(pos):
    flip(pos, "engine-static-audit.json", lambda p: p["oracle"][0].update(sha256="0" * 64), ["V4"], "INVALID")


def test_v5_dirty_engine_files_are_invalid(pos):
    flip(pos, "engine-static-audit.json", lambda p: p["engine_files"].update(clean=False, paths_dirty=["round2/src/eoo_engine/engine.py"]), ["V5"], "INVALID")


def test_v5_unclean_mutation_control_is_invalid(pos):
    flip(pos, "mutation-results.json", lambda p: p["controls"].update(clean=False), ["V5"], "INVALID")


def test_missing_evidence_never_supports(pos):
    (pos / "mutation-results.json").unlink()
    v = evaluate(pos)
    assert v["verdict"] != "SUPPORTED" and v["problems"] and vals(v)["S5"] is None


def test_tampered_payload_never_supports(pos):
    rec = json.loads((pos / "mutation-results.json").read_text())
    rec["payload"]["mutants"][0]["description"] = "changed after sealing"
    (pos / "mutation-results.json").write_text(json.dumps(rec))
    v = evaluate(pos)
    assert v["verdict"] != "SUPPORTED" and any("payload_hash" in p for p in v["problems"])


def test_every_contract_clause_has_a_named_predicate(pos):
    from eoo_exp.util import ROOT
    contract = json.loads((ROOT / "hypotheses/h20/contract.json").read_text())["evaluator"]
    got = vals(evaluate(pos))
    for key, table in (("support_if", SUPPORT), ("reject_if", REJECT), ("inconclusive_if", INCONCLUSIVE), ("invalid_if", INVALID)):
        assert len(table) >= len(contract[key])
    assert {"S1", "S2", "S3", "S4", "S5", "R1", "I1", "I2", "I3", "V1", "V2", "V3", "V4", "V5"} == set(got) and len(contract["support_if"]) == 5


def test_verdict_is_a_pure_function_of_the_evidence(pos):
    a, b = evaluate(pos), evaluate(pos)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
