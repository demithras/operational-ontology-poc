"""G3 fix3 (G3-E22): effect_digest of an OWN decision is true only if every touched object/field is low; args_digest keeps the exemption."""
import pytest

from g2_rig import new_anchor
from g3_rig import G3Rig
from paladin.sovview import LowView
from r3_shared.histstore import HistoryStore

ATT = ("attach_evidence", {"hypothesis": "H-C", "evidence": "EV-C1"})
HID = {"redacted": "effect_digest"}


@pytest.fixture
def rig(tmp_path_factory):
    ap = new_anchor(tmp_path_factory.mktemp("anchor"))
    tmp = tmp_path_factory.mktemp("rig")
    r = G3Rig(tmp, v3=True, history=HistoryStore(str(tmp / "h.sqlite")), anchor=ap.client())
    r.res = r.dep.direct(r.tok("researcher-1"), *ATT, request_id="d1")
    yield r
    ap.close()


def _core(rig):
    return rig.dep._c


def _rec(rig):
    return _core(rig).ledger.get_meta("dec:d1")


def _view(fields):
    v = LowView()
    for ref, fs in fields.items():
        v.objects[ref] = {f: 0 for f in fs}
        v.fields_of[ref] = frozenset(fs)
    return v


def test_own_write_touching_only_visible_fields_keeps_the_true_digest(rig):
    d = rig.dep.prov_decision(rig.tok("researcher-1"), "d1").body["decision"]
    assert d["effect_digest"] == _rec(rig)["s"]["effect_digest"] and isinstance(d["effect_digest"], str)
    assert d["args_digest"] == _rec(rig)["s"]["args_digest"]


def _own_write(rig):
    """A synthetic own decision whose rows create an object with a visible and a hidden property (the live attach_evidence
    transaction writes only a commit mark, so the row shapes are supplied directly)."""
    rec = dict(_rec(rig))
    rec["rows"] = [{"k": "create", "r": "Evidence:EV-X", "f": ["status", "path"]}, {"k": "update", "r": "Hypothesis:H-C", "f": ["state"]}]
    return rec["s"]["subject"], rec


def test_own_write_touching_a_hidden_field_is_redacted(rig):
    core = _core(rig)
    own, rec = _own_write(rig)
    full = {"Evidence:EV-X": {"status", "path"}, "Hypothesis:H-C": {"state"}}
    assert core._eff_low(own, rec, _view(full)) is True                       # all touched fields low -> true digest
    assert core._eff_low(own, rec, _view({**full, "Evidence:EV-X": {"status"}})) is False   # hidden `path`
    assert core._eff_low(own, rec, _view({"Evidence:EV-X": {"status", "path"}})) is False   # touched object hidden


def test_own_args_digest_stays_true_even_when_the_effect_digest_is_redacted(rig):
    core = _core(rig)
    own, rec = _own_write(rig)
    empty = _view({})
    assert core._args_low(own, rec, empty) is True and core._eff_low(own, rec, empty) is False


def test_external_effect_rows_are_never_low(rig):
    core = _core(rig)
    rec = {"s": {"subject": "u", "on_behalf_of": None}, "refs": [], "edges": [], "rows": [{"k": "external"}]}
    assert core._eff_low("u", rec, _view({})) is False
