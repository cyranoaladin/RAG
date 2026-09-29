#!/usr/bin/env bash
# Provisionnement CIBLÉ du seul rôle ingestion_control_adopter (adoption V2).
#
# Chemin distinct de provision_ingestion_control_roles.sh : celui-ci réaligne
# les mots de passe, attributs et appartenances des quatre rôles historiques.
# Ce script ne touche QUE le rôle adopter :
#   - rôle absent : CREATE ROLE avec le vérificateur SCRAM fourni ;
#   - rôle présent : réalignement des attributs de moindre privilège, SANS
#     mot de passe — jamais de rotation (la cohérence du secret conservé est
#     vérifiée par l'appelant, par une connexion réelle) ;
#   - appartenances de l'adopter révoquées ; droits identiques au bloc adopter
#     de provision_ingestion_control_roles.sh (preuve : test de parité).
#
# Le mot de passe en clair n'atteint jamais le serveur : l'appelant fournit un
# vérificateur SCRAM-SHA-256 calculé côté client
# (INGESTION_CONTROL_ADOPTER_PASSWORD_VERIFIER), transmis à psql par
# ``\getenv`` — jamais en argument. La journalisation des instructions est en
# outre coupée pour la transaction (SET LOCAL, superutilisateur requis).
#
# Le rôle est global au cluster ; ses privilèges de données sont bornés à la
# base PGDATABASE (CONNECT, schéma ingestion_control).
#
# Usage : PGHOST=... PGPORT=... PGDATABASE=... PGUSER=<superutilisateur> PGPASSWORD=... \
#         INGESTION_CONTROL_ADOPTER_PASSWORD_VERIFIER='SCRAM-SHA-256$4096:...' \
#         ./scripts/provision_ingestion_control_adopter_role.sh
set -euo pipefail

: "${PGHOST:?PGHOST must be set}"
: "${PGDATABASE:?PGDATABASE must be set}"
: "${PGUSER:?PGUSER must be set}"
: "${INGESTION_CONTROL_ADOPTER_PASSWORD_VERIFIER:?INGESTION_CONTROL_ADOPTER_PASSWORD_VERIFIER must be set}"

ADOPTER_ROLE="${INGESTION_CONTROL_ADOPTER_ROLE:-ingestion_control_adopter}"
if [[ ! "$ADOPTER_ROLE" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; then
    printf 'ERROR: invalid PostgreSQL role name: %s\n' "$ADOPTER_ROLE" >&2
    exit 1
fi
if [[ "$ADOPTER_ROLE" == "$PGUSER" ]]; then
    printf 'ERROR: ADOPTER_ROLE must not equal PGUSER (%s)\n' "$PGUSER" >&2
    exit 1
fi
# Un mot de passe en clair ne doit jamais partir vers le serveur.
if [[ ! "$INGESTION_CONTROL_ADOPTER_PASSWORD_VERIFIER" =~ ^SCRAM-SHA-256\$[0-9]+:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+$ ]]; then
    echo "ERROR: INGESTION_CONTROL_ADOPTER_PASSWORD_VERIFIER is not a SCRAM-SHA-256 verifier" >&2
    exit 1
fi
export ADOPTER_ROLE INGESTION_CONTROL_ADOPTER_PASSWORD_VERIFIER

psql -X -q --single-transaction -v ON_ERROR_STOP=1 <<'SQL'
SET LOCAL log_statement = 'none';
SET LOCAL log_min_duration_statement = -1;
SET LOCAL log_min_error_statement = 'panic';
\getenv adopter_role ADOPTER_ROLE
\getenv adopter_verifier INGESTION_CONTROL_ADOPTER_PASSWORD_VERIFIER

SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L', :'adopter_role', :'adopter_verifier')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'adopter_role')
\gexec

-- Rôle déjà présent : attributs réalignés, mot de passe INCHANGÉ.
SELECT format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS', :'adopter_role')
\gexec

SELECT format('REVOKE %I FROM %I', g.rolname, :'adopter_role')
FROM pg_auth_members m
JOIN pg_roles g ON g.oid = m.roleid
WHERE m.member = (SELECT oid FROM pg_roles WHERE rolname = :'adopter_role')
\gexec

-- Droits identiques au bloc adopter de provision_ingestion_control_roles.sh.
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'adopter_role')
\gexec
GRANT USAGE ON SCHEMA ingestion_control TO :"adopter_role" ;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA ingestion_control FROM :"adopter_role" ;
GRANT SELECT, INSERT ON ingestion_control.ingestion_runs TO :"adopter_role" ;
GRANT SELECT, INSERT ON ingestion_control.resources TO :"adopter_role" ;
GRANT SELECT, INSERT ON ingestion_control.artifacts TO :"adopter_role" ;
GRANT SELECT, INSERT ON ingestion_control.workflow_events TO :"adopter_role" ;
GRANT SELECT, INSERT ON ingestion_control.artifact_attributions TO :"adopter_role" ;
GRANT SELECT, INSERT ON ingestion_control.sealed_release_adoptions TO :"adopter_role" ;
GRANT SELECT ON ingestion_control.scope_authorizations TO :"adopter_role" ;
GRANT EXECUTE ON FUNCTION ingestion_control.artifact_attribution_digest(
    uuid, text, boolean, text, text) TO :"adopter_role" ;
REVOKE UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA ingestion_control FROM :"adopter_role" ;
REVOKE ALL PRIVILEGES ON SCHEMA public FROM :"adopter_role" ;
SQL

echo "ADOPTER_ROLE_PROVISIONED role=$ADOPTER_ROLE database=$PGDATABASE"
