"""Static rule provenance_composition (Engine v1.2): an adapter that composes provenance itself is flagged; writing the
Engine's envelope text verbatim is clean. Known-negative = the v1.1 trailer code of GitStore, planted back."""
import pytest

from eoo_exp.util import ROOT
from eoo_h20 import adapter_static as AS

STORE, ADAPTER = "src/eoo_engine_git/store.py", "src/eoo_engine_git/adapter.py"

# The v1.1 code removed by Engine v1.2 (GitStore._msg + the commit_rows trailer block), verbatim in substance.
OLD_TRAILERS = '''

def _msg_v11(self, subject, trailers):
    return subject + "\\\\n\\\\n" + "\\\\n".join(f"{k}: {v}" for k, v in trailers.items()) + "\\\\n"


def _trailers_v11(self, meta, writer, rows, base, head, how, files):
    return {"EOO-Execution": meta["execution"], "EOO-Writer": writer, "EOO-Action": meta["action"],
            "EOO-Idempotency-Key": meta.get("idempotency_key") or "-", "EOO-Effects": " ".join(meta["effects"]),
            "EOO-Targets": ",".join(t for t, _ in rows), "EOO-Base": base, "EOO-Head-At-Write": head or "-",
            "EOO-Merge": how, "EOO-Engine-Version": self.engine_version}
'''


def _kinds(a):
    return [v for r in a["files"] for v in r["violations"] if v["kind"] == "provenance_composition"]


def test_known_positive_the_real_verbatim_write_is_clean():
    a = AS.audit()
    assert _kinds(a) == [] and a["violations"] == 0
    assert 'message=effect.get("envelope_text")' in (ROOT / ADAPTER).read_text()  # the verbatim pass-through the rule accepts


def test_known_negative_the_old_trailer_code_is_flagged():
    a = AS.audit(overrides={STORE: (ROOT / STORE).read_text() + OLD_TRAILERS})
    hits = _kinds(a)
    labels = {v["value"] for v in hits if v["how"] == "provenance label literal"}
    assert {"EOO-Execution", "EOO-Action", "EOO-Base", "EOO-Engine-Version"} <= labels
    assert {v["qual"] for v in hits} == {"_trailers_v11"} and a["declared_hits"] == 0


@pytest.mark.parametrize("snippet,how", [
    ('        msg = effect["envelope_text"] + "EOO-Base: x\\n"\n', "envelope_text altered, not written verbatim"),
    ('        msg = f"{effect.get(\'envelope_text\')}extra"\n', "envelope_text altered, not written verbatim"),
    ('        msg = effect["envelope_text"].replace("a", "b")\n', "envelope_text altered, not written verbatim"),
    ('        msg = "exec " + effect["envelope"]["execution"]\n', "reads structured envelope fields"),
])
def test_planted_composition_in_an_adapter_is_flagged(snippet, how):
    src = (ROOT / ADAPTER).read_text()
    anchor = '        eid, ex = effect["effect_id"], effect["execution"]\n'
    assert anchor in src
    a = AS.audit(overrides={ADAPTER: src.replace(anchor, anchor + snippet, 1)})
    assert how in {v["how"] for v in _kinds(a)}


def test_importing_the_engine_renderer_into_an_adapter_is_flagged():
    src = (ROOT / ADAPTER).read_text() + "\nfrom eoo_engine.provenance import render_envelope\n"
    a = AS.audit(overrides={ADAPTER: src})
    assert [v["kind"] for r in a["files"] for v in r["violations"]] == ["engine_governance_import"]
