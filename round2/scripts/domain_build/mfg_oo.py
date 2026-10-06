"""Manufacturing: governance (oo:) object types, from contracts/ontology/v3/oo-core.ttl, oo-observation.ttl and shapes."""
from __future__ import annotations

from .common import DT, I, N, BO, S, enum, p
from .mfg_objects import iri

OOC = "contracts/ontology/v3/oo-core.ttl"
OOO = "contracts/ontology/v3/oo-observation.ttl"
SHD = "contracts/shapes/v3/decision-shape.ttl"
SHA = "contracts/shapes/v3/action-execution-shape.ttl"
SHE = "contracts/shapes/v3/evidence-snapshot-shape.ttl"
STATUSES = ["DRAFT", "PROPOSED", "INSUFFICIENT_EVIDENCE", "DENIED_AUTHORIZATION", "DENIED_POLICY", "INVALID_CONFORMANCE",
            "REQUIRES_APPROVAL", "APPROVED", "EXECUTING", "EXECUTION_FAILED", "OUTCOME_UNKNOWN", "AWAITING_OBSERVATION",
            "DIVERGED", "OBSERVED_SUCCESS", "ACTION_VERSION_INVALIDATED", "GATE_UNAVAILABLE"]
IRI = "`iri`: RDF identity (no declared id property in the sources)"
PINNED = "pinned: reference_model/state.py PINNED_DECISION_FIELDS and oo-core.ttl 'Immutable once APPROVED'"


def add_oo_objects(b):
    pin = lambda n, t=S, r=True: p(n, t, r, True)  # noqa: E731 - hash-covered, immutable once approved
    b.obj("Decision", "decisionId", [
        p("decisionId", S, True, True), pin("decisionType"), pin("ontologyVersion"), pin("shapeSetVersion"),
        pin("authorizationModelVersion"), pin("policyBundleVersion"), pin("actionType"), pin("actionVersion", I),
        p("createdAt", DT, True), p("identityMappingVersion"), p("projectionDefinitionVersion"),
        p("reconciliationPredicateVersion"), p("openfgaAuthorizationModelId"),
        p("unavailableGate", S, False, False, [enum("authorization", "policy")]),
        p("status", S, True, False, [enum(*STATUSES)]), pin("parametersJson", S, False), p("decisionContentHash"),
        p("approvedAt", DT), p("approvalDecisionHash"), p("approvalScope"), p("actionPinnedSha256"),
        p("actionSha256AtExecute"), p("actionVersionInvalidatedAt", DT)],
        src=f"{OOC} (oo:Decision and its properties); {SHD} (DecisionShape minCount/maxCount/sh:in)",
        note=f"required = DecisionShape sh:minCount 1; immutable = {PINNED}; status vocabulary = DecisionShape sh:in (16 concepts)")
    b.obj("EvidenceSnapshot", "iri", [
        iri(), p("snapshotObservedAt", DT, True), p("snapshotContentHash", S, True), p("sourcePositionsJson"),
        p("requiredFactsJson"), p("excludedFactsJson"), p("projectionRowHashesJson")], ["ProvEntity"],
        src=f"{OOC} (oo:EvidenceSnapshot); {SHE} (EvidenceSnapshotShape)", note=IRI + "; *Json properties are xsd:string holding JSON text, kept as string")
    b.obj("DecisionActivity", "iri", [iri()], ["ProvActivity"], src=f"{OOC} (oo:DecisionActivity)", note=IRI + "; no properties declared")
    b.obj("ActionExecution", "actionExecutionId", [
        p("actionExecutionId", S, True, True, d="same value is the idempotency key sent to the external system"),
        p("quantity", I, False, False, ["min_inclusive:1"]), p("externalSystem", S, False, False, [enum("WMS", "ERP", "MES")]),
        p("externalOperation"), p("commandStatus"), p("commandReceiptJson"), p("startedAt", DT), p("completedAt", DT),
        p("temporalWorkflowId")], ["ProvActivity"],
        src=f"{OOC} (oo:ActionExecution); {SHA} (ActionExecutionShape: quantity >= 1)")
    b.obj("Outcome", "outcomeId", [
        p("outcomeId", S, True, True),
        p("reconciliationState", S, True, False, [enum("NOT_STARTED", "COMMAND_SENT", "COMMAND_ACCEPTED", "AWAITING_OBSERVATION",
                                                       "CONVERGED", "DIVERGED", "OUTCOME_UNKNOWN", "COMPENSATING", "COMPENSATED", "FAILED")]),
        p("expectedEffectJson", S, True), p("observedEffectJson", S, True), p("observedAtOutcome", DT),
        p("compensationStatus", S, False, False, [enum("NONE", "NOT_APPLICABLE", "COMPENSATING", "COMPENSATED", "COMPENSATION_FAILED")]),
        p("compensatingActionExecutionId"), p("sourceEvidenceLsn")], ["ProvEntity"],
        src=f"{OOC} (oo:Outcome); {SHA} (OutcomeShape)")
    for cls, desc in (("HumanActor", "human principal"), ("SoftwareAgent", "software agent acting for a human")):
        b.obj(cls, "actorId", [p("actorId", S, True, True, d="e.g. planner-1, agent-1"),
                               p("actorRole", S, False, False, [enum("planner", "junior_planner", "supervisor", "agent")])],
              ["ProvAgent"], src=f"{OOC} (oo:{cls} subClassOf prov:" + ("Agent" if cls == "HumanActor" else "SoftwareAgent") + "; oo:actorId, oo:actorRole)",
              note="oo:actorId / oo:actorRole declare no rdfs:domain; attached to both agent classes (choice, see decisions)")
    b.obj("AuthorizationCheck", "iri", [
        iri(), p("checkRelation"), p("checkObject"), p("checkOutcome", S, False, False, [enum("ALLOWED", "DENIED", "UNAVAILABLE")]),
        p("checkedAt", DT), p("checkAuthorizationModelId")], ["ProvEntity"], src=f"{OOC} (oo:AuthorizationCheck)", note=IRI)
    b.obj("PolicyEvaluation", "iri", [
        iri(), p("policyOutcome", S, False, False, [enum("allow", "deny", "require_approval", "UNAVAILABLE")]),
        p("policyReasonsJson"), p("policyObligationsJson"), p("policyInputHash"), p("policyInputJson")], ["ProvEntity"],
        src=f"{OOC} (oo:PolicyEvaluation)", note=IRI)
    b.obj("ConformanceCheck", "iri", [
        iri(), p("conformanceOutcome", S, False, False, [enum("CONFORMS", "VIOLATED")]), p("conformanceViolationsJson")],
        ["ProvEntity"], src=f"{OOC} (oo:ConformanceCheck)", note=IRI)


def add_observation_objects(b):
    b.obj("Observation", "iri", [
        iri(), p("sourceSystem", S, False, False, [enum("erp", "mes", "wms")]), p("sourceTable"), p("sourcePk"),
        p("sourceLsn", d="Postgres WAL LSN; ordering authority, never wall clock"), p("sourceVersion", I),
        p("cdcOperation", S, False, False, [enum("c", "u", "d", "r")]), p("observedAt", DT), p("applied", BO)],
        ["ProvActivity"], src=f"{OOO} (oo:Observation)", note=IRI)
    b.obj("SourcePosition", "iri", [iri(), p("lastLsn"), p("lastVersion", I), p("lastObservedAt", DT)],
          src=f"{OOO} (oo:SourcePosition)", note=IRI + "; one per (source, table, primary key)")
    b.obj("IdentityResolutionActivity", "iri", [iri()], ["ProvActivity"], src=f"{OOO} (oo:IdentityResolutionActivity)", note=IRI)
    b.obj("IdentityMapping", "iri", [
        iri(), p("mappingRuleId"), p("mappingRuleVersion"), p("sourceLocalId"), p("authority"),
        p("confidence", N, d="xsd:decimal"), p("createdAtMapping", DT)], ["ProvEntity"], src=f"{OOO} (oo:IdentityMapping)", note=IRI)
    b.obj("QuarantinedIdentity", "iri", [iri(), p("quarantineReason")], ["ProvEntity"], src=f"{OOO} (oo:QuarantinedIdentity)",
          note=IRI + "; F09: a source-local id no mapping rule could resolve unambiguously")


def add_oo_interfaces(b):
    note = "rdfs:subClassOf prov:%s in oo-core.ttl / oo-observation.ttl; the PROV class declares no properties, so the interface is a pure marker"
    b.iface("ProvEntity", src=f"{OOC}, {OOO} (subClassOf prov:Entity)", note=note % "Entity")
    b.iface("ProvActivity", src=f"{OOC}, {OOO} (subClassOf prov:Activity)", note=note % "Activity")
    b.iface("ProvAgent", src=f"{OOC} (subClassOf prov:Agent / prov:SoftwareAgent; oo:actor range prov:Agent)", note=note % "Agent")
