#!/usr/bin/env bash
# Runs once, automatically, when the postgres container's data directory is
# first initialized (standard docker-entrypoint-initdb.d hook). Creates one
# role + one database per source system (erp/mes/wms) plus two forward-looking
# databases (ontology_hot, baseline) for later phases, per
# docs/experiment/briefs/phase2.md item 1.
#
# Each role gets CONNECT revoked from every OTHER system's database, so the
# credential-isolation requirement (phase2.md item 5, "wms role cannot
# connect to the erp DB") holds at the Postgres level, not just by
# convention in application code.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
	CREATE ROLE ${ERP_DB_USER} LOGIN PASSWORD '${ERP_DB_PASSWORD}';
	CREATE DATABASE ${ERP_DB_NAME} OWNER ${ERP_DB_USER};

	CREATE ROLE ${MES_DB_USER} LOGIN PASSWORD '${MES_DB_PASSWORD}';
	CREATE DATABASE ${MES_DB_NAME} OWNER ${MES_DB_USER};

	CREATE ROLE ${WMS_DB_USER} LOGIN PASSWORD '${WMS_DB_PASSWORD}';
	CREATE DATABASE ${WMS_DB_NAME} OWNER ${WMS_DB_USER};

	CREATE ROLE ${ONTOLOGY_HOT_DB_USER} LOGIN PASSWORD '${ONTOLOGY_HOT_DB_PASSWORD}';
	CREATE DATABASE ${ONTOLOGY_HOT_DB_NAME} OWNER ${ONTOLOGY_HOT_DB_USER};

	CREATE ROLE ${BASELINE_DB_USER} LOGIN PASSWORD '${BASELINE_DB_PASSWORD}';
	CREATE DATABASE ${BASELINE_DB_NAME} OWNER ${BASELINE_DB_USER};

	-- Credential isolation: revoke default PUBLIC connect grant on every
	-- database, then grant CONNECT back only to that database's own role
	-- (plus the bootstrap superuser, which keeps needing access for
	-- future init scripts / ops).
	REVOKE CONNECT ON DATABASE ${ERP_DB_NAME} FROM PUBLIC;
	REVOKE CONNECT ON DATABASE ${MES_DB_NAME} FROM PUBLIC;
	REVOKE CONNECT ON DATABASE ${WMS_DB_NAME} FROM PUBLIC;
	REVOKE CONNECT ON DATABASE ${ONTOLOGY_HOT_DB_NAME} FROM PUBLIC;
	REVOKE CONNECT ON DATABASE ${BASELINE_DB_NAME} FROM PUBLIC;

	GRANT CONNECT ON DATABASE ${ERP_DB_NAME} TO ${ERP_DB_USER};
	GRANT CONNECT ON DATABASE ${MES_DB_NAME} TO ${MES_DB_USER};
	GRANT CONNECT ON DATABASE ${WMS_DB_NAME} TO ${WMS_DB_USER};
	GRANT CONNECT ON DATABASE ${ONTOLOGY_HOT_DB_NAME} TO ${ONTOLOGY_HOT_DB_USER};
	GRANT CONNECT ON DATABASE ${BASELINE_DB_NAME} TO ${BASELINE_DB_USER};
EOSQL

# Lock down the public schema of each system DB to only that DB's own role
# (belt-and-suspenders alongside the CONNECT revoke above).
for pair in "${ERP_DB_NAME}:${ERP_DB_USER}" "${MES_DB_NAME}:${MES_DB_USER}" "${WMS_DB_NAME}:${WMS_DB_USER}" "${ONTOLOGY_HOT_DB_NAME}:${ONTOLOGY_HOT_DB_USER}" "${BASELINE_DB_NAME}:${BASELINE_DB_USER}"; do
	db="${pair%%:*}"
	role="${pair##*:}"
	psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<-EOSQL
		REVOKE ALL ON SCHEMA public FROM PUBLIC;
		GRANT ALL ON SCHEMA public TO ${role};
	EOSQL
done
