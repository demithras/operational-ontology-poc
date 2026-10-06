"""Independent H22 verdict oracle: plain-arithmetic restatement of the preregistered rules over a flat case description.

Imports nothing from the Engine, Toolchain, domains, eoo_h22 or hdd (static test). Used only to cross-check the evaluator.
Case: {domains:int real, tasks:int completed, class_ratios:{cls: [per-task ratios]}, noninferior:{cls:bool}, slope, ci:[lo,hi]|None,
       tier:bool, fair_persist:bool, regressions:int}
"""


def _median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def verdict(c, min_domains=3, min_tasks=30, sup=0.75, rej=0.90, min_classes=2):
    if c["domains"] < min_domains or c["tasks"] < min_tasks:
        return "INCONCLUSIVE"
    meds = {k: _median(v) for k, v in c["class_ratios"].items() if v}
    lo, hi = c["ci"] if c["ci"] else (None, None)
    slope = c["slope"]
    if all(m >= rej for m in meds.values()) and meds or (slope is not None and slope >= 1.0):
        return "REJECTED"
    cheap = [k for k, m in meds.items() if m <= sup]
    apparent = len(cheap) >= min_classes and slope is not None and lo is not None and slope <= sup
    if apparent and (not c["fair_persist"] or c["regressions"] or any(not c["noninferior"].get(k) for k in cheap)):
        return "REJECTED"
    if lo is not None and lo <= sup and hi >= rej:
        return "INCONCLUSIVE"
    good = [k for k in cheap if c["noninferior"].get(k)]
    if len(good) >= min_classes and lo is not None and slope <= sup and c["tier"]:
        return "SUPPORTED"
    return "INCONCLUSIVE"
