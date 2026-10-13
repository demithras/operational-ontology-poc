"""G5-E32: the read judge compares served objects by the ops_model.LOOSE_PROPS rule (form), not raw equality."""
import copy
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from r3_harness.h29 import judge, judge_req
from r3_oracle import continuity as C

EV = Path(__file__).resolve().parents[1] / "experiments" / "h29" / "exp-h29-001"


def _evidence_records():
    out = []
    for v in ("paladin", "conventional"):
        n = 0
        for line in gzip.open(EV / v / "fault-sequences.jsonl.gz", "rt"):
            if "disclosure_leak" not in line:
                continue
            for cd in json.loads(line).get("class_details", {}).get("disclosure_leak", []):
                out.append((v, cd["detail"])); n += 1
        assert n == 2, (v, n)          # fails (never skips) if the committed evidence is absent or changed
    return out


RECORDS = _evidence_records()


def _run(exp, body, status="OK", raw=False, monkeypatch=None, kind="get", args=None):
    lv = object()
    monkeypatch.setattr(judge_req, "low_view", lambda *a, **k: lv)
    monkeypatch.setattr(judge_req, "expected_read_object", lambda *a: exp)
    monkeypatch.setattr(judge_req, "expected_list_objects", lambda *a: exp)
    monkeypatch.setattr(judge, "active", lambda cw, t: [])
    monkeypatch.setattr(C, "classify", lambda *a, **k: SimpleNamespace(kind=C.SAFE, down=None, strict=True))
    if raw:
        monkeypatch.setattr(judge_req, "served_matches", lambda a, b: a == b)
    monkeypatch.setattr(judge_req, "_unrelated", lambda *a, **k: None)
    row = {"req": [], "classes": {}, "harness": []}
    e = {"t": 1, "n": 1, "k": "read", "operation": kind, "principal": "p", "args": args or {"type": "Verdict", "key": "k"},
         "res": {"status": status, "body": body}}
    judge_req._read(None, row, e, SimpleNamespace(down=lambda t: set()), None, None, None, None, SimpleNamespace(snap={}), lambda t: None, {}, None)
    return row


@pytest.mark.parametrize("v,d", RECORDS)
def test_exp_h29_001_records_are_not_leaks(v, d, monkeypatch):
    row = _run(tuple(d["oracle"]), d["got"], monkeypatch=monkeypatch)
    assert "disclosure_leak" not in row["classes"]
    assert row["req"][0]["progressed"] is True


@pytest.mark.parametrize("v,d", RECORDS)
def test_old_raw_comparison_flags_the_four_records(v, d, monkeypatch):
    row = _run(tuple(d["oracle"]), d["got"], raw=True, monkeypatch=monkeypatch)
    assert len(row["classes"]["disclosure_leak"]) == 1


def _base():
    v, d = RECORDS[0]
    return tuple(d["oracle"]), copy.deepcopy(d["got"])


def _mut(f):
    exp, got = _base()
    f(got)
    return exp, got


NEG = {
    "other_value": lambda g: g["props"].update(value="SUPPORTED"),
    "extra_prop": lambda g: g["props"].update(extra="x"),
    "blank_reason": lambda g: g["props"].update(reason="  "),
    "non_string_reason": lambda g: g["props"].update(reason=3),
    "hash_63": lambda g: g["props"].update(derivation_hash="a" * 63),
    "hash_nonhex": lambda g: g["props"].update(derivation_hash="g" * 64),
    "hash_upper": lambda g: g["props"].update(derivation_hash="A" * 64),
    "other_git_commit": lambda g: g["props"].update(git_commit="deadbeef"),
    "missing_prop": lambda g: g["props"].pop("git_commit"),
    "other_ref": lambda g: g.update(ref="Verdict:other"),
    "extra_body_key": lambda g: g.update(more=1),
}


@pytest.mark.parametrize("name", sorted(NEG))
def test_known_negatives_still_leak(name, monkeypatch):
    exp, got = _mut(NEG[name])
    assert len(_run(exp, got, monkeypatch=monkeypatch)["classes"]["disclosure_leak"]) == 1


def test_field_outside_low_view_is_a_leak(monkeypatch):
    exp, got = _base()
    exp[1]["props"].pop("git_commit")                  # the low view hides git_commit; the variant served it
    assert len(_run(exp, got, monkeypatch=monkeypatch)["classes"]["disclosure_leak"]) == 1


def test_list_read_extra_object_leaks_and_equal_passes(monkeypatch):
    exp = ("OK", {"refs": ["Verdict:a", "Verdict:b"]})
    ok = _run(exp, {"refs": ["Verdict:a", "Verdict:b"]}, kind="list", args={"type": "Verdict"}, monkeypatch=monkeypatch)
    assert "disclosure_leak" not in ok["classes"]
    bad = _run(exp, {"refs": ["Verdict:a", "Verdict:b", "Verdict:c"]}, kind="list", args={"type": "Verdict"}, monkeypatch=monkeypatch)
    assert len(bad["classes"]["disclosure_leak"]) == 1


def test_object_bodies_get_loose_rule_only_by_ref_props_shape():
    exp = {"ref": "Verdict:x", "props": {"value": "S", "reason": "a", "derivation_hash": "0" * 64}}
    ok = {"ref": "Verdict:x", "props": {"value": "S", "reason": "b", "derivation_hash": "1" * 64}}
    assert judge_req.served_matches(exp, ok) is True
    assert judge_req.served_matches({"objects": [exp]}, {"objects": [ok]}) is False     # no hidden loosening inside wrappers


def test_non_verdict_types_compare_exactly():
    a = {"ref": "Task:t", "props": {"reason": "x"}}
    b = {"ref": "Task:t", "props": {"reason": "y"}}
    assert judge_req.served_matches(a, b) is False and judge_req.served_matches(a, copy.deepcopy(a)) is True


def test_one_shared_normaliser():
    from r3_oracle import recoverymodel
    assert judge_req._loose is recoverymodel._loose
