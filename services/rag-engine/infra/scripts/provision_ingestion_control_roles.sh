#!/usr/bin/env bash
# Provisionnement des rôles PostgreSQL du schéma ingestion_control (LOT44b,
# décision D1 : rôles et privilèges séparés du rôle applicatif rag-engine).
#
# Deux rôles, jamais confondus :
#   - rôle de migration (INGESTION_CONTROL_MIGRATOR_ROLE) : seul habilité à
#     créer/modifier le schéma (via bootstrap_ingestion_control_schema.sh) ;
#   - rôle runtime (INGESTION_CONTROL_APP_ROLE) : seul utilisé par la couche
#     Python de primitives de concurrence — privilèges minimaux, table par
#     table, et protection append-only réelle de workflow_events
#     (REVOKE UPDATE, DELETE — jamais seulement une convention applicative).
#
# Aucun mot de passe codé en dur : les deux mots de passe sont exigés en
# variables d'environnement (échec explicite si absentes) et transmis à
# psql via des variables liées (jamais interpolés dans une chaîne SQL par
# concaténation Python/bash).
#
# Note d'implémentation : la substitution de variable psql (:'var') ne
# s'applique jamais à l'intérieur d'un corps délimité par $$ ... $$ (DO/
# fonctions) — c'est un comportement documenté de psql, pas un bug. Ce
# script utilise donc le motif \gexec (générer le DDL comme donnée via un
# SELECT classique où :'var' fonctionne, puis l'exécuter) plutôt que des
# blocs DO$$ pour tout ce qui nécessite une substitution.
#
# Usage : PGHOST=... PGPORT=... \
#         PGUSER=<rôle administratif externe, ex. superutilisateur du \
#                 conteneur — seul celui-ci a besoin de CREATEROLE ; ni \
#                 le rôle de migration ni le rôle runtime n'en reçoivent> \
#         PGPASSWORD=... PGDATABASE=... \
#         INGESTION_CONTROL_MIGRATOR_PASSWORD=... \
#         INGESTION_CONTROL_APP_PASSWORD=... \
#         ./scripts/provision_ingestion_control_roles.sh
set -euo pipefail

: "${PGHOST:?PGHOST must be set}"
: "${PGDATABASE:?PGDATABASE must be set}"
: "${PGUSER:?PGUSER must be set}"
: "${INGESTION_CONTROL_MIGRATOR_PASSWORD:?INGESTION_CONTROL_MIGRATOR_PASSWORD must be set}"
: "${INGESTION_CONTROL_APP_PASSWORD:?INGESTION_CONTROL_APP_PASSWORD must be set}"

MIGRATOR_ROLE="${INGESTION_CONTROL_MIGRATOR_ROLE:-ingestion_control_migrator}"
APP_ROLE="${INGESTION_CONTROL_APP_ROLE:-ingestion_control_app}"

psql -X -q --single-transaction -v ON_ERROR_STOP=1 \
    -v "migrator_role=$MIGRATOR_ROLE" \
    -v "app_role=$APP_ROLE" \
    -v "migrator_password=$INGESTION_CONTROL_MIGRATOR_PASSWORD" \
    -v "app_password=$INGESTION_CONTROL_APP_PASSWORD" <<'SQL'
-- Créer ou faire évoluer le mot de passe des deux rôles, idempotent.
--
-- CREATEROLE n'est PAS accordé au rôle de migration : la création des deux
-- rôles eux-mêmes est faite ici par la connexion administrative externe
-- ($PGUSER, superutilisateur du conteneur), jamais par le rôle de
-- migration lui-même. Ce dernier n'a besoin que d'être propriétaire du
-- schéma ingestion_control (ALTER SCHEMA ... OWNER TO, ci-dessous) pour
-- exécuter les migrations (CREATE TABLE/INDEX/CONSTRAINT) : la propriété
-- d'un schéma suffit intrinsèquement à y créer des objets, sans qu'aucun
-- privilège de gestion des rôles ne soit nécessaire. Un examen a confirmé
-- qu'aucun script de ce lot n'exerce jamais CREATEROLE depuis le rôle de
-- migration — accordé initialement "au cas où", supprimé ici comme
-- privilège excessif non justifié (cf. ADR-0027).
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L', :'migrator_role', :'migrator_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migrator_role')
\gexec

SELECT format('ALTER ROLE %I PASSWORD %L', :'migrator_role', :'migrator_password')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migrator_role')
\gexec

SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L', :'app_role', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_role')
\gexec

SELECT format('ALTER ROLE %I PASSWORD %L', :'app_role', :'app_password')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_role')
\gexec

-- Rôle de migration : seul habilité à créer/modifier le schéma. Ne reçoit
-- aucun privilège de données au-delà de ce qui est nécessaire pour créer
-- des objets — propriété du schéma suffit pour exécuter les migrations.
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'migrator_role')
\gexec

SELECT 'CREATE SCHEMA ingestion_control AUTHORIZATION ' || quote_ident(current_user)
WHERE NOT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'ingestion_control')
\gexec

SELECT format('ALTER SCHEMA ingestion_control OWNER TO %I', :'migrator_role')
\gexec

-- Rôle runtime : aucun privilège hérité par défaut, tout accordé
-- explicitement, table par table.
REVOKE ALL PRIVILEGES ON SCHEMA ingestion_control FROM PUBLIC;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA ingestion_control FROM PUBLIC;

SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'app_role')
\gexec

GRANT USAGE ON SCHEMA ingestion_control TO :"app_role" ;

GRANT SELECT, INSERT, UPDATE ON ingestion_control.ingestion_runs TO :"app_role" ;
GRANT SELECT, INSERT, UPDATE ON ingestion_control.resources TO :"app_role" ;
GRANT SELECT, INSERT, UPDATE ON ingestion_control.resource_candidates TO :"app_role" ;
GRANT SELECT, INSERT, UPDATE ON ingestion_control.artifacts TO :"app_role" ;
GRANT SELECT, INSERT, UPDATE ON ingestion_control.jobs TO :"app_role" ;

-- Protection append-only réelle : INSERT/SELECT uniquement, jamais
-- UPDATE/DELETE — appliquée au niveau du privilège SQL, pas seulement par
-- convention côté application (LOT44a, ADR-0026, décision 5).
GRANT SELECT, INSERT ON ingestion_control.workflow_events TO :"app_role" ;
REVOKE UPDATE, DELETE, TRUNCATE ON ingestion_control.workflow_events FROM :"app_role" ;

-- Aucune écriture directe dans rag_chunks/public depuis le rôle runtime
-- ingestion_control — vérifié explicitement, jamais supposé.
REVOKE ALL PRIVILEGES ON SCHEMA public FROM :"app_role" ;
SQL

echo "ROLES_PROVISIONED=1"
echo "MIGRATOR_ROLE=$MIGRATOR_ROLE"
echo "APP_ROLE=$APP_ROLE"
