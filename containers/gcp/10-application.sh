#!/bin/sh
# The official PostgreSQL entrypoint invokes this only for a new data volume.
set -eu

psql --username "$POSTGRES_USER" --dbname postgres --set ON_ERROR_STOP=1 <<'SQL'
\getenv app_password ASTROAGENT_DB_PASSWORD
CREATE ROLE astroagent LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
CREATE DATABASE astroagent OWNER astroagent TEMPLATE template0;
\connect astroagent
CREATE EXTENSION vector;
CREATE EXTENSION pg_trgm;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO astroagent;
SQL
