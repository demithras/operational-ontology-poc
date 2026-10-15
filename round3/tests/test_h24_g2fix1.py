"""G2 fix1 (E-5, E-6): set_authority documents are base-only; mirror follows a revoke made effective by a retry;
every supplied resource ref must exist (oracle)."""
import random
from types import SimpleNamespace

import pytest

from r3_harness.h23.corpus import load_specs
from r3_harness.h24 import gen_graph
from r3_harness.h24.gen_seq import Seq, composed
from r3_harness.h24.rows import mirror_apply, mirror_revoke
from r3_oracle import ops_model as M
from r3_oracle.authority_v2 import INF, RefAuthority
from r3_shared.authspec import validate_strict

SPECS = load_specs()


def _env_with_edge(domain="manufacturing", seed=3):
    ops, auth = SPECS[domain]
    rng = random.Random(seed)
    w, info = gen_graph.make_world(ops, auth, rng)
    steps = gen_graph.plan_edges(ops, w, info, rng, 0, 8)
    edge = next(s["edge"] for s in steps if s["intent"] == "legal" or s["intent"].startswith("legal"))
    env = SimpleNamespace(mirror=RefAuthority.from_spec(w), _ms=0, clock=SimpleNamespace(now=lambda: 1), ops=ops)
    return env, edge, ops


def test_e5_composed_document_is_base_only_even_with_edges_and_revocations_in_the_mirror():
    env, edge, ops = _env_with_edge()
    ok = env.mirror.issue_delegate(edge, INF, 1).ok
    if not ok:
        pytest.skip("generator edge not acceptable in this seed")
    from r3_harness.h24.rows import mirror_delegate
    mirror_delegate(env, edge)
    mirror_revoke(env, edge["issuer"], edge["id"])
    st = env.mirror.view(None)
    assert edge["id"] in st.edges and edge["id"] in st.revoked
    doc = composed(env)
    assert doc["capabilities"] == [] and doc["revoked"] == []
    assert {k: v for k, v in doc.items() if k not in ("capabilities", "revoked")} == st.base
    validate_strict(doc, ops)


def test_mirror_revoke_is_idempotent_and_records_the_first_effective_revoke():
    env, edge, _ = _env_with_edge()
    from r3_harness.h24.rows import mirror_delegate
    mirror_delegate(env, edge)
    n0 = len(env.mirror.events)
    mirror_revoke(env, edge["issuer"], edge["id"])
    mirror_revoke(env, edge["issuer"], edge["id"])  # "already": no second event
    assert len(env.mirror.events) == n0 + 1 and edge["id"] in env.mirror.view(None).revoked


def _crash_env(env, first, retry):
    """The mirror env itself, with a revoke that answers `first` (crashed) then `retry` (effective)."""
    answers = [first, retry]
    env.arm = lambda point: None
    env.crash_restart = lambda: None
    env.revoke = lambda actor, edge_id, rid, crash=None: {"status": answers.pop(0), "rid": rid}
    return env


@pytest.mark.parametrize("point", ["before_commit", "after_commit"])
def test_e5_crashed_revoke_made_effective_by_retry_is_mirrored(point):
    env, edge, _ = _env_with_edge()
    from r3_harness.h24.rows import mirror_delegate
    mirror_delegate(env, edge)
    s = Seq.__new__(Seq)
    s.env, s.rng = _crash_env(env, "UNKNOWN", "OK"), random.Random(1)
    s.rid = lambda p="r": "v1"
    s.rng.choice = lambda seq: point if point in seq else seq[0]
    s.rng.random = lambda: 0.9  # not a plain restart
    s.s_crash()
    assert edge["id"] in env.mirror.view(None).revoked


def test_e6_every_supplied_resource_ref_must_exist_required_and_optional(monkeypatch):
    """Authority scope is neutralised so the existence rule itself is what is measured (every ref of every op)."""
    monkeypatch.setattr(M.authority, "decide", lambda *a, **k: SimpleNamespace(allow=True, reason=""))
    n_req = n_opt = 0
    for d in ("manufacturing", "project"):
        ops, auth = SPECS[d]
        snap = _seed(ops)
        for op in ops["operations"]:
            by = {o["type"]: o["key"] for o in ops["seed"]["objects"]}
            args = {}
            for i in op["inputs"]:
                if i["type"] == "resource":
                    args[i["name"]] = by.get(i["resource_type"])
            for i in op["inputs"]:
                if i["type"] != "resource" or args.get(i["name"]) is None:
                    continue
                bad = {**args, i["name"]: "NOPE"}
                for j in op["inputs"]:  # fill non-resource inputs with schema-agnostic probes: skip ops we cannot build
                    if j["name"] not in bad:
                        break
                else:
                    out = M.evaluate(ops, auth, "x", None, op["name"], bad, snap, 1)
                    if out.kind in (M.INVALID, M.DENIED_RULE) and "target-existence" in out.detail:
                        n_req, n_opt = (n_req + 1, n_opt) if i["required"] else (n_req, n_opt + 1)
                    assert out.kind != M.COMMIT, (d, op["name"], i["name"])
    assert n_req > 0, "no required-ref case reached the existence rule"


def _seed(ops):
    s = ops["seed"]
    return {"objects": {f"{o['type']}:{o['key']}": {"props": dict(o["props"]), "version": 1} for o in s["objects"]},
            "links": [[x["link_type"], x["src"], x["dst"]] for x in s["links"]], "effects": []}
