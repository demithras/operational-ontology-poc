"""Every line shape the H15 OpenPona encoding renders or accepts (the encoding table's source).

Pattern placeholders (anything else is a literal token):
  {DECL:h,..}  address with one of the heads, declared by this line; binds the next atom slot
  {DECL0:h}    address declared by this line, binding no atom (effects, type nodes, list items)
  {S:h,..}     address of an already-declared thing this line talks about (no atom)
  {R:role}     reference address; the role fixes which heads may appear (see ROLES)
  {V:w}        atom slot written as the two tokens `w ni` ("this w, bound in the record")
  {NI}         atom slot written as the single token `ni`
  {TYPE}       a type phrase: a primitive phrase (vocab.PRIMITIVE_PHRASES) or a ref/type-node address
  {PKG}        the literal `kulupu` (the package itself), binding the next atom slot
Each entry: id -> (pattern, IR meaning, canon gloss justification, gloss strength).
"""
from __future__ import annotations

ROLES = {
    "endpoint": ("ijo", "selo", "weka"), "iface": ("selo", "weka"), "link": ("linja", "weka"),
    "object": ("ijo", "weka"), "object_or_link": ("ijo", "linja", "weka"), "action": ("pali", "weka"),
    "authority": ("ken", "weka"), "policy": ("lawa", "weka"), "import": ("kulupu",), "prop": ("sona",),
    "readable": ("ijo", "linja", "lukin", "sona", "weka"), "typeref": ("ijo", "selo", "weka", "nasin"),
}
_RES = "ijo,linja,selo,ilo,pali,lawa,ken,lukin,awen"

T = {
    # ---- package ----
    "pkg.decl": ("{PKG} li lon", "package_id (atom on the package)", "kulupu group/aggregate/collective = the package; lon presence: 'the package is present'", "strong"),
    "pkg.version": ("{V:tenpo} la kulupu li lon", "version", "tenpo temporalize/process through time: 'at this time-state the package is present'; the canonical 'version' gloss belongs to the particle anu, which cannot carry content", "moderate"),
    "pkg.domain": ("{V:ma} la kulupu li lon", "domain_id", "ma locate/scope/territory: 'in this scope the package is present'", "strong"),
    "pkg.import": ("kulupu li kute e {DECL:kulupu}", "imports[] element (declares an import address)", "kute receive/accept signal: the package receives another package (kulupu)", "strong"),
    "pkg.imports_empty": ("kulupu li kute e ala", "imports: [] (explicitly empty)", "ala negate/absence: receives nothing", "strong"),
    "pkg.ext": ("{DECL:weka} li tan {R:import}", "a name '<import>#<name>' (declares an external address)", "weka distance/away = outside this package; tan source: it derives from that import", "strong"),
    "pkg.meta": ("kulupu li sona e {DECL:sitelen}", "metadata entry (key atom)", "sona know/model: what the package knows about itself; sitelen represent: a represented value", "moderate"),
    "pkg.meta_empty": ("kulupu li sona e ala", "metadata: {}", "knows nothing", "moderate"),
    "meta.entry": ("{S:sitelen} li sona e {DECL:sitelen}", "JSON object member (key atom)", "as pkg.meta, one level down", "moderate"),
    "meta.obj_empty": ("{S:sitelen} li sona e ala", "JSON {}", "knows nothing", "moderate"),
    "meta.item": ("{S:sitelen} li linja e {DECL0:sitelen}", "JSON array element (order = line order)", "linja link/thread/chain: a chain of items", "strong"),
    "meta.list_empty": ("{S:sitelen} li linja e ala", "JSON []", "chains nothing", "strong"),
    "meta.true": ("{S:sitelen} li sama e lon", "JSON true", "sama match; lon presence/reality (pu: real, true)", "strong"),
    "meta.false": ("{S:sitelen} li sama e lon ala", "JSON false", "lon ala: not true", "strong"),
    "meta.null": ("{S:sitelen} li sama e ala", "JSON null", "ala absence: matches nothing", "strong"),
    "meta.int": ("{S:sitelen} li kulupu ijo li sama e {NI}", "JSON integer (atom = decimal literal)", "integer type phrase (see type rows) + matches the bound literal", "moderate"),
    "meta.float": ("{S:sitelen} li kulupu pilin li sama e {NI}", "JSON non-integer number (atom = JSON literal)", "number type phrase + bound literal", "weak"),
    "meta.str": ("{S:sitelen} li sitelen toki li sama e {NI}", "JSON string (atom)", "string type phrase + bound literal", "strong"),
    # ---- every resource ----
    "res.decl": ("{DECL:" + _RES + "} li lon", "a resource; its kind is the address head; id = atom", "lon presence: 'X is present'; head glosses: ijo entity, linja link, selo interface, ilo tool, pali execute, lawa govern, ken permission-capability, lukin observe, awen persist/hold", "strong"),
    "res.version": ("{V:tenpo} la {S:pali,lawa} li lon", "actions[].version / policies[].version", "as pkg.version", "moderate"),
    # ---- object type ----
    "obj.description": ("{S:ijo} li sitelen e {V:toki}", "object_types[].description", "sitelen represent: X is represented by this text (toki communicate)", "strong"),
    "obj.implements": ("{S:ijo} li sama e {R:iface}", "object_types[].implements[] element", "sama match/align/equivalence: X matches interface I", "strong"),
    "obj.pk": ("{S:ijo} li ni tan {R:prop}", "object_types[].primary_key (a property of X)", "ni bind/fix referent; tan source: X's referent is fixed from P", "strong"),
    "prop.decl": ("{S:ijo,linja,selo,lukin} li sona e {DECL:sona}", "properties[] / required_properties[] element (name atom)", "sona know/model: X models attribute P", "moderate"),
    "link.props_empty": ("{S:linja} li sona e ala", "link_types[].properties: []", "models nothing", "moderate"),
    # ---- property / parameter ----
    "slot.type": ("{S:sona,kute} li {TYPE}", "property/parameter type", "predicate nominal: P is (a) T", "strong"),
    "slot.required_t": ("{S:sona,kute} li wile", "required: true", "wile intend/need (pu: must)", "strong"),
    "slot.required_f": ("{S:sona,kute} li wile ala", "required: false", "not needed", "strong"),
    "prop.immutable_t": ("{S:sona} li awen", "immutable: true", "awen retain/persist (pu: enduring, kept)", "strong"),
    "prop.immutable_f": ("{S:sona} li awen ala", "immutable: false", "does not persist unchanged", "strong"),
    "prop.description": ("{S:sona} li sitelen e {V:toki}", "property description", "as obj.description", "strong"),
    "prop.constraint": ("{V:nasin} li lawa e {S:sona}", "property constraints[] element", "nasin route/method/rule; lawa govern: this rule governs P", "strong"),
    "prop.constraints_empty": ("ala li lawa e {S:sona}", "property constraints: []", "nothing governs P", "strong"),
    "type.list": ("{DECL0:nasin} li linja e {TYPE}", "{list: T}", "linja chain: a chain of T", "strong"),
    "type.optional": ("{DECL0:nasin} li {TYPE} anu ala", "{optional: T}", "anu alternative + ala absence: T or nothing", "strong"),
    # ---- link type ----
    "link.ends": ("{S:linja} li linja e {R:endpoint} tan {R:endpoint}", "link to (object) / from (source)", "linja link; e directed target = to; tan source = from", "strong"),
    "link.from_min": ("tan ijo la {S:linja} li lon e {V:kulupu}", "from_cardinality.min", "tan ijo la: for a source entity; lon presence: at least this many are present", "moderate"),
    "link.from_max": ("tan ijo la {S:linja} li ken e {V:kulupu}", "from_cardinality.max (integer)", "ken possibility: at most this many are possible", "moderate"),
    "link.from_star": ("tan ijo la {S:linja} li ken e kulupu ale", "from_cardinality.max = '*'", "ale universal/countless: a countless group is possible", "strong"),
    "link.to_min": ("tawa ijo la {S:linja} li lon e {V:kulupu}", "to_cardinality.min", "tawa ijo la: for a target entity (pu tawa: to, toward)", "moderate"),
    "link.to_max": ("tawa ijo la {S:linja} li ken e {V:kulupu}", "to_cardinality.max (integer)", "as from_max", "moderate"),
    "link.to_star": ("tawa ijo la {S:linja} li ken e kulupu ale", "to_cardinality.max = '*'", "as from_star", "strong"),
    "link.directed_t": ("{S:linja} li tawa", "directed: true", "tawa move/direct/orient", "strong"),
    "link.directed_f": ("{S:linja} li tawa ala", "directed: false", "has no direction", "strong"),
    # ---- interface ----
    "iface.required_link": ("{S:selo} li wile e {R:link}", "interfaces[].required_links[] element", "wile need/target", "strong"),
    "iface.capability": ("{S:selo} li ken e {V:ken}", "interfaces[].capabilities[] element", "ken enablement/permission-capability", "strong"),
}

T.update({
    # ---- function ----
    "fn.purity": ("{S:ilo} li ante ala e ijo", "purity = NO_COMMITTED_BUSINESS_SIDE_EFFECT", "ante transform, ala negate: F transforms no entity", "strong"),
    "fn.input": ("{S:ilo,pali} li kute e {DECL:kute}", "inputs[] element (name atom; order = line order)", "kute receive: F/A receives parameter", "strong"),
    "fn.output": ("{S:ilo} li pana e {TYPE}", "functions[].output", "pana emit/give: F emits a T", "strong"),
    "fn.reads": ("{S:ilo} li lukin e {R:readable}", "functions[].reads[] element", "lukin inspect/observe", "strong"),
    "fn.impl": ("{S:ilo} li tan {V:ilo}", "functions[].implementation_ref", "tan source: F derives from this implementation (ilo tool/means)", "strong"),
    "fn.det_deterministic": ("{S:ilo} li pana sama", "determinism = deterministic", "emits the same (sama)", "strong"),
    "fn.det_nondeterministic": ("{S:ilo} li pana ante", "determinism = nondeterministic", "emits differently (ante)", "strong"),
    "fn.det_external": ("{S:ilo} li pana tan sona weka", "determinism = external-model", "emits from a distant model (sona model, weka away)", "moderate"),
    # ---- action ----
    "act.authority": ("{S:pali} li ken tan {R:authority}", "actions[].authority_refs[] element ('auth:' + id)", "ken enablement; tan source: A is enabled from rule K", "strong"),
    "act.policy": ("{S:pali} li lawa tan {R:policy}", "actions[].policy_refs[] element ('policy:' + id)", "lawa govern; tan source: A is governed from policy", "strong"),
    "act.precondition": ("{V:lon} la {S:pali} li ken", "actions[].preconditions[] element", "la condition: given this state (lon), A is possible", "strong"),
    "act.effect": ("{S:pali} li pali e {DECL0:ante}", "actions[].effects[] element (order = line order)", "pali execute: A executes change (ante)", "strong"),
    "act.idem_required": ("{S:pali} li wile e sike sama", "idempotency = required", "wile must; sike iterate; sama same: repeating must stay the same", "moderate"),
    "act.idem_na": ("{S:pali} li wile ala e sike sama", "idempotency = not_applicable", "repeating-the-same is not required", "moderate"),
    "act.outcome": ("{S:pali} li kama e {V:lon}", "actions[].outcome_predicate", "kama become/arrive: A brings about this state", "moderate"),
    "act.compensation": ("{S:pali} li nasin weka e {R:action}", "actions[].compensation_action = action id", "nasin route/procedure + weka remove: A's removal procedure is A2", "moderate"),
    "act.compensation_null": ("{S:pali} li nasin weka e ala", "actions[].compensation_action = null", "removal procedure: none", "moderate"),
    # ---- effect ----
    "eff.create": ("{S:ante} li pali e {R:object}", "operation create", "pali make", "strong"),
    "eff.update": ("{S:ante} li ante e {R:object}", "operation update", "ante transform/change", "strong"),
    "eff.delete": ("{S:ante} li weka e {R:object}", "operation delete", "weka remove", "strong"),
    "eff.link": ("{S:ante} li linja e {R:link}", "operation link", "linja link", "strong"),
    "eff.unlink": ("{S:ante} li weka linja e {R:link}", "operation unlink", "remove-link", "strong"),
    "eff.git_change": ("{S:ante} li sitelen e {R:object_or_link}", "operation git_change", "sitelen inscribe/encode: the change is inscribed (committed)", "weak"),
    "eff.external_call": ("{S:ante} li toki e {V:ilo}", "operation external_call (target = opaque system atom)", "toki communicate/exchange with this tool/system (ilo)", "moderate"),
    "eff.field": ("{S:ante} li ma e {R:prop}", "effects[].fields[] element (local target)", "ma locate/scope: the change is scoped to P", "moderate"),
    "eff.field_opaque": ("{S:ante} li ma e {V:sona}", "effects[].fields[] element (external/imported target: opaque atom)", "scoped to this attribute (sona)", "moderate"),
    "eff.fields_empty": ("{S:ante} li ma e ala", "effects[].fields: []", "scoped to nothing", "moderate"),
    # ---- policy ----
    "pol.allow": ("{S:lawa} li ken e pali", "decision = allow", "ken permit; pali the execution", "strong"),
    "pol.deny": ("{S:lawa} li ken ala e pali", "decision = deny", "does not permit the execution", "strong"),
    "pol.require_approval": ("{S:lawa} li wile e pona tan jan", "decision = require_approval", "wile need; pona good/approval; tan jan from an agent", "moderate"),
    "pol.classify": ("{S:lawa} li kulupu e ijo", "decision = classify", "kulupu group: puts the entity in a group", "moderate"),
    "pol.expression": ("{S:lawa} li tan {V:nasin}", "policies[].expression_ref", "tan source: derives from this rule (nasin method)", "strong"),
    # ---- authority rule ----
    "auth.principal": ("{S:ken} li ma e {V:jan}", "principal_selector", "ma locate/scope: selects this agent (jan)", "strong"),
    "auth.capability": ("{S:ken} li open e {V:ken}", "capability", "open expose possibility: exposes this capability (ken)", "strong"),
    "auth.resource": ("{S:ken} li ma e {V:ijo}", "resource_selector", "selects this entity (ijo)", "strong"),
    "auth.allow": ("{S:ken} li ken", "effect = allow", "ken: is allowed", "strong"),
    "auth.deny": ("{S:ken} li ken ala", "effect = deny", "ken ala: is not allowed", "strong"),
    "auth.deleg_t": ("{S:ken} li pana e ken", "delegation_allowed = true", "pana give: passes the permission on", "moderate"),
    "auth.deleg_f": ("{S:ken} li pana ala e ken", "delegation_allowed = false", "does not pass the permission on", "moderate"),
    # ---- observation type ----
    "obs.subject": ("{S:lukin} li lukin e {R:object}", "observation_types[].subject_type", "lukin observe: observes O", "strong"),
    "obs.source": ("{S:lukin} li kama tan {V:kute}", "observation_types[].source_binding", "canon sentence 'sona ni li kama tan kute': arrives from this received signal", "strong"),
    "obs.truth": ("{S:lukin} li tan lukin", "truth_status = observed", "tan source: derives from observation (lukin)", "strong"),
    # ---- constraint ----
    "con.scope": ("{V:ma} la {S:awen} li lon", "constraints[].scope (opaque atom, Gate-0 ruling 1)", "ma scope: within this scope C holds", "strong"),
    "con.expression": ("{S:awen} li tan {V:nasin}", "constraints[].expression_ref", "as pol.expression", "strong"),
    "con.hard": ("{S:awen} li ken ala e weka", "severity = hard", "ken ala e weka: may not be ignored (pu weka: ignored)", "moderate"),
    "con.soft": ("{S:awen} li ken e weka", "severity = soft", "may be ignored", "moderate"),
})

# Type phrases (not lines): primitive -> phrase, with gloss justification and strength.
TYPE_GLOSS = {
    "string": ("sitelen toki", "writing that communicates (text)", "strong"),
    "integer": ("kulupu ijo", "an aggregate (kulupu) of discrete entities (ijo): a count", "moderate"),
    "number": ("kulupu pilin", "an aggregate of a sensed/evaluated magnitude (pilin): a measure", "weak"),
    "boolean": ("lon anu ala", "present/true or absent/not (pu lon: real, true; ala: no, not)", "strong"),
    "datetime": ("tenpo", "a moment in time", "strong"),
    "date": ("tenpo sike", "time of the cycle (pu sike: one year): a calendar date", "weak"),
    "json": ("sitelen kulupu", "an aggregate representation: a structured document", "moderate"),
    "bytes": ("sitelen sijelo", "an embodied (physical) encoding", "moderate"),
    "{ref: X}": ("<address of X>", "predicate nominal: the slot is an X (object type / interface / external name)", "strong"),
}
