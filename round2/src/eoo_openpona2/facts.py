"""Rule id -> (whose fact, field name, value). 'whose': pkg | subj (the {S:..} resource) | prop / param (the
{C:..} owner's property / parameter) | eff (the effect the line continues). value: a literal stated by the line
itself, or 'atom' (the value atom), 'ref', 'type', 'name' (the {P}/{K} atom)."""
from __future__ import annotations

FACTS = {
    "pkg.decl": ("pkg", "package_id", "atom"), "pkg.version": ("pkg", "version", "atom"),
    "pkg.domain": ("pkg", "domain_id", "atom"), "pkg.imports_empty": ("pkg", "imports_empty", True),
    "res.version": ("subj", "version", "atom"), "obj.description": ("subj", "description", "atom"),
    "obj.implements": ("subj", "implements", "ref"), "obj.pk": ("subj", "primary_key", "name"),
    "link.props_empty": ("subj", "props_empty", True),
    "prop.type": ("prop", "type", "type"), "prop.required_t": ("prop", "required", True),
    "prop.required_f": ("prop", "required", False), "prop.immutable_t": ("prop", "immutable", True),
    "prop.immutable_f": ("prop", "immutable", False), "prop.description": ("prop", "description", "atom"),
    "prop.constraint": ("prop", "constraints", "atom"), "prop.constraints_empty": ("prop", "constraints_empty", True),
    "param.type": ("param", "type", "type"), "param.required_t": ("param", "required", True),
    "param.required_f": ("param", "required", False),
    "link.ends": ("subj", "ends", "ref"), "link.from_min": ("subj", "from_min", "atom"),
    "link.from_max": ("subj", "from_max", "atom"), "link.from_star": ("subj", "from_star", True),
    "link.to_min": ("subj", "to_min", "atom"), "link.to_max": ("subj", "to_max", "atom"),
    "link.to_star": ("subj", "to_star", True), "link.directed_t": ("subj", "directed", True),
    "link.directed_f": ("subj", "directed", False),
    "iface.required_link": ("subj", "required_links", "ref"), "iface.capability": ("subj", "capabilities", "atom"),
    "fn.purity": ("subj", "purity", "NO_COMMITTED_BUSINESS_SIDE_EFFECT"), "fn.output": ("subj", "output", "type"),
    "fn.reads": ("subj", "reads", "ref"), "fn.impl": ("subj", "implementation_ref", "atom"),
    "fn.det_deterministic": ("subj", "determinism", "deterministic"),
    "fn.det_nondeterministic": ("subj", "determinism", "nondeterministic"),
    "fn.det_external": ("subj", "determinism", "external-model"),
    "act.authority": ("subj", "authority_refs", "ref"), "act.policy": ("subj", "policy_refs", "ref"),
    "act.precondition": ("subj", "preconditions", "atom"), "act.idem_required": ("subj", "idempotency", "required"),
    "act.idem_na": ("subj", "idempotency", "not_applicable"), "act.outcome": ("subj", "outcome_predicate", "atom"),
    "act.compensation": ("subj", "compensation_action", "ref"),
    "act.compensation_null": ("subj", "compensation_action", None),
    "eff.field": ("eff", "fields", "atom"), "eff.fields_empty": ("eff", "fields_empty", True),
    "pol.allow": ("subj", "decision", "allow"), "pol.deny": ("subj", "decision", "deny"),
    "pol.require_approval": ("subj", "decision", "require_approval"), "pol.classify": ("subj", "decision", "classify"),
    "pol.expression": ("subj", "expression_ref", "atom"), "auth.principal": ("subj", "principal_selector", "atom"),
    "auth.capability": ("subj", "capability", "atom"), "auth.resource": ("subj", "resource_selector", "atom"),
    "auth.allow": ("subj", "effect", "allow"), "auth.deny": ("subj", "effect", "deny"),
    "auth.deleg_t": ("subj", "delegation_allowed", True), "auth.deleg_f": ("subj", "delegation_allowed", False),
    "obs.subject": ("subj", "subject_type", "ref"), "obs.source": ("subj", "source_binding", "atom"),
    "obs.truth": ("subj", "truth_status", "observed"),
    "con.scope": ("subj", "scope", "atom"), "con.expression": ("subj", "expression_ref", "atom"),
    "con.hard": ("subj", "severity", "hard"), "con.soft": ("subj", "severity", "soft"),
}
# Effect lines: rule id -> IR operation. Each declares the next effect of its action.
EFFECT_OPS = {"eff.create": "create", "eff.update": "update", "eff.delete": "delete", "eff.link": "link",
              "eff.unlink": "unlink", "eff.git_change": "git_change", "eff.external_call": "external_call"}
META_RULES = {"pkg.meta", "pkg.meta_empty", "meta.entry", "meta.obj_empty", "meta.item", "meta.list_empty",
              "meta.close", "meta.true", "meta.false", "meta.null", "meta.int", "meta.float", "meta.str"}
TYPE_NODE_RULES = {"type.list": "list", "type.optional": "optional"}
