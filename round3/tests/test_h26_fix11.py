"""G3 fix11: equal world_log schedules across a pair (G3-E32b); anchor teardown."""
import pytest

from r3_harness.h26 import gen_pair, sim


def _check(p):
    ops, auth, _ = gen_pair.load(p["domain"])
    base = sim.apply_changes(sim.empty(), [c for b in sim.seed_batches(ops) for c in b])
    s = [gen_pair.row_schedule(base, d, ops, p["auth"]) for d in p["w"]]
    assert s[0] == s[1], p["id"]


def test_p2620_4955_has_equal_schedules():
    p, st = gen_pair.draw(2620, 4955)
    assert p is not None
    _check(p)


def test_noop_link_is_not_a_row():
    base = sim.apply_changes(sim.empty(), [{"op": "create", "type": "T", "key": "a", "props": {}}])
    ch = {"op": "link", "link_type": "L", "src": "T:a", "dst": "T:a"}
    assert sim.change_rows(base, [ch, ch]) == 1


@pytest.mark.parametrize("domain", gen_pair.DOMAINS)
def test_property_equal_schedules_and_low_docs(domain):
    n = 0
    for i in range(1200):
        if n >= 300:
            break
        if gen_pair.DOMAINS[i % 2] != domain:
            continue
        p, _ = gen_pair.draw(2620, i)
        if p is None:
            continue
        n += 1
        _check(p)
    assert n == 300
