"""Hypothesis-driven state machine: the real GitStore and the oracle DAG move in lock step; scenarios from the experiment generator."""
import itertools

from hypothesis import given, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from eoo_engine_git import ConflictError, RowRejected
from eoo_h19.execute import lost_updates, run_scenario
from eoo_h19.gen import _change, gen_scenario, scenario_hash
from eoo_h19.oracle import M
from eoo_h19.seed import change_to_rows
from eoo_h19.storelevel import failures, run_corpus

COUNTER = itertools.count()


@given(st.randoms(use_true_random=False))
def test_generated_scenarios_agree_with_the_oracle_in_every_check(env, rnd):
    sc = gen_scenario(rnd)
    row, _ = run_scenario(env, sc, f"hy{next(COUNTER):06d}")
    assert not row["exc"]
    for w in row["w"]:
        assert w["a"] == 1 and w["L"] == 0 and w["ref_ok"] == 1 and w["D"] == 1 and w.get("r", "eq") == "eq"
    assert all(b["pinned"] for b in row["binds"])


class GitVsOracle(RuleBasedStateMachine):
    """Writes from head or from a stale commit, in either merge mode: Git's accepted/conflict/rejected outcome and head state == the oracle's."""

    @initialize()
    def start(self):
        from eoo_h19.seed import Env
        self.env = Env()
        self.ref, self.cs, self.dag = f"refs/heads/sm-{next(COUNTER)}", [self.env.root], M.Dag(self.env.root_state)
        self.env.store.repo.set_ref(self.ref, self.env.root)

    def teardown(self):
        self.env.close()

    @rule(rnd=st.randoms(use_true_random=False), lag=st.integers(0, 3), never=st.booleans())
    def write(self, rnd, lag, never):
        change, mode = [_change(rnd) for _ in range(rnd.randint(1, 2))], "never" if never else "compatible"
        base_i = max(0, len(self.cs) - 1 - lag)
        out = self.dag.write(base_i, change, mode)
        try:
            rec = self.env.store.commit_rows(rows=change_to_rows(change), base=self.cs[base_i], writer="w", meta={"execution": "x", "action": "a", "effects": []},
                                             ref=self.ref, merge_mode=mode, message="m\n")
            got = "ok"
            self.cs.append(rec["sha"])
        except ConflictError:
            got = "conflict"
        except RowRejected:
            got = "rejected"
        assert got == out.kind
        if got != "ok" and out.kind == "ok":
            self.dag.commits.pop()

    @invariant()
    def head_is_the_oracle_state(self):
        assert self.env.raw.head(self.ref) == self.cs[-1]
        assert M.state_hash(self.env.raw.logical(self.cs[-1])) == self.dag.hash(self.dag.head)


TestGitVsOracle = GitVsOracle.TestCase


def test_lost_update_checker_known_positive_and_known_negative():
    prev = {"e": {"a": 1, "b": 2}}
    base = {"e": {"a": 0, "b": 2}}
    change = [{"e": "e", "props": {"a": 1}}]
    assert lost_updates(prev, {"e": {"a": 1, "b": 2}}, change, base) == []
    assert lost_updates(prev, {"e": {"a": 0, "b": 2}}, change, base) == [("e", "a")]  # the writer's change vanished
    assert lost_updates(prev, {"e": {"a": 1, "b": 9}}, change, base) == [("e", "b")]  # someone else's value changed under a write that did not touch it
    assert lost_updates(prev, {}, change, base) and lost_updates({"e": {"a": 1}}, {"e": {"a": 1}}, [{"e": "z", "props": {"q": 1}}], {}) == [("z", "*")]
    assert lost_updates({"e": {"a": 5}}, {"e": {"a": 5}}, [{"e": "e", "props": {"a": 0}}], {"e": {"a": 0}}) == []  # a value equal to the writer's own base is not a change


def test_control_corpus_is_clean_and_has_every_class(scenarios):
    res = run_corpus(scenarios, batch=60, log=lambda m: None)
    assert not any(failures(res).values()), failures(res)
    from eoo_h19.storelevel import tally
    t = tally(res)
    assert t["conflict"] and t["rejected"] and t["stale_writes"] and t["replays"] == t["conflict"] and t["binds_with_later_change"]
    assert all(t["classes"].get(c, 0) for c in ("compatible_concurrent", "conflicting_concurrent", "stale_base", "rebuild_same_commit", "historical_binding_after_change"))


def test_generator_is_deterministic_and_unique():
    from eoo_h19.gen import generate
    a, ia = generate(42, 200)
    b, ib = generate(42, 200)
    assert a == b and ia == ib and len({scenario_hash(s) for s in a}) == 200
