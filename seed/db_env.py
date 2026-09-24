"""Tiny, dependency-free .env reader + per-system DSN builder for scripts
that run on the HOST (not inside docker-compose's network) — currently only
seed/load.py and tests/integration/conftest.py. Deliberately does not pull
in python-dotenv to keep the dependency list minimal.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path | None = None) -> None:
    """Populate os.environ from .env (falling back to .env.example) without
    overriding any variable already set in the real environment."""
    candidates = [path] if path else [REPO_ROOT / ".env", REPO_ROOT / ".env.example"]
    for candidate in candidates:
        if candidate and candidate.exists():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if key and key not in os.environ:
                    os.environ[key] = value.strip()
            return


def host_dsn(db_name_var: str, db_user_var: str, db_password_var: str) -> str:
    """DSN for connecting from the host to a system database via the
    docker-compose-published Postgres port (POSTGRES_HOST_PORT)."""
    host = os.environ.get("OO_POSTGRES_HOST", "localhost")
    port = os.environ["POSTGRES_HOST_PORT"]
    name = os.environ[db_name_var]
    user = os.environ[db_user_var]
    password = os.environ[db_password_var]
    return f"host={host} port={port} dbname={name} user={user} password={password}"


def erp_dsn() -> str:
    return host_dsn("ERP_DB_NAME", "ERP_DB_USER", "ERP_DB_PASSWORD")


def mes_dsn() -> str:
    return host_dsn("MES_DB_NAME", "MES_DB_USER", "MES_DB_PASSWORD")


def ontology_hot_dsn() -> str:
    """Phase 4: host-side DSN for the ontology_hot database (services/
    projection_builder connects via SERVICE_DB_* container env vars instead
    — this is for host-run scripts: rebuild.py, bench_phase4.py, and
    tests/integration/ reading hot-projection rows directly)."""
    return host_dsn("ONTOLOGY_HOT_DB_NAME", "ONTOLOGY_HOT_DB_USER", "ONTOLOGY_HOT_DB_PASSWORD")


def wms_dsn() -> str:
    return host_dsn("WMS_DB_NAME", "WMS_DB_USER", "WMS_DB_PASSWORD")


def http_base_urls() -> dict[str, str]:
    host = os.environ.get("OO_SERVICE_HOST", "localhost")
    return {
        "erp": f"http://{host}:{os.environ['ERP_HTTP_PORT']}",
        "mes": f"http://{host}:{os.environ['MES_HTTP_PORT']}",
        "wms": f"http://{host}:{os.environ['WMS_HTTP_PORT']}",
    }


# --- Phase 3 (docs/adr/0002-cdc-now-not-deferred.md) --------------------


def rdf4j_server_url() -> str:
    """Host-reachable RDF4J server base (repositories live under
    ``{this}/repositories/{id}``). services/ingestion (running inside
    docker-compose) instead uses RDF4J_BASE_URL=http://rdf4j:8080/rdf4j-server
    directly, set in docker-compose.yml."""
    host = os.environ.get("OO_SERVICE_HOST", "localhost")
    return f"http://{host}:{os.environ['RDF4J_HOST_PORT']}/rdf4j-server"


def connect_rest_url() -> str:
    host = os.environ.get("OO_SERVICE_HOST", "localhost")
    return f"http://{host}:{os.environ['CONNECT_HOST_PORT']}"


def ingestion_health_url() -> str:
    host = os.environ.get("OO_SERVICE_HOST", "localhost")
    return f"http://{host}:{os.environ['INGESTION_HEALTH_PORT']}"


# --- Phase 5 (docs/experiment/briefs/phase5.md) --------------------------


def openfga_api_url() -> str:
    host = os.environ.get("OO_SERVICE_HOST", "localhost")
    return f"http://{host}:{os.environ['OPENFGA_HOST_PORT']}"


def opa_base_url() -> str:
    host = os.environ.get("OO_SERVICE_HOST", "localhost")
    return f"http://{host}:{os.environ['OPA_HOST_PORT']}"


def decision_service_url() -> str:
    host = os.environ.get("OO_SERVICE_HOST", "localhost")
    return f"http://{host}:{os.environ['DECISION_SERVICE_HTTP_PORT']}"
