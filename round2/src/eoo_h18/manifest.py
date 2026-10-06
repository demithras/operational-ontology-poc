"""Attribution manifests for the bespoke-surface metric (ENGINE_PREREG H18 bespoke_surface_metric).

Every handwritten line/resource of both variants is assigned to exactly one class. 'X' classes are mandatory EOO surface
that has no file-only counterpart (authority rules, outcome predicates): counted in the headline total (conservative toward
the baseline) and reported separately for the sensitivity bound. 'EXCL:*' classes are NOT counted for either variant; the reason
is part of the evidence.
"""
from __future__ import annotations

P, IR, PATCH = "domains/project/", "domains/project/ir.v2.json", "src/eoo_h18/tc_patch.json"
LG = P + "logic/"
H19_CONSTRAINTS = ["rebuild-reproduces-state-hash", "durable-actions-are-git-changes", "no-silent-stale-write",
                   "conflicts-surface-explicitly", "ephemeral-state-marked", "historical-binding-preserved"]
H19_POLICIES = ["stale_write_rejected", "conflicting_change_denied_with_conflict", "ephemeral_state_never_canonical", "historical_binding_preserved"]


def eoo() -> list[dict]:
    m: list[dict] = []
    t = "src/eoo_h18/tc_eoo.py"
    # ---- TC3 then TC2 (patch + logic), harness plumbing excluded ----
    m += [{"cls": "TC3X", "py": t, "sym": "_replication_outcome"}, {"cls": "TC3X", "py": t, "re": r"outcome_predicate|_replication_outcome"},
          {"cls": "TC3", "py": t, "sym": "_evaluated"}, {"cls": "TC3", "py": t, "sym": "_replication_rows"},
          {"cls": "TC3", "py": t, "re": r"count_replications|experiment is EVALUATED|register_replication#1"},
          {"cls": "TC2", "py": t, "sym": "dependency_ops"}, {"cls": "TC2", "py": t, "sym": "_latest_verdict"},
          {"cls": "TC2", "py": t, "sym": "evidence_of_verdict"}, {"cls": "TC2", "py": t, "sym": "blocked_hypotheses"},
          {"cls": "TC2", "py": t, "re": r"evidence_of_verdict:v1|blocked_hypotheses:v1"}, {"cls": "EXCL:harness_plumbing", "py": t, "all": True},
          {"cls": "TC3", "ir": PATCH, "kind": "object_types", "ids": ["Replication"]}, {"cls": "TC3", "ir": PATCH, "kind": "link_types", "ids": ["REPLICATES"]},
          {"cls": "TC3", "ir": PATCH, "kind": "functions", "ids": ["count_replications"]}, {"cls": "TC3", "ir": PATCH, "kind": "actions", "ids": ["register_replication"]},
          {"cls": "TC3X", "ir": PATCH, "kind": "authority_rules", "ids": ["researcher-register-replication"]},
          {"cls": "TC2", "ir": PATCH, "kind": "link_types", "ids": ["DEPENDS_ON"]},
          {"cls": "TC2", "ir": PATCH, "kind": "functions", "ids": ["evidence_of_verdict", "blocked_hypotheses"]}]
    # ---- TC1 python: exclusions first (docs/05 = H19 properties, freeze computation, shared tools, legacy), then the rest ----
    m += [{"cls": "EXCL:h19_git_authority", "py": LG + "constraints.py", "sym": f"make.{s}"} for s in
          ("rebuild_hash", "durable_are_git", "no_stale", "conflicts_explicit", "ephemeral_marked", "history_preserved")]
    m += [{"cls": "EXCL:h19_git_authority", "py": LG + "constraints.py", "sym": "state_hash"}, {"cls": "EXCL:h19_git_authority", "py": LG + "constraints.py", "sym": "STATE_TYPES"},
          {"cls": "EXCL:h19_git_authority", "py": LG + "constraints.py",
           "re": r"constraint:(rebuild-reproduces|durable-actions|no-silent|conflicts-surface|ephemeral-state|historical-binding)|fields_of|for a in ir\[\"actions\"\]|types = \{t"}]
    m += [{"cls": "EXCL:h19_git_authority", "py": LG + "policies.py", "sym": f"make.{s}"} for s in ("stale_write", "conflicting_change", "ephemeral", "historical_rebinding")]
    m += [{"cls": "EXCL:h19_git_authority", "py": LG + "policies.py", "re": r"docs/05#"},
          {"cls": "EXCL:freeze_hash_computation", "py": LG + "freeze.py", "all": True},
          {"cls": "EXCL:freeze_hash_computation", "py": LG + "functions.py", "re": r"freeze_protocol|canonical_state_hash|import state_hash"},
          {"cls": "EXCL:shared_evaluator_adapter", "py": P + "evaluators.py", "all": True},
          {"cls": "EXCL:shared_seed_loader", "py": P + "seed_from_repo.py", "all": True},
          {"cls": "EXCL:legacy_p4b_fake_git", "py": P + "projection.py", "all": True}, {"cls": "EXCL:legacy_p4b_fake_git", "py": P + "adapters/git_fake.py", "all": True},
          {"cls": "TC1X", "py": LG + "actions.py", "sym": "_outcome"}, {"cls": "TC1X", "py": LG + "actions.py", "sym": "_GIT"},
          {"cls": "TC1X", "py": LG + "selectors.py", "all": True}, {"cls": "TC1X", "py": LG + "actions.py", "re": r"outcome_predicate"}]
    m += [{"cls": "TC1", "py": f, "all": True} for f in (LG + "actions.py", LG + "constraints.py", LG + "policies.py", LG + "functions.py", LG + "payloads.py",
                                                          LG + "facts.py", LG + "derive.py", LG + "lifecycle.py", LG + "__init__.py", P + "pack.py")]
    # ---- TC1 declarative config (IR v2) ----
    keep = lambda kind, drop: {"cls": "TC1", "ir": IR, "kind": kind, "ids": drop}  # noqa: E731
    m += [{"cls": "EXCL:h19_git_authority", "ir": IR, "kind": "constraints", "ids": H19_CONSTRAINTS}, {"cls": "EXCL:h19_git_authority", "ir": IR, "kind": "policies", "ids": H19_POLICIES},
          {"cls": "EXCL:freeze_hash_computation", "ir": IR, "kind": "functions", "ids": ["compute_freeze_hash", "canonical_state_hash"]},
          {"cls": "EXCL:unused_observation_type", "ir": IR, "kind": "observation_types", "ids": ["TestRunObserved"]},
          {"cls": "TC1X", "ir": IR, "kind": "authority_rules", "all": True}]
    m += [{"cls": "TC1", "ir": IR, "kind": k, "all": True} for k in ("object_types", "link_types", "interfaces", "actions", "policies", "constraints", "functions", "observation_types")]
    return m


def baseline() -> list[dict]:
    B = "baselines/h18_fileonly/"
    S = B + "schemas/"
    return ([{"cls": "TC3", "py": B + "replication.py", "all": True}, {"cls": "TC3", "py": B + "ci.py", "re": r"replication"}, {"cls": "TC3", "json": S + "replication.schema.json"},
             {"cls": "TC2", "py": B + "queries.py", "all": True}]
            + [{"cls": "TC1", "py": B + f, "all": True} for f in ("actions.py", "rules.py", "derive.py")]
            + [{"cls": "TC1", "json": S + f"{n}.schema.json"} for n in ("hypothesis", "experiment", "evidence", "verdict", "threshold", "component", "decision", "contractversion")]
            + [{"cls": "RECURRING", "py": B + f, "all": True} for f in ("repo.py", "ci.py", "__init__.py")])


def recurring_eoo_files() -> list[str]:
    import glob
    from eoo_exp.util import ROOT
    return sorted(str(p.relative_to(ROOT)) for pat in ("src/eoo_engine/*.py", "src/eoo_engine_git/*.py", "domains/_pack.py", "domains/_support.py") for p in ROOT.glob(pat))
