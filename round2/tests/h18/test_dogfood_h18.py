"""The real H15 lifecycle through generic Actions into a temp Git repo, checked with the real git CLI."""
import pytest

from eoo_h18.dogfood import run_dogfood


@pytest.fixture(scope="module")
def dog(reader, tmp_path_factory):
    return run_dogfood(reader, tmp_path_factory.mktemp("dog"))


def test_every_step_behaves_as_expected_and_hostile_steps_are_blocked(dog):
    assert [s["step"] for s in dog["steps"] if s["accepted"] != s["expected_accept"]] == []
    blocked = {s["step"]: s["gate"] for s in dog["steps"] if not s["accepted"]}
    assert blocked == {"hostile_post_freeze_threshold_edit": "preconditions", "hostile_forced_verdict_input": "inputs"}
    assert all(not s["head_moved"] for s in dog["steps"] if not s["accepted"])


def test_derived_verdict_equals_the_committed_authoritative_verdict(dog):
    assert dog["reproducible"] and dog["derived_verdicts"] == [("verdict-H15-1", dog["committed_verdict"])]
    assert dog["phase_final"] == "SUPERSEDED"


def test_git_cli_sees_one_traced_commit_per_accepted_action(dog):
    c = dog["git_cli"]
    assert c["fsck"] and c["history_agrees"] and c["accepted_with_matching_commit_trailers"] == c["accepted_actions"] == 11
    assert c["cli_commits_on_branch"] == c["expected_commits"] == 13


def test_real_repository_is_never_written(dog):
    import subprocess
    from eoo_exp.util import REPO
    assert not dog["repo"].startswith(str(REPO))
    assert subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "round2/protocol", "round2/hypotheses", "round2/experiments/h15"],
                          capture_output=True, text=True).stdout == ""
