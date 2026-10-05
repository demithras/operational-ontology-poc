"""Each H19 mutation, applied by monkeypatch, is killed by the check it targets; the clean control stays green; patches restore."""
import pytest

from eoo_h19.mutants import REGISTRY, m4_write_without_git_change
from eoo_h19.storelevel import failures, run_corpus, tally
from eoo_engine_git import GitStore
import eoo_engine_git.store as S


@pytest.fixture(scope="module")
def control(scenarios):
    return failures(run_corpus(scenarios, batch=60, log=lambda m: None))


def test_control_is_clean(control):
    assert not any(control.values()), control


@pytest.mark.parametrize("m", [m for m in REGISTRY if m["level"] == "store"], ids=lambda m: m["id"])
def test_store_mutant_is_killed_by_its_check_and_only_with_the_mutation(m, scenarios, control):
    orig = (GitStore.canonical_hash, S.merge, S.would_be)
    with m["ctx"]():
        res = run_corpus(scenarios, batch=60, log=lambda x: None)
    f = failures(res)
    assert f[m["expect"]] > 0, f"{m['id']} survived: {f}"
    assert control[m["expect"]] == 0 and tally(res)["exceptions"] == 0
    assert (GitStore.canonical_hash, S.merge, S.would_be) == orig  # restored


def test_specific_failure_signatures(scenarios):
    by = {}
    for m in REGISTRY:
        if m["level"] == "store":
            with m["ctx"]():
                by[m["id"]] = failures(run_corpus(scenarios, batch=60, log=lambda x: None))
    assert by["M2_missing_base_version_check"]["no_lost_update"] > 0 and by["M1_timestamp_dependent_projection"]["no_lost_update"] == 0
    assert by["M3_history_rebinding"]["binding_pinned"] > 0 and by["M3_history_rebinding"]["rebuild_hash_equal"] == 0  # a fresh rebuild is not fooled by it
    assert by["M5_pinned_binding_rewritable"]["no_rebinding_accepted"] > 0


def test_engine_level_mutant_is_seen_by_the_canonical_change_audit():
    import subprocess
    from domains.project.logic.freeze import git_blob_reader
    from eoo_exp.util import ROOT
    from eoo_h19.audit import run_audit, summarize
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    reader = git_blob_reader(head)
    clean = summarize(run_audit(reader, 3, 6, log=lambda m: None)["cases"])
    bad = summarize(run_audit(reader, 3, 6, log=lambda m: None, ctx=m4_write_without_git_change)["cases"])
    assert clean["ontology_only_writes"] == 0 and clean["accepted_actions"] > 0
    assert bad["ontology_only_writes"] == bad["accepted_actions"] > 0 and bad["accepted_one_commit"] == 0
