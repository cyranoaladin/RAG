#!/usr/bin/env bash
# Provisionnement des rôles PostgreSQL du schéma ingestion_control (LOT44b,
# décision D1 : rôles et privilèges séparés du rôle applicatif rag-engine).
#
# Quatre rôles, jamais confondus :
#   - rôle de migration (INGESTION_CONTROL_MIGRATOR_ROLE) : seul habilité à
#     créer/modifier le schéma (via bootstrap_ingestion_control_schema.sh) ;
#   - rôle runtime (INGESTION_CONTROL_APP_ROLE) : seul utilisé par la couche
#     Python de primitives de concurrence — privilèges minimaux, table par
#     table, et protection append-only réelle de workflow_events
#     (REVOKE UPDATE, DELETE — jamais seulement une convention applicative) ;
#   - rôle d'autorité de scope (INGESTION_CONTROL_AUTHORITY_ROLE, LOT41A,
#     ADR-0032) : seul habilité à écrire dans scope_authorizations, via
#     authorize_scope_cli.py — jamais le rôle runtime, qui ne peut jamais
#     s'auto-écrire une autorisation ;
#   - rôle d'attestation de publication (INGESTION_CONTROL_ATTESTOR_ROLE,
#     LOT42, ADR-0033) : seul habilité à écrire dans
#     publication_attestations, via attest_publication_cli.py et le worker
#     pour les attestations déterministes — distinct du rôle d'autorité.
#
# Aucun mot de passe codé en dur : les quatre mots de passe sont exigés en
# variables d'environnement (échec explicite si absentes) et transmis à
# psql via ``\getenv`` (jamais visibles dans les arguments du processus
# psql — remédiation revue PR#90, même motif que
# ``infra/postgres/provision_runtime_roles.sh``) — jamais interpolés dans
# une chaîne SQL par concaténation Python/bash.
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
#                 conteneur — seul celui-ci a besoin de CREATEROLE ; aucun \
#                 des quatre rôles gouvernés n'en reçoit> \
#         PGPASSWORD=... PGDATABASE=... \
#         INGESTION_CONTROL_MIGRATOR_PASSWORD=... \
#         INGESTION_CONTROL_APP_PASSWORD=... \
#         INGESTION_CONTROL_AUTHORITY_PASSWORD=... \
#         INGESTION_CONTROL_ATTESTOR_PASSWORD=... \
#         ./scripts/provision_ingestion_control_roles.sh
set -euo pipefail

: "${PGHOST:?PGHOST must be set}"
: "${PGDATABASE:?PGDATABASE must be set}"
: "${PGUSER:?PGUSER must be set}"
: "${INGESTION_CONTROL_MIGRATOR_PASSWORD:?INGESTION_CONTROL_MIGRATOR_PASSWORD must be set}"
: "${INGESTION_CONTROL_APP_PASSWORD:?INGESTION_CONTROL_APP_PASSWORD must be set}"
: "${INGESTION_CONTROL_AUTHORITY_PASSWORD:?INGESTION_CONTROL_AUTHORITY_PASSWORD must be set}"
: "${INGESTION_CONTROL_ATTESTOR_PASSWORD:?INGESTION_CONTROL_ATTESTOR_PASSWORD must be set}"

MIGRATOR_ROLE="${INGESTION_CONTROL_MIGRATOR_ROLE:-ingestion_control_migrator}"
APP_ROLE="${INGESTION_CONTROL_APP_ROLE:-ingestion_control_app}"
AUTHORITY_ROLE="${INGESTION_CONTROL_AUTHORITY_ROLE:-ingestion_control_authority}"
ATTESTOR_ROLE="${INGESTION_CONTROL_ATTESTOR_ROLE:-ingestion_control_attestor}"
export MIGRATOR_ROLE APP_ROLE AUTHORITY_ROLE ATTESTOR_ROLE

# Remédiation revue PR#90 : un rôle mal formé (guillemet, espace) échoue
# maintenant explicitement avant tout accès base, jamais interpolé tel quel.
for role in "$MIGRATOR_ROLE" "$APP_ROLE" "$AUTHORITY_ROLE" "$ATTESTOR_ROLE"; do
    if [[ ! "$role" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; then
        printf 'ERROR: invalid PostgreSQL role name: %s\n' "$role" >&2
        exit 1
    fi
done
# Remédiation revue PR#90 (Cubic P1) : INGESTION_CONTROL_APP_ROLE identique
# à INGESTION_CONTROL_MIGRATOR_ROLE donnerait au rôle runtime la propriété
# du schéma (ALTER SCHEMA ... OWNER TO ci-dessous) et annulerait la
# protection append-only de workflow_events — rejeté avant toute écriture.
# Étendu (LOT41A/LOT42) : les quatre rôles doivent être deux à deux
# distincts, pour la même raison — un rôle non distinct hériterait
# silencieusement des privilèges (ou de la propriété de schéma) d'un autre
# rôle gouverné, contredisant le principe de moindre privilège que ce
# script est censé garantir pour chacun d'eux indépendamment.
all_roles=("$MIGRATOR_ROLE" "$APP_ROLE" "$AUTHORITY_ROLE" "$ATTESTOR_ROLE")
all_role_names=(MIGRATOR_ROLE APP_ROLE AUTHORITY_ROLE ATTESTOR_ROLE)
for ((i = 0; i < ${#all_roles[@]}; i++)); do
    for ((j = i + 1; j < ${#all_roles[@]}; j++)); do
        if [[ "${all_roles[$i]}" == "${all_roles[$j]}" ]]; then
            printf 'ERROR: %s and %s must be distinct (both resolve to %s).\n' \
                "${all_role_names[$i]}" "${all_role_names[$j]}" "${all_roles[$i]}" >&2
            exit 1
        fi
    done
done
# Remédiation revue PR#90 (Cubic P1, revue incrémentale) : PGUSER est la
# connexion administrative externe (superutilisateur du conteneur) qui
# exécute CE script — jamais l'un des rôles gouvernés eux-mêmes. Si l'un
# des quatre rôles résolvait à la même valeur que PGUSER, l'ALTER ROLE ...
# NOSUPERUSER NOCREATEDB NOCREATEROLE ... ci-dessous s'appliquerait au
# compte administratif utilisé pour se connecter, lui retirant ses propres
# privilèges en cours de script (auto-verrouillage) et brouillant la
# distinction stricte "connexion administrative externe" vs "rôle gouverné"
# que ce script est censé garantir. Rejeté avant toute écriture.
for ((i = 0; i < ${#all_roles[@]}; i++)); do
    if [[ "${all_roles[$i]}" == "$PGUSER" ]]; then
        printf 'ERROR: %s must not equal PGUSER (both resolve to %s) — PGUSER is the external administrative connection, never one of the governed roles it provisions.\n' \
            "${all_role_names[$i]}" "$PGUSER" >&2
        exit 1
    fi
done

psql -X -q --single-transaction -v ON_ERROR_STOP=1 <<'SQL'
\getenv migrator_role MIGRATOR_ROLE
\getenv app_role APP_ROLE
\getenv authority_role AUTHORITY_ROLE
\getenv attestor_role ATTESTOR_ROLE
\getenv migrator_password INGESTION_CONTROL_MIGRATOR_PASSWORD
\getenv app_password INGESTION_CONTROL_APP_PASSWORD
\getenv authority_password INGESTION_CONTROL_AUTHORITY_PASSWORD
\getenv attestor_password INGESTION_CONTROL_ATTESTOR_PASSWORD

-- Créer ou faire évoluer les deux rôles, idempotent.
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

-- Remédiation revue PR#90 (Cubic P1) : sur un rôle déjà existant, réaligne
-- aussi ses attributs de moindre privilège — pas seulement le mot de
-- passe. Sans cela, un rôle laissé NOLOGIN par une intervention externe
-- ferait échouer le runtime, et un rôle laissé SUPERUSER/CREATEDB/
-- CREATEROLE/REPLICATION/BYPASSRLS contournerait les protections
-- ci-dessous — cet ALTER ROLE échoue explicitement ce script si le rôle
-- dérive de la politique attendue plutôt que de le laisser silencieusement
-- privilégié.
SELECT format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L', :'migrator_role', :'migrator_password')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'migrator_role')
\gexec

SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L', :'app_role', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_role')
\gexec

SELECT format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L', :'app_role', :'app_password')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_role')
\gexec

-- Rôle d'autorité de scope (LOT41A, ADR-0032) et rôle d'attestation de
-- publication (LOT42, ADR-0033) — même politique de moindre privilège que
-- migrator/app ci-dessus, créés/alignés ici pour la même raison.
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L', :'authority_role', :'authority_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'authority_role')
\gexec

SELECT format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L', :'authority_role', :'authority_password')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'authority_role')
\gexec

SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L', :'attestor_role', :'attestor_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'attestor_role')
\gexec

SELECT format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L', :'attestor_role', :'attestor_password')
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'attestor_role')
\gexec

-- Remédiation revue PR#90 (Cubic P1, revue incrémentale) : ni MIGRATOR_ROLE
-- ni APP_ROLE ne doivent jamais rester membres d'un autre rôle. NOINHERIT
-- (ci-dessus) empêche seulement l'héritage *automatique* des privilèges
-- d'un rôle dont on est membre — l'appartenance seule permet toujours un
-- `SET ROLE` explicite vers ce rôle, une voie d'escalade que ce script ne
-- peut jamais laisser en place silencieusement pour un rôle censé rester à
-- privilège strictement minimal (ex. une intervention manuelle antérieure
-- qui aurait fait `GRANT some_privileged_role TO ingestion_control_app`).
-- Toute appartenance préexistante est donc révoquée inconditionnellement
-- ici (fail-closed par suppression réelle, pas par simple détection qui
-- laisserait la dérive en place) — ce script n'accorde lui-même aucune
-- appartenance à un autre rôle, donc toute appartenance trouvée ici est
-- par construction non autorisée.
SELECT format('REVOKE %I FROM %I', g.rolname, :'migrator_role')
FROM pg_auth_members m
JOIN pg_roles g ON g.oid = m.roleid
WHERE m.member = (SELECT oid FROM pg_roles WHERE rolname = :'migrator_role')
\gexec

SELECT format('REVOKE %I FROM %I', g.rolname, :'app_role')
FROM pg_auth_members m
JOIN pg_roles g ON g.oid = m.roleid
WHERE m.member = (SELECT oid FROM pg_roles WHERE rolname = :'app_role')
\gexec

SELECT format('REVOKE %I FROM %I', g.rolname, :'authority_role')
FROM pg_auth_members m
JOIN pg_roles g ON g.oid = m.roleid
WHERE m.member = (SELECT oid FROM pg_roles WHERE rolname = :'authority_role')
\gexec

SELECT format('REVOKE %I FROM %I', g.rolname, :'attestor_role')
FROM pg_auth_members m
JOIN pg_roles g ON g.oid = m.roleid
WHERE m.member = (SELECT oid FROM pg_roles WHERE rolname = :'attestor_role')
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

-- LOT41A/LOT42 (ADR-0032/ADR-0033) : le worker (app_role) doit pouvoir LIRE
-- scope_authorizations/publication_attestations pour exécuter lui-même la
-- vérification live (verify_scope_authorization/verify_publication_
-- attestation, appelées avec sa propre connexion) — jamais y écrire : seul
-- un opérateur humain, via authorize_scope_cli.py/attest_publication_cli.py
-- (rôles authority_role/attestor_role dédiés ci-dessus), en a le droit.
GRANT SELECT ON ingestion_control.scope_authorizations TO :"app_role" ;
GRANT SELECT ON ingestion_control.publication_attestations TO :"app_role" ;

-- Aucune écriture directe dans rag_chunks/public depuis le rôle runtime
-- ingestion_control — vérifié explicitement, jamais supposé.
REVOKE ALL PRIVILEGES ON SCHEMA public FROM :"app_role" ;

-- Rôle d'autorité de scope (LOT41A) : écriture réservée à
-- scope_authorizations, aucune autre table de ce schéma — le worker
-- (app_role) ne reçoit jamais ce privilège, et ce rôle ne reçoit jamais les
-- privilèges du worker (aucun accès à resources/jobs/workflow_events).
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'authority_role')
\gexec

GRANT USAGE ON SCHEMA ingestion_control TO :"authority_role" ;
GRANT SELECT, INSERT ON ingestion_control.scope_authorizations TO :"authority_role" ;
-- Seules les onze colonnes de révocation sont modifiables après écriture
-- (même frontière GitHub que l'octroi, sur une PR de révocation dédiée,
-- ADR-0032 § 3) — toute autre colonne d'une autorisation déjà écrite reste
-- immuable, y compris pour ce rôle : GRANT UPDATE de colonne, jamais
-- UPDATE de table.
GRANT UPDATE (
    revoked_at, revoked_by, revocation_reason,
    revocation_evidence_repository, revocation_evidence_pull_request,
    revocation_evidence_base_sha, revocation_evidence_head_sha,
    revocation_evidence_review_id, revocation_evidence_reviewer,
    revocation_evidence_submitted_at, revocation_evidence_challenge
) ON ingestion_control.scope_authorizations TO :"authority_role" ;
REVOKE DELETE, TRUNCATE ON ingestion_control.scope_authorizations FROM :"authority_role" ;
REVOKE ALL PRIVILEGES ON SCHEMA public FROM :"authority_role" ;

-- Rôle d'attestation de publication (LOT42) : écriture réservée à
-- publication_attestations, plus lecture seule de scope_authorizations
-- (revérification en direct du scope référencé, ADR-0033 § 4) et de
-- resources/artifacts/resource_candidates (attest_publication_cli.py en
-- dérive collection/content_sha256/canonical_url — jamais acceptés en
-- argument opérateur libre, cf. docstring du CLI) — jamais d'écriture sur
-- aucune de ces quatre tables depuis ce rôle.
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'attestor_role')
\gexec

GRANT USAGE ON SCHEMA ingestion_control TO :"attestor_role" ;
GRANT SELECT, INSERT ON ingestion_control.publication_attestations TO :"attestor_role" ;
-- Seules invalidated_at/invalidated_reason sont modifiables après
-- écriture (audit d'une invalidation détectée en direct, ADR-0033 § 4) —
-- toute autre colonne d'une attestation déjà écrite reste immuable, y
-- compris pour ce rôle : GRANT UPDATE de colonne, jamais UPDATE de table.
GRANT UPDATE (invalidated_at, invalidated_reason)
    ON ingestion_control.publication_attestations TO :"attestor_role" ;
REVOKE DELETE, TRUNCATE ON ingestion_control.publication_attestations FROM :"attestor_role" ;
GRANT SELECT ON ingestion_control.scope_authorizations TO :"attestor_role" ;
GRANT SELECT ON ingestion_control.resources TO :"attestor_role" ;
GRANT SELECT ON ingestion_control.artifacts TO :"attestor_role" ;
GRANT SELECT ON ingestion_control.resource_candidates TO :"attestor_role" ;
-- Remédiation GATE H1 (items E et K) : les faits durables de publication
-- (résultat des droits, de la qualité, du gate) vivent dans
-- workflow_events. Sans cette LECTURE, le conteneur d'attestation devrait
-- recevoir en plus le DSN du worker pour les lire — exactement le cumul de
-- credentials que l'isolation des rôles doit empêcher. SELECT seul :
-- l'append-only de workflow_events reste intact (aucun INSERT/UPDATE/DELETE
-- pour ce rôle, contrairement au worker qui y écrit).
GRANT SELECT ON ingestion_control.workflow_events TO :"attestor_role" ;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ingestion_control.workflow_events FROM :"attestor_role" ;
REVOKE ALL PRIVILEGES ON SCHEMA public FROM :"attestor_role" ;
SQL

echo "ROLES_PROVISIONED=1"
echo "MIGRATOR_ROLE=$MIGRATOR_ROLE"
echo "APP_ROLE=$APP_ROLE"
echo "AUTHORITY_ROLE=$AUTHORITY_ROLE"
echo "ATTESTOR_ROLE=$ATTESTOR_ROLE"
