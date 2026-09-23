#!/usr/bin/env bash
# Signature LOCALE des manifestes de readiness de la publication V3 (lot CY).
#
# À lancer par le détenteur de la clé de répétition, sur son poste, jamais sur
# l'hôte. La graine est lue par l'outil canonique depuis un fichier (0600) ;
# elle n'apparaît ni dans les arguments, ni dans l'environnement, ni dans la
# sortie. Deux manifestes, préparés ensemble, chacun limité à SA release :
#
#   staging-readiness-v3.json           V3, pour toutes les étapes worker V3
#   staging-readiness-v2-backfill.json  V2, pour le seul rattrapage d'attribution
#                                       (chemin B), validité courte
#
# Un manifeste V2 ne permet pas de publier V2 : Worker B exige en plus une
# attestation batch de V2, qui n'existe pas, et l'autorisation V3 interdit
# `v2_publication`.
#
#   READINESS_SEED_FILE=~/chemin/vers/la/graine scripts/go_live/sign_staging_v3_readiness_manifests.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
SEED="${READINESS_SEED_FILE:-$HOME/nexus-rehearsal-readiness.seed}"
OUT="${READINESS_LOCAL:-$HOME/nexus-staging-v3-readiness}"
PYTHON="${PYTHON:-$(command -v python3)}"
AUTH_V3="docs/reports/go_live/authorizations/staging_v3_publication_authorization.json"
ANCRE="governance/trust-anchors/rehearsal-readiness-v1.json"
CLE="nexus-rehearsal-readiness-20260920-01"
V3_MANIFEST="services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v3/release-f8fb983d04f4b7c1/profile_gate/production-profile-gate.release.json"
V2_MANIFEST="services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2/release-1b9eba0c0eb0ab13/profile_gate/production-profile-gate.release.json"

[ -f "$SEED" ] || { echo "graine absente : $SEED (READINESS_SEED_FILE)" >&2; exit 2; }
[ "$(stat -c %a "$SEED")" = 600 ] || { echo "la graine doit être en 0600 : $SEED" >&2; exit 2; }
[ -e "$OUT/staging-readiness-v3.json" ] && { echo "déjà signé : $OUT (rien n'est écrasé)" >&2; exit 2; }

champ() { "$PYTHON" -c "import json,sys; d=json.load(open('$AUTH_V3')); print(d['runtime_image'][sys.argv[1]])" "$1"; }
IMAGE="$(champ reference)"
BUILD="$(champ source_commit_sha)"
V3_SHA="$(sha256sum "$V3_MANIFEST" | cut -d' ' -f1)"
V2_SHA="$(sha256sum "$V2_MANIFEST" | cut -d' ' -f1)"
[ "$V3_SHA" = c0f5897bf0a2d2f388ba0534de2cc4bb3198ab5d68173f4d28713572ce222e16 ] || { echo "manifeste V3 inattendu" >&2; exit 2; }
[ "$V2_SHA" = e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864 ] || { echo "manifeste V2 inattendu" >&2; exit 2; }

cat <<EOF
Objets à signer (clé $CLE, ancre $ANCRE) :

  1. staging-readiness-v3.json
     release  production-profile-gate-2026-2027-v3  manifeste $V3_SHA
     image    $IMAGE
     build    $BUILD   validité 30 jours
  2. staging-readiness-v2-backfill.json   (rattrapage d'attribution seulement)
     release  production-profile-gate-2026-2027-v2  manifeste $V2_SHA
     image    $IMAGE
     build    $BUILD   validité 7 jours

Sortie : $OUT (0700)
EOF
read -r -p "Signer exactement ces deux objets ? (oui/non) " reponse
[ "$reponse" = oui ] || { echo "rien n'est signé"; exit 1; }

install -d -m 0700 "$OUT"
signer() {  # $1 release_id  $2 manifeste de release  $3 jours  $4 sortie
    "$PYTHON" services/rag-engine/scripts/sign_staging_readiness_manifest_cli.py \
        --merge-sha "$BUILD" --worker-image "$IMAGE" \
        --allowed-release-id "$1" --release-manifest-file "$2" \
        --key-id "$CLE" --private-key-file "$SEED" \
        --trust-anchor-file "$ANCRE" --valid-days "$3" --output "$4"
    chmod 600 "$4"
}
signer production-profile-gate-2026-2027-v3 "$V3_MANIFEST" 30 "$OUT/staging-readiness-v3.json"
signer production-profile-gate-2026-2027-v2 "$V2_MANIFEST" 7 "$OUT/staging-readiness-v2-backfill.json"

echo
echo "Signés et revérifiés contre l'ancre par l'outil canonique :"
(cd "$OUT" && sha256sum staging-readiness-v3.json staging-readiness-v2-backfill.json)
echo "SIGNATURES_OK"
