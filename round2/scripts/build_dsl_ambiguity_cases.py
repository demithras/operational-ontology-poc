#!/usr/bin/env python3
"""Instantiate round2/protocol/h15_ambiguity_classes.json for the direct DSL baseline.

Writes round2/tests/h15/dsl_ambiguity_cases.jsonl. Every edit must match its base text EXACTLY ONCE
(a silent substitution miss would leave the base unchanged and the case would test nothing).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eoo_dsl import render  # noqa: E402

BASES = {name: render(json.loads((ROOT / "ontology" / "examples" / f"{f}.json").read_text()))
         for name, f in (("M", "manufacturing-minimal"), ("P", "project-domain-minimal"))}

AUTH_HDR = "authority_rules:\n  - id: inventory-transfer\n"
CASES = [
    # (id, class, base, [(old, new)], expected, dsl_error, description)
    ("type-missing-property", "missing_type", "M", [("      - name: quantity\n        type: integer\n        required: true\n        immutable: false\n    implements", "      - name: quantity\n        required: true\n        immutable: false\n    implements")], "error", "DslMissingField", "property without type"),
    ("type-missing-output", "missing_type", "M", [("    output: integer\n", "")], "error", "DslMissingField", "function without output type"),
    ("type-nonprimitive-name", "missing_type", "M", [("        type: integer\n        required: true\n        immutable: false\n    implements", "        type: number_of_things\n        required: true\n        immutable: false\n    implements")], "error", "DslEnumError", "type that is not a primitive"),
    ("card-missing-to", "missing_cardinality", "P", [("    to_cardinality:\n      min: 1\n      max: 1\n", "")], "error", "DslMissingField", "link without to_cardinality"),
    ("card-missing-max", "missing_cardinality", "P", [("    to_cardinality:\n      min: 1\n      max: 1\n", "    to_cardinality:\n      min: 1\n")], "error", "DslMissingField", "cardinality without max"),
    ("card-null-max", "missing_cardinality", "P", [('      max: "*"\n', "      max:\n")], "error", "DslTypeError", "cardinality max left empty"),
    ("kind-renamed-functions", "missing_resource_kind", "M", [("functions:\n", "callables:\n")], "error", "DslUnknownKey", "functions list under a non-kind key"),
    ("kind-action-with-output", "missing_resource_kind", "M", [("    effects:\n      - target: WMS\n        operation: external_call\n        fields: [quantity]\n", "    output: integer\n")], "error", "DslUnknownKey", "an action carrying a function-only field and no effects"),
    ("kind-function-no-purity", "missing_resource_kind", "M", [("    purity: NO_COMMITTED_BUSINESS_SIDE_EFFECT\n", "")], "error", "DslMissingField", "function whose purity marker is removed"),
    ("auth-missing-effect", "missing_authority_effect", "M", [("    effect: allow\n    delegation_allowed: true\n", "    delegation_allowed: true\n")], "error", "DslMissingField", "authority rule without effect"),
    ("auth-null-effect", "missing_authority_effect", "P", [("    effect: allow\n    delegation_allowed: false\n", "    effect:\n    delegation_allowed: false\n")], "error", "DslTypeError", "authority effect left empty"),
    ("policy-missing-decision", "missing_policy_decision", "M", [("    decision: allow\n", "")], "error", "DslMissingField", "policy without decision"),
    ("policy-null-decision", "missing_policy_decision", "P", [("    decision: allow\n", "    decision:\n")], "error", "DslTypeError", "policy decision left empty"),
    ("version-missing-package", "missing_version", "M", [("domain_id: manufacturing\nversion: v1\n", "domain_id: manufacturing\n")], "error", "DslMissingField", "package without version"),
    ("version-missing-action", "missing_version", "M", [("    compensation_action: null\n    version: v1\n", "    compensation_action: null\n")], "error", "DslMissingField", "action without version"),
    ("version-missing-policy", "missing_version", "P", [('    expression_ref: "policy:preregistration-complete:v1"\n    version: v1\n', '    expression_ref: "policy:preregistration-complete:v1"\n')], "error", "DslMissingField", "policy without version"),
    ("required-missing-property", "missing_required_flag", "M", [("        type: string\n        required: true\n        immutable: true\n      - name: quantity", "        type: string\n        immutable: true\n      - name: quantity")], "error", "DslMissingField", "property without required flag"),
    ("required-null-property", "missing_required_flag", "P", [("      - name: claim\n        type: string\n        required: true\n", "      - name: claim\n        type: string\n        required:\n")], "error", "DslTypeError", "property required flag left empty"),
    ("bind-ambiguous-reads", "ambiguous_binding", "M", [("reads: [InventoryLot.quantity]", "reads: [InventoryLot]"), ("link_types: []\n", "link_types:\n  - id: InventoryLot\n    from: InventoryLot\n    to: InventoryLot\n    from_cardinality: {min: 0, max: 1}\n    to_cardinality: {min: 0, max: 1}\n")], "error", "DslAmbiguousReference", "reads names both an object type and a link type"),
    ("bind-ambiguous-git-target", "ambiguous_binding", "P", [("link_types:\n  - id: HypothesisHasEvidence", "link_types:\n  - id: Hypothesis\n    from: Hypothesis\n    to: Evidence\n    from_cardinality: {min: 0, max: 1}\n    to_cardinality: {min: 0, max: 1}\n  - id: HypothesisHasEvidence")], "error", "DslAmbiguousReference", "git_change target is both an object type and a link type"),
    ("bind-duplicate-id", "ambiguous_binding", "P", [("link_types:\n", "  - id: Hypothesis\n    primary_key: id\n    properties:\n      - name: id\n        type: string\n        required: true\n    implements: []\nlink_types:\n")], "error", "DslDuplicateId", "two object types with the same id"),
    ("unresolved-type-ref", "unresolved_binding", "M", [("    inputs:\n      - name: lot\n        type: {ref: InventoryLot}\n        required: true\n    output: integer", "    inputs:\n      - name: lot\n        type: {ref: Inventory}\n        required: true\n    output: integer")], "unresolved", "DslUnresolvedReference", "type ref to a missing object type"),
    ("unresolved-link-end", "unresolved_binding", "P", [("    to: Evidence\n", "    to: Evidenc\n")], "unresolved", "DslUnresolvedReference", "link endpoint matches nothing"),
    ("unresolved-authority-ref", "unresolved_binding", "M", [('"auth:inventory-transfer"', '"auth:inventory-transfer-x"')], "unresolved", "DslUnresolvedReference", "authority_ref matches no rule"),
    ("unresolved-implements", "unresolved_binding", "M", [("implements: [Transferable]", "implements: [Transferabl]")], "unresolved", "DslUnresolvedReference", "implements an interface that does not exist"),
    ("dangling-key-typo", "dangling_atom", "M", [('    description: "Inventory lot"', '    descrption: "Inventory lot"')], "error", "DslUnknownKey", "misspelled key leaves its value without a slot"),
    ("dangling-extra-key", "dangling_atom", "M", [("      - name: quantity\n        type: integer\n        required: true\n        immutable: false\n    implements", "      - name: quantity\n        owner: team-a\n        type: integer\n        required: true\n        immutable: false\n    implements")], "error", "DslUnknownKey", "extra atom on a property"),
    ("dangling-bare-item", "dangling_atom", "P", [("    properties:\n      - name: id\n        type: string\n        required: true\n        immutable: true\n      - name: claim", "    properties:\n      - orphan_atom\n      - name: id\n        type: string\n        required: true\n        immutable: true\n      - name: claim")], "error", "DslTypeError", "bare scalar where a property mapping is expected"),
    ("parse-duplicate-key", "surface_parse_ambiguous", "M", [("version: v1\nimports: []", "version: v1\nversion: v2\nimports: []")], "error", "DslDuplicateKey", "same key twice"),
    ("parse-alias", "surface_parse_ambiguous", "M", [("    capabilities: [read, transfer]", "    capabilities: &c [read, transfer]\n    required_links: *c")], "error", "DslAliasError", "anchor and alias"),
    ("parse-two-documents", "surface_parse_ambiguous", "M", [("<END>", "---\npackage_id: other\n")], "error", "DslSurfaceAmbiguity", "two YAML documents"),
    ("parse-float-version", "surface_parse_ambiguous", "M", [('domain_id: manufacturing\nversion: v1\n', 'domain_id: manufacturing\nversion: 1.0\n')], "error", "DslTypeError", "1.0 is a number, not a version string"),
    ("parse-yes-bool", "surface_parse_ambiguous", "M", [("        type: integer\n        required: true\n        immutable: false\n    implements", "        type: integer\n        required: yes\n        immutable: false\n    implements")], "error", "DslTypeError", "yes is a string here, not a boolean"),
    ("parse-tab-indent", "surface_parse_ambiguous", "M", [("    primary_key: id\n", "\tprimary_key: id\n")], "error", "DslSyntaxError", "tab indentation"),
    ("token-enum", "unknown_token_or_key", "M", [("    idempotency: required", "    idempotency: maybe")], "error", "DslEnumError", "unknown idempotency value"),
    ("token-primitive", "unknown_token_or_key", "M", [("        type: integer\n        required: true\n        immutable: false\n    implements", "        type: int\n        required: true\n        immutable: false\n    implements")], "error", "DslEnumError", "int is not a primitive"),
    ("token-top-key", "unknown_token_or_key", "M", [("imports: []\n", "imports: []\nowner: me\n")], "error", "DslUnknownKey", "unknown package key"),
    ("token-effect-op", "unknown_token_or_key", "M", [("operation: external_call", "operation: call")], "error", "DslEnumError", "unknown effect operation"),
    ("token-type-ctor", "unknown_token_or_key", "M", [("type: {ref: InventoryLot}\n        required: true\n    output", "type: {reference: InventoryLot}\n        required: true\n    output")], "error", "DslUnknownKey", "unknown type constructor key"),
]


def build() -> list[dict]:
    rows = []
    for cid, cls, base, edits, expected, err, desc in CASES:
        text = BASES[base]
        for old, new in edits:
            if old == "<END>":
                text = text + new
                continue
            assert text.count(old) == 1, f"{cid}: edit target must occur exactly once, found {text.count(old)}: {old!r}"
            text = text.replace(old, new)
        assert text != BASES[base], cid
        rows.append({"id": cid, "class": cls, "base": base, "expected": expected, "dsl_error": err, "description": desc, "text": text})
    return rows


if __name__ == "__main__":
    rows = build()
    out = ROOT / "tests" / "h15" / "dsl_ambiguity_cases.jsonl"
    out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    print(f"wrote {len(rows)} cases to {out.relative_to(ROOT)}")
