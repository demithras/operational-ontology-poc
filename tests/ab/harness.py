"""Shared A/B test harness — one place that opens every connection a
workload might need (both variants' HTTP clients, every source DB, both
decision stores, RDF4J), used identically by `pytest tests/ab` (via
conftest.py fixtures) and by `scripts/run_ab.py` (calling each workload's
`run(harness)` function directly, no pytest collection needed — see that
script's own docstring for why: a single orchestrated run needs to
aggregate every workload's metrics into ONE results file, which is
awkward to do from inside pytest's own result reporting)."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import psycopg

from seed import db_env
from services.common.rdf4j_client import RDF4JClient
from tests.ab.clients import VariantClient, make_clients


@dataclass
class Harness:
    clients: dict[str, VariantClient]
    erp_conn: psycopg.Connection
    mes_conn: psycopg.Connection
    wms_conn: psycopg.Connection
    baseline_conn: psycopg.Connection
    ontology_hot_conn: psycopg.Connection
    rdf4j_client: RDF4JClient
    erp_http: httpx.Client
    mes_http: httpx.Client
    wms_http: httpx.Client

    @property
    def ontology(self) -> VariantClient:
        return self.clients["ontology"]

    @property
    def baseline(self) -> VariantClient:
        return self.clients["baseline"]

    @classmethod
    def create(cls) -> "Harness":
        db_env.load_dotenv()
        return cls(
            clients=make_clients(),
            erp_conn=psycopg.connect(db_env.erp_dsn(), autocommit=True),
            mes_conn=psycopg.connect(db_env.mes_dsn(), autocommit=True),
            wms_conn=psycopg.connect(db_env.wms_dsn(), autocommit=True),
            baseline_conn=psycopg.connect(db_env.baseline_dsn(), autocommit=True),
            ontology_hot_conn=psycopg.connect(db_env.ontology_hot_dsn(), autocommit=True),
            rdf4j_client=RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo"),
            erp_http=httpx.Client(base_url=db_env.http_base_urls()["erp"], timeout=10.0),
            mes_http=httpx.Client(base_url=db_env.http_base_urls()["mes"], timeout=10.0),
            wms_http=httpx.Client(base_url=db_env.http_base_urls()["wms"], timeout=10.0),
        )

    def close(self) -> None:
        for c in self.clients.values():
            c.client.close()
        self.erp_conn.close()
        self.mes_conn.close()
        self.wms_conn.close()
        self.baseline_conn.close()
        self.ontology_hot_conn.close()
        self.rdf4j_client.close()
        self.erp_http.close()
        self.mes_http.close()
        self.wms_http.close()
