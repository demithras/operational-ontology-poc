"""Run TC2 (forensic queries) and TC3 (model change) through BOTH variants and the independent expectations."""
from __future__ import annotations

import json

from baselines.h18_fileonly import queries as bq, replication as brep
from baselines.h18_fileonly.ci import check
from baselines.h18_fileonly.repo import Model
from eoo_engine.canon import to_plain
from eoo_exp.util import load_oracle

from . import tc_eoo
from .rig import EooRig, PRINCIPAL

OQ = load_oracle("h18", "queries")
EXPERIMENT = "exp-h15-002"


def tc_rig(reader, workdir=None, ir_version=None) -> EooRig:
    return EooRig(workdir, reader=reader, package=tc_eoo.patched_ir(ir_version), extend=tc_eoo.extend, extra_ops=tc_eoo.dependency_ops(reader))


def run_tc2(rig: EooRig, reader) -> dict:
    ref = "refs/heads/main"
    files, e = rig.store.files_at(rig.store.head(ref)), rig.engine(ref)
    got = {"q1": e.call_function("evidence_of_verdict", {"hypothesis": "H15"}), "q2": list(e.call_function("find_orphan_components", {})),
           "q3": list(e.call_function("blocked_hypotheses", {}))}
    m = Model(files)
    base = {"q1": bq.q1(m, "H15"), "q2": bq.q2(m), "q3": bq.q3(m, reader)}
    want = {"q1": OQ.q1(reader), "q2": OQ.q2(files), "q3": OQ.q3(files, reader)}
    norm = lambda x: json.loads(json.dumps(to_plain(x), sort_keys=True))  # noqa: E731
    return {"expected": want, "eoo": norm(got), "baseline": norm(base),
            "eoo_correct": {k: norm(got[k]) == norm(want[k]) for k in want}, "baseline_correct": {k: norm(base[k]) == norm(want[k]) for k in want}}


def run_tc3(rig: EooRig, reader) -> dict:
    ref = "refs/heads/main"
    files = rig.store.files_at(rig.store.head(ref))
    steps = [("register_for_evaluated_experiment", "r-1", EXPERIMENT, True), ("register_for_unevaluated_experiment", "r-2", "exp-h16-001", False),
             ("register_second_for_evaluated_experiment", "r-3", EXPERIMENT, True), ("register_for_unknown_experiment", "r-4", "exp-nope", False)]
    rows, bfiles = [], dict(files)
    for name, rid, exp, expected in steps:
        e = rig.engine(ref)
        try:
            rec = e.propose("register_replication", {"id": rid, "experiment_ref": exp, "outcome": "reproduced"}, PRINCIPAL, idempotency_key=f"tc3-{rid}")
            got = rec["state"] == "RECONCILED_SUCCESS"
        except Exception:  # noqa: BLE001 - an unresolvable reference is a refusal
            got = False
        m = Model(bfiles)
        try:
            new = brep.register(bfiles, m, rid, exp, "reproduced")
            bad = check(bfiles, new, rig.evaluators)
            bgot = not bad
        except Exception:  # noqa: BLE001
            bgot, new = False, bfiles
        if bgot:
            bfiles = new
        rows.append({"step": name, "expected_accept": expected, "eoo_accept": got, "baseline_accept": bgot})
    e = rig.engine(ref)
    counts = {x: {"eoo": e.call_function("count_replications", {"experiment": x}), "baseline": brep.count(Model(bfiles), x),
                  "expected": 2 if x == EXPERIMENT else 0} for x in (EXPERIMENT, "exp-h16-001")}
    ok = lambda k: all(r[k] == r["expected_accept"] for r in rows)  # noqa: E731
    return {"steps": rows, "counts": counts, "eoo_correct": ok("eoo_accept") and all(c["eoo"] == c["expected"] for c in counts.values()),
            "baseline_correct": ok("baseline_accept") and all(c["baseline"] == c["expected"] for c in counts.values())}
