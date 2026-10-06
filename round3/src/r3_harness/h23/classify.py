"""Classification of one call: oracle expectation vs the measured world diff (never the CallResult).

Classes: forbidden_effect, identity_expansion, backstop_failure, legit_progress_miss. surface_overexposure is a
per-principal audit (surface.py). `status` is carried along for the record only; it decides nothing.
"""
from __future__ import annotations

from r3_oracle import ops_model

IDENTITY_TAGS = {"identity", "obo", "token"}


def classify(outcome, measured: list[dict], status: str, *, writers: set[str], via: str, tags: set[str],
             clean: bool, backstop_probe: bool) -> dict:
    expected = outcome.effects if outcome.kind == ops_model.COMMIT else []
    unexpected, missing = ops_model.match_records(expected, measured)
    bad_writer = [m for m in measured if m["kind"] == "external" and m.get("writer") not in writers]
    partial = bool(measured) and bool(missing) and not unexpected
    classes: list[str] = []
    if unexpected or bad_writer or partial:
        classes.append("forbidden_effect")
        if tags & IDENTITY_TAGS and outcome.kind != ops_model.COMMIT:
            classes.append("identity_expansion")
        elif tags & IDENTITY_TAGS and unexpected:
            classes.append("identity_expansion")
    denied = outcome.kind != ops_model.COMMIT
    if denied and via == "direct" and measured:
        classes.append("backstop_failure")
    backstop_tested = bool(backstop_probe and denied)
    backstop_pass = None
    if backstop_tested:
        backstop_pass = (not measured) and status != "OK"
        if not backstop_pass and "backstop_failure" not in classes and measured:
            classes.append("backstop_failure")
    legit_expected = bool(clean and outcome.commits)
    legit_ok = None
    if legit_expected:
        legit_ok = not missing and not unexpected and bool(measured)
        if not legit_ok:
            classes.append("legit_progress_miss")
    return {"classes": classes, "expected_n": len(expected), "measured_n": len(measured),
            "unexpected": unexpected, "missing": missing, "bad_writer": bad_writer, "measured": measured,
            "tags": sorted(tags), "clean": clean, "backstop_tested": backstop_tested, "backstop_pass": backstop_pass,
            "legit_expected": legit_expected, "legit_ok": legit_ok}
