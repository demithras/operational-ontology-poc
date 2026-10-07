import json
import os
import shutil
import tempfile
import pytest
from r3_shared.anchor import AnchorClient, AnchorError, start_anchor, verify_anchor_log, LOG_NAME, KEY_NAME

R = "a" * 64


@pytest.fixture
def anchor(tmp_path):
    sockdir = tempfile.mkdtemp(prefix="anc")  # short path: AF_UNIX sun_path limit
    ap = start_anchor(str(tmp_path / "anchor"), os.path.join(sockdir, "s"))
    yield ap
    if ap.proc.poll() is None:
        ap.proc.kill()
    shutil.rmtree(sockdir, ignore_errors=True)


def filled(anchor):
    c = anchor.client()
    for s in (1, 2, 3):
        c.append("st-A", s, f"d{s}", f"{s}" * 64)
    c.append("st-B", 1, "x1", "b" * 64)
    return c


def test_separate_process_and_roundtrip(anchor):
    assert anchor.pid != os.getpid() and anchor.proc.poll() is None
    c = filled(anchor)
    e = c.get("st-A", 2)
    assert (e["decision_id"], e["root"], e["i"]) == ("d2", "2" * 64, 1) and len(e["mac"]) == 64
    assert c.lookup("st-A", "d3")["seq"] == 3 and c.lookup("st-A", "nope") is None and c.get("st-A", 9) is None
    assert c.head("st-A")["seq"] == 3 and c.head("st-B")["seq"] == 1 and c.head("zz") is None
    assert c.append("st-B", 2, "x2", R)["prev_entry"] != "0" * 64


def test_seq_gap_dup_and_malformed_refused(anchor):
    c = anchor.client()
    c.append("s", 1, "d1", R)
    with pytest.raises(AnchorError, match="duplicate"):
        c.append("s", 1, "d1b", R)
    with pytest.raises(AnchorError, match="gap"):
        c.append("s", 3, "d3", R)
    with pytest.raises(AnchorError, match="gap"):
        c.append("fresh", 2, "d", R)
    with pytest.raises(AnchorError, match="malformed"):
        c.append("s", "2", "d", R)
    with pytest.raises(AnchorError, match="malformed"):
        c.append("s", True, "d", R)
    assert c.head("s")["seq"] == 1  # refusals changed nothing
    assert len(open(os.path.join(anchor.anchor_dir, LOG_NAME), "rb").read().splitlines()) == 1


def test_close_reveals_key_and_clean_log_verifies(anchor):
    d = anchor.anchor_dir
    c = filled(anchor)
    assert not os.path.exists(os.path.join(d, KEY_NAME))  # key never on disk before close
    info = anchor.close()
    assert len(bytes.fromhex(info["key"])) == 32 and info["head"]["entries"] == 4
    v = verify_anchor_log(d, expected_head=info["head"])
    assert v["ok"] and v["entries"] == 4 and v["errors"] == []
    with pytest.raises(AnchorError):
        c.append("st-A", 4, "d4", R)  # closed


def _closed(anchor):
    filled(anchor)
    info = anchor.close()
    return anchor.anchor_dir, info, os.path.join(anchor.anchor_dir, LOG_NAME)


def test_known_negative_edited_line(anchor):
    d, info, lp = _closed(anchor)
    lines = open(lp).read().splitlines()
    e = json.loads(lines[1])
    e["root"] = "f" * 64                       # edit content, keep the old mac
    lines[1] = json.dumps(e, sort_keys=True, separators=(",", ":"))
    open(lp, "w").write("\n".join(lines) + "\n")
    v = verify_anchor_log(d, expected_head=info["head"])
    assert not v["ok"] and not v["mac_ok"] and not v["chain_ok"]  # bad MAC at line 1 and chain break at line 2


def test_known_negative_deleted_middle_and_last_line(anchor):
    d, info, lp = _closed(anchor)
    lines = open(lp).read().splitlines()
    open(lp, "w").write("\n".join(lines[:1] + lines[2:]) + "\n")
    v = verify_anchor_log(d)
    assert not v["ok"] and not v["chain_ok"]
    open(lp, "w").write("\n".join(lines[:-1]) + "\n")  # tail truncation: chain intact, head must catch it
    v = verify_anchor_log(d, expected_head=info["head"])
    assert v["chain_ok"] and v["mac_ok"] and not v["head_ok"] and not v["ok"]


def test_known_negative_forged_mac_with_recomputed_chain(anchor):
    d, info, lp = _closed(anchor)
    lines = open(lp, "rb").read().splitlines()
    import hashlib
    e = json.loads(lines[-1])
    e["root"] = "e" * 64                       # forger rewrites the LAST entry; no key => cannot make the MAC valid
    e["mac"] = hashlib.sha256(b"guess").hexdigest()
    lines[-1] = json.dumps(e, sort_keys=True, separators=(",", ":")).encode()
    open(lp, "wb").write(b"\n".join(lines) + b"\n")
    v = verify_anchor_log(d)
    assert not v["ok"] and not v["mac_ok"] and not v["head_ok"]


def test_unclosed_log_is_not_verifiable(anchor):
    filled(anchor)
    v = verify_anchor_log(anchor.anchor_dir)
    assert not v["ok"] and any("key not revealed" in x for x in v["errors"])
    assert verify_anchor_log(anchor.anchor_dir, key=b"k" * 32)["mac_ok"] is False


def test_start_refuses_existing_log_and_client_unreachable(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / LOG_NAME).write_text("")
    with pytest.raises(AnchorError):
        start_anchor(str(tmp_path / "a"), str(tmp_path / "s"))
    with pytest.raises(AnchorError, match="unreachable"):
        AnchorClient(str(tmp_path / "nosock")).head("s")
