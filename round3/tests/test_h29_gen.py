"""H29 generator / rule table / authority-version family tests."""
import json
import subprocess
import sys

from r3_harness.h29 import faults, gen, rules, specs
from r3_harness.h29.machine import RULE_METHODS

ROUND3 = faults.ROUND3


def test_rule_table_generator_and_machine_agree():
    kinds = set()
    stats = {}
    for i in range(96):
        s = gen.build("env", i, 2911, stats)
        assert s is not None
        kinds |= {st["op"] for st in s["steps"]}
    for st_, n in (("ctrl", 6), ("bnd", 8)):
        for i in range(n):
            kinds |= {st["op"] for st in gen.build(st_, i, 2911, stats)["steps"]}
    assert RULE_METHODS == set(rules.RULES)                                  # machine rules == frozen table (set difference)
    assert kinds == set(rules.RULES), (kinds ^ set(rules.RULES))              # generator step kinds == machine rules (set difference)


def test_generator_sweep_no_exceptions_envelope_and_lengths():
    stats = {}
    for i in range(160):
        s = gen.build("env", i, 2911 + i % 3, stats)
        assert s is not None, i
        assert 24 <= len(s["steps"]) <= 48
        ok, why = faults.envelope_ok(s)
        assert ok, (i, why)
        for st in s["steps"]:
            rules.validate_step(st)
    assert "generator_redraw_exhausted" not in stats


def test_generator_is_deterministic_and_reaches_every_class_and_crash_point():
    a = [gen.build("env", i, 7, {}) for i in range(128)]
    b = [gen.build("env", i, 7, {}) for i in range(128)]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert {c for s in a for c in s["classes"]} == set(rules.CLASSES)
    assert {cp for s in a for cp in s["cp"]} == set(faults.CRASH_POINTS)
    assert all(any(st["op"] == "request" and st.get("tag") == "stale" for st in s["steps"]) for s in a if s["classes"][0] == "F6")


def test_envelope_ok_rejects_out_of_envelope():
    bad = {"steps": [{"op": "fault_start", "fid": "f1", "cls": "F5", "node": "AUTH", "mode": "drop", "duration": 20}]}
    assert not faults.envelope_ok(bad)[0]
    three = {"steps": [{"op": "fault_start", "fid": f"f{i}", "cls": c, "node": n, "mode": "drop", "duration": 5}
                       for i, (c, n) in enumerate([("F2", "AUTH"), ("F5", "ANCHOR"), ("F5", "OBS")])]}
    assert not faults.envelope_ok(three)[0]


def test_authority_version_family_one_grant_removed_and_script_check():
    for dom in specs.DOMAINS:
        fam = specs.family(dom)
        assert len(fam) >= 2
        ids0 = [g["id"] for g in fam[0]["grants"]]
        for k in range(1, len(fam)):
            ids = [g["id"] for g in fam[k]["grants"]]
            assert len(ids) == len(ids0) - 1 and set(ids) < set(ids0)           # narrowing only, exactly ONE grant removed
            rest = {x: y for x, y in fam[k].items() if x != "grants"}
            assert rest == {x: y for x, y in fam[0].items() if x != "grants"}
            assert specs.removed_grant(dom, k) in ids0
    r = subprocess.run([sys.executable, str(ROUND3 / "scripts/gen_h29_authversions.py"), "--check"], capture_output=True)
    assert r.returncode == 0
