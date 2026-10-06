"""Sidecar audit (contract experiment.audit_procedure): record vocabulary, alpha-renaming, line-only shape test.

Alpha-renaming: every non-literal record atom becomes the fresh opaque string 'rho' + hex(utf8(atom)) (injective,
shares no characters with the original). The compiled IR must decode back to the original IR exactly.
Line-only shape test: every record atom becomes a UNIQUE placeholder per slot ('1' for decimal-integer slots, '1.5'
for non-integer number slots, 'P<n>' otherwise); substituting the original atom back for every placeholder in the
compiled IR must reproduce the original IR (numbers masked: numeric literal slots are the only free numbers).
"""
from __future__ import annotations

import re
from collections import Counter

import eoo_openpona.compiler as op_compiler
from eoo_ir import equivalent
from eoo_ir.validate import Index
from eoo_openpona.lines import n_slots

from .slots import FLOAT_RULES, INT_RULES, KEY, line_rules, record_vocabulary
from .util import atom_strings, canon, mask_numbers

MARK = "ρ"
_TOK = re.compile(MARK + r"([0-9a-f]*)")
_PH = re.compile(r"P([0-9]+)")
_PH_FULL = re.compile(r"(auth:|policy:)?P[0-9]+([#.]P[0-9]+)*")


def _key_order(k: str):
    m = KEY.fullmatch(k)
    return (int(m.group(1)), int(m.group(2)))


def key_rules(text: str, rec: dict) -> dict:
    tids = {ln.lineno: ln.tid for ln in line_rules(text)}
    return {k: tids[_key_order(k)[0]] for k in rec}


def _map_ir(x, fn):
    if isinstance(x, dict):
        return {fn(k): _map_ir(v, fn) for k, v in x.items()}
    if isinstance(x, list):
        return [_map_ir(v, fn) for v in x]
    return fn(x) if isinstance(x, str) else x


def _decode(s: str) -> str:
    return _TOK.sub(lambda m: bytes.fromhex(m.group(1)).decode("utf-8"), s)


def classify(path: str) -> str:
    for needle, name in (("cardinality", "cardinality"), ("authority", "authority"), ("version", "version"),
                         ("type", "type"), ("kind", "function_action_kind"), ("purity", "function_action_kind"),
                         ("idempotency", "action_semantics"), ("effect", "effect_semantics")):
        if needle in path:
            return name
    return "other_structure"


def _findings(ir: dict, got: dict, label: str, limit: int = 8) -> list[dict]:
    eq = equivalent(mask_numbers(ir), mask_numbers(got))
    paths = sorted({d.split(":", 1)[0] for d in eq.diffs})[:limit]
    return [{"test": label, "ir_path": p, "category": classify(p),
             "classification": "indispensable_semantic_sidecar"} for p in paths]


def alpha_test(ir: dict, text: str, rec: dict) -> dict:
    rules = key_rules(text, rec)
    renamed = {k: (v if rules[k] in INT_RULES | FLOAT_RULES else MARK + v.encode("utf-8").hex()) for k, v in rec.items()}
    try:
        got = op_compiler.compile(text, renamed)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}", "findings": [
            {"test": "alpha_rename", "ir_path": "<compile>", "category": "other_structure",
             "classification": "indispensable_semantic_sidecar"}]}
    unrenamed = [s for s in atom_strings(got) if MARK not in s]
    back = _map_ir(got, _decode)
    same = canon(back) == canon(ir)
    ok = same and not unrenamed and equivalent(ir, back).ok
    return {"ok": ok, "findings": [] if ok else _findings(ir, back, "alpha_rename") +
            ([{"test": "alpha_rename", "ir_path": "<unrenamed atom>", "category": "other_structure",
                "classification": "atom_not_taken_from_record"}] if unrenamed else []),
            "unrenamed_atoms": len(unrenamed)}


def shape_test(ir: dict, text: str, rec: dict) -> dict:
    rules = key_rules(text, rec)
    ph, orig, n = {}, {}, 0
    for k in sorted(rec, key=_key_order):
        if rules[k] in INT_RULES:
            ph[k] = "1"
        elif rules[k] in FLOAT_RULES:
            ph[k] = "1.5"
        else:
            n += 1
            ph[k] = f"P{n}"
            orig[n] = rec[k]
    try:
        got = op_compiler.compile(text, ph, check_ir=False)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}", "findings": [
            {"test": "line_only_shape", "ir_path": "<compile>", "category": "other_structure",
             "classification": "indispensable_semantic_sidecar"}]}
    leaked = [s for s in atom_strings(got) if not _PH_FULL.fullmatch(s)]
    back = _map_ir(got, lambda s: _PH.sub(lambda m: orig[int(m.group(1))], s))
    ok = canon(mask_numbers(back)) == canon(mask_numbers(ir)) and not leaked
    return {"ok": ok, "leaked_atoms": len(leaked),
            "findings": [] if ok else _findings(ir, back, "line_only_shape")}


def ir_ref_slots(ir: dict) -> int:
    """Reference slots of an IR package (graph edges the line must carry), counted from the schema fields."""
    ix = Index(ir)

    def tref(t) -> int:
        if isinstance(t, dict):
            (k, v), = t.items()
            return 1 if k == "ref" else tref(v)
        return 0

    n = 0
    for o in ir["object_types"]:
        n += len(o["implements"]) + 1 + sum(tref(p["type"]) for p in o["properties"])
    for lk in ir["link_types"]:
        n += 2 + sum(tref(p["type"]) for p in lk.get("properties", []))
    for it in ir["interfaces"]:
        n += len(it["required_links"]) + sum(tref(p["type"]) for p in it["required_properties"])
    for f in ir["functions"]:
        n += len(f["reads"]) + tref(f["output"]) + sum(tref(p["type"]) for p in f["inputs"])
    for a in ir["actions"]:
        n += len(a["authority_refs"]) + len(a["policy_refs"]) + sum(tref(p["type"]) for p in a["inputs"])
        n += 1 if isinstance(a.get("compensation_action"), str) else 0
        for e in a["effects"]:
            if e["operation"] == "external_call":
                continue
            n += 1
            m = ix.resolve(e["target"], ("object_types", "link_types"))
            if len(m) == 1 and m[0][0] != "import":
                n += len(e.get("fields", []))
    for o in ir["observation_types"]:
        n += 1 + sum(tref(p["type"]) for p in o["properties"])
    return n


def label_ref_slots(text: str) -> tuple[int, dict]:
    """Reference slots carried by coreference labels in the lines (declarations of external names excluded)."""
    roles: Counter = Counter()
    for ln in line_rules(text):
        if ln.tid == "pkg.ext":
            continue
        for s in ln.slots:
            if s[0] == "ref":
                roles[s[2]] += 1
            elif s[0] == "type" and s[1][0] == "addr" and s[1][1].split()[0] != "nasin":  # nasin = type-constructor node
                roles["typeref"] += 1
    return sum(roles.values()), dict(roles)


def audit_package(ir: dict, text: str, rec: dict) -> dict:
    a, s = alpha_test(ir, text, rec), shape_test(ir, text, rec)
    total = ir_ref_slots(ir)
    via, roles = label_ref_slots(text)
    return {"alpha": a, "shape": s, "ref_slots_total": total, "ref_slots_via_labels": via, "roles": roles}
