"""Cost-accounting fairness: both variants' glue must be counted by the same rules.

Works over a SNAPSHOT of the H18 bespoke-change metrics (assignment + per_class + recurring tax). Every check recomputes from the
raw per-file line assignment, so a perturbation that ignores one variant's equivalent glue (python or recurring) is visible.
"""
from __future__ import annotations

import copy

VARIANTS = ("baseline", "eoo")
DIMS = (("config", "config_lines"), ("python", "python_loc"))


def _sum(d) -> int:
    return sum(d.values()) if d else 0


def asymmetries(snap: dict) -> list[str]:
    out: list[str] = []
    a, pc = snap["assignment"], snap["per_class"]
    for cls, row in sorted(pc.items()):
        for v in VARIANTS:
            for src, key in DIMS:
                stated = row[v].get(key)
                if stated is None:
                    out.append(f"{cls}/{v}: dimension {key} not accounted")
                    continue
                got = _sum(a[v][src].get(cls))
                if got != stated:
                    out.append(f"{cls}/{v}: {key} stated {stated} != {got} recomputed from the per-file assignment")
            extra = row[v].get("mandatory_extras", {"config_lines": 0, "python_loc": 0, "total": 0})
            for src, key in DIMS:
                got = _sum(a[v][src].get(cls + "X"))
                if got != extra.get(key, 0):
                    out.append(f"{cls}/{v}: mandatory extras {key} stated {extra.get(key, 0)} != {got} recomputed")
            core = row[v]["config_lines"] + row[v]["python_loc"] if "config_lines" in row[v] and "python_loc" in row[v] else None
            if core is not None and "total" in row[v] and row[v].get("total") != core + (row[v]["mandatory_extras"]["total"] if "mandatory_extras" in row[v] else 0) \
                    and row[v].get("total_without_extras", row[v]["total"]) != core:
                out.append(f"{cls}/{v}: total does not equal config + python (+ extras)")
        b, e = row["baseline"]["total"], row["eoo"]["total"]
        if b and abs(e / b - row["ratio_eoo_over_baseline"]) > 5e-4:
            out.append(f"{cls}: stated ratio {row['ratio_eoo_over_baseline']} != {e}/{b}")
    for v in VARIANTS:  # a variant that reports NO python glue anywhere while the other has some is not counting equivalent glue
        mine = sum(row[v].get("python_loc", 0) for row in pc.values())
        theirs = sum(row[o].get("python_loc", 0) for row in pc.values() for o in VARIANTS if o != v)
        if mine == 0 and theirs > 0:
            out.append(f"{v}: no python glue counted in any class while the other variant counts {theirs}")
    for v in VARIANTS:
        if not snap["recurring_complexity_loc"].get(v):
            out.append(f"{v}: recurring complexity not counted")
        if snap["python_unassigned_lines"].get(v):
            out.append(f"{v}: python lines left unassigned {sorted(snap['python_unassigned_lines'][v])}")
    return out


def task_asymmetries(tasks: list[dict]) -> list[str]:
    """Per-task cost rows: both variants must declare the same cost components, none may be null (an ignored glue component)."""
    out = []
    for t in tasks:
        e, b = t.get("eoo_components"), t.get("baseline_components")
        if not isinstance(e, dict) or not isinstance(b, dict) or set(e) != set(b):
            out.append(f"{t.get('task_id')}: cost components differ between variants ({sorted(e or {})} vs {sorted(b or {})})")
        elif any(x is None for x in (*e.values(), *b.values())):
            out.append(f"{t.get('task_id')}: a cost component is null (glue ignored)")
    return out


# --- mutants of the cost accounting (each must be detected; the control must be clean) -------------------------------------------------
def _recompute(row: dict, v: str) -> None:
    r = row[v]
    r["total_without_extras"] = r["config_lines"] + r["python_loc"]
    r["total"] = r["total_without_extras"] + r.get("mandatory_extras", {}).get("total", 0)


def _reratio(snap: dict) -> None:
    for row in snap["per_class"].values():
        b = row["baseline"]["total"]
        row["ratio_eoo_over_baseline"] = round(row["eoo"]["total"] / b, 3) if b else 0.0


def ignore_glue_mutants(snap: dict) -> dict[str, dict]:
    """Perturbations that ignore ONE variant's equivalent glue. Each returns a full, self-consistent-looking snapshot."""
    muts = {}
    m = copy.deepcopy(snap)  # M1: per-class python glue zeroed for EOO, totals re-derived, assignment untouched
    for row in m["per_class"].values():
        row["eoo"]["python_loc"] = 0
        _recompute(row, "eoo")
    _reratio(m)
    muts["M1_eoo_python_glue_zeroed_in_totals"] = m
    m = copy.deepcopy(snap)  # M2: baseline python glue rows dropped from the assignment, per-class numbers kept
    m["assignment"]["baseline"]["python"] = {k: {} for k in m["assignment"]["baseline"]["python"]}
    muts["M2_baseline_python_assignment_dropped"] = m
    m = copy.deepcopy(snap)  # M3: baseline python glue dropped CONSISTENTLY everywhere (assignment, per-class, totals)
    m["assignment"]["baseline"]["python"] = {k: {} for k in m["assignment"]["baseline"]["python"]}
    for row in m["per_class"].values():
        row["baseline"]["python_loc"] = 0
        _recompute(row, "baseline")
    _reratio(m)
    muts["M3_baseline_python_glue_dropped_consistently"] = m
    m = copy.deepcopy(snap)  # M4: the EOO recurring (engine/toolchain) tax ignored
    m["recurring_complexity_loc"]["eoo"] = 0
    muts["M4_eoo_recurring_tax_ignored"] = m
    return muts
