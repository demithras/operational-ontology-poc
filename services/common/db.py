"""Per-service Postgres connection pool.

Each service (erp/mes/wms) calls `open_pool()` once at startup with its OWN
connection settings (from its own SERVICE_DB_* environment variables — see
docker-compose.yml). There is no shared credential or shared connection
between services; each process only ever holds a pool to the single
database it owns.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg_pool import ConnectionPool


def dsn_from_env() -> str:
    host = os.environ["SERVICE_DB_HOST"]
    port = os.environ.get("SERVICE_DB_PORT", "5432")
    name = os.environ["SERVICE_DB_NAME"]
    user = os.environ["SERVICE_DB_USER"]
    password = os.environ["SERVICE_DB_PASSWORD"]
    return f"host={host} port={port} dbname={name} user={user} password={password}"


_pool: ConnectionPool | None = None


def open_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=dsn_from_env(),
            min_size=1,
            max_size=10,
            open=True,
            kwargs={"autocommit": False},
        )
        _pool.wait(timeout=30)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    pool = open_pool()
    with pool.connection() as conn:
        yield conn
