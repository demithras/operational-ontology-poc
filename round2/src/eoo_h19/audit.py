"""Engine-level canonical-change audit: real Project Actions on the Engine over a Git repository, audited from Git alone.

For every proposed Action the audit reads the branch with the git CLI (never through GitStore) before and after:
  accepted  => exactly one new commit whose only parent is the old head, naming the execution; the Engine's own store unchanged;
  refused   => the branch did not move; no effect ran;
  always    => a fresh Engine projected from the new head equals the logical state read raw from that commit (no split brain).
A canonical ontology-only write is any step that breaks one of these. Evidence / Verdict bindings are re-read at the end of each case.
"""
from __future__ import annotations

import tempfile
import time

from eoo_engine_git import GitStore, Repo
from eoo_h18 import corpus
from eoo_h18.rig import EooRig

from .oracle import M
from .rawgit import RawGit

BOUND_TYPES = ("Evidence", "Verdict")


def engine_logical(state) -> dict:
    out = {f"obj|{t}|{k}": r["props"] for (t, k), r in state.objects.items()}
    out.update({f"lnk|{lt}|{s[0]}|{s[1]}|{d[0]}|{d[1]}": r["props"] for (lt, s, d), r in state.links.items()})
    return out


def _same(a: dict, b: dict) -> bool:
    return M.canon(a) == M.canon(b)


def audit_case(rig: EooRig, raw: RawGit, case: dict, label: str) -> dict:
    ref = rig.open_case(case, label)
    rows, pins = [], []
    for i, op in enumerate(case["ops"]):
        head0 = raw.head(ref)
        n0 = raw.count(head0)
        r = rig.step(case, ref, i, op)
        head1 = raw.head(ref)
        n1 = raw.count(head1)
        acc, moved = bool(r["accepted"]), head1 != head0
        trace_ok = all(r["trace"].values()) if acc and "trace" in r else None
        one_commit = n1 - n0 == 1 and raw.parents(head1) == [head0] if moved else None
        proj_equal = _same(engine_logical(rig.engine(ref).state()), raw.logical(head1))
        ootw = (not r["engine_store_unchanged"]) or (not r["effects_all_git"]) or (moved and not acc) or (acc and not one_commit) or (acc and not trace_ok) or (not proj_equal)
        rows.append({"op": op["k"], "acc": int(acc), "new_commits": n1 - n0, "one_commit": one_commit, "trace": trace_ok, "proj": int(proj_equal),
                     "unchanged": int(r["engine_store_unchanged"]), "git_only": int(r["effects_all_git"]), "ootw": int(ootw), "exc": r["exception"]})
        if acc and op["k"] in ("attach", "evaluate", "forced_verdict"):
            lg = raw.logical(head1)
            pins.append({"commit": head1, "digest": rig.store.canonical_hash(head1), "entries": {e: p for e, p in lg.items() if e.split("|")[1] in BOUND_TYPES}})
    final = raw.logical(raw.head(ref))
    cold = GitStore(Repo(rig.store.repo.path), rig.package, clock=lambda: "2099-01-01T00:00:00+00:00")
    bound = [{"hash_same": int(cold.canonical_hash(p["commit"]) == p["digest"]),
              "entries_same": int(all(e in final and _same(final[e], props) for e, props in p["entries"].items())), "n_entries": len(p["entries"])} for p in pins]
    return {"id": label, "steps": rows, "bindings": bound}


def run_audit(reader, seed: int, n: int, *, ir_version=None, log=print, ctx=None) -> dict:
    rig = EooRig(tempfile.mkdtemp(prefix="eoo-h19-audit-"), reader=reader, ir_version=ir_version)
    raw = RawGit(rig.workdir / "repo")
    cases, info = corpus.generate(rig, seed, n)
    out, t0 = [], time.time()
    from contextlib import nullcontext
    with (ctx() if ctx else nullcontext()):
        for k, c in enumerate(cases):
            out.append(audit_case(rig, raw, c, f"a{k:05d}"))
            if k % 50 == 0:
                log(f"[audit] {k}/{len(cases)} cases {time.time() - t0:.0f}s")
    return {"rig": rig, "raw": raw, "cases": out, "corpus": info}


def summarize(cases: list) -> dict:
    steps = [s for c in cases for s in c["steps"]]
    acc = [s for s in steps if s["acc"]]
    refused = [s for s in steps if not s["acc"]]
    b = [x for c in cases for x in c["bindings"]]
    return {"cases": len(cases), "steps": len(steps), "accepted_actions": len(acc), "accepted_one_commit": sum(1 for s in acc if s["one_commit"]),
            "accepted_traced": sum(1 for s in acc if s["trace"]), "refused_actions": len(refused), "refused_moved_branch": sum(1 for s in refused if s["new_commits"]),
            "projection_checks": len(steps), "projection_mismatches": sum(1 for s in steps if not s["proj"]),
            "engine_store_changed": sum(1 for s in steps if not s["unchanged"]), "non_git_effects": sum(1 for s in steps if not s["git_only"]),
            "ontology_only_writes": sum(s["ootw"] for s in steps), "exceptions": sum(1 for s in steps if s["exc"]),
            "bindings": len(b), "bindings_hash_same": sum(x["hash_same"] for x in b), "bindings_entries_same": sum(x["entries_same"] for x in b),
            "bound_entries": sum(x["n_entries"] for x in b)}
