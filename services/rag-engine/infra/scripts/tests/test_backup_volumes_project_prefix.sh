#!/usr/bin/env bash
# Remédiation revue PR#90 (Cubic P2, revue incrémentale) : preuve que
# backup-volumes.sh résout bien le volume Docker RÉEL d'un projet Compose
# donné (ex. "nexuslot44ftest_rag_ingestion_artifacts_data") via les
# étiquettes com.docker.compose.project/com.docker.compose.volume, jamais
# la forme nue ("rag_ingestion_artifacts_data") qui ne correspond en
# réalité à AUCUN volume créé par `docker compose up` sans
# `-p`/COMPOSE_PROJECT_NAME explicite — et ne se laisse jamais confondre
# par un volume de même clé appartenant à un tout autre projet Compose
# présent sur le même hôte (scénario réel constaté sur une machine de
# développement partagée : plusieurs projets sans rapport y possèdent
# chacun un volume "rag_chroma_data" sous des noms réels différents).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_SCRIPT="$SCRIPT_DIR/../backup-volumes.sh"

if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    echo "SKIP: Docker not available"
    exit 0
fi

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

TEST_PROJECT="nexuslot44ftest"
REAL_VOLUME="${TEST_PROJECT}_rag_ingestion_artifacts_data"
DECOY_PROJECT="nexuslot44fdecoy"
DECOY_VOLUME="${DECOY_PROJECT}_rag_ingestion_artifacts_data"
BACKUP_ROOT="$(mktemp -d)"
trap 'docker volume rm -f "$REAL_VOLUME" "$DECOY_VOLUME" >/dev/null 2>&1; rm -rf "$BACKUP_ROOT"' EXIT

# Volume RÉEL de ce test, étiqueté exactement comme Compose le ferait pour
# le projet dont ce test se réclame.
docker volume create \
    --label "com.docker.compose.project=${TEST_PROJECT}" \
    --label "com.docker.compose.volume=rag_ingestion_artifacts_data" \
    "$REAL_VOLUME" >/dev/null
docker run --rm -v "${REAL_VOLUME}:/data" busybox \
    sh -c "echo 'real project content' > /data/probe.txt"

# Volume DECOY : même clé Compose ("rag_ingestion_artifacts_data"), mais un
# projet différent — ne doit jamais être choisi à la place du vrai.
docker volume create \
    --label "com.docker.compose.project=${DECOY_PROJECT}" \
    --label "com.docker.compose.volume=rag_ingestion_artifacts_data" \
    "$DECOY_VOLUME" >/dev/null
docker run --rm -v "${DECOY_VOLUME}:/data" busybox \
    sh -c "echo 'DECOY_MUST_NEVER_BE_BACKED_UP' > /data/probe.txt"

BACKUP_DIR="$BACKUP_ROOT" COMPOSE_PROJECT_NAME="$TEST_PROJECT" "$BACKUP_SCRIPT" \
    >/tmp/backup_volumes_test_output.log 2>&1 \
    || { cat /tmp/backup_volumes_test_output.log >&2; fail "backup-volumes.sh exited non-zero"; }

archive="$(find "$BACKUP_ROOT" -maxdepth 1 -name 'rag_ingestion_artifacts_data-*.tgz' -print -quit)"
[[ -n "$archive" ]] || {
    cat /tmp/backup_volumes_test_output.log >&2
    fail "no archive created for the labeled artifact volume — resolution did not find it"
}

extracted="$(mktemp -d)"
tar xzf "$archive" -C "$extracted"
[[ -f "$extracted/probe.txt" ]] || fail "archive does not contain the expected probe.txt"
grep -q "real project content" "$extracted/probe.txt" \
    || fail "archive content does not match the real project's volume"
grep -q "DECOY_MUST_NEVER_BE_BACKED_UP" "$extracted/probe.txt" \
    && fail "backed up the DECOY project's volume instead of the real one"
rm -rf "$extracted"

grep -q "Skipping rag_chroma_data" /tmp/backup_volumes_test_output.log \
    || fail "expected other, genuinely absent volumes to still be skipped cleanly"

rm -f /tmp/backup_volumes_test_output.log
echo "PASS: backup-volumes.sh resolves the correct project-labeled artifact volume, never a same-key decoy from another project"
