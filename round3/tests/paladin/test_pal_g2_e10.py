"""E-10: replay re-derives the authority verdict only for OK/DENIED decisions; INVALID decisions keep every other check."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from g2_hist import envelopes, tamper_envelope  # noqa: E402
from g2_rig import new_anchor  # noqa: E402
from test_pal_g2_project import create, mk  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(scope="module")
def anchor(tmp_path_factory):
    ap = new_anchor(tmp_path_factory.mktemp("anchor"))
    yield ap
    ap.close()


@pytest.fixture
def inv(tmp_path, anchor):
    r = mk(tmp_path, history=True, anchor=anchor.client())
    res = r.dep.direct(r.token("researcher-1"), "flag_orphan_component", {"component": "C-NOPE"}, on_behalf_of=None, request_id="inv1")
    assert res.status == "INVALID", res  # nonexistent target of an AUTHORISED caller, no deny rule fires (flag_orphan_component: classify/stale/ephemeral only): INVALID (G3-E17 order: deny rules -> existence); evaluate_hypothesis on an absent target is a lifecycle DENY since fix9
    assert create(r, "researcher-1", None, "ok1").status == "OK"
    return r


def test_e10_clean_invalid_decision_replays_verified(inv):
    assert envelopes(inv)["inv1"]["decision"]["status"] == "INVALID"
    res = inv.deploy(state_dir=None).replay("inv1")
    assert (res.status, res.reason) == ("VERIFIED", "ok"), res
    assert inv.deploy(state_dir=None).replay("ok1").status == "VERIFIED"


def test_e10_tampered_invalid_decision_still_detected(inv):
    tamper_envelope(inv, "inv1", lambda e: e["decision"].__setitem__("operation", "reschedule_work_order"))
    assert inv.deploy(state_dir=None).replay("inv1").status in ("TAMPERED", "UNRESOLVED")
    tv = inv.tamper()
    d = envelopes(inv)["inv1"]["artifacts"]["policy"]
    tv.delete(f"art/{d}")
    assert inv.deploy(state_dir=None).replay("inv1").status in ("TAMPERED", "UNRESOLVED")
