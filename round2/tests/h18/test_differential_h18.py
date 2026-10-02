"""RuleBasedStateMachine (PRIMARY Hypothesis role): the REAL Engine over a Git repo and the independent oracle, step by step."""
import copy
import subprocess

import hypothesis.strategies as st
from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, precondition, rule

from eoo_exp.util import ROOT, load_oracle
from eoo_h18.fixture import SUBJECTS, facts_for
from eoo_h18.gen import classify
from eoo_h18.rig import EooRig

W = load_oracle("h18", "world")
KNOWN_GAPS = {"supersede_self", "new_version_chain"}  # pinned in test_findings_h18.py
_RIG = []


def rig():
    if not _RIG:
        from domains.project.logic.freeze import git_blob_reader
        head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        _RIG.append(EooRig(reader=git_blob_reader(head)))
    return _RIG[0]


class LifecycleMachine(RuleBasedStateMachine):
    @initialize(subject=st.sampled_from(SUBJECTS), phase0=st.sampled_from(("DRAFT", "PREREGISTERED", "RUNNING")),
                pins=st.lists(st.sampled_from(("good", "good", "version", "env", "commit", "hash")), min_size=1, max_size=4),
                tags=st.lists(st.sampled_from("ssrn"), min_size=4, max_size=4), dec=st.sampled_from(("because", "")),
                missing=st.sampled_from((None, "rival", "falsifier", "evaluator")))
    def setup(self, subject, phase0, pins, tags, dec, missing):
        r = rig()
        complete = {k: not (phase0 == "DRAFT" and k == missing) for k in W.CORE_LINKS}
        self.case = {"subject": subject, "phase0": phase0, "complete": complete,
                    "evidence": [{"id": f"ev-gen-{i}", "pin": p, "tag": tags[i]} for i, p in enumerate(pins)],
                    "decision": {"id": "dec-gen", "rationale": dec}, "components": [{"id": "cmp-gen-0"}],
                    "facts": facts_for(r.base_ops, subject, r.commit0), "ops": []}
        self.ref = r.open_case(self.case, f"sm-{r.tick}")
        self.w, self.i, self.dead = W.World(copy.deepcopy(self.case)), 0, False

    def do(self, op):
        pre = copy.deepcopy(self.w)
        legal, want = self.w.step(op)
        self.case["ops"].append(op)
        row = rig().step(self.case, self.ref, self.i, op)
        self.i += 1
        gap = bool(KNOWN_GAPS & set(classify(pre, op, legal)))
        assert row["exception"] is None, row
        if legal and not row["accepted"]:
            assert gap, ("legal op refused outside the pinned gaps", op, row["state"], row["denied_gate"])
            self.w, want = pre, pre.summary()
        elif not legal and (row["accepted"] or row["committed"]):
            assert gap, ("ILLEGAL op reached Git", op, row["state"])
            self.dead = True
            return
        assert row["summary"] == want, (op, {k: (want[k], row["summary"][k]) for k in want if want[k] != row["summary"][k]})
        if row["accepted"]:
            assert row["new_commits"] == 1 and all(row["trace"].values()) and row["engine_store_unchanged"] and row["effects_all_git"]
        else:
            assert row["new_commits"] == 0

    @precondition(lambda self: self.dead)
    @rule()
    def idle_after_a_pinned_gap(self):
        """After a pinned gap let an illegal op reach Git the oracle world no longer matches the repo: nothing more to compare."""

    @precondition(lambda self: not self.dead)
    @rule(fv=st.sampled_from(("fh-1", "fh-2", "")))
    def preregister(self, fv):
        self.do({"k": "preregister", "freeze": "junk" if fv else "blank", "freeze_value": fv})

    @precondition(lambda self: not self.dead)
    @rule(v=st.integers(100, 199))
    def edit_threshold(self, v):
        self.do({"k": "edit_threshold", "value": v if v != self.case["facts"]["threshold_value"] else v + 1})

    @precondition(lambda self: not self.dead)
    @rule(exp=st.sampled_from(("base", "latest")))
    def new_version(self, exp):
        self.do({"k": "new_version", "exp": exp})

    @precondition(lambda self: not self.dead)
    @rule()
    def start(self):
        self.do({"k": "start"})

    @precondition(lambda self: not self.dead)
    @rule(i=st.integers(0, 3))
    def attach(self, i):
        self.do({"k": "attach", "ev": self.case["evidence"][i % len(self.case["evidence"])]["id"]})

    @precondition(lambda self: not self.dead)
    @rule()
    def evaluate(self):
        self.do({"k": "evaluate"})

    @precondition(lambda self: not self.dead)
    @rule(v=st.sampled_from(("SUPPORTED", "REJECTED")))
    def forced_verdict(self, v):
        self.do({"k": "forced_verdict", "value": v if v != W.expected_verdict(self.w.tags()) else "INVALID"})

    @precondition(lambda self: not self.dead)
    @rule(succ=st.sampled_from(("other", "other", "self")))
    def supersede(self, succ):
        self.do({"k": "supersede", "succ": succ})

    @precondition(lambda self: not self.dead)
    @rule(c=st.sampled_from(("cmp-gen-0", "cmp-legacy-draft", "cmp-hdd")))
    def flag(self, c):
        self.do({"k": "flag", "cmp": c})

    @precondition(lambda self: not self.dead)
    @rule()
    def decision(self):
        self.do({"k": "decision"})

    @precondition(lambda self: not self.dead)
    @rule(claim=st.sampled_from(("a claim", "", "other claim")))
    def create(self, claim):
        self.do({"k": "create", "claim": claim})


TestLifecycle = LifecycleMachine.TestCase
TestLifecycle.settings = settings(max_examples=70, stateful_step_count=9, deadline=None, database=None,
                                  suppress_health_check=list(__import__("hypothesis").HealthCheck))
