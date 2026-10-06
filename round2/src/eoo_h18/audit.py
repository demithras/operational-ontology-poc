"""Static audit (reuse of the H16 AST audit): does the generic Engine (and the Git store) branch on a Project-domain identity?"""
from __future__ import annotations

from eoo_exp.util import ROOT
from eoo_h16.audit import BRANCH, collect_tokens, exempt_words, read_dir, scan_sources

SCOPES = {"engine_core": ROOT / "src/eoo_engine", "git_store": ROOT / "src/eoo_engine_git"}
PLANTS = {"engine_core": ("src/eoo_engine/registry.py", '\nif False and model.package_id == "project-ontology":\n    pass\n'),
          "git_store": ("src/eoo_engine_git/store.py", '\n_X = {"Hypothesis": 1}\n')}


def project_tokens(tokens: dict) -> set:
    return {t for t, origins in tokens.items() if any(o.startswith("project") for o in origins)}


def engine_audit() -> dict:
    tokens, ex = collect_tokens(), exempt_words()
    proj = project_tokens(tokens)
    out = {"tokens": len(tokens), "project_tokens": len(proj), "exempt_words": len(ex), "scopes": {}, "probes": {}}
    for name, d in SCOPES.items():
        src = read_dir(d)
        res = scan_sources(src, tokens, ex)
        out["scopes"][name] = {"files_scanned": res["files_scanned"], "string_constants_scanned": res["string_constants_scanned"],
                               "branch_hits": res["branch_hits"], "literal_hits": res["literal_hits"],
                               "project_branch_hits": sum(1 for h in res["hits"] if h["position"] in BRANCH and set(h["tokens"]) & proj),
                               "hits": res["hits"][:20]}
        f, plant = PLANTS[name]
        planted = dict(src)
        planted[f] = planted[f] + plant  # known-positive: a planted domain branch MUST be found
        p = scan_sources(planted, tokens, ex)
        out["probes"][name] = {"planted_file": f, "branch_hits_after_plant": p["branch_hits"], "literal_hits_after_plant": p["literal_hits"],
                               "found": p["literal_hits"] > res["literal_hits"]}
    out["project_domain_branches"] = sum(s["project_branch_hits"] for s in out["scopes"].values())
    out["domain_identity_branches"] = sum(s["branch_hits"] for s in out["scopes"].values())
    return out
