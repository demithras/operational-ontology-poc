"""G5-E31: the unanchored_ack ordering check must not depend on the anchor service being reachable; an unreadable head after OK is a harness row."""
import json

from r3_harness.h29 import driver, judge, rc, services
from r3_harness.h29.judge_req import _anchor_entry_violation as V


def _old(seqs, before, after, fresh):
    """The pre-E31 function body (known-negative): an unreadable head at the reply meant 'nothing to order against'."""
    if not isinstance(after, int) or after < 0:
        return None
    b = before if isinstance(before, int) and before >= 0 else 0
    new = [x for x in seqs if x > b]
    if new:
        return None if new[0] <= after else {"why": "appended after"}
    return None


def test_ok_during_anchor_drop_entry_appended_after_heal_is_unanchored_ack():
    # head read from the log file at the reply = 4; the entry for this OK (seq 5) only lands after the heal
    assert V([5], 4, 4, True)["why"] == "anchor entry appended after the reply"
    # the old code read the head through the dropped service (-1) and returned None for the very same record
    assert _old([5], 4, -1, True) is None
    assert V([5], 4, -1, True) == {"harness": "anchor_head_unreadable", "why": "anchor head unreadable after an OK reply (G5-E31)"}
    assert V([5], 4, None, True)["harness"] == "anchor_head_unreadable"


def test_head_is_read_from_the_log_file(tmp_path):
    from r3_shared.anchor import LOG_NAME
    (tmp_path / LOG_NAME).write_text("".join(json.dumps({"stream": s, "seq": q}) + "\n" for s, q in (("a", 1), ("b", 1), ("a", 2))))
    assert services.anchor_head_from_log(tmp_path, "a") == 2 and services.anchor_head_from_log(tmp_path, "b") == 1
    assert services.anchor_head_from_log(tmp_path, "c") == 0
    assert services.anchor_head_from_log(tmp_path / "nope", "a") is None


def test_driver_and_rc_read_heads_without_the_anchor_service(tmp_path):
    from r3_shared.anchor import LOG_NAME
    (tmp_path / LOG_NAME).write_text(json.dumps({"stream": "s", "seq": 3}) + "\n")

    class Boom:
        def head(self, stream):
            raise ConnectionError("ANCHOR dropped")

    class Svc:
        anchor_dir, anchor = tmp_path, Boom()

    class D(driver.Run):
        def __init__(self):
            self.svc, self.stream, self.hist_path = Svc(), "s", None

    class Rep:
        status = "OK"

    d = D()
    assert d.anchor_head_after_ok(Rep()) == 3 and d.anchor_head_before() == 3 and rc._head(d, "s") == 3
    d.svc.anchor_dir = tmp_path / "gone"
    assert d.anchor_head_after_ok(Rep()) == -1                     # unreadable log after OK -> -1 -> harness row at the judge
    Rep.status = "DENIED"
    assert d.anchor_head_after_ok(Rep()) is None


def test_unreadable_head_row_blocks_the_run():
    assert "anchor_head_unreadable" in judge.BLOCKING
