"""Lock-step executor: one scenario runs on the real GitStore AND on the oracle DAG; every write is compared with the oracle's canonical outcome.

Checks per write (names are the evidence vocabulary): oracle_outcome_agreement, no_lost_update (independent of the oracle: the raw Git
states before/after must contain the writer's values and keep everyone else's), conflict_explicit_replayable, ref_unchanged_on_refusal,
digest_stable (write-time digest == rebuild digest). At scenario end: binding_pinned, no_rebinding_accepted.
"""
from __future__ import annotations

from eoo_engine_git import ConflictError, RowRejected, layout

from .oracle import M

MISSING = object()
from .seed import Env, change_to_rows, conflict_pairs


def lost_updates(prev: dict, new: dict, change: list, base: dict) -> list:
    """Raw-Git definition of a lost update, from three raw states (the writer's base, the head before, the head after).

    A CHANGE of the writer (a value different from the one on its own base, or a new entry) must be in the new head; every value
    of the previous head that the writer did not change must still be there. A value the writer set equal to its base is not a
    change (a three-way merge cannot tell it from not writing it), so concurrent edits of that property are not lost by it.
    """
    want: dict = {}
    for ch in change:
        want.setdefault(ch["e"], {}).update(ch.get("props", {}))
    changed = {e: {p: v for p, v in props.items() if e not in base or base[e].get(p, MISSING) != v} for e, props in want.items()}
    lost = []
    for e in want:
        if e not in new:
            lost.append((e, "*"))
            continue
        lost += [(e, p) for p, v in changed[e].items() if new[e].get(p) != v]
    for e, props in prev.items():
        if e not in new:
            lost.append((e, "*"))
            continue
        lost += [(e, p) for p, v in props.items() if p not in changed.get(e, {}) and new[e].get(p) != v]
    return lost


def _commit(st, rows, base, writer, ref, mode, label):
    return st.commit_rows(rows=rows, base=base, writer=writer, meta={"execution": label, "action": "h19-gen", "effects": []}, ref=ref,
                          merge_mode=mode, message=f"h19 {label}\n")


def run_scenario(env: Env, sc: dict, label: str) -> tuple[dict, list]:
    """(compact result row, [(commit sha, oracle-model hash, write-time store digest or None)] for the rebuild stage)."""
    st, raw = env.store, env.raw
    ref = f"refs/heads/s-{label}"
    st.repo.set_ref(ref, env.root)
    cs, dag, binds, wrows, classes = [env.root], M.Dag(env.root_state), [], [], set()
    wdig: dict = {env.root: layout.artifact_digest(st.files_at(env.root))}
    exc = None
    after_change = 0

    def do_write(i: int, change: list, lag: int, tag: str):
        nonlocal after_change
        base_i = max(0, len(cs) - 1 - lag)
        base, head = cs[base_i], cs[-1]
        out = dag.write(base_i, change, sc["mode"])
        rows, writer = change_to_rows(change), f"w{i}"
        got, rec, confl, row = "ok", None, [], {"t": tag, "x": out.kind, "s": int(base_i != len(cs) - 1)}
        try:
            rec = _commit(st, rows, base, writer, ref, sc["mode"], f"{label}/{i}")
        except ConflictError as ce:
            got, confl = "conflict", conflict_pairs(ce.conflicts)
            explicit = ce.base == base and ce.head == head and bool(confl) and st.conflicts[-1]["base"] == base
            try:  # replay: the same write on the same base against the same head must give the same explicit conflict
                _commit(st, rows, base, writer, ref, sc["mode"], f"{label}/{i}")
                row["r"] = "accepted"
            except ConflictError as c2:
                row["r"] = "eq" if conflict_pairs(c2.conflicts) == confl and explicit else "neq"
        except RowRejected:
            got = "rejected"
        row["g"] = got
        row["ref_ok"] = int(raw.head(ref) == head) if got != "ok" else 1
        row["a"] = int(got == out.kind and (got != "conflict" or confl == out.conflicts))
        row["L"], row["D"] = 0, 1
        if got == "ok":
            new = rec["sha"]
            row["L"] = len(lost_updates(raw.logical(head), raw.logical(new), change, raw.logical(base)))
            row["ref_ok"] = int(raw.head(ref) == new and raw.parents(new) == [head])
            if out.kind == "ok":
                row["a"] = int(M.state_hash(raw.logical(new)) == out.hash)
            else:
                dag.commits.append(((dag.head,), raw.logical(new)))  # resync the oracle to what Git now holds (the divergence is recorded)
            cs.append(new)
            wdig[new] = rec["state_hash"]
            row["D"] = int(rec["state_hash"] == st.canonical_hash(new))
            after_change += 1
            for b in binds:
                b["after"] += 1
        elif out.kind == "ok":
            dag.commits.pop()  # the oracle expected a commit Git did not make
        classes.update(out.classes)
        wrows.append(row)
        return row, got

    try:
        for i, step in enumerate(sc["steps"]):
            if step["k"] == "bind":
                x, n = cs[-1], len(binds)
                ev = f"obj|Evidence|ev-{label}-{n}"
                row, got = do_write(i, [{"e": ev, "props": {"payload_hash": f"ph-{n}", "git_commit": x, "experiment_version": "1", "environment": "env"}}], 0, "bind")
                if got == "ok":
                    binds.append({"ev": ev, "commit": x, "idx": len(cs) - 2, "digest": wdig[x], "raw": M.state_hash(raw.logical(x)), "after": 0})
            elif step["k"] == "rebind":
                if step["b"] < len(binds):
                    b = binds[step["b"]]
                    row, got = do_write(i, [{"e": b["ev"], "props": {"git_commit": cs[-1]}}], 0, "rebind")
                    row["rebound"] = int(got == "ok")
            else:
                do_write(i, step["changes"], step["lag"], "w")
        bind_rows = []
        head_logical = raw.logical(cs[-1])
        for b in binds:
            ok = (st.canonical_hash(b["commit"]) == b["digest"] and M.state_hash(raw.logical(b["commit"])) == b["raw"] == dag.hash(b["idx"])
                  and head_logical.get(b["ev"], {}).get("git_commit") == b["commit"])
            bind_rows.append({"pinned": int(ok), "after": b["after"]})
            if b["after"]:
                classes.add("historical_binding_after_change")
        classes.add("rebuild_same_commit")
    except Exception as e:  # noqa: BLE001 - recorded as a failure row, never a silent pass
        exc, bind_rows = f"{type(e).__name__}: {str(e)[:160]}", []
    commits = [(sha, dag.hash(i) if i < len(dag.commits) else None, wdig.get(sha)) for i, sha in enumerate(cs)]
    return {"id": label, "mode": sc["mode"], "classes": sorted(classes), "w": wrows, "binds": bind_rows, "commits": len(cs), "exc": exc}, commits
