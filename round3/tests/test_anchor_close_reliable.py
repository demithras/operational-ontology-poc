"""Anchor close must deliver its reply (key + head) before the server process exits, even on a busy host."""
import tempfile
from pathlib import Path

from r3_shared.anchor import start_anchor, verify_anchor_log


def test_close_reply_is_always_delivered_with_exact_head():
    for i in range(40):
        d = Path(tempfile.mkdtemp(prefix="ac"))
        ap = start_anchor(d / "a", d / "s.sock")
        c = ap.client()
        for seq in (1, 2, 3):
            c.append("s", seq, f"d{seq}", "r")
        r = ap.close()
        assert r["head"]["entries"] == 3 and len(r["key"]) == 64, i
        assert verify_anchor_log(d / "a", expected_head=r["head"])["ok"], i
        assert ap.proc.returncode == 0, i
