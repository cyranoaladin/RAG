#!/usr/bin/env bash
# Signature LOCALE du manifeste de readiness de la publication V4 (lot DB).
#
# À lancer par le détenteur de la clé de répétition, sur son poste, jamais sur
# l'hôte. La graine est lue par l'outil canonique depuis un fichier (0600) ;
# elle n'apparaît ni dans les arguments, ni dans l'environnement, ni dans la
# sortie. Un seul manifeste, limité à V4 et à l'image worker autorisée :
#
#   staging-readiness-v4.json   V4, pour toutes les étapes worker (A et B)
#
# Worker B en déduit sa qualification liée à la release (ADR-0060) ; aucun
# argument ne l'active. Aucun manifeste V2 ni V3 : ni rattrapage ni adoption.
#
#   READINESS_SEED_FILE=~/chemin/vers/la/graine scripts/go_live/sign_staging_v4_readiness_manifests.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
SEED="${READINESS_SEED_FILE:-$HOME/nexus-rehearsal-readiness.seed}"
OUT="${READINESS_LOCAL:-$HOME/nexus-staging-v4-readiness}"
PYTHON="${PYTHON:-$(command -v python3)}"
AUTH_V4="docs/reports/go_live/authorizations/staging_v4_publication_authorization.json"
ANCRE="governance/trust-anchors/rehearsal-readiness-v1.json"
CLE="nexus-rehearsal-readiness-20260920-01"
V4_MANIFEST="services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v4/release-024f8625ebfeb7ce/profile_gate/production-profile-gate.release.json"

[ -f "$SEED" ] || { echo "graine absente : $SEED (READINESS_SEED_FILE)" >&2; exit 2; }
[ "$(stat -c %a "$SEED")" = 600 ] || { echo "la graine doit être en 0600 : $SEED" >&2; exit 2; }
[ -e "$OUT/staging-readiness-v4.json" ] && { echo "déjà signé : $OUT (rien n'est écrasé)" >&2; exit 2; }

champ() { "$PYTHON" -c "import json,sys; d=json.load(open('$AUTH_V4')); print(d['runtime_image'][sys.argv[1]])" "$1"; }
IMAGE="$(champ reference)"
BUILD="$(champ source_commit_sha)"
V4_SHA="$(sha256sum "$V4_MANIFEST" | cut -d' ' -f1)"
[ "$V4_SHA" = bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be ] || { echo "manifeste V4 inattendu" >&2; exit 2; }

cat <<EOF
Objet à signer (clé $CLE, ancre $ANCRE) :

  staging-readiness-v4.json
     release  production-profile-gate-2026-2027-v4  manifeste $V4_SHA
     image    $IMAGE
     build    $BUILD   validité 30 jours

Sortie : $OUT (0700)
EOF
read -r -p "Signer exactement cet objet ? (oui/non) " reponse
[ "$reponse" = oui ] || { echo "rien n'est signé"; exit 1; }

install -d -m 0700 "$OUT"
"$PYTHON" services/rag-engine/scripts/sign_staging_readiness_manifest_cli.py \
    --merge-sha "$BUILD" --worker-image "$IMAGE" \
    --allowed-release-id production-profile-gate-2026-2027-v4 --release-manifest-file "$V4_MANIFEST" \
    --key-id "$CLE" --private-key-file "$SEED" \
    --trust-anchor-file "$ANCRE" --valid-days 30 --output "$OUT/staging-readiness-v4.json"
chmod 600 "$OUT/staging-readiness-v4.json"

echo
echo "Signé et revérifié contre l'ancre par l'outil canonique :"
(cd "$OUT" && sha256sum staging-readiness-v4.json)
echo "SIGNATURE_OK"
