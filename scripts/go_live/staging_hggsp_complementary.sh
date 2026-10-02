#!/usr/bin/env bash
# Complément HGGSP : commandes futures seulement, après fusion de l'autorité.
# Aucun retrait des anciens jobs V4, aucune fermeture de #262.
# Usage : staging_hggsp_complementary.sh status | [--dry-run] run [--until ETAPE]
set -euo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${STATE_DIR:-$HOME/nexus-staging-hggsp-complementary}"
V4_STATE_DIR="${V4_STATE_DIR:-$HOME/nexus-staging-v4-run}"
_HGGSP_DRY=""
[ "${1:-}" = "--dry-run" ] && { _HGGSP_DRY="--dry-run"; shift; }
# Fonctions de transport, rôles et contrôle historique déjà qualifiées.
# shellcheck source=staging_v4_publication_recovery.sh
source "$ICI/staging_v4_publication_recovery.sh" $_HGGSP_DRY

AUTH_HGGSP="docs/reports/go_live/authorizations/staging_hggsp_complementary_authorization.json"
CHECKER="scripts/go_live/check_staging_authorization.py"
PREFLIGHT="scripts/go_live/staging_hggsp_complementary.py"
SCOPES="scripts/go_live/build_hggsp_successor_r4_authorizations.py"
READINESS_CHECK="scripts/go_live/hggsp_successor_readiness.py"
RELEASE_HGGSP="production-profile-gate-2026-2027-v5-hggsp"
COLLECTION_P="rag_nexus_hggsp_premiere_specialite"
COLLECTION_T="rag_nexus_hggsp_terminale_specialite"
OLD_JOBS_SHA256="fef6d99df13b08c3ea02f79f29be94fa5f8d12a639ef7af85989bfcdaba6af31"
READINESS_LOCAL="${HGGSP_READINESS_LOCAL:-$HOME/nexus-staging-hggsp-successor-readiness}"
READINESS_MANIFESTE="staging-readiness-hggsp-successor.json"
READINESS_BINDING="staging-readiness-hggsp-successor-binding.json"
TRANSFER_HOST="$RUN/transfer_manifest_hggsp_successor.json"
TRANSFER_CONTAINER="/run-db/transfer_manifest_hggsp_successor.json"
WORKER_B_HGGSP="nexus-hggsp-successor-worker-b"
PROBE_IMAGE=""
CONTROL020="scripts/go_live/hggsp_control_schema_020.py"
# Adoption V2 : sixième fichier par rôle, et secret adopter conservé hors Git.
REMOTE_ADOPTER_ENV="$REMOTE_ROLES/ingestion-control-adopter.env"
REMOTE_ADOPTER_SECRET_DIR="$REMOTE/secrets/hggsp-adopter"
REMOTE_ADOPTER_SECRET="$REMOTE_ADOPTER_SECRET_DIR/ingestion_control_adopter.password"

ORDRE_HGGSP=(
    successor_readiness_install successor_preflight
    successor_control_schema_020_and_adopter_role
    successor_scope_authorization_registration_r4 successor_sealed_ingestion_or_binding
    successor_batch_review_proposal successor_batch_review_record
    successor_attestations successor_publication_job_enqueue successor_worker_b_publication
    successor_independent_verification
)

champ_hggsp() {
    "$PYTHON" - "$AUTH_HGGSP" "$1" <<'PY'
import json, sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
for key in sys.argv[2].split("."):
    value = value[key]
print(value)
PY
}
cible_hggsp() {
    "$PYTHON" - "$1" <<'PY'
import json, sys
sys.path.insert(0, "scripts/go_live")
import check_staging_authorization as auth
print(json.dumps(auth.OPERATIONS_HGGSP[sys.argv[1]]["cible"], sort_keys=True))
PY
}
autoriser_hggsp() {
    local op="$1" cible sortie
    cible="$(cible_hggsp "$op")" || fail "opération HGGSP inconnue : $op"
    if ! sortie=$("$PYTHON" "$CHECKER" --operation "$op" --cible "$cible" 2>&1); then
        log "$sortie"
        fail "$op refusée par l'autorité active"
    fi
    log "AUTORISEE $op"
}
readiness_locale() {
    "$PYTHON" "$READINESS_CHECK" verify --bundle-dir "$READINESS_LOCAL" >/dev/null \
        || fail "readiness successeur absente ou invalide"
}
readiness_distante() {
    local attendu_v1 attendu_binding observe
    attendu_v1="$(sha256sum "$READINESS_LOCAL/$READINESS_MANIFESTE" | cut -d' ' -f1)"
    attendu_binding="$(sha256sum "$READINESS_LOCAL/$READINESS_BINDING" | cut -d' ' -f1)"
    if [ "$DRY_RUN" = 1 ]; then
        log "SIMULATION : deux empreintes de readiness distante comparées aux fichiers signés locaux"
        return
    fi
    observe=$(remote <<EOF
set -euo pipefail
test -f "$READINESS_REMOTE/$READINESS_MANIFESTE"
test -f "$READINESS_REMOTE/$READINESS_BINDING"
sha256sum "$READINESS_REMOTE/$READINESS_MANIFESTE" "$READINESS_REMOTE/$READINESS_BINDING"
EOF
) || fail "readiness distante indisponible"
    grep -qx "$attendu_v1  $READINESS_REMOTE/$READINESS_MANIFESTE" <<<"$observe" \
        || fail "readiness V1 distante différente de celle signée localement"
    grep -qx "$attendu_binding  $READINESS_REMOTE/$READINESS_BINDING" <<<"$observe" \
        || fail "liaison signée distante différente de celle vérifiée localement"
}
images_locales() {
    # Les deux images sont contrôlées LOCALEMENT, avant le premier SSH. Le
    # registre de scopes est celui installé DANS l'image retrieval épinglée.
    local image scope1 scope2 ids
    IMAGE="$(champ_hggsp runtime_image.reference)"
    PROBE_IMAGE="$(champ_hggsp retrieval_image.reference)"
    [ "$IMAGE" = 'ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:2228650e2245ea2fdc45d442a78363fd362781c2f80e2270618eedca0abf9bcf' ] \
        || fail "digest Worker B divergent"
    [ "$PROBE_IMAGE" = 'ghcr.io/cyranoaladin/rag-ingestor@sha256:11aa98d58ebcd10ee09543d4791f63b67542b764ab0484f004cccc8d43e86caf' ] \
        || fail "digest retrieval divergent"
    "$PYTHON" packages/contracts/scripts/build_hggsp_successor_scope_artifacts.py --check \
        || fail "autorités de scopes successeurs #269 divergentes"
    "$PYTHON" "$SCOPES" --check || fail "autorisations r4 successeurs divergentes"
    ids=$("$PYTHON" - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path("packages/contracts/src").resolve()))
sys.path.insert(0, "scripts/go_live")
from nexus_contracts import load_retrieval_scope_registry
import yaml
authority = yaml.safe_load(Path("packages/contracts/authorities/production-profile-scope-successors-hggsp-v5.yml").read_text())
ids = [binding["scope_id"] for binding in authority["bindings"]]
registry = load_retrieval_scope_registry()
if len(ids) != 2 or any(scope not in registry for scope in ids):
    raise SystemExit("deux scopes successeur requis")
print(" ".join(ids))
PY
) || fail "scopes successeur non dérivables"
    read -r scope1 scope2 <<<"$ids"
    [ -n "$scope1" ] && [ -n "$scope2" ] && [ "$(wc -w <<<"$ids")" = 2 ] \
        || fail "deux scopes successeur exactement requis"
    if [ "$DRY_RUN" = 1 ]; then
        log "SIMULATION : inspection des deux images locales et des deux scopes installés"
        return
    fi
    for image in "$IMAGE" "$PROBE_IMAGE"; do
        docker image inspect "$image" >/dev/null 2>&1 || docker pull -q "$image" >/dev/null \
            || fail "image épinglée inaccessible : $image"
    done
    docker run --rm --pull=never --network none "$PROBE_IMAGE" python -c '
import sys
from nexus_contracts import load_retrieval_scope_registry
registry = load_retrieval_scope_registry()
if any(scope not in registry for scope in sys.argv[1:]):
    raise SystemExit("scopes successeur absents de l image retrieval épinglée")
' "$scope1" "$scope2" || fail "image retrieval épinglée incapable de servir les scopes successeur"
}

phase_hggsp() {
    case "$1" in
        successor_batch_review_record)
            if [ -f "$STATE_DIR/batch-record.attempt" ]; then echo record_replay; else echo prepare; fi ;;
        successor_publication_job_enqueue)
            if [ -f "$STATE_DIR/enqueue.attempt" ]; then echo enqueue_replay; else echo enqueue; fi ;;
        successor_worker_b_publication) echo publish ;;
        successor_independent_verification) echo verify ;;
        successor_attestations) echo attested ;;
        *) echo prepare ;;
    esac
}

preflight_hggsp() {
    local op="$1" phase
    autoriser_hggsp "$op"
    readiness_locale
    if [ "$op" != successor_readiness_install ]; then readiness_distante; fi
    phase="$(phase_hggsp "$op")"
    # Contrôle indépendant du rôle app et du rôle reader. La comparaison
    # historique, mesurée au premier prévol, reste obligatoire après chaque
    # étape. La revue #262 est relue en direct dans le CLI.
    if [ ! -f "$STATE_DIR/legacy_baseline.txt" ]; then
        [ "$op" = successor_readiness_install ] || [ "$op" = successor_preflight ] \
          || fail "prévol initial et baseline ragdb absents"
        if [ "$DRY_RUN" = 0 ]; then
            { echo "set -euo pipefail"; mesure_historique; } | remote > "$STATE_DIR/legacy_baseline.txt" \
                || fail "mesure initiale de ragdb impossible"
            [ "$(grep -c '^LEGACY_' "$STATE_DIR/legacy_baseline.txt")" = 7 ] \
                || fail "mesure de ragdb incomplète"
        fi
    fi
    if [ "$DRY_RUN" = 0 ]; then
        [ -f "$V4_STATE_DIR/legacy_baseline.txt" ] \
            || fail "baseline historique V4 absente"
        cmp -s "$V4_STATE_DIR/legacy_baseline.txt" "$STATE_DIR/legacy_baseline.txt" \
            || fail "ragdb historique différente du prévol V4"
    fi
    local baseline_sha current_sha
    if [ "$DRY_RUN" = 0 ]; then
        { echo "set -euo pipefail"; mesure_historique; } | remote > "$STATE_DIR/legacy-current.txt" \
            || fail "ragdb : mesure courante impossible"
        cmp -s "$STATE_DIR/legacy_baseline.txt" "$STATE_DIR/legacy-current.txt" \
            || fail "ragdb historique modifiée depuis le prévol initial"
        baseline_sha="$(sha256sum "$STATE_DIR/legacy_baseline.txt" | cut -d' ' -f1)"
        current_sha="$(sha256sum "$STATE_DIR/legacy-current.txt" | cut -d' ' -f1)"
    else
        baseline_sha="$(printf '0%.0s' {1..64})"
        current_sha="$baseline_sha"
    fi
    if [ "$DRY_RUN" = 1 ]; then
        log "SIMULATION : prévol $phase en lecture seule, revue #262 live, vieux jobs SHA $OLD_JOBS_SHA256"
        return
    fi
    env_de_role "$REMOTE_WORKER_ENV" "$REMOTE_READER_ENV"
    remote <<EOF | tee "$STATE_DIR/$op.preflight" || fail "prévol HGGSP $op refusé"
set -euo pipefail
cd $REMOTE/repo && git fetch -q origin && git checkout -q --detach $AUTH_COMMIT
$(jeton_present)
$(tirer "$IMAGE")
docker run --rm --network host --env-file "$REMOTE_WORKER_ENV" --env-file "$REMOTE_READER_ENV" \\
  -e NEXUS_GITHUB_TOKEN_FILE=/run/secrets/github-token \\
  -v "$REMOTE_GITHUB_TOKEN_FILE:/run/secrets/github-token:ro" \\
  -v "$REMOTE/repo:/repo:ro" -w /repo --entrypoint python "$IMAGE" \\
  /repo/$PREFLIGHT --phase "$phase" \\
  --legacy-baseline-sha256 "$baseline_sha" --legacy-current-sha256 "$current_sha"
EOF
    grep -q '^HGGSP_PREFLIGHT_OK ' "$STATE_DIR/$op.preflight" || fail "bilan de prévol absent"
}

charger_hggsp() {
    [ -f "$AUTH_HGGSP" ] || fail "autorisation HGGSP active absente (proposition inactive)"
    AUTH_COMMIT="$(git rev-parse HEAD)"
    [ "$AUTH_COMMIT" = "$(git rev-parse origin/main)" ] \
      || fail "checkout opérateur différent de origin/main fusionné"
    IMAGE="$(champ_hggsp runtime_image.reference)"
    PROBE_IMAGE="$(champ_hggsp retrieval_image.reference)"
}

transfer_sha() {
    local digest
    digest="$(sed -n 's/^sha256=//p' "$STATE_DIR/successor_sealed_ingestion_or_binding.transfer" 2>/dev/null)"
    [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || fail "empreinte du manifeste de transfert successeur absente"
    printf '%s' "$digest"
}

ids_r4() {
    "$PYTHON" "$SCOPES" --ids || fail "deux autorisations r4 introuvables"
}

etape_successor_readiness_install() {
    local file expected observed
    for file in "$READINESS_MANIFESTE" "$READINESS_BINDING"; do
        [ -f "$READINESS_LOCAL/$file" ] || fail "readiness signée manquante : $file"
        expected="$(sha256sum "$READINESS_LOCAL/$file" | cut -d' ' -f1)"
        if [ "$DRY_RUN" = 0 ]; then
            if echo "test -f '$READINESS_REMOTE/$file'" | remote >/dev/null 2>&1; then
                observed="$(echo "sha256sum '$READINESS_REMOTE/$file'" | remote | cut -d' ' -f1)"
                [ "$observed" = "$expected" ] || fail "readiness distante déjà présente mais divergente : $file"
            else
                echo "install -d -m 0700 '$READINESS_REMOTE' && test ! -e '$READINESS_REMOTE/$file'" | remote \
                    || fail "destination readiness indisponible : $file"
                scp -q "$READINESS_LOCAL/$file" "$SSH_HOST:$READINESS_REMOTE/$file" \
                    || fail "installation readiness $file"
            fi
            observed="$(echo "chmod 600 '$READINESS_REMOTE/$file' && sha256sum '$READINESS_REMOTE/$file'" | remote | cut -d' ' -f1)"
            [ "$observed" = "$expected" ] || fail "readiness installée divergente : $file"
        fi
    done
    readiness_distante
    marquer successor_readiness_install "deux fichiers signés, V4 conservée"
}

etape_successor_preflight() {
    marquer successor_preflight "V4=9/263/405/5678 HGGSP=0 vieux_jobs=$OLD_JOBS_SHA256 ragdb inchangée"
}

etape_successor_control_schema_020_and_adopter_role() {
    # Base de contrôle ragdb_profile_gate_v4 : 019 -> 020 par le runner
    # canonique, puis le SEUL rôle adopter (provisionneur ciblé, aucun autre
    # rôle touché). Le secret est créé et conservé sur l'hôte AVANT le rôle ;
    # il n'apparaît dans aucun argument ni aucune sortie. Le compte
    # administratif (superutilisateur du conteneur) reste confiné à cette
    # étape : il n'est transmis à aucun conteneur. La logique, les reprises
    # et les refus sont dans $CONTROL020 ; chaque exécution repart de l'état
    # réel, le marqueur .done n'en dispense pas.
    local stamp; stamp=$(date -u +%Y%m%dT%H%M%SZ)
    remote <<EOF | tee "$STATE_DIR/control020.out" || fail "migration 020 / rôle adopter refusés"
set -euo pipefail
umask 077
command -v psql >/dev/null || { echo "psql absent de l'hôte" >&2; exit 4; }
cd $REMOTE/repo && git fetch -q origin && git checkout -q --detach $AUTH_COMMIT
ids=\$(docker ps -q) || { echo "INSPECTION_DOCKER_IMPOSSIBLE : aucune migration" >&2; exit 4; }
if [ -n "\$ids" ]; then
    docker inspect \$ids | python3 $REMOTE/repo/scripts/go_live/worker_b_guard.py \\
        || { echo "WORKER_B_ACTIF_OU_INSPECTION_AMBIGUE : aucune migration" >&2; exit 4; }
fi
taille=\$($(psql_ro "$DB" "select pg_database_size(current_database())"))
libre=\$(df -B1 --output=avail $REMOTE/backups | tail -1)
test "\$libre" -gt "\$((taille * 3))" || { echo "DISQUE_INSUFFISANT pour la sauvegarde" >&2; exit 4; }
install -d -m 0700 $REMOTE_ADOPTER_SECRET_DIR
d=$REMOTE/backups/hggsp-020-$stamp; install -d -m 0700 "\$d"
docker exec $CONTAINER sh -c 'pg_dump -Fc -U "\$POSTGRES_USER" $DB' > "\$d/$DB.dump"
test -s "\$d/$DB.dump"; chmod 600 "\$d/$DB.dump"
docker exec -i $CONTAINER pg_restore --list < "\$d/$DB.dump" > /dev/null \\
    || { echo "SAUVEGARDE_ILLISIBLE" >&2; exit 4; }
(
    set -a; . "$REMOTE_STAGING_ENV"; set +a
    export PGHOST=127.0.0.1 PGPORT="\$PGVECTOR_PORT" PGDATABASE=$DB
    export PGUSER=\$(docker exec $CONTAINER printenv POSTGRES_USER) PGPASSWORD="\$PGVECTOR_PASSWORD"
    python3 $CONTROL020 apply --repository-root $REMOTE/repo \\
        --secret-file $REMOTE_ADOPTER_SECRET --roles-dir $REMOTE_ROLES --backup-file "\$d/$DB.dump"
)
EOF
    [ "$DRY_RUN" = 1 ] && { marquer successor_control_schema_020_and_adopter_role "dry-run"; return; }
    grep -q '^HGGSP_CONTROL020_OK head=20 adopter=ingestion_control_adopter ' "$STATE_DIR/control020.out" \
        || fail "020 et rôle adopter non prouvés"
    verifier_historique
    marquer successor_control_schema_020_and_adopter_role "head=20, adopter provisionné, secret conservé, DSN 0600"
}

exiger_revue_scopes() {
    if [ -z "${SCOPE_REVIEW_PR:-}" ] || [ -z "${SCOPE_REVIEW_HEAD:-}" ]; then
        fail "revue humaine distincte des deux r4 absente : SCOPE_REVIEW_PR et SCOPE_REVIEW_HEAD requis"
    fi
    [[ "$SCOPE_REVIEW_PR" =~ ^[1-9][0-9]*$ ]] || fail "numéro de PR scopes invalide"
    [ "$SCOPE_REVIEW_PR" != 262 ] || fail "#262 n'est pas la revue des scopes successeurs"
    "$PYTHON" scripts/github/trusted_human_review_github.py --repository cyranoaladin/RAG \
        --pull-request "$SCOPE_REVIEW_PR" --expected-head "$SCOPE_REVIEW_HEAD" --check \
        > "$STATE_DIR/scope-review.json" || fail "revue humaine scopes non approuvée au HEAD exact"
}

etape_successor_scope_authorization_registration_r4() {
    local id ids
    "$PYTHON" "$SCOPES" --check || fail "deux r4 HGGSP successeurs non conformes"
    exiger_revue_scopes
    ids="$(ids_r4)"
    env_de_role "$REMOTE_AUTHORITY_ENV"
    for id in $ids; do
        remote <<EOF | tee -a "$STATE_DIR/scope-registration.out" || fail "enregistrement r4 $id refusé"
set -euo pipefail
$(jeton_present)
$(tirer "$IMAGE")
docker run --rm --network host --env-file "$REMOTE_AUTHORITY_ENV" \\
  -e NEXUS_GITHUB_TOKEN_FILE=/run/secrets/github-token \\
  -v "$REMOTE_GITHUB_TOKEN_FILE:/run/secrets/github-token:ro" \\
  --entrypoint python "$IMAGE" -m ingestor.ingestion_worker.authorize_scope_cli \\
  record-authorization --authorization-id "$id" --repository cyranoaladin/RAG \\
  --pull-request "${SCOPE_REVIEW_PR:?SCOPE_REVIEW_PR}" --expected-head "${SCOPE_REVIEW_HEAD:?SCOPE_REVIEW_HEAD}"
EOF
    done
    verifier_historique
    marquer successor_scope_authorization_registration_r4 "count=2 review=$SCOPE_REVIEW_PR@$SCOPE_REVIEW_HEAD"
}

etape_successor_sealed_ingestion_or_binding() {
    # Les 74 ressources V4 HGGSP existent déjà ; adoption canonique bornée
    # par le manifeste successeur (74 placements), jamais réingestion des 405.
    remote <<EOF | tee "$STATE_DIR/transfer.out" || fail "52 PDF : empreintes divergentes"
set -euo pipefail
$(jeton_present)
$(tirer "$IMAGE")
docker run --rm --network host -v "$REMOTE/repo:/repo:ro" \\
  -v "$REMOTE/artifact-store:/store:ro" -v "$RUN:/run-db" \\
  -e NEXUS_GITHUB_TOKEN_FILE=/run/secrets/github-token \\
  -v "$REMOTE_GITHUB_TOKEN_FILE:/run/secrets/github-token:ro" \\
  -w /repo --entrypoint python "$IMAGE" /repo/$PREFLIGHT \\
  --build-transfer-manifest --repository-root /repo --artifact-store /store \\
  --output "$TRANSFER_CONTAINER"
EOF
    [ "$DRY_RUN" = 1 ] && { marquer successor_sealed_ingestion_or_binding "dry-run"; return; }
    local digest
    digest="$(sed -nE 's/^HGGSP_TRANSFER_OK sha256=([0-9a-f]{64})$/\1/p' "$STATE_DIR/transfer.out")"
    [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || fail "empreinte transfert absente"
    echo "test \"\$(sha256sum '$TRANSFER_HOST' | cut -d' ' -f1)\" = '$digest'" | remote \
        || fail "manifeste de transfert hôte différent de celui du conteneur"
    printf 'sha256=%s\n' "$digest" > "$STATE_DIR/successor_sealed_ingestion_or_binding.transfer"
    local release_dir registry_sha inventory_sha
    release_dir="/repo/$(champ_hggsp release.release_dir)"
    registry_sha="$("$PYTHON" - <<'PY'
import json
from pathlib import Path
auth=json.loads(Path("docs/reports/go_live/authorizations/staging_hggsp_complementary_authorization.json").read_text())
release=Path(auth["release"]["release_dir"])
manifest=json.loads((release/"production-profile-gate.release.json").read_text())
print(manifest["artifact_registry"]["sha256"])
PY
)"
    inventory_sha="$("$PYTHON" - <<'PY'
import json
from pathlib import Path
auth=json.loads(Path("docs/reports/go_live/authorizations/staging_hggsp_complementary_authorization.json").read_text())
manifest=json.loads((Path(auth["release"]["release_dir"])/"production-profile-gate.release.json").read_text())
print(manifest["authorities"]["candidate_inventory_sha256"])
PY
)"
    # Adoption V2 (migration 020) : ressources et artefacts de contrôle
    # successeurs DISTINCTS, sous le rôle adopter et lui seul ; l'adoption V1
    # sous attestor heurterait les 74 attestations V4 actives.
    worker "$REMOTE_ADOPTER_ENV" ingestor.ingestion_worker.attest_publication_cli \
      adopt-predecessor-release --adoption-version SEALED-RELEASE-ADOPTION-V2 \
      --release-id "$RELEASE_HGGSP" --release-dir "$release_dir" \
      --release-manifest-sha256 "$(champ_hggsp release.manifest_sha256)" \
      --artifacts-release-sha256 "$registry_sha" --candidate-inventory-sha256 "$inventory_sha" \
      --transfer-manifest-path "$TRANSFER_CONTAINER" --transfer-manifest-sha256 "$digest" \
      --predecessor-release-id production-profile-gate-2026-2027-v4 \
      --predecessor-release-manifest-sha256 bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be \
      --adopted-by "${OPERATOR_ID:?OPERATOR_ID requis}" | remote | tee "$STATE_DIR/adoption.out" \
      || fail "adoption bornée des 74 refusée"
    # Premier passage : written=74 already_present=0 ; rejeu : 0 et 74.
    grep -Eq '^ADOPTION_RECORDED .* adoption_version=SEALED-RELEASE-ADOPTION-V2 .* placements=74 (written=74 already_present=0|written=0 already_present=74) ' \
        "$STATE_DIR/adoption.out" || fail "adoption V2 autre que 74 refusée"
    local ids id1 id2
    ids="$(ids_r4)"; read -r id1 id2 <<<"$ids"
    worker "$REMOTE_ATTESTOR_ENV" ingestor.ingestion_worker.attest_publication_cli \
      bind-publication-authorities --release-id "$RELEASE_HGGSP" \
      --scope-authorization "$COLLECTION_P=$id1" --scope-authorization "$COLLECTION_T=$id2" \
      --bound-by "${OPERATOR_ID:?OPERATOR_ID requis}" | remote | tee "$STATE_DIR/binding.out" \
      || fail "liaison des deux autorités refusée"
    grep -q '^PUBLICATION_AUTHORITIES_BOUND .* collections=2 ' "$STATE_DIR/binding.out" \
      || fail "liaison autre que deux collections refusée"
    # Ensembles et identités, pas seulement « 74 » : lecture seule, rôle app.
    env_de_role "$REMOTE_WORKER_ENV"
    remote <<EOF | tee "$STATE_DIR/lineage.out" || fail "filiation V2 non prouvée"
set -euo pipefail
$(tirer "$IMAGE")
docker run --rm --network host --env-file "$REMOTE_WORKER_ENV" \\
  -v "$REMOTE/repo:/repo:ro" -w /repo --entrypoint python "$IMAGE" \\
  /repo/$PREFLIGHT --verify-v2-lineage
EOF
    [ "$DRY_RUN" = 1 ] || grep -q '^HGGSP_V2_LINEAGE_OK adoptions=74 ' "$STATE_DIR/lineage.out" \
      || fail "filiation V2 : 74 identités successeur distinctes non prouvées"
    verifier_historique
    marquer successor_sealed_ingestion_or_binding "adopted=74 bound=2 transfer=$digest"
}

etape_successor_batch_review_proposal() {
    local release_dir="/repo/$(champ_hggsp release.release_dir)"
    worker "$REMOTE_ATTESTOR_ENV" ingestor.ingestion_worker.attest_publication_cli \
      propose-release-batch-review --release-id "$RELEASE_HGGSP" --release-dir "$release_dir" \
      --release-manifest-sha256 "$(champ_hggsp release.manifest_sha256)" \
      --transfer-manifest-path "$TRANSFER_CONTAINER" --transfer-manifest-sha256 "$(transfer_sha)" \
      --rights-registry-path /repo/services/rag-pedago/configs/rights_evidence_registry.yml \
      --review-id "${BATCH_REVIEW_ID:?BATCH_REVIEW_ID requis}" \
      --evaluator "${EVALUATOR:?EVALUATOR requis}" \
      --pii-decision-set-path /repo/governance/pii-review-decisions/pii-review-2026-09-22-profile-gate-v3.json \
      --pii-review-receipt-path /repo/governance/pii-review-bindings/pii-review-2026-09-22-profile-gate-v3.json \
      --review-trust-anchor-path /repo/governance/trust-anchors/review-binding-v1.json \
      --pii-review-index-path /repo/docs/reports/evidence-index/pii_review_index_20260922_profile_gate_v3.json \
      --pii-review-reviewers-sha256 "$(sha256sum scripts/github/trusted-reviewers.json | cut -d' ' -f1)" \
      --repository-root /repo | remote | tee "$STATE_DIR/batch-proposal.out" \
      || fail "proposition de revue batch HGGSP refusée"
    verifier_historique
    if [ "$DRY_RUN" = 0 ]; then
        extraire_artefact_revue "$STATE_DIR/batch-proposal.out"
        marquer successor_batch_review_proposal "$(cat "$STATE_DIR/proposal_artifact.txt")"
    else
        marquer successor_batch_review_proposal "dry-run"
    fi
    log "ATTENTE_HUMAINE: créer une PR batch distincte, ouverte, la faire approuver au HEAD exact"
    exit 0
}

etape_successor_batch_review_record() {
    [ -n "${BATCH_REVIEW_PR:-}" ] && [ -n "${BATCH_REVIEW_HEAD:-}" ] \
      && [ -n "${BATCH_REVIEW_ARTIFACT:-}" ] || fail "revue batch humaine distincte absente"
    [ "$BATCH_REVIEW_PR" != 262 ] && [ "$BATCH_REVIEW_PR" != "${SCOPE_REVIEW_PR:-}" ] \
      || fail "revue batch non distincte"
    printf 'attempt\n' > "$STATE_DIR/batch-record.attempt"
    worker "$REMOTE_ATTESTOR_ENV" ingestor.ingestion_worker.attest_publication_cli \
      record-release-batch-attestation --release-id "$RELEASE_HGGSP" \
      --review-id "${BATCH_REVIEW_ID:?BATCH_REVIEW_ID requis}" \
      --repository cyranoaladin/RAG --pull-request "$BATCH_REVIEW_PR" \
      --expected-head "$BATCH_REVIEW_HEAD" --review-artifact-path "$BATCH_REVIEW_ARTIFACT" \
      | remote | tee "$STATE_DIR/batch-record.out" || fail "enregistrement batch refusé"
    verifier_historique
    marquer successor_batch_review_record "pr=$BATCH_REVIEW_PR head=$BATCH_REVIEW_HEAD"
}

etape_successor_attestations() {
    # record-release-batch-attestation est le seul écrivain canonique. Le
    # prévol qui précède a déjà compté exactement 74 attestations actives.
    marquer successor_attestations "74 attestations successeur actives"
}

etape_successor_publication_job_enqueue() {
    env_de_role "$REMOTE_WORKER_ENV"
    printf 'attempt\n' > "$STATE_DIR/enqueue.attempt"
    remote <<EOF | tee "$STATE_DIR/enqueue.out" || fail "74 nouveaux jobs HGGSP refusés"
set -euo pipefail
$(jeton_present)
$(tirer "$IMAGE")
docker run -i --rm --network host --env-file "$REMOTE_WORKER_ENV" \\
  -e NEXUS_GITHUB_TOKEN_FILE=/run/secrets/github-token \\
  -v "$REMOTE_GITHUB_TOKEN_FILE:/run/secrets/github-token:ro" \\
  -v "$REMOTE/repo:/repo:ro" -w /repo --entrypoint python "$IMAGE" - <<'PY'
import os
import sys
from pathlib import Path

sys.path.insert(0, "/repo/scripts/go_live")
from staging_hggsp_complementary import enqueue_successor, require_authority_for_write

require_authority_for_write(Path("/repo"), "successor_publication_job_enqueue")
dsn = os.environ.get("PG_INGESTION_CONTROL_DSN")
if not dsn:
    raise SystemExit("HGGSP_REFUSED: DSN de contrôle absente")
import psycopg

with psycopg.connect(dsn) as conn:
    counts = enqueue_successor(conn)
    conn.commit()
print(f"HGGSP_JOBS_ENQUEUED created={counts['created']} already_queued={counts['already_queued']} total=74")
PY
EOF
    [ "$DRY_RUN" = 1 ] || grep -q '^HGGSP_JOBS_ENQUEUED .* total=74$' "$STATE_DIR/enqueue.out" \
      || fail "enqueue : 74 jobs neufs non prouvés"
    verifier_historique
    marquer successor_publication_job_enqueue "jobs=74, anciens jobs V4 intacts"
}

args_worker_hggsp() {
    local -a args
    mapfile -t args < <("$PYTHON" "$PREFLIGHT" --worker-args --transfer-sha256 "$(transfer_sha)") \
      || fail "arguments Worker B successeur refusés"
    [ "${#args[@]}" -gt 30 ] || fail "arguments Worker B incomplets"
    printf '%q ' "${args[@]}"
}

etape_successor_worker_b_publication() {
    local status args attempt nom
    args="$(args_worker_hggsp)"
    attempt="$(cat "$STATE_DIR/worker-b.attempt" 2>/dev/null || echo 1)"
    [[ "$attempt" =~ ^[1-9][0-9]*$ ]] || fail "numéro de tentative Worker B invalide"
    nom="$WORKER_B_HGGSP-$attempt"
    if [ -f "$STATE_DIR/worker-b.current" ]; then
        [ "$(cat "$STATE_DIR/worker-b.current")" = "$nom" ] || fail "identité du conteneur Worker B divergente"
        [ "$DRY_RUN" = 1 ] || {
            status=$(echo "docker inspect --format '{{.State.Status}} {{.State.ExitCode}}' $nom" | remote) \
                || fail "état du Worker B précédent indisponible"
            if [ "$status" = 'exited 75' ]; then
                echo "docker logs $nom 2>&1" | remote > "$STATE_DIR/worker-b.$attempt.out" || true
                attempt="$((attempt + 1))"
                printf '%s\n' "$attempt" > "$STATE_DIR/worker-b.attempt"
                rm "$STATE_DIR/worker-b.current"
                nom="$WORKER_B_HGGSP-$attempt"
                log "reprise après 75 : ancien conteneur $WORKER_B_HGGSP-$((attempt - 1)) conservé, nouveau prévol effectué"
            elif [ "$status" != 'exited 0' ] && [[ "$status" != running\ * ]] \
                 && [[ "$status" != created\ * ]] && [[ "$status" != restarting\ * ]]; then
                fail "Worker B précédent : $status ; conteneur conservé"
            fi
        }
    fi
    if [ ! -f "$STATE_DIR/worker-b.current" ]; then
        { echo 'set -euo pipefail'
          echo "! docker inspect $nom >/dev/null 2>&1 || { echo 'WORKER_B_DEJA_PRESENT' >&2; exit 4; }"
          WORKER_DETACHE="$nom" worker "$REMOTE_WORKER_ENV:$REMOTE_PUBLISHER_ENV" \
            ingestor.ingestion_worker.multilevel_publication_resume_cli "$args"
        } | remote || fail "Worker B HGGSP non lancé"
        printf '%s\n' "$attempt" > "$STATE_DIR/worker-b.attempt"
        printf '%s\n' "$nom" > "$STATE_DIR/worker-b.current"
    fi
    [ "$DRY_RUN" = 1 ] && { marquer successor_worker_b_publication "dry-run"; return; }
    while :; do
        status=$(echo "docker inspect --format '{{.State.Status}} {{.State.ExitCode}}' $nom" | remote) \
          || fail "état Worker B indisponible"
        case "$status" in
            'exited 0') break ;;
            'exited 75')
                echo "docker logs $nom 2>&1" | remote > "$STATE_DIR/worker-b.$attempt.out" || true
                fail "Worker B limité (75), conteneur et preuves conservés ; nouveau prévol requis" ;;
            'running '*|'created '*|'restarting '*) sleep "${WORKER_B_POLL_S:-60}" ;;
            *) fail "Worker B : état $status ; conteneur conservé" ;;
        esac
    done
    echo "docker logs $nom 2>&1" | remote > "$STATE_DIR/worker-b.$attempt.out" \
      || fail "journal Worker B indisponible, conteneur conservé"
    grep -q "claim_scope=$COLLECTION_P,$COLLECTION_T claim_release_id=$RELEASE_HGGSP" "$STATE_DIR/worker-b.$attempt.out" \
      || fail "Worker B sans preuve des deux dimensions de claim"
    verifier_historique
    marquer successor_worker_b_publication "exited=0, conteneur $nom conservé"
}

etape_successor_independent_verification() {
    # Le prévol produit en lecture seule a déjà exigé 2/52/74/2590,
    # 9/263/405/5678 et l'union 11/315/479/8268, les vieux jobs et #262.
    # La sonde réelle doit couvrir les 11 scopes. Une image incapable de
    # servir les nouveaux IDs a déjà été refusée avant le premier SSH.
    env_de_role "$REMOTE_READER_ENV"
    remote <<EOF | tee "$STATE_DIR/retrieval.out" || fail "retrieval indépendant refusé"
set -euo pipefail
$(jeton_present)
$(tirer "$PROBE_IMAGE")
docker run --rm --network host --env-file "$REMOTE_READER_ENV" \\
  -e NEXUS_GITHUB_TOKEN_FILE=/run/secrets/github-token \\
  -v "$REMOTE_GITHUB_TOKEN_FILE:/run/secrets/github-token:ro" \\
  -v "$REMOTE/repo:/repo:ro" -v "$RUN:/run-db" -w /app \\
  --entrypoint python "$PROBE_IMAGE" /repo/scripts/go_live/staging_retrieval_probe.py \\
  --repository-root /repo --output /run-db/retrieval-probe-mixed.json \\
  --mixed-registry /repo/services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json \\
  --mixed-registry-sha256 59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6
EOF
    [ "$DRY_RUN" = 1 ] && { marquer successor_independent_verification "dry-run"; return; }
    grep -q '^SONDE_RETRIEVAL_MIXTE ' "$STATE_DIR/retrieval.out" \
      || fail "onze scopes mixtes non sondés"
    verifier_historique
    marquer successor_independent_verification "2/52/74/2590 + 9/263/405/5678 + 11/315/479/8268, retrieval 11, V4 inchangée"
}

if [ "${BASH_SOURCE[0]}" != "$0" ]; then return 0; fi
case "${1:-}" in
    status)
        for op in "${ORDRE_HGGSP[@]}"; do
            if fait "$op"; then echo "FAIT $op $(cat "$STATE_DIR/$op.done")"; else echo "A_FAIRE $op"; fi
        done ;;
    run)
        until_op=""
        [ "${2:-}" = --until ] && until_op="${3:?étape attendue}"
        [ -z "$until_op" ] || [[ " ${ORDRE_HGGSP[*]} " == *" $until_op "* ]] \
          || fail "étape HGGSP inconnue : $until_op"
        charger_hggsp
        autoriser_hggsp "${ORDRE_HGGSP[0]}"
        images_locales
        for op in "${ORDRE_HGGSP[@]}"; do
            fait "$op" && { [ "$op" = "$until_op" ] && break; continue; }
            preflight_hggsp "$op"
            "etape_$op"
            [ "$op" = "$until_op" ] && break
        done ;;
    *) echo "usage: $0 status | [--dry-run] run [--until ETAPE]" >&2; exit 2 ;;
esac
