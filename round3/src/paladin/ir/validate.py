"""Validation of an IR package: frozen JSON Schema + referential integrity.

Referential rules (written here, once, so every surface is judged by the same rules):

* ids are unique per resource kind; property names are unique per owner; parameter names
  are unique per function/action;
* ``primary_key`` names a property of its own object type;
* a reference resolves against ids of the allowed kinds of its slot (see ``_SLOTS`` below).
  Zero matches -> ``unresolved_ref``; more than one distinct match -> ``ambiguous_ref``.
  A reference that matches no local resource may be import-qualified ("<import>#<name>"),
  where ``<import>`` is an entry of ``imports``; such a reference is accepted but not
  checked any deeper (the imported package is outside this document);
* ``reads`` entries may also be ``<Type>.<property>`` (object/link/observation type);
* ``authority_refs`` entries are ``auth:<authority rule id>``; ``policy_refs`` entries are
  ``policy:<policy id>`` (the spelling used by the frozen examples);
* effect targets resolve by operation (create/update/delete -> object type, link/unlink ->
  link type, git_change -> object or link type); ``external_call`` targets are opaque system
  names. Effect ``fields`` of a locally resolved target must be properties of that target.

``constraint.scope``, authority selectors, capabilities and every ``*_ref``/predicate string
other than the ones listed above are opaque atoms: they are NOT resolved here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

from jsonschema import Draft202012Validator

from .kinds import AUTH_PREFIX, IMPORT_SEP, POLICY_PREFIX, RESOURCE_ARRAYS

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "ontology" / "ir.schema.json"


@dataclass(frozen=True)
class IRError:
    code: str  # schema | duplicate_id | duplicate_name | bad_primary_key | unresolved_ref | ambiguous_ref | unknown_field
    path: str
    message: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.path}: {self.message}"


@lru_cache(maxsize=1)
def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(load_schema())


def _jpath(parts) -> str:
    out = ""
    for p in parts:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out or "<root>"


def schema_errors(pkg: Any) -> list[IRError]:
    errs = [IRError("schema", _jpath(e.absolute_path), e.message) for e in _validator().iter_errors(pkg)]
    return sorted(errs, key=lambda e: (e.path, e.message))


_PROP_KINDS = ("object_types", "link_types", "observation_types")
_EFFECT_KINDS = {
    "create": ("object_types",),
    "update": ("object_types",),
    "delete": ("object_types",),
    "link": ("link_types",),
    "unlink": ("link_types",),
    "git_change": ("object_types", "link_types"),
}
ENDPOINT_KINDS = ("object_types", "interfaces")  # link endpoints and typeExpr refs
READS_KINDS = ("object_types", "link_types", "observation_types")


class Index:
    """Id / property index of one package (assumes it is schema-valid)."""

    def __init__(self, pkg: dict):
        self.ids = {k: [r["id"] for r in pkg[k]] for k in RESOURCE_ARRAYS}
        self.idset = {k: set(v) for k, v in self.ids.items()}
        self.imports = sorted(set(pkg.get("imports", [])))
        self.props: dict[tuple[str, str], set[str]] = {}
        for kind, key in (("object_types", "properties"), ("link_types", "properties"),
                          ("observation_types", "properties")):
            for r in pkg[kind]:
                self.props.setdefault((kind, r["id"]), set()).update(p["name"] for p in r.get(key, []))

    def resolve(self, ref: str, kinds, prefix: str = "", allow_prop: bool = False) -> list[tuple]:
        """All distinct things ``ref`` denotes. Empty = unresolved, >1 = ambiguous."""
        matches: list[tuple] = []
        name = None
        if not prefix:
            name = ref
        elif ref.startswith(prefix):
            name = ref[len(prefix):]
        if name is not None:
            for k in kinds:
                if name in self.idset[k]:
                    matches.append((k, name))
            if allow_prop:
                for i, ch in enumerate(name):
                    if ch != ".":
                        continue
                    head, tail = name[:i], name[i + 1:]
                    for k in kinds:
                        if k in _PROP_KINDS and head in self.idset[k] and tail in self.props.get((k, head), ()):
                            matches.append((k, head, tail))
        if not matches:
            for imp in self.imports:
                if ref.startswith(imp + IMPORT_SEP) and len(ref) > len(imp) + 1:
                    matches.append(("import", imp))
        return list(dict.fromkeys(matches))


def _type_refs(te: Any, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(te, dict):
        if "ref" in te:
            yield path + ".ref", te["ref"]
        elif "list" in te:
            yield from _type_refs(te["list"], path + ".list")
        elif "optional" in te:
            yield from _type_refs(te["optional"], path + ".optional")


def referential_errors(pkg: dict) -> list[IRError]:
    """Referential integrity of a schema-valid package."""
    errs: list[IRError] = []
    ix = Index(pkg)

    def check(path: str, ref: str, kinds, prefix: str = "", allow_prop: bool = False) -> list[tuple]:
        m = ix.resolve(ref, kinds, prefix, allow_prop)
        if not m:
            errs.append(IRError("unresolved_ref", path, f"{ref!r} does not resolve to any of {list(kinds)}"))
        elif len(m) > 1:
            errs.append(IRError("ambiguous_ref", path, f"{ref!r} matches {len(m)} resources: {m}"))
        return m

    for kind in RESOURCE_ARRAYS:
        seen: set[str] = set()
        for i, r in enumerate(pkg[kind]):
            if r["id"] in seen:
                errs.append(IRError("duplicate_id", f"{kind}[{i}].id", f"duplicate id {r['id']!r}"))
            seen.add(r["id"])

    def names_unique(path: str, items: list, what: str) -> None:
        seen: set[str] = set()
        for j, it in enumerate(items):
            if it["name"] in seen:
                errs.append(IRError("duplicate_name", f"{path}[{j}].name", f"duplicate {what} name {it['name']!r}"))
            seen.add(it["name"])

    def typed_props(path: str, props: list) -> None:
        for j, p in enumerate(props):
            for tp, ref in _type_refs(p["type"], f"{path}[{j}].type"):
                check(tp, ref, ENDPOINT_KINDS)

    for i, o in enumerate(pkg["object_types"]):
        base = f"object_types[{i}]"
        names_unique(f"{base}.properties", o["properties"], "property")
        typed_props(f"{base}.properties", o["properties"])
        if o["primary_key"] not in {p["name"] for p in o["properties"]}:
            errs.append(IRError("bad_primary_key", f"{base}.primary_key",
                                f"{o['primary_key']!r} is not a property of {o['id']!r}"))
        for j, ref in enumerate(o["implements"]):
            check(f"{base}.implements[{j}]", ref, ("interfaces",))
    for i, lk in enumerate(pkg["link_types"]):
        base = f"link_types[{i}]"
        check(f"{base}.from", lk["from"], ENDPOINT_KINDS)
        check(f"{base}.to", lk["to"], ENDPOINT_KINDS)
        names_unique(f"{base}.properties", lk.get("properties", []), "property")
        typed_props(f"{base}.properties", lk.get("properties", []))
    for i, it in enumerate(pkg["interfaces"]):
        base = f"interfaces[{i}]"
        names_unique(f"{base}.required_properties", it["required_properties"], "property")
        typed_props(f"{base}.required_properties", it["required_properties"])
        for j, ref in enumerate(it["required_links"]):
            check(f"{base}.required_links[{j}]", ref, ("link_types",))
    for i, f in enumerate(pkg["functions"]):
        base = f"functions[{i}]"
        names_unique(f"{base}.inputs", f["inputs"], "parameter")
        for j, p in enumerate(f["inputs"]):
            for tp, ref in _type_refs(p["type"], f"{base}.inputs[{j}].type"):
                check(tp, ref, ENDPOINT_KINDS)
        for tp, ref in _type_refs(f["output"], f"{base}.output"):
            check(tp, ref, ENDPOINT_KINDS)
        for j, ref in enumerate(f["reads"]):
            check(f"{base}.reads[{j}]", ref, READS_KINDS, allow_prop=True)
    for i, a in enumerate(pkg["actions"]):
        base = f"actions[{i}]"
        names_unique(f"{base}.inputs", a["inputs"], "parameter")
        for j, p in enumerate(a["inputs"]):
            for tp, ref in _type_refs(p["type"], f"{base}.inputs[{j}].type"):
                check(tp, ref, ENDPOINT_KINDS)
        for j, ref in enumerate(a["authority_refs"]):
            check(f"{base}.authority_refs[{j}]", ref, ("authority_rules",), prefix=AUTH_PREFIX)
        for j, ref in enumerate(a["policy_refs"]):
            check(f"{base}.policy_refs[{j}]", ref, ("policies",), prefix=POLICY_PREFIX)
        for j, e in enumerate(a["effects"]):
            kinds = _EFFECT_KINDS.get(e["operation"])
            if kinds is None:  # external_call: opaque system name
                continue
            m = check(f"{base}.effects[{j}].target", e["target"], kinds)
            if len(m) == 1 and m[0][0] != "import":
                allowed = ix.props.get((m[0][0], m[0][1]), set())
                for q, fld in enumerate(e.get("fields", [])):
                    if fld not in allowed:
                        errs.append(IRError("unknown_field", f"{base}.effects[{j}].fields[{q}]",
                                            f"{fld!r} is not a property of {m[0][1]!r}"))
        ca = a.get("compensation_action")
        if isinstance(ca, str):
            check(f"{base}.compensation_action", ca, ("actions",))
    for i, o in enumerate(pkg["observation_types"]):
        base = f"observation_types[{i}]"
        check(f"{base}.subject_type", o["subject_type"], ("object_types",))
        names_unique(f"{base}.properties", o["properties"], "property")
        typed_props(f"{base}.properties", o["properties"])
    return sorted(errs, key=lambda e: (e.path, e.code))


def validate(pkg: Any) -> list[IRError]:
    """Schema errors if any, else referential errors. Empty list = valid."""
    errs = schema_errors(pkg)
    return errs if errs else referential_errors(pkg)
