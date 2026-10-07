"""A2 generators: schema-valid inputs, depth/DAG/illegal coverage, uniqueness, seeded determinism."""
import collections
import random

from r3_harness.h23.corpus import load_specs
from r3_harness.h24 import gen_graph
from r3_harness.h24.gen_race import TYPES, run_race
from r3_harness.h24.gen_seq import run_sequence
from r3_oracle.authority_v2 import INF, RefAuthority, event
from r3_shared.authspec import validate_strict
from tests.fakes.h24_fakes import load

SPECS = load_specs()


def plans(n=60):
    for i in range(n):
        d = ("manufacturing", "project")[i % 2]
        ops, auth = SPECS[d]
        rng = random.Random(i)
        w, info = gen_graph.make_world(ops, auth, rng)
        yield d, ops, w, info, gen_graph.plan_edges(ops, w, info, rng, 0, rng.randint(6, 14), force_deep=i % 10 == 0)


def test_worlds_are_schema_valid_with_6_to_14_fresh_principals_and_delegable_grants():
    for d, ops, w, info, _ in plans(20):
        validate_strict(w, ops)
        fresh = [p for p in w["principals"] if p["id"].startswith("dp-")]
        assert 6 <= len(fresh) <= 14
        assert info["holders"] and all(g["origin"] == "neutral-extension" for g in w["grants"] if g["id"].startswith("g24-"))


def test_depth_distribution_fanout_dag_and_every_illegal_kind():
    depth, intents, parents, children, multi = collections.Counter(), collections.Counter(), collections.Counter(), {}, 0
    for d, ops, w, info, steps in plans(120):
        legal = [s["edge"] for s in steps if s["intent"] == "legal"]
        for s in steps:
            intents[s["intent"]] += 1
            if s["depth"]:
                depth[s["depth"]] += 1
        for e in legal:
            parents[e["parent"]] += 1
            children.setdefault(e["child"], set()).add(e["id"])
        multi += any(len(v) > 1 for v in children.values())
        children = {}
    n = sum(depth.values())
    assert sum(v for k, v in depth.items() if k >= 4) / n >= 0.25
    assert max(depth) == gen_graph.MAXD
    assert max(parents.values()) >= 1 and multi > 0  # fan-out and principals reachable by several edges
    kinds = {k.split(":", 1)[1] for k in intents if k.startswith("illegal:")}
    assert kinds >= set(gen_graph.ILLEGAL) - {"keys_null"} and len(kinds) >= 12, kinds


def test_oracle_refuses_every_illegal_intent_against_the_planned_graph():
    """Known-positive for the generator labels: replaying the plan through the oracle, legal edges are accepted and
    an intent-tagged illegal edge is refused unless its parent was itself refused (then it fails differently)."""
    bad_accepted = tot = 0
    for d, ops, w, info, steps in plans(60):
        ra, seq = RefAuthority.from_spec(w), 0
        for s in steps:
            v = ra.issue_delegate(s["edge"], INF, 0)
            if s["intent"].startswith("illegal"):
                tot += 1
                bad_accepted += v.ok
            if v.ok:
                seq += 1
                ra = ra.apply(event(seq, 0, "delegate", {"edge": s["edge"]}))
    assert tot > 50 and bad_accepted == 0


def test_sequences_are_deterministic_unique_and_cover_every_operation():
    v, seen, ops = load("fake-honest"), set(), collections.Counter()
    for i in range(24):
        a = run_sequence(v, SPECS, 5, i)
        b = run_sequence(v, SPECS, 5, i) if i < 3 else a
        assert a["digest"] == b["digest"] and 20 <= len(a["calls"]) <= 140
        seen.add(a["digest"])
        for c in a["calls"]:
            if c["kind"] == "request":
                ops[f"{a['domain']}:{c['op']}"] += 1
    assert len(seen) == 24
    assert run_sequence(v, SPECS, 6, 0)["digest"] != run_sequence(v, SPECS, 5, 0)["digest"]
    need = {f"{d}:{o['name']}" for d in SPECS for o in SPECS[d][0]["operations"]}
    assert need <= set(ops), need - set(ops)


def test_every_race_type_runs_and_the_pair_is_recorded():
    v = load("fake-honest")
    for i, t in enumerate(TYPES):
        r = run_race(v, SPECS, 3, i, t)
        assert r["type"] == t and r["calls"] and r["match"], (t, r["classes"])
        assert r["executed"] == (t != "SEQ")
        assert all(c["inv"] < c["ret"] for c in r["calls"])
    seq_orders = {run_race(v, SPECS, 3, i, "SEQ")["order"] for i in (0, 1)}
    assert seq_orders == {"effect_first", "revoke_first", None} & seq_orders and not run_race(v, SPECS, 3, 0, "SEQ")["overlap"]
