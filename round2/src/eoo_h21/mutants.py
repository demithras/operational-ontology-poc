"""Mutation proof (contract python_hypothesis_role.mutation_proof): each generator mutant is applied by monkeypatch,
the surface is rebuilt and run through the conformance, differential and polymorphism checks; every target mutant must be
killed by an ASSERTION (a build/load crash is reported as a harness error, never as a kill) and the controls must be clean."""
from __future__ import annotations

import tempfile
from contextlib import contextmanager

from eoo_toolchain import build, gen_caps, gen_sdk, gen_surface, load_generated, selectors

from . import cases, conformance, differential, polymorphism


@contextmanager
def patched(*pairs):
    saved = [(obj, name, getattr(obj, name)) for obj, name, _new in pairs]
    try:
        for obj, name, new in pairs:
            setattr(obj, name, new)
        yield
    finally:
        for obj, name, old in saved:
            setattr(obj, name, old)


def m_drop_property():
    orig = gen_sdk.fields_of
    return [(gen_sdk, "fields_of", lambda o: [p for p in orig(o) if len(o["properties"]) < 2 or p["name"] != o["properties"][-1]["name"]])]


def m_drop_cardinality():
    flat = lambda lk: ((0, "*"), (0, "*"))  # noqa: E731
    return [(gen_sdk, "link_card", flat), (gen_surface, "link_card", flat)]


def m_expose_denied():
    orig = selectors.compile_principal
    return [(selectors, "compile_principal", lambda text, look: ["any"] if text != "*" and (text.startswith("role:") or "#" in text) else orig(text, look))]


def m_suppress_allowed():
    orig = gen_caps.rule_table

    def rule_table(ir):
        first = "action:" + ir["actions"][0]["id"]
        return {k: v for k, v in orig(ir).items() if not (v["effect"] == "allow" and v["capability"] == first)}
    return [(gen_caps, "rule_table", rule_table)]


def m_hardcode_interface():
    def src(iface, impls):
        return f"    return list_objects(client, sdk.{impls[0]})  # hard-coded concrete type"
    return [(gen_surface, "interface_tool_src", src)]


def m_function_as_action():
    return [(gen_sdk, "call_base", lambda kind: "ActionRequest")]


def m_delegation_flag_ignored():
    orig = gen_caps.compile_rule
    return [(gen_caps, "compile_rule", lambda rule, look: {**orig(rule, look), "delegation": True})]


def m_noop():
    return [(gen_sdk, "fields_of", gen_sdk.fields_of)]


TARGETS = {"drop_property": ("type-generation", m_drop_property), "drop_cardinality": ("type-generation", m_drop_cardinality),
           "expose_denied_action": ("security", m_expose_denied), "suppress_allowed_action": ("security", m_suppress_allowed),
           "hardcode_concrete_interface_type": ("polymorphism", m_hardcode_interface),
           "function_generated_as_action": ("type-generation", m_function_as_action),
           "delegation_flag_ignored": ("security", m_delegation_flag_ignored)}
CONTRACT_FOUR = ("drop_property", "drop_cardinality", "expose_denied_action", "suppress_allowed_action", "hardcode_concrete_interface_type")


def evaluate_surface(ir: dict, engine, case_list: list) -> dict:
    d = tempfile.mkdtemp(prefix="h21-mut-")
    inv = build(ir, d)
    sdk, _caps, surf = load_generated(d, inv["package"])
    conf = conformance.check(ir, sdk)
    diff = differential.run(ir, surf, case_list, sample_rows=3)
    poly = polymorphism.against_engine(ir, surf, engine)
    return {"conformance_failed": conf["failed"], "conformance_sample": conf["failures"][:3], "differential_mismatching_cases": diff["mismatching_cases"],
            "differential_by_dimension": diff["mismatches_by_dimension"], "differential_over": diff["overexposed_total"],
            "differential_under": diff["underexposed_total"], "polymorphism_failures": [r["interface"] for r in poly if not r["equals_store"]
                                                                                           or r["tool_source_names_an_implementer"]
                                                                                           or r["types_served"] != r["types_with_objects"]]}


def detected_by(r: dict) -> list:
    out = []
    if r["conformance_failed"]:
        out.append("type_conformance")
    if r["differential_mismatching_cases"]:
        out.append("security_differential")
    if r["polymorphism_failures"]:
        out.append("interface_polymorphism")
    return out


def run_all(domains: dict, n_cases: int, seed: int) -> dict:
    """domains: {name: {"ir": ir, "engine": booted engine}}. Returns the mutation-results payload."""
    case_lists = {d: cases.unique_cases(v["ir"], n_cases, seed + 7) for d, v in domains.items()}
    out = {"mutants": [], "controls": {}, "cases_per_domain": {d: len(c) for d, c in case_lists.items()}}
    for label, patch in (("clean_build", None), ("noop_patch", m_noop)):
        rows = {}
        for d, v in domains.items():
            ctx = patched(*patch()) if patch else patched()
            with ctx:
                rows[d] = evaluate_surface(v["ir"], v["engine"], case_lists[d])
        out["controls"][label] = {"clean": all(not detected_by(r) for r in rows.values()), "per_domain": rows}
    out["controls"]["clean"] = all(c["clean"] for c in out["controls"].values() if isinstance(c, dict) and "clean" in c)
    for mid, (klass, make) in TARGETS.items():
        per, errors = {}, {}
        for d, v in domains.items():
            try:
                with patched(*make()):
                    per[d] = evaluate_surface(v["ir"], v["engine"], case_lists[d])
            except Exception as exc:  # noqa: BLE001 - recorded as a harness error, never a kill
                errors[d] = f"{type(exc).__name__}: {str(exc)[:160]}"
        det = {d: detected_by(r) for d, r in per.items()}
        out["mutants"].append({"id": mid, "class": klass, "target": True, "contract_mutation": mid in CONTRACT_FOUR, "per_domain": per,
                               "harness_errors": errors, "detected_by": sorted({x for v in det.values() for x in v}),
                               "detected_in_domains": sorted(d for d, v in det.items() if v), "killed_in_every_domain": (not errors and all(det.values()))})
    return out
