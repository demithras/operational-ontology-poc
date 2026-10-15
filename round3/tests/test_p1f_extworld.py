"""P1f-2 ExternalWorld: every refusal reason in the frozen order, an audit row on every attempt, server tick monotone, the
control plane unreachable from the data plane, ledger/sysstate semantics. In-process core (known root key) + real subprocess."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from r3_shared import extcap
from r3_shared.extadapter import payload_digest
from r3_shared.extsystems import load_systems
from r3_shared.extworld import ExternalError, start_external
from r3_shared.extworld_core import REFUSALS, ExternalWorldCore
from tests.p1f_util import KEY, PAY, TARGET, audit, cap_for, core, eff_count

W = lambda c, cap, op="expedite", tgt=TARGET, pay=None: c.write(cap, op, tgt, PAY if pay is None else pay, "adp")  # noqa: E731


def test_refusal_vocabulary_is_the_frozen_order():
    assert REFUSALS == ("bad_signature", "unknown_root", "system_mismatch", "operation_mismatch", "target_mismatch",
                        "payload_mismatch", "correlation_missing", "expired", "uses_exhausted")


def test_applied_write_updates_ledger_audit_and_sysstate():
    c = core()
    c.advance(2)
    r = W(c, cap_for(c))
    assert r == {"status": "applied", "reason": "", "seq": 1}
    a = audit(c)
    assert [(x["outcome"], x["reason"], x["tick"], x["deployment"], x["correlation"]) for x in a] == [("applied", "", 2, "dep1", "r1#0")]
    assert c._get("ERP", "po:PO-1") == {"expectedAt": -1}          # frozen erp_expedite semantics: expectedAt -= 1
    assert eff_count(c) == 1


def _cases(c):
    """One case per reason; each returns (cap, operation, target, payload)."""
    good = lambda **kw: cap_for(c, **kw)  # noqa: E731
    forged = good()[:-3] + ("AAA" if not good().endswith("AAA") else "BBB")
    unissued = extcap.attenuate(extcap.mint_root(KEY, "never-issued", "ERP", "depX"), correlation="x#0", max_uses=1)
    wide = extcap.attenuate(c.issue_root("dep1", "ERP"), correlation="w#0", max_uses=1)     # system-only cap + correlation
    return {
        "bad_signature": (forged, "expedite", TARGET, PAY),
        "unknown_root": (unissued, "expedite", TARGET, PAY),
        "system_mismatch": (extcap.attenuate(good(), system="WMS"), "expedite", TARGET, PAY),
        "operation_mismatch": (good(operation="other"), "expedite", TARGET, PAY),
        "target_mismatch": (good(), "expedite", "po:PO-2", PAY),
        "payload_mismatch": (good(), "expedite", TARGET, {**PAY, "expedite_fee": 11}),
        "correlation_missing": (extcap.attenuate(c.issue_root("dep1", "ERP"), operation="expedite"), "expedite", TARGET, PAY),
        "expired": (good(not_after=1), "expedite", TARGET, PAY),
        "uses_exhausted": None,
    }, wide


@pytest.mark.parametrize("reason", REFUSALS)
def test_each_refusal_reason_refuses_and_is_audited(reason):
    c = core()
    c.advance(5)
    cases, _ = _cases(c)
    if reason == "uses_exhausted":
        cap = cap_for(c, correlation="u#0", not_after=9)
        assert W(c, cap)["status"] == "applied"
        args = (cap, "expedite", TARGET, PAY)
    else:
        args = cases[reason]
    before = eff_count(c)
    r = c.write(args[0], args[1], args[2], args[3], "adp")
    assert (r["status"], r["reason"]) == ("refused", reason)
    assert eff_count(c) == before                                   # nothing applied by a refusal
    last = audit(c)[-1]
    assert (last["outcome"], last["reason"], last["seq"]) == ("refused", reason, r["seq"])
    assert last["adapter_id"] == "adp" and last["operation"] == args[1] and last["target"] == args[2]
    assert last["payload_digest"] == payload_digest(args[3])


def test_every_attempt_appends_exactly_one_audit_row():
    c = core()
    caps = [cap_for(c, correlation=f"r{i}#0") for i in range(3)]
    n = 0
    for cap in caps + caps:                                                # 3 applied + 3 uses_exhausted
        W(c, cap)
        n += 1
        assert len(audit(c)) == n
    assert [a["outcome"] for a in audit(c)] == ["applied"] * 3 + ["refused"] * 3
    assert eff_count(c) == 3


def test_bad_signature_row_is_unattributed():
    c = core()
    cap = cap_for(c)
    W(c, cap[:-2] + "AA")
    a = audit(c)[-1]
    assert (a["reason"], a["deployment"], a["cap_chain"], a["correlation"], a["system"]) == ("bad_signature", "", "", "", "")


@pytest.mark.parametrize("first,second", [
    ("bad_signature", "target_mismatch"), ("unknown_root", "target_mismatch"), ("system_mismatch", "operation_mismatch"),
    ("operation_mismatch", "target_mismatch"), ("target_mismatch", "payload_mismatch"), ("payload_mismatch", "expired"),
    ("correlation_missing", "expired"), ("expired", "uses_exhausted")])
def test_two_failing_reasons_report_the_earlier(first, second):
    c = core()
    c.advance(5)
    good = lambda **kw: cap_for(c, **kw)  # noqa: E731
    g = good()
    cases = {
        ("bad_signature", "target_mismatch"): (g[:-2] + "AA", TARGET + "x", PAY),
        ("unknown_root", "target_mismatch"): (extcap.attenuate(extcap.mint_root(KEY, "nope", "ERP", "d"), correlation="x#0"), TARGET + "x", PAY),
        ("system_mismatch", "operation_mismatch"): (extcap.attenuate(g, system="WMS", operation="zzz"), "expedite", PAY),
        ("operation_mismatch", "target_mismatch"): (good(operation="zzz"), TARGET + "x", PAY),
        ("target_mismatch", "payload_mismatch"): (g, TARGET + "x", {**PAY, "expedite_fee": 1}),
        ("payload_mismatch", "expired"): (good(not_after=1), TARGET, {**PAY, "expedite_fee": 1}),
        ("correlation_missing", "expired"): (extcap.attenuate(c.issue_root("dep1", "ERP"), not_after_tick=1), TARGET, PAY),
        ("expired", "uses_exhausted"): (good(not_after=9, correlation="e#0"), TARGET, PAY),
    }
    cap, tgt, pay = cases[(first, second)]
    if (first, second) == ("expired", "uses_exhausted"):
        assert W(c, cap, tgt=tgt, pay=pay)["status"] == "applied"        # now exhausted ...
        c.advance(10)                                                    # ... and expired
    r = c.write(cap, "expedite", tgt, pay, "adp")
    assert r["reason"] == first


def test_uses_counted_per_chain_not_per_correlation_string():
    c = core()
    cap = cap_for(c, max_uses=2)
    narrower = extcap.attenuate(cap, not_after_tick=9)                    # same chain id
    assert [W(c, x)["status"] for x in (cap, narrower, cap)] == ["applied", "applied", "refused"]
    assert W(c, cap_for(c, max_uses=2))["status"] == "refused"            # identical caveats = same chain = still exhausted


def test_over_used_idempotent_set_cap_allows_exactly_max_uses():
    c = core()
    pay = {"work_order_id": "WO-1", "new_planned_start": 7}
    cap = cap_for(c, system="MES", operation="reschedule", target="wo:WO-1", payload=pay, max_uses=3)
    out = [c.write(cap, "reschedule", "wo:WO-1", pay, "adp")["status"] for _ in range(5)]
    assert out == ["applied"] * 3 + ["refused"] * 2
    assert c._get("MES", "wo:WO-1") == {"plannedStart": 7}


def test_forged_and_out_of_scope_caps_leave_no_effect():
    c = core()
    c.advance(3)
    wide = extcap.attenuate(c.issue_root("dep1", "WMS"), operation="transfer", correlation="w#0", max_uses=9)   # no target/payload caveat
    # a cap that really IS broad (system+operation+correlation only) is honoured by the server: scoping is the variant's job,
    # which is exactly why credential_scope_broadened is detectable only via the ledger (R28-14).
    assert c.write(wide, "transfer", "transfer:Z@A->B", {"part": "Z"}, "adp")["status"] == "applied"
    narrow = cap_for(c, system="WMS", operation="transfer", target="transfer:P@A->B", payload={"part": "P"}, correlation="n#0")
    for tgt, pay in (("transfer:Z@A->B", {"part": "P"}), ("transfer:P@A->B", {"part": "Z"})):
        assert c.write(narrow, "transfer", tgt, pay, "adp")["status"] == "refused"
    assert eff_count(c) == 1


def test_server_tick_is_monotone_and_stamps_rows():
    c = core()
    c.advance(4)
    c.advance(4)
    with pytest.raises(ValueError):
        c.advance(3)
    for bad in (-1, 1.5, True, "5"):
        with pytest.raises(ValueError):
            c.advance(bad)
    W(c, cap_for(c))
    c.advance(6)
    W(c, cap_for(c, correlation="r2#0"))
    assert [a["tick"] for a in audit(c)] == [4, 6]


def test_systems_must_validate_and_ledger_not_reused(tmp_path):
    with pytest.raises(Exception):
        ExternalWorldCore(tmp_path / "a", {"version": "r3-external-1"})
    c = ExternalWorldCore(tmp_path / "b", load_systems("manufacturing"))
    c.close()
    with pytest.raises(FileExistsError):
        ExternalWorldCore(tmp_path / "b", load_systems("manufacturing"))


def test_issue_root_is_deterministic_per_deployment_and_system():
    c = core()
    assert c.issue_root("d", "ERP") == c.issue_root("d", "ERP") != c.issue_root("d2", "ERP") != c.issue_root("d", "WMS")
    with pytest.raises(ValueError):
        c.issue_root("d", "NOPE")


# ---- the real service process ---------------------------------------------------------------------------------------
@pytest.fixture
def svc(tmp_path):
    sp = tmp_path / "sys.json"
    sp.write_text(json.dumps(load_systems("manufacturing")))
    sock = os.path.join(tempfile.mkdtemp(prefix="r3sock"), "s")
    p = start_external(tmp_path / "ext", sp, sock)
    yield p
    if p.proc.poll() is None:
        p.close()


def test_data_plane_cannot_reach_the_control_plane(svc):
    from r3_shared.extworld import _call
    for op in ("advance", "issue_root", "observer_key", "close", "seed", "tick"):
        with pytest.raises(ExternalError, match="not available on the data plane"):
            _call(svc.sock_path, {"op": op, "tick": 99, "deployment": "d", "system": "ERP"})
    assert svc.client().tick() == 0                                        # untouched
    data_only = svc.client().data_only()
    for fn in (lambda: data_only.advance(5), lambda: data_only.issue_root("d", "ERP"), lambda: data_only.close(),
               lambda: data_only.observer_key("d")):
        with pytest.raises(ExternalError, match="control plane not available"):
            fn()
    with pytest.raises(ExternalError, match="not available on the control plane"):
        from r3_shared.extworld import _call as call
        call(svc.ctl_path, {"op": "write"})


def test_service_write_roundtrip_and_close_reveals_key(svc):
    c = svc.client()
    c.advance(1)
    root = c.issue_root("dep1", "ERP")
    cap = extcap.attenuate(root, operation="expedite", target=TARGET, payload_digest=payload_digest(PAY), correlation="r#0",
                           max_uses=1, not_after_tick=5)
    d = c.data_only()
    assert d.write(cap, "expedite", TARGET, PAY, "adp").status == "applied"
    r = d.write(cap, "expedite", TARGET, PAY, "adp")
    assert (r.status, r.reason) == ("refused", "uses_exhausted") and r.seq == 2
    out = svc.close()
    assert len(out["root_key_hex"]) == 64 and out["head"] == {"effects": 1, "audit": 2}
    assert (Path(svc.ext_dir) / "KEY.revealed").read_text() == out["root_key_hex"]
    assert extcap.verify(bytes.fromhex(out["root_key_hex"]), cap)         # evaluator can re-verify every applied cap chain
    with pytest.raises(ExternalError):
        d.write(cap, "expedite", TARGET, PAY, "adp")


def test_server_refuses_to_start_without_dir_or_systems(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    for args in ([], ["--dir", str(tmp_path / "x")], ["--dir", str(tmp_path / "x"), "--systems", str(tmp_path / "s.json")]):
        p = subprocess.run([sys.executable, "-m", "r3_shared.extworld_server", *args], capture_output=True, text=True, env=env, timeout=30)
        assert p.returncode != 0 and "READY" not in p.stdout
    assert not (tmp_path / "x" / "external.db").exists()
