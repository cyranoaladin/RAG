#!/usr/bin/env bash
# Signature LOCALE du manifeste de readiness V4 pour l'image Worker B DI (lot DI).
#
# Même outil canonique, même clé de répétition, même ancre et même release que
# la signature V4 (sign_staging_v4_readiness_manifests.sh) ; seule l'image
# change : celle que l'autorisation DI ACTIVE épingle par digest. Tant que
# l'autorisation DI n'est pas fusionnée à son emplacement canonique, ou que son
# image est encore en attente de construction, rien n'est signé.
#
# À lancer par le détenteur de la clé, sur son poste, jamais sur l'hôte :
#
#   READINESS_SEED_FILE=~/chemin/vers/la/graine scripts/go_live/sign_staging_v4_di_readiness_manifest.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
SEED="${READINESS_SEED_FILE:-$HOME/nexus-rehearsal-readiness.seed}"
OUT="${READINESS_LOCAL:-$HOME/nexus-staging-v4-di-readiness}"
PYTHON="${PYTHON:-$(command -v python3)}"
AUTH_DI="docs/reports/go_live/authorizations/staging_v4_partial_recovery_authorization.json"
ANCRE="governance/trust-anchors/rehearsal-readiness-v1.json"
CLE="nexus-rehearsal-readiness-20260920-01"
MANIFESTE_SORTIE="staging-readiness-v4-di.json"
V4_MANIFEST="services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v4/release-024f8625ebfeb7ce/profile_gate/production-profile-gate.release.json"

[ -f "$AUTH_DI" ] || { echo "autorisation DI absente : $AUTH_DI (la proposition ne fait rien signer)" >&2; exit 2; }
"$PYTHON" scripts/go_live/check_staging_authorization.py --operation partial_readiness_resign \
    --cible "$("$PYTHON" -c "import json,sys; sys.path.insert(0,'scripts/go_live'); import check_staging_authorization as a; print(json.dumps(a.OPERATIONS_DI['partial_readiness_resign']['cible']))")" \
    >/dev/null || { echo "partial_readiness_resign non autorisée (check_staging_authorization.py)" >&2; exit 2; }
[ -f "$SEED" ] || { echo "graine absente : $SEED (READINESS_SEED_FILE)" >&2; exit 2; }
[ "$(stat -c %a "$SEED")" = 600 ] || { echo "la graine doit être en 0600 : $SEED" >&2; exit 2; }
[ -e "$OUT/$MANIFESTE_SORTIE" ] && { echo "déjà signé : $OUT (rien n'est écrasé)" >&2; exit 2; }

champ() { "$PYTHON" -c "import json,sys; d=json.load(open('$AUTH_DI')); print(d['runtime_image'][sys.argv[1]])" "$1"; }
IMAGE="$(champ reference)"
BUILD="$(champ source_commit_sha)"
V4_SHA="$(sha256sum "$V4_MANIFEST" | cut -d' ' -f1)"
[ "$V4_SHA" = bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be ] || { echo "manifeste V4 inattendu" >&2; exit 2; }

cat <<EOT
Objet à signer (clé $CLE, ancre $ANCRE) :

  $MANIFESTE_SORTIE
     release  production-profile-gate-2026-2027-v4  manifeste $V4_SHA
     image    $IMAGE   (image DI)
     build    $BUILD   validité 30 jours

Sortie : $OUT (0700)
EOT
read -r -p "Signer exactement cet objet ? (oui/non) " reponse
[ "$reponse" = oui ] || { echo "rien n'est signé"; exit 1; }

install -d -m 0700 "$OUT"
"$PYTHON" services/rag-engine/scripts/sign_staging_readiness_manifest_cli.py \
    --merge-sha "$BUILD" --worker-image "$IMAGE" \
    --allowed-release-id production-profile-gate-2026-2027-v4 --release-manifest-file "$V4_MANIFEST" \
    --key-id "$CLE" --private-key-file "$SEED" \
    --trust-anchor-file "$ANCRE" --valid-days 30 --output "$OUT/$MANIFESTE_SORTIE"
chmod 600 "$OUT/$MANIFESTE_SORTIE"

echo
echo "Signé et revérifié contre l'ancre par l'outil canonique :"
(cd "$OUT" && sha256sum "$MANIFESTE_SORTIE")
echo "SIGNATURE_OK"
