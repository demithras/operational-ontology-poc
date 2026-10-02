"""bespoke-change-metrics: TC1-TC3 per variant, correctness, recurring complexity, sensitivity."""
from __future__ import annotations

from eoo_exp.util import ROOT

from . import loc, manifest

CLASSES = ("TC1", "TC2", "TC3")


def measure(correctness: dict) -> dict:
    e, b = loc.assign(manifest.eoo()), loc.assign(manifest.baseline())
    rec_e = sum(len(loc.code_lines(ROOT / f)) for f in manifest.recurring_eoo_files())
    rec_b = sum(b["python"].get("RECURRING", {}).values())
    per = {}
    for c in CLASSES:
        te, tx, tb = loc.class_totals(e, c), loc.class_totals(e, c + "X"), loc.class_totals(b, c)
        eoo_total = te["total"] + tx["total"]
        per[c] = {"eoo": {**te, "mandatory_extras": tx, "total": eoo_total, "total_without_extras": te["total"]},
                  "baseline": tb, "declarative_resources": {"eoo": e["resources"].get(c, 0) + e["resources"].get(c + "X", 0), "baseline": b["resources"].get(c, 0)},
                  "ratio_eoo_over_baseline": round(eoo_total / tb["total"], 3) if tb["total"] else None,
                  "ratio_without_extras": round(te["total"] / tb["total"], 3) if tb["total"] else None,
                  "eoo_reduction": round(1 - eoo_total / tb["total"], 3) if tb["total"] else None,
                  "eoo_reduction_without_extras": round(1 - te["total"] / tb["total"], 3) if tb["total"] else None,
                  "correctness": correctness[c]}
    return {"per_class": per, "recurring_complexity_loc": {"eoo": rec_e, "baseline": rec_b, "eoo_files": manifest.recurring_eoo_files()},
            "excluded_not_counted": {k: loc.class_totals(e, k) for k in sorted({*e["python"], *e["config"]}) if k.startswith("EXCL:")},
            "python_unassigned_lines": {"eoo": e["python_unassigned"], "baseline": b["python_unassigned"]},
            "assignment": {"eoo": {"python": e["python"], "config": e["config"]}, "baseline": {"python": b["python"], "config": b["config"]}},
            "normalisation": "JSON counted as json.dumps(indent=2) lines for both variants; Python = non-blank, non-comment, non-docstring lines"}
