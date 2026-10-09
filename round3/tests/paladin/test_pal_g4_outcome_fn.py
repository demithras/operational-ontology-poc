"""P1f-6 rule coverage of Paladin's own outcome function over scripted observer snapshots (rules N, U, D1, D2, D3, S, F, W), with a
hand-derived expectation per row (not computed by the code under test) and a coverage set difference."""
from paladin.extoutcome import outcome_state
from r3_shared.extobs import AudRow, EffRow, ObsSnapshot

I = {"operation": "expedite", "target": "po:P", "payload_digest": "d" * 64, "correlation": "r#0", "expiry": 8,
     "idempotency": "at_most_once", "observability": "full"}
EF = lambda seq, **kw: EffRow(seq, 1, "ERP", kw.get("op", "expedite"), kw.get("t", "po:P"), kw.get("d", "d" * 64), "c", kw.get("cor", "r#0"), "a")  # noqa: E731
AU = lambda seq, outcome="applied", reason="", **kw: AudRow(seq, 1, "ERP", kw.get("op", "expedite"), kw.get("t", "po:P"),  # noqa: E731
                                                          kw.get("d", "d" * 64), "c", kw.get("cor", "r#0"), "a", outcome, reason)
P = lambda state="PENDING", ev=(): {"state": state, "confidence": "full", "evidence": list(ev)}  # noqa: E731
S = lambda eff=(), aud=(), ct=5: ObsSnapshot(ct, list(eff), list(aud), ct)  # noqa: E731

# (rule, intent override, snapshot, previous, expected state, expected evidence)
CASES = [
    ("N", {"observability": "none"}, S([EF(1)]), P(), "UNKNOWN", []),
    ("N", {"observability": "none"}, None, P("RECONCILED_SUCCESS"), "UNKNOWN", []),
    ("U", {}, None, P(), "UNKNOWN", []),
    ("U", {}, None, P("RECONCILED_SUCCESS", [3]), "RECONCILED_SUCCESS", [3]),
    ("U", {}, None, P("DIVERGED", [4]), "DIVERGED", [4]),
    ("D1", {}, S([EF(1)], [AU(1)]), P("DIVERGED", [9]), "DIVERGED", [1]),
    ("D2", {}, S([EF(1, t="po:X")], [AU(1, t="po:X")]), P(), "DIVERGED", [1]),
    ("D2", {}, S([], [AU(2, "refused", "target_mismatch", t="po:X")]), P(), "DIVERGED", [2]),
    ("D2", {}, S([EF(1)], [AU(1), AU(2, "refused", "payload_mismatch", d="e" * 64)]), P(), "DIVERGED", [1, 2]),
    ("D3", {}, S([EF(1), EF(2)], [AU(1), AU(2)]), P(), "DIVERGED", [1, 2]),
    ("D3", {"idempotency": "exactly_once_required"}, S([EF(1), EF(2)]), P(), "DIVERGED", [1, 2]),
    ("S", {}, S([EF(1)], [AU(1), AU(2, "refused", "uses_exhausted")]), P(), "RECONCILED_SUCCESS", [1, 2]),
    ("S", {"idempotency": "idempotent_set"}, S([EF(1), EF(2)]), P(), "RECONCILED_SUCCESS", [1, 2]),
    ("S", {"observability": "effects_only"}, S([EF(1)]), P(), "RECONCILED_SUCCESS", [1]),
    ("S", {}, S([EF(1, cor="other#0")]), P(), "PENDING", []),                       # another request's row is not evidence
    ("F", {}, S([], [AU(1, "refused", "expired")], ct=9), P(), "RECONCILED_FAILED", [1]),
    ("F", {}, S([], [], ct=9), P(), "RECONCILED_FAILED", []),
    ("W", {}, S([], [], ct=8), P(), "PENDING", []),                                  # complete_through == expiry is not past it
    ("W", {}, S([], [AU(1, "refused", "uses_exhausted")], ct=3), P(), "PENDING", [1]),
]


def test_every_rule_row_matches_its_hand_derived_expectation():
    for rule, over, snap, prev, state, ev in CASES:
        got = outcome_state({**I, **over}, snap, prev)
        assert (got["state"], got["evidence"]) == (state, ev), (rule, over)
        assert got["confidence"] == ("low" if over.get("observability") in ("none", "effects_only") else "full")


def test_rule_coverage_set_difference():
    assert {c[0] for c in CASES} == {"N", "U", "D1", "D2", "D3", "S", "F", "W"}


def test_precedence_pairs_follow_the_frozen_order():
    both = S([EF(1, t="po:X")], [], ct=99)                                           # D2 beats S and F
    assert outcome_state(I, both, P())["state"] == "DIVERGED"
    assert outcome_state(I, None, P("DIVERGED", [1]))["state"] == "DIVERGED"            # U before D1 keeps a final state either way
    assert outcome_state({**I, "observability": "none"}, None, P("DIVERGED"))["state"] == "UNKNOWN"   # N before U and D1
    assert outcome_state(I, S([EF(1), EF(2)], ct=99), P("RECONCILED_SUCCESS"))["state"] == "DIVERGED"  # success can only go to DIVERGED


def test_monotone_over_a_growing_observer_view():
    """Along snapshots that only GROW (more rows, later complete_through) every step is an allowed transition. Frozen-text gap
    (reported, not chosen): P1f-6 read literally can leave SUCCESS for PENDING when a LATER read withholds rows (lagging fault with a
    larger k, or a smaller watermark); the transitions sentence assumes monotone views."""
    from r3_shared.outcome import allowed_transition
    chain = [S(ct=2), S([EF(1)], ct=3), S([EF(1)], [AU(1)], ct=9), S([EF(1), EF(2)], [AU(1), AU(2)], ct=9),
             S([EF(1), EF(2), EF(3, t="po:X")], [AU(1), AU(2)], ct=10)]
    for start in ("PENDING", "UNKNOWN"):
        prev, trail = P(start), [start]
        for snap in chain:
            prev = outcome_state(I, snap, prev)
            trail.append(prev["state"])
        assert trail == [start, "PENDING", "RECONCILED_SUCCESS", "RECONCILED_SUCCESS", "DIVERGED", "DIVERGED"], trail
        assert all(allowed_transition(a, b) for a, b in zip(trail, trail[1:]))


def test_negative_literal_function_regresses_on_a_withdrawn_view():
    got = outcome_state(I, S(ct=3), P("RECONCILED_SUCCESS", [1]))["state"]   # documents the gap above; guarded by the oracle's order
    assert got == "PENDING"
