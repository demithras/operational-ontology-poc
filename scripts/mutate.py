#!/usr/bin/env python3
"""Phase 10a item 2 — docs/experiment/spec/08_test_strategy.md "Mutation
testing (recommended)": the 5 named mutations, applied to the REAL
implementation (not a copy), each with a "deploy" step that makes the
mutation actually live against whatever component evaluates it, and a
matching revert.

Usage:

    .venv/bin/python scripts/mutate.py apply <ID>
    .venv/bin/python scripts/mutate.py revert <ID>
    .venv/bin/python scripts/mutate.py status <ID>
    .venv/bin/python scripts/mutate.py list

`tests/mutation/test_mutations.py` is the actual pass/fail authority
(apply -> run the relevant suite -> confirm RED on an ASSERTION -> revert
-> confirm the control suite is GREEN); this module only owns the
apply/revert/deploy mechanics so that suite doesn't have to.

Each mutation's "deploy" step reflects how that PARTICULAR component
actually picks up a contract change in this repo (see docs/experiment/
implementation-notes.md's Phase 10a item 2 section for the full
reasoning):
  - OPA policy + pyshacl SHACL fixtures: read straight off disk by their
    own test runners (`opa test`, pyshacl) — no live service involved,
    so "deploy" is a no-op.
  - OpenFGA authorization model: `bootstrap_openfga.py` writes a NEW
    (immutable) model version and decision_service always resolves
    "latest" per request — re-running it after either an apply OR a
    revert is what makes the change live.
  - `services/action_worker/outcome_eval.py`: baked into the shared
    Docker image (services/ isn't bind-mounted into that container) —
    "deploy" is `docker compose up -d --build action_worker`.
  - WMS idempotency check: a process-wide runtime TOGGLE (services/
    common/faults.py::FaultRegistry), not a file edit at all — "apply"/
    "revert" ARE the deploy step (one HTTP call to WMS's own test-mode
    endpoint), see services/wms/transfers.py's own comment for why a
    file-level mutation isn't how this one is expressed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKER_CONFIG = os.environ.get(
    "DOCKER_CONFIG",
    "/private/tmp/claude-501/-Users-d-surchis-work-operational-ontology-poc/"
    "4651d52d-5874-4c7c-ba8b-4da032dde2a5/scratchpad/docker-config",
)


@dataclass(frozen=True)
class Mutation:
    id: str
    description: str
    kind: str  # "file" | "toggle"
    target: list[str]  # pytest node ids the mutation must turn RED
    control: list[str]  # pytest node ids that must stay GREEN throughout
    path: Optional[Path] = None
    old: Optional[str] = None
    new: Optional[str] = None
    deploy: Optional[str] = None  # None | "bootstrap_openfga" | "docker_rebuild:<service>"


MUTATIONS: dict[str, Mutation] = {
    "POLICY_COMPARATOR": Mutation(
        id="POLICY_COMPARATOR",
        description=(
            "OPA policy comparator (spec 08's own example category): the safety-stock "
            "hard_deny boundary `remaining < safety_stock` -> `remaining <= safety_stock` "
            "in contracts/policies/v1/transfer_inventory.rego"
        ),
        kind="file",
        path=REPO_ROOT / "contracts" / "policies" / "v1" / "transfer_inventory.rego",
        old="remaining < input.evidence.safety_stock",
        new="remaining <= input.evidence.safety_stock",
        deploy=None,
        target=["tests/contracts/test_opa_policies.py::test_opa_test_suite_passes_and_is_not_empty[v1]"],
        control=["tests/contracts/test_opa_policies.py::test_opa_test_suite_passes_and_is_not_empty[v2]"],
    ),
    "SHACL_CARDINALITY": Mutation(
        id="SHACL_CARDINALITY",
        description=(
            "SHACL cardinality: oo:EvidenceSnapshot's required oo:snapshotContentHash "
            "minCount 1 -> 0 in contracts/shapes/v1/evidence-snapshot-shape.ttl"
        ),
        kind="file",
        path=REPO_ROOT / "contracts" / "shapes" / "v1" / "evidence-snapshot-shape.ttl",
        old="sh:path oo:snapshotContentHash ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:string ;",
        new="sh:path oo:snapshotContentHash ; sh:minCount 0 ; sh:maxCount 1 ; sh:datatype xsd:string ;",
        deploy=None,
        # NOTE (found live, first attempt): decision-missing-actor.ttl was tried first as the
        # target here and turned out to be a COMPOUND negative fixture — it references a bare
        # oo:EvidenceSnapshot (es-2) with NEITHER snapshotContentHash NOR snapshotObservedAt, so
        # it stays non-conforming via the evidence-snapshot shape regardless of decision-shape's
        # own oo:actor cardinality, making that pairing unable to prove THIS mutation. Both
        # fixtures below carry exactly ONE violation each (verified by reading the fixture
        # files), which is what a mutation-testing pairing actually needs.
        target=["tests/contracts/test_shacl_fixtures.py::test_negative_fixture_does_not_conform[evidence-snapshot-missing-content-hash.ttl]"],
        control=["tests/contracts/test_shacl_fixtures.py::test_negative_fixture_does_not_conform[decision-missing-evidence.ttl]"],
    ),
    "AUTHZ_RELATION": Mutation(
        id="AUTHZ_RELATION",
        description=(
            "OpenFGA authorization relation: widen can_approve_large_transfer_v2 to also "
            "include junior_planner in contracts/authorization/v2/model.fga (v2, NOT v1 -- "
            "the live stack has contracts/manifests/deployed_version.json's authorization "
            "pointer at v2, per action v3's approval_relation=can_approve_large_transfer_v2)"
        ),
        kind="file",
        path=REPO_ROOT / "contracts" / "authorization" / "v2" / "model.fga",
        old="define can_approve_large_transfer_v2: senior_approver",
        new="define can_approve_large_transfer_v2: senior_approver or junior_planner",
        deploy="bootstrap_openfga_v2_forced",
        target=["tests/integration/test_decision_service_approval.py::test_junior_planner_denied_protected_approval"],
        control=["tests/integration/test_decision_service_approval.py::test_supervisor_can_approve_and_decision_becomes_approved"],
    ),
    "RECONCILIATION_QUANTITY": Mutation(
        id="RECONCILIATION_QUANTITY",
        description=(
            "Reconciliation quantity comparator: the F16/F17 divergence check's "
            "`actual_quantity != requested_quantity` -> `== ` (inverted) in "
            "services/action_worker/outcome_eval.py"
        ),
        kind="file",
        path=REPO_ROOT / "services" / "action_worker" / "outcome_eval.py",
        old='if status in ("COMMITTED", "PARTIAL", "REVERSED") and actual_quantity != requested_quantity:',
        new='if status in ("COMMITTED", "PARTIAL", "REVERSED") and actual_quantity == requested_quantity:',
        deploy="docker_rebuild:action_worker",
        target=["tests/faults/test_divergence.py::test_f16_f17_partial_commit_diverges_and_compensates"],
        control=["tests/faults/test_divergence.py::test_f15_200_without_commit_never_observed_success"],
    ),
    "IDEMPOTENCY_HANDLING": Mutation(
        id="IDEMPOTENCY_HANDLING",
        description=(
            "WMS idempotency check: process-wide runtime toggle "
            "(services/common/faults.py::FaultRegistry.disable_idempotency_check) "
            "makes a deduped retry re-apply its inventory mutation instead of being dropped"
        ),
        kind="toggle",
        target=["tests/integration/test_wms_idempotency.py::test_same_key_ten_concurrent_requests_exactly_one_effect"],
        control=["tests/integration/test_wms_idempotency.py::test_same_key_different_body_is_409"],
    ),
}


def _docker_compose(*args: str, timeout: float = 240.0) -> subprocess.CompletedProcess:
    env = {**os.environ, "DOCKER_CONFIG": DOCKER_CONFIG}
    return subprocess.run(["docker", "compose", *args], cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=timeout)


def _wms_base_url() -> str:
    sys.path.insert(0, str(REPO_ROOT))
    from seed import db_env

    db_env.load_dotenv()
    return db_env.http_base_urls()["wms"]


def _set_file_content(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise RuntimeError(f"{path}: expected substring not found — file has drifted since this mutation was written:\n{old!r}")
    path.write_text(text.replace(old, new, 1))


def _deploy_authz_v2_forced() -> None:
    """Publishes contracts/authorization/v2/model.fga as a GENUINELY NEW
    OpenFGA authorization model version and makes it "latest" — deliberately
    NOT services/decision_service/bootstrap_openfga.py's own `bootstrap()`/
    `_write_model()` path, which (by design, per its own docstring)
    content-DEDUPLICATES against recent models and reuses an existing id
    when the content already matches. That is exactly right for `make up`'s
    idempotent bring-up, but WRONG here: after this mutation's own apply
    (genuinely new content -> no dedup match -> fine) the REVERT pushes the
    ORIGINAL v2 content back, which dedup-matches the store's OLD, no-longer-
    latest v2 model and returns ITS id without creating anything new -- so
    "latest" stays on whatever the apply step made latest instead of
    reverting. Found live during this phase's own first run: reverting via
    the dedup path left the store's "latest" authorization model
    PERMANENTLY on a stale (even v1-shaped, from an earlier debugging
    attempt) model, breaking a control test that has nothing to do with
    this mutation. Forcing a brand-new model on EVERY apply/revert call
    keeps "latest" always pointed at whatever THIS call just published,
    which is the only invariant this mutation testing setup actually needs.
    Explicitly pins `authorization_model_id` on every tuple write (rather
    than relying on "latest" resolution, which was observed to lag briefly
    right after a brand-new model is created) and tolerates "already
    exists" exactly like services/decision_service/bootstrap_openfga.py's
    own _write_tuples does."""
    sys.path.insert(0, str(REPO_ROOT))
    from seed import db_env
    from services.decision_service.bootstrap_openfga import _find_or_create_store, _transform_model_to_json, STORE_NAME

    db_env.load_dotenv()
    base_url = db_env.openfga_api_url()
    auth_dir = REPO_ROOT / "contracts" / "authorization" / "v2"
    model_json = _transform_model_to_json(auth_dir / "model.fga")
    import yaml

    tuples = yaml.safe_load((auth_dir / "tuples.yaml").read_text())

    with httpx.Client(timeout=10.0) as client:
        store_id = _find_or_create_store(client, base_url, STORE_NAME)
        r = client.post(f"{base_url}/stores/{store_id}/authorization-models", json=model_json)
        r.raise_for_status()
        model_id = r.json()["authorization_model_id"]
        for tuple_key in tuples:
            tr = client.post(
                f"{base_url}/stores/{store_id}/write",
                json={"writes": {"tuple_keys": [tuple_key]}, "authorization_model_id": model_id},
            )
            if tr.status_code == 200 or (tr.status_code == 400 and "already exist" in tr.text.lower()):
                continue
            tr.raise_for_status()

    latest = httpx.get(f"{base_url}/stores/{store_id}/authorization-models?page_size=1", timeout=10.0)
    latest.raise_for_status()
    latest_id = latest.json()["authorization_models"][0]["id"]
    if latest_id != model_id:
        raise RuntimeError(
            f"forced-new model {model_id} did not become 'latest' (found {latest_id} instead) "
            f"— a concurrent writer may be racing this store"
        )


def _run_deploy(deploy: Optional[str]) -> None:
    if deploy is None:
        return
    if deploy == "bootstrap_openfga_v2_forced":
        _deploy_authz_v2_forced()
        return
    if deploy.startswith("docker_rebuild:"):
        service = deploy.split(":", 1)[1]
        build = _docker_compose("up", "-d", "--build", service)
        if build.returncode != 0:
            raise RuntimeError(f"docker compose up -d --build {service} failed: {build.stdout}\n{build.stderr}")
        return
    raise ValueError(f"unknown deploy mechanism: {deploy!r}")


def apply_mutation(mutation_id: str) -> None:
    m = MUTATIONS[mutation_id]
    if m.kind == "toggle":
        r = httpx.post(f"{_wms_base_url()}/_test/idempotency-check", json={"enabled": False}, timeout=10.0)
        r.raise_for_status()
        assert r.json()["idempotency_check_enabled"] is False, r.json()
        return
    assert m.path is not None and m.old is not None and m.new is not None
    _set_file_content(m.path, m.old, m.new)
    _run_deploy(m.deploy)


def revert_mutation(mutation_id: str) -> None:
    m = MUTATIONS[mutation_id]
    if m.kind == "toggle":
        r = httpx.post(f"{_wms_base_url()}/_test/idempotency-check", json={"enabled": True}, timeout=10.0)
        r.raise_for_status()
        assert r.json()["idempotency_check_enabled"] is True, r.json()
        return
    assert m.path is not None and m.old is not None and m.new is not None
    _set_file_content(m.path, m.new, m.old)
    _run_deploy(m.deploy)


def status(mutation_id: str) -> str:
    m = MUTATIONS[mutation_id]
    if m.kind == "toggle":
        r = httpx.get(f"{_wms_base_url()}/_test/faults", timeout=10.0)
        r.raise_for_status()
        enabled = r.json().get("idempotency_check_enabled")
        return "MUTATED (idempotency check disabled)" if enabled is False else "clean"
    assert m.path is not None
    text = m.path.read_text()
    if m.new in text:
        return "MUTATED"
    if m.old in text:
        return "clean"
    return "UNKNOWN (neither old nor new substring found — file has drifted)"


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] == "list":
        for mid, m in MUTATIONS.items():
            print(f"{mid}: {m.description}")
        return 0
    cmd = argv[1]
    if cmd not in ("apply", "revert", "status"):
        print(f"unknown command: {cmd!r} (expected apply|revert|status|list)", file=sys.stderr)
        return 2
    if len(argv) < 3:
        print("usage: mutate.py <apply|revert|status> <MUTATION_ID>", file=sys.stderr)
        return 2
    mutation_id = argv[2]
    if mutation_id not in MUTATIONS:
        print(f"unknown mutation id: {mutation_id!r}. Known: {sorted(MUTATIONS)}", file=sys.stderr)
        return 2
    if cmd == "apply":
        apply_mutation(mutation_id)
        print(f"{mutation_id}: applied")
    elif cmd == "revert":
        revert_mutation(mutation_id)
        print(f"{mutation_id}: reverted")
    else:
        print(f"{mutation_id}: {status(mutation_id)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
