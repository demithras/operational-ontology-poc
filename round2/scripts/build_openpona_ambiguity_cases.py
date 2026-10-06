#!/usr/bin/env python3
"""Instantiate every class of protocol/h15_ambiguity_classes.json for the OpenPona surface.

Writes tests/h15/openpona_ambiguity_cases.jsonl. Each case edits a canonical render of a base IR
(M/P = the frozen minimal examples, C = tests/h15/openpona_coverage_ir.json). --check: exit 1 if stale.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eoo_openpona import render  # noqa: E402
from eoo_openpona.lines import read_line  # noqa: E402

OUT = ROOT / "tests" / "h15" / "openpona_ambiguity_cases.jsonl"
BASE_FILES = {"M": "ontology/examples/manufacturing-minimal.json", "P": "ontology/examples/project-domain-minimal.json",
              "C": "tests/h15/openpona_coverage_ir.json"}


class Doc:
    def __init__(self, base: str):
        text, rec = render(json.loads((ROOT / BASE_FILES[base]).read_text()))
        self.base = base
        self.lines = text.splitlines()
        self.atoms = {int(k[1:].split(".")[0]): v for k, v in rec.items()}  # every rule binds <= 1 atom
        self.tids = [read_line(i, ln).tid for i, ln in enumerate(self.lines, 1)]

    def find(self, tid: str, contains: str = "", nth: int = 0) -> int:
        hits = [i for i, t in enumerate(self.tids) if t == tid and contains in self.lines[i]]
        return hits[nth]

    def delete(self, i: int) -> "Doc":
        self.lines.pop(i)
        self.tids.pop(i)
        self.atoms = {(n if n <= i else n - 1): v for n, v in self.atoms.items() if n != i + 1}
        return self

    def replace(self, i: int, text: str, atom=None, keep_atom: bool = True) -> "Doc":
        self.lines[i] = text
        if not keep_atom:
            self.atoms.pop(i + 1, None)
        if atom is not None:
            self.atoms[i + 1] = atom
        return self

    def insert(self, i: int, text: str, atom=None) -> "Doc":
        self.lines.insert(i, text)
        self.tids.insert(i, "?")
        self.atoms = {(n if n <= i else n + 1): v for n, v in self.atoms.items()}
        if atom is not None:
            self.atoms[i + 1] = atom
        return self

    def subject(self, i: int) -> str:
        return self.lines[i].split(" li ")[0].split(" la ")[-1]

    def case(self, cid, cls, desc, error, code, record=None, record_json=None):
        rec = record if record is not None else {f"L{n}.a1": v for n, v in sorted(self.atoms.items())}
        c = {"id": cid, "class": cls, "base": self.base, "description": desc,
             "expected": "unresolved" if cls == "unresolved_binding" else "error",
             "error": error, "code": code, "text": "".join(ln + "\n" for ln in self.lines), "record": rec}
        if record_json is not None:
            c["record_json"] = record_json
        return c


def _rec(d: Doc) -> dict:
    return {f"L{n}.a1": v for n, v in sorted(d.atoms.items())}


def cases() -> list[dict]:
    out = []
    # ---- missing_type
    d = Doc("M"); i = d.find("slot.type", "sona pi"); out.append(d.delete(i).case(
        "type-missing-property", "missing_type", "property type statement deleted", "Invalid", "missing:type"))
    d = Doc("M"); out.append(d.delete(d.find("fn.output")).case(
        "type-missing-output", "missing_type", "function output statement deleted", "Invalid", "missing:output"))
    d = Doc("M"); i = d.find("slot.type", "sona pi"); out.append(d.replace(i, d.subject(i) + " li sitelen").case(
        "type-not-a-type-phrase", "missing_type", "type phrase replaced by a word that is no type phrase", "Invalid", "unknown_line"))
    d = Doc("M"); out.append(d.delete(d.find("slot.type", "kute pi")).case(
        "type-missing-parameter", "missing_type", "parameter type statement deleted", "Invalid", "missing:type"))
    # ---- missing_cardinality
    d = Doc("P"); out.append(d.delete(d.find("link.from_min")).case(
        "card-missing-from-min", "missing_cardinality", "from lower bound deleted", "Invalid", "missing:from_min"))
    d = Doc("P"); out.append(d.delete(d.find("link.to_max")).case(
        "card-missing-to-max", "missing_cardinality", "to upper bound deleted", "Invalid", "missing:to_max"))
    d = Doc("P"); i = d.find("link.to_min"); out.append(d.replace(i, d.lines[i], atom="").case(
        "card-empty-bound", "missing_cardinality", "to lower bound atom is the empty string", "Invalid", "literal"))
    d = Doc("P"); i = d.find("link.to_min"); out.append(d.replace(i, d.lines[i][: -len(" ni")], keep_atom=False).case(
        "card-bound-without-slot", "missing_cardinality", "'kulupu ni' -> 'kulupu': bound slot not declared", "Invalid", "unknown_line"))
    d = Doc("P"); out.append(d.delete(d.find("link.from_star")).case(
        "card-missing-star", "missing_cardinality", "unbounded ('*') from upper bound deleted", "Invalid", "missing:from_max"))
    # ---- missing_resource_kind
    d = Doc("M"); i = d.find("res.decl", "ilo pi"); out.append(d.replace(i, "toki" + d.lines[i][3:]).case(
        "kind-unknown-head", "missing_resource_kind", "function declared under head 'toki' (no kind)", "Invalid", "unknown_line"))
    d = Doc("M"); out.append(d.delete(d.find("fn.purity")).case(
        "kind-function-without-purity", "missing_resource_kind", "Function purity statement deleted", "Invalid", "missing:purity"))
    d = Doc("M"); i = d.find("fn.purity"); out.append(d.insert(i + 1, d.subject(i) + " li wile e sike sama").case(
        "kind-function-with-action-field", "missing_resource_kind", "idempotency stated on a Function", "Invalid", "unknown_line"))
    d = Doc("M"); a = d.subject(d.find("res.decl", "pali pi"))
    d.lines = [ln.replace(a, "ilo pi pona ala") for ln in d.lines]
    out.append(d.case("kind-action-under-function-head", "missing_resource_kind",
                      "every line of the Action rewritten under a Function head", "Invalid", "unknown_line"))
    # ---- missing_authority_effect
    d = Doc("M"); out.append(d.delete(d.find("auth.allow")).case(
        "auth-effect-deleted", "missing_authority_effect", "authority effect deleted", "Invalid", "missing:effect"))
    d = Doc("M"); i = d.find("auth.allow"); out.append(d.replace(i, d.subject(i) + " li pona").case(
        "auth-effect-unknown", "missing_authority_effect", "effect replaced by 'li pona'", "Invalid", "unknown_line"))
    d = Doc("M"); i = d.find("auth.allow"); out.append(d.insert(i + 1, d.subject(i) + " li ken ala").case(
        "auth-effect-both", "missing_authority_effect", "allow and deny both stated", "Ambiguous", "conflict:effect"))
    # ---- missing_policy_decision
    d = Doc("M"); out.append(d.delete(d.find("pol.allow")).case(
        "policy-decision-deleted", "missing_policy_decision", "policy decision deleted", "Invalid", "missing:decision"))
    d = Doc("M"); i = d.find("pol.allow"); out.append(d.replace(i, d.subject(i) + " li sona e pali").case(
        "policy-decision-unknown", "missing_policy_decision", "decision replaced by 'li sona e pali'", "Invalid", "unknown_line"))
    d = Doc("M"); i = d.find("pol.allow"); out.append(d.insert(i + 1, d.subject(i) + " li kulupu e ijo").case(
        "policy-decision-two", "missing_policy_decision", "allow and classify both stated", "Ambiguous", "conflict:decision"))
    # ---- missing_version
    d = Doc("M"); out.append(d.delete(d.find("pkg.version")).case(
        "version-package", "missing_version", "package version deleted", "Invalid", "missing:version"))
    d = Doc("M"); out.append(d.delete(d.find("res.version", "pali pi")).case(
        "version-action", "missing_version", "action version deleted", "Invalid", "missing:version"))
    d = Doc("M"); out.append(d.delete(d.find("res.version", "lawa pi")).case(
        "version-policy", "missing_version", "policy version deleted", "Invalid", "missing:version"))
    # ---- missing_required_flag
    d = Doc("M"); out.append(d.delete(d.find("slot.required_t", "sona pi")).case(
        "required-deleted", "missing_required_flag", "property required statement deleted", "Invalid", "missing:required"))
    d = Doc("M"); i = d.find("slot.required_t", "sona pi"); out.append(d.replace(i, d.lines[i] + " wile").case(
        "required-meta-repetition", "missing_required_flag", "'li wile' -> 'li wile wile' (META D1(wile))", "Invalid", "structure_mismatch"))
    d = Doc("M"); i = d.find("slot.required_t", "sona pi"); out.append(d.insert(i + 1, d.lines[i] + " ala").case(
        "required-both", "missing_required_flag", "required true and false both stated", "Ambiguous", "conflict:required"))
    return out + cases2()


def cases2() -> list[dict]:
    out = []
    # ---- ambiguous_binding
    d = Doc("P"); i = d.find("res.decl", "ijo pi"); out.append(d.insert(i + 1, d.lines[i], atom="Other").case(
        "bind-address-declared-twice", "ambiguous_binding", "one address declared by two lines", "Ambiguous", "duplicate_address"))
    d = Doc("P"); i, j = d.find("res.decl", "ijo pi", 0), d.find("res.decl", "ijo pi", 1)
    out.append(d.replace(j, d.lines[j], atom=d.atoms[i + 1]).case(
        "bind-duplicate-id", "ambiguous_binding", "two object types bound to the same id atom", "Ambiguous", "ir:duplicate_id"))
    d = Doc("P"); i, j = d.find("prop.decl", "", 0), d.find("prop.decl", "", 1)
    out.append(d.replace(j, d.lines[j], atom=d.atoms[i + 1]).case(
        "bind-duplicate-property-name", "ambiguous_binding", "two properties of one owner bound to one name",
        "Ambiguous", "ir:duplicate_name"))
    d = Doc("C"); i = d.find("res.decl", "selo pi"); out.append(d.replace(i, d.lines[i], atom="ext-pkg@v2#Audited").case(
        "bind-local-shadows-import", "ambiguous_binding",
        "interface renamed to the spelling of an imported name the line references: the IR string would denote the local one",
        "Ambiguous", "denotation"))
    # ---- unresolved_binding
    d = Doc("M"); i = d.find("obj.implements"); out.append(d.replace(i, d.subject(i) + " li sama e selo pi pona ala").case(
        "unres-undeclared-reference", "unresolved_binding", "implements names an address no line declares",
        "Unresolved", "unresolved_address"))
    d = Doc("M"); rec = _rec(d); rec.pop(f"L{d.find('res.decl', 'ijo pi') + 1}.a1")
    out.append(d.case("unres-missing-atom", "unresolved_binding", "the id atom of an object type is missing from the record",
                      "Unresolved", "missing_atom", record=rec))
    d = Doc("M"); i = d.find("obj.description"); out.append(d.replace(i, "ijo pi pona ala" + d.lines[i][len(d.subject(i)):]).case(
        "unres-undeclared-subject", "unresolved_binding", "a description about an undeclared object address",
        "Unresolved", "unresolved_address"))
    # ---- dangling_atom
    d = Doc("M"); rec = _rec(d); rec[f"L{d.find('pkg.imports_empty') + 1}.a1"] = "x"
    out.append(d.case("dangling-slotless-line", "dangling_atom", "atom for a line that declares no slot", "Invalid",
                      "dangling_atom", record=rec))
    d = Doc("M"); rec = _rec(d); rec[f"L{len(d.lines) + 1}.a1"] = "x"
    out.append(d.case("dangling-beyond-text", "dangling_atom", "atom for a line that does not exist", "Invalid",
                      "dangling_atom", record=rec))
    d = Doc("M"); rec = _rec(d); rec["L1.a2"] = "x"
    out.append(d.case("dangling-second-slot", "dangling_atom", "second atom on a one-slot line", "Invalid",
                      "dangling_atom", record=rec))
    d = Doc("C"); i = d.find("pkg.ext"); out.append(d.insert(i + 1, "weka pi pona ala li tan kulupu pi open lon", atom="Unused").case(
        "dangling-external-name", "dangling_atom", "an external name declared but filling no slot", "Invalid", "dangling_address"))
    # ---- surface_parse_ambiguous
    d = Doc("M"); i = d.find("obj.description"); out.append(d.replace(i, d.lines[i] + " toki ni toki").case(
        "surface-meta-fold-ambiguous", "surface_parse_ambiguous", "description object 'toki ni toki ni toki' folds two ways",
        "Ambiguous", "parse_ambiguous"))
    d = Doc("M"); i = d.find("slot.type", "sona pi"); out.append(d.replace(i, d.subject(i) + " li sitelen toki sitelen toki sitelen").case(
        "surface-type-ambiguous", "surface_parse_ambiguous", "type phrase repeated so the META fold is ambiguous",
        "Ambiguous", "parse_ambiguous"))
    d = Doc("M"); rj = json.dumps(_rec(d), ensure_ascii=False)
    rj = rj[:-1] + ', "L1.a1": "other"}'
    out.append(d.case("surface-record-duplicate-key", "surface_parse_ambiguous", "record JSON states L1.a1 twice",
                      "Ambiguous", "record_duplicate_key", record_json=rj))
    d = Doc("P"); rec = _rec(d); rec[f"L{d.find('link.to_min') + 1}.a1"] = 1
    out.append(d.case("surface-record-number-not-string", "surface_parse_ambiguous",
                      "record value is a JSON number, not a string atom", "Invalid", "atom_type", record=rec))
    # ---- unknown_token_or_key
    d = Doc("M"); i = d.find("res.decl", "ijo pi"); out.append(d.replace(i, d.subject(i) + " li jo").case(
        "unknown-token", "unknown_token_or_key", "'jo' is not one of the 42 tokens", "Invalid", "parse_invalid"))
    d = Doc("M"); rec = _rec(d); rec["type"] = "object"
    out.append(d.case("unknown-record-key", "unknown_token_or_key", "a structural-looking record key", "Invalid",
                      "record_key", record=rec))
    d = Doc("M"); i = d.find("slot.type", "sona pi"); out.append(d.replace(i, d.subject(i) + " li nanpa").case(
        "unknown-primitive", "unknown_token_or_key", "unknown primitive word 'nanpa'", "Invalid", "parse_invalid"))
    d = Doc("M"); i = d.find("res.decl", "ijo pi"); out.append(d.replace(i, "Ijo" + d.lines[i][3:]).case(
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
