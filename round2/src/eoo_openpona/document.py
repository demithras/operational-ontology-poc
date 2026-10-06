"""Text + record -> Document: matched lines, declarations, facts. No IR yet, no guessing."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .errors import Ambiguous, Invalid, Unresolved
from .lines import Line, n_slots, read_line
from .vocab import ALL_HEADS

KEY_RE = re.compile(r"L([1-9][0-9]*)\.a([1-9][0-9]*)")
PKG = "kulupu"  # the package's own (fixed) address

# tid -> (field, value) for facts about the subject; value: 'atom' | 'ref' | 'type' | literal
FACTS = {
    "pkg.decl": ("package_id", "atom"), "pkg.version": ("version", "atom"), "pkg.domain": ("domain_id", "atom"),
    "pkg.imports_empty": ("imports_empty", True), "pkg.meta_empty": ("meta_empty", True),
    "meta.obj_empty": ("obj_empty", True), "meta.list_empty": ("list_empty", True),
    "meta.true": ("scalar", True), "meta.false": ("scalar", False), "meta.null": ("scalar", None),
    "meta.int": ("scalar", ("int",)), "meta.float": ("scalar", ("float",)), "meta.str": ("scalar", ("str",)),
    "res.version": ("version", "atom"), "obj.description": ("description", "atom"),
    "obj.implements": ("implements", "ref"), "obj.pk": ("primary_key", "ref"),
    "link.props_empty": ("props_empty", True), "slot.type": ("type", "type"),
    "slot.required_t": ("required", True), "slot.required_f": ("required", False),
    "prop.immutable_t": ("immutable", True), "prop.immutable_f": ("immutable", False),
    "prop.description": ("description", "atom"), "prop.constraint": ("constraints", "atom"),
    "prop.constraints_empty": ("constraints_empty", True),
    "type.list": ("ctor", "list"), "type.optional": ("ctor", "optional"),
    "link.ends": ("ends", "ref"), "link.from_min": ("from_min", "atom"), "link.from_max": ("from_max", "atom"),
    "link.from_star": ("from_star", True), "link.to_min": ("to_min", "atom"), "link.to_max": ("to_max", "atom"),
    "link.to_star": ("to_star", True), "link.directed_t": ("directed", True), "link.directed_f": ("directed", False),
    "iface.required_link": ("required_links", "ref"), "iface.capability": ("capabilities", "atom"),
    "fn.purity": ("purity", "NO_COMMITTED_BUSINESS_SIDE_EFFECT"), "fn.output": ("output", "type"),
    "fn.reads": ("reads", "ref"), "fn.impl": ("implementation_ref", "atom"),
    "fn.det_deterministic": ("determinism", "deterministic"),
    "fn.det_nondeterministic": ("determinism", "nondeterministic"), "fn.det_external": ("determinism", "external-model"),
    "act.authority": ("authority_refs", "ref"), "act.policy": ("policy_refs", "ref"),
    "act.precondition": ("preconditions", "atom"), "act.idem_required": ("idempotency", "required"),
    "act.idem_na": ("idempotency", "not_applicable"), "act.outcome": ("outcome_predicate", "atom"),
    "act.compensation": ("compensation_action", "ref"), "act.compensation_null": ("compensation_action", None),
    "eff.create": ("op", "create"), "eff.update": ("op", "update"), "eff.delete": ("op", "delete"),
    "eff.link": ("op", "link"), "eff.unlink": ("op", "unlink"), "eff.git_change": ("op", "git_change"),
    "eff.external_call": ("op", "external_call"), "eff.field": ("fields", "ref"),
    "eff.field_opaque": ("fields", "atom"), "eff.fields_empty": ("fields_empty", True),
    "pol.allow": ("decision", "allow"), "pol.deny": ("decision", "deny"),
    "pol.require_approval": ("decision", "require_approval"), "pol.classify": ("decision", "classify"),
    "pol.expression": ("expression_ref", "atom"), "auth.principal": ("principal_selector", "atom"),
    "auth.capability": ("capability", "atom"), "auth.resource": ("resource_selector", "atom"),
    "auth.allow": ("effect", "allow"), "auth.deny": ("effect", "deny"),
    "auth.deleg_t": ("delegation_allowed", True), "auth.deleg_f": ("delegation_allowed", False),
    "obs.subject": ("subject_type", "ref"), "obs.source": ("source_binding", "atom"),
    "obs.truth": ("truth_status", "observed"),
    "con.scope": ("scope", "atom"), "con.expression": ("expression_ref", "atom"),
    "con.hard": ("severity", "hard"), "con.soft": ("severity", "soft"),
}
# tid -> what the declared address is (the subject, if any, is its parent)
DECLS = {"res.decl": "resource", "pkg.import": "import", "pkg.ext": "external", "prop.decl": "property",
         "fn.input": "parameter", "act.effect": "effect", "type.list": "type_node", "type.optional": "type_node",
         "pkg.meta": "meta_node", "meta.entry": "meta_node", "meta.item": "meta_node"}


@dataclass
class Decl:
    addr: str
    what: str
    line: int
    atom: str | None = None
    parent: str | None = None
    tid: str = ""
    refs: list = field(default_factory=list)  # ('ref', addr, role) items on the declaring line


@dataclass
class Document:
    lines: list[Line]
    decls: dict[str, Decl]
    facts: dict[tuple[str, str], list[tuple[int, object]]]
    order: list[str]  # declared addresses in line order


def split_lines(text: str) -> list[str]:
    if not isinstance(text, str):
        raise Invalid("text_type", f"text must be str, got {type(text).__name__}")
    body = text[:-1] if text.endswith("\n") else text
    raw = body.split("\n") if body else []
    for i, ln in enumerate(raw, 1):
        if not ln.strip():
            raise Invalid("blank_line", "one statement per line; blank lines are not statements", i)
        if "\r" in ln:
            raise Invalid("parse_invalid", "carriage return inside a line", i)
    return raw


def check_record(lines: list[Line], record) -> dict[str, str]:
    if not isinstance(record, dict):
        raise Invalid("record_type", f"record must be a mapping, got {type(record).__name__}")
    want = {f"L{ln.lineno}.a{j}" for ln in lines for j in range(1, n_slots(ln.tid) + 1)}
    for k, v in record.items():
        if not isinstance(k, str) or not KEY_RE.fullmatch(k):
            raise Invalid("record_key", f"record key {k!r} is not a neutral address 'L<line>.a<slot>'")
        if k not in want:
            raise Invalid("dangling_atom", f"record key {k!r} fills no atom slot any line declares")
        if not isinstance(v, str):
            raise Invalid("atom_type", f"record value at {k} must be a string atom, got {type(v).__name__}")
    missing = sorted(want - set(record), key=lambda s: tuple(int(x) for x in KEY_RE.fullmatch(s).groups()))
    if missing:
        raise Unresolved("missing_atom", f"atom slots with no bound value: {missing[:5]}")
    return record


def read_document(text: str, record) -> Document:
    lines = [read_line(i, t) for i, t in enumerate(split_lines(text), 1)]
    rec = check_record(lines, record)
    decls: dict[str, Decl] = {}
    facts: dict[tuple[str, str], list] = {}
    order: list[str] = []
    for ln in lines:
        items = ln.slots
        atoms = [rec[f"L{ln.lineno}.a{j}"] for j in range(1, n_slots(ln.tid) + 1)]
        assert len(atoms) <= 1, ln.tid  # every template binds at most one atom
        atom = atoms[0] if atoms else None
        subj = next((v for k, v, *_ in items if k == "subj"), None)
        decl = next((v for k, v, *_ in items if k in ("decl", "decl0")), None)
        refs = [it for it in items if it[0] == "ref"]
        if ln.tid in DECLS:
            if decl in decls:
                raise Ambiguous("duplicate_address", f"address {decl!r} is declared twice "
                                f"(lines {decls[decl].line} and {ln.lineno})", ln.lineno)
            what = DECLS[ln.tid]
            if what == "resource":
                what = ALL_HEADS[decl.split()[0]]
            decls[decl] = Decl(decl, what, ln.lineno, atom if (ln.tid != "act.effect" and ln.tid not in (
                "type.list", "type.optional", "meta.item")) else None, subj or PKG, ln.tid, refs)
            order.append(decl)
        if ln.tid not in FACTS:
            continue
        name, val = FACTS[ln.tid]
        if ln.tid in ("type.list", "type.optional"):
            subj = decl
            facts.setdefault((decl, "type"), []).append((ln.lineno, next(v for k, v in items if k == "type")))
        subj = subj or PKG
        if val == "atom":
            val = atom
        elif val == "ref":
            val = tuple(r[1] for r in refs) if len(refs) > 1 else refs[0][1]
        elif val == "type":
            val = next(v for k, v in items if k == "type")
        elif isinstance(val, tuple):  # metadata scalar literal: (kind, atom)
            val = (val[0], atom)
        facts.setdefault((subj, name), []).append((ln.lineno, val))
    return Document(lines, decls, facts, order)
