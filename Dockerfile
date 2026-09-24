# Single shared image for the fake source-system services (services/erp,
# services/mes, services/wms) AND, since Phase 3, services/ingestion
# (docs/adr/0002-cdc-now-not-deferred.md). Which service runs is chosen by
# docker-compose's `command:` per container — this keeps one Dockerfile
# instead of near-identical copies per service (phase2.md item 2).
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml
COPY services /app/services
COPY reference_model /app/reference_model
# services/identity_resolver reads contracts/identity/v1/mapping_rules.yaml
# at runtime (services/ingestion/consumer.py, running inside this image).
COPY contracts /app/contracts

RUN pip install --no-cache-dir \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.32" \
    "psycopg[binary,pool]>=3.2" \
    "httpx>=0.27" \
    "rdflib>=7.0" \
    "pyyaml>=6.0" \
    "confluent-kafka>=2.5" \
    "temporalio>=1.33" \
    "mcp<2,>=1.2" \
    "starlette" \
    "opentelemetry-api>=1.27" \
    "opentelemetry-sdk>=1.27" \
    "opentelemetry-exporter-otlp-proto-http>=1.27"

# services.* / reference_model.* are implicit namespace packages (no
# __init__.py at their top level, matching the rest of the repo) — make sure
# `uvicorn services.erp.app:app` can import them regardless of how uvicorn's
# own CWD-on-sys.path behavior changes across versions.
ENV PYTHONPATH=/app

EXPOSE 8000
