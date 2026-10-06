#!/usr/bin/env python3
"""Instantiate every class of protocol/h15_ambiguity_classes.json for the OpenPona v2 surface (>= 3 cases per class).

Writes tests/h15/openpona2_ambiguity_cases.jsonl. Each case edits a canonical v2 render of a base IR (M/P = the frozen
minimal examples, C = tests/h15/openpona_coverage_ir.json, A = an object type and a link type sharing one id,
E = a package with nested metadata and no resources, so its metadata block ends the text).
--check: exit 1 if the committed file is stale.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eoo_openpona2 import render  # noqa: E402
from eoo_openpona2.lines import read_line  # noqa: E402

OUT = ROOT / "tests" / "h15" / "openpona2_ambiguity_cases.jsonl"
BASE_FILES = {"M": "ontology/examples/manufacturing-minimal.json", "P": "ontology/examples/project-domain-minimal.json",
              "C": "tests/h15/openpona_coverage_ir.json"}
SHARED_ID_IR = {  # base A: object type and link type both named 'Lot'; one action updates the object type
    "package_id": "a", "version": "1", "imports": [],
    "object_types": [{"id": "Lot", "primary_key": "id", "implements": [],
                      "properties": [{"name": "id", "type": "string", "required": True}]}],
    "link_types": [{"id": "Lot", "from": "Lot", "to": "Lot", "from_cardinality": {"min": 0, "max": "*"},
                    "to_cardinality": {"min": 0, "max": 1}}],
    "interfaces": [], "functions": [], "policies": [], "authority_rules": [], "observation_types": [], "constraints": [],
    "actions": [{"id": "touch", "inputs": [], "authority_refs": [], "policy_refs": [], "preconditions": [],
                 "effects": [{"operation": "update", "target": "Lot", "fields": ["id"]}], "idempotency": "required",
                 "outcome_predicate": "done", "version": "1"}]}

EMPTY_META_IR = {"package_id": "e", "version": "1", "object_types": [], "link_types": [], "interfaces": [],
                 "functions": [], "actions": [], "policies": [], "authority_rules": [], "observation_types": [],
                 "constraints": [], "metadata": {"k": {"a": 1}}}


class Doc:
    def __init__(self, base: str):
        ir = {"A": SHARED_ID_IR, "E": EMPTY_META_IR}.get(base) or json.loads((ROOT / BASE_FILES[base]).read_text())
        text, rec = render(ir)
        self.base = base
        self.lines = text.splitlines()
        self.atoms: list[list] = [[] for _ in self.lines]
        for k, v in sorted(rec.items(), key=lambda kv: tuple(int(x) for x in kv[0][1:].split(".a"))):
            n, _ = (int(x) for x in k[1:].split(".a"))
            self.atoms[n - 1].append(v)
        self.rids = [read_line(i, ln).rid for i, ln in enumerate(self.lines, 1)]

    def find(self, rid: str, nth: int = 0, head: str = "") -> int:
        hits = [i for i, r in enumerate(self.rids) if r == rid and self.lines[i].startswith(head)]
        return hits[nth]

    def delete(self, i: int) -> "Doc":
        for x in (self.lines, self.atoms, self.rids):
            x.pop(i)
        return self

    def replace(self, i: int, text: str | None = None, atoms: list | None = None) -> "Doc":
        if text is not None:
            self.lines[i] = text
        if atoms is not None:
            self.atoms[i] = list(atoms)
        return self

    def insert(self, i: int, text: str, atoms: list | None = None) -> "Doc":
        self.lines.insert(i, text)
        self.atoms.insert(i, list(atoms or []))
        self.rids.insert(i, "?")
        return self

    def record(self) -> dict:
        return {f"L{n}.a{j}": v for n, at in enumerate(self.atoms, 1) for j, v in enumerate(at, 1)}

    def case(self, cid, cls, desc, error, code, record=None, record_json=None):
        c = {"id": cid, "class": cls, "base": self.base, "description": desc,
             "expected": "unresolved" if cls == "unresolved_binding" else "error", "error": error, "code": code,
             "text": "".join(ln + "\n" for ln in self.lines), "record": record if record is not None else self.record()}
        if record_json is not None:
            c["record_json"] = record_json
        return c


def cases() -> list[dict]:
    out = []
    # ---- missing_type
    d = Doc("M"); out.append(d.delete(d.find("prop.type")).case(
        "type-missing-property", "missing_type", "property type statement deleted", "Invalid", "missing:type"))
    d = Doc("M"); out.append(d.delete(d.find("fn.output")).case(
        "type-missing-output", "missing_type", "function output statement deleted", "Invalid", "missing:output"))
    d = Doc("M"); out.append(d.delete(d.find("param.type")).case(
        "type-missing-parameter", "missing_type", "parameter type statement deleted", "Invalid", "missing:type"))
    d = Doc("M"); i = d.find("prop.type"); out.append(d.replace(i, "ijo ni la sona ni li sitelen").case(
        "type-not-a-type-phrase", "missing_type", "type phrase replaced by a word that is no type phrase", "Invalid",
        "unknown_line"))
    d = Doc("C"); tn = ("type.list", "type.optional")
    i = next(i for i, r in enumerate(d.rids) if r == "type.list" and d.rids[i - 1] not in tn and d.rids[i + 1] not in tn)
    out.append(d.delete(i).case(
        "type-announced-never-stated", "missing_type",
        "a one-level constructed type ('li nasin' + 'nasin li linja e ..'): the stating line is deleted",
        "Invalid", "missing:type_node"))
    # ---- missing_cardinality
    d = Doc("P"); out.append(d.delete(d.find("link.from_min")).case(
        "card-missing-from-min", "missing_cardinality", "from lower bound deleted", "Invalid", "missing:from_min"))
    d = Doc("P"); out.append(d.delete(d.find("link.to_max")).case(
        "card-missing-to-max", "missing_cardinality", "to upper bound deleted", "Invalid", "missing:to_max"))
    d = Doc("P"); i = d.find("link.to_min"); out.append(d.replace(i, atoms=[d.atoms[i][0], ""]).case(
        "card-empty-bound", "missing_cardinality", "to lower bound atom is the empty string", "Invalid", "literal"))
    d = Doc("P"); i = d.find("link.to_min"); out.append(d.replace(i, d.lines[i][: -len(" ni")], [d.atoms[i][0]]).case(
        "card-bound-without-slot", "missing_cardinality", "'kulupu ni' -> 'kulupu': bound slot not declared", "Invalid",
        "unknown_line"))
    d = Doc("P"); out.append(d.delete(d.find("link.from_star")).case(
        "card-missing-star", "missing_cardinality", "unbounded ('*') from upper bound deleted", "Invalid", "missing:from_max"))
    # ---- missing_resource_kind
    d = Doc("M"); i = d.find("res.decl", head="ilo"); out.append(d.replace(i, "toki ni li lon").case(
        "kind-unknown-head", "missing_resource_kind", "function declared under head 'toki' (no kind)", "Invalid",
        "unknown_line"))
    d = Doc("M"); out.append(d.delete(d.find("fn.purity")).case(
        "kind-function-without-purity", "missing_resource_kind", "Function purity statement deleted", "Invalid",
        "missing:purity"))
    d = Doc("M"); i = d.find("fn.purity"); out.append(d.insert(i + 1, "ilo ni li wile e sike sama", d.atoms[i]).case(
        "kind-function-with-action-field", "missing_resource_kind", "idempotency stated on a Function", "Invalid",
        "unknown_line"))
    d = Doc("M"); i = d.find("res.decl", head="ilo"); out.append(d.replace(i, "pali ni li lon").case(
        "kind-function-declared-as-action", "missing_resource_kind",
        "the Function's declaration says 'pali' (Action): its Function statements bind no declared Function",
        "Unresolved", "unresolved_binding"))
    # ---- missing_authority_effect
    d = Doc("M"); out.append(d.delete(d.find("auth.allow")).case(
        "auth-effect-deleted", "missing_authority_effect", "authority effect deleted", "Invalid", "missing:effect"))
    d = Doc("M"); i = d.find("auth.allow"); out.append(d.replace(i, "ken ni li pona").case(
        "auth-effect-unknown", "missing_authority_effect", "effect replaced by 'li pona'", "Invalid", "unknown_line"))
    d = Doc("M"); i = d.find("auth.allow"); out.append(d.insert(i + 1, "ken ni li ken ala", d.atoms[i]).case(
        "auth-effect-both", "missing_authority_effect", "allow and deny both stated", "Ambiguous", "conflict:effect"))
    # ---- missing_policy_decision
    d = Doc("M"); out.append(d.delete(d.find("pol.allow")).case(
        "policy-decision-deleted", "missing_policy_decision", "policy decision deleted", "Invalid", "missing:decision"))
    d = Doc("M"); i = d.find("pol.allow"); out.append(d.replace(i, "lawa ni li sona e pali").case(
        "policy-decision-unknown", "missing_policy_decision", "decision replaced by 'li sona e pali'", "Invalid",
        "unknown_line"))
    d = Doc("M"); i = d.find("pol.allow"); out.append(d.insert(i + 1, "lawa ni li kulupu e ijo", d.atoms[i]).case(
        "policy-decision-two", "missing_policy_decision", "allow and classify both stated", "Ambiguous",
        "conflict:decision"))
    # ---- missing_version
    d = Doc("M"); out.append(d.delete(d.find("pkg.version")).case(
        "version-package", "missing_version", "package version deleted", "Invalid", "missing:version"))
    d = Doc("M"); out.append(d.delete(d.find("res.version", head="tenpo ni la pali")).case(
        "version-action", "missing_version", "action version deleted", "Invalid", "missing:version"))
    d = Doc("M"); out.append(d.delete(d.find("res.version", head="tenpo ni la lawa")).case(
        "version-policy", "missing_version", "policy version deleted", "Invalid", "missing:version"))
    # ---- missing_required_flag
    d = Doc("M"); out.append(d.delete(d.find("prop.required_t")).case(
        "required-deleted", "missing_required_flag", "property required statement deleted", "Invalid", "missing:required"))
    d = Doc("M"); i = d.find("prop.required_t"); out.append(d.replace(i, d.lines[i] + " wile").case(
        "required-meta-repetition", "missing_required_flag", "'li wile' -> 'li wile wile' (META D1(wile))", "Invalid",
        "structure_mismatch"))
    d = Doc("M"); i = d.find("prop.required_t"); out.append(d.insert(i + 1, d.lines[i] + " ala", d.atoms[i]).case(
        "required-both", "missing_required_flag", "required true and false both stated", "Ambiguous", "conflict:required"))
    return out + cases2()


def cases2() -> list[dict]:
    out = []
    # ---- ambiguous_binding
    d = Doc("P"); i = d.find("res.decl", head="ijo"); out.append(d.insert(i + 1, d.lines[i], d.atoms[i]).case(
        "bind-declared-twice", "ambiguous_binding", "one object type id bound by two declaring lines", "Ambiguous",
        "duplicate_declaration"))
    d = Doc("P"); i = d.find("prop.decl"); out.append(d.insert(i + 1, d.lines[i], d.atoms[i]).case(
        "bind-property-declared-twice", "ambiguous_binding", "one property name of one owner declared twice", "Ambiguous",
        "duplicate_declaration"))
    d = Doc("M"); i = d.find("param.decl", head="pali"); out.append(d.insert(i + 1, d.lines[i], d.atoms[i]).case(
        "bind-parameter-declared-twice", "ambiguous_binding", "one parameter name of one action declared twice",
        "Ambiguous", "duplicate_declaration"))
    d = Doc("A"); i = d.find("eff.update"); out.append(d.replace(i, "pali ni li sitelen e ijo ni").case(
        "bind-git-change-shared-id", "ambiguous_binding",
        "git_change on 'ijo ni' = Lot, but the IR string 'Lot' denotes both the object type and the link type",
        "Ambiguous", "ir:ambiguous_ref"))
    # ---- unresolved_binding
    d = Doc("M"); i = d.find("obj.implements"); out.append(d.replace(i, atoms=[d.atoms[i][0], "Nope"]).case(
        "unres-undeclared-reference", "unresolved_binding", "implements binds an interface id no line declares",
        "Unresolved", "unresolved_binding"))
    d = Doc("M"); rec = d.record(); rec.pop(f"L{d.find('res.decl', head='ijo') + 1}.a1")
    out.append(d.case("unres-missing-atom", "unresolved_binding", "the id atom of an object type is missing from the record",
                      "Unresolved", "missing_atom", record=rec))
    d = Doc("M"); i = d.find("obj.description"); out.append(d.replace(i, atoms=["Ghost", d.atoms[i][1]]).case(
        "unres-undeclared-subject", "unresolved_binding", "a description about an object id no line declares",
        "Unresolved", "unresolved_binding"))
    d = Doc("M"); i = d.find("fn.reads"); out.append(d.replace(i, atoms=[d.atoms[i][0], "nope", d.atoms[i][2]]).case(
        "unres-undeclared-property", "unresolved_binding", "reads binds a property name its owner does not declare",
        "Unresolved", "unresolved_binding"))
    d = Doc("M"); i = d.find("act.authority"); out.append(d.replace(i, "pali ni li ken tan weka ni pi kulupu ni",
                                                                   [d.atoms[i][0], "rule", "not-imported"]).case(
        "unres-not-imported", "unresolved_binding", "an import-qualified reference to a package that is not imported",
        "Unresolved", "unresolved_binding"))
    # ---- dangling_atom
    d = Doc("M"); rec = d.record(); rec[f"L{d.find('pkg.imports_empty') + 1}.a1"] = "x"
    out.append(d.case("dangling-slotless-line", "dangling_atom", "atom for a line that declares no slot", "Invalid",
                      "dangling_atom", record=rec))
    d = Doc("M"); rec = d.record(); rec[f"L{len(d.lines) + 1}.a1"] = "x"
    out.append(d.case("dangling-beyond-text", "dangling_atom", "atom for a line that does not exist", "Invalid",
                      "dangling_atom", record=rec))
    d = Doc("M"); rec = d.record(); rec["L1.a2"] = "x"
    out.append(d.case("dangling-second-slot", "dangling_atom", "second atom on a one-slot line", "Invalid",
                      "dangling_atom", record=rec))
    d = Doc("M"); i = d.find("res.decl", head="ijo"); out.append(d.insert(i + 1, "ante li ma e sona ni", ["quantity"]).case(
        "dangling-field-without-effect", "dangling_atom", "an effect field item that follows no effect statement",
        "Invalid", "dangling_statement"))
    # ---- surface_parse_ambiguous
    d = Doc("M"); i = d.find("obj.description"); out.append(d.replace(i, d.lines[i] + " toki ni toki").case(
        "surface-meta-fold-ambiguous", "surface_parse_ambiguous", "description object 'toki ni toki ni toki' folds two ways",
        "Ambiguous", "parse_ambiguous"))
    d = Doc("M"); i = d.find("prop.type"); out.append(d.replace(i, "ijo ni la sona ni li sitelen toki sitelen toki sitelen").case(
        "surface-type-ambiguous", "surface_parse_ambiguous", "type phrase repeated so the META fold is ambiguous",
        "Ambiguous", "parse_ambiguous"))
    d = Doc("M"); rj = json.dumps(d.record(), ensure_ascii=False)
    rj = rj[:-1] + ', "L1.a1": "other"}'
    out.append(d.case("surface-record-duplicate-key", "surface_parse_ambiguous", "record JSON states L1.a1 twice",
                      "Ambiguous", "record_duplicate_key", record_json=rj))
    d = Doc("P"); rec = d.record(); rec[f"L{d.find('link.to_min') + 1}.a2"] = 1
    out.append(d.case("surface-record-number-not-string", "surface_parse_ambiguous",
                      "record value is a JSON number, not a string atom", "Invalid", "atom_type", record=rec))
    d = Doc("M"); i = d.find("meta.true"); out.append(d.insert(i + 1, "sitelen li pini").case(
        "surface-metadata-close-unplaced", "surface_parse_ambiguous",
        "a metadata close statement with no open value to close (cannot be placed)", "Invalid", "dangling_metadata"))
    d = Doc("E"); out.append(d.delete(d.find("meta.close")).case(
        "surface-metadata-unclosed-at-end", "surface_parse_ambiguous",
        "the close statement of a nested metadata object is deleted; the text ends with the value still open",
        "Invalid", "unclosed:metadata"))
    # ---- unknown_token_or_key
    d = Doc("M"); i = d.find("res.decl", head="ijo"); out.append(d.replace(i, "ijo ni li jo").case(
        "unknown-token", "unknown_token_or_key", "'jo' is not one of the 42 tokens", "Invalid", "parse_invalid"))
    d = Doc("M"); rec = d.record(); rec["type"] = "object"
    out.append(d.case("unknown-record-key", "unknown_token_or_key", "a structural-looking record key", "Invalid",
                      "record_key", record=rec))
    d = Doc("M"); i = d.find("prop.type"); out.append(d.replace(i, "ijo ni la sona ni li nanpa").case(
        "unknown-primitive", "unknown_token_or_key", "unknown primitive word 'nanpa'", "Invalid", "parse_invalid"))
    d = Doc("M"); i = d.find("res.decl", head="ijo"); out.append(d.replace(i, "Ijo ni li lon").case(
        "unknown-capitalised", "unknown_token_or_key", "capitalised token (a name)", "Invalid", "parse_invalid"))
    return out


def main() -> int:
    text = "".join(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n" for c in cases())
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text() != text:
            print(f"STALE {OUT.relative_to(ROOT)}")
            return 1
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text.splitlines())} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
