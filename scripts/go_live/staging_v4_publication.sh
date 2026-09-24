#!/usr/bin/env bash
# Orchestrateur de la publication V4 sur le staging cloisonné (lots DB, DC).
#
# Plan : docs/runbooks/staging_v4_publication_EXECUTION_PLAN.md
# Chaque étape est d'abord soumise au vérificateur d'autorisation, sur sa cible
# exacte (tirée du vérificateur, jamais ressaisie ici). Premier écart : arrêt.
# Aucune commande canonique n'est réimplémentée : ce script les enchaîne, avec
# des arguments dérivés de la release par staging_v4_arguments.py.
#
# Base DÉDIÉE (lot DC) : V4 vit dans ``ragdb_profile_gate_v4``, créée
# additivement dans le cluster existant. ``ragdb`` (acquisition V2, placements
# pilotes) reste intacte : mesurée au pré-vol, revérifiée après chaque étape
# qui écrit. Tout contenu inattendu dans la base dédiée est un refus.
#
#   scripts/go_live/staging_v4_publication.sh [--dry-run] run [--until <étape>]
#   scripts/go_live/staging_v4_publication.sh status
#
# État et journal expurgé : $STATE_DIR (défaut ~/nexus-staging-v4-run, 0700).
# Reprise : une étape marquée faite n'est pas rejouée ; supprimer son marqueur
# ne la rejoue qu'après que sa commande canonique a revérifié son état (les
# commandes sont idempotentes : already_present, rejeu sans écriture).
# Création de la base interrompue : relancer le pré-vol (marqueur supprimé),
# qui constate une base dédiée VIERGE ; l'étape de création l'accepte alors.
set -euo pipefail

ROOT="${NEXUS_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$ROOT"
STATE_DIR="${STATE_DIR:-$HOME/nexus-staging-v4-run}"
# Interpréteur LOCAL (poste de l'opérateur) ; l'hôte garde son python3.
PYTHON="${PYTHON:-python3}"
SSH_HOST="${SSH_HOST:-nexus-prod}"
REMOTE="/srv/nexus-staging"
CONTAINER="nexus-staging-pgvector-1"
DB="ragdb_profile_gate_v4"
LEGACY_DB="ragdb"
AUTH_V4="docs/reports/go_live/authorizations/staging_v4_publication_authorization.json"
RUN="$REMOTE/run-db"
MODELE_NOM="e5-large-prerentree-2026-2027-20260828-materialise"
MODELE_INVENTAIRE="58ad18dbb0a154c5a10320de9efdf81944f8b1ee1a01cc7f077e8b86b364dbc6"
MODELE_LOCAL="${MODELE_LOCAL:-$HOME/rag-model-artifacts/$MODELE_NOM}"
# Manifeste de readiness signé localement (sign_staging_v4_readiness_manifests.sh).
READINESS_LOCAL="${READINESS_LOCAL:-$HOME/nexus-staging-v4-readiness}"
READINESS_MANIFESTE="staging-readiness-v4.json"
READINESS_REMOTE="$REMOTE/readiness"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && { DRY_RUN=1; shift; }
# Essai à blanc sans réseau (tests) : le contrôle d'autorisation n'est pas
# appelé. N'a AUCUN effet hors --dry-run.
HORS_LIGNE=0
[ "$DRY_RUN" = 1 ] && [ "${DRY_RUN_OFFLINE:-0}" = 1 ] && HORS_LIGNE=1

# Fichiers SOURCES de l'hôte (0600, jamais affichés, jamais montés dans un
# worker) : seules les étapes de migration et de dérivation les lisent.
REMOTE_STAGING_ENV="$REMOTE/secrets/staging.env"
REMOTE_CONTROL_SOURCE_ENV="$REMOTE/secrets/ingestion_control.env"
REMOTE_READINESS_ENV="$REMOTE/secrets/readiness.env"
# Fichiers PAR RÔLE, dérivés par l'étape role_env_derivation : les seuls que
# reçoivent les conteneurs.
REMOTE_ROLES="$REMOTE/secrets/v4-roles"
REMOTE_WORKER_ENV="$REMOTE_ROLES/ingestion-control-app.env"
REMOTE_ATTESTOR_ENV="$REMOTE_ROLES/ingestion-control-attestor.env"
REMOTE_AUTHORITY_ENV="$REMOTE_ROLES/ingestion-control-authority.env"
REMOTE_PUBLISHER_ENV="$REMOTE_ROLES/rag-publisher.env"
REMOTE_READER_ENV="$REMOTE_ROLES/rag-reader.env"
# Jeton GitHub en lecture : créé par le propriétaire après approbation.
REMOTE_GITHUB_TOKEN_FILE="$REMOTE/secrets/github-read-token/token"

install -d -m 0700 "$STATE_DIR"
LOG="$STATE_DIR/execution.log"

redact() {  # aucun secret ne passe dans le journal
    sed -E \
        -e "s#(password=)'([^'\\\\]|\\\\.)*'#\\1'***'#g" \
        -e 's#(password=)[^ '"'"']+#\1***#g' \
        -e 's#(postgres(ql)?://[^:/ ]+:)[^@ ]+@#\1***@#g' \
        -e 's#(gh[pousr]_|github_pat_)[A-Za-z0-9_]+#\1***#g' \
        -e 's#((PASSWORD|SECRET|TOKEN|KEY|DSN)[A-Z_]*=)[^ ]+#\1***#g'
}
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | redact | tee -a "$LOG" >&2; }
fail() { log "ARRET: $*"; exit 3; }

champ() {  # lit un champ de l'autorisation V4 par chemin pointé
    "$PYTHON" -c "
import json,sys
d=json.load(open('$AUTH_V4'))
for k in sys.argv[1].split('.'): d=d[k]
print(d)" "$1"
}
cible() {
    "$PYTHON" -c "
import json,sys; sys.path.insert(0,'scripts/go_live')
import check_staging_authorization as a
print(json.dumps(a.OPERATIONS_V4[sys.argv[1]]['cible'], sort_keys=True))" "$1"
}
autoriser() {
    local op="$1" sortie
    if [ "$HORS_LIGNE" = 1 ]; then
        log "SIMULATION: contrôle d'autorisation de $op non appelé (essai hors ligne)"; return 0
    fi
    if ! sortie=$("$PYTHON" scripts/go_live/check_staging_authorization.py \
            --operation "$op" --cible "$(cible "$op")" 2>&1); then
        log "$sortie"
        [ "$DRY_RUN" = 1 ] && { log "SIMULATION: $op serait refusée en réel"; return 0; }
        fail "$op non autorisée"
    fi
    log "AUTORISEE $op"
}
remote() {  # exécute sur l'hôte le script lu sur l'entrée standard
    if [ "$DRY_RUN" = 1 ]; then
        { echo "--- [dry-run] ssh $SSH_HOST bash -s"; cat; echo "---"; } | redact | tee -a "$LOG" >&2
        return 0
    fi
    ssh -o BatchMode=yes "$SSH_HOST" bash -s 2>&1 | redact | tee -a "$LOG"
    return "${PIPESTATUS[0]}"
}
fait() { [ -f "$STATE_DIR/$1.done" ]; }
marquer() { printf '%s\n' "$2" > "$STATE_DIR/$1.done"; log "FAIT $1 $2"; }
psql_ro() {  # $1 = base, $2 = requête ; lecture seule imposée par le serveur
    printf 'docker exec -e PGOPTIONS=%q %s sh -c %q\n' "-c default_transaction_read_only=on" "$CONTAINER" \
        "psql -v ON_ERROR_STOP=1 -X -At -U \"\$POSTGRES_USER\" -d $1 -c \"$2\""
}
args_de() {  # arguments canoniques, une ligne par argument, citée pour bash
    local sortie
    sortie=$("$PYTHON" scripts/go_live/staging_v4_arguments.py "$@") || fail "arguments refusés : $*"
    local -a tableau; mapfile -t tableau <<<"$sortie"
    printf '%q ' "${tableau[@]}"
}
transfert_sha() { sed -n 's/^sha256=//p' "$STATE_DIR/transfer_manifest_v4.done"; }

IMAGE="" ; SONDE="" ; AUTH_COMMIT=""
charger_autorisation() {
    [ -f "$AUTH_V4" ] || fail "autorisation V4 absente"
    IMAGE="$(champ runtime_image.reference)"
    SONDE="$(champ probe_image.reference)"
    AUTH_COMMIT="$(git log -1 --format=%H -- "$AUTH_V4")"
}

tirer() {  # l'image épinglée, et elle seule : le digest réel doit être le nommé
    cat <<EOF
docker image inspect "$1" >/dev/null 2>&1 || docker pull -q "$1"
test "\$(docker inspect --format '{{index .RepoDigests 0}}' "$1")" = "$1"
EOF
}

env_de_role() {  # refuse tout fichier qui n'est pas un fichier PAR RÔLE
    local f
    for f in "$@"; do
        case "$f" in
            "$REMOTE_ROLES"/*.env) ;;
            *) fail "fichier d'environnement hors des fichiers par rôle : $f" ;;
        esac
    done
}

jeton_present() {  # le jeton GitHub : présent, 0600, sous 0700 ; jamais lu ici
    cat <<EOF
test -s "$REMOTE_GITHUB_TOKEN_FILE" || { echo "JETON_GITHUB_ABSENT" >&2; exit 4; }
test "\$(stat -c %a "$REMOTE_GITHUB_TOKEN_FILE")" = 600 || { echo "JETON_GITHUB_MODE" >&2; exit 4; }
test "\$(stat -c %a "\$(dirname "$REMOTE_GITHUB_TOKEN_FILE")")" = 700 || { echo "JETON_GITHUB_DIR_MODE" >&2; exit 4; }
EOF
}

mesure_historique() {  # ragdb : têtes, comptes et empreintes des lignes existantes
    cat <<EOF
echo "LEGACY_PRODUCT_HEAD=\$($(psql_ro "$LEGACY_DB" "select coalesce(max(version),0) from public.rag_schema_migrations"))"
echo "LEGACY_CONTROL_HEAD=\$($(psql_ro "$LEGACY_DB" "select coalesce(max(version),0) from ingestion_control.schema_migrations"))"
echo "LEGACY_RESOURCES=\$($(psql_ro "$LEGACY_DB" "select count(*)||':'||md5(coalesce(string_agg(resource_id::text||resource_state||state_version, ',' order by resource_id),'')) from ingestion_control.resources"))"
echo "LEGACY_ARTIFACTS=\$($(psql_ro "$LEGACY_DB" "select count(*)||':'||md5(coalesce(string_agg(artifact_id::text||sha256, ',' order by artifact_id),'')) from ingestion_control.artifacts"))"
echo "LEGACY_PLACEMENTS=\$($(psql_ro "$LEGACY_DB" "select count(*)||':'||md5(coalesce(string_agg(placement_id||placement_status||currentness, ',' order by placement_id),'')) from public.rag_artifact_placements"))"
echo "LEGACY_CHUNKS=\$($(psql_ro "$LEGACY_DB" "select count(*)||':'||md5(coalesce(string_agg(chunk_id, ',' order by chunk_id),'')) from public.rag_chunks"))"
echo "LEGACY_SCOPE_AUTHORIZATIONS=\$($(psql_ro "$LEGACY_DB" "select count(*) from ingestion_control.scope_authorizations"))"
EOF
}

verifier_historique() {  # ragdb doit être EXACTEMENT celle du pré-vol
    local apres
    [ "$DRY_RUN" = 1 ] && { mesure_historique | remote >/dev/null; return 0; }
    apres=$( { echo "set -euo pipefail"; mesure_historique; } | remote) || fail "ragdb : mesure impossible"
    [ "$apres" = "$(cat "$STATE_DIR/legacy_baseline.txt")" ] \
        || fail "ragdb a changé depuis le pré-vol — arrêt de sécurité (voir legacy_baseline.txt)"
    log "RAGDB_INCHANGEE"
}

vide_cible() {  # la base dédiée : lignes de chaque table métier (0 si absente)
    cat <<'SQL'
select coalesce(sum(n),0) from (
  select case when to_regclass('public.rag_chunks') is null then 0 else (select count(*) from public.rag_chunks) end as n
  union all select case when to_regclass('public.rag_artifacts') is null then 0 else (select count(*) from public.rag_artifacts) end
  union all select case when to_regclass('public.rag_artifact_placements') is null then 0 else (select count(*) from public.rag_artifact_placements) end
  union all select case when to_regclass('ingestion_control.resources') is null then 0 else (select count(*) from ingestion_control.resources) end
  union all select case when to_regclass('ingestion_control.artifacts') is null then 0 else (select count(*) from ingestion_control.artifacts) end
  union all select case when to_regclass('ingestion_control.publication_attestations') is null then 0 else (select count(*) from ingestion_control.publication_attestations) end
) t
SQL
}

worker() {  # $1 = fichiers d'env PAR RÔLE (':') ; reste = module et arguments
    local manifeste="$READINESS_MANIFESTE" envs="" f sha
    sha=$(sha256sum "$READINESS_LOCAL/$manifeste" 2>/dev/null | cut -d' ' -f1) \
        || fail "manifeste de readiness local absent : $manifeste"
    IFS=: read -r -a _fichiers <<<"$1"; shift
    env_de_role "${_fichiers[@]}"
    for f in "${_fichiers[@]}"; do envs+="--env-file \"$f\" "; done
    cat <<EOF
set -euo pipefail
$(jeton_present)
docker image inspect "$IMAGE" >/dev/null 2>&1 || docker pull -q "$IMAGE"
IMAGE_REELLE=\$(docker inspect --format '{{index .RepoDigests 0}}' "$IMAGE")
test "\$IMAGE_REELLE" = "$IMAGE"
install -d -m 0700 $RUN
docker run --rm --network host \\
  --env-file "$REMOTE_READINESS_ENV" $envs\\
  -e NEXUS_ENVIRONMENT=rehearsal \\
  -e NEXUS_EXPECTED_READINESS_PROTOCOL=NEXUS-STAGING-READINESS-V1 \\
  -e NEXUS_ACTUAL_WORKER_IMAGE="\$IMAGE_REELLE" \\
  -e NEXUS_READINESS_MANIFEST_PATH="$READINESS_REMOTE/$manifeste" \\
  -e NEXUS_READINESS_MANIFEST_SHA256="$sha" \\
  -e NEXUS_GITHUB_TOKEN_FILE=/run/secrets/github-token \\
  -v "$REMOTE_GITHUB_TOKEN_FILE:/run/secrets/github-token:ro" \\
  -v "$REMOTE/repo:/repo:ro" -v "$REMOTE/artifact-store:/store:ro" \\
  -v "$REMOTE/models:/models:ro" -v "$REMOTE/readiness:$REMOTE/readiness:ro" \\
  -v "$RUN:/run-db" \\
  -w /repo --entrypoint python "$IMAGE" -m $*
EOF
}

# ── étapes ────────────────────────────────────────────────────────────────

etape_preflight_measurement() {
    autoriser preflight_measurement
    local mesures
    mesures=$(remote <<EOF
set -euo pipefail
test "\$(docker ps --filter name=^/${CONTAINER}\$ --format '{{.Names}}')" = "$CONTAINER"
echo "DISK_FREE_KB=\$(df -Pk $REMOTE | awk 'NR==2{print \$4}')"
echo "PSQL_ON_HOST=\$(command -v psql >/dev/null && echo yes || echo no)"
echo "PYTHON3_ON_HOST=\$(command -v python3 >/dev/null && echo yes || echo no)"
echo "SUPERUSER=\$(docker exec $CONTAINER printenv POSTGRES_USER)"
for f in "$REMOTE_STAGING_ENV" "$REMOTE_CONTROL_SOURCE_ENV" "$REMOTE_READINESS_ENV"; do
    if [ -f "\$f" ]; then echo "SOURCE_FILE \$f \$(stat -c %a "\$f")"; else echo "SOURCE_FILE_MISSING \$f"; fi
done
if [ -d "$REMOTE_ROLES" ]; then echo "ROLE_DIR present \$(stat -c %a "$REMOTE_ROLES")"; else echo "ROLE_DIR absent"; fi
if [ -f "$REMOTE_GITHUB_TOKEN_FILE" ]; then echo "GITHUB_TOKEN present \$(stat -c %a "$REMOTE_GITHUB_TOKEN_FILE")"; else echo "GITHUB_TOKEN absent"; fi
ls -1 $REMOTE/secrets | sed 's/^/SECRET_NAME /'
# infra/.env du checkout serveur : le runner produit le source AVANT ses
# valeurs par défaut — il ne doit fixer ni la base ni le conteneur.
DOTENV=$REMOTE/repo/services/rag-engine/infra/.env
if [ -f "\$DOTENV" ]; then
    if grep -qE '^[[:space:]]*(export[[:space:]]+)?(PGVECTOR_DB|PGVECTOR_CONTAINER|PGVECTOR_USER|PGDATABASE)=' "\$DOTENV"; then
        echo "INFRA_DOTENV overrides_target"
    else
        echo "INFRA_DOTENV present_harmless"
    fi
else
    echo "INFRA_DOTENV absent"
fi
for m in $REMOTE/models/*/SHA256SUMS; do [ -f "\$m" ] && echo "MODEL \$(sha256sum "\$m")"; done
echo "STORE_OBJECTS=\$(ls $REMOTE/artifact-store 2>/dev/null | wc -l)"
$(mesure_historique)
echo "TARGET_EXISTS=\$($(psql_ro "$LEGACY_DB" "select count(*) from pg_database where datname = '$DB'"))"
if [ "\$($(psql_ro "$LEGACY_DB" "select count(*) from pg_database where datname = '$DB'"))" = 1 ]; then
    echo "TARGET_ROWS=\$($(psql_ro "$DB" "$(vide_cible | tr '\n' ' ')"))"
fi
# Chaque mot de passe source doit authentifier SON rôle : les runners de
# provisionnement réimposent ces valeurs (ALTER ROLE ... PASSWORD) ; elles
# doivent donc être celles en vigueur. Aucune valeur n'est affichée.
(
    set -a; . "$REMOTE_STAGING_ENV"; . "$REMOTE_CONTROL_SOURCE_ENV"; set +a
    SU=\$(docker exec $CONTAINER printenv POSTGRES_USER)
    for couple in "\$SU:PGVECTOR_PASSWORD" \
                  ingestion_control_migrator:INGESTION_CONTROL_MIGRATOR_PASSWORD \
                  ingestion_control_app:INGESTION_CONTROL_APP_PASSWORD \
                  ingestion_control_attestor:INGESTION_CONTROL_ATTESTOR_PASSWORD \
                  ingestion_control_authority:INGESTION_CONTROL_AUTHORITY_PASSWORD \
                  rag_publisher:PGVECTOR_PUBLISHER_PASSWORD \
                  rag_reader:PGVECTOR_RETRIEVAL_PASSWORD \
                  rag_reviewer:PGVECTOR_REVIEW_PASSWORD; do
        role=\${couple%%:*}; variable=\${couple#*:}
        if [ -z "\${!variable:-}" ]; then echo "ROLE_AUTH \$role MISSING_SOURCE"; continue; fi
        if PGPASSWORD="\${!variable}" \\
            psql "host=127.0.0.1 port=\$PGVECTOR_PORT user=\$role dbname=$LEGACY_DB options='-c default_transaction_read_only=on'" -X -At -c "select current_user" \\
            2>/dev/null | grep -qx "\$role"; then
            echo "ROLE_AUTH \$role OK"
        else
            echo "ROLE_AUTH \$role KO"
        fi
    done
)
EOF
) || fail "pré-vol : mesure impossible"
    [ "$DRY_RUN" = 1 ] && { printf 'absente\n' > "$STATE_DIR/cible"; marquer preflight_measurement "dry-run"; return; }
    decision_prevol "$mesures"
    marquer preflight_measurement "cible=$(cat "$STATE_DIR/cible") $(tr '\n' ' ' < "$STATE_DIR/legacy_baseline.txt")"
}

decision_prevol() {  # $1 = mesures du pré-vol ; écrit l'état, ou arrête
    local mesures="$1" existe lignes
    printf '%s\n' "$mesures" > "$STATE_DIR/preflight.txt"
    grep '^LEGACY_' <<<"$mesures" > "$STATE_DIR/legacy_baseline.txt" || fail "pré-vol : ragdb non mesurée"
    [ "$(grep -c '^LEGACY_' "$STATE_DIR/legacy_baseline.txt")" = 7 ] || fail "pré-vol : mesure de ragdb incomplète"
    ! grep -q '^SOURCE_FILE_MISSING' <<<"$mesures" || fail "pré-vol : fichier source absent (preflight.txt)"
    grep -q '^PSQL_ON_HOST=yes' <<<"$mesures" || fail "pré-vol : psql absent de l'hôte"
    grep -q '^PYTHON3_ON_HOST=yes' <<<"$mesures" || fail "pré-vol : python3 absent de l'hôte"
    ! grep -q '^INFRA_DOTENV overrides_target' <<<"$mesures" || fail "pré-vol : infra/.env du serveur fixe la base ou le conteneur"
    ! grep -qE '^ROLE_AUTH .* (KO|MISSING_SOURCE)$' <<<"$mesures" \
        || fail "pré-vol : un mot de passe source n'authentifie pas son rôle — le provisionnement le changerait"
    [ "$(grep -c '^ROLE_AUTH .* OK$' <<<"$mesures")" = 8 ] || fail "pré-vol : identités des rôles incomplètes"
    existe=$(sed -n 's/^TARGET_EXISTS=//p' <<<"$mesures")
    if [ "$existe" = 0 ]; then
        printf 'absente\n' > "$STATE_DIR/cible"
    elif [ "$existe" = 1 ]; then
        lignes=$(sed -n 's/^TARGET_ROWS=//p' <<<"$mesures")
        [ "$lignes" = 0 ] || fail "pré-vol : la base dédiée $DB porte déjà ${lignes:-?} ligne(s) — contenu inattendu, refus"
        printf 'vierge\n' > "$STATE_DIR/cible"
    else
        fail "pré-vol : existence de $DB illisible"
    fi
}

etape_backup_before_migration() {
    autoriser backup_before_migration
    local stamp; stamp=$(date -u +%Y%m%dT%H%M%SZ)
    remote <<EOF || fail "sauvegarde"
set -euo pipefail
d=$REMOTE/backups/dc-$stamp; install -d -m 0700 "\$d"
docker exec $CONTAINER sh -c 'pg_dump -Fc -U "\$POSTGRES_USER" $LEGACY_DB' > "\$d/ragdb.dump"
test -s "\$d/ragdb.dump"; chmod 600 "\$d/ragdb.dump"; sha256sum "\$d/ragdb.dump"
EOF
    marquer backup_before_migration "dc-$stamp (ragdb, lecture)"
}

etape_database_creation() {
    autoriser database_creation
    local etat; etat=$(cat "$STATE_DIR/cible" 2>/dev/null) || fail "création : pré-vol absent"
    if [ "$etat" = vierge ]; then
        # Reprise : la base existe, le pré-vol l'a constatée vierge ; on le revérifie.
        remote <<EOF || fail "création : la base dédiée n'est plus vierge"
set -euo pipefail
test "\$($(psql_ro "$DB" "$(vide_cible | tr '\n' ' ')"))" = 0
EOF
        marquer database_creation "reprise : $DB présente et vierge"
        return
    fi
    [ "$etat" = absente ] || fail "création : état de la cible inconnu ($etat)"
    remote <<EOF || fail "création de $DB"
set -euo pipefail
test "\$($(psql_ro "$LEGACY_DB" "select count(*) from pg_database where datname = '$DB'"))" = 0 \\
    || { echo "BASE_DEJA_PRESENTE $DB : refus, rien n'est réutilisé" >&2; exit 4; }
docker exec $CONTAINER sh -c 'createdb -U "\$POSTGRES_USER" -T template0 -E UTF8 --locale=C $DB'
test "\$($(psql_ro "$LEGACY_DB" "select pg_encoding_to_char(encoding)||'/'||datcollate||'/'||datctype from pg_database where datname = '$DB'"))" = "UTF8/C/C"
test "\$($(psql_ro "$DB" "$(vide_cible | tr '\n' ' ')"))" = 0
EOF
    verifier_historique
    marquer database_creation "$DB créée (UTF8/C/C, template0)"
}

etape_product_migrations() {
    autoriser product_migrations
    remote <<EOF || fail "migrations produit"
set -euo pipefail
cd $REMOTE/repo && git fetch -q origin && git checkout -q --detach $AUTH_COMMIT
test "\$($(psql_ro "$DB" "select case when to_regclass('public.rag_schema_migrations') is null then 0 else (select coalesce(max(version),0) from public.rag_schema_migrations) end"))" = 0 \\
    || { echo "TETE_PRODUIT_INATTENDUE avant migration" >&2; exit 4; }
cd services/rag-engine/infra
! grep -qE '^[[:space:]]*(export[[:space:]]+)?(PGVECTOR_DB|PGVECTOR_CONTAINER|PGVECTOR_USER)=' .env 2>/dev/null
(
    set -a; . "$REMOTE_STAGING_ENV"; set +a
    export PGVECTOR_CONTAINER=$CONTAINER PGVECTOR_DB=$DB
    export PGVECTOR_USER=\$(docker exec $CONTAINER printenv POSTGRES_USER)
    export PGVECTOR_RETRIEVAL_USER=rag_reader PGVECTOR_REVIEW_USER=rag_reviewer PGVECTOR_PUBLISHER_USER=rag_publisher
    BACKUP_ROOT=$REMOTE/backups ./scripts/apply_pgvector_migrations.sh
)
test "\$($(psql_ro "$DB" "select max(version) from public.rag_schema_migrations"))" = 5
EOF
    verifier_historique
    marquer product_migrations "$DB head=5"
}

etape_control_migrations() {
    autoriser control_migrations
    remote <<EOF || fail "migrations contrôle"
set -euo pipefail
command -v psql >/dev/null || { echo "psql absent de l'hôte" >&2; exit 4; }
test "\$($(psql_ro "$DB" "select case when to_regclass('ingestion_control.schema_migrations') is null then 0 else (select coalesce(max(version),0) from ingestion_control.schema_migrations) end"))" = 0 \\
    || { echo "TETE_CONTROLE_INATTENDUE avant migration" >&2; exit 4; }
cd $REMOTE/repo/services/rag-engine/infra
(
    set -a; . "$REMOTE_STAGING_ENV"; . "$REMOTE_CONTROL_SOURCE_ENV"; set +a
    export PGHOST=127.0.0.1 PGPORT="\$PGVECTOR_PORT" PGDATABASE=$DB
    export PGUSER=\$(docker exec $CONTAINER printenv POSTGRES_USER) PGPASSWORD="\$PGVECTOR_PASSWORD"
    ./scripts/provision_and_bootstrap_ingestion_control.sh
)
test "\$($(psql_ro "$DB" "select max(version) from ingestion_control.schema_migrations"))" = 19
EOF
    verifier_historique
    marquer control_migrations "$DB head=19"
}

etape_role_env_derivation() {
    autoriser role_env_derivation
    local script="scripts/go_live/staging_v4_role_env.py" f variable role
    grep -qx 'PYSRC' "$script" && fail "dérivation : délimiteur réservé présent dans le script"
    {
        cat <<EOF
set -euo pipefail
umask 077
(
    set -a; . "$REMOTE_STAGING_ENV"; . "$REMOTE_CONTROL_SOURCE_ENV"; set +a
    python3 - --database $DB --out-dir $REMOTE_ROLES <<'PYSRC'
EOF
        cat "$script"
        cat <<EOF
PYSRC
)
EOF
        # Chaque fichier doit authentifier SON rôle sur la base dédiée, et
        # aucun autre ; la valeur n'est jamais affichée.
        for f in ingestion-control-app.env:PG_INGESTION_CONTROL_DSN:ingestion_control_app \
                 ingestion-control-attestor.env:PG_INGESTION_CONTROL_ATTESTOR_DSN:ingestion_control_attestor \
                 ingestion-control-authority.env:PG_INGESTION_CONTROL_AUTHORITY_DSN:ingestion_control_authority \
                 rag-publisher.env:PG_RAG_DSN:rag_publisher \
                 rag-reader.env:PG_RAG_DSN:rag_reader; do
            IFS=: read -r fichier variable role <<<"$f"
            cat <<EOF
test "\$(stat -c %a "$REMOTE_ROLES/$fichier")" = 600
test "\$(grep -c '' "$REMOTE_ROLES/$fichier")" = 1
dsn=\$(sed -n 's/^$variable=//p' "$REMOTE_ROLES/$fichier")
test "\$(PGOPTIONS='-c default_transaction_read_only=on' psql "\$dsn" -X -At -c "select current_user||'|'||current_database()")" = "$role|$DB"
echo "ROLE_ENV_VERIFIED $fichier $role $DB"
EOF
        done
        echo "test \"\$(stat -c %a \"$REMOTE_ROLES\")\" = 700"
    } | remote | tee "$STATE_DIR/role-env.out" || fail "dérivation des fichiers par rôle"
    [ "$DRY_RUN" = 1 ] || [ "$(grep -c '^ROLE_ENV_VERIFIED ' "$STATE_DIR/role-env.out")" = 5 ] \
        || fail "dérivation : cinq fichiers vérifiés attendus"
    verifier_historique
    marquer role_env_derivation "5 fichiers, $REMOTE_ROLES"
}

etape_model_artifact_install() {
    if [ "$DRY_RUN" = 0 ] && grep -q "^MODEL $MODELE_INVENTAIRE " "$STATE_DIR/preflight.txt"; then
        marquer model_artifact_install "déjà présent"; return
    fi
    autoriser model_artifact_install
    [ -f "$MODELE_LOCAL/SHA256SUMS" ] || fail "artefact E5 local absent : $MODELE_LOCAL"
    [ "$(sha256sum "$MODELE_LOCAL/SHA256SUMS" | cut -d' ' -f1)" = "$MODELE_INVENTAIRE" ] || fail "artefact E5 local : inventaire inattendu"
    (cd "$MODELE_LOCAL" && sha256sum -c --quiet SHA256SUMS) || fail "artefact E5 local : fichier altéré"
    if [ "$DRY_RUN" = 0 ]; then
        remote <<EOF || fail "modèle : destination"
set -euo pipefail
test ! -e $REMOTE/models/$MODELE_NOM || { echo "destination existante : rien n'est écrasé" >&2; exit 4; }
install -d -m 0700 $REMOTE/models/$MODELE_NOM.partiel
EOF
        rsync -a --chmod=D0700,F0600 "$MODELE_LOCAL/" "$SSH_HOST:$REMOTE/models/$MODELE_NOM.partiel/" || fail "modèle : copie"
    fi
    remote <<EOF || fail "modèle : vérification"
set -euo pipefail
cd $REMOTE/models/$MODELE_NOM.partiel
test "\$(sha256sum SHA256SUMS | cut -d' ' -f1)" = "$MODELE_INVENTAIRE"
sha256sum -c --quiet SHA256SUMS
mv $REMOTE/models/$MODELE_NOM.partiel $REMOTE/models/$MODELE_NOM
EOF
    marquer model_artifact_install "inventaire=$MODELE_INVENTAIRE"
}

etape_readiness_manifest_install() {
    autoriser readiness_manifest_install
    local f="$READINESS_MANIFESTE"
    [ -f "$READINESS_LOCAL/$f" ] || fail "manifeste signé absent : $READINESS_LOCAL/$f (signature du détenteur de la clé)"
    if [ "$DRY_RUN" = 0 ]; then
        echo "install -d -m 0700 $READINESS_REMOTE" | remote || fail "readiness : destination"
        scp -q "$READINESS_LOCAL/$f" "$SSH_HOST:$READINESS_REMOTE/$f" || fail "readiness : dépôt de $f"
    fi
    echo "cd $READINESS_REMOTE && chmod 600 $f && sha256sum $f" | remote || fail "readiness : vérification"
    marquer readiness_manifest_install "$f"
}

etape_transfer_manifest_v4() {
    autoriser transfer_manifest_v4
    local liste="docs/reports/evidence/external_staging_v2_artifact_transfer_manifest.json"
    remote <<EOF > "$STATE_DIR/store-hashes.txt" || fail "rehachage du magasin"
set -euo pipefail
cd $REMOTE/artifact-store && sha256sum -- *.pdf
EOF
    [ "$DRY_RUN" = 1 ] && { marquer transfer_manifest_v4 "sha256=dry-run"; return; }
    "$PYTHON" - "$liste" "$STATE_DIR/store-hashes.txt" "$STATE_DIR/transfer_manifest_v4.json" <<'PY' || fail "manifeste de transfert V4"
import json, sys
v2 = json.load(open(sys.argv[1]))
observed = {}
for line in open(sys.argv[2]):
    parts = line.split()
    if len(parts) == 2 and parts[1].endswith(".pdf"):
        observed[parts[1]] = parts[0]
files, bad = [], []
for entry in v2["files"]:
    got = observed.get(entry["file"])
    files.append({"file": entry["file"], "sha256_expected": entry["sha256_expected"], "sha256_observed": got})
    if got != entry["sha256_expected"]:
        bad.append(entry["file"])
if bad:
    raise SystemExit(f"{len(bad)} objet(s) absent(s) ou divergent(s), premier : {bad[0]}")
doc = {
    "manifest_kind": "NEXUS-STAGING-ARTIFACT-TRANSFER-V1",
    "release_id": "production-profile-gate-2026-2027-v4",
    "transfer_method": "aucun transfert : objets déjà présents sur l'hôte, rehachés en lecture sous l'identité V4",
    "destination_path": "/srv/nexus-staging/artifact-store/",
    "file_count": len(files), "files": files,
    "digest_mismatches": 0, "digest_missing": 0,
    "predecessor_transfer_manifest_release_id": v2["release_id"],
    "production_db_reads": 0, "production_db_writes": 0, "production_paths_written": 0,
}
open(sys.argv[3], "w").write(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
PY
    scp -q "$STATE_DIR/transfer_manifest_v4.json" "$SSH_HOST:$RUN/transfer_manifest_v4.json" || fail "dépôt du manifeste V4"
    marquer transfer_manifest_v4 "sha256=$(sha256sum "$STATE_DIR/transfer_manifest_v4.json" | cut -d' ' -f1)"
}

etape_scope_authorization_registration_r4() {
    autoriser scope_authorization_registration_r4
    # Conteneur ponctuel d'autorité : il reçoit, seul, le fichier du rôle
    # authority ; aucun worker ne le voit. La CLI relit la revue EN DIRECT (PR
    # ouverte, APPROVED, head exact, check épinglé) et l'artefact au head approuvé.
    local pr head ids id
    pr="$(champ scope_authorizations.pull_request)"
    head="$(champ scope_authorizations.expected_head)"
    env_de_role "$REMOTE_AUTHORITY_ENV"
    ids=$("$PYTHON" scripts/go_live/staging_v4_arguments.py autorisations-r4) || fail "r4 : dérivation refusée"
    for id in $ids; do
        remote <<EOF | tee -a "$STATE_DIR/registration.out" || fail "enregistrement de $id"
set -euo pipefail
$(jeton_present)
$(tirer "$IMAGE")
docker run --rm --network host \\
  --env-file "$REMOTE_AUTHORITY_ENV" \\
  -e NEXUS_GITHUB_TOKEN_FILE=/run/secrets/github-token \\
  -v "$REMOTE_GITHUB_TOKEN_FILE:/run/secrets/github-token:ro" \\
  --entrypoint python "$IMAGE" -m ingestor.ingestion_worker.authorize_scope_cli \\
  record-authorization --authorization-id "$id" --repository cyranoaladin/RAG \\
  --pull-request "$pr" --expected-head "$head"
EOF
    done
    verifier_historique
    marquer scope_authorization_registration_r4 "pr=$pr head=$head count=$(wc -w <<<"$ids")"
}

etape_sealed_ingestion_v4() {
    autoriser sealed_ingestion_v4
    # Ingestion INITIALE : la base dédiée ne doit porter aucune ressource.
    remote <<EOF || fail "ingestion : la base dédiée n'est plus vierge"
set -euo pipefail
test "\$($(psql_ro "$DB" "select count(*) from ingestion_control.resources"))" = 0
test "\$($(psql_ro "$DB" "select count(*) from public.rag_artifact_placements"))" = 0
EOF
    worker "$REMOTE_WORKER_ENV" ingestor.ingestion_worker.sealed_release_ingestion_cli \
        "$(args_de ingestion-v4 --transfer-sha256 "$(transfert_sha)")" | remote | tee "$STATE_DIR/ingestion.out" \
        || fail "ingestion scellée V4"
    [ "$DRY_RUN" = 1 ] || grep -q 'resources=479 ' "$STATE_DIR/ingestion.out" || fail "ingestion V4 : comptes inattendus"
    verifier_historique
    marquer sealed_ingestion_v4 "ok"
}

etape_batch_review_proposal() {
    autoriser batch_review_proposal
    worker "$REMOTE_ATTESTOR_ENV" ingestor.ingestion_worker.attest_publication_cli propose-release-batch-review \
        --release-id "$(champ release.release_id)" --release-dir "/repo/$(champ release.release_dir)" \
        --release-manifest-sha256 "$(champ release.release_manifest_sha256)" \
        --transfer-manifest-path /run-db/transfer_manifest_v4.json --transfer-manifest-sha256 "$(transfert_sha)" \
        --rights-registry-path /repo/services/rag-pedago/configs/rights_evidence_registry.yml \
        --review-id "${BATCH_REVIEW_ID:?BATCH_REVIEW_ID}" --evaluator "${EVALUATOR:?EVALUATOR : identité réelle}" \
        --pii-decision-set-path /repo/governance/pii-review-decisions/pii-review-2026-09-22-profile-gate-v3.json \
        --pii-review-receipt-path /repo/governance/pii-review-bindings/pii-review-2026-09-22-profile-gate-v3.json \
        --review-trust-anchor-path /repo/governance/trust-anchors/review-binding-v1.json \
        --pii-review-index-path /repo/docs/reports/evidence-index/pii_review_index_20260922_profile_gate_v3.json \
        --pii-review-reviewers-sha256 "$(sha256sum scripts/github/trusted-reviewers.json | cut -d' ' -f1)" \
        --repository-root /repo | remote | tee "$STATE_DIR/proposal.out" || fail "proposition de revue batch"
    verifier_historique
    marquer batch_review_proposal "ok"
    log "ATTENTE_HUMAINE: soumettre l'artefact de revue batch en PR et le faire approuver au head exact"
    exit 0
}

etape_batch_review_record() {
    autoriser batch_review_record
    worker "$REMOTE_ATTESTOR_ENV" ingestor.ingestion_worker.attest_publication_cli record-release-batch-attestation \
        --release-id "$(champ release.release_id)" --review-id "${BATCH_REVIEW_ID:?BATCH_REVIEW_ID}" \
        --repository cyranoaladin/RAG --pull-request "${BATCH_REVIEW_PR:?BATCH_REVIEW_PR}" \
        --expected-head "${BATCH_REVIEW_HEAD:?BATCH_REVIEW_HEAD}" \
        --review-artifact-path "${BATCH_REVIEW_ARTIFACT:?BATCH_REVIEW_ARTIFACT}" \
        | remote || fail "enregistrement de l'attestation batch"
    verifier_historique
    marquer batch_review_record "ok"
}

etape_worker_b_publication() {
    autoriser worker_b_publication
    worker "$REMOTE_WORKER_ENV:$REMOTE_PUBLISHER_ENV" \
        ingestor.ingestion_worker.multilevel_publication_resume_cli \
        "$(args_de worker-b --transfer-sha256 "$(transfert_sha)" --embedding-root "/models/$MODELE_NOM")" \
        --max-iterations "${MAX_ITERATIONS:-2000}" | remote | tee "$STATE_DIR/worker-b.out" || fail "Worker B"
    [ "$DRY_RUN" = 1 ] || grep -q 'authority_mode=RELEASE_BOUND_STAGING_QUALIFICATION' "$STATE_DIR/worker-b.out" \
        || fail "Worker B : démarrage hors qualification liée à la release"
    verifier_historique
    marquer worker_b_publication "ok"
}

etape_independent_verification() {
    autoriser independent_verification
    env_de_role "$REMOTE_READER_ENV"
    remote <<EOF | tee "$STATE_DIR/verification.txt" || fail "vérification"
set -euo pipefail
echo "PLACEMENTS=\$($(psql_ro "$DB" "select count(distinct collection)||' '||count(distinct artifact_id)||' '||count(*) from public.rag_artifact_placements"))"
echo "CHUNKS=\$($(psql_ro "$DB" "select count(distinct chunk_id) from public.rag_chunks"))"
echo "RELEASE=\$($(psql_ro "$DB" "select string_agg(distinct programme_version||'/'||visibility||'/'||currentness, ',') from public.rag_artifact_placements"))"
$(tirer "$SONDE")
docker run --rm --network host --env-file "$REMOTE_READER_ENV" -e PYTHONPATH=/app \\
  -v "$REMOTE/repo:/repo:ro" -v "$RUN:/run-db" -w /app \\
  --entrypoint python "$SONDE" /repo/scripts/go_live/staging_retrieval_probe.py \\
  --repository-root /repo --output /run-db/retrieval-probe.json
EOF
    verifier_historique
    [ "$DRY_RUN" = 1 ] && { marquer independent_verification "dry-run"; return; }
    grep -qx 'PLACEMENTS=11 315 479' "$STATE_DIR/verification.txt" || fail "vérification : placements inattendus"
    grep -qx 'CHUNKS=8268' "$STATE_DIR/verification.txt" || fail "vérification : chunks inattendus"
    grep -q '^SONDE_RETRIEVAL_V4 ' "$STATE_DIR/verification.txt" || fail "vérification : sonde de retrieval"
    marquer independent_verification "ok"
}

ORDRE=(preflight_measurement backup_before_migration database_creation product_migrations
       control_migrations role_env_derivation model_artifact_install readiness_manifest_install
       transfer_manifest_v4 scope_authorization_registration_r4 sealed_ingestion_v4
       batch_review_proposal batch_review_record worker_b_publication independent_verification)

# Sourcé (tests) : fonctions définies, rien n'est exécuté.
if [ "${BASH_SOURCE[0]}" != "$0" ]; then return 0; fi

case "${1:-}" in
    status)
        for e in "${ORDRE[@]}"; do
            if fait "$e"; then echo "FAIT    $e $(cat "$STATE_DIR/$e.done")"; else echo "A_FAIRE $e"; fi
        done ;;
    run)
        jusqua=""; [ "${2:-}" = "--until" ] && jusqua="${3:?étape attendue}"
        if [ "$DRY_RUN" = 0 ]; then
            "$PYTHON" scripts/go_live/check_staging_authorization.py >/dev/null || fail "autorisation de base invalide"
        fi
        charger_autorisation
        for e in "${ORDRE[@]}"; do
            if fait "$e"; then log "DEJA_FAIT $e"; else "etape_$e"; fi
            [ -n "$jusqua" ] && [ "$e" = "$jusqua" ] && break
        done ;;
    *) echo "usage: $0 [--dry-run] run [--until <étape>] | status" >&2; exit 2 ;;
esac
