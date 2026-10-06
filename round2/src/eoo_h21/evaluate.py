"""Frozen H21 evaluator: evidence directory -> verdict.json. One named predicate per contract clause, with its numbers.

Numbers are recomputed from the raw rows where the evidence carries them (case hashes, per-mutant per-domain check results,
conformance counts); a missing / unreadable evidence file can never produce SUPPORTED.
"""
from __future__ import annotations

import json
from pathlib import Path

from eoo_exp import scaffold as sc
from eoo_exp.provenance import freeze_hash
from eoo_exp.util import ROOT, sha_file

from .run import HID, REQUIRED

SUPPORT = {
    "S1": "0 handwritten endpoint/tool additions for the preregistered ordinary Domain 2 resources (Toolchain, domains and IR-gate files unchanged; resources usable through generated tools)",
    "S2": "100% type/cardinality/function-action conformance on generated surface tests (both domains and the regenerated extended project surface)",
    "S3": "100% capability-set equality with the independent authority oracle across >= 10,000 unique generated principal cases per domain",
    "S4": "0 forbidden external/canonical effects from adversarial agent calls (positive control proves effects are observable)",
    "S5": "Generic interface tool works across >= 2 implementing object types with no per-type code (also after adding implementers)",
    "S6": "All target mutations detected (controls clean)",
}
REJECT = {"R1": "A preregistered ordinary resource required bespoke endpoint/tool code, or a security overexposure / forbidden effect occurred"}
INCONCLUSIVE = {
    "I1": "Generated principal corpus below the frozen minimum, or the interface-polymorphism case is not implemented",
    "I2": "Harness cannot answer: the effect meter never saw an effect, conformance had no checks, the end-to-end replication demo failed, or a mutant run errored",
    "I3": "Engine cross-check disagrees with the oracle where the surface and oracle agree (the oracle or the live Engine is wrong about the case space)",
}
INVALID = {
    "V1": "The Toolchain imports (or dynamically loads) the authority oracle implementation, making the differential tautological",
    "V2": "Evidence records carry a protocol-freeze / ENGINE_PREREG hash different from the files now",
    "V3": "Evidence records disagree on commit / seed / corpus hash",
    "V4": "The oracle imports the Engine / Toolchain / domains, or an oracle file changed since the run",
    "V5": "Harness self-check failed (mutation controls not clean, Engine / domain / protocol / IR files differ from HEAD)",
}
DOMAINS = ("manufacturing", "project")
NEW_TOOLS = {"act_register_replication", "call_count_replications", "get_Replication", "list_Replication", "follow_REPLICATES"}


def evaluate(exp_dir, root: Path = ROOT) -> dict:
    d = Path(exp_dir)
    th = json.loads((root / "protocol/thresholds.json").read_text())["H21"]
    minimum = json.loads((root / "hypotheses/h21/contract.json").read_text())["experiment"]["minimum_runs"]
    recs, pay, problems = sc.load_evidence(d, HID, REQUIRED, root)
    wrong, ident = sc.protocol_state(recs, root)
    n: dict = {"thresholds": th, "minimum_runs": minimum}
    mf, hw, sec, adv, pol, mu = (pay.get(f) for f in REQUIRED)
    if mf:
        c = {x: mf["domains"][x]["conformance"] for x in DOMAINS}
        n.update(conformance_checks={x: c[x]["checks"] for x in DOMAINS}, conformance_failed={x: c[x]["checks"] - c[x]["passed"] for x in DOMAINS},
                 conformance_rate=min((c[x]["passed"] / c[x]["checks"]) if c[x]["checks"] else 0.0 for x in DOMAINS),
                 clean_builds=all(mf["domains"][x]["clean_build"] and mf["domains"][x]["rebuild_identical"] for x in DOMAINS),
                 stray_files_in_generated_dir={x: mf["domains"][x]["handwritten_files_in_generated_dir"] for x in DOMAINS},
                 toolchain_forbidden_imports=mf["toolchain"]["forbidden_imports"], toolchain_imports_oracle=mf["toolchain"]["imports_oracle"],
                 toolchain_domain_token_hits=mf["domain_token_scan"]["hits"], oracle_forbidden_imports=[i for o in mf["oracle"] for i in o["forbidden_imports"]],
                 oracle_sha_matches=all(sha_file(root / o["file"]) == o["sha256"] for o in mf["oracle"]),
                 toolchain_files_scanned=len(mf["toolchain"]["files"]), tools={x: mf["domains"][x]["tools"]["by_kind"] for x in DOMAINS})
    if hw:
        e2e, rc = hw["end_to_end"], hw["regenerated_conformance"]
        n.update(handwritten_endpoint_code=hw["handwritten_endpoint_or_tool_code_added"], toolchain_files_changed=hw["toolchain_files_changed"],
                 token_hits_outside_logic=hw["token_occurrences_in_toolchain_and_domains"], gate0_unchanged=hw["gate0_files_unchanged"],
                 new_generated_tools=hw["generated_new_tools"], scanner_known_negative=hw["handwritten_endpoint_definitions"]["scanner_known_negative_planted_endpoint"],
                 e2e_ok=e2e["all_ok"], e2e_steps=[(r["step"][:60], r["ok"]) for r in e2e["steps"]], regenerated_conformance=rc["passed"] / rc["checks"] if rc["checks"] else 0.0,
                 regenerated_diff_mismatches=hw["regenerated_differential"]["mismatching_cases"], domain_logic=hw["domain_logic"]["lines_total"],
                 read_only_paths_dirty=hw["read_only_paths_dirty"])
    if sec:
        D = sec["domains"]
        n.update(unique_cases={x: len(set(D[x]["case_sha256"])) for x in DOMAINS},
                 mismatching_cases={x: D[x]["differential"]["mismatching_cases"] for x in DOMAINS},
                 overexposed={x: D[x]["differential"]["overexposed_total"] for x in DOMAINS}, underexposed={x: D[x]["differential"]["underexposed_total"] for x in DOMAINS},
                 capability_equality=min(1.0 - D[x]["differential"]["mismatching_cases"] / max(1, D[x]["differential"]["cases"]) for x in DOMAINS),
                 dimensions=sorted({k for x in DOMAINS for k in D[x]["differential"]["capabilities_compared"]}),
                 capabilities_compared={x: D[x]["differential"]["capabilities_compared"] for x in DOMAINS},
                 coverage={x: D[x]["differential"]["coverage"] for x in DOMAINS},
                 engine_cross_check={x: {k: D[x]["engine_cross_check"][k] for k in ("cases", "decisions_compared", "disagreements")} for x in DOMAINS},
                 baseline_contextual={x: D[x]["baseline_contextual"] for x in DOMAINS})
    if adv:
        T = {x: adv["domains"][x]["totals"] for x in DOMAINS}
        n.update(adversarial=T, positive_control={x: adv["domains"][x]["positive_control"]["effect_observed"] for x in DOMAINS},
                 forbidden_effects=sum(t["principals_with_effects"] + t["other_outcomes"] + t["attribute_leaks"] + t["engine_touched_by_surface_attacks"]
                                       + (t["backstop_calls"] - t["backstop_denied"]) for t in T.values()),
                 adversarial_calls=sum(t["direct_calls"] + t["fuzz_calls"] + t["backstop_calls"] for t in T.values()))
    if pol:
        rows = {x: pol["domains"][x] for x in DOMAINS}
        named = {x: next((r for r in rows[x] if r["interface"] == i), None) for x, i in (("project", "VersionedResearchObject"), ("manufacturing", "Statused"))}
        n.update(interfaces={x: len(rows[x]) for x in DOMAINS}, interface_implementers={x: (r["implementer_count"] if r else None) for x, r in named.items()},
                 interface_failures=[f"{x}:{r['interface']}" for x in DOMAINS for r in rows[x]
                                     if not r["equals_store"] or r["tool_source_names_an_implementer"] or r["types_served"] != r["types_with_objects"]
                                     or not r["after_adding_two_implementers"]["tool_source_identical"] or not r["after_adding_two_implementers"]["serves_new_types"]],
                 interface_min_served=min((r["types_served"] for x in DOMAINS for r in rows[x] if r["interface"] in ("VersionedResearchObject", "Statused")), default=0),
                 replication_seventh=pol["extended_project_ir_replication_as_seventh_implementer"]["ok"])
    if mu:
        tg = [m for m in mu["mutants"] if m["target"]]

        def killed(m):
            return not m["harness_errors"] and all(bool(r["conformance_failed"] or r["differential_mismatching_cases"] or r["polymorphism_failures"])
                                                   for r in m["per_domain"].values()) and len(m["per_domain"]) == len(DOMAINS)
        n.update(mutation_total=len(tg), mutation_killed=sum(killed(m) for m in tg), mutation_kill_rate=(sum(killed(m) for m in tg) / len(tg)) if tg else 0.0,
                 mutation_survivors=[m["id"] for m in tg if not killed(m)], mutation_errors={m["id"]: m["harness_errors"] for m in tg if m["harness_errors"]},
                 mutation_contract_four_present=sorted(m["id"] for m in tg if m["contract_mutation"]),
                 mutation_controls_clean=bool(mu["controls"]["clean"]), mutation_detected_by={m["id"]: m["detected_by"] for m in tg})

    def has(*k):
        return all(x in n for x in k)
    s1 = (n["handwritten_endpoint_code"] <= th["max_handwritten_endpoints_for_preregistered_ordinary_resources"] and not n["toolchain_files_changed"]
          and not n["token_hits_outside_logic"] and n["gate0_unchanged"] and NEW_TOOLS <= set(n["new_generated_tools"]) and n["e2e_ok"]
          and n["scanner_known_negative"] == ["act_register_replication"]) if has("handwritten_endpoint_code") else None
    s2 = (n["conformance_rate"] >= th["required_type_conformance"] and n["regenerated_conformance"] >= th["required_type_conformance"]
          and n["clean_builds"] and all(v > 0 for v in n["conformance_checks"].values())) if has("conformance_rate", "regenerated_conformance") else None
    s3 = (all(v >= th["min_generated_principal_cases"] for v in n["unique_cases"].values()) and n["capability_equality"] >= th["required_capability_set_equality"]
          and not any(n["mismatching_cases"].values()) and {"actionable", "queryable", "visible"} <= set(n["dimensions"])) if has("unique_cases", "capability_equality") else None
    s4 = (n["forbidden_effects"] <= th["max_forbidden_effects"] and all(n["positive_control"].values()) and n["adversarial_calls"] > 0
          and all(t["hidden_action_instances"] > 0 and t["unknown_tool"] == t["direct_calls"] + t["fuzz_calls"] and t["surface_oracle_tool_mismatches"] == 0
                  for t in n["adversarial"].values())) if has("forbidden_effects") else None
    s5 = (not n["interface_failures"] and n["interface_min_served"] >= th["min_interface_implementations"] and n["replication_seventh"]
          and all(v is not None and v >= th["min_interface_implementations"] for v in n["interface_implementers"].values())) if has("interface_failures") else None
    s6 = (n["mutation_kill_rate"] >= th["required_mutation_kill_rate"] and n["mutation_controls_clean"] and not n["mutation_errors"]
          and len(n["mutation_contract_four_present"]) == 5) if has("mutation_kill_rate") else None
    r1_parts = []
    if has("handwritten_endpoint_code"):
        r1_parts.append(n["handwritten_endpoint_code"] > 0 or bool(n["toolchain_files_changed"]) or bool(n["token_hits_outside_logic"]))
    if has("overexposed"):
        r1_parts.append(any(v > 0 for v in n["overexposed"].values()))
    if has("forbidden_effects"):
        r1_parts.append(n["forbidden_effects"] > 0)
    r1 = any(r1_parts) if r1_parts else None
    i1 = (any(v < th["min_generated_principal_cases"] for v in n["unique_cases"].values())
          or any(v is None or v < th["min_interface_implementations"] for v in n["interface_implementers"].values())) if has("unique_cases", "interface_implementers") else None
    i2 = (not all(n["positive_control"].values()) or any(v == 0 for v in n["conformance_checks"].values()) or not n["e2e_ok"] or bool(n["mutation_errors"])) \
        if has("positive_control", "conformance_checks", "e2e_ok", "mutation_errors") else None
    i3 = any(v["disagreements"] > 0 for v in n["engine_cross_check"].values()) if has("engine_cross_check") else None
    v1 = (bool(n["toolchain_imports_oracle"]) or bool(n["toolchain_forbidden_imports"])) if has("toolchain_imports_oracle") else None
    v4 = (bool(n["oracle_forbidden_imports"]) or not n["oracle_sha_matches"]) if has("oracle_forbidden_imports") else None
    v5 = (bool(n.get("read_only_paths_dirty")) or (has("mutation_controls_clean") and not n["mutation_controls_clean"]))
    pred = {"support_if": sc.rows(SUPPORT, {"S1": s1, "S2": s2, "S3": s3, "S4": s4, "S5": s5, "S6": s6}), "reject_if": sc.rows(REJECT, {"R1": r1}),
            "inconclusive_if": sc.rows(INCONCLUSIVE, {"I1": i1, "I2": i2, "I3": i3}),
            "invalid_if": sc.rows(INVALID, {"V1": v1, "V2": bool(wrong), "V3": len(ident) > 1, "V4": v4, "V5": v5})}
    return sc.finish(HID, ident[0][3] if ident else None, protocol_valid=not wrong and len(ident) <= 1 and not v1 and not v4 and not v5,
                     complete=not problems, sample_sufficient=(i1 is False and i2 is False and i3 is False), reject_hit=r1 is True,
                     support_hit=all(x is True for x in (s1, s2, s3, s4, s5, s6)), predicates=pred, numbers=n, problems=problems,
                     extra={"protocol": {"freeze_sha256": freeze_hash()}, "evidence_payload_hashes": {f: r["payload_hash"] for f, r in sorted(recs.items())},
                            "evaluator_sha256": sha_file(Path(__file__)),
                            "interpretation_notes": [
                                "DEVELOPMENT RUN unless the experiment id is exp-h21-001 produced by the orchestrator in an isolated worktree.",
                                "visible/queryable capabilities are all-or-nothing by principal registration: the IR carries no read-authority rules, so the "
                                "differential is informative mainly for actionable/approvable capability sets (numbers.capabilities_compared).",
                                "Opaque selectors (ProjectOntology:*, Threshold:preregistered) are domain logic injected into the surface; the differential "
                                "uses harness/oracle models of them over the case world; the Engine cross-check uses the domain pack's real bindings.",
                                "The surface/Engine boundary: hidden tools are absent from the surface; the Engine's authority gate is a second line, measured "
                                "separately (adversarial backstop_denied), not credited to the Toolchain.",
                                "Baseline is CONTEXTUAL only (numbers.baseline_contextual): it supports no clause."]})
