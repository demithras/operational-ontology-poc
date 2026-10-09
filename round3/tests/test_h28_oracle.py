"""Oracle unit tests: P1f-6 rules (every one with a negative), refusal model vs ExternalWorldCore (C28-5 oracle half), isolation (C28-0)."""
import ast
import tempfile
from pathlib import Path

import pytest

from r3_harness.h28 import evaluator
from r3_oracle import extoracle
from r3_oracle.extoutcome import outcome_state
from r3_shared import extcap
from r3_shared.extadapter import payload_digest
from tests.p1f_util import KEY, PAY, TARGET, cap_for, core

I = {"operation": "expedite", "target": TARGET, "payload_digest": payload_digest(PAY), "correlation": "r1#0"}


def row(seq, op="expedite", tgt=TARGET, dig=I["payload_digest"], cor="r1#0"):
    return {"seq": seq, "operation": op, "target": tgt, "payload_digest": dig, "correlation": cor}


def snap(eff=(), aud=(), ct=0, wm=None):
    return {"effects": list(eff), "audit": list(aud), "complete_through_tick": ct, "watermark": ct if wm is None else wm}


def st(s, prev=None, cls="at_most_once", obs="full", exp=5, pev=None, pwm=None):
    return outcome_state(I, s, prev, pev, cls, obs, exp, pwm)


def test_rules_in_order():
    assert st(snap(), obs="none")[:2] == ("UNKNOWN", "low")                                   # N
    assert st(None, prev="RECONCILED_SUCCESS")[0] == "RECONCILED_SUCCESS"                      # U keeps final
    assert st(None, prev="PENDING")[0] == "UNKNOWN"                                            # U otherwise UNKNOWN
    assert st(snap([row(1)]), prev="DIVERGED")[0] == "DIVERGED"                                # D1 absorbing
    assert st(snap([row(1, tgt="po:X")]))[0] == "DIVERGED"                                     # D2 (effect row)
    assert st(snap([], [row(2, tgt="po:X")]))[0] == "DIVERGED"                                 # D2 (audit row)
    assert st(snap([row(1), row(2)]))[0] == "DIVERGED"                                         # D3
    assert st(snap([row(1), row(2)]), cls="idempotent_set")[0] == "RECONCILED_SUCCESS"        # D3 not for idempotent_set
    assert st(snap([row(1)]))[0] == "RECONCILED_SUCCESS"                                       # S
    assert st(snap(ct=6))[0] == "RECONCILED_FAILED"                                            # F
    assert st(snap(ct=5))[0] == "PENDING"                                                      # W (not past expiry)
    assert st(snap([], [row(3)] , ct=2))[0] == "PENDING"                                       # matching refused-style audit row is benign


def test_confidence_and_evidence_e19():
    s, c, ev = st(snap([row(4)], [row(4)]), obs="effects_only")
    assert (s, c) == ("RECONCILED_SUCCESS", "low") and ev == [4]                               # audit invisible/ignored when not full
    s, c, ev = st(snap([row(4)], [row(4), row(9)]))
    assert c == "full" and ev == [4, 4, 9]                                                     # G4-E19: ints, duplicates kept, sorted
    assert all(isinstance(x, int) for x in ev)


def test_monotone_e16():
    s = st(snap(ct=9, wm=9), prev="RECONCILED_FAILED", pwm=12)
    assert s[0] == "RECONCILED_FAILED"                                                         # lower watermark ignored
    assert st(snap(ct=3, wm=3), prev="RECONCILED_SUCCESS", pwm=2)[0] == "RECONCILED_SUCCESS"  # never back to PENDING


def test_refusal_model_matches_externalworld_in_frozen_order():
    c = core()
    issued = {(r[0], r[1], r[2]) for r in []}
    good = cap_for(c)
    issued = {(extcap.root_nonce(good), "ERP", "dep1")}
    cases = [(good, "expedite", TARGET, PAY, "applied"), (good + "x", "expedite", TARGET, PAY, "bad_signature"),
             (good, "expedite", "po:OTHER", PAY, "target_mismatch"), (good, "expedite", TARGET, {**PAY, "expedite_fee": 11}, "payload_mismatch"),
             (good, "other", TARGET, PAY, "operation_mismatch")]
    for cap, op, tgt, pay, want in cases:
        used = c.con.execute("SELECT count(*) FROM effects WHERE cap_chain=?", (extcap.chain_id(cap) if want != "bad_signature" else "",)).fetchone()[0]
        got = extoracle.predict_write(KEY, c.systems, cap, op, tgt, pay, c.tick, used, issued)
        assert got == want
        assert c.write(cap, op, tgt, pay, "t")["reason"] == ("" if want == "applied" else want)
    assert extoracle.predict_write(KEY, c.systems, good, "expedite", TARGET, PAY, c.tick, 1, issued) == "uses_exhausted"
    assert extoracle.predict_write(KEY, c.systems, good, "expedite", TARGET, PAY, 99, 0, issued) == "expired"


def test_scope_and_duplicates():
    led = {"effects": [{"seq": 1, "deployment": "d", "system": "ERP", "operation": "expedite", "target": TARGET,
                        "payload_digest": I["payload_digest"], "correlation": "r1#0"}], "audit": []}
    ok = {"system": "ERP", "operation": "expedite", "target": TARGET, "payload_digest": I["payload_digest"], "correlation": "r1#0",
          "idempotency": "at_most_once"}
    assert extoracle.scope_check(led, {"d": [ok]}) == []
    assert len(extoracle.scope_check(led, {"d": []})) == 1 and len(extoracle.scope_check(led, {"other": [ok]})) == 1
    led["effects"].append({**led["effects"][0], "seq": 2})
    assert extoracle.duplicates(led, "d", ok) == 1 and extoracle.duplicates(led, "d", {**ok, "idempotency": "idempotent_set"}) == 0


def test_isolation_scan_passes_and_a_known_negative_fails():
    assert evaluator.oracle_isolation() == (True, [])
    d = Path(tempfile.mkdtemp())
    (d / "extoracle.py").write_text("import paladin.engine\nfrom r3_harness.h28 import judge\nimport r3_shared.histstore\n")
    ok, bad = evaluator.oracle_isolation(d)
    assert not ok and len(bad) >= 3


def test_oracle_has_no_variant_import_anywhere_in_its_modules():
    for f in (Path(extoracle.__file__), Path(extoracle.__file__).with_name("extoutcome.py")):
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                assert not any(x in ast.dump(n) for x in ("paladin", "conventional", "r3_harness"))
