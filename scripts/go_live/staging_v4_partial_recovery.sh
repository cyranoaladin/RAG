#!/usr/bin/env bash
# Orchestrateur DI : reprise PARTIELLE de la publication V4 sous la revue #262.
#
# Plan : docs/runbooks/staging_v4_partial_recovery_DI_EXECUTION_PLAN.md
# Chaque étape est soumise au vérificateur d'autorisation DI, sur sa cible
# exacte. Les fonctions de bas niveau (ssh, conteneurs, lecture seule,
# intangibilité de ragdb, outil DH) sont celles des orchestrateurs V4 et DH,
# sourcés en bibliothèque : aucune n'est recopiée.
#
#   scripts/go_live/staging_v4_partial_recovery.sh [--dry-run] run [--until <étape>]
#   scripts/go_live/staging_v4_partial_recovery.sh status
#
# État : $STATE_DIR (défaut ~/nexus-staging-v4-recovery-di, 0700).
set -euo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Un essai à blanc ne partage JAMAIS l'état du réel : ses marques « dry-run »
# feraient sauter des étapes réelles.
if [ "${1:-}" = "--dry-run" ]; then
    export STATE_DIR="${STATE_DIR:-$HOME/nexus-staging-v4-recovery-di-dry-run}"
else
    export STATE_DIR="${STATE_DIR:-$HOME/nexus-staging-v4-recovery-di}"
fi
export READINESS_LOCAL="${READINESS_LOCAL:-$HOME/nexus-staging-v4-di-readiness}"
_DI_DRY=""
[ "${1:-}" = "--dry-run" ] && { _DI_DRY="--dry-run"; shift; }
# shellcheck source=staging_v4_publication_recovery.sh
source "$ICI/staging_v4_publication_recovery.sh" $_DI_DRY

# La readiness DI : même release, image DI ; déposée À CÔTÉ de celle de V4.
READINESS_MANIFESTE="staging-readiness-v4-di.json"
AUTH_DI="docs/reports/go_live/authorizations/staging_v4_partial_recovery_authorization.json"
PROPOSITION_DI="docs/reports/go_live/authorizations/proposed/staging_v4_partial_recovery_authorization.json"
IDENTITE_DI="docs/reports/go_live/recovery/di_partial_v4_262.json"
OUTIL_DI="scripts/go_live/staging_v4_partial_recovery.py"
WORKER_B_DI="nexus-v4-worker-b-di"

cible_di() {
    "$PYTHON" -c "
import json,sys; sys.path.insert(0,'scripts/go_live')
import check_staging_authorization as a
print(json.dumps(a.OPERATIONS_DI[sys.argv[1]]['cible'], sort_keys=True))" "$1"
}
cible_di_champ() { cible_di "$1" | "$PYTHON" -c "import json,sys; v=json.load(sys.stdin)[sys.argv[1]]; print(' '.join(v) if isinstance(v, list) else v)" "$2"; }
autoriser_di() {
    local op="$1" sortie
    if [ "$HORS_LIGNE" = 1 ]; then
        log "SIMULATION: contrôle d'autorisation DI de $op non appelé (essai hors ligne)"; return 0
    fi
    if ! sortie=$("$PYTHON" scripts/go_live/check_staging_authorization.py \
            --operation "$op" --cible "$(cible_di "$op")" 2>&1); then
        log "$sortie"
        [ "$DRY_RUN" = 1 ] && { log "SIMULATION: $op serait refusée en réel"; return 0; }
        fail "$op non autorisée"
    fi
    log "AUTORISEE $op"
}
charger_autorisation_di() {
    if [ -f "$AUTH_DI" ]; then
        AUTH_SOURCE="$AUTH_DI"
        AUTH_COMMIT="$(git log -1 --format=%H -- "$AUTH_DI")"
    elif [ "$DRY_RUN" = 1 ]; then
        AUTH_SOURCE="$PROPOSITION_DI"
        AUTH_COMMIT="$(git rev-parse HEAD)"
        log "SIMULATION: autorisation DI absente, proposition lue pour l'essai à blanc"
    else
        fail "autorisation DI absente : $AUTH_DI (la proposition n'autorise rien)"
    fi
    if [ "$(champ_dh runtime_image.status 2>/dev/null || true)" = PENDING_BUILD_FROM_MAIN ]; then
        [ "$DRY_RUN" = 1 ] || fail "image DI en attente de construction : l'autorisation n'est pas active"
        IMAGE="ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:$(printf '0%.0s' {1..64})"
        log "SIMULATION: image DI en attente de construction — digest nul pour l'essai à blanc"
    else
        IMAGE="$(champ_dh runtime_image.reference)"
    fi
    SONDE="$(champ_dh probe_image.reference)"
    REVUE_PR="$(champ_dh active_review.pull_request)"
    REVUE_TETE="$(champ_dh active_review.head_sha)"
}

outil_di() {  # reste = arguments de l'outil DI ; rôle app, lecture seule, aucun jeton
    env_de_role "$REMOTE_WORKER_ENV"
    cat <<EOF2
set -euo pipefail
cd $REMOTE/repo && git fetch -q origin && git checkout -q --detach $AUTH_COMMIT
test -f "$REMOTE/repo/$OUTIL_DI" && test -f "$REMOTE/repo/$IDENTITE_DI"
$(tirer "$IMAGE")
docker run --rm --network host --env-file "$REMOTE_WORKER_ENV" \\
  -v "$REMOTE/repo:/repo:ro" -w /repo --entrypoint python "$IMAGE" \\
  /repo/$OUTIL_DI --repository-root /repo --identity /repo/$IDENTITE_DI $*
EOF2
}

# ── étapes ────────────────────────────────────────────────────────────────

etape_partial_readiness_install() {
    autoriser_di partial_readiness_install
    local f="$READINESS_MANIFESTE"
    [ -f "$READINESS_LOCAL/$f" ] || fail "manifeste DI signé absent : $READINESS_LOCAL/$f (sign_staging_v4_di_readiness_manifest.sh)"
    if [ "$DRY_RUN" = 0 ]; then
        echo "install -d -m 0700 $READINESS_REMOTE && test ! -e $READINESS_REMOTE/$f" | remote \
            || fail "readiness DI : destination (un manifeste DI existe déjà : rien n'est écrasé)"
        scp -q "$READINESS_LOCAL/$f" "$SSH_HOST:$READINESS_REMOTE/$f" || fail "readiness DI : dépôt"
    fi
    echo "cd $READINESS_REMOTE && chmod 600 $f && sha256sum $f staging-readiness-v4.json" | remote \
        || fail "readiness DI : vérification"
    marquer partial_readiness_install "$f"
}

decision_prevol_di() {  # $1 = mesures ; écrit la référence ragdb, ou arrête
    local mesures="$1"
    printf '%s\n' "$mesures" > "$STATE_DIR/preflight.txt"
    grep '^LEGACY_' <<<"$mesures" > "$STATE_DIR/legacy_baseline.txt" || fail "pré-vol : ragdb non mesurée"
    [ "$(grep -c '^LEGACY_' "$STATE_DIR/legacy_baseline.txt")" = 7 ] || fail "pré-vol : mesure de ragdb incomplète"
    ! grep -qE '^WORKER_B [^ ]+ (running|restarting|created|paused)$' <<<"$mesures" \
        || fail "pré-vol : un Worker B est actif — l'arrêter avant toute reprise"
    grep -qx 'GITHUB_TOKEN ok' <<<"$mesures" || fail "pré-vol : jeton GitHub absent"
}

etape_partial_preflight() {
    autoriser_di partial_preflight
    local mesures noms
    noms="$WORKER_B_V4 $WORKER_B_DH $(seq -f "$WORKER_B_DI-%g" 1 9 | tr '\n' ' ')"
    mesures=$(remote <<EOF3
set -euo pipefail
$(mesure_historique)
echo "PRODUCT_ROWS=\$($(psql_ro "$DB" "select (select count(*) from public.rag_artifacts)||':'||(select count(*) from public.rag_artifact_placements)||':'||(select count(*) from public.rag_chunks)"))"
for nom in $noms; do
    echo "WORKER_B \$nom \$(docker inspect --format '{{.State.Status}}' \$nom 2>/dev/null || echo absent)"
done
$(jeton_present)
echo "GITHUB_TOKEN ok"
EOF3
) || fail "pré-vol DI : mesures"
    [ "$DRY_RUN" = 1 ] || decision_prevol_di "$mesures"
    outil_di partial-precondition | remote | tee "$STATE_DIR/partial-precondition.out" \
        || fail "précondition partielle refusée (voir partial-precondition.out)"
    outil_dh "$REMOTE_WORKER_ENV" 1 review-precondition --pull-request "$REVUE_PR" \
        --expected-head "$REVUE_TETE" --stage worker-b | remote | tee "$STATE_DIR/precondition-worker-b.out" \
        || fail "précondition de revue #$REVUE_PR refusée"
    verifier_historique
    if [ "$DRY_RUN" = 1 ]; then
        printf 'excluded_jobs_sha256=%s\n' "$(printf 'e%.0s' {1..64})" > "$STATE_DIR/partial_plan.txt"
        marquer partial_preflight "dry-run"; return
    fi
    grep -q '^REVIEW_PRECONDITION_OK stage=worker-b ' "$STATE_DIR/precondition-worker-b.out" \
        || fail "précondition de revue : bilan absent"
    local empreinte
    empreinte=$(sed -nE 's/^PARTIAL_PRECONDITION_OK .*excluded_jobs_sha256=([0-9a-f]{64}).*$/\1/p' \
        "$STATE_DIR/partial-precondition.out")
    [ -n "$empreinte" ] || fail "précondition partielle : empreinte des jobs exclus absente"
    # L'empreinte de RÉFÉRENCE est celle du premier pré-vol : une relance doit
    # la reproduire à l'identique, jamais la remplacer.
    if [ -f "$STATE_DIR/partial_plan.txt" ]; then
        grep -qx "excluded_jobs_sha256=$empreinte" "$STATE_DIR/partial_plan.txt" \
            || fail "jobs exclus modifiés depuis le premier pré-vol — arrêt"
    else
        echo "excluded_jobs_sha256=$empreinte" > "$STATE_DIR/partial_plan.txt"
    fi
    marquer partial_preflight "$(grep -o 'claim_scope=.*' "$STATE_DIR/partial-precondition.out")"
}

nom_worker_b_di() { echo "$WORKER_B_DI-$(( $(grep -c '^LANCE ' "$STATE_DIR/worker-b-di.state" 2>/dev/null || true) + ${1:-0} ))"; }

etape_partial_worker_b_publication() {
    autoriser_di partial_worker_b_publication
    local nom etat collections args_scope="" c a_publier
    collections="$(cible_di_champ partial_worker_b_publication claimed_collections)"
    for c in $collections; do args_scope+="--collection $c "; done
    a_publier=$(sed -nE 's/^PARTIAL_PRECONDITION_OK .*to_publish=([0-9]+).*$/\1/p' \
        "$STATE_DIR/partial-precondition.out" 2>/dev/null || true)
    if [ "$DRY_RUN" = 1 ] || ! grep -q '^LANCE ' "$STATE_DIR/worker-b-di.state" 2>/dev/null \
            || grep -q '^RELANCE_DEMANDEE' "$STATE_DIR/worker-b-di.state"; then
        nom="$(nom_worker_b_di 1)"
        { echo "set -euo pipefail"
          echo "! docker inspect $nom >/dev/null 2>&1 || { echo 'WORKER_B_DEJA_PRESENT' >&2; exit 4; }"
          WORKER_DETACHE=$nom worker "$REMOTE_WORKER_ENV:$REMOTE_PUBLISHER_ENV" \
            ingestor.ingestion_worker.multilevel_publication_resume_cli \
            "$(args_de worker-b --transfer-sha256 "$(transfert_sha)" --embedding-root "/models/$MODELE_NOM")" \
            "$args_scope" \
            --min-job-interval-s "$(cible_di_champ partial_worker_b_publication min_job_interval_s)" \
            --rate-limit-max-wait-s "$(cible_di_champ partial_worker_b_publication rate_limit_max_wait_s)" \
            --max-consecutive-rate-limits "$(cible_di_champ partial_worker_b_publication max_consecutive_rate_limits)" \
            --max-idle-polls "$(cible_di_champ partial_worker_b_publication max_idle_polls)" \
            --max-iterations "$(( 3 * ${a_publier:-405} + 50 ))"
        } | remote || fail "Worker B DI : lancement"
        echo "LANCE $nom" >> "$STATE_DIR/worker-b-di.state"
        sed -i '/^RELANCE_DEMANDEE/d' "$STATE_DIR/worker-b-di.state"
    fi
    [ "$DRY_RUN" = 1 ] && { marquer partial_worker_b_publication "dry-run"; return; }
    nom="$(sed -n 's/^LANCE //p' "$STATE_DIR/worker-b-di.state" | tail -1)"
    while :; do
        etat=$(echo "docker inspect --format '{{.State.Status}} {{.State.ExitCode}}' $nom" | remote) \
            || fail "Worker B DI : état illisible"
        case "$etat" in
            "exited "*) break ;;
            "running "*|"created "*|"restarting "*) sleep "${WORKER_B_POLL_S:-60}" ;;
            *) fail "Worker B DI : état inattendu ($etat)" ;;
        esac
    done
    echo "docker logs $nom 2>&1" | remote > "$STATE_DIR/$nom.out" || fail "Worker B DI : journal"
    grep -q "MULTILEVEL_PUBLICATION_WORKER_CLAIM_SCOPE collections=$(tr ' ' ',' <<<"$collections")" \
        "$STATE_DIR/$nom.out" || fail "Worker B DI : liste d'autorisation absente du démarrage"
    grep -q 'authority_mode=RELEASE_BOUND_STAGING_QUALIFICATION' "$STATE_DIR/$nom.out" \
        || fail "Worker B DI : démarrage hors qualification liée à la release"
    verifier_historique
    case "$etat" in
        "exited 0") ;;
        "exited 75")
            echo "ARRET_LIMITATION $nom" >> "$STATE_DIR/worker-b-di.state"
            fail "Worker B DI : limitation GitHub persistante (code 75) ; file intacte, aucune tentative consommée par la limitation. Relancer plus tard avec DI_RELAUNCH=1 (le pré-vol est refait)" ;;
        *) fail "Worker B DI : sortie $etat (journal : $nom.out, conteneur conservé)" ;;
    esac
    marquer partial_worker_b_publication "$nom $(grep -c 'status=succeeded' "$STATE_DIR/$nom.out") succeeded"
}

etape_partial_independent_verification() {
    autoriser_di partial_independent_verification
    local collections args_sonde="" c
    collections="$(cible_di_champ partial_worker_b_publication claimed_collections)"
    for c in $collections; do args_sonde+="--collection $c "; done
    env_de_role "$REMOTE_READER_ENV"
    remote <<EOF4 | tee "$STATE_DIR/verification.txt" || fail "vérification"
set -euo pipefail
echo "PLACEMENTS=\$($(psql_ro "$DB" "select count(distinct collection)||' '||count(distinct artifact_id)||' '||count(*) from public.rag_artifact_placements"))"
echo "CHUNKS=\$($(psql_ro "$DB" "select count(distinct chunk_id) from public.rag_chunks"))"
echo "HGGSP=\$($(psql_ro "$DB" "select count(*) from public.rag_artifact_placements where collection like 'rag_nexus_hggsp_%'"))"
$(tirer "$SONDE")
docker run --rm --network host --env-file "$REMOTE_READER_ENV" -e PYTHONPATH=/app \\
  -v "$REMOTE/repo:/repo:ro" -v "$RUN:/run-db" -w /app \\
  --entrypoint python "$SONDE" /repo/scripts/go_live/staging_retrieval_probe.py \\
  --repository-root /repo --output /run-db/retrieval-probe-di.json $args_sonde
EOF4
    verifier_historique
    [ "$DRY_RUN" = 1 ] && { marquer partial_independent_verification "dry-run"; return; }
    grep -qx 'PLACEMENTS=9 263 405' "$STATE_DIR/verification.txt" || fail "vérification : placements inattendus"
    grep -qx 'CHUNKS=5678' "$STATE_DIR/verification.txt" || fail "vérification : chunks inattendus"
    grep -qx 'HGGSP=0' "$STATE_DIR/verification.txt" || fail "vérification : un placement HGGSP existe"
    grep -q '^SONDE_RETRIEVAL_V4 ' "$STATE_DIR/verification.txt" || fail "vérification : sonde de retrieval"
    marquer partial_independent_verification "ok"
}

etape_partial_closure_check() {
    autoriser_di partial_closure_check
    local empreinte
    empreinte="$(sed -n 's/^excluded_jobs_sha256=//p' "$STATE_DIR/partial_plan.txt")"
    outil_di partial-closure-check --excluded-jobs-sha256 "$empreinte" | remote | tee "$STATE_DIR/partial-closure.out" \
        || fail "contrôle partiel refusé (voir partial-closure.out)"
    [ "$DRY_RUN" = 1 ] || grep -q '^DI_PARTIAL_PUBLICATION_COMPLETE .*review_closure=NOT_SAFE' "$STATE_DIR/partial-closure.out" \
        || fail "contrôle partiel : bilan absent"
    marquer partial_closure_check "$(grep -o 'published=.*' "$STATE_DIR/partial-closure.out" 2>/dev/null || echo dry-run)"
    log "ATTENTE_HUMAINE: la revue #$REVUE_PR reste OUVERTE — 74 placements HGGSP attendent la décision sur la release successeur"
}

ORDRE_DI=(partial_readiness_install partial_preflight partial_worker_b_publication
          partial_independent_verification partial_closure_check)

# Sourcé (tests) : fonctions définies, rien n'est exécuté.
if [ "${BASH_SOURCE[0]}" != "$0" ]; then return 0; fi

case "${1:-}" in
    status)
        for e in "${ORDRE_DI[@]}"; do
            if fait "$e"; then echo "FAIT    $e $(cat "$STATE_DIR/$e.done")"; else echo "A_FAIRE $e"; fi
        done ;;
    run)
        jusqua=""; [ "${2:-}" = "--until" ] && jusqua="${3:?étape attendue}"
        if [ "$DRY_RUN" = 0 ]; then
            ! grep -qsx 'dry-run' "$STATE_DIR"/*.done "$STATE_DIR/partial_plan.txt" 2>/dev/null \
                && ! grep -qs "^excluded_jobs_sha256=$(printf 'e%.0s' {1..64})\$" "$STATE_DIR/partial_plan.txt" \
                || fail "état d'essai à blanc dans $STATE_DIR : le réel exige un état propre"
            "$PYTHON" scripts/go_live/check_staging_authorization.py >/dev/null || fail "autorisation de base invalide"
        fi
        charger_autorisation_di
        if [ "${DI_RELAUNCH:-0}" = 1 ]; then
            grep -q '^ARRET_LIMITATION ' "$STATE_DIR/worker-b-di.state" 2>/dev/null \
                || fail "DI_RELAUNCH : aucun arrêt pour limitation constaté"
            rm -f "$STATE_DIR/partial_preflight.done"
            echo "RELANCE_DEMANDEE" >> "$STATE_DIR/worker-b-di.state"
        fi
        for e in "${ORDRE_DI[@]}"; do
            if fait "$e"; then log "DEJA_FAIT $e"; else "etape_$e"; fi
            if [ -n "$jusqua" ] && [ "$e" = "$jusqua" ]; then break; fi
        done ;;
    *) echo "usage: $0 [--dry-run] run [--until <étape>] | status" >&2; exit 2 ;;
esac
