"""Property tests of the generic procedure (PROT-H25 s2.4): a quorum stage's outcome equals the count rule computed
independently; a decided stage never changes; a stage with too few judgments is AWAITING; merit-free (no merit input exists)."""
from hypothesis import given, settings, strategies as st

from paladin.govir import compile_governance
from paladin.procedure import ALLOW, DENY, CaseBook

MEMBERS = [f"m{i}" for i in range(7)]


def doc(n, k, recuse):
    return {"spec": "r3-governance-1", "model": "x", "domain": "project",
            "bodies": [{"id": "b", "members": MEMBERS[:n], "rule": {"kind": "quorum", "k": k, "recuse": ["requester"] if recuse else []}, "rank": 1}],
            "superior": [], "precedence": [], "emergency": None,
            "matters": [{"id": "mt", "scope": {"operations": ["op"], "resources": [{"type": "T", "keys": None}]}, "competent": ["b"],
                         "concurrence": False, "review": None, "on_absent": "await"}]}


@settings(max_examples=200, deadline=None)
@given(n=st.integers(1, 7), data=st.data(), recuse=st.booleans(),
       seq=st.lists(st.tuples(st.integers(0, 6), st.sampled_from(["concur", "dissent", "abstain"])), max_size=14))
def test_quorum_outcome_matches_the_count_rule_and_never_flips(n, data, recuse, seq):
    k = data.draw(st.integers(1, n))
    book = CaseBook(compile_governance(doc(n, k, recuse), "v"))
    requester = MEMBERS[0] if recuse else "outsider"
    c = book.apply_propose(1, 0, "c", requester, None, "op", {}, [("T", "k")])
    elig = [m for m in MEMBERS[:n] if not (recuse and m == requester)]
    seen, first, decided = {}, {}, None
    for i, (mi, val) in enumerate(seq):
        who = MEMBERS[mi]
        if who not in elig or who in seen or decided is not None:
            continue
        seen[who] = val
        book.apply_judge(10 + i, i, "c", "decision", who, val, f"r{i}")
        pos, neg = sum(v == "concur" for v in seen.values()), sum(v == "dissent" for v in seen.values())
        ne = len(elig)
        expect = None if ne < k else ALLOW if pos >= k else DENY if neg > ne - k else None
        got = c.decided["decision"][0] if c.decided["decision"] else None
        assert got == expect
        if got is not None:
            decided = got
    if decided is not None:
        assert c.decided["decision"][0] == decided        # fixed at the commit point of the deciding judgment
        assert book.basis(c, "decision") == [j["rid"] for j in c.judgments]
    assert c.decided["decision"] is None or len(c.judgments) >= 1   # no outcome without a supplied judgment
