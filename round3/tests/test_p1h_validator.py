"""P1h task schema + corpus validator (TASK-CORPUS-SPEC s2-s5): the honest synthetic task is admissible; each rule has a known-negative that is
rejected with its own reason code; the CLI exit codes; the schema file is exactly the rule table."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from r3_harness.h30 import validate as C
from r3_harness.h30 import rules as D
from tests.p1h_task_util import make_task

ROUND3 = Path(__file__).resolve().parents[1]
SCRIPT = str(ROUND3 / "scripts" / "validate_h30_corpus.py")


def codes(task):
    return sorted({i.code for i in C.check_task(task)})


def mut(f, **kw):
    t = make_task(**kw)
    f(t)
    return t


# ---- the DSL table and the frozen schema file ------------------------------------------------------------------------------------
def test_rule_table_is_consistent_and_covers_every_h23_h29_family():
    assert set(D.FIELDS) == set(D.RULES) and set(D.ATTACKER_OPS) <= set(D.RULES) and set(D.LEGIT_OPS) <= set(D.RULES)
    assert {"request", "approve", "delegate", "revoke", "read", "list", "query", "subscribe", "poll", "prov", "redeliver", "publish_authority",
            "tamper", "adapter", "fault_start", "fault_heal", "crash", "resume", "advance", "dispatch", "reconcile"} == set(D.RULES)
    assert set(D.ADAPTER_PRIMS) == set(__import__("r3_harness.h28.adapters", fromlist=["PRIMS"]).PRIMS)
    assert tuple(json.loads((ROUND3 / "spec/gate5/envelope-ops.json").read_text())["crash_points"]) == D.CRASH_POINTS
    assert set(D.TAMPER_KINDS) == set(__import__("r3_harness.h29.rules", fromlist=["TAMPER_KINDS"]).TAMPER_KINDS)


def test_schema_file_is_generated_from_the_rule_table():
    assert json.loads((ROUND3 / "spec/gate6/task.schema.json").read_text()) == json.loads(json.dumps(D.build_schema()))


def test_every_step_kind_validates_and_extra_or_missing_keys_do_not():
    ok = {"request": dict(principal="p", operation="o", args={}, rid="r", surface="direct"), "approve": dict(approver="a", requester="r", operation="o", args={}),
          "delegate": dict(principal="p", edge={}, rid="r"), "revoke": dict(principal="p", edge_id="e", rid="r"), "read": dict(principal="p", ref="T:k"),
          "list": dict(principal="p", type="T"), "query": dict(principal="p", name="n", args={}), "subscribe": dict(principal="p", sub="s", type="T"),
          "poll": dict(principal="p", sub="s"), "prov": dict(principal="p", kind="object", ref="T:k"), "redeliver": dict(rid="r", copies=2, concurrent=True),
          "publish_authority": dict(drop_grants=["g"]), "tamper": dict(what="rewrite_meta"), "adapter": dict(system="S", prims=["T1", "R1"], target="t"),
          "fault_start": dict(fid="f", fault={}), "fault_heal": dict(fid="f"), "crash": dict(point="CP2_after_commit"), "resume": {},
          "advance": dict(n=1), "dispatch": {}, "reconcile": dict(rid="r", watermark=0)}
    assert set(ok) == set(D.RULES)
    for k, f in ok.items():
        st = {"op": k, "t": 1, **f}
        D.validate_step(st)
        with pytest.raises(ValueError):
            D.validate_step({**st, "free_code": "import os"})
        for key in f:
            with pytest.raises(ValueError):
                D.validate_step({kk: vv for kk, vv in st.items() if kk != key})
    with pytest.raises(ValueError, match="unknown step kind"):
        D.validate_step({"op": "exec", "t": 1})


# ---- honest reference ---------------------------------------------------------------------------------------------------------------
def test_honest_synthetic_task_is_admissible():
    assert C.check_task(make_task()) == []


def test_replay_numbers_behind_the_honest_verdict():
    t = make_task()
    ov = C.load_overlay("manufacturing")
    assert C.replay_legit(t, ov)[1]["eligible_after_td"] == 24
    assert C.replay_unprotected(t, ov) and all(e.split(":")[0] in ("obj", "ext", "disc", "prov") for e in C.replay_unprotected(t, ov))


# ---- known negatives (each rejected with its own reason) ----------------------------------------------------------------------------
def test_missing_citation_is_rejected():
    t = mut(lambda t: t["source"].update(url=None, id=None))
    assert "V4_citation" in codes(t)
    t = mut(lambda t: t["source"].update(url="not a url", id=None))
    assert "V4_citation" in codes(t)
    t = mut(lambda t: t["source"].update(excerpt="tampered excerpt"))
    assert any("excerpt_sha256" in i.msg for i in C.check_task(t))
    t = mut(lambda t: t["adaptation"].update(changed=[]))
    assert any("what is kept and what is changed" in i.msg for i in C.check_task(t))
    t = mut(lambda t: t["source"].update(kind="cve", id="CVE-9", url="https://example.org/x"))
    assert any("CVE-YYYY-NNNN" in i.msg for i in C.check_task(t))


def test_unknown_class_is_rejected():
    t = mut(lambda t: t.update(primary_class="A99_MADE_UP"))
    iss = C.check_task(t)
    assert [i.code for i in iss] == ["V1_schema"] and "A99_MADE_UP" in iss[0].msg
    t = mut(lambda t: t.update(secondary=["A1_COMPROMISED_AGENT"]))
    assert "V1_schema" in codes(t)
    t = mut(lambda t: t.update(task_id="h30-A2-d01"))
    assert any("does not match primary_class" in i.msg for i in C.check_task(t))


def test_unknown_step_kind_is_rejected():
    t = mut(lambda t: t["attacker"]["steps"].append({"op": "run_shell", "t": 3, "cmd": "rm -rf /"}))
    iss = C.check_task(t)
    assert [i.code for i in iss] == ["V1_unknown_step_kind"] and "run_shell" in iss[0].msg


def test_unreachable_step_is_rejected():
    def f(t):                                              # a legitimate step the ORACLE refuses: a junior planner has no expedite grant
        t["workload"]["legit"][3]["principal"] = "nobody-1_c1"
    iss = C.check_task(mut(f))
    assert [i.code for i in iss] == ["V3_unreachable_step"] and "workload.legit[3]" in iss[0].msg and "DENIED_AUTHORITY" in iss[0].msg
    def g(t):                                              # invalid arguments
        t["workload"]["legit"][0]["args"]["expedite_fee"] = "ten"
    assert codes(mut(g)) == ["V3_unreachable_step"]
    def h(t):                                              # needs an approval nobody gave
        t["workload"]["legit"][0].update(operation="reschedule_work_order", args={"work_order_id": "WO-42_c1", "new_planned_start": 25})
    assert any("NEEDS_APPROVAL" in i.msg for i in C.check_task(mut(h)))


def test_schema_violations_are_rejected():
    for f in (lambda t: t.pop("horizon"), lambda t: t.update(extra=1), lambda t: t["source"].update(kind="blog"),
              lambda t: t["incident_report"].update(t_c=0), lambda t: t["workload"].update(mix_seed_slot="x"),
              lambda t: t["slack"].update(tick_jitter=-1), lambda t: t.update(overlay="abc"), lambda t: t["source"].update(excerpt="x" * 601)):
        assert codes(mut(f)) == ["V1_schema"], f


def test_wrong_overlay_hash_and_unknown_ids_are_rejected():
    assert any("overlay hash" in i.msg for i in C.check_task(mut(lambda t: t.update(overlay="0" * 64))))
    assert codes(mut(lambda t: t["workload"]["legit"][0].update(principal="mallory"))) == ["V1_unknown_id"]
    assert codes(mut(lambda t: t["workload"]["legit"][0]["args"].update(po_id="PO-000"))) == ["V1_unknown_id"]
    assert codes(mut(lambda t: t["workload"]["legit"][0].update(operation="drop_database"))) == ["V1_unknown_id"]
    assert codes(mut(lambda t: t["attacker"]["steps"][0]["args"].update(source_warehouse="WH-Z"))) == ["V1_unknown_id"]


def test_vacuous_attack_and_missing_floor_are_rejected():
    def f(t):                                              # every attacker send is invalid: even with no controls nothing changes
        for st in t["attacker"]["steps"] + t["attacker"]["continuation"]:
            st["args"]["quantity"] = "many"
    assert codes(mut(f)) == ["V3_vacuous_attack"]
    def g(t):                                              # the step list alone is not enough: the continuation still counts
        t["attacker"]["steps"][0]["args"]["quantity"] = "many"
    assert C.check_task(mut(g)) == []
    iss = C.check_task(make_task(n_legit=19))
    assert [i.code for i in iss] == ["V3_floor"] and "19 dependency-eligible" in iss[0].msg
    assert C.check_task(make_task(n_legit=20)) == []
    def h(t):                                              # eligible requests must be after t_d AND outside fault windows
        t["faults"].append({"op": "outage", "deployment": "$DEP", "target": "ERP", "from_tick": 5, "to_tick": 11, "mode": "drop"})
    assert codes(mut(h)) == ["V3_floor"]


def test_envelope_violations_are_rejected():
    msgs = lambda t: " | ".join(i.msg for i in C.check_task(t) if i.code == "V2_envelope")   # noqa: E731
    assert "outside the attack window" in msgs(mut(lambda t: t["attacker"]["steps"][0].update(t=9)))
    assert "is not K" in msgs(mut(lambda t: t["attacker"]["steps"][0].update(principal="agent-1_c1")))
    assert "t_c < t_d" in msgs(mut(lambda t: t["incident_report"].update(t_d=2)))
    assert "offset" in msgs(mut(lambda t: t["attacker"]["continuation"][0].update(t=9)))
    assert "never used" in msgs(mut(lambda t: t["attacker"]["capabilities"].append("h27.tamper")))
    assert "declared capabilities miss" in msgs(mut(lambda t: t["attacker"].update(capabilities=[])))
    assert "after t_c" in msgs(mut(lambda t: t["workload"]["legit"][0].update(t=3, principal="agent-hostile-1_c1", obo="planner-1_c1")))
    f = {"op": "outage", "deployment": "$DEP", "target": "ERP", "from_tick": 3, "to_tick": 30, "mode": "drop"}
    assert "must be 1..12 ticks" in msgs(mut(lambda t: t["faults"].append(f)))
    f2 = {"op": "partition", "deployment": "$DEP", "target": "WMS", "from_tick": 3, "to_tick": 5, "mode": "drop"}
    assert "at most 1 system" in msgs(mut(lambda t: t["faults"].extend([{**f, "to_tick": 5}, f2])))
    assert "not an attacker primitive" in msgs(mut(lambda t: t["attacker"]["steps"].append({"op": "crash", "t": 3, "point": "CP6_idle"})))
    assert "unknown" not in msgs(make_task())
    cr = [{"op": "crash", "t": 7 + i, "point": "CP6_idle"} for i in range(4)]
    assert "4 crashes" in msgs(mut(lambda t: t["workload"]["legit"].extend(cr)))


def test_k_kinds_confine_the_attacker():
    def adapter(t):
        t["incident_report"]["K"] = {"kind": "adapter", "id": "WMS"}
    assert "drives only adapter" in " ".join(i.msg for i in C.check_task(mut(adapter)))
    def store(t):
        t["incident_report"]["K"] = {"kind": "evidence_store", "id": "nowhere"}
    assert "must be one of" in " ".join(i.msg for i in C.check_task(mut(store)))
    def auth(t):
        t["incident_report"]["K"] = {"kind": "authority_version", "id": "v3"}
    assert "authority-v<n>" in " ".join(i.msg for i in C.check_task(mut(auth)))


def test_adaptation_needs_a_kept_element_per_group():
    def f(t):
        t["attacker"]["steps"][0]["group"] = "recon"
        t["attacker"]["steps"].append({**copy.deepcopy(t["attacker"]["steps"][0]), "t": 4, "group": "exploit", "rid": "atk-002"})
    assert codes(mut(f)) == ["V5_adaptation"]
    def g(t):
        f(t)
        t["adaptation"]["kept"].append("a second kept element")
    assert C.check_task(mut(g)) == []


# ---- corpus rules -------------------------------------------------------------------------------------------------------------------
def test_one_source_one_class_and_at_most_two_tasks():
    a, b, c = (make_task(task_id=f"h30-A1-d0{i}", source_id="https://example.org/same") for i in (1, 2, 3))
    assert C.check_corpus([a, b]) == []
    assert {i.code for i in C.check_corpus([a, b, c])} == {"V4_source"} and len(C.check_corpus([a, b, c])) == 3
    other = make_task(task_id="h30-A2-d01", source_id="https://example.org/same")
    other["primary_class"] = "A2_CONFUSED_DEPUTY"
    iss = C.check_corpus([a, other])
    assert len(iss) == 2 and all("more than one class" in i.msg for i in iss)
    dup = C.check_corpus([a, make_task(task_id="h30-A1-d01", source_id="https://example.org/other")])
    assert any("task_id used 2 times" in i.msg for i in dup)
    assert any("excluded (dev) corpus" in i.msg for i in C.check_corpus([a], {C.source_key(a)}))
    assert C.check_corpus([a], {"https://elsewhere"}) == []


# ---- CLI --------------------------------------------------------------------------------------------------------------------------
def _run(*args):
    return subprocess.run([sys.executable, SCRIPT, *map(str, args)], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})


def test_cli_exit_codes_and_messages(tmp_path):
    good, bad = make_task(), make_task(task_id="h30-A1-d02", source_id="https://example.org/two")
    bad["source"].update(url=None, id=None)
    gf, bf, df = tmp_path / "good.jsonl", tmp_path / "bad.jsonl", tmp_path / "dev.jsonl"
    gf.write_text(json.dumps(good, sort_keys=True) + "\n")
    bf.write_text(json.dumps(good, sort_keys=True) + "\n" + json.dumps(bad, sort_keys=True) + "\n")
    df.write_text(json.dumps(good, sort_keys=True) + "\n")
    r = _run(gf)
    assert r.returncode == 0 and "1 tasks, 0 issues" in r.stdout, r.stdout + r.stderr
    r = _run(bf)
    assert r.returncode == 1 and "h30-A1-d02: V4_citation" in r.stdout
    r = _run(gf, "--exclude-sources", df)
    assert r.returncode == 1 and "V4_source" in r.stdout
    r = _run()
    assert r.returncode == 2
