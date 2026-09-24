#!/usr/bin/env bash
# Mesure, en LECTURE SEULE, l'état réel du staging cloisonné (lot CZ).
#
# Ne migre, n'attribue, n'adopte, n'ingère ni ne publie rien : le script
# distant n'appelle que hostname, df, docker ps/inspect et psql dans une
# session forcée en lecture seule (default_transaction_read_only=on). Une
# table absente est rapportée ABSENTE, une requête en échec ERREUR — jamais 0.
#
# Seule écriture : le rapport local, expurgé, dans $MESURE_DIR (0700/0600).
#
#   scripts/go_live/measure_staging_state.sh
set -euo pipefail

SSH_HOST="nexus-prod"
CONTAINER="nexus-staging-pgvector-1"
DB="ragdb"
MESURE_DIR="${MESURE_DIR:-$HOME/nexus-staging-measure}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
umask 077
install -d -m 0700 "$MESURE_DIR"
SORTIE="$MESURE_DIR/staging-state-$STAMP.txt"

ssh -o BatchMode=yes "$SSH_HOST" bash -s <<'DISTANT' \
    | sed -E -e 's#(postgres(ql)?://[^:/ ]+:)[^@ ]+@#\1***@#g' \
             -e 's#((PASSWORD|SECRET|TOKEN|KEY|DSN)[A-Z_]*=)[^ ]+#\1***#g' \
    > "$SORTIE"
set -uo pipefail
C=nexus-staging-pgvector-1
DB=ragdb
echo "HOST=$(hostname)"
echo "DATE_UTC=$(date -u +%FT%TZ)"
echo "DISK /srv/nexus-staging $(df -Pk /srv/nexus-staging 2>&1 | awk 'NR==2{print "total_kb="$2" free_kb="$4}')"
echo "--- conteneurs du projet nexus-staging"
docker ps -a --filter label=com.docker.compose.project=nexus-staging \
    --format 'CONTAINER {{.Names}} {{.Status}} {{.Image}}' 2>&1
echo "--- identité du conteneur PostgreSQL"
docker inspect "$C" --format 'ID={{.Id}} CREATED={{.Created}} IMAGE={{.Config.Image}}' 2>&1
docker inspect "$C" --format '{{range .Mounts}}MOUNT type={{.Type}} name={{.Name}} source={{.Source}} dest={{.Destination}}{{"\n"}}{{end}}' 2>&1
q() {  # $1 = libellé, $2 = requête ; lecture seule imposée à la session
    local out
    if out=$(docker exec -e PGOPTIONS='-c default_transaction_read_only=on' "$C" \
            sh -c "psql -X -At -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d $DB -c \"\$0\"" "$2" 2>&1); then
        printf '%s=%s\n' "$1" "$(printf '%s' "$out" | tr '\n' ';')"
    else
        printf '%s=ERREUR:%s\n' "$1" "$(printf '%s' "$out" | tr '\n' ' ' | cut -c1-200)"
    fi
}
t() {  # compte d'une table, ou ABSENTE
    q "$1" "select case when to_regclass('$1') is null then 'ABSENTE' else (select count(*)::text from $1) end"
}
echo "--- identité de la base"
q SESSION "select current_database()||' user='||current_user||' read_only='||current_setting('default_transaction_read_only')||' server_version='||current_setting('server_version')"
q SYSTEM_IDENTIFIER "select system_identifier from pg_control_system()"
q POSTMASTER_START "select pg_postmaster_start_time()"
q DATABASES "select string_agg(datname, ',' order by datname) from pg_database where not datistemplate"
q SCHEMAS "select string_agg(nspname, ',' order by nspname) from pg_namespace where nspname not like 'pg_%' and nspname <> 'information_schema'"
echo "--- têtes de migration"
q PRODUCT_HEAD "select case when to_regclass('public.rag_schema_migrations') is null then 'ABSENTE' else (select coalesce(max(version),0)::text from public.rag_schema_migrations) end"
q CONTROL_HEAD "select case when to_regclass('ingestion_control.schema_migrations') is null then 'ABSENTE' else (select coalesce(max(version),0)::text from ingestion_control.schema_migrations) end"
echo "--- plan de contrôle"
for tbl in ingestion_runs resources resource_candidates artifacts workflow_events jobs \
           scope_authorizations publication_attestations artifact_attributions \
           sealed_release_projections sealed_release_adoptions revoked_review_evidence; do
    t "ingestion_control.$tbl"
done
q RELEASES_IN_ARTIFACTS "select string_agg(r||':'||n, ',') from (select coalesce(payload->>'release_id','<sans>') r, count(*) n from ingestion_control.artifacts group by 1 order by 1) x"
q DISTINCT_CONTENT_IN_ARTIFACTS "select count(distinct sha256) from ingestion_control.artifacts"
q RESOURCE_STATES "select string_agg(s||':'||n, ',') from (select resource_state s, count(*) n from ingestion_control.resources group by 1 order by 1) x"
q RESOURCE_PIPELINES "select string_agg(k||':'||n, ',') from (select pipeline_kind k, count(*) n from ingestion_control.resources group by 1 order by 1) x"
q RUNS_BY_STATUS "select string_agg(s||':'||n, ',') from (select status s, count(*) n from ingestion_control.ingestion_runs group by 1 order by 1) x"
q JOBS_BY_STATUS "select string_agg(s||':'||n, ',') from (select status s, count(*) n from ingestion_control.jobs group by 1 order by 1) x"
q SCOPE_AUTHORIZATIONS "select string_agg(authorization_id||'/'||protocol_version||(case when revoked_at is null then '' else '/REVOKED' end), ',' order by authorization_id) from ingestion_control.scope_authorizations"
q ARTIFACT_AUTHORIZATIONS "select string_agg(a||':'||n, ',') from (select payload->>'scope_authorization_id' a, count(*) n from ingestion_control.artifacts group by 1 order by 1) x"
q LAST_EVENT "select max(created_at) from ingestion_control.workflow_events"
echo "--- base produit"
for tbl in public.rag_artifacts public.rag_artifact_placements public.rag_chunks; do t "$tbl"; done
q PRODUCT_PROGRAMMES "select string_agg(p||':'||n, ',') from (select programme_version p, count(*) n from public.rag_chunks group by 1 order by 1) x"
DISTANT
chmod 600 "$SORTIE"
sha256sum "$SORTIE"
cat "$SORTIE"
