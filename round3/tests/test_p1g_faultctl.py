"""P1g-3 server-side fault controls: AnchorServer partition (drop vs reply_lost, refused rows logged server-side, reads follow the
windows), ExternalWorld outage/partition (unavailable evaluated BEFORE bad_signature; audit row; reply_lost applies the write)."""
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

from r3_shared import extcap
from r3_shared.anchor import AnchorError, AnchorUnavailable, require_anchor, start_anchor
from r3_shared.extadapter import payload_digest
from r3_shared.extsystems import load_systems
from r3_shared.extobs import validate_audit_row
from r3_shared.extworld import ExternalError, ExternalUnavailable, _call, start_external
from r3_shared.extworld_core import REFUSALS, REFUSALS_G5, ExternalWorldCore, Unavailable
from r3_shared.faultplane import DependencyUnavailable
from tests.p1f_util import KEY, PAY, TARGET, audit, cap_for, eff_count


@pytest.fixture
def anchor():
    d = Path(tempfile.mkdtemp(prefix="r3f"))
    p = start_anchor(d / "a", d / "s", control=True)
    yield p
    try:
        p.close()
    except Exception:
        p.proc.kill()
    shutil.rmtree(d, ignore_errors=True)


def test_anchor_drop_window_refuses_appends_and_reads(anchor):
    c, ctl = anchor.client(), anchor.control()
    ctl.partition("st", 2, 4, "drop")
    c.append("st", 1, "d1", "a" * 64)                                   # tick 0: before the window
    ctl.advance(2)
    for call in (lambda: c.append("st", 2, "d2", "b" * 64), lambda: c.get("st", 1), lambda: c.lookup("st", "d1"), lambda: c.head("st")):
        with pytest.raises(AnchorUnavailable) as ei:
            call()
        assert isinstance(ei.value, DependencyUnavailable) and str(ei.value) == "ANCHOR" and isinstance(ei.value, AnchorError)
    c.append("other", 1, "x1", "c" * 64)                                # another stream is unaffected
    ctl.advance(4)
    assert c.head("st")["seq"] == 1                                     # the dropped append was NOT applied
    assert c.append("st", 2, "d2", "b" * 64)["seq"] == 2                # window is [from, to)
    log = ctl.fault_log()
    assert [(r["op"], r["mode"], r["applied"]) for r in log["log"]] == [("append", "drop", False), ("get", "drop", False),
                                                                          ("lookup", "drop", False), ("head", "drop", False)]
    assert log["windows"][0]["deployment"] == "st"


def test_anchor_reply_lost_applies_the_append_then_drops_the_reply(anchor):
    c, ctl = anchor.client(), anchor.control()
    ctl.partition("st", 1, 3, "reply_lost")
    ctl.advance(1)
    with pytest.raises(AnchorUnavailable):
        c.append("st", 1, "d1", "a" * 64)
    ctl.advance(3)
    e = c.lookup("st", "d1")
    assert e is not None and e["seq"] == 1                              # applied and logged despite the lost reply
    assert ctl.fault_log()["log"] == [{"tick": 1, "stream": "st", "op": "append", "mode": "reply_lost", "applied": True}]
    with pytest.raises(AnchorError, match="duplicate"):
        c.append("st", 1, "d1", "a" * 64)


def test_anchor_control_plane_is_separate_and_off_by_default(tmp_path):
    p = start_anchor(tmp_path / "a", os.path.join(tempfile.mkdtemp(prefix="r3f"), "s"))        # no --control
    try:
        assert not os.path.exists(p.ctl_path)
        with pytest.raises(AnchorError):
            p.control().tick()
    finally:
        p.close()


def test_anchor_data_plane_refuses_control_ops_and_bad_commands(anchor):
    c = anchor.client()
    with pytest.raises(AnchorError, match="unknown op"):
        c._call({"op": "partition", "cmd": {}})
    with pytest.raises(AnchorError, match="unknown op"):
        c._call({"op": "advance", "tick": 5})
    ctl = anchor.control()
    for bad in ({"op": "outage", "deployment": "s", "from_tick": 1, "to_tick": 3, "mode": "drop"},
                {"op": "partition", "deployment": "s", "from_tick": 3, "to_tick": 3, "mode": "drop"}):
        with pytest.raises((AnchorError, ValueError)):
            ctl._c._call({"op": "partition", "cmd": bad})
    ctl.advance(2)
    with pytest.raises(AnchorError, match="tick must be"):
        ctl.advance(1)


def test_require_anchor_refuses_without_service(anchor):
    assert require_anchor("exp-h29-001", env={"R3_ANCHOR_SOCK": anchor.sock_path, "R3_ANCHOR_DIR": anchor.anchor_dir}) == (anchor.sock_path, anchor.anchor_dir)
    with pytest.raises(AnchorError, match="requires R3_ANCHOR_SOCK"):
        require_anchor("exp-h29-001", env={})
    with pytest.raises(AnchorError, match="no anchor configured"):
        require_anchor("exp-h29-dev1", env={})
    with pytest.raises(AnchorError, match="is not running"):
        require_anchor("exp-h29-001", env={"R3_ANCHOR_SOCK": "/tmp/r3-none", "R3_ANCHOR_DIR": "x"})


# ---- ExternalWorld -----------------------------------------------------------------------------------------------------
def test_unavailable_is_appended_after_the_frozen_reasons_but_evaluated_first():
    assert REFUSALS[-1] == "uses_exhausted" and "unavailable" not in REFUSALS and REFUSALS_G5 == ("unavailable",)
    c = ExternalWorldCore(tempfile.mkdtemp(prefix="r3x"), load_systems("manufacturing"), root_key=KEY)
    cap = cap_for(c)
    c.advance(1)
    nonce, steps, _ = extcap._decode(cap)
    forged = extcap._encode(nonce, steps, bytes(32))                                             # decodable, wrong signature
    assert c.write(forged, "expedite", TARGET, PAY, "adp")["reason"] in ("bad_signature",)       # healthy: the frozen order
    c.fault({"op": "outage", "deployment": "dep1", "target": "ERP", "from_tick": 2, "to_tick": 5, "mode": "drop"})
    c.advance(2)
    for token in (cap, forged):
        with pytest.raises(Unavailable):
            c.write(token, "expedite", TARGET, PAY, "adp")
    rows = audit(c)
    assert [r["reason"] for r in rows if r["tick"] == 2] == ["unavailable", "unavailable"]      # BEFORE bad_signature / any frozen reason
    assert all(r["outcome"] == "refused" and r["deployment"] == "" and r["system"] == "" for r in rows if r["tick"] == 2)  # G5-E4
    assert eff_count(c) == 0
    c.advance(5)
    assert c.write(cap, "expedite", TARGET, PAY, "adp")["status"] == "applied"                    # window is [from, to)
    assert [x["mode"] for x in c.fault_log()] == ["drop"]


def test_reply_lost_applies_the_write_and_other_deployments_are_unaffected():
    c = ExternalWorldCore(tempfile.mkdtemp(prefix="r3x"), load_systems("manufacturing"), root_key=KEY)
    cap, other = cap_for(c), cap_for(c, dep="dep2", correlation="r9#0")
    c.fault({"op": "partition", "deployment": "dep1", "target": "ERP", "from_tick": 0, "to_tick": 3, "mode": "reply_lost"})
    with pytest.raises(Unavailable):
        c.write(cap, "expedite", TARGET, PAY, "adp")
    assert eff_count(c) == 1 and audit(c)[-1]["outcome"] == "applied"                            # applied; only the reply is lost
    assert c.write(other, "expedite", TARGET, PAY, "adp")["status"] == "applied"                  # dep2 is not partitioned
    assert c.fault_log()[0]["mode"] == "reply_lost"


def test_fault_command_rules_server_side():
    c = ExternalWorldCore(tempfile.mkdtemp(prefix="r3x"), load_systems("manufacturing"), root_key=KEY)
    base = {"op": "outage", "deployment": "d", "target": "ERP", "from_tick": 1, "to_tick": 2, "mode": "drop"}
    for bad in ({**base, "target": "NOPE"}, {**base, "mode": "reply_lost"}, {k: v for k, v in base.items() if k != "target"}, {**base, "to_tick": 1}):
        with pytest.raises(ValueError):
            c.fault(bad)
    c.fault(base)
    c.clear_faults()
    assert c.faults == [] and len(c.fault_log()) == 1


def test_client_sees_external_unavailable_over_the_socket(tmp_path):
    sp = tmp_path / "systems.json"
    sp.write_text(json.dumps(load_systems("manufacturing")))
    p = start_external(tmp_path / "ext", sp, os.path.join(tempfile.mkdtemp(prefix="r3sock"), "s"))
    try:
        ctl = p.client()
        root = ctl.issue_root("dep", "ERP")
        cap = extcap.attenuate(root, system="ERP", operation="expedite", target=TARGET, payload_digest=payload_digest(PAY),
                               correlation="r#0", max_uses=1, not_after_tick=9)
        ctl.advance(1)
        ctl.outage("ERP", "dep", 1, 3)
        with pytest.raises(ExternalUnavailable) as ei:
            ctl.data_only().write(cap, "expedite", TARGET, PAY, "adp")
        assert str(ei.value) == "EXT:ERP" and isinstance(ei.value, ExternalError) and isinstance(ei.value, DependencyUnavailable)
        assert ctl.fault_log()[0]["system"] == "ERP"
        with pytest.raises(ExternalError, match="not available on the data plane"):
            _call(p.sock_path, {"op": "fault", "cmd": {}})
        ctl.advance(3)
        assert ctl.data_only().write(cap, "expedite", TARGET, PAY, "adp").status == "applied"
    finally:
        out = p.close()
    con = sqlite3.connect(f"file:{Path(p.ext_dir) / 'external.db'}?mode=ro", uri=True)
    assert [r[0] for r in con.execute("SELECT reason FROM audit ORDER BY seq")] == ["unavailable", ""]
    con.close()


# ---- G5-E4: `unavailable` rows never attribute from unverified claims ------------------------------------------------
def _forged(c, **kw):
    nonce, steps, _ = extcap._decode(cap_for(c, **kw))
    return extcap._encode(nonce, steps, bytes(32))


def _outage(c, to=5):
    c.fault({"op": "outage", "deployment": "dep1", "target": "ERP", "from_tick": 1, "to_tick": to, "mode": "drop"})
    c.advance(1)


def test_g5e4_honest_cap_in_outage_row_is_unattributed_with_separate_unverified_claim():
    c = ExternalWorldCore(tempfile.mkdtemp(prefix="r3x"), load_systems("manufacturing"), root_key=KEY)
    cap = cap_for(c)
    _outage(c)
    with pytest.raises(Unavailable):
        c.write(cap, "expedite", TARGET, PAY, "adp")
    row = audit(c)[-1]
    assert row["reason"] == "unavailable" and row["deployment"] == "" and row["system"] == "" and row["cap_chain"] == ""
    assert row["correlation"] == ""
    claim = c.unverified_claims()[row["seq"]]
    assert claim["deployment"] == "dep1" and claim["system"] == "ERP" and ["correlation", "r1#0"] in claim["caveats"]
    assert eff_count(c) == 0


def test_g5e4_forged_cap_claiming_a_deployment_in_outage_is_unavailable_with_no_effect_and_no_attribution():
    c = ExternalWorldCore(tempfile.mkdtemp(prefix="r3x"), load_systems("manufacturing"), root_key=KEY)
    forged = _forged(c)
    _outage(c)
    with pytest.raises(Unavailable):
        c.write(forged, "expedite", TARGET, PAY, "adp")
    row = audit(c)[-1]
    assert row["reason"] == "unavailable" and row["deployment"] == "" and row["system"] == "" and eff_count(c) == 0
    assert c.unverified_claims()[row["seq"]]["deployment"] == "dep1"
    assert [r for r in audit(c) if r["deployment"] == "dep1"] == []                  # nothing attributed to dep1


def test_g5e4_same_forged_cap_outside_the_outage_is_still_bad_signature():
    c = ExternalWorldCore(tempfile.mkdtemp(prefix="r3x"), load_systems("manufacturing"), root_key=KEY)
    forged = _forged(c)
    c.fault({"op": "outage", "deployment": "dep1", "target": "ERP", "from_tick": 3, "to_tick": 5, "mode": "drop"})
    assert c.write(forged, "expedite", TARGET, PAY, "adp")["reason"] == "bad_signature"      # tick 0: before the window
    c.advance(5)
    assert c.write(forged, "expedite", TARGET, PAY, "adp")["reason"] == "bad_signature"      # after the window
    assert c.unverified_claims() == {} and eff_count(c) == 0


def test_g5e4_schema_rejects_an_unavailable_row_with_a_deployment_or_other_attribution():
    c = ExternalWorldCore(tempfile.mkdtemp(prefix="r3x"), load_systems("manufacturing"), root_key=KEY)
    cap = cap_for(c)
    _outage(c)
    with pytest.raises(Unavailable):
        c.write(cap, "expedite", TARGET, PAY, "adp")
    row = audit(c)[-1]
    good = {k: v for k, v in row.items()}
    good["unverified_claim"] = c.unverified_claims()[row["seq"]]
    validate_audit_row(good)
    validate_audit_row({**good, "deployment": None})
    for bad in ({**good, "deployment": "dep1"}, {**good, "system": "ERP"}, {**good, "cap_chain": "a" * 64},
                {**good, "reason": "bad_signature"}, {**good, "unverified_claim": {"system": "ERP"}}):
        with pytest.raises(ValueError):
            validate_audit_row(bad)
