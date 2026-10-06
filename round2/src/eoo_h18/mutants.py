"""Registered mutations of the Project Ontology logic / store. Each one removes EVERY layer that enforces one rule
(precondition + policy + constraint [+ payload]) so the rule is genuinely off; control (no mutation) must stay clean."""
from __future__ import annotations

ALWAYS = lambda ctx: True  # noqa: E731
NEVER = lambda ctx: False  # noqa: E731


def _only(bindings, kind, key, action, when_action):
    """Replace ``kind:key`` by ``when_action`` for the named action only; the original everywhere else."""
    orig = bindings.get(kind, key)
    bindings.bind(kind, key, lambda ctx: when_action(ctx) if ctx.action == action else orig(ctx))


def m1_threshold_edit_after_freeze(b):
    _only(b, "precondition", "phase == DRAFT", "edit_threshold", ALWAYS)
    b.bind("policy", "docs/04#threshold-immutable", NEVER)
    b.bind("constraint", "constraint:threshold-immutable-after-preregistration:v1", ALWAYS)


def m2_verdict_without_evidence(b):
    pay = b.get("payload", "evaluate_hypothesis#0")  # the verdict row is written by the payload, which derives it directly
    b.bind("payload", "evaluate_hypothesis#0", lambda ctx: {**pay(ctx), "value": "SUPPORTED"} if not _count(ctx.view, ctx.inputs["hypothesis"]) else pay(ctx))
    orig = b.get("function", "src/hdd/verdict.py:evaluate_common")
    b.bind("function", "src/hdd/verdict.py:evaluate_common",
           lambda view, a: "SUPPORTED" if not _count(view, a["hypothesis"]) else orig(view, a))
    b.bind("precondition", "evidence_count(hypothesis) >= 1 or an explicit INCONCLUSIVE/INVALID reason is given", ALWAYS)
    b.bind("policy", "docs/04#evaluated-needs-evidence", NEVER)
    for c in ("constraint:evaluated-requires-evidence-or-reason:v1", "constraint:supported-needs-evidence:v1", "constraint:verdict-machine-derived:v1"):
        b.bind("constraint", c, ALWAYS)


def _count(view, hid) -> int:
    return len(view.follow("SUPPORTS_OR_REFUTES", "Hypothesis", hid, "in"))


def m4_unpinned_evidence_accepted(b):
    b.bind("precondition", "evidence is pinned to experiment version, commit and environment", ALWAYS)
    b.bind("policy", "docs/04#evidence-binding", NEVER)
    b.bind("constraint", "constraint:evidence-bound-to-version-commit-environment:v1", ALWAYS)


def m5_supersede_out_of_order(b):
    _only(b, "precondition", "phase == EVALUATED", "supersede_hypothesis", ALWAYS)
    b.bind("policy", "docs/04#lifecycle-order", ALWAYS)  # an 'allow' policy: not applying would default-deny
    b.bind("constraint", "constraint:lifecycle-order:v1", ALWAYS)


# id, class, target (a preregistered mutation), mutate hook or None, store provenance flag, expected signal
REGISTRY = [
    {"id": "M1_allow_post_freeze_threshold_edit", "class": "lifecycle_rule", "target": True, "mutate": m1_threshold_edit_after_freeze, "provenance": True,
     "expect": {"kind": "illegal_accepted", "op": "edit_threshold"}},
    {"id": "M2_allow_verdict_without_evidence", "class": "lifecycle_rule", "target": True, "mutate": m2_verdict_without_evidence, "provenance": True,
     "expect": {"kind": "summary_mismatch", "op": "evaluate", "field": "verdicts"}},
    {"id": "M3_detach_commit_provenance", "class": "git_traceability", "target": True, "mutate": None, "provenance": False,
     "expect": {"kind": "trace_failure"}},
    {"id": "M4_allow_unpinned_evidence", "class": "lifecycle_rule", "target": False, "mutate": m4_unpinned_evidence_accepted, "provenance": True,
     "expect": {"kind": "illegal_accepted", "op": "attach"}},
    {"id": "M5_allow_supersede_out_of_order", "class": "lifecycle_rule", "target": False, "mutate": m5_supersede_out_of_order, "provenance": True,
     "expect": {"kind": "illegal_accepted", "op": "supersede", "class_tag": "supersede_non_evaluated"}},
]
