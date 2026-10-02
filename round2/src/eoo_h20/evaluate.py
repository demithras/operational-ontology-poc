"""Frozen H20 evaluator: evidence directory -> verdict.json. One named predicate per contract clause, with its numbers.

Numbers are recomputed from the raw rows (per-execution histories are aggregated by the tracer, per-definition rows and per-mutant
signals are read as written); a missing / unreadable evidence file can never produce SUPPORTED.
"""
from __future__ import annotations

import json
from pathlib import Path

from eoo_exp import scaffold as sc
from eoo_h16.audit import BRANCH
from eoo_exp.provenance import freeze_hash
from eoo_exp.util import ROOT, load_oracle, sha_file

from .run import FORBIDDEN_IMPORTS, HID, REQUIRED

SUPPORT = {
    "S1": "0 forbidden domain-specific core branches (token scan + identity-in-branch scan over the whole import closure)",
    "S2": "100% registered domain operations use generic lifecycle states (all executions conform; every registered Action executed; dispatch is kind-keyed)",
    "S3": "0 governance semantics found in adapters beyond declared external binding responsibilities (static, in-adapter taint, ok-mode, Engine-owned idempotency)",
    "S4": "Generated synthetic resource/action executes without Engine edit (>= 3,000 unique, oracle-equal, Engine bytes + dispatch table unchanged, alias-invariant)",
    "S5": "All target mutations detected (controls clean)",
}
REJECT = {"R1": "A domain-specific Engine branch (token, identity, or alias-dependent behaviour) or an undeclared governance-in-adapter behaviour was found"}
INCONCLUSIVE = {
    "I1": "Either domain does not exercise read, Function, governed Action, security and provenance paths",
    "I2": "Fewer unique synthetic definitions than the frozen minimum_runs",
    "I3": "Harness cannot answer: a workload suite failed, the Engine disagreed with the oracle on a synthetic case, an execution broke the frozen lifecycle, or a known-negative went undetected",
}
INVALID = {
    "V1": "The static audit excludes files that actually participate in Engine semantic dispatch (or the closure contains a dynamic import site)",
    "V2": "Evidence records carry a protocol-freeze / ENGINE_PREREG hash different from the files now",
    "V3": "Evidence records disagree on commit / seed / corpus hash",
    "V4": "Oracle shares implementation code with the Engine (imports eoo_engine / eoo_toolchain / domains) or its file changed",
    "V5": "Harness self-check failed (mutation controls not clean, Engine / domain / protocol files differ from HEAD)",
}
DOMAINS = ("manufacturing", "project")
L = load_oracle("h20", "lifecycle")


def evaluate(exp_dir, root: Path = ROOT) -> dict:
    d = Path(exp_dir)
    th = json.loads((root / "protocol/thresholds.json").read_text())["H20"]
    minimum = json.loads((root / "hypotheses/h20/contract.json").read_text())["experiment"]["minimum_runs"]
    recs, pay, problems = sc.load_evidence(d, HID, REQUIRED, root)
    wrong, ident = sc.protocol_state(recs, root)
    n: dict = {"thresholds": th, "minimum_runs": minimum}
    st, tr, ad, sy, mu = (pay.get(f) for f in REQUIRED)
    if st:
        pa = st["participation"]
        branch = sum(1 for h in st["token_hits"] if h["position"] in BRANCH)  # recomputed from the raw hit rows
        n.update(static_files_scanned=len(st["file_sha256"]), static_token_branch_hits=branch,
                 static_token_literal_hits=len(st["token_hits"]), static_identity_branch_hits=len(st["identity_branch_hits"]),
                 forbidden_core_branches=branch + len(st["identity_branch_hits"]), forbidden_core_literals=len(st["token_hits"]),
                 static_tokens_checked=st["token_count"], string_constants_scanned=st["string_constants_scanned"],
                 participants_unscanned=pa["unscanned_participants"], participants_scanned=len(pa["scanned_engine_closure"]),
                 participants_binding_side=len(pa["binding_side"]), participants_harness_side=len(pa["harness_side"]),
                 closure_dynamic_import_sites=st["closure"]["dynamic_import_sites"], closure_domain_files=st["closure"]["domain_files_in_closure"],
                 engine_files_clean=st["engine_files"]["clean"],
                 oracle_forbidden_imports=[i for o in st["oracle"] for i in o["forbidden_imports"]],
                 oracle_sha_matches=all(sha_file(root / o["file"]) == o["sha256"] for o in st["oracle"]),
                 scanned_equals_closure=sorted(st["closure"]["files"]) == sorted(st["file_sha256"]))
    if tr:
        dm = tr["domains"]
        n["suites"] = {k: ({x: v[x] for x in ("exit_code", "passed", "failed", "error")} if k == "pytest" else v) for k, v in tr["suites"].items()}
        n["suite_failures"] = (tr["suites"]["pytest"]["exit_code"] != 0 or tr["suites"]["pytest"]["failed"] > 0
                               or any(v["failures"] for v in tr["suites"]["state_machine_sample"].values()))
        hc = {x: dm[x]["executions"]["history_counts"] for x in DOMAINS}  # recomputed: the frozen oracle judges every distinct history
        n["executions"] = {x: sum(hc[x].values()) for x in DOMAINS}
        n["distinct_histories"] = {x: len(hc[x]) for x in DOMAINS}
        n["nonconforming_histories"] = {x: sorted(h for h in hc[x] if L.history_problem(h.split(" > "))) for x in DOMAINS}
        n["nonconforming_executions"] = sum(c for x in DOMAINS for h, c in hc[x].items() if L.history_problem(h.split(" > ")))
        n["lifecycle_conformity"] = (1.0 - n["nonconforming_executions"] / max(1, sum(n["executions"].values())))
        n["action_coverage"] = {x: len(set(dm[x]["actions"]["executed_with_conformant_history"]) & set(dm[x]["actions"]["registered"]))
                                / max(1, len(dm[x]["actions"]["registered"])) for x in DOMAINS}
        n["actions_unexecuted"] = {x: dm[x]["actions"]["unexecuted"] for x in DOMAINS}
        n["dispatch_outside_generic_set"] = {x: [f"{r['kind']}.{r['op']}" for r in dm[x]["dispatch"] if L.dispatch_problem(r["kind"], r["op"])]
                                             for x in DOMAINS}
        n["not_dispatched_registered"] = {x: {k: len(v) for k, v in dm[x]["not_dispatched"].items()} for x in DOMAINS}
        n["paths"] = {x: dm[x]["paths"] for x in DOMAINS}
        n["completed_actions"] = {x: sum(c for h, c in hc[x].items() if h.endswith("RECONCILED_SUCCESS")) for x in DOMAINS}
        n["cross_domain"] = tr["cross_domain"]
        n["baseline_contextual"] = tr["baseline_contextual"]["per_domain"]
        n["provenance_complete"] = all(dm[x]["paths"]["provenance_required_fields_present"] == dm[x]["paths"]["provenance_records"] > 0 for x in DOMAINS)
    if ad:
        s, dy = ad["static"], ad["dynamic"]
        viol = sum(len(r["violations"]) for r in s["files"])  # recomputed from the per-file rows
        decl = sum(len(r["declared"]) for r in s["files"])
        n.update(adapter_files=len(s["files"]), adapter_static_violations=viol, adapter_declared_exception_hits=decl,
                 adapter_disclosed=sum(len(r["disclosed"]) for r in s["files"]), adapter_taint_violations=len(dy["governance_calls_inside_adapters"]),
                 adapter_taint_known_negative=dy["taint_known_negative"]["detected"], adapter_calls=sum(dy["adapter_calls_observed"].values()),
                 ok_mode_refusals=[r for r in dy["ok_mode_probe"] if not r["carried_out"]],
                 engine_owns_idempotency=all(r["engine_decided"] for r in dy["engine_owns_idempotency_probe"]),
                 adapter_strict_count_without_exceptions=viol + decl)
    if sy:
        R = sy["definitions"]  # recomputed from the per-definition rows
        kinds = {k for r in R for k in r["kinds"]}
        n.update(synthetic_unique=len({r["sha"] for r in R}), synthetic_structures=len({r["structure_sha"] for r in R}),
                 synthetic_mismatches=sum(1 for r in R if r["mismatches"] or r["expected_state"] != r["observed_state"]),
                 synthetic_engine_edited=sy["engine_files_sha256_before"] != sy["engine_files_sha256_after"],
                 synthetic_dispatch_changed=sy["dispatch_fingerprint_before"] != sy["dispatch_fingerprint_after"],
                 synthetic_unknown_kinds=sorted(kinds - set(sy["dispatch_fingerprint_after"])), synthetic_id_clash=sy["synthetic_ids_equal_to_domain_tokens"],
                 alias_definitions=sy["alias_invariance"]["definitions"], alias_disagreements=sy["alias_invariance"]["disagreements"],
                 synthetic_replays_identical=all(r["replay_ok"] for r in R), synthetic_retries_ok=all(r["retry_ok"] for r in R),
                 synthetic_states=dict(sorted({s: sum(1 for r in R if r["observed_state"] == s) for s in {r["observed_state"] for r in R}}.items())),
                 synthetic_engine_version=sy["candidate"]["engine_version"])
    if mu:
        det = {m["id"]: bool(m["signals"]["static_flagged"] or m["signals"]["dynamic_flagged"]) for m in mu["mutants"]}  # recomputed
        tgt = [m for m in mu["mutants"] if m["target"]]
        n.update(mutation_total=len(tgt), mutation_killed=sum(det[m["id"]] for m in tgt),
                 mutation_kill_rate=(sum(det[m["id"]] for m in tgt) / len(tgt)) if tgt else 0.0,
                 mutation_classes=sorted({m["class"] for m in tgt}), mutation_survivors=[m["id"] for m in tgt if not det[m["id"]]],
                 mutation_controls_clean=bool(mu["controls"]["clean"] and mu["controls"]["adapter_static_clean"] and mu["controls"]["ok_mode_probe_clean"]
                                              and not (mu["controls"]["clean_copy"]["static_flagged"] or mu["controls"]["clean_copy"]["dynamic_flagged"]
                                                       or mu["controls"]["noop_edit"]["static_flagged"] or mu["controls"]["noop_edit"]["dynamic_flagged"])), mutation_static_blind_spots=[m["id"] for m in tgt if m.get("static_blind_spot")],
                 mutation_detected_by={m["id"]: m["detected_by"] for m in mu["mutants"]})

    def has(*k):
        return all(x in n for x in k)
    ok = lambda *k: has(*k)  # noqa: E731
    s1 = (n["forbidden_core_branches"] <= th["max_domain_specific_core_branches"] and n["forbidden_core_literals"] == 0
          and n["static_files_scanned"] > 20 and n["scanned_equals_closure"]) if ok("forbidden_core_branches", "static_files_scanned") else None
    s2 = (n["lifecycle_conformity"] >= th["required_generic_lifecycle_coverage"] and all(v >= th["required_generic_lifecycle_coverage"]
          for v in n["action_coverage"].values()) and not any(n["dispatch_outside_generic_set"].values())
          and n["cross_domain"]["handler_object_per_kind_is_single"] and n["cross_domain"]["provenance_key_sets_equal"]
          and n["cross_domain"]["state_sets_equal_or_subset_of_frozen"] and n["provenance_complete"]) if ok("lifecycle_conformity") else None
    s3 = (n["adapter_static_violations"] <= th["max_governance_semantics_in_adapters"] and n["adapter_taint_violations"] == 0
          and n["adapter_taint_known_negative"] and not n["ok_mode_refusals"] and n["engine_owns_idempotency"]
          and n["adapter_calls"] > 0) if ok("adapter_static_violations", "ok_mode_refusals") else None
    s4 = (n["synthetic_unique"] >= minimum and n["synthetic_mismatches"] == 0 and not n["synthetic_engine_edited"]
          and not n["synthetic_dispatch_changed"] and not n["synthetic_unknown_kinds"] and not n["synthetic_id_clash"]
          and n["alias_disagreements"] == 0 and n["alias_definitions"] >= 100 and n["synthetic_replays_identical"]
          and n["synthetic_retries_ok"]) if ok("synthetic_unique") else None
    s5 = (n["mutation_kill_rate"] >= th["required_mutation_kill_rate"] and n["mutation_controls_clean"]
          and {"domain_branch_in_engine", "governance_in_adapter"} <= set(n["mutation_classes"])) if ok("mutation_kill_rate") else None
    r1_parts = []
    if ok("forbidden_core_branches"):
        r1_parts.append(n["forbidden_core_branches"] > 0 or n["forbidden_core_literals"] > 0)
    if ok("alias_disagreements"):
        r1_parts.append(n["alias_disagreements"] > 0)
    if ok("adapter_static_violations"):
        r1_parts.append(n["adapter_static_violations"] > 0 or n["adapter_taint_violations"] > 0 or bool(n["ok_mode_refusals"]))
    r1 = any(r1_parts) if r1_parts else None
    i1 = (any(not (p["read_dispatches"] and p["function_dispatches"] and p["governed_action_executions"] and p["security_authority_decisions"]
                   and p["security_authority_denials"] and p["provenance_records"]) or n["completed_actions"][x] == 0
                for x, p in n["paths"].items())) if ok("paths") else None
    i2 = (n["synthetic_unique"] < minimum) if ok("synthetic_unique") else None
    i3 = (n["suite_failures"] or n["nonconforming_executions"] > 0 or n["synthetic_mismatches"] > 0
          or not n["adapter_taint_known_negative"]) if ok("suite_failures", "synthetic_mismatches", "adapter_taint_known_negative") else None
    v1 = (bool(n["participants_unscanned"]) or bool(n["closure_dynamic_import_sites"]) or bool(n["closure_domain_files"])) if ok("participants_unscanned") else None
    v4 = (bool(n["oracle_forbidden_imports"]) or not n["oracle_sha_matches"]) if ok("oracle_forbidden_imports") else None
    v5 = ((not n["engine_files_clean"]) if ok("engine_files_clean") else False) or ((not n["mutation_controls_clean"]) if ok("mutation_controls_clean") else False)
    pred = {"support_if": sc.rows(SUPPORT, {"S1": s1, "S2": s2, "S3": s3, "S4": s4, "S5": s5}),
            "reject_if": sc.rows(REJECT, {"R1": r1}),
            "inconclusive_if": sc.rows(INCONCLUSIVE, {"I1": i1, "I2": i2, "I3": i3}),
            "invalid_if": sc.rows(INVALID, {"V1": v1, "V2": bool(wrong), "V3": len(ident) > 1, "V4": v4, "V5": v5})}
    return sc.finish(HID, ident[0][3] if ident else None, protocol_valid=not wrong and len(ident) <= 1 and not v1 and not v4 and not v5,
                     complete=not problems, sample_sufficient=(i1 is False and i2 is False and i3 is False),
                     reject_hit=r1 is True, support_hit=all(x is True for x in (s1, s2, s3, s4, s5)), predicates=pred, numbers=n,
                     problems=problems,
                     extra={"protocol": {"freeze_sha256": freeze_hash()}, "evidence_payload_hashes": {f: r["payload_hash"] for f, r in sorted(recs.items())},
                            "evaluator_sha256": sha_file(Path(__file__)), "candidate": (sy or {}).get("candidate"),
                            "interpretation_notes": [
                                "DEVELOPMENT RUN unless the experiment id is exp-h20-001 produced by the orchestrator in an isolated worktree.",
                                "S2 reads '100% registered domain operations' as: every registered ACTION of both domains was executed through the "
                                "generic lifecycle with a conformant history (real domain logic in the suites and the H17 machine; generated bindings in the "
                                "generic sweep), every execution of every workload conforms to the frozen state machine, and every dispatched (kind, op) "
                                "belongs to the frozen kind-keyed set. Registered Functions / policies / reads are reported as dispatched-or-not "
                                "(numbers.not_dispatched_registered), not required.",
                                "S3 includes one declared exception (store.py GitStore._msg, commit-message trailers); numbers.adapter_strict_count_without_exceptions "
                                "is the count when it is not accepted.",
                                "The alias-invariance probe (neutral vs real domain identifiers for the same synthetic definition) is the dynamic twin of the static "
                                "token scan; a domain-name-keyed behaviour that avoids every literal would still show up there.",
                                "Baseline is CONTEXTUAL only (numbers.baseline_contextual): it supports no clause."]})
