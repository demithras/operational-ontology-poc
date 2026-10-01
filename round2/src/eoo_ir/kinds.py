"""Static vocabulary of the frozen EOO IR (mirrors ontology/ir.schema.json).

This module only names things; it never decides what a value means.
"""
from __future__ import annotations

# Resource arrays of an IR package, in schema order.
RESOURCE_ARRAYS = (
    "object_types",
    "link_types",
    "interfaces",
    "functions",
    "actions",
    "policies",
    "authority_rules",
    "observation_types",
    "constraints",
)

PRIMITIVES = ("string", "integer", "number", "boolean", "datetime", "date", "json", "bytes")
TYPE_CONSTRUCTORS = ("ref", "list", "optional")
EFFECT_OPERATIONS = ("create", "update", "delete", "link", "unlink", "external_call", "git_change")
POLICY_DECISIONS = ("allow", "deny", "require_approval", "classify")
IDEMPOTENCY = ("required", "not_applicable")
AUTHORITY_EFFECTS = ("allow", "deny")
SEVERITIES = ("hard", "soft")
DETERMINISM = ("deterministic", "nondeterministic", "external-model")
PURITY = "NO_COMMITTED_BUSINESS_SIDE_EFFECT"
TRUTH_STATUS = "observed"

# Reference prefixes used by Action authority_refs / policy_refs (frozen examples:
# "auth:inventory-transfer" -> authority rule "inventory-transfer").
AUTH_PREFIX = "auth:"
POLICY_PREFIX = "policy:"
# Import-qualified external reference: "<import string>#<name>".
IMPORT_SEP = "#"
