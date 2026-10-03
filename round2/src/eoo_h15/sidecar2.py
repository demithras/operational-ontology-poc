"""H15 v2 sidecar audit (protocol/H15_V2_PREREG.json audit_procedure_v2).

1. Alpha-renaming: every non-numeric record atom VALUE becomes 'rho' + hex(utf8(value)) (a bijection: equal values
   stay equal, different values stay different); compile must equal the IR renamed the same way (decode back = IR).
2. Line-only shape: every atom VALUE becomes a value-consistent, kind-valid placeholder ('P<n>' for strings, a fresh
   integer / non-integer number for numeric literal slots); substituting the originals back into the compiled IR must
   give the original IR exactly.
3. Record-key vocabulary: keys are neutral 'L<line>.a<slot>' slots declared by the lines, values strings, and every
   slot belongs to a declared atom class (identifier / opaque string / literal).
4. Meaning rule: the bounded-vocabulary test (meaning.py) over the domains and the generated sample.
"""
from __future__ import annotations

import re

import eoo_openpona2
import eoo_openpona2.compiler as op2_compiler
from eoo_ir import equivalent
from eoo_openpona2.lines import read_line

from . import meaning
from .sidecar import _decode, _findings, _map_ir, ir_ref_slots
from .util import atom_strings, canon

MARK = "ρ"
KEY = re.compile(r"L([1-9][0-9]*)\.a([1-9][0-9]*)")
INT_RULES = {"link.from_min", "link.from_max", "link.to_min", "link.to_max", "meta.int"}
FLOAT_RULES = {"meta.float"}
LITERAL_RULES = {"pkg.version", "res.version", "meta.str"} | INT_RULES | FLOAT_RULES
OPAQUE_RULES = {"obj.description", "prop.description", "prop.constraint", "iface.capability", "fn.impl",
                "act.precondition", "act.outcome", "pol.expression", "auth.principal", "auth.capability",
                "auth.resource", "obs.source", "con.scope", "con.expression", "eff.external_call"}
IDENT_KINDS = {"pkg", "imp", "decl", "subj", "ctx", "prop", "param", "ref", "type"}
# value slots that hold an identifier: domain id, metadata keys, effect field names (property names or opaque
# external field names)
IDENT_RULES = {"pkg.domain", "pkg.meta", "meta.entry", "eff.field"}


def slot_classes(text: str) -> dict[str, tuple]:
    """record key -> (rule id, class, numeric kind or None) for every atom slot the lines declare. Derived from the
    phrase table only (never from the record)."""
    out = {}
    for i, ln in enumerate(text.splitlines(), 1):
        line = read_line(i, ln)
        j = 1
        for p in line.entry.parts:
            for _ in range(p.n):
                if p.kind in IDENT_KINDS or line.rid in IDENT_RULES:
                    cls = "identifier"
                elif line.rid in LITERAL_RULES:
                    cls = "literal"
                elif line.rid in OPAQUE_RULES:
                    cls = "opaque_string"
                else:
                    cls = None
                num = None
                if p.kind in ("val", "ni") and line.rid in INT_RULES:
                    num = "int"
                elif p.kind in ("val", "ni") and line.rid in FLOAT_RULES:
                    num = "float"
                out[f"L{i}.a{j}"] = (line.rid, cls, num)
                j += 1
    return out


def record_vocabulary(text: str, rec: dict) -> dict:
    sc = slot_classes(text)
    bad_key = sorted(k for k in rec if not KEY.fullmatch(k))
    non_str = sorted(k for k, v in rec.items() if not isinstance(v, str))
    extra = sorted(set(rec) - set(sc) - set(bad_key))
    missing = sorted(set(sc) - set(rec))
    unclassified = sorted({rid for rid, c, _ in sc.values() if c is None})
    cls: dict[str, int] = {}
    for _, c, _ in sc.values():
        if c:
            cls[c] = cls.get(c, 0) + 1
    return {"keys": len(rec), "declared_slots": len(sc), "non_atom_keys": bad_key, "non_string_values": non_str,
            "keys_not_declared_by_a_line": extra, "slots_without_key": missing, "atom_rules_without_class": unclassified,
            "slots_by_class": cls, "ok": not (bad_key or non_str or extra or missing or unclassified)}


def _numeric(sc: dict, k: str) -> str | None:
    return sc[k][2]


def alpha_test(ir: dict, text: str, rec: dict) -> dict:
    sc = slot_classes(text)
    renamed = {k: (v if _numeric(sc, k) else MARK + v.encode("utf-8").hex()) for k, v in rec.items()}
    try:
        got = op2_compiler.compile(text, renamed)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}", "findings": [
            {"test": "alpha_rename", "ir_path": "<compile>", "category": "other_structure",
             "classification": "indispensable_semantic_sidecar"}]}
    unrenamed = [s for s in atom_strings(got) if MARK not in s]
    back = _map_ir(got, _decode)
    ok = canon(back) == canon(ir) and not unrenamed and equivalent(ir, back).ok
    return {"ok": ok, "unrenamed_atoms": len(unrenamed), "findings": [] if ok else _findings(ir, back, "alpha_rename") + (
        [{"test": "alpha_rename", "ir_path": "<unrenamed atom>", "category": "other_structure",
          "classification": "atom_not_taken_from_record"}] if unrenamed else [])}


def shape_test(ir: dict, text: str, rec: dict) -> dict:
    sc = slot_classes(text)
    ph: dict[str, str] = {}
    by_val: dict[tuple, str] = {}
    back_s: dict[str, str] = {}
    back_n: dict[tuple, object] = {}
    for k in sorted(rec, key=lambda s: tuple(int(x) for x in KEY.fullmatch(s).groups())):
        kind = _numeric(sc, k) or "str"
        key = (kind, rec[k])
        if key not in by_val:
            n = len(by_val) + 1
            if kind == "int":
                by_val[key] = str(1000 + n)
                back_n[("int", 1000 + n)] = int(rec[k])
            elif kind == "float":
                by_val[key] = repr(1000.5 + n)
                back_n[("float", 1000.5 + n)] = float(rec[k])
            else:
                by_val[key] = f"P{n}"
                back_s[f"P{n}"] = rec[k]
        ph[k] = by_val[key]
    try:
        got = op2_compiler.compile(text, ph, check_ir=False)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}", "findings": [
            {"test": "line_only_shape", "ir_path": "<compile>", "category": "other_structure",
             "classification": "indispensable_semantic_sidecar"}]}
    leaked = [s for s in atom_strings(got) if not _PH_FULL.fullmatch(s)]
    try:
        back = _subst(got, back_s, back_n)
    except KeyError as e:
        return {"ok": False, "leaked_atoms": len(leaked), "error": f"number not from a literal slot: {e}",
                "findings": [{"test": "line_only_shape", "ir_path": "<number>", "category": "other_structure",
                              "classification": "indispensable_semantic_sidecar"}]}
    ok = canon(back) == canon(ir) and not leaked
    return {"ok": ok, "leaked_atoms": len(leaked), "distinct_placeholders": len(by_val),
            "findings": [] if ok else _findings(ir, back, "line_only_shape")}


_PH = re.compile(r"P([0-9]+)")
_PH_FULL = re.compile(r"(auth:|policy:)?P[0-9]+([#.]P[0-9]+)*")


def _subst(x, back_s: dict, back_n: dict):
    if isinstance(x, dict):
        return {_PH.sub(lambda m: back_s[m.group(0)], k): _subst(v, back_s, back_n) for k, v in x.items()}
    if isinstance(x, list):
        return [_subst(v, back_s, back_n) for v in x]
    if isinstance(x, str):
        return _PH.sub(lambda m: back_s[m.group(0)], x)
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, int):
        return back_n[("int", x)]
    if isinstance(x, float):
        return back_n[("float", x)]
    return x


def ref_slot_bindings(text: str) -> tuple[int, dict]:
    """Reference slots written as canon bindings in the lines ('<head> ni', 'weka ni pi kulupu ni', 'sona ni pi h ni'),
    by role. None of them is a label: the target id is the bound record atom."""
    roles: dict[str, int] = {}
    for i, ln in enumerate(text.splitlines(), 1):
        line = read_line(i, ln)
        if line.rid in ("obj.pk", "eff.field"):  # primary key: an own property; field: property or opaque name
            roles[line.rid] = roles.get(line.rid, 0) + 1
        for p in line.entry.parts:
            if p.kind == "ref":
                roles[p.arg[0]] = roles.get(p.arg[0], 0) + 1
            elif p.kind == "type" and p.arg[0] == "ref":
                roles["typeref"] = roles.get("typeref", 0) + 1
    return sum(roles.values()), roles


def audit_package(ir: dict, text: str, rec: dict) -> dict:
    a, s = alpha_test(ir, text, rec), shape_test(ir, text, rec)
    via, roles = ref_slot_bindings(text)
    return {"alpha": a, "shape": s, "ref_slots_total": ir_ref_slots(ir), "ref_slots_via_bindings": via, "roles": roles,
            "vocabulary": record_vocabulary(text, rec)}


SAMPLE_N = 2000


def run_audit(domain_irs: dict, head: list[dict]) -> dict:
    """sidecar-audit.json payload for the v2 candidate (same top-level keys as v1, plus the v2 procedure and the
    meaning rule). The indispensable-sidecar count is alpha/shape findings + record-vocabulary violations; the meaning
    rule is reported separately and enters reject clause R3 in the v2 evaluator."""
    res = {"domains": {}, "generated_sample": {}}
    findings, vocab_bad = [], 0
    for d, ir in domain_irs.items():
        a = audit_package(ir, *eoo_openpona2.render(ir))
        findings += [{**f, "where": d} for f in a["alpha"]["findings"] + a["shape"]["findings"]]
        vocab_bad += not a["vocabulary"]["ok"]
        res["domains"][d] = {"alpha_rename_ok": a["alpha"]["ok"], "line_only_shape_ok": a["shape"]["ok"],
                             "record_vocabulary": a["vocabulary"], "reference_slots_total": a["ref_slots_total"],
                             "reference_slots_via_coreference_labels": 0,
                             "reference_slots_via_record_bindings": a["ref_slots_via_bindings"],
                             "reference_slots_by_role": a["roles"], "alpha_error": a["alpha"].get("error"),
                             "shape_error": a["shape"].get("error")}
    g = {"packages": 0, "alpha_failed": 0, "shape_failed": 0, "vocabulary_failed": 0, "reference_slots_total": 0,
         "reference_slots_via_coreference_labels": 0, "reference_slots_via_record_bindings": 0,
         "record_slots_by_class": {}, "failing": []}
    for i, ir in enumerate(head[:SAMPLE_N]):
        a = audit_package(ir, *eoo_openpona2.render(ir))
        g["packages"] += 1
        g["alpha_failed"] += not a["alpha"]["ok"]
        g["shape_failed"] += not a["shape"]["ok"]
        g["vocabulary_failed"] += not a["vocabulary"]["ok"]
        g["reference_slots_total"] += a["ref_slots_total"]
        g["reference_slots_via_record_bindings"] += a["ref_slots_via_bindings"]
        for k, v in a["vocabulary"]["slots_by_class"].items():
            g["record_slots_by_class"][k] = g["record_slots_by_class"].get(k, 0) + v
        if not (a["alpha"]["ok"] and a["shape"]["ok"] and a["vocabulary"]["ok"]):
            findings += [{**f, "where": f"generated[{i}]"} for f in a["alpha"]["findings"] + a["shape"]["findings"]]
            if len(g["failing"]) < 10:
                g["failing"].append({"label": f"generated[{i}]", "package": ir, "alpha": a["alpha"], "shape": a["shape"],
                                     "vocabulary": a["vocabulary"]})
    res["generated_sample"] = g
    ind = [f for f in findings if f["classification"] == "indispensable_semantic_sidecar"]
    res["findings"] = findings[:100]
    res["findings_total"] = len(findings)
    res["indispensable_semantic_sidecar_findings"] = len(ind)
    res["record_vocabulary_violations"] = vocab_bad + g["vocabulary_failed"]
    res["indispensable_sidecar_count"] = len(ind) + res["record_vocabulary_violations"]
    pk = [(d, ir) for d, ir in domain_irs.items()] + [(f"generated[{i}]", ir) for i, ir in enumerate(head[:SAMPLE_N])]
    res["meaning_rule"] = meaning.bounded_vocabulary(eoo_openpona2.render, pk, meaning.v2_table_size())
    res["procedure"] = ("audit_procedure_v2: record-key vocabulary; alpha-renaming of atom VALUES (rho+hex, value-"
                        "consistent; decode back must equal the IR); line-only shape (value-consistent kind-valid "
                        "placeholders; substitute back must equal the IR exactly); bounded-vocabulary meaning rule")
    return res
