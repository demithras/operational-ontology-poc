"""Minimal RDF4J REST client. Deliberately thin (httpx + string formatting,
no rdf4j-python-driver dependency) — every call here was verified by hand
against the running eclipse/rdf4j-workbench:6.1.0-tomcat container during
Phase 3 implementation (see contracts/rdf4j/v1/oo-repository-config.ttl's
header comment for the empirical notes on config format / 409-on-violation
behavior).

Used by: services/ingestion/bootstrap_rdf4j.py (repo + ontology + shapes
setup), services/ingestion/consumer.py (writing observed facts),
services/identity_resolver (reading/writing identity mappings), and
tests/contracts/test_shacl_rdf4j_transactional.py.
"""

from __future__ import annotations

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(10.0)


def _context_param(graph_iri: str | None) -> dict[str, str]:
    if graph_iri is None:
        return {}
    return {"context": f"<{graph_iri}>"}


class RDF4JClient:
    def __init__(self, base_url: str, repository: str, timeout: httpx.Timeout = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.repository = repository
        self._client = httpx.Client(timeout=timeout)

    @property
    def _repo_url(self) -> str:
        return f"{self.base_url}/repositories/{self.repository}"

    def close(self) -> None:
        self._client.close()

    # --- repository lifecycle -------------------------------------------------

    def repository_exists(self) -> bool:
        r = self._client.get(f"{self.base_url}/repositories/{self.repository}/size")
        return r.status_code == 200

    def create_repository(self, config_ttl: str) -> None:
        r = self._client.put(
            f"{self.base_url}/repositories/{self.repository}",
            content=config_ttl.encode("utf-8"),
            headers={"Content-Type": "text/turtle"},
        )
        r.raise_for_status()

    def delete_repository(self) -> None:
        r = self._client.delete(f"{self.base_url}/repositories/{self.repository}")
        if r.status_code not in (204, 404):
            r.raise_for_status()

    # --- statements -------------------------------------------------------

    def add_turtle(self, ttl_text: str, graph_iri: str | None = None) -> httpx.Response:
        """POST adds triples (RDF is a set — re-adding is naturally
        idempotent). Returns the raw response so callers can inspect a 409
        SHACL-violation body instead of a generic exception."""
        return self._client.post(
            f"{self._repo_url}/statements",
            params=_context_param(graph_iri),
            content=ttl_text.encode("utf-8"),
            headers={"Content-Type": "text/turtle"},
        )

    def update(self, sparql_update: str) -> httpx.Response:
        """SPARQL 1.1 Update (DELETE/INSERT ... WHERE) against the whole
        repository — used by services/decision_service/rdf_writer.py to
        transition an already-committed Decision's oo:status (e.g.
        REQUIRES_APPROVAL -> APPROVED) via one atomic retract+add, since
        add_turtle() is purely additive and cannot itself remove the old
        status value (SHACL's `sh:maxCount 1` would otherwise see two).
        Verified empirically against the running RDF4J 6.1.0 container:
        `Content-Type: application/sparql-update`, raw SPARQL Update text as
        the body, HTTP 204 on success, still SHACL-validated (a resulting
        two-statuses-at-once state would 409 exactly like add_turtle would)."""
        return self._client.post(
            f"{self._repo_url}/statements",
            content=sparql_update.encode("utf-8"),
            headers={"Content-Type": "application/sparql-update"},
        )

    def clear_graph(self, graph_iri: str) -> None:
        r = self._client.delete(f"{self._repo_url}/statements", params={"context": f"<{graph_iri}>"})
        if r.status_code not in (204, 404):
            r.raise_for_status()

    def delete_subject(self, subject_iri: str, graph_iri: str | None = None) -> None:
        """Removes every statement with the given subject (any predicate/
        object), scoped to graph_iri if given. Used by services/ingestion
        to retract an entity's stale fac: triples before writing its new
        observed state (phase3.md item 5's upsert-on-newer-CDC-event
        pattern)."""
        params = {"subj": f"<{subject_iri}>"}
        params.update(_context_param(graph_iri))
        r = self._client.delete(f"{self._repo_url}/statements", params=params)
        if r.status_code not in (204, 404):
            r.raise_for_status()

    # --- query --------------------------------------------------------------

    def ask(self, sparql: str) -> bool:
        r = self._client.get(
            self._repo_url,
            params={"query": sparql},
            headers={"Accept": "application/sparql-results+json"},
        )
        r.raise_for_status()
        return bool(r.json()["boolean"])

    def select(self, sparql: str) -> list[dict[str, str]]:
        r = self._client.get(
            self._repo_url,
            params={"query": sparql},
            headers={"Accept": "application/sparql-results+json"},
        )
        r.raise_for_status()
        bindings = r.json()["results"]["bindings"]
        return [{k: v["value"] for k, v in row.items()} for row in bindings]

    def size(self, graph_iri: str | None = None) -> int:
        params = _context_param(graph_iri)
        # RDF4J's /size endpoint takes repeated context params, IRI-only
        # (no angle brackets) — quote explicitly rather than reusing
        # _context_param's angle-bracket form.
        if graph_iri is not None:
            params = {"context": f"<{graph_iri}>"}
        r = self._client.get(f"{self._repo_url}/size", params=params)
        r.raise_for_status()
        return int(r.text.strip())
