"""G3 fix7 (G3-E30): hidden variations only produce reachable state (vary_L link types, vary_F fields, vary_E creations)."""
import json
import random

from r3_harness.h26 import gen_pair, gen_vary as V, sim


def _ops(d):
    return json.load(open(gen_pair.ROUND3 / f"spec/ops/{d}.json"))


def test_reachable_link_types_derived_from_ops_spec():
    assert V.reachable_link_types(_ops("project")) == {"NEW_VERSION_OF", "PRODUCES", "SUPPORTS_OR_REFUTES", "EVALUATES",
                                                       "SUPERSEDED_BY", "CHANGES"}
    assert "TESTED_BY" not in V.reachable_link_types(_ops("project"))
    assert V.reachable_link_types(_ops("manufacturing")) == set()


def test_p2601_97_no_longer_varies_tested_by():
    p, _ = gen_pair.one(2601, 97)
    if p is not None:
        for w in p["w"]:
            for b in w["batches"]:
                assert all(c.get("link_type") != "TESTED_BY" for c in b)


def test_vary_L_only_reachable_link_types_200_draws_per_domain():
    for dom in gen_pair.DOMAINS:
        ok = V.reachable_link_types(_ops(dom))
        seen = 0
        for i in range(200):
            p, st = gen_pair.one(2700, i, kind="L", domain=dom)
            assert p is not None and not st["skipped"], (dom, i)
            if "L" not in p["kinds"]:
                assert not ok and st["kind_substituted"] == "L->E"
                continue
            seen += 1
            assert p["info"]["L"]["link"][0] in ok, (dom, p["info"]["L"])
            for w in p["w"]:
                assert all(c["link_type"] in ok for b in w["batches"] for c in b if c.get("op") == "link")
        assert (seen > 0) == bool(ok), (dom, seen)
        print(dom, "allowed link types:", sorted(ok), "L pairs:", seen)


def test_vary_F_and_E_respect_writable_sets_in_store_managed_domain():
    ops, auth, _g = gen_pair.load("project")
    upd, cr = V.updatable_fields(ops), V.creatable(ops)
    base = sim.apply_changes(sim.empty(), [c for b in sim.seed_batches(ops) for c in b])
    roots = [p["id"] for p in auth["principals"] if p["delegated_by"] is None]
    nf = ne = 0
    assert not V.kind_feasible(ops, "F") and V.kind_feasible(gen_pair.load("manufacturing")[0], "F")
    for i in range(300):
        lv = gen_pair.low_view(base, auth, roots[i % len(roots)], ops)
        r = V.vary_F(random.Random(f"F{i}"), ops, lv, base)
        if r:
            nf += 1
            t, _k = r[2]["ref"].split(":", 1)
            assert (t, r[2]["field"]) in upd
        r = V.vary_E(random.Random(f"E{i}"), ops, lv, base)
        if r:
            ne += 1
            for d in r[:2]:
                for ch in d["batches"][0]:
                    assert ch["type"] in cr and set(ch["props"]) <= set(cr[ch["type"]]) | {
                        next(x for x in ops["resource_types"] if x["name"] == ch["type"])["key_field"]}
                    if ch["type"] == "Hypothesis":
                        assert ch["props"]["phase"] == "DRAFT"
    assert nf == 0 and ne > 0, (nf, ne)  # project: no reachable F; E draws exist


def test_seed_2601_x_500_redraw_count_report(capsys):
    tot = sk = 0
    for i in range(500):
        p, st = gen_pair.one(2601, i)
        tot += st["redraws"]
        sk += st["skipped"]
    print("REDRAWS", tot, "SKIPPED", sk)
    assert sk == 0
