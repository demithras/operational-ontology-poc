"""docs/experiment/spec/02_scope_and_non_goals.md: ERP/MES/WMS "must use
separate databases/schemas, APIs, credentials, and ownership boundaries".
Verified at the Postgres level (db/init/00_init.sh REVOKE CONNECT), not
just by convention in application code.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from seed import db_env


@pytest.fixture(scope="module", autouse=True)
def _dotenv():
    db_env.load_dotenv()


def _cross_dsn(own_user_var: str, own_password_var: str, other_db_var: str) -> str:
    host = os.environ.get("OO_POSTGRES_HOST", "localhost")
    port = os.environ["POSTGRES_HOST_PORT"]
    user = os.environ[own_user_var]
    password = os.environ[own_password_var]
    other_db = os.environ[other_db_var]
    return f"host={host} port={port} dbname={other_db} user={user} password={password}"


CROSS_PAIRS = [
    ("wms role -> erp db", "WMS_DB_USER", "WMS_DB_PASSWORD", "ERP_DB_NAME"),
    ("erp role -> mes db", "ERP_DB_USER", "ERP_DB_PASSWORD", "MES_DB_NAME"),
    ("mes role -> wms db", "MES_DB_USER", "MES_DB_PASSWORD", "WMS_DB_NAME"),
]


@pytest.mark.parametrize("label,user_var,password_var,db_var", CROSS_PAIRS, ids=[p[0] for p in CROSS_PAIRS])
def test_cross_system_credential_is_rejected(stack_up: bool, label: str, user_var: str, password_var: str, db_var: str):
    if not stack_up:
        pytest.skip("stack not reachable — run 'make up && make seed' first")

    dsn = _cross_dsn(user_var, password_var, db_var)
    with pytest.raises(psycopg.OperationalError):
        with psycopg.connect(dsn, connect_timeout=5):
            pass  # should never get here — connection must be rejected


def test_own_credential_still_works(stack_up: bool):
    if not stack_up:
        pytest.skip("stack not reachable — run 'make up && make seed' first")
    with psycopg.connect(db_env.wms_dsn(), connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)
