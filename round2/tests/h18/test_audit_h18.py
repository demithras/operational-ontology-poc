"""Static audit of the generic Engine + the Git store: 0 Project-domain branches, and the audit is not vacuous."""
from eoo_h18.audit import SCOPES, engine_audit, PLANTS
from eoo_h16.audit import collect_tokens, exempt_words, read_dir, scan_sources


def test_no_project_domain_branch_in_engine_or_git_store():
    a = engine_audit()
    assert a["project_domain_branches"] == 0 and a["domain_identity_branches"] == 0
    assert sum(s["string_constants_scanned"] for s in a["scopes"].values()) > 1000
    assert a["scopes"]["git_store"]["files_scanned"] >= 6


def test_planted_known_positives_are_found_in_each_scope():
    a = engine_audit()
    assert all(p["found"] for p in a["probes"].values()), a["probes"]


def test_project_tokens_are_really_in_the_token_set():
    t = collect_tokens()
    assert {"Hypothesis", "attach_evidence", "project-ontology", "Evidence"} <= set(t)


def test_a_planted_project_branch_in_the_git_store_is_a_branch_hit():
    src = read_dir(SCOPES["git_store"])
    f = "src/eoo_engine_git/store.py"
    src[f] += '\nif x == "Hypothesis":\n    pass\n'
    assert scan_sources(src, collect_tokens(), exempt_words())["branch_hits"] >= 1
