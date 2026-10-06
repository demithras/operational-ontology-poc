"""Tiny builder for the frozen real-domain IR files; records provenance for every resource it emits."""
from __future__ import annotations

from collections import OrderedDict

KINDS = ("object_types", "link_types", "interfaces", "functions", "actions", "policies", "authority_rules",
         "observation_types", "constraints")
KIND_LABEL = {"object_types": "ObjectType", "link_types": "LinkType", "interfaces": "Interface", "functions": "Function",
              "actions": "Action", "policies": "Policy", "authority_rules": "AuthorityRule",
              "observation_types": "ObservationType", "constraints": "Constraint"}

S, I, N, BO, DT, J = "string", "integer", "number", "boolean", "datetime", "json"


def ref(x):
    return {"ref": x}


def opt(t):
    return {"optional": t}


def lst(t):
    return {"list": t}


def card(lo, hi):
    return {"min": lo, "max": hi}


ONE, OPT1, MANY, ONE_MANY = card(1, 1), card(0, 1), card(0, "*"), card(1, "*")


def p(name, typ=S, req=False, imm=False, c=None, d=None):
    out = {"name": name, "type": typ, "required": req, "immutable": imm}
    if d:
        out["description"] = d
    if c:
        out["constraints"] = list(c)
    return out


def enum(*vals):
    return "enum:" + "|".join(vals)


def param(name, typ, req=True):
    return {"name": name, "type": typ, "required": req}


class Builder:
    def __init__(self, package_id, domain_id, version, metadata=None):
        self.head = {"package_id": package_id, "domain_id": domain_id, "version": version, "imports": []}
        self.res = {k: [] for k in KINDS}
        self.prov: list[tuple[str, str, str, str]] = []
        self.choices: list[str] = []
        self.metadata = metadata

    def _add(self, kind, r, src, note=""):
        self.res[kind].append(r)
        self.prov.append((kind, r["id"], src, note))

    def decide(self, text: str) -> None:
        self.choices.append(text)

    def obj(self, id, pk, props, implements=(), desc=None, src="", note=""):
        r = {"id": id, "primary_key": pk, "properties": props, "implements": list(implements)}
        if desc:
            r["description"] = desc
        self._add("object_types", r, src, note)

    def link(self, id, frm, to, fc, tc, props=(), src="", note=""):
        r = {"id": id, "from": frm, "to": to, "from_cardinality": fc, "to_cardinality": tc, "directed": True,
             "properties": list(props)}
        self._add("link_types", r, src, note)

    def iface(self, id, props=(), links=(), caps=(), src="", note=""):
        self._add("interfaces", {"id": id, "required_properties": list(props), "required_links": list(links),
                                 "capabilities": list(caps)}, src, note)

    def fn(self, id, inputs, output, reads, impl, det="deterministic", src="", note=""):
        self._add("functions", {"id": id, "inputs": inputs, "output": output, "purity": "NO_COMMITTED_BUSINESS_SIDE_EFFECT",
                                "reads": list(reads), "implementation_ref": impl, "determinism": det}, src, note)

    def action(self, id, inputs, auth, pol, pre, effects, idem, outcome, comp, version, src="", note=""):
        self._add("actions", {"id": id, "inputs": inputs, "authority_refs": [f"auth:{a}" for a in auth],
                              "policy_refs": [f"policy:{x}" for x in pol], "preconditions": list(pre), "effects": effects,
                              "idempotency": idem, "outcome_predicate": outcome, "compensation_action": comp,
                              "version": version}, src, note)

    def policy(self, id, decision, expr, version, src="", note=""):
        self._add("policies", {"id": id, "decision": decision, "expression_ref": expr, "version": version}, src, note)

    def authority(self, id, principal, cap, resource, effect, deleg, src="", note=""):
        self._add("authority_rules", {"id": id, "principal_selector": principal, "capability": cap,
                                      "resource_selector": resource, "effect": effect, "delegation_allowed": deleg}, src, note)

    def observation(self, id, subject, props, source, src="", note=""):
        self._add("observation_types", {"id": id, "subject_type": subject, "properties": props, "source_binding": source,
                                        "truth_status": "observed"}, src, note)

    def constraint(self, id, scope, expr, severity, src="", note=""):
        self._add("constraints", {"id": id, "scope": scope, "expression_ref": expr, "severity": severity}, src, note)

    def ir(self) -> dict:
        out = OrderedDict(self.head)
        for k in KINDS:
            out[k] = self.res[k]
        if self.metadata is not None:
            out["metadata"] = self.metadata
        return dict(out)

    def provenance_md(self, title: str, intro: str, src_header: str) -> str:
        lines = [f"# {title}", "", intro, "", "## Resource counts", "", "| kind | count |", "|---|---|"]
        for k in KINDS:
            lines.append(f"| {KIND_LABEL[k]} | {len(self.res[k])} |")
        lines += ["", f"## Resource provenance", "", f"| kind | id | {src_header} | note |", "|---|---|---|---|"]
        for kind, rid, src, note in self.prov:
            esc = lambda s: s.replace("|", "\\|").replace("\n", " ")  # noqa: E731
            lines.append(f"| {KIND_LABEL[kind]} | `{esc(rid)}` | {esc(src)} | {esc(note)} |")
        lines += ["", "## Source gaps and decisions", ""]
        lines += [f"{n}. {c}" for n, c in enumerate(self.choices, 1)]
        return "\n".join(lines) + "\n"
