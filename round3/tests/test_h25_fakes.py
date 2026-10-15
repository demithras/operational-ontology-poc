"""Known-negative fakes: each yields exactly its expected class set (ORACLE-AND-HARNESS-G3 A7)."""
import pytest

from r3_harness.h25 import boundary
from tests.h25_util import classes, fake

CLEAN = {"ok", "race_refusal_ok"}
VIOL = {"procedural_mismatch", "illegitimate_effect", "fabricated_judgment", "emergency_violation", "invalid_doc_accepted",
        "linearizability_violation", "unattributed_write", "writer_violation", "unlogged_write", "progress_loss",
        "domain_branch", "unsupported", "world_lock_timeout"}


def got(name):
    return {k for k, v in classes(fake(name)).items() if v and k in VIOL}


def test_honest_is_clean():
    assert got("fake-honest") == set()


def test_quorum_weakened():
    g = got("fake-quorumweak")
    assert "procedural_mismatch" in g and g & {"illegitimate_effect", "fabricated_judgment"} and g <= VIOL - {"unsupported"}


def test_autofill_is_fabricated_judgment():
    g = got("fake-autofill")
    assert "fabricated_judgment" in g and "procedural_mismatch" in g


def test_no_expiry_is_emergency_violation():
    assert "emergency_violation" in got("fake-noexpiry")


def test_precedence_inverted():
    assert "procedural_mismatch" in got("fake-precinverted")


def test_domain_branch_shows_in_corpus_and_audit():
    from r3_harness.h25 import audit
    assert "procedural_mismatch" in got("fake-domainbranch")
    r = audit.rename_audit(fake("fake-domainbranch"), 3, 80, domain="project", keep_roles=("admin",))
    assert r["domain_branch"] > 0
    assert audit.static_scan(sources=fake("fake-domainbranch").sources)["hit_count"] >= 1


def test_merit_reader_is_caught_by_boundary_probe():
    v = fake("fake-meritreader")
    assert sum(boundary.merit_probe(v, 2, i)["fabricated"] for i in range(80)) > 0


def test_ignores_judgments_is_procedural_mismatch_and_flip_mismatch():
    v = fake("fake-ignoresjudgments")
    assert "procedural_mismatch" in got("fake-ignoresjudgments")
    flips = [boundary.flip_probe(v, 2, i) for i in range(60)]
    assert sum(1 for f in flips if f["changed"] and "procedural_mismatch" in f["classes"]) > 0


def test_always_oracle_needed_is_only_progress_loss():
    g = got("fake-alwaysoracleneeded")
    assert g == {"progress_loss"}, g


@pytest.mark.parametrize("name", ["fake-precinverted", "fake-quorumweak", "fake-noexpiry", "fake-autofill"])
def test_each_mutant_fake_differs_from_control(name):
    assert got(name) != set()
