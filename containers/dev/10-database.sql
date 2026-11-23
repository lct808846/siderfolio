-- Only installed by the entrypoint for the isolated dev volume.
\getenv app_password ASTRO_DEV_DB_PASSWORD
CREATE ROLE astroagent LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';
ALTER DATABASE astroagent_dev OWNER TO astroagent;
CREATE EXTENSION vector;
CREATE EXTENSION pg_trgm;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO astroagent;
