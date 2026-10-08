"""G3 fix2: an OWN decision's effect_digest covers the full world_log rows (E-4); a hidden property in `data.props`
makes it non-low (G3-E21: own decisions are not exempt), so the honest oracle-backed fake must not diverge across worlds."""
from r3_harness.h26 import analyze, gen_pair, observe
from r3_oracle import disclosure_prov as P
from r3_shared.disclosure import marker
from tests.fakes import fake_h26


class _LV:
    def __init__(self, objects, observer="u1"):
        self.objects, self.observer, self.links, self.prov = objects, observer, set(), {}
        self.facts = type('F', (), {'edges': []})()


def _dec(props):
    row = {"seq": 4, "tx": 1, "tag": "effect", "tick": 1, "writer": "w", "kind": "update", "ref": "Component:c",
           "data": {"patch": {"flag": True}, "props": props, "version": 2}}
    sc = {k: "x" for k in P.DECISION_KEYS}
    return {"id": "d", "rid": "d", "subject": "u1", "on_behalf_of": None, "resources": [], "args_refs": [], "args_scalar_free": True,
            "scalars": sc, "effects": [{"kind": "update", "ref": "Component:c", "changes": {"flag": [False, True]}}],
            "effect_rows": [row], "edge_path": []}


def test_own_decision_effect_digest_redacted_when_rows_carry_hidden_props():
    d = _dec({"id": "c", "flag": True, "path": "secret"})
    assert not P._digest_low(_LV({"Component:c": {"id": "c", "flag": True}}), d, "effect")
    assert P.expected_decision(_LV({"Component:c": {"id": "c", "flag": True}}), d)["effect_digest"] == marker("digest")


def test_own_decision_effect_digest_true_when_all_row_props_low():
    d = _dec({"id": "c", "flag": True})
    assert P._digest_low(_LV({"Component:c": {"id": "c", "flag": True}}), d, "effect")


def test_honest_fake_pair_p1_27_does_not_diverge():
    """Repro of the c7a3338 REJECTED: seed 1, pair p1-27 (project), hidden `path` leaked via own effect_digest."""
    v = fake_h26.load("fake-honest", ())
    for idx in range(900):
        p, _ = gen_pair.draw(1, idx, aa=False)
        if p is not None and p["id"] == "p1-27":
            row = analyze.pair_row(p, [observe.run_world(v, p, w) for w in (0, 1)])
            assert row["divergences"] == []
            return
    raise AssertionError("pair p1-27 not drawn")
