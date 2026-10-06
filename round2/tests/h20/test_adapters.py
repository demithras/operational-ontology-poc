"""Adapter audit: clean on the real adapters, red on planted governance; taint known-negative; the Engine owns idempotency."""
import pytest

from eoo_exp.util import ROOT
from eoo_h20 import adapter_dynamic as AD
from eoo_h20 import adapter_static as AS
from eoo_h20.trace import Tracer

WMS = "domains/manufacturing/adapters/wms_fake.py"


def test_adapter_file_set_covers_both_domains_and_the_git_store():
    files = AS.adapter_files()
    assert {"domains/manufacturing/adapters/wms_fake.py", "domains/manufacturing/adapters/erp_mes_fake.py", "domains/project/adapters/git_fake.py",
            "src/eoo_engine_git/adapter.py", "src/eoo_engine_git/store.py"} <= set(files)


def test_real_adapters_are_clean_with_no_declared_exception():  # Engine v1.2: the strict count is 0 with an EMPTY list
    a = AS.audit()
    assert AS.DECLARED_EXCEPTIONS == [] and a["declared_exceptions"] == []
    assert a["violations"] == 0 and a["declared_hits"] == 0 and sum(len(r["declared"]) for r in a["files"]) == 0
    assert a["allowed"] and a["forbidden"] == ["authority checks", "policy evaluation", "precondition evaluation", "idempotency decisions",
                                               "provenance writing", "action lifecycle state changes"]


def _mut(extra_def: str, branch: str) -> dict:
    src = (ROOT / WMS).read_text()
    src = src.replace('        xid = effect["execution"]\n', f'        xid = effect["execution"]\n{branch}', 1).replace("    # -- fake internals", extra_def + "    # -- fake internals", 1)
    return {WMS: src}


@pytest.mark.parametrize("extra,branch,kind", [
    ("    def _policy_ok(self, p):\n        return True\n\n", "        if not self._policy_ok(payload):\n            raise ValueError\n", "governance_definition"),
    ("", "        if effect['principal'] == 'x':\n            raise ValueError\n", "governance_term_in_decision"),
    ("", "        if self.state == 'APPROVED':\n            pass\n", "lifecycle_state_literal"),
    ("", "        if effect['idempotency_key'] in self.seen:\n            raise ValueError\n", "governance_term_in_decision"),
])
def test_planted_governance_is_flagged(extra, branch, kind):
    a = AS.audit(overrides=_mut(extra, branch))
    assert a["violations"] >= 1 and kind in {v["kind"] for r in a["files"] for v in r["violations"]}


def test_planted_engine_governance_import_is_flagged():
    src = (ROOT / WMS).read_text() + "\nfrom eoo_engine.authority import evaluate\nfrom eoo_engine import Principal\n"
    a = AS.audit(overrides={WMS: src})
    assert [v["kind"] for r in a["files"] for v in r["violations"]] == ["engine_governance_import", "engine_governance_import"]


def test_innocuous_names_are_a_declared_blind_spot_of_the_static_audit():
    a = AS.audit(overrides=_mut("    def _within(self, p):\n        return True\n\n", "        if not self._within(payload):\n            raise ValueError\n"))
    assert a["violations"] == 0  # ... and the behavioural probe is what catches it (tests/h20/test_mutants.py)


def test_no_exception_left_a_planted_provenance_branch_counts():
    src = (ROOT / "src/eoo_engine_git/store.py").read_text() + "\n\ndef _msg(self):\n    if not self.provenance:\n        return 1\n"
    a = AS.audit(overrides={"src/eoo_engine_git/store.py": src})
    assert a["violations"] == 1 and a["declared_hits"] == 0


def test_taint_known_negative_sees_a_journal_write_from_an_adapter():
    r = AD.taint_known_negative(Tracer)
    assert r["detected"] and r["violations"][0]["adapter"] == "WmsFake.apply"


def test_engine_owns_the_idempotency_decision():
    rows = AD.idempotency_probe()
    assert {r["domain"] for r in rows} == {"manufacturing", "project"} and all(r["engine_decided"] for r in rows)
    assert all(r["adapter_calls_after_retry"] == r["adapter_calls_after_first"] == 1 for r in rows)


def test_ok_mode_probe_is_clean_and_sees_a_refusing_adapter():
    assert all(r["carried_out"] for r in AD.ok_mode_probe())
    src = (ROOT / WMS).read_text().replace('        xid = effect["execution"]\n', '        xid = effect["execution"]\n        if payload["quantity"] > 10:\n            raise WmsUnavailable("no")\n', 1)
    from eoo_h20.mutants import _adapter_class
    bad = [r for r in AD.ok_mode_probe({"manufacturing": _adapter_class(src, "WmsFake")}) if not r["carried_out"]]
    assert bad and bad[0]["state"] == "OUTCOME_UNKNOWN"


def test_tracer_records_adapter_calls_with_the_taint_set():
    t = Tracer()
    with t.installed():
        AD.idempotency_probe()
    assert t.adapter_calls[("WmsFake", "apply")] >= 1 and t.adapter_violations == []


# ---- behavioural twin of provenance_composition: what the adapter WROTE == effect['envelope_text'], byte for byte ----
def test_provenance_verbatim_known_positive_real_adapters_write_the_envelope_verbatim():
    from eoo_h20 import provenance_writes as PW
    r = PW.probes(Tracer)
    assert r["known_positive_clean"]
    for name, x in r["known_positive"].items():
        assert x["adapter_provenance_writes"] > 0 and x["adapter_provenance_verbatim_mismatches"] == 0, (name, x)
    assert set(r["known_positive"]["git_fake"]["by_adapter"]) == {"GitFake"} and set(r["known_positive"]["git_adapter"]["by_adapter"]) == {"GitAdapter"}


def test_provenance_verbatim_known_negative_an_appended_non_eoo_line_is_detected():
    from eoo_h20 import provenance_writes as PW
    r = PW.probes(Tracer)
    assert r["known_negative_detected"]
    for name, x in r["known_negative"].items():  # label "Writer: w1" does not start with EOO-: invisible to the static rule
        assert x["adapter_provenance_verbatim_mismatches"] == 1, (name, x)
        m = x["first_mismatches"][0]
        assert "Writer: w1" in m["written"] or len(m["written"]) == 300  # truncated example still names the divergent adapter
        assert m["adapter"] in ("GitFake", "GitAdapter")
    from eoo_h20 import adapter_static as AS
    assert AS.audit()["violations"] == 0  # the static rule alone sees nothing here: only the behavioural check closes the blind spot


def test_tracer_counts_a_batch_commit_once_and_ignores_stores_it_cannot_read():
    t = Tracer()
    with t.installed():
        AD.idempotency_probe()  # manufacturing (WmsFake: no readable commit store) + project (GitFake)
    n = t.provenance_numbers()
    assert n["by_adapter"] == {"GitFake": 1} and n["adapter_provenance_verbatim_mismatches"] == 0
