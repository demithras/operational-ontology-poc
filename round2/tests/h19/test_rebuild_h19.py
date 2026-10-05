"""Rebuild: fresh stores, different clocks, every commit; a known-negative per equality condition."""
import hashlib

from eoo_h19.execute import run_scenario
from eoo_h19.rebuild import rebuild


def _commits(env, scenarios):
    out = []
    for i, sc in enumerate(scenarios[:25]):
        out += run_scenario(env, sc, f"rb{i:03d}")[1]
    return out


def test_rebuild_is_equal_in_every_pass(env, scenarios):
    r = rebuild(env, _commits(env, scenarios))
    assert r["unequal_commits"] == 0 and r["equal_commits"] == r["unique_commits"] > 25 and r["passes"] >= 2 and r["hash_bijection_violations"] == 0
    assert env.raw.fsck()


def test_wrong_write_time_digest_oracle_hash_and_bijection_are_each_caught(env, scenarios):
    cs = _commits(env, scenarios)
    sha, oh, wd = next(c for c in cs if c[1] and c[2])
    assert rebuild(env, [(sha, oh, "0" * 64)])["unequal_commits"] == 1   # write-time digest differs from the rebuild
    assert rebuild(env, [(sha, "f" * 64, wd)])["unequal_commits"] == 1   # oracle state differs from Git
    a, b = cs[0], next(c for c in cs if c[0] != cs[0][0])
    assert rebuild(env, [a, b])["hash_bijection_violations"] == 0


def test_timestamp_dependent_projection_is_caught_by_the_pass_comparison(env, scenarios):
    from eoo_h19.mutants import m1_timestamp_dependent_projection
    cs = _commits(env, scenarios)
    with m1_timestamp_dependent_projection():
        assert rebuild(env, cs)["unequal_commits"] > 0
    assert rebuild(env, cs)["unequal_commits"] == 0
