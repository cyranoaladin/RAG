#!/usr/bin/env bash
# Provisionner ou réconcilier les identités runtime avec le moindre privilège.
set -euo pipefail

validate_runtime_role_environment() {
    local variable role password
    local -a required_variables=(
        POSTGRES_USER
        PGVECTOR_RETRIEVAL_USER
        PGVECTOR_RETRIEVAL_PASSWORD
        PGVECTOR_REVIEW_USER
        PGVECTOR_REVIEW_PASSWORD
        PGVECTOR_PUBLISHER_USER
        PGVECTOR_PUBLISHER_PASSWORD
    )
    for variable in "${required_variables[@]}"; do
        if [[ -z "${!variable:-}" ]]; then
            printf 'ERROR: %s requis pour provisionner les roles runtime.\n' \
                "$variable" >&2
            return 1
        fi
    done

    POSTGRES_DB="${POSTGRES_DB:-$POSTGRES_USER}"
    export POSTGRES_DB

    for role in \
        "$PGVECTOR_RETRIEVAL_USER" \
        "$PGVECTOR_REVIEW_USER" \
        "$PGVECTOR_PUBLISHER_USER"; do
        if [[ ! "$role" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; then
            printf '%s\n' "ERROR: nom de role runtime invalide." >&2
            return 1
        fi
    done
    if [[ "$PGVECTOR_RETRIEVAL_USER" == "$PGVECTOR_REVIEW_USER" \
       || "$PGVECTOR_RETRIEVAL_USER" == "$PGVECTOR_PUBLISHER_USER" \
       || "$PGVECTOR_REVIEW_USER" == "$PGVECTOR_PUBLISHER_USER" \
       || "$PGVECTOR_RETRIEVAL_USER" == "$POSTGRES_USER" \
       || "$PGVECTOR_REVIEW_USER" == "$POSTGRES_USER" \
       || "$PGVECTOR_PUBLISHER_USER" == "$POSTGRES_USER" ]]; then
        printf '%s\n' "ERROR: les quatre roles PostgreSQL doivent etre distincts." >&2
        return 1
    fi
    for password in \
        "$PGVECTOR_RETRIEVAL_PASSWORD" \
        "$PGVECTOR_REVIEW_PASSWORD" \
        "$PGVECTOR_PUBLISHER_PASSWORD"; do
        if (( ${#password} < 32 )); then
            printf '%s\n' \
                "ERROR: mot de passe runtime trop court (32 caracteres minimum)." \
                >&2
            return 1
        fi
    done
}

provision_runtime_roles_sql() {
    # \getenv évite de placer les secrets sur la ligne de commande de psql.
    # Les CREATE conditionnels rendent la projection rejouable sur un volume
    # existant; ALTER réimpose les attributs de moindre privilège sans changer
    # le mot de passe d'un rôle déjà provisionné.
    cat <<'SQL'
\getenv database_name POSTGRES_DB
\getenv retrieval_user PGVECTOR_RETRIEVAL_USER
\getenv retrieval_password PGVECTOR_RETRIEVAL_PASSWORD
\getenv review_user PGVECTOR_REVIEW_USER
\getenv review_password PGVECTOR_REVIEW_PASSWORD
\getenv publisher_user PGVECTOR_PUBLISHER_USER
\getenv publisher_password PGVECTOR_PUBLISHER_PASSWORD

REVOKE ALL PRIVILEGES ON DATABASE :"database_name" FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

SELECT format(
    'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
    :'retrieval_user', :'retrieval_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'retrieval_user')
\gexec
SELECT format(
    'ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
    :'retrieval_user'
)
\gexec
GRANT CONNECT ON DATABASE :"database_name" TO :"retrieval_user";
GRANT USAGE ON SCHEMA public TO :"retrieval_user";
GRANT USAGE ON TYPE vector TO :"retrieval_user";
GRANT SELECT ON TABLE rag_chunks, rag_artifacts, rag_artifact_placements
    TO :"retrieval_user";
GRANT SELECT ON TABLE rag_schema_migrations TO :"retrieval_user";
GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system() TO :"retrieval_user";

SELECT format(
    'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
    :'review_user', :'review_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'review_user')
\gexec
SELECT format(
    'ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
    :'review_user'
)
\gexec
GRANT CONNECT ON DATABASE :"database_name" TO :"review_user";
GRANT USAGE ON SCHEMA public TO :"review_user";
GRANT USAGE ON TYPE vector TO :"review_user";
GRANT SELECT ON TABLE rag_chunks TO :"review_user";
GRANT UPDATE (review_status) ON TABLE rag_chunks TO :"review_user";
GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system() TO :"review_user";

SELECT format(
    'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
    :'publisher_user', :'publisher_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'publisher_user')
\gexec
SELECT format(
    'ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
    :'publisher_user'
)
\gexec
GRANT CONNECT ON DATABASE :"database_name" TO :"publisher_user";
GRANT USAGE ON SCHEMA public TO :"publisher_user";
GRANT USAGE ON TYPE vector TO :"publisher_user";
GRANT SELECT, INSERT ON TABLE rag_artifacts TO :"publisher_user";
GRANT SELECT, INSERT ON TABLE rag_artifact_placements TO :"publisher_user";
GRANT SELECT, INSERT ON TABLE rag_chunks TO :"publisher_user";
SQL
}

main() {
    validate_runtime_role_environment
    provision_runtime_roles_sql | psql \
        --username "$POSTGRES_USER" \
        --dbname "$POSTGRES_DB" \
        --set ON_ERROR_STOP=1 \
        --single-transaction
}

if [[ -z "${BASH_SOURCE[0]-}" || "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
