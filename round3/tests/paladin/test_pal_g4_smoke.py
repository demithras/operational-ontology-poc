from g4_rig import EXP, G4Rig, RES, TR


def test_smoke_manufacturing(tmp_path):
    r = G4Rig(tmp_path)
    try:
        res = r.call("planner-1", "expedite_purchase_order", EXP, "r1")
        assert res.status == "OK", res
        print(res.body)
        assert r.dep.dispatch_pending().body == {"submitted": 1}
        r.tick(9)
        out = r.dep.reconcile("r1", 10)
        print(out, r.ledger())
    finally:
        r.finish()
