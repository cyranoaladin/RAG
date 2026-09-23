#!/usr/bin/env bash
# Orchestrateur de la publication V3 sur le staging cloisonné (lot CY).
#
# Plan : docs/runbooks/staging_v3_publication_EXECUTION_PLAN.md
# Chaque étape est d'abord soumise au vérificateur d'autorisation, sur sa cible
# exacte (tirée du vérificateur, jamais ressaisie ici). Premier écart : arrêt.
# Aucune commande canonique n'est réimplémentée : ce script les enchaîne, avec
# des arguments dérivés de la release par staging_v3_arguments.py.
#
#   scripts/go_live/staging_v3_publication.sh [--dry-run] run [--until <étape>]
#   scripts/go_live/staging_v3_publication.sh status
#
# État et journal expurgé : $STATE_DIR (défaut ~/nexus-staging-v3-run, 0700).
# Reprise : une étape marquée faite n'est pas rejouée ; supprimer son marqueur
# ne la rejoue qu'après que sa commande canonique a revérifié son état (les
# commandes sont idempotentes : already_present, rejeu sans écriture).
set -euo pipefail

ROOT="${NEXUS_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$ROOT"
STATE_DIR="${STATE_DIR:-$HOME/nexus-staging-v3-run}"
SSH_HOST="${SSH_HOST:-nexus-prod}"
REMOTE="/srv/nexus-staging"
CONTAINER="nexus-staging-pgvector-1"
DB="ragdb"
AUTH_V3="docs/reports/go_live/authorizations/staging_v3_publication_authorization.json"
MODELE_NOM="e5-large-prerentree-2026-2027-20260828-materialise"
MODELE_INVENTAIRE="58ad18dbb0a154c5a10320de9efdf81944f8b1ee1a01cc7f077e8b86b364dbc6"
MODELE_LOCAL="${MODELE_LOCAL:-$HOME/rag-model-artifacts/$MODELE_NOM}"
# Manifestes de readiness signés localement (sign_staging_v3_readiness_manifests.sh).
READINESS_LOCAL="${READINESS_LOCAL:-$HOME/nexus-staging-v3-readiness}"
READINESS_REMOTE="$REMOTE/readiness"
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && { DRY_RUN=1; shift; }

# Fichiers d'environnement de l'hôte (0600, jamais affichés). Leurs noms sont
# constatés au pré-vol ; leur contenu ne transite jamais par ce poste.
REMOTE_STAGING_ENV="${REMOTE_STAGING_ENV:-$REMOTE/secrets/staging.env}"
REMOTE_READINESS_ENV="${REMOTE_READINESS_ENV:-$REMOTE/secrets/readiness.env}"
REMOTE_WORKER_ENV="${REMOTE_WORKER_ENV:-$REMOTE/secrets/ingestion-control-app.env}"
REMOTE_ATTESTOR_ENV="${REMOTE_ATTESTOR_ENV:-$REMOTE/secrets/ingestion-control-attestor.env}"
REMOTE_PUBLISHER_ENV="${REMOTE_PUBLISHER_ENV:-$REMOTE/secrets/rag-publisher.env}"
REMOTE_GITHUB_TOKEN_FILE="${REMOTE_GITHUB_TOKEN_FILE:-$REMOTE/secrets/github-read-token/token}"

install -d -m 0700 "$STATE_DIR"
LOG="$STATE_DIR/execution.log"

redact() {  # aucun secret ne passe dans le journal
    sed -E \
        -e 's#(postgres(ql)?://[^:/ ]+:)[^@ ]+@#\1***@#g' \
        -e 's#(gh[pousr]_|github_pat_)[A-Za-z0-9_]+#\1***#g' \
        -e 's#((PASSWORD|SECRET|TOKEN|KEY|DSN)[A-Z_]*=)[^ ]+#\1***#g'
}
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | redact | tee -a "$LOG" >&2; }
fail() { log "ARRET: $*"; exit 3; }

champ() {  # lit un champ de l'autorisation V3 par chemin pointé
    python3 -c "
import json,sys
d=json.load(open('$AUTH_V3'))
for k in sys.argv[1].split('.'): d=d[k]
print(d)" "$1"
}
cible() {
    python3 -c "
import json,sys; sys.path.insert(0,'scripts/go_live')
import check_staging_authorization as a
print(json.dumps(a.OPERATIONS_V3[sys.argv[1]]['cible'], sort_keys=True))" "$1"
}
autoriser() {
    local op="$1" sortie
    if ! sortie=$(python3 scripts/go_live/check_staging_authorization.py \
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
chemin() { cat "$STATE_DIR/chemin" 2>/dev/null || true; }
psql_ro() {  # requête en lecture, dans le conteneur exact
    printf 'docker exec %s sh -c %q\n' "$CONTAINER" \
        "psql -v ON_ERROR_STOP=1 -X -At -U \"\$POSTGRES_USER\" -d $DB -c \"$1\""
}
args_de() {  # arguments canoniques, une ligne par argument, citée pour bash
    local sortie
    sortie=$(python3 scripts/go_live/staging_v3_arguments.py "$@") || fail "arguments refusés : $*"
    local -a tableau; mapfile -t tableau <<<"$sortie"
    printf '%q ' "${tableau[@]}"
}
transfert_sha() { sed -n 's/^sha256=//p' "$STATE_DIR/transfer_manifest_v3.done"; }

IMAGE="" ; AUTH_COMMIT=""
charger_autorisation() {
    [ -f "$AUTH_V3" ] || fail "autorisation V3 absente"
    IMAGE="$(champ runtime_image.reference)"
    AUTH_COMMIT="$(git log -1 --format=%H -- "$AUTH_V3")"
}

worker() {  # $1 = v3|v2 (manifeste de readiness) ; $2 = fichiers d'env (':') ; reste = module et arguments
    local manifeste="staging-readiness-$1.json" envs="" f sha
    [ "$1" = v2 ] && manifeste="staging-readiness-v2-backfill.json"
    shift
    sha=$(sha256sum "$READINESS_LOCAL/$manifeste" 2>/dev/null | cut -d' ' -f1) \
        || fail "manifeste de readiness local absent : $manifeste"
    IFS=: read -r -a _fichiers <<<"$1"; shift
    for f in "${_fichiers[@]}"; do envs+="--env-file \"$f\" "; done
    cat <<EOF
set -euo pipefail
docker image inspect "$IMAGE" >/dev/null 2>&1 || docker pull -q "$IMAGE"
IMAGE_REELLE=\$(docker inspect --format '{{index .RepoDigests 0}}' "$IMAGE")
test "\$IMAGE_REELLE" = "$IMAGE"
install -d -m 0700 $REMOTE/run-cy
docker run --rm --network host \\
  --env-file "$REMOTE_READINESS_ENV" $envs\\
  -e NEXUS_ACTUAL_WORKER_IMAGE="\$IMAGE_REELLE" \\
  -e NEXUS_READINESS_MANIFEST_PATH="$READINESS_REMOTE/$manifeste" \\
  -e NEXUS_READINESS_MANIFEST_SHA256="$sha" \\
  -e NEXUS_GITHUB_TOKEN_FILE=/run/secrets/github-token \\
  -v "$REMOTE_GITHUB_TOKEN_FILE:/run/secrets/github-token:ro" \\
  -v "$REMOTE/repo:/repo:ro" -v "$REMOTE/artifact-store:/store:ro" \\
  -v "$REMOTE/models:/models:ro" -v "$REMOTE/readiness:$REMOTE/readiness:ro" \\
  -v "$REMOTE/run-cy:/run-cy" \\
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
for f in "$REMOTE_STAGING_ENV" "$REMOTE_READINESS_ENV" "$REMOTE_WORKER_ENV" "$REMOTE_ATTESTOR_ENV" "$REMOTE_PUBLISHER_ENV" "$REMOTE_GITHUB_TOKEN_FILE"; do
    if [ -f "\$f" ]; then echo "SECRET_FILE \$f \$(stat -c %a "\$f")"; else echo "SECRET_FILE_MISSING \$f"; fi
done
ls -1 $REMOTE/secrets | sed 's/^/SECRET_NAME /'
for m in $REMOTE/models/*/SHA256SUMS; do [ -f "\$m" ] && echo "MODEL \$(sha256sum "\$m")"; done
echo "STORE_OBJECTS=\$(ls $REMOTE/artifact-store 2>/dev/null | wc -l)"
echo "DB_SIZE=\$($(psql_ro "select pg_database_size('$DB')"))"
echo "PRODUCT_HEAD=\$($(psql_ro "select coalesce(max(version),0) from public.rag_schema_migrations"))"
echo "CONTROL_HEAD=\$($(psql_ro "select coalesce(max(version),0) from ingestion_control.schema_migrations"))"
echo "RESOURCES=\$($(psql_ro "select count(*) from ingestion_control.resources"))"
echo "ARTIFACTS=\$($(psql_ro "select count(*) from ingestion_control.artifacts"))"
echo "ATTRIBUTIONS=\$($(psql_ro "select case when to_regclass('ingestion_control.artifact_attributions') is null then -1 else (select count(*) from ingestion_control.artifact_attributions) end"))"
EOF
) || fail "pré-vol : mesure impossible"
    [ "$DRY_RUN" = 1 ] && { printf 'A\n' > "$STATE_DIR/chemin"; marquer preflight_measurement "dry-run"; return; }
    printf '%s\n' "$mesures" > "$STATE_DIR/preflight.txt"
    if grep -q '^SECRET_FILE_MISSING' <<<"$mesures"; then
        fail "pré-vol : fichier d'environnement absent — noms réels dans preflight.txt (SECRET_NAME)"
    fi
    local ressources artefacts decision
    ressources=$(sed -n 's/^RESOURCES=//p' <<<"$mesures")
    artefacts=$(sed -n 's/^ARTIFACTS=//p' <<<"$mesures")
    if [ "$ressources" = 0 ] && [ "$artefacts" = 0 ]; then decision=A
    elif [ "$artefacts" -gt 0 ]; then decision=B    # rattrapage : la commande vérifie 479/479
    else fail "pré-vol : état intermédiaire (resources=$ressources artifacts=$artefacts) — écart à instruire"
    fi
    printf '%s\n' "$decision" > "$STATE_DIR/chemin"
    marquer preflight_measurement "chemin=$decision resources=$ressources artifacts=$artefacts"
}

etape_backup_before_migration() {
    autoriser backup_before_migration
    local stamp; stamp=$(date -u +%Y%m%dT%H%M%SZ)
    remote <<EOF || fail "sauvegarde"
set -euo pipefail
d=$REMOTE/backups/cy-$stamp; install -d -m 0700 "\$d"
docker exec $CONTAINER sh -c 'pg_dump -Fc -U "\$POSTGRES_USER" $DB' > "\$d/ragdb.dump"
test -s "\$d/ragdb.dump"; sha256sum "\$d/ragdb.dump"
EOF
    marquer backup_before_migration "cy-$stamp"
}

etape_product_migrations() {
    autoriser product_migrations
    remote <<EOF || fail "migrations produit"
set -euo pipefail
cd $REMOTE/repo && git fetch -q origin && git checkout -q --detach $AUTH_COMMIT
cd services/rag-engine/infra
PGVECTOR_CONTAINER=$CONTAINER BACKUP_ROOT=$REMOTE/backups ./scripts/apply_pgvector_migrations.sh
test "\$($(psql_ro "select max(version) from public.rag_schema_migrations"))" = 5
EOF
    marquer product_migrations "head=5"
}

etape_control_migrations() {
    autoriser control_migrations
    remote <<EOF || fail "migrations contrôle"
set -euo pipefail
command -v psql >/dev/null || { echo "psql absent de l'hôte" >&2; exit 4; }
cd $REMOTE/repo/services/rag-engine/infra
set -a; . "$REMOTE_STAGING_ENV"; set +a
PGHOST=127.0.0.1 PGPORT=\${PGVECTOR_PORT:-15435} PGDATABASE=$DB \\
PGUSER="\$PGVECTOR_USER" PGPASSWORD="\$PGVECTOR_PASSWORD" \\
    ./scripts/provision_and_bootstrap_ingestion_control.sh
test "\$($(psql_ro "select max(version) from ingestion_control.schema_migrations"))" = 18
EOF
    marquer control_migrations "head=18"
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
    local fichiers=(staging-readiness-v3.json)
    [ "$(chemin)" = B ] && fichiers+=(staging-readiness-v2-backfill.json)
    for f in "${fichiers[@]}"; do
        [ -f "$READINESS_LOCAL/$f" ] || fail "manifeste signé absent : $READINESS_LOCAL/$f (signature du détenteur de la clé)"
    done
    if [ "$DRY_RUN" = 0 ]; then
        echo "install -d -m 0700 $READINESS_REMOTE" | remote || fail "readiness : destination"
        for f in "${fichiers[@]}"; do
            scp -q "$READINESS_LOCAL/$f" "$SSH_HOST:$READINESS_REMOTE/$f" || fail "readiness : dépôt de $f"
        done
    fi
    echo "cd $READINESS_REMOTE && chmod 600 ${fichiers[*]} && sha256sum ${fichiers[*]}" | remote \
        || fail "readiness : vérification"
    marquer readiness_manifest_install "${fichiers[*]}"
}

etape_transfer_manifest_v3() {
    autoriser transfer_manifest_v3
    local liste="docs/reports/evidence/external_staging_v2_artifact_transfer_manifest.json"
    remote <<EOF > "$STATE_DIR/store-hashes.txt" || fail "rehachage du magasin"
set -euo pipefail
cd $REMOTE/artifact-store && sha256sum -- *.pdf
EOF
    [ "$DRY_RUN" = 1 ] && { marquer transfer_manifest_v3 "sha256=dry-run"; return; }
    python3 - "$liste" "$STATE_DIR/store-hashes.txt" "$STATE_DIR/transfer_manifest_v3.json" <<'PY' || fail "manifeste de transfert V3"
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
    "release_id": "production-profile-gate-2026-2027-v3",
    "transfer_method": "aucun transfert : objets déjà présents sur l'hôte, rehachés en lecture sous l'identité V3",
    "destination_path": "/srv/nexus-staging/artifact-store/",
    "file_count": len(files), "files": files,
    "digest_mismatches": 0, "digest_missing": 0,
    "predecessor_transfer_manifest_release_id": v2["release_id"],
    "production_db_reads": 0, "production_db_writes": 0, "production_paths_written": 0,
}
open(sys.argv[3], "w").write(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
PY
    scp -q "$STATE_DIR/transfer_manifest_v3.json" "$SSH_HOST:$REMOTE/run-cy/transfer_manifest_v3.json" || fail "dépôt du manifeste V3"
    marquer transfer_manifest_v3 "sha256=$(sha256sum "$STATE_DIR/transfer_manifest_v3.json" | cut -d' ' -f1)"
}

etape_sealed_ingestion_v3() {
    [ "$(chemin)" = A ] || { log "SAUTEE sealed_ingestion_v3 (chemin $(chemin))"; return; }
    autoriser sealed_ingestion_v3
    worker v3 "$REMOTE_WORKER_ENV" ingestor.ingestion_worker.sealed_release_ingestion_cli \
        "$(args_de ingestion-v3 --transfer-sha256 "$(transfert_sha)")" | remote || fail "ingestion scellée V3"
    marquer sealed_ingestion_v3 "ok"
}

etape_attribution_backfill_v2() {
    [ "$(chemin)" = B ] || { log "SAUTEE attribution_backfill_v2 (chemin $(chemin))"; return; }
    autoriser attribution_backfill_v2
    worker v2 "$REMOTE_WORKER_ENV" ingestor.ingestion_worker.sealed_release_ingestion_cli \
        "$(args_de rattrapage-v2)" | remote | tee "$STATE_DIR/backfill.out" || fail "rattrapage V2"
    [ "$DRY_RUN" = 1 ] || grep -q 'examined=479 .*missing_rows=0' "$STATE_DIR/backfill.out" || fail "rattrapage V2 : comptes inattendus"
    marquer attribution_backfill_v2 "ok"
}

etape_adoption_v3() {
    [ "$(chemin)" = B ] || { log "SAUTEE adoption_v3 (chemin $(chemin))"; return; }
    autoriser adoption_v3
    worker v3 "$REMOTE_ATTESTOR_ENV" ingestor.ingestion_worker.attest_publication_cli \
        "$(args_de adoption-v3 --transfer-sha256 "$(transfert_sha)" --adopted-by "${ADOPTED_BY:?ADOPTED_BY : identité réelle de l\'opérateur}")" \
        | remote | tee "$STATE_DIR/adoption.out" || fail "adoption V3"
    [ "$DRY_RUN" = 1 ] || grep -q 'placements=479' "$STATE_DIR/adoption.out" || fail "adoption : comptes inattendus"
    marquer adoption_v3 "ok"
}

etape_batch_review_proposal() {
    autoriser batch_review_proposal
    worker v3 "$REMOTE_ATTESTOR_ENV" ingestor.ingestion_worker.attest_publication_cli propose-release-batch-review \
        --release-id "$(champ release.release_id)" --release-dir "/repo/$(champ release.release_dir)" \
        --release-manifest-sha256 "$(champ release.release_manifest_sha256)" \
        --transfer-manifest-path /run-cy/transfer_manifest_v3.json --transfer-manifest-sha256 "$(transfert_sha)" \
        --rights-registry-path /repo/services/rag-pedago/configs/rights_evidence_registry.yml \
        --review-id "${BATCH_REVIEW_ID:?BATCH_REVIEW_ID}" --evaluator "${EVALUATOR:?EVALUATOR : identité réelle}" \
        --pii-decision-set-path /repo/governance/pii-review-decisions/pii-review-2026-09-22-profile-gate-v3.json \
        --pii-review-receipt-path /repo/governance/pii-review-bindings/pii-review-2026-09-22-profile-gate-v3.json \
        --review-trust-anchor-path /repo/governance/trust-anchors/review-binding-v1.json \
        --pii-review-index-path /repo/docs/reports/evidence-index/pii_review_index_20260922_profile_gate_v3.json \
        --pii-review-reviewers-sha256 "$(sha256sum scripts/github/trusted-reviewers.json | cut -d' ' -f1)" \
        --repository-root /repo | remote | tee "$STATE_DIR/proposal.out" || fail "proposition de revue batch"
    marquer batch_review_proposal "ok"
    log "ATTENTE_HUMAINE: soumettre l'artefact de revue batch en PR et le faire approuver au head exact"
    exit 0
}

etape_batch_review_record() {
    autoriser batch_review_record
    worker v3 "$REMOTE_ATTESTOR_ENV" ingestor.ingestion_worker.attest_publication_cli record-release-batch-attestation \
        --release-id "$(champ release.release_id)" --review-id "${BATCH_REVIEW_ID:?BATCH_REVIEW_ID}" \
        --repository cyranoaladin/RAG --pull-request "${BATCH_REVIEW_PR:?BATCH_REVIEW_PR}" \
        --expected-head "${BATCH_REVIEW_HEAD:?BATCH_REVIEW_HEAD}" \
        --review-artifact-path "${BATCH_REVIEW_ARTIFACT:?BATCH_REVIEW_ARTIFACT}" \
        | remote || fail "enregistrement de l'attestation batch"
    marquer batch_review_record "ok"
}

etape_worker_b_publication() {
    autoriser worker_b_publication
    worker v3 "$REMOTE_WORKER_ENV:$REMOTE_PUBLISHER_ENV" \
        ingestor.ingestion_worker.multilevel_publication_resume_cli \
        "$(args_de worker-b --transfer-sha256 "$(transfert_sha)" --embedding-root "/models/$MODELE_NOM")" \
        --max-iterations "${MAX_ITERATIONS:-2000}" | remote || fail "Worker B"
    marquer worker_b_publication "ok"
}

etape_independent_verification() {
    autoriser independent_verification
    remote <<EOF | tee "$STATE_DIR/verification.txt" || fail "vérification"
set -euo pipefail
echo "PLACEMENTS=\$($(psql_ro "select count(distinct collection)||' '||count(distinct artifact_id)||' '||count(*) from public.rag_artifact_placements"))"
echo "CHUNKS=\$($(psql_ro "select count(distinct chunk_id) from public.rag_chunks"))"
EOF
    marquer independent_verification "ok"
}

ORDRE=(preflight_measurement backup_before_migration product_migrations control_migrations
       model_artifact_install readiness_manifest_install transfer_manifest_v3 sealed_ingestion_v3 attribution_backfill_v2
       adoption_v3 batch_review_proposal batch_review_record worker_b_publication
       independent_verification)

case "${1:-}" in
    status)
        for e in "${ORDRE[@]}"; do
            if fait "$e"; then echo "FAIT    $e $(cat "$STATE_DIR/$e.done")"; else echo "A_FAIRE $e"; fi
        done ;;
    run)
        jusqua=""; [ "${2:-}" = "--until" ] && jusqua="${3:?étape attendue}"
        if [ "$DRY_RUN" = 0 ]; then
            python3 scripts/go_live/check_staging_authorization.py >/dev/null || fail "autorisation de base invalide"
        fi
        charger_autorisation
        for e in "${ORDRE[@]}"; do
            if fait "$e"; then log "DEJA_FAIT $e"; else "etape_$e"; fi
            [ -n "$jusqua" ] && [ "$e" = "$jusqua" ] && break
        done ;;
    *) echo "usage: $0 [--dry-run] run [--until <étape>] | status" >&2; exit 2 ;;
esac
