"""Compiler mutation testing (AGENTS.md section 9): inject a known defect into a compiler by monkeypatch and require
the round-trip / ambiguity suites to notice it. Render is never the mutated side: artifacts are rendered once, clean.

Every mutation is paired with a CONTROL (the unmutated suite must report zero hits). A hit only counts as a kill when it
is an observed behavioural difference (valid input rejected, non-equivalent output, ambiguous case accepted, invented
semantics); a crash (unexpected exception type) is recorded separately and never counts as a kill."""
from __future__ import annotations

import copy
import random
from collections import Counter

import pytest

import eoo_dsl
import eoo_dsl.compiler as dsl_compiler
import eoo_openpona.compiler as op_compiler
import eoo_openpona.ctx as ctx
import eoo_openpona.document as document
import eoo_openpona.lines as op_lines
import eoo_openpona.resources as resources
from eoo_ir import equivalent
from eoo_ir.mutations import REGISTRY, apply_class
from eoo_openpona.errors import Invalid

from . import ambiguity, candidate, mutants_v2
from .roundtrip import attempt
from .surfaces import SURFACES
from .util import ROOT, load_json


# ------------------------------------------------------------------ OpenPona mutants (monkeypatch targets)
def _op_one(mp):
    return ctx._C.one


def op_drop_cardinality(mp):
    mp.setattr(ctx._C, "card", lambda self, a, side: {"min": 0, "max": "*"})


def op_swap_function_action(mp):
    mp.setitem(document.ALL_HEADS, "ilo", "actions")
    mp.setitem(document.ALL_HEADS, "pali", "functions")


def op_drop_authority_ref(mp):
    o = resources._action
    mp.setattr(resources, "_action", lambda c, a, p: {**o(c, a, p), "authority_refs": []})


def op_drop_version(mp):
    o = ctx._C.one
    mp.setattr(ctx._C, "one", lambda self, a, f, required=True: "v" if f == "version" else o(self, a, f, required))


def op_accept_ambiguous_binding(mp):
    mp.setattr(op_compiler, "_check_ir", lambda c, ir: None)  # denotation / ambiguous_ref checks switched off


def op_default_missing_type(mp):
    o = ctx._C.one

    def one(self, a, f, required=True):
        try:
            return o(self, a, f, required)
        except Invalid as e:
            if f == "type" and e.code == "missing:type":
                return ("prim", "string")  # DEFECT: invents a type
            raise
    mp.setattr(ctx._C, "one", one)


def op_default_immutable_false(mp):  # extra (not a registered target class)
    o = ctx._C.prop
    mp.setattr(ctx._C, "prop", lambda self, a, path: {"immutable": False, **o(self, a, path)})


def op_accept_parse_ambiguity(mp):  # extra: parser AMBIGUOUS -> pick the first skeleton
    real = op_lines.parsed

    class _R:
        def __init__(self, r):
            self.__dict__.update(r.__dict__ if hasattr(r, "__dict__") else {k: getattr(r, k) for k in dir(r) if not k.startswith("_")})
    def parsed(text):
        r = real(text)
        if r.status == "AMBIGUOUS":
            x = _R(r)
            x.status, x.skeletons = "RESOLVED", [r.skeletons[0]]
            return x
        return r
    mp.setattr(op_lines, "parsed", parsed)


# ------------------------------------------------------------------ DSL mutants
def _post(mp, fn):
    orig = dsl_compiler.compile

    def comp(text):
        return fn(copy.deepcopy(orig(text)))
    mp.setattr(dsl_compiler, "compile", comp)


def _each(doc, kind, fn):
    for x in doc.get(kind, []):
        fn(x)
    return doc


def dsl_drop_cardinality(mp):
    _post(mp, lambda d: _each(d, "link_types", lambda x: x.update(from_cardinality={"min": 0, "max": "*"}, to_cardinality={"min": 0, "max": "*"})))


def dsl_swap_function_action(mp):
    def f(d):
        d["functions"], d["actions"] = d["actions"], d["functions"]
        return d
    _post(mp, f)


def dsl_drop_authority_ref(mp):
    _post(mp, lambda d: _each(d, "actions", lambda x: x.update(authority_refs=[])))


def dsl_drop_version(mp):
    def f(d):
        d["version"] = "v"
        _each(d, "actions", lambda x: x.update(version="v"))
        return _each(d, "policies", lambda x: x.update(version="v"))
    _post(mp, f)


def dsl_accept_ambiguous_binding(mp):
    real = dsl_compiler.referential_errors
    mp.setattr(dsl_compiler, "referential_errors", lambda doc: [e for e in real(doc) if e.code != "ambiguous_ref"])


def dsl_default_missing_type(mp):
    real = dsl_compiler.check

    def check(doc, spec, path):
        for k in ("object_types", "link_types", "interfaces", "observation_types"):
            for o in doc.get(k, []) if isinstance(doc, dict) else []:
                for p in o.get("properties", o.get("required_properties", [])) if isinstance(o, dict) else []:
                    if isinstance(p, dict):
                        p.setdefault("type", "string")  # DEFECT: invents a type
        real(doc, spec, path)
    mp.setattr(dsl_compiler, "check", check)


def dsl_default_required_false(mp):  # extra
    real = dsl_compiler.check

    def check(doc, spec, path):
        for o in doc.get("object_types", []) if isinstance(doc, dict) else []:
            for p in o.get("properties", []):
                p.setdefault("required", False)
        real(doc, spec, path)
    mp.setattr(dsl_compiler, "check", check)


CLASSES = {
    "drop_cardinality": "link cardinality (min/max) lost: replaced by 0..*",
    "swap_function_action": "Function and Action kinds exchanged",
    "drop_authority_ref": "Action authority_refs dropped",
    "drop_version": "package / action / policy version replaced by a constant",
    "accept_ambiguous_binding": "ambiguous / duplicate reference accepted (first reading picked)",
    "default_missing_type": "a missing property/parameter type defaulted to string",
}
MUTANTS = {
    "openpona": {"drop_cardinality": op_drop_cardinality, "swap_function_action": op_swap_function_action,
                 "drop_authority_ref": op_drop_authority_ref, "drop_version": op_drop_version,
                 "accept_ambiguous_binding": op_accept_ambiguous_binding, "default_missing_type": op_default_missing_type},
    "dsl": {"drop_cardinality": dsl_drop_cardinality, "swap_function_action": dsl_swap_function_action,
            "drop_authority_ref": dsl_drop_authority_ref, "drop_version": dsl_drop_version,
            "accept_ambiguous_binding": dsl_accept_ambiguous_binding, "default_missing_type": dsl_default_missing_type},
}
EXTRAS = {"openpona": {"default_immutable_false": op_default_immutable_false,
                       "accept_parse_ambiguity": op_accept_parse_ambiguity},
          "dsl": {"default_required_false": dsl_default_required_false}}


# ------------------------------------------------------------------ the detection suite
def build_probes(generated: list[dict]) -> list[dict]:
    """Valid IRs with their CLEAN artifacts on both surfaces (rendered before any mutation)."""
    irs = [("coverage_ir", load_json("tests/h15/openpona_coverage_ir.json")),
           ("manufacturing", load_json("domains/manufacturing/ir.json")), ("project", load_json("domains/project/ir.json"))]
    for p in sorted((ROOT / "ontology/examples").glob("*.json")):
        irs.append((p.stem, load_json(f"ontology/examples/{p.name}")))
    irs += [(f"generated[{i}]", g) for i, g in enumerate(generated)]
    return [{"name": n, "ir": ir, "art": {s: SURFACES[s].render(ir) for s in SURFACES}} for n, ir in irs]


def suite(surface: str, probes: list[dict], deletion_pkgs: list[tuple[str, dict]], seed: int) -> dict:
    s = SURFACES[surface]
    hits: Counter = Counter()
    ex: list[dict] = []

    def hit(kind, what):
        hits[kind] += 1
        if len(ex) < 5 or kind != "crash" and len([e for e in ex if e["kind"] == kind]) < 2:
            ex.append({"kind": kind, "what": what})

    for p in probes:
        try:
            out = s.compile(p["art"][surface])
        except s.typed_errors as e:
            hit("valid_input_rejected", f"{p['name']}: {getattr(e, 'code', type(e).__name__)}")
            continue
        except Exception as e:  # noqa: BLE001
            hit("crash", f"{p['name']}: {type(e).__name__}: {str(e)[:80]}")
            continue
        if not equivalent(p["ir"], out).ok:
            hit("non_equivalent", f"{p['name']}: {equivalent(p['ir'], out).diffs[0][:100]}")
    d = ambiguity.declared_openpona() if surface == "openpona" else ambiguity.declared_dsl()
    for i in d["accepted"]:
        hit("ambiguity_case_accepted", i)
    for i in d["crashed"]:
        hit("crash", f"case {i}")
    acc = ambiguity._new()
    rnd = random.Random(seed)
    for label, ir in deletion_pkgs:
        if surface == "openpona":
            n = len(SURFACES["openpona"].render(ir)[0].splitlines())
            ambiguity.op_deletions(ir, label, acc, sorted(rnd.sample(range(1, n + 1), min(25, n))))
        else:
            ambiguity.dsl_deletions(ir, label, acc, rnd, 25)
    for x in acc["invented"]:
        hit("deletion_mutant_invented", f"{x['source']}")
    for x in acc["crashed"]:
        hit("crash", f"deletion {x['source']}: {x['error']}")
    return {"hits": dict(hits), "examples": ex[:8], "probes": len(probes), "declared_cases": d["total"],
            "deletion_mutants": acc["total"]}


def _killed(res: dict) -> bool:
    return any(v for k, v in res["hits"].items() if k != "crash")


def run(generated: list[dict], seed: int, n_deletion_pkgs: int = 12) -> dict:
    probes = build_probes(generated)
    dels = [(f"generated[{i}]", g) for i, g in enumerate(generated[:n_deletion_pkgs])]
    out = {"classes": CLASSES, "mutants": [], "controls": {}, "probes": [p["name"] for p in probes][:8] + ["..."],
           "n_probes": len(probes)}
    for surface in ("openpona", "dsl"):
        c = suite(surface, probes, dels, seed)
        out["controls"][surface] = {**c, "clean": not c["hits"]}
        if surface == "openpona" and candidate.is_v2():
            tables = ((True, mutants_v2.MUTANTS), (False, mutants_v2.EXTRAS))
        else:
            tables = ((True, MUTANTS[surface]), (False, EXTRAS[surface]))
        for target, table in tables:
            for cid, fn in table.items():
                with pytest.MonkeyPatch.context() as mp:
                    fn(mp)
                    res = suite(surface, probes, dels, seed)
                out["mutants"].append({"id": f"{surface}:{cid}", "surface": surface, "class": cid, "target": target,
                                       "killed": _killed(res), "crash_hits": res["hits"].get("crash", 0), **res})
        # the patches are undone: the control must be reproducible afterwards (no leaked monkeypatch)
        again = suite(surface, probes, dels, seed)
        out["controls"][surface]["clean_after_restore"] = not again["hits"]
    tg = [m for m in out["mutants"] if m["target"]]
    out["summary"] = {s: {"target_mutants": sum(m["surface"] == s for m in tg),
                          "killed": sum(m["surface"] == s and m["killed"] for m in tg),
                          "kill_rate": (sum(m["surface"] == s and m["killed"] for m in tg) / max(1, sum(m["surface"] == s for m in tg)))}
                      for s in ("openpona", "dsl")}
    out["oracle_known_negatives"] = oracle_known_negatives(probes, seed)
    return out


# Mutation classes of the oracle's own registry that correspond to the targeted defect classes.
ORACLE_CLASSES = ("from_cardinality_min", "from_cardinality_max", "to_cardinality_min", "to_cardinality_max",
                  "kind_function_to_action", "kind_action_to_function", "action_authority_refs_remove",
                  "action_authority_refs_change", "action_version", "policy_version", "package_version",
                  "type_primitive", "link_from", "action_idempotency")


def oracle_known_negatives(probes: list[dict], seed: int) -> dict:
    """The oracle must call a package with a known single-field defect NON-equivalent (it is the judge of every check)."""
    per = {c: {"applied": 0, "detected": 0} for c in ORACLE_CLASSES if c in REGISTRY}
    for p in probes:
        for c in per:
            m = apply_class(c, p["ir"], seed)
            if m is None:
                continue
            per[c]["applied"] += 1
            per[c]["detected"] += not equivalent(p["ir"], m).ok
    return {"per_class": per, "applied": sum(v["applied"] for v in per.values()),
            "detected": sum(v["detected"] for v in per.values()),
            "all_detected": all(v["detected"] == v["applied"] for v in per.values()) and
            all(v["applied"] > 0 for v in per.values())}
