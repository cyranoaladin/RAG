#!/usr/bin/env bash
# Provisionner les deux identités runtime minimales sur un volume Docker neuf.
set -euo pipefail

required_variables=(
    POSTGRES_USER
    PGVECTOR_RETRIEVAL_USER
    PGVECTOR_RETRIEVAL_PASSWORD
    PGVECTOR_REVIEW_USER
    PGVECTOR_REVIEW_PASSWORD
)
for variable in "${required_variables[@]}"; do
    if [[ -z "${!variable:-}" ]]; then
        printf 'ERROR: %s requis pour provisionner les roles runtime.\n' \
            "$variable" >&2
        exit 1
    fi
done

POSTGRES_DB="${POSTGRES_DB:-$POSTGRES_USER}"
export POSTGRES_DB

for role in "$PGVECTOR_RETRIEVAL_USER" "$PGVECTOR_REVIEW_USER"; do
    if [[ ! "$role" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; then
        printf '%s\n' "ERROR: nom de role runtime invalide." >&2
        exit 1
    fi
done
if [[ "$PGVECTOR_RETRIEVAL_USER" == "$PGVECTOR_REVIEW_USER" \
   || "$PGVECTOR_RETRIEVAL_USER" == "$POSTGRES_USER" \
   || "$PGVECTOR_REVIEW_USER" == "$POSTGRES_USER" ]]; then
    printf '%s\n' "ERROR: les trois roles PostgreSQL doivent etre distincts." >&2
    exit 1
fi
for password in "$PGVECTOR_RETRIEVAL_PASSWORD" "$PGVECTOR_REVIEW_PASSWORD"; do
    if (( ${#password} < 32 )); then
        printf '%s\n' "ERROR: mot de passe runtime trop court (32 caracteres minimum)." >&2
        exit 1
    fi
done

# \getenv évite de placer les secrets sur la ligne de commande de psql. Les
# identifiants et littéraux sont ensuite quotés par psql avant envoi au serveur.
psql \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --set ON_ERROR_STOP=1 <<'SQL'
\getenv database_name POSTGRES_DB
\getenv retrieval_user PGVECTOR_RETRIEVAL_USER
\getenv retrieval_password PGVECTOR_RETRIEVAL_PASSWORD
\getenv review_user PGVECTOR_REVIEW_USER
\getenv review_password PGVECTOR_REVIEW_PASSWORD

BEGIN;

REVOKE ALL PRIVILEGES ON DATABASE :"database_name" FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE ROLE :"retrieval_user"
    LOGIN PASSWORD :'retrieval_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
GRANT CONNECT ON DATABASE :"database_name" TO :"retrieval_user";
GRANT USAGE ON SCHEMA public TO :"retrieval_user";
GRANT USAGE ON TYPE vector TO :"retrieval_user";
GRANT SELECT ON TABLE rag_chunks TO :"retrieval_user";
GRANT SELECT ON TABLE rag_schema_migrations TO :"retrieval_user";
GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system() TO :"retrieval_user";

CREATE ROLE :"review_user"
    LOGIN PASSWORD :'review_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
GRANT CONNECT ON DATABASE :"database_name" TO :"review_user";
GRANT USAGE ON SCHEMA public TO :"review_user";
GRANT USAGE ON TYPE vector TO :"review_user";
GRANT SELECT ON TABLE rag_chunks TO :"review_user";
GRANT UPDATE (review_status) ON TABLE rag_chunks TO :"review_user";
GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system() TO :"review_user";

COMMIT;
SQL
