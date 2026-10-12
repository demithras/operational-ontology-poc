"""Aggregation of judged rows into the quantities the evaluator and the evidence files need (ORACLE-AND-HARNESS-G5 s6-s8)."""
from __future__ import annotations

from collections import Counter, defaultdict

from . import faults, judge

SAFETY = ("forbidden_effect", "stale_authority_commit", "stale_authority_after_restart", "effect_outside_scope", "disclosure_leak",
          "unanchored_ack", "tampered_record_trusted", "false_success", "false_reconciled_success", "duplicate_effect", "duplicate_commit")
RECOVERY = ("recovery_nondeterministic", "recovery_divergence")


def aggregate(rows: list) -> dict:
    env = [r for r in rows if r["stratum"] in ("env", "ctrl")]
    bnd = [r for r in rows if r["stratum"] == "bnd"]
    clean = [r for r in env if not any(h in judge.BLOCKING for h in r["harness"])]
    classes = {c: {"count": 0, "sequences": []} for c in judge.CLASSES}
    for r in env + bnd:
        for c, dd in r["classes"].items():
            if c == "boundary_not_explicit" and r["stratum"] != "bnd":
                continue
            classes[c]["count"] += len(dd)
            classes[c]["sequences"].append(r["seq"])
    prog = {"overall": [0, 0], "per_class": {c: [0, 0] for c in ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8")}, "post_recovery": [0, 0],
            "per_node": defaultdict(lambda: [0, 0]), "during_fault": [0, 0], "spurious": Counter(), "outcome": [0, 0], "ctrl": [0, 0]}
    mis = {"total": 0, "by_kind": Counter(), "ids": []}
    rec = {"checks": 0, "passes": 0, "events": 0, "restricted_io": 0}
    probes = {"total": 0, "per_shape": Counter(), "in_auth_anchor_window": 0, "per_shape_in_window": Counter(), "lease_gap": 0,
              "boundary_total": 0, "boundary_per_shape": Counter()}
    for r in env:                                                                       # G5-E28 (a)/(c): counted on every judged env/ctrl row
        for q in r["req"]:
            if q.get("probe"):
                probes["total"] += 1
                probes["per_shape"][q.get("probe_shape")] += 1
                if set(q.get("phi") or ()) & {"AUTH", "ANCHOR"}:
                    probes["in_auth_anchor_window"] += 1
                    probes["per_shape_in_window"][q.get("probe_shape")] += 1
            probes["lease_gap"] += bool(q.get("lease_gap"))
    for r in bnd:                                                                       # B1/B2 probe matrix (every shape, dependency down)
        for q in (r["boundary"] or {}).get("probes", []):
            probes["boundary_total"] += 1                                              # G5-E29(b): S-bnd probes are reported, never toward the floor
            probes["boundary_per_shape"][q["shape"]] += 1
    for r in clean:
        rc2 = [x["t_probe"] for x in ((r["recovery"] or {}).get("rc2") or [])]
        for q in r["req"]:
            if q.get("spurious"):
                prog["spurious"][q["spurious"]] += 1
            if not q.get("eligible"):
                continue
            tgt = prog["ctrl"] if r["stratum"] == "ctrl" else prog["overall"]
            tgt[0] += 1
            tgt[1] += q["progressed"]
            if r["stratum"] == "ctrl":
                continue
            prog["overall"]  # noqa: B018
            if q["fclasses"]:
                prog["during_fault"][0] += 1
                prog["during_fault"][1] += q["progressed"]
            for c in q["fclasses"]:
                prog["per_class"][c][0] += 1
                prog["per_class"][c][1] += q["progressed"]
            if any(t0 <= q["t"] < t0 + 10 for t0 in rc2):
                prog["post_recovery"][0] += 1
                prog["post_recovery"][1] += q["progressed"]
        if r["stratum"] == "env":
            for n, (e, p) in r["unrelated"].items():
                prog["per_node"][n][0] += e
                prog["per_node"][n][1] += p
            op = r.get("outcome_progress") or {"checked": 0, "lost": []}
            prog["outcome"][0] += op["checked"]
            prog["outcome"][1] += len(op["lost"])
        for kind, dd in r["mis"].items():
            mis["total"] += len(dd)
            mis["by_kind"][kind] += len(dd)
            mis["ids"] += [{"seq": r["seq"], "kind": kind, **{k: v for k, v in d.items() if k in ("rid", "t", "why")}} for d in dd]
        rec["checks"] += r["recovery_checks"][0]
        rec["passes"] += r["recovery_checks"][1]
        rec["events"] += len((r["recovery"] or {}).get("rc1") or [])
        rec["restricted_io"] += len(r["restricted_io"])
    seq_class = Counter(c for r in rows if r["stratum"] == "env" for c in set(r["planned_classes"]))
    cps = Counter(cp for r in rows if r["stratum"] == "env" for cp in set((r.get("planned_cps") or [])))
    harness = Counter(h for r in rows for h in set(r["harness"]))
    bnd_res = defaultdict(lambda: {"n": 0, "violations": 0})
    for r in bnd:
        b = (r["boundary"] or {}).get("probe")
        bnd_res[b]["n"] += 1
        bnd_res[b]["violations"] += len((r["boundary"] or {}).get("violations", []))
    inj = defaultdict(lambda: {"scheduled": 0, "issued": 0, "enforced": 0, "refused_ge1": 0})
    for r in env:
        for x in r["injection"]:
            if "cls" in x:
                k = f"{x['cls']}:{x['node'].split(':')[0]}"
                inj[k]["scheduled"] += 1
                inj[k]["issued"] += x["issued"]
                inj[k]["enforced"] += x["enforced"]
                inj[k]["refused_ge1"] += x["refused_calls"] > 0
            else:
                inj["crash:" + x["crash_point"]]["scheduled"] += 1
                inj["crash:" + x["crash_point"]]["enforced"] += x["fired"]
    return {"rows": len(rows), "env_sequences": sum(r["stratum"] == "env" for r in rows), "ctrl_sequences": sum(r["stratum"] == "ctrl" for r in rows),
            "bnd_sequences": len(bnd), "classes": classes, "progress": {**prog, "per_node": dict(prog["per_node"]), "spurious": dict(prog["spurious"])},
            "misclassification": {**mis, "by_kind": dict(mis["by_kind"])}, "recovery": rec, "sequences_with_class": dict(seq_class),
            "crash_points": dict(cps), "harness": dict(harness), "boundary": dict(bnd_res), "injection": dict(inj),
            "stale_sensitive_sequences": sum(1 for r in env if r["stale_sensitive"] > 0 and "F6" in r["planned_classes"]),
            "f6_sequences": sum(1 for r in env if "F6" in r["planned_classes"]),
            "probes": {**probes, "per_shape": dict(probes["per_shape"]), "per_shape_in_window": dict(probes["per_shape_in_window"])}}
