"""The frozen OpenPona v2 phrase table (H15 v2): every line the encoding renders or accepts instantiates one row.

Placeholders (anything else is a literal token). Every `ni` binds the next record atom, left to right:
  {PKG}      `kulupu ni`  the package itself; atom = package_id
  {IMP}      `kulupu ni`  an imported package; atom = the import string
  {D:h,..}   `h ni`       a resource declared by this line; atom = its id; the head h states its kind
  {S:h,..}   `h ni`       the resource this line is about; atom = its id (coreference = equal atoms)
  {C:h,..}   `h ni`       the owner named as context (`... la`); atom = owner id (canon/05: narrowest context)
  {P}        `sona ni`    a property of the context/subject owner; atom = property name
  {K}        `kute ni`    a parameter of the context/subject function or action; atom = parameter name
  {V:w}      `w ni`       a value atom (opaque string or literal) of the kind w names
  {NI}       `ni`         a metadata scalar literal
  {R:role}   a reference; vocab.ROLES lists the alternatives (`h ni`, `weka ni pi kulupu ni`, `sona ni pi h ni`)
  {TYPE}     a primitive phrase | `ijo ni` / `selo ni` / `weka ni pi kulupu ni` (a ref type) | bare `nasin`
             (a constructed type, stated by the next line)
Bare heads (no `ni`) are the thing under discussion (block continuation): `kulupu` = this package,
`sitelen` = the metadata value currently open, `ante` = the change stated by the preceding effect line,
`nasin` = the constructed type announced by the preceding line.
Each row: id -> (pattern, IR meaning, canon gloss justification, strength).
"""
from __future__ import annotations

_OWN = "ijo,linja,selo,lukin"
_RES = "ijo,linja,selo,ilo,pali,lawa,ken,lukin,awen"

T = {
    # ---- package ----
    "pkg.decl": ("{PKG} li lon", "package_id", "kulupu group/collective = the package; lon presence: 'this package is present'", "strong"),
    "pkg.version": ("{V:tenpo} la kulupu li lon", "version", "tenpo time-state: 'at this time-state the package is present'; the canon 'version' gloss belongs to the particle anu, which cannot carry content", "moderate"),
    "pkg.domain": ("{V:ma} la kulupu li lon", "domain_id", "ma locate/scope: 'in this scope the package is present'", "strong"),
    "pkg.import": ("kulupu li kute e {IMP}", "imports[] element", "kute receive/accept: the package receives this (other) package", "strong"),
    "pkg.imports_empty": ("kulupu li kute e ala", "imports: []", "ala absence: receives nothing", "strong"),
    "pkg.meta": ("kulupu li sona e {V:sitelen}", "metadata member (key atom); opens its value", "sona know/model: what the package knows about itself; sitelen represent: a represented value", "moderate"),
    "pkg.meta_empty": ("kulupu li sona e ala", "metadata: {}", "knows nothing", "moderate"),
    "meta.entry": ("sitelen li sona e {V:sitelen}", "JSON object member (key atom); opens its value", "as pkg.meta, one level down: the open value knows this value", "moderate"),
    "meta.obj_empty": ("sitelen li sona e ala", "JSON {}", "the open value knows nothing", "moderate"),
    "meta.item": ("sitelen li linja e sitelen", "JSON array element (order = line order); opens it", "linja link/chain: the open value chains a value", "strong"),
    "meta.list_empty": ("sitelen li linja e ala", "JSON []", "chains nothing", "strong"),
    "meta.close": ("sitelen li pini", "end of the open JSON object/array", "pini close/complete: the open value is complete", "strong"),
    "meta.true": ("sitelen li sama e lon", "JSON true", "sama match; lon presence/reality (pu: true)", "strong"),
    "meta.false": ("sitelen li sama e lon ala", "JSON false", "lon ala: not true", "strong"),
    "meta.null": ("sitelen li sama e ala", "JSON null", "ala absence: matches nothing", "strong"),
    "meta.int": ("sitelen li kulupu ijo li sama e {NI}", "JSON integer (atom = decimal literal)", "integer type phrase + matches the bound literal", "moderate"),
    "meta.float": ("sitelen li kulupu pilin li sama e {NI}", "JSON non-integer number (atom = JSON literal)", "number type phrase + bound literal", "weak"),
    "meta.str": ("sitelen li sitelen toki li sama e {NI}", "JSON string (atom)", "string type phrase + bound literal", "strong"),
    # ---- every resource ----
    "res.decl": ("{D:" + _RES + "} li lon", "a resource; kind = head, id = atom", "lon presence: 'this X is present'; heads: ijo entity, linja link, selo interface, ilo tool, pali execute, lawa govern, ken permission-capability, lukin observe, awen persist/hold", "strong"),
    "res.version": ("{V:tenpo} la {S:pali,lawa} li lon", "actions[].version / policies[].version", "as pkg.version", "moderate"),
    # ---- object type ----
    "obj.description": ("{S:ijo} li sitelen e {V:toki}", "object_types[].description", "sitelen represent: X is represented by this text (toki communicate)", "strong"),
    "obj.implements": ("{S:ijo} li sama e {R:iface}", "object_types[].implements[] element", "sama match/align: X matches interface I", "strong"),
    "obj.pk": ("{S:ijo} li ni tan {P}", "object_types[].primary_key", "ni bind/fix referent; tan source: X's referent is fixed from its attribute P", "strong"),
    "prop.decl": ("{S:" + _OWN + "} li sona e {P}", "properties[] / required_properties[] element (order = line order)", "sona know/model: X models attribute P", "moderate"),
    "link.props_empty": ("{S:linja} li sona e ala", "link_types[].properties: []", "models nothing", "moderate"),
    # ---- property facts (owner named as context) ----
    "prop.type": ("{C:" + _OWN + "} la {P} li {TYPE}", "property type", "in X's context, P is (a) T (predicate nominal)", "strong"),
    "prop.required_t": ("{C:" + _OWN + "} la {P} li wile", "property required: true", "wile need (pu: must)", "strong"),
    "prop.required_f": ("{C:" + _OWN + "} la {P} li wile ala", "property required: false", "not needed", "strong"),
    "prop.immutable_t": ("{C:" + _OWN + "} la {P} li awen", "immutable: true", "awen retain/persist (pu: kept)", "strong"),
    "prop.immutable_f": ("{C:" + _OWN + "} la {P} li awen ala", "immutable: false", "does not persist unchanged", "strong"),
    "prop.description": ("{C:" + _OWN + "} la {P} li sitelen e {V:toki}", "property description", "as obj.description", "strong"),
    "prop.constraint": ("{C:" + _OWN + "} la {V:nasin} li lawa e {P}", "property constraints[] element", "nasin method/rule; lawa govern: this rule governs P", "strong"),
    "prop.constraints_empty": ("{C:" + _OWN + "} la ala li lawa e {P}", "property constraints: []", "nothing governs P", "strong"),
    # ---- parameters ----
    "param.decl": ("{S:ilo,pali} li kute e {K}", "inputs[] element (order = line order)", "kute receive: F/A receives this parameter", "strong"),
    "param.type": ("{C:ilo,pali} la {K} li {TYPE}", "parameter type", "in F/A's context, the parameter is (a) T", "strong"),
    "param.required_t": ("{C:ilo,pali} la {K} li wile", "parameter required: true", "wile need", "strong"),
    "param.required_f": ("{C:ilo,pali} la {K} li wile ala", "parameter required: false", "not needed", "strong"),
    # ---- constructed types (pre-order: each bare `nasin` is stated by the next line) ----
    "type.list": ("nasin li linja e {TYPE}", "{list: T}", "linja chain: the announced way is a chain of T", "strong"),
    "type.optional": ("nasin li {TYPE} anu ala", "{optional: T}", "anu alternative + ala absence: T or nothing", "strong"),
}

T.update({
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
    # ---- function ----
    "fn.purity": ("{S:ilo} li ante ala e ijo", "purity = NO_COMMITTED_BUSINESS_SIDE_EFFECT", "ante transform, ala negate: F transforms no entity", "strong"),
    "fn.output": ("{S:ilo} li pana e {TYPE}", "functions[].output", "pana emit/give: F emits a T", "strong"),
    "fn.reads": ("{S:ilo} li lukin e {R:readable}", "functions[].reads[] element", "lukin inspect/observe", "strong"),
    "fn.impl": ("{S:ilo} li tan {V:ilo}", "functions[].implementation_ref", "tan source: F derives from this implementation (ilo tool/means)", "strong"),
    "fn.det_deterministic": ("{S:ilo} li pana sama", "determinism = deterministic", "emits the same (sama)", "strong"),
    "fn.det_nondeterministic": ("{S:ilo} li pana ante", "determinism = nondeterministic", "emits differently (ante)", "strong"),
    "fn.det_external": ("{S:ilo} li pana tan sona weka", "determinism = external-model", "emits from a distant model (sona model, weka away)", "moderate"),
    # ---- action ----
    "act.authority": ("{S:pali} li ken tan {R:authority}", "actions[].authority_refs[] element ('auth:' + id)", "ken enablement; tan source: A is enabled from rule K", "strong"),
    "act.policy": ("{S:pali} li lawa tan {R:policy}", "actions[].policy_refs[] element ('policy:' + id)", "lawa govern; tan source: A is governed from policy P", "strong"),
    "act.precondition": ("{V:lon} la {S:pali} li ken", "actions[].preconditions[] element", "la condition: given this state (lon), A is possible", "strong"),
    "act.idem_required": ("{S:pali} li wile e sike sama", "idempotency = required", "wile must; sike iterate; sama same: repeating must stay the same", "moderate"),
    "act.idem_na": ("{S:pali} li wile ala e sike sama", "idempotency = not_applicable", "repeating-the-same is not required", "moderate"),
    "act.outcome": ("{S:pali} li kama e {V:lon}", "actions[].outcome_predicate", "kama become/arrive: A brings about this state", "moderate"),
    "act.compensation": ("{S:pali} li nasin weka e {R:action}", "actions[].compensation_action = action id", "nasin route/procedure + weka remove: A's removal procedure is A2", "moderate"),
    "act.compensation_null": ("{S:pali} li nasin weka e ala", "actions[].compensation_action = null", "removal procedure: none", "moderate"),
    # ---- effects: one line per effect (order = line order); its fields follow as `ante` lines ----
    "eff.create": ("{S:pali} li pali e {R:object}", "effects[] element, operation create", "pali make: A makes this entity", "strong"),
    "eff.update": ("{S:pali} li ante e {R:object}", "effects[] element, operation update", "ante transform/change: A changes this entity", "strong"),
    "eff.delete": ("{S:pali} li weka e {R:object}", "effects[] element, operation delete", "weka remove: A removes this entity", "strong"),
    "eff.link": ("{S:pali} li linja e {R:link}", "effects[] element, operation link", "linja link: A links by this link type", "strong"),
    "eff.unlink": ("{S:pali} li weka linja e {R:link}", "effects[] element, operation unlink", "weka linja remove-link", "strong"),
    "eff.git_change": ("{S:pali} li sitelen e {R:object_or_link}", "effects[] element, operation git_change", "sitelen inscribe/encode: A inscribes (commits) this thing", "weak"),
    "eff.external_call": ("{S:pali} li toki e {V:ilo}", "effects[] element, operation external_call (target = opaque system atom)", "toki communicate with this tool/system (ilo)", "moderate"),
    "eff.field": ("ante li ma e {V:sona}", "fields[] element of the preceding effect (a property of a local target, opaque otherwise)", "ma locate/scope: the change (ante) is scoped to this attribute (sona)", "moderate"),
    "eff.fields_empty": ("ante li ma e ala", "fields: [] of the preceding effect", "the change is scoped to nothing", "moderate"),
    # ---- policy ----
    "pol.allow": ("{S:lawa} li ken e pali", "decision = allow", "ken permit; pali the execution", "strong"),
    "pol.deny": ("{S:lawa} li ken ala e pali", "decision = deny", "does not permit the execution", "strong"),
    "pol.require_approval": ("{S:lawa} li wile e pona tan jan", "decision = require_approval", "wile need; pona good/approval; tan jan from an agent", "moderate"),
    "pol.classify": ("{S:lawa} li kulupu e ijo", "decision = classify", "kulupu group: puts the entity in a group", "moderate"),
    "pol.expression": ("{S:lawa} li tan {V:nasin}", "policies[].expression_ref", "tan source: derives from this rule (nasin method)", "strong"),
    # ---- authority rule ----
    "auth.principal": ("{S:ken} li ma e {V:jan}", "principal_selector", "ma locate/scope: selects this agent (jan)", "strong"),
    "auth.capability": ("{S:ken} li open e {V:ken}", "capability", "open expose: exposes this capability (ken)", "strong"),
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
    "con.scope": ("{V:ma} la {S:awen} li lon", "constraints[].scope (opaque atom)", "ma scope: within this scope C holds", "strong"),
    "con.expression": ("{S:awen} li tan {V:nasin}", "constraints[].expression_ref", "as pol.expression", "strong"),
    "con.hard": ("{S:awen} li ken ala e weka", "severity = hard", "ken ala e weka: may not be ignored (pu weka: ignored)", "moderate"),
    "con.soft": ("{S:awen} li ken e weka", "severity = soft", "may be ignored", "moderate"),
})

# Type phrases (fillers of {TYPE}): IR type -> (phrase, gloss justification, strength).
TYPE_GLOSS = {
    "string": ("sitelen toki", "writing that communicates (text)", "strong"),
    "integer": ("kulupu ijo", "an aggregate (kulupu) of discrete entities (ijo): a count", "moderate"),
    "number": ("kulupu pilin", "an aggregate of a sensed/evaluated magnitude (pilin): a measure", "weak"),
    "boolean": ("lon anu ala", "present/true or absent/not (pu lon: real, true; ala: no, not)", "strong"),
    "datetime": ("tenpo", "a moment in time", "strong"),
    "date": ("tenpo sike", "time of the cycle (pu sike: one year): a calendar date", "weak"),
    "json": ("sitelen kulupu", "an aggregate representation: a structured document", "moderate"),
    "bytes": ("sitelen sijelo", "an embodied (physical) encoding", "moderate"),
    "{ref: X}": ("ijo ni | selo ni | weka ni pi kulupu ni", "predicate nominal: the slot is this entity / interface / name from that package", "strong"),
    "{list: T} / {optional: T}": ("nasin", "nasin way/method: a constructed way of shaping a value, stated by the next line (type.list / type.optional)", "moderate"),
}
