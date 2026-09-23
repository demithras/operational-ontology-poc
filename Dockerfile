# Single shared image for the three fake source-system services
# (services/erp, services/mes, services/wms). Which service runs is chosen
# by docker-compose's `command:` per container — this keeps one Dockerfile
# instead of three near-identical copies (phase2.md item 2).
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml
COPY services /app/services
COPY reference_model /app/reference_model

RUN pip install --no-cache-dir \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.32" \
    "psycopg[binary,pool]>=3.2"

# services.* / reference_model.* are implicit namespace packages (no
# __init__.py at their top level, matching the rest of the repo) — make sure
# `uvicorn services.erp.app:app` can import them regardless of how uvicorn's
# own CWD-on-sys.path behavior changes across versions.
ENV PYTHONPATH=/app

EXPOSE 8000
