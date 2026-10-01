"""Ambiguity / missing-type attacks: the declared cases of both surfaces and generated single-deletion mutants.

Fail-closed property (protocol/h15_ambiguity_classes.json): for an under-specified input M, compile(M) raises a typed
error (or reports it unresolved), OR whatever it returns is exactly what M states (nothing guessed)."""
from __future__ import annotations

import copy
import json
import random
from collections import Counter

import eoo_dsl.errors as dsl_errors
import eoo_openpona
import eoo_openpona.compiler as op_compiler
from eoo_dsl import DslError
import eoo_dsl.compiler as dsl_compiler
from eoo_ir import validate
from eoo_openpona import OpenPonaError, load_record

from .opdoc import canonical_doc, delete_line
from .util import ROOT, canon

import eoo_dsl


def _jsonl(rel: str) -> list[dict]:
    return [json.loads(x) for x in (ROOT / rel).read_text().splitlines()]


def classes() -> dict:
    return {c["id"]: c["expected"] for c in json.loads((ROOT / "protocol/h15_ambiguity_classes.json").read_text())["classes"]}


def declared_openpona() -> dict:
    res = []
    for c in _jsonl("tests/h15/openpona_ambiguity_cases.jsonl"):
        out = {"id": c["id"], "class": c["class"], "expected": c["expected"], "declared": f"{c['error']}/{c['code']}"}
        try:
            rec = load_record(c["record_json"]) if "record_json" in c else c["record"]
            op_compiler.compile(c["text"], rec)
            out["outcome"] = "accepted"
        except OpenPonaError as e:
            out["got"] = f"{type(e).__name__}/{e.code}"
            out["outcome"] = "as_declared" if out["got"] == out["declared"] else "closed_other"
        except Exception as e:  # noqa: BLE001 - any other exception is a crash, not a refusal
            out["outcome"] = "crash"
            out["got"] = f"{type(e).__name__}: {str(e)[:120]}"
        res.append(out)
    return _summ(res)


def declared_dsl() -> dict:
    res = []
    for c in _jsonl("tests/h15/dsl_ambiguity_cases.jsonl"):
        want = getattr(dsl_errors, c["dsl_error"])
        out = {"id": c["id"], "class": c["class"], "expected": c["expected"], "declared": c["dsl_error"]}
        try:
            dsl_compiler.compile(c["text"])
            out["outcome"] = "accepted"
        except DslError as e:
            out["got"] = type(e).__name__
            ok = isinstance(e, want) and (c["expected"] != "unresolved" or isinstance(e, dsl_errors.DslUnresolvedReference))
            out["outcome"] = "as_declared" if ok else "closed_other"
        except Exception as e:  # noqa: BLE001
            out["outcome"] = "crash"
            out["got"] = f"{type(e).__name__}: {str(e)[:120]}"
        res.append(out)
    return _summ(res)


def _summ(res: list[dict]) -> dict:
    by = Counter(r["outcome"] for r in res)
    per_class: dict = {}
    for r in res:
        d = per_class.setdefault(r["class"], {"total": 0, "fail_closed": 0, "as_declared": 0})
        d["total"] += 1
        d["fail_closed"] += r["outcome"] in ("as_declared", "closed_other")
        d["as_declared"] += r["outcome"] == "as_declared"
    return {"total": len(res), "fail_closed": by["as_declared"] + by["closed_other"], "as_declared": by["as_declared"],
            "accepted": [r["id"] for r in res if r["outcome"] == "accepted"],
            "crashed": [r["id"] for r in res if r["outcome"] == "crash"],
            "closed_with_other_error": [r for r in res if r["outcome"] == "closed_other"],
            "classes_covered": sorted(per_class), "classes_declared": sorted(classes()), "per_class": per_class,
            "cases": res}


# ---------------------------------------------------------------- deletion mutants
def _new() -> dict:
    return {"total": 0, "raised": 0, "accepted_exact": 0, "invented": [], "crashed": [], "wrongly_rejected": [],
            "raised_by_error": Counter()}


def _fin(d: dict) -> dict:
    d = {**d, "raised_by_error": dict(d["raised_by_error"].most_common(30))}
    d["violations"] = len(d["invented"]) + len(d["crashed"])
    d["invented"], d["crashed"], d["wrongly_rejected"] = d["invented"][:20], d["crashed"][:20], d["wrongly_rejected"][:20]
    d["fail_closed_rate"] = None if not d["total"] else (d["total"] - d["violations"]) / d["total"]
    return d


def op_deletions(ir: dict, label: str, acc: dict, lines: list[int] | None = None) -> None:
    text, rec = eoo_openpona.render(ir)
    for k in lines or range(1, len(text.splitlines()) + 1):
        mt, mr = delete_line(text, rec, k)
        acc["total"] += 1
        try:
            out = op_compiler.compile(mt, mr)
        except OpenPonaError as e:
            acc["raised"] += 1
            acc["raised_by_error"][f"{type(e).__name__}/{e.code}"] += 1
            continue
        except Exception as e:  # noqa: BLE001
            acc["crashed"].append({"source": label, "line": k, "error": f"{type(e).__name__}: {str(e)[:100]}"})
            continue
        try:
            same = canonical_doc(*eoo_openpona.render(out)) == canonical_doc(mt, mr)
        except Exception as e:  # noqa: BLE001
            acc["crashed"].append({"source": label, "line": k, "error": f"re-render {type(e).__name__}: {str(e)[:100]}"})
            continue
        if same:
            acc["accepted_exact"] += 1
        else:
            acc["invented"].append({"source": label, "line": k, "deleted": text.splitlines()[k - 1]})


def _sites(doc, path=()):
    out = []
    if isinstance(doc, (dict, list)):
        it = doc.items() if isinstance(doc, dict) else enumerate(doc)
        for k, v in it:
            out.append(path + (k,))
            out += _sites(v, path + (k,))
    return out


def _delete(doc, path):
    d = copy.deepcopy(doc)
    p = d
    for x in path[:-1]:
        p = p[x]
    del p[path[-1]]
    return d


def dsl_deletions(ir: dict, label: str, acc: dict, rnd: random.Random, k: int) -> None:
    sites = _sites(ir)
    for path in rnd.sample(sites, min(k, len(sites))):
        m = _delete(ir, path)
        acc["total"] += 1
        try:
            out = dsl_compiler.compile(eoo_dsl.render(m))
        except DslError as e:
            acc["raised"] += 1
            acc["raised_by_error"][type(e).__name__] += 1
            if not validate(m):
                acc["wrongly_rejected"].append({"source": label, "path": list(map(str, path))})
            continue
        except Exception as e:  # noqa: BLE001
            acc["crashed"].append({"source": label, "path": list(map(str, path)), "error": f"{type(e).__name__}: {str(e)[:100]}"})
            continue
        if canon(out) == canon(m) and not validate(m):
            acc["accepted_exact"] += 1
        else:
            acc["invented"].append({"source": label, "path": list(map(str, path))})


def deletion_mutants(packages: list[tuple[str, dict]], domains: list[tuple[str, dict]], seed: int,
                     domain_lines: int = 80, dsl_sites: int = 25) -> dict:
    """packages: (label, IR) of generated packages (every OpenPona line deleted; dsl_sites random JSON deletions);
    domains: real-domain IRs (domain_lines random OpenPona line deletions, 4*dsl_sites JSON deletions)."""
    rnd = random.Random(seed)
    op, ds = _new(), _new()
    for label, ir in packages:
        op_deletions(ir, label, op)
        dsl_deletions(ir, label, ds, rnd, dsl_sites)
    for label, ir in domains:
        n = len(eoo_openpona.render(ir)[0].splitlines())
        op_deletions(ir, label, op, sorted(rnd.sample(range(1, n + 1), min(domain_lines, n))))
        dsl_deletions(ir, label, ds, rnd, 4 * dsl_sites)
    return {"openpona": _fin(op), "dsl": _fin(ds)}


def run(packages, domains, seed: int, **kw) -> dict:
    op, ds = declared_openpona(), declared_dsl()
    dm = deletion_mutants(packages, domains, seed, **kw)
    return {"declared": {"openpona": op, "dsl": ds}, "deletion_mutants": dm,
            "summary": {s: {"declared_total": d["total"], "declared_fail_closed": d["fail_closed"],
                            "declared_accepted": len(d["accepted"]), "declared_crashed": len(d["crashed"]),
                            "deletion_total": dm[s]["total"], "deletion_violations": dm[s]["violations"],
                            "deletion_raised": dm[s]["raised"], "deletion_accepted_exact": dm[s]["accepted_exact"]}
                        for s, d in (("openpona", op), ("dsl", ds))}}
