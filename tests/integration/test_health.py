"""docs/experiment/spec/04_architecture.md: every fake source exposes a
health endpoint."""

from __future__ import annotations

import httpx


def test_erp_health(erp_client: httpx.Client):
    r = erp_client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_mes_health(mes_client: httpx.Client):
    r = mes_client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_wms_health(wms_client: httpx.Client):
    r = wms_client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
