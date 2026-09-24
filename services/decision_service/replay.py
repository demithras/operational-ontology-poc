"""Historical replay + counterfactual reevaluation — docs/experiment/spec/07_versioning_and_replay.md.

`replay_decision(decision_id, ...)` is the CORE gate: docs/experiment/spec/07's
"Core rule" ("A historical decision is evaluated under the contract that
existed when it was made") — never re-derives evidence live, never re-runs
gates under CURRENT rules. Every input it uses is either (a) already frozen
on the Decision at propose() time (evidence facts, policy input_json,
authz relation/object), or (b) the archived, immutable contracts/<kind>/<pinned
version>/ artifact on disk.

`reevaluate_under_current(decision_id, ...)` is the SEPARATE counterfactual
path (spec: "This must never overwrite or be confused with historical
replay") — takes the frozen evidence FACTS (not the frozen policy input,
since the whole point is asking what TODAY's rules would say) and re-runs
them through the CURRENTLY deployed action/policy/evidence-shape logic. It
never writes anything back to RDF4J/Postgres.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from services.common.rdf4j_client import RDF4JClient
from services.common.rdf_graphs import decision_graph_iri
from services.common.sparql_escape import escape_sparql_literal
from services.decision_service import authz, hashing, store
from services.decision_service.action_types import get_action_type

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_ROOT = REPO_ROOT / "contracts"
QUERIES_DIR = CONTRACTS_ROOT / "queries" / "v1"
MODEL_IDS_PATH = CONTRACTS_ROOT / "manifests" / "openfga_model_ids.json"


class DecisionNotFound(ValueError):
    pass


class ReplayIntegrityError(RuntimeError):
    """F29 ('old policy deleted -> replay -> replay fails loudly'): an
    archived contract artifact this decision pinned no longer matches (or
    no longer exists) on disk. Raised, never swallowed — replay must FAIL
    LOUDLY, not silently substitute the current artifact."""


@dataclass
class ReplayResult:
    decision_id: str
    original: dict[str, Any]
    replay: dict[str, Any]
    # PASS | FAIL | PARTIAL_RECORDED_ONLY (Phase 7b requirement A: a
    # decision whose evidence/action/policy all reconstruct correctly but
    # whose AUTHORIZATION could only be checked via the honest
    # "recorded_only" fallback (docs/adr/0004) must never report a plain
    # PASS — that would silently certify authorization reproducibility that
    # never actually happened. FAIL always wins over PARTIAL_RECORDED_ONLY:
    # a genuine mismatch is worse than "we couldn't prove it either way".
    status: str
    failure_reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "original": self.original,
            "replay": self.replay,
            "status": self.status,
            **({"failure_reasons": self.failure_reasons} if self.failure_reasons else {}),
        }


def _parse_version_tag(tag: str) -> tuple[str, str]:
    """"v2@sha256:abc..." -> ("v2", "abc...")."""
    version, _, sha = tag.partition("@sha256:")
    return version, sha


def _sha256_of_dir(directory: Path, pattern: str = "*") -> str:
    import hashlib

    h = hashlib.sha256()
    if not directory.exists():
        return h.hexdigest()
    for path in sorted(directory.glob(pattern)):
        h.update(path.read_bytes())
    return h.hexdigest()


def _verify_archive(kind: str, version_dir: str, expected_sha: str, pattern: str) -> None:
    directory = CONTRACTS_ROOT / kind / version_dir
    if not directory.is_dir():
        raise ReplayIntegrityError(
            f"F29: contracts/{kind}/{version_dir}/ no longer exists on disk (pinned sha256={expected_sha})"
        )
    actual = _sha256_of_dir(directory, pattern)
    if actual != expected_sha:
        raise ReplayIntegrityError(
            f"F29: contracts/{kind}/{version_dir}/ content sha256={actual} does not match the pinned sha256={expected_sha} "
            f"— the archived artifact this decision depends on was modified or replaced after the decision was made"
        )


def _fetch_rdf_fields(rdf4j_client: RDF4JClient, decision_id: str) -> dict[str, str]:
    template = (QUERIES_DIR / "q9_replay_authz_fields.rq").read_text()
    sparql = template.replace("%%DECISION_ID%%", escape_sparql_literal(decision_id))
    # Phase 7b fix (see the query's own header comment): scope the
    # oo:actor lookup to this decision's own named graph — that shared
    # HumanActor node's oo:actorId triple is re-asserted in every OTHER
    # decision by the same actor, and an unscoped pattern fans out into
    # one row per such decision (found empirically: 2656 rows for one
    # decision_id before this fix).
    sparql = sparql.replace("%%GRAPH_IRI%%", decision_graph_iri(decision_id))
    rows = rdf4j_client.select(sparql)
    if not rows:
        raise DecisionNotFound(f"decision {decision_id!r} not found in RDF4J (or has no oo:status)")
    return rows[0]


def _eval_via_live_opa(opa_base_url: str, package_path: str, input_json: dict) -> str | None:
    """The LIVE running OPA server ALREADY serves every published policy
    version's package simultaneously and forever (docker-compose.yml mounts
    the WHOLE contracts/policies/ tree, not just the current one — see that
    file's own comment) — evaluating an ARCHIVED package through it is
    exactly as historically faithful as a fresh `opa eval` against the
    on-disk bundle, and works identically whether replay runs host-side
    (scripts/replay_cli.py) or inside the decision_service CONTAINER
    (POST /replay/{id}), which has neither a docker socket nor the docker
    CLI. Returns None (never raises) if OPA is unreachable, so the caller
    can fall back to `opa eval` via docker."""
    package_url_path = package_path.replace(".", "/")
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.post(f"{opa_base_url}/v1/data/{package_url_path}/result", json={"input": input_json})
        if r.status_code != 200:
            return None
        body = r.json().get("result")
        if not body or "decision" not in body:
            return None
        return body["decision"]
    except httpx.HTTPError:
        return None


def _eval_via_docker(policies_dir: Path, package_path: str, input_json: dict) -> str:
    """`opa eval` via docker on the archived bundle (docs/experiment/spec/07
    item 1's own suggested mechanism) — the fallback when the live OPA
    server isn't reachable (e.g. a fully offline host-side audit)."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(input_json, f)
        input_path = Path(f.name)
    try:
        result = subprocess.run(
            [
                "docker", "run", "--rm",
                "-v", f"{policies_dir}:/policies:ro",
                "-v", f"{input_path}:/input.json:ro",
                "openpolicyagent/opa:latest",
                "eval", "-d", "/policies", "-i", "/input.json", "--format", "json",
                f"data.{package_path}.result",
            ],
            capture_output=True, text=True, timeout=30,
        )
    finally:
        input_path.unlink(missing_ok=True)
    if result.returncode != 0:
        raise ReplayIntegrityError(f"opa eval against the archived bundle failed: {result.stderr[:500]}")
    body = json.loads(result.stdout)
    try:
        return body["result"][0]["expressions"][0]["value"]["decision"]
    except (KeyError, IndexError) as exc:
        raise ReplayIntegrityError(f"opa eval produced no result for data.{package_path}.result: {result.stdout[:500]}") from exc


def _eval_policy(opa_base_url: str | None, policies_dir: Path, package_path: str, input_json: dict) -> str:
    if opa_base_url:
        live_outcome = _eval_via_live_opa(opa_base_url, package_path, input_json)
        if live_outcome is not None:
            return live_outcome
    return _eval_via_docker(policies_dir, package_path, input_json)


def replay_decision(
    decision_id: str, conn, rdf4j_client: RDF4JClient, openfga_api_url: str, opa_base_url: str | None = None,
) -> ReplayResult:
    pg_row = store.get_decision(conn, decision_id)
    if pg_row is None:
        raise DecisionNotFound(f"decision {decision_id!r} not found")
    rdf_fields = _fetch_rdf_fields(rdf4j_client, decision_id)

    # Evidence reconstruction is RDF4J-authoritative, not Postgres: the
    # Postgres evidence_snapshot column (services/decision_service/store.py::insert_decision)
    # deliberately omits `projection_row_hashes` (an index convenience,
    # never claimed complete) — only RDF4J's EvidenceSnapshot resource
    # carries oo:requiredFactsJson/oo:sourcePositionsJson/
    # oo:projectionRowHashesJson, the THREE inputs
    # hashing.evidence_snapshot_content_hash actually hashed at propose()
    # time. Recomputing from Postgres's partial copy alone silently
    # produces a DIFFERENT hash (found empirically while building this —
    # every decision "failed" replay until this was fixed).
    facts_used = json.loads(rdf_fields["requiredFactsJson"]) if rdf_fields.get("requiredFactsJson") else {}
    source_positions = json.loads(rdf_fields["sourcePositionsJson"]) if rdf_fields.get("sourcePositionsJson") else []
    projection_row_hashes = json.loads(rdf_fields["projectionRowHashesJson"]) if rdf_fields.get("projectionRowHashesJson") else []
    recomputed_evidence_hash = hashing.evidence_snapshot_content_hash(facts_used, source_positions, projection_row_hashes)
    stored_evidence_hash = rdf_fields.get("snapshotContentHash")
    evidence_hash_match = stored_evidence_hash is not None and recomputed_evidence_hash == stored_evidence_hash

    parameters = pg_row["parameters"]
    recomputed_decision_hash = hashing.decision_content_hash(
        pg_row["actor_type"], pg_row["actor_id"], pg_row["principal_actor_id"], pg_row["evidence_snapshot_id"],
        pg_row["ontology_version"], pg_row["shape_set_version"], pg_row["authorization_model_version"],
        pg_row["policy_bundle_version"], pg_row["action_type"], pg_row["action_version"], parameters,
    )
    stored_decision_hash = pg_row["decision_content_hash"]
    if stored_decision_hash is None:
        # A decision that never reached REQUIRES_APPROVAL/APPROVED
        # (INSUFFICIENT_EVIDENCE/DENIED_AUTHORIZATION/DENIED_POLICY/
        # INVALID_CONFORMANCE — see services/decision_service/propose_flow.py's
        # `_finalize`) never had a decision_content_hash computed AT ALL,
        # by design (F01-F09: "0 external effects", nothing to pin an
        # approvable action tuple to). There is nothing to mismatch —
        # vacuously true, not a failure.
        action_input_match = True
    else:
        action_input_match = recomputed_decision_hash == stored_decision_hash
        # Cross-check: RDF4J (authoritative) must agree with the Postgres index.
        rdf_decision_hash = rdf_fields.get("decisionContentHash")
        if rdf_decision_hash and stored_decision_hash != rdf_decision_hash:
            action_input_match = False

    ontology_vdir, ontology_sha = _parse_version_tag(pg_row["ontology_version"])
    shape_vdir, shape_sha = _parse_version_tag(pg_row["shape_set_version"])
    policy_vdir, policy_sha = _parse_version_tag(pg_row["policy_bundle_version"])
    authz_vdir, authz_sha = _parse_version_tag(pg_row["authorization_model_version"])

    # F29: raises loudly if any archived artifact is gone/modified — never
    # caught here, propagates to the caller (HTTP 409/500, CLI non-zero).
    _verify_archive("ontology", ontology_vdir, ontology_sha, "*.ttl")
    _verify_archive("shapes", shape_vdir, shape_sha, "*.ttl")
    _verify_archive("policies", policy_vdir, policy_sha, "*")
    _verify_archive("authorization", authz_vdir, authz_sha, "model.fga")

    # --- Re-run the policy gate against the ARCHIVED bundle -------------
    policy_result = pg_row["policy_result"] or {}
    policy_input = policy_result.get("input_json")
    gate_result_match = True
    policy_replayed_outcome = None
    if policy_input is not None:
        action = get_action_type(pg_row["action_type"], pg_row["action_version_dir"] or "v1")
        # Dotted Rego package path (e.g. "factory.inventory.transfer") — NOT
        # the slash-separated form services/decision_service/policy.py uses
        # for OPA's REST API URL; `opa eval`'s query argument needs real
        # Rego syntax (`data.factory.inventory.transfer.result`), and
        # mixing the two forms is a silent rego_unsafe_var_error, found
        # empirically while building this.
        package_path = action.policy_package if action else None
        if package_path:
            policy_replayed_outcome = _eval_policy(
                opa_base_url, CONTRACTS_ROOT / "policies" / policy_vdir, package_path, policy_input,
            )
            if policy_replayed_outcome != policy_result.get("outcome"):
                gate_result_match = False

    # --- Re-run the authorization check ----------------------------------
    # Phase 7b (R4 ADR update): replay re-issues the IDENTICAL Check —
    # same relation/object/actor/HISTORICAL model id — WITH the decision's
    # own HISTORICAL tuple snapshot supplied as OpenFGA's `contextual_tuples`
    # (never the live store's current tuples), so a live re-Check proves
    # authorization against the state that actually existed at propose()
    # time, not whatever the store looks like now. Three possible modes:
    #   "not_applicable" — this decision never reached an authorization
    #     check at all (e.g. INSUFFICIENT_EVIDENCE short-circuited first) —
    #     nothing to replay, vacuously fine, same treatment as
    #     action_input_match above.
    #   "recorded_only"  — a check happened, but live re-verification could
    #     not run (model id doesn't resolve in this store, no tuple
    #     snapshot was ever captured — a pre-Phase-7b decision — or OpenFGA
    #     itself is unreachable). Honest ADR-0004 fallback: the recorded
    #     outcome is trusted, not re-proven.
    #   "live"            — the check was actually re-run and its outcome
    #     compared against what was recorded.
    authz_result = pg_row["authorization_result"] or {}
    authz_model_id = rdf_fields.get("checkAuthorizationModelId") or rdf_fields.get("openfgaAuthorizationModelId")
    tuples_snapshot_json = rdf_fields.get("checkTuplesSnapshotJson")
    tuples_snapshot = json.loads(tuples_snapshot_json) if tuples_snapshot_json else None
    authz_replayed_outcome = authz_result.get("outcome")
    if not authz_result.get("outcome"):
        authz_replay_mode = "not_applicable"
    else:
        authz_replay_mode = "recorded_only"
        if authz_model_id and rdf_fields.get("checkRelation") and rdf_fields.get("checkObject") and rdf_fields.get("actorId") and tuples_snapshot:
            live = authz.check(
                openfga_api_url, _resolve_store_id(openfga_api_url), rdf_fields["checkRelation"], rdf_fields["checkObject"],
                pg_row["actor_type"], rdf_fields["actorId"], authz_model_id,
                contextual_tuples=tuples_snapshot, capture_tuples_snapshot=False,
            )
            if live.outcome != authz.UNAVAILABLE:
                authz_replay_mode = "live"
                authz_replayed_outcome = live.outcome
                if live.outcome != authz_result.get("outcome"):
                    gate_result_match = False

    all_pass = evidence_hash_match and action_input_match and gate_result_match
    failure_reasons = []
    if not evidence_hash_match:
        failure_reasons.append("evidence_hash_mismatch")
    if not action_input_match:
        failure_reasons.append("decision_content_hash_mismatch")
    if not gate_result_match:
        failure_reasons.append("gate_result_mismatch")
    if authz_replay_mode == "recorded_only":
        failure_reasons.append("authz_replay_recorded_only")

    if not all_pass:
        status = "FAIL"
    elif authz_replay_mode == "recorded_only":
        status = "PARTIAL_RECORDED_ONLY"
    else:
        status = "PASS"

    return ReplayResult(
        decision_id=decision_id,
        original={
            "evidence_hash": stored_evidence_hash,
            "ontology_version": pg_row["ontology_version"],
            "shape_version": pg_row["shape_set_version"],
            "authz_version": pg_row["authorization_model_version"],
            "policy_version": pg_row["policy_bundle_version"],
            "action_version": f"v{pg_row['action_version']}@{pg_row['action_pinned_sha256']}",
            "gate_results": {
                "authorization": authz_result.get("outcome"),
                "policy": policy_result.get("outcome"),
                "conformance": (pg_row["conformance_result"] or {}).get("outcome"),
            },
            "proposed_action": {"action_type": pg_row["action_type"], "parameters": parameters},
            "observed_outcome": pg_row["status"],
        },
        replay={
            "reconstructed": True,
            "evidence_hash_match": evidence_hash_match,
            "gate_result_match": gate_result_match,
            "action_input_match": action_input_match,
            "policy_replayed_outcome": policy_replayed_outcome,
            "authz_replayed_outcome": authz_replayed_outcome,
            "authz_replay_mode": authz_replay_mode,
        },
        status=status,
        failure_reasons=failure_reasons,
    )


_store_id_cache: dict[str, str] = {}


def _resolve_store_id(openfga_api_url: str) -> str | None:
    # Same "resolve fresh, never trust a stale cache across a store wipe"
    # policy as services/decision_service/app.py — but replay is typically
    # a short-lived CLI/one-off HTTP call, so a per-process cache (cleared
    # never, since the process itself is short-lived) is fine here, unlike
    # the long-running decision_service.
    if openfga_api_url not in _store_id_cache:
        resolved = authz.resolve_store_id(openfga_api_url)
        if resolved:
            _store_id_cache[openfga_api_url] = resolved
    return _store_id_cache.get(openfga_api_url)


def reevaluate_under_current(decision_id: str, conn, opa_base_url: str) -> dict[str, Any]:
    """Counterfactual: 'what would TODAY's deployed rules decide given the
    historical EVIDENCE FACTS?' Never overwrites the original decision;
    never writes anything at all. Reuses the frozen `facts_used` (never
    re-reads live projections — those may have moved on since) but rebuilds
    the policy INPUT from them using the CURRENT action/policy_package, so
    (unlike replay) this deliberately CAN diverge from the original."""
    from services.decision_service import policy as policy_mod
    from services.decision_service.evidence import EvidenceResult
    from services.decision_service.manifest import build_manifest, content_addressed

    pg_row = store.get_decision(conn, decision_id)
    if pg_row is None:
        raise DecisionNotFound(f"decision {decision_id!r} not found")
    evidence = pg_row["evidence_snapshot"] or {}
    facts_used = evidence.get("facts_used", {})

    manifest = build_manifest()  # CURRENT live manifest, deliberately not historical
    action_version_dir = manifest["deployed_version"]["actions"]
    action = get_action_type(pg_row["action_type"], action_version_dir)
    if action is None:
        raise ValueError(f"action type {pg_row['action_type']!r} not found under current version {action_version_dir!r}")
    current_action_sha256 = manifest["actions"].get(pg_row["action_type"], {}).get("sha256", "?")

    # A V1-era evidence snapshot has no "reservation_ok" fact (that field
    # didn't exist until V2 — contracts/actions/v2/transfer_inventory.yaml)
    # but DOES already carry on_hand/reserved inside current_source_inventory
    # (services/decision_service/evidence.py has always populated both,
    # even when v1's own policy never read them) — derive it rather than
    # fail, since the underlying data genuinely was captured at the time,
    # just not yet surfaced as its own named fact.
    src = facts_used.get("current_source_inventory", {})
    if "reservation_ok" not in facts_used and "on_hand" in src and "reserved" in src:
        facts_used = {**facts_used, "reservation_ok": bool(src["on_hand"] >= src["reserved"])}

    ev = EvidenceResult(facts_used=facts_used, facts_excluded=evidence.get("facts_excluded", {}))
    try:
        input_json = policy_mod.build_input(action, pg_row["parameters"], ev)
    except KeyError as exc:
        # Honest failure mode, never a crash: the historical evidence shape
        # genuinely cannot answer what today's policy needs.
        return {
            "mode": "counterfactual",
            "decision_id": decision_id,
            "original_status": pg_row["status"],
            "error": f"cannot reevaluate under current rules — historical evidence is missing a field the "
                     f"CURRENT policy input requires: {exc}",
            "under_current_action_version": f"{action_version_dir}@{current_action_sha256}",
            "note": "counterfactual only — never written back to history",
        }
    current_result = policy_mod.evaluate(opa_base_url, action, input_json)

    return {
        "mode": "counterfactual",
        "decision_id": decision_id,
        "original_status": pg_row["status"],
        "original_policy_outcome": (pg_row["policy_result"] or {}).get("outcome"),
        "under_current_policy_version": content_addressed(manifest["opa"]),
        "under_current_action_version": f"{action_version_dir}@{current_action_sha256}",
        "under_current_policy_outcome": current_result.outcome,
        "diverges_from_original": current_result.outcome != (pg_row["policy_result"] or {}).get("outcome"),
        "note": "counterfactual only — never written back to history",
    }
