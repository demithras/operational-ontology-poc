"""Turn tracer state + audits into the evidence payloads (plain JSON-able dicts)."""
from __future__ import annotations

import json
from collections import Counter

from eoo_exp.util import ROOT, load_oracle

L = load_oracle("h20", "lifecycle")
PKG = {"manufacturing-ontology": "manufacturing", "project-ontology": "project"}
IR = {"manufacturing": "domains/manufacturing/ir.json", "project": "domains/project/ir.v2.json"}
KINDS = ("object_types", "link_types", "interfaces", "functions", "actions", "policies", "authority_rules", "observation_types", "constraints")


def registered() -> dict:
    out = {}
    for dom, f in IR.items():
        ir = json.loads((ROOT / f).read_text())
        out[dom] = {k: sorted(r["id"] for r in ir[k]) for k in KINDS}
    return out


def dispatch_traces(t, suites: dict, extra: dict) -> dict:
    reg = registered()
    by_dom: dict = {}
    for dom, pkg in ((d, p) for p, d in PKG.items()):
        disp = {(k, o): n for (p, k, o), n in t.dispatch.items() if p == pkg}
        rows = [r for r in t.execs.values() if r["pkg"] == pkg and r.get("history")]
        bad = []
        for r in rows:
            prob = L.history_problem(r["history"])
            if prob:
                bad.append({"action": r["action"], "history": r["history"], "problem": prob})
        covered = {r["action"] for r in rows if not L.history_problem(r["history"])}
        read_calls = sum(n for (k, o), n in disp.items() if L.CLASS_OF.get((k, o)) == "read")
        authority_rows = [r for r in rows if any(g == "authority" for g, _ in r["gates"])]
        prov_keys = Counter(r.get("prov_keys") for r in rows)
        kinds_cov = {k: sorted(set(reg[dom][k]) & t.rids.get((pkg, k), set())) for k in KINDS if k not in ("authority_rules",)}
        kinds_cov["authority_rules"] = sorted(set(reg[dom]["authority_rules"]) & t.authority_rules_seen.get(pkg, set()))
        by_dom[dom] = {
            "package_id": pkg, "engines_built": t.engines.get(pkg, 0),
            "dispatch": [{"kind": k, "op": o, "calls": n, "generic": L.dispatch_problem(k, o) is None} for (k, o), n in sorted(disp.items())],
            "dispatch_outside_generic_set": [f"{k}.{o}" for (k, o) in sorted(disp) if L.dispatch_problem(k, o)],
            "registered_counts": {k: len(v) for k, v in reg[dom].items()},
            "dispatched_or_decided_counts": {k: len(v) for k, v in kinds_cov.items()},
            "not_dispatched": {k: sorted(set(reg[dom][k]) - set(kinds_cov[k])) for k in KINDS if set(reg[dom][k]) - set(kinds_cov[k])},
            "executions": {"count": len(rows), "by_final_state": dict(Counter(r["history"][-1] for r in rows)),
                           "history_counts": dict(Counter(" > ".join(r["history"]) for r in rows)),
                           "distinct_histories": len({tuple(r["history"]) for r in rows}),
                           "histories_sample": sorted({" > ".join(r["history"]) for r in rows})[:12],
                           "nonconforming": bad[:10], "nonconforming_count": len(bad),
                           "states_used": sorted({s for r in rows for s in r["history"]})},
            "actions": {"registered": reg[dom]["actions"], "executed_with_conformant_history": sorted(covered),
                        "coverage": len(covered & set(reg[dom]["actions"])) / len(reg[dom]["actions"]),
                        "unexecuted": sorted(set(reg[dom]["actions"]) - covered)},
            "paths": {"read_dispatches": read_calls, "function_dispatches": disp.get(("functions", "call"), 0),
                      "governed_action_executions": len(rows), "security_authority_decisions": disp.get(("authority_rules", "decide"), 0),
                      "security_executions_with_authority_gate": len(authority_rows),
                      "security_authority_denials": sum(1 for r in authority_rows if ("authority", False) in r["gates"]),
                      "policy_evaluations": disp.get(("policies", "evaluate"), 0),
                      "provenance_records": sum(1 for r in rows if r.get("prov_keys")),
                      "provenance_required_fields_present": sum(1 for r in rows if r.get("prov_keys")
                                                                and all(f in r["prov_keys"] for f in L.PROVENANCE_REQUIRED_FIELDS))},
            "provenance_key_sets": sorted(" ".join(k) for k in prov_keys if k)}
    both = [by_dom[d] for d in by_dom]
    return {"frozen": {"states": list(L.STATES), "terminal": list(L.TERMINAL), "kind_ops": {k: sorted(v) for k, v in L.KIND_OPS.items()},
                       "oracle": "oracles/h20/lifecycle.py"},
            "suites": suites, "domains": by_dom,
            "cross_domain": {
                "handler_object_per_kind_is_single": all(len(v) == 1 for v in t.handler_ids.values()),
                "handler_classes": {k: sorted(v) for k, v in t.handler_classes.items()},
                "state_sets_equal_or_subset_of_frozen": all(set(b["executions"]["states_used"]) <= set(L.STATES) for b in both),
                "provenance_key_sets_equal": len({tuple(b["provenance_key_sets"]) for b in both}) == 1,
                "other_packages_traced": sorted({p for (p, _k, _o) in t.dispatch if p not in PKG})[:5]},
            **extra}
