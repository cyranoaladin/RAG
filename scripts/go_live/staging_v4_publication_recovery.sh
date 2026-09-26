#!/usr/bin/env bash
# Orchestrateur DH : reprise de la publication V4 après la fermeture de #257.
#
# Plan : docs/runbooks/staging_v4_publication_recovery_DH_EXECUTION_PLAN.md
# Chaque étape est soumise au vérificateur d'autorisation DH, sur sa cible
# exacte. L'autorisation V4 (DG) n'est jamais rejouée : elle est seulement la
# source des images épinglées, que DH exige identiques.
#
# Les fonctions de bas niveau (ssh, conteneurs, lecture seule, intangibilité de
# ragdb, extraction de l'artefact de revue) sont celles de l'orchestrateur V4,
# sourcé en bibliothèque : aucune n'est recopiée.
#
#   scripts/go_live/staging_v4_publication_recovery.sh [--dry-run] run [--until <étape>]
#   scripts/go_live/staging_v4_publication_recovery.sh status
#
# État : $STATE_DIR (défaut ~/nexus-staging-v4-recovery-dh, 0700). L'état de
# l'exécution V4 ($V4_STATE_DIR) n'est que LU (manifeste de transfert).
set -euo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${STATE_DIR:-$HOME/nexus-staging-v4-recovery-dh}"
V4_STATE_DIR="${V4_STATE_DIR:-$HOME/nexus-staging-v4-run}"
_DH_DRY=""
[ "${1:-}" = "--dry-run" ] && { _DH_DRY="--dry-run"; shift; }
# shellcheck source=staging_v4_publication.sh
source "$ICI/staging_v4_publication.sh" $_DH_DRY

AUTH_DH="docs/reports/go_live/authorizations/staging_v4_publication_recovery_authorization.json"
PROPOSITION_DH="docs/reports/go_live/authorizations/proposed/staging_v4_publication_recovery_authorization.json"
IDENTITE_DH="docs/reports/go_live/recovery/dh_stale_review_257.json"
OUTIL_DH="scripts/go_live/staging_v4_publication_recovery.py"
WORKER_B_V4="nexus-v4-worker-b"
WORKER_B_DH="nexus-v4-worker-b-dh"
PR_PERIMEE=257
AUTH_SOURCE=""

champ_dh() {  # lit un champ de l'autorisation DH par chemin pointé
    "$PYTHON" -c "
import json,sys
d=json.load(open('$AUTH_SOURCE'))
for k in sys.argv[1].split('.'): d=d[k]
print(d)" "$1"
}
cible_dh() {
    "$PYTHON" -c "
import json,sys; sys.path.insert(0,'scripts/go_live')
import check_staging_authorization as a
print(json.dumps(a.OPERATIONS_DH[sys.argv[1]]['cible'], sort_keys=True))" "$1"
}
cible_dh_champ() { cible_dh "$1" | "$PYTHON" -c "import json,sys; print(json.load(sys.stdin)[sys.argv[1]])" "$2"; }
autoriser_dh() {
    local op="$1" sortie
    if [ "$HORS_LIGNE" = 1 ]; then
        log "SIMULATION: contrôle d'autorisation DH de $op non appelé (essai hors ligne)"; return 0
    fi
    if ! sortie=$("$PYTHON" scripts/go_live/check_staging_authorization.py \
            --operation "$op" --cible "$(cible_dh "$op")" 2>&1); then
        log "$sortie"
        [ "$DRY_RUN" = 1 ] && { log "SIMULATION: $op serait refusée en réel"; return 0; }
        fail "$op non autorisée"
    fi
    log "AUTORISEE $op"
}
charger_autorisation_dh() {
    if [ -f "$AUTH_DH" ]; then
        AUTH_SOURCE="$AUTH_DH"
        AUTH_COMMIT="$(git log -1 --format=%H -- "$AUTH_DH")"
    elif [ "$DRY_RUN" = 1 ]; then
        # Essai à blanc seulement : la PROPOSITION décrit ce que l'autorisation
        # nommerait. Elle n'autorise rien et ne sert jamais en réel.
        AUTH_SOURCE="$PROPOSITION_DH"
        AUTH_COMMIT="$(git rev-parse HEAD)"
        log "SIMULATION: autorisation DH absente, proposition lue pour l'essai à blanc"
    else
        fail "autorisation DH absente : $AUTH_DH (la proposition n'autorise rien)"
    fi
    IMAGE="$(champ_dh runtime_image.reference)"
    SONDE="$(champ_dh probe_image.reference)"
}
# Le manifeste de transfert est celui de l'exécution V4 : DH ne le refait pas.
transfert_sha() { sed -n 's/^sha256=//p' "$V4_STATE_DIR/transfer_manifest_v4.done"; }

outil_dh() {  # $1 = fichier(s) d'env par rôle (':'), $2 = jeton (0|1), reste = arguments de l'outil
    local envs="" f jeton="$2" montage=""
    IFS=: read -r -a _fichiers <<<"$1"; shift 2
    env_de_role "${_fichiers[@]}"
    for f in "${_fichiers[@]}"; do envs+="--env-file \"$f\" "; done
    [ "$jeton" = 1 ] && montage="-e NEXUS_GITHUB_TOKEN_FILE=/run/secrets/github-token -v \"$REMOTE_GITHUB_TOKEN_FILE:/run/secrets/github-token:ro\" "
    cat <<EOF
set -euo pipefail
$(jeton_si "$jeton")
cd $REMOTE/repo && git fetch -q origin && git checkout -q --detach $AUTH_COMMIT
test -f "$REMOTE/repo/$OUTIL_DH" && test -f "$REMOTE/repo/$IDENTITE_DH"
$(tirer "$IMAGE")
docker run --rm --network host $envs$montage\\
  -v "$REMOTE/repo:/repo:ro" -w /repo --entrypoint python "$IMAGE" \\
  /repo/$OUTIL_DH --repository-root /repo --stale-review /repo/$IDENTITE_DH $*
EOF
}

jeton_si() { if [ "$1" = 1 ]; then jeton_present; fi; }
plan_dh() { sed -n "s/^$1=//p" "$STATE_DIR/recovery_plan.txt"; }

# ── étapes ────────────────────────────────────────────────────────────────

etape_recovery_preflight() {
    autoriser_dh recovery_preflight
    local mesures
    [ -f "$V4_STATE_DIR/transfer_manifest_v4.done" ] || fail "pré-vol : état V4 illisible ($V4_STATE_DIR)"
    mesures=$(remote <<EOF
set -euo pipefail
test "\$(docker ps --filter name=^/${CONTAINER}\$ --format '{{.Names}}')" = "$CONTAINER"
$(mesure_historique)
echo "TARGET_EXISTS=\$($(psql_ro "$LEGACY_DB" "select count(*) from pg_database where datname = '$DB'"))"
echo "PRODUCT_ROWS=\$($(psql_ro "$DB" "select (select count(*) from public.rag_artifacts)||':'||(select count(*) from public.rag_artifact_placements)||':'||(select count(*) from public.rag_chunks)"))"
for nom in $WORKER_B_V4 $WORKER_B_DH; do
    echo "WORKER_B \$nom \$(docker inspect --format '{{.State.Status}}' \$nom 2>/dev/null || echo absent)"
done
echo "TRANSFER_MANIFEST=\$(sha256sum $RUN/transfer_manifest_v4.json | cut -d' ' -f1)"
$(jeton_present)
echo "GITHUB_TOKEN ok"
EOF
) || fail "pré-vol DH : mesure impossible"
    if [ "$DRY_RUN" = 0 ]; then
        decision_prevol_dh "$mesures"
        # Le journal d'un Worker B arrêté est une preuve : copié, jamais retiré.
        echo "docker logs $WORKER_B_V4 2>&1 || true" | remote > "$STATE_DIR/worker-b-v4-stopped.log" || true
    fi
    outil_dh "$REMOTE_WORKER_ENV" 0 preview | remote | tee "$STATE_DIR/preview.out" \
        || { [ "$DRY_RUN" = 1 ] || fail "aperçu DH refusé (voir preview.out)"; }
    verifier_historique
    if [ "$DRY_RUN" = 1 ]; then
        printf 'attestation_set_sha256=%s\njob_set_sha256=%s\n' "$(printf 'a%.0s' {1..64})" "$(printf 'b%.0s' {1..64})" \
            > "$STATE_DIR/recovery_plan.txt"
        marquer recovery_preflight "dry-run"; return
    fi
    grep -E '^RECOVERY_PREVIEW attestation_set_sha256=[0-9a-f]{64} job_set_sha256=[0-9a-f]{64}$' "$STATE_DIR/preview.out" \
        | sed -E 's/^RECOVERY_PREVIEW //; s/ /\n/' > "$STATE_DIR/recovery_plan.txt"
    [ "$(grep -c . "$STATE_DIR/recovery_plan.txt")" = 2 ] || fail "aperçu DH : empreintes absentes"
    marquer recovery_preflight "$(tr '\n' ' ' < "$STATE_DIR/recovery_plan.txt")"
    log "ATTENTE_HUMAINE: relire preview.out, puis relancer avec DH_PREVIEW_ACK=$(plan_dh attestation_set_sha256)"
    exit 0
}

decision_prevol_dh() {  # $1 = mesures ; écrit la référence ragdb, ou arrête
    local mesures="$1"
    printf '%s\n' "$mesures" > "$STATE_DIR/preflight.txt"
    grep '^LEGACY_' <<<"$mesures" > "$STATE_DIR/legacy_baseline.txt" || fail "pré-vol : ragdb non mesurée"
    [ "$(grep -c '^LEGACY_' "$STATE_DIR/legacy_baseline.txt")" = 7 ] || fail "pré-vol : mesure de ragdb incomplète"
    grep -qx 'TARGET_EXISTS=1' <<<"$mesures" || fail "pré-vol : base dédiée $DB absente — DH ne crée aucune base"
    grep -qx 'PRODUCT_ROWS=0:0:0' <<<"$mesures" \
        || fail "pré-vol : la base dédiée porte déjà des lignes produit — publication à expertiser, hors DH"
    ! grep -qE '^WORKER_B [^ ]+ (running|restarting|created|paused)$' <<<"$mesures" \
        || fail "pré-vol : un Worker B est actif — l'arrêter avant toute reprise"
    grep -qx "TRANSFER_MANIFEST=$(transfert_sha)" <<<"$mesures" \
        || fail "pré-vol : le manifeste de transfert de l'hôte n'est plus celui de V4"
    grep -qx 'GITHUB_TOKEN ok' <<<"$mesures" || fail "pré-vol : jeton GitHub absent"
}

etape_stale_job_cancellation() {
    autoriser_dh stale_job_cancellation
    local a j; a="$(plan_dh attestation_set_sha256)"; j="$(plan_dh job_set_sha256)"
    [ "$DRY_RUN" = 1 ] || [ "${DH_PREVIEW_ACK:-}" = "$a" ] \
        || fail "annulation : DH_PREVIEW_ACK doit reprendre l'empreinte relue de l'aperçu ($a)"
    outil_dh "$REMOTE_WORKER_ENV" 0 cancel-stale-jobs --attestation-set-sha256 "$a" --job-set-sha256 "$j" \
        | remote | tee "$STATE_DIR/cancel.out" || fail "annulation des jobs périmés"
    [ "$DRY_RUN" = 1 ] || grep -q '^STALE_JOBS_CANCELLED ' "$STATE_DIR/cancel.out" || fail "annulation : bilan absent"
    verifier_historique
    marquer stale_job_cancellation "$(grep -o 'review=.*' "$STATE_DIR/cancel.out" 2>/dev/null || echo dry-run)"
}

etape_stale_attestation_invalidation() {
    autoriser_dh stale_attestation_invalidation
    local a; a="$(plan_dh attestation_set_sha256)"
    outil_dh "$REMOTE_ATTESTOR_ENV" 1 invalidate-stale-attestations --attestation-set-sha256 "$a" \
        | remote | tee "$STATE_DIR/invalidate.out" || fail "invalidation des attestations périmées"
    [ "$DRY_RUN" = 1 ] || grep -q '^STALE_ATTESTATIONS_INVALIDATED ' "$STATE_DIR/invalidate.out" \
        || fail "invalidation : bilan absent"
    verifier_historique
    marquer stale_attestation_invalidation "$(grep -o 'review=.*' "$STATE_DIR/invalidate.out" 2>/dev/null || echo dry-run)"
}

etape_recovery_review_proposal() {
    autoriser_dh recovery_review_proposal
    local perimee; perimee="$(champ_dh stale_review.review_id)"
    [ "${BATCH_REVIEW_ID:?BATCH_REVIEW_ID}" != "$perimee" ] || fail "proposition : l'identifiant de revue $perimee est celui de #257"
    worker "$REMOTE_ATTESTOR_ENV" ingestor.ingestion_worker.attest_publication_cli propose-release-batch-review \
        --release-id "$(champ_dh release.release_id)" --release-dir "/repo/$(champ_dh release.release_dir)" \
        --release-manifest-sha256 "$(champ_dh release.release_manifest_sha256)" \
        --transfer-manifest-path /run-db/transfer_manifest_v4.json --transfer-manifest-sha256 "$(transfert_sha)" \
        --rights-registry-path /repo/services/rag-pedago/configs/rights_evidence_registry.yml \
        --review-id "$BATCH_REVIEW_ID" --evaluator "${EVALUATOR:?EVALUATOR : identité réelle}" \
        --pii-decision-set-path /repo/governance/pii-review-decisions/pii-review-2026-09-22-profile-gate-v3.json \
        --pii-review-receipt-path /repo/governance/pii-review-bindings/pii-review-2026-09-22-profile-gate-v3.json \
        --review-trust-anchor-path /repo/governance/trust-anchors/review-binding-v1.json \
        --pii-review-index-path /repo/docs/reports/evidence-index/pii_review_index_20260922_profile_gate_v3.json \
        --pii-review-reviewers-sha256 "$(sha256sum scripts/github/trusted-reviewers.json | cut -d' ' -f1)" \
        --repository-root /repo | remote | tee "$STATE_DIR/proposal.out" || fail "proposition de revue de reprise"
    verifier_historique
    [ "$DRY_RUN" = 1 ] && { marquer recovery_review_proposal "dry-run"; log "ATTENTE_HUMAINE: revue de reprise"; exit 0; }
    extraire_artefact_revue "$STATE_DIR/proposal.out"
    marquer recovery_review_proposal "$(cat "$STATE_DIR/proposal_artifact.txt")"
    log "ATTENTE_HUMAINE: ouvrir une NOUVELLE PR avec l'artefact, la faire approuver au head exact, la laisser OUVERTE jusqu'au closure-check"
    exit 0
}

exiger_revue_de_reprise() {
    [ "${BATCH_REVIEW_PR:?BATCH_REVIEW_PR}" != "$PR_PERIMEE" ] || fail "la revue #$PR_PERIMEE est fermée : elle ne fonde jamais une reprise"
    : "${BATCH_REVIEW_HEAD:?BATCH_REVIEW_HEAD}"
}

etape_recovery_review_record() {
    autoriser_dh recovery_review_record
    exiger_revue_de_reprise
    worker "$REMOTE_ATTESTOR_ENV" ingestor.ingestion_worker.attest_publication_cli record-release-batch-attestation \
        --release-id "$(champ_dh release.release_id)" --review-id "${BATCH_REVIEW_ID:?BATCH_REVIEW_ID}" \
        --repository cyranoaladin/RAG --pull-request "$BATCH_REVIEW_PR" --expected-head "$BATCH_REVIEW_HEAD" \
        --review-artifact-path "${BATCH_REVIEW_ARTIFACT:?BATCH_REVIEW_ARTIFACT}" \
        | remote | tee "$STATE_DIR/record.out" || fail "enregistrement des attestations de reprise"
    [ "$DRY_RUN" = 1 ] || grep -q '^RELEASE_BATCH_ATTESTATIONS_RECORDED ' "$STATE_DIR/record.out" || fail "enregistrement : bilan absent"
    verifier_historique
    marquer recovery_review_record "pr=$BATCH_REVIEW_PR head=$BATCH_REVIEW_HEAD"
}

precondition_de_revue() {  # $1 = enqueue | worker-b
    exiger_revue_de_reprise
    outil_dh "$REMOTE_WORKER_ENV" 1 review-precondition --pull-request "$BATCH_REVIEW_PR" \
        --expected-head "$BATCH_REVIEW_HEAD" --stage "$1" | remote | tee "$STATE_DIR/precondition-$1.out" \
        || fail "précondition de revue ($1) refusée"
    [ "$DRY_RUN" = 1 ] || grep -q "^REVIEW_PRECONDITION_OK stage=$1 " "$STATE_DIR/precondition-$1.out" \
        || fail "précondition de revue ($1) : bilan absent"
}

etape_recovery_job_enqueue() {
    autoriser_dh recovery_job_enqueue
    precondition_de_revue enqueue
    env_de_role "$REMOTE_WORKER_ENV"
    local attendu; attendu="$(cible_dh_champ recovery_job_enqueue expected_jobs)"
    remote <<EOF | tee "$STATE_DIR/enqueue.out" || fail "mise en file des jobs de reprise"
set -euo pipefail
cd $REMOTE/repo && git fetch -q origin && git checkout -q --detach $AUTH_COMMIT
$(tirer "$IMAGE")
docker run --rm --network host --env-file "$REMOTE_WORKER_ENV" \\
  -v "$REMOTE/repo:/repo:ro" -w /repo --entrypoint python "$IMAGE" \\
  /repo/scripts/go_live/staging_v4_enqueue_publication.py \\
  --release-id "$(champ_dh release.release_id)" --expected-jobs $attendu
EOF
    [ "$DRY_RUN" = 1 ] || grep -q "^PUBLICATION_JOBS_ENQUEUED .* total=$attendu\$" "$STATE_DIR/enqueue.out" \
        || fail "mise en file : total inattendu"
    verifier_historique
    marquer recovery_job_enqueue "$(grep -o 'crees=.*' "$STATE_DIR/enqueue.out" 2>/dev/null || echo dry-run)"
}

etape_recovery_worker_b_publication() {
    autoriser_dh recovery_worker_b_publication
    local nom="$WORKER_B_DH" attendu etat
    attendu="$(cible_dh_champ recovery_job_enqueue expected_jobs)"
    if [ "$DRY_RUN" = 1 ] || ! grep -qx "LANCE $nom" "$STATE_DIR/worker-b-dh.state" 2>/dev/null; then
        precondition_de_revue worker-b
        { echo "set -euo pipefail"
          echo "! docker inspect $nom >/dev/null 2>&1 || { echo 'WORKER_B_DEJA_PRESENT' >&2; exit 4; }"
          WORKER_DETACHE=$nom worker "$REMOTE_WORKER_ENV:$REMOTE_PUBLISHER_ENV" \
            ingestor.ingestion_worker.multilevel_publication_resume_cli \
            "$(args_de worker-b --transfer-sha256 "$(transfert_sha)" --embedding-root "/models/$MODELE_NOM")" \
            --max-iterations "$((attendu + 3))"
        } | remote || fail "Worker B : lancement"
        echo "LANCE $nom" > "$STATE_DIR/worker-b-dh.state"
    fi
    [ "$DRY_RUN" = 1 ] && { marquer recovery_worker_b_publication "dry-run"; return; }
    while :; do
        etat=$(echo "docker inspect --format '{{.State.Status}} {{.State.ExitCode}}' $nom" | remote) \
            || fail "Worker B : état illisible"
        case "$etat" in
            "exited "*) break ;;
            "running "*|"created "*|"restarting "*) sleep "${WORKER_B_POLL_S:-60}" ;;
            *) fail "Worker B : état inattendu ($etat)" ;;
        esac
    done
    echo "docker logs $nom 2>&1" | remote > "$STATE_DIR/worker-b-dh.out" || fail "Worker B : journal"
    [ "$etat" = "exited 0" ] || fail "Worker B : sortie $etat (journal : worker-b-dh.out, conteneur conservé)"
    grep -q 'authority_mode=RELEASE_BOUND_STAGING_QUALIFICATION' "$STATE_DIR/worker-b-dh.out" \
        || fail "Worker B : démarrage hors qualification liée à la release"
    [ "$(grep -c 'status=succeeded' "$STATE_DIR/worker-b-dh.out")" = "$attendu" ] \
        || fail "Worker B : $attendu publications attendues (journal : worker-b-dh.out, conteneur conservé)"
    echo "docker rm $nom >/dev/null" | remote || fail "Worker B : retrait du conteneur DH terminé"
    verifier_historique
    marquer recovery_worker_b_publication "succeeded=$attendu"
}

etape_recovery_independent_verification() {
    autoriser_dh recovery_independent_verification
    env_de_role "$REMOTE_READER_ENV"
    remote <<EOF | tee "$STATE_DIR/verification.txt" || fail "vérification"
set -euo pipefail
echo "PLACEMENTS=\$($(psql_ro "$DB" "select count(distinct collection)||' '||count(distinct artifact_id)||' '||count(*) from public.rag_artifact_placements"))"
echo "CHUNKS=\$($(psql_ro "$DB" "select count(distinct chunk_id) from public.rag_chunks"))"
$(tirer "$SONDE")
docker run --rm --network host --env-file "$REMOTE_READER_ENV" -e PYTHONPATH=/app \\
  -v "$REMOTE/repo:/repo:ro" -v "$RUN:/run-db" -w /app \\
  --entrypoint python "$SONDE" /repo/scripts/go_live/staging_retrieval_probe.py \\
  --repository-root /repo --output /run-db/retrieval-probe-dh.json
EOF
    verifier_historique
    [ "$DRY_RUN" = 1 ] && { marquer recovery_independent_verification "dry-run"; return; }
    grep -qx 'PLACEMENTS=11 315 479' "$STATE_DIR/verification.txt" || fail "vérification : placements inattendus"
    grep -qx 'CHUNKS=8268' "$STATE_DIR/verification.txt" || fail "vérification : chunks inattendus"
    grep -q '^SONDE_RETRIEVAL_V4 ' "$STATE_DIR/verification.txt" || fail "vérification : sonde de retrieval"
    marquer recovery_independent_verification "ok"
}

etape_recovery_review_closure_check() {
    autoriser_dh recovery_review_closure_check
    outil_dh "$REMOTE_WORKER_ENV" 0 closure-check | remote | tee "$STATE_DIR/closure.out" \
        || fail "fermeture : la revue de reprise est encore nécessaire — la laisser ouverte"
    [ "$DRY_RUN" = 1 ] || grep -q '^REVIEW_CLOSURE_SAFE ' "$STATE_DIR/closure.out" || fail "fermeture : bilan absent"
    marquer recovery_review_closure_check "$(grep -o 'REVIEW_CLOSURE_SAFE.*' "$STATE_DIR/closure.out" 2>/dev/null || echo dry-run)"
    log "ATTENTE_HUMAINE: la PR de revue de reprise peut être fusionnée ou fermée par un humain ; rien n'est fait automatiquement"
}

ORDRE_DH=(recovery_preflight stale_job_cancellation stale_attestation_invalidation
          recovery_review_proposal recovery_review_record recovery_job_enqueue
          recovery_worker_b_publication recovery_independent_verification recovery_review_closure_check)

# Sourcé (tests) : fonctions définies, rien n'est exécuté.
if [ "${BASH_SOURCE[0]}" != "$0" ]; then return 0; fi

case "${1:-}" in
    status)
        for e in "${ORDRE_DH[@]}"; do
            if fait "$e"; then echo "FAIT    $e $(cat "$STATE_DIR/$e.done")"; else echo "A_FAIRE $e"; fi
        done ;;
    run)
        jusqua=""; [ "${2:-}" = "--until" ] && jusqua="${3:?étape attendue}"
        if [ "$DRY_RUN" = 0 ]; then
            "$PYTHON" scripts/go_live/check_staging_authorization.py >/dev/null || fail "autorisation de base invalide"
        fi
        charger_autorisation_dh
        for e in "${ORDRE_DH[@]}"; do
            if fait "$e"; then log "DEJA_FAIT $e"; else "etape_$e"; fi
            if [ -n "$jusqua" ] && [ "$e" = "$jusqua" ]; then break; fi
        done ;;
    *) echo "usage: $0 [--dry-run] run [--until <étape>] | status" >&2; exit 2 ;;
esac
