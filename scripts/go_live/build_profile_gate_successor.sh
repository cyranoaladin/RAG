#!/usr/bin/env bash
# Construit un successeur profile-gate, puis le confronte à sa référence.
#
# Généralise build_profile_gate_v3.sh (qui reste la trace de V3) : essai à
# blanc, construction dans un répertoire NEUF, diff machine contre la release
# de référence, rejeu des chargeurs canoniques. Le motif d'écart d'autorité
# cite, pour chaque autorité qu'il nomme, le dernier commit de son fichier —
# le producteur vérifie ensuite que ce commit est atteignable et porte
# l'empreinte liée.
#
# Variables obligatoires :
#   RELEASE_ID            identité gouvernée (ADR-0050)
#   REFERENCE_DIR         répertoire profile_gate de la release de référence
#   OUTPUT_DIR            sortie (neuve)
#   PDF_ROOT              miroir des PDF
#   MOTIVE_LABEL          raison écrite de l'écart
#   MOTIVE_PATHS          chemins (séparés par ':') des autorités modifiées
# Variables facultatives :
#   NEXUS_PROFILE_ROOT / NEXUS_PROFILE_MANIFEST / NEXUS_FINAL_SET_SHA256 (lignée)
#   EVIDENCE_DIR, PEDAGO_PYTHON, ENGINE_PYTHON, NEXUS_REPO_ROOT
set -euo pipefail

ROOT="${NEXUS_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$ROOT"

: "${RELEASE_ID:?}" "${REFERENCE_DIR:?}" "${OUTPUT_DIR:?}" "${PDF_ROOT:?}"
: "${MOTIVE_LABEL:?}" "${MOTIVE_PATHS:?}"
RELEASES="services/rag-pedago/data/releases/prerentree_2026_2027"
EVIDENCE="${EVIDENCE_DIR:-$OUTPUT_DIR.evidence}"
PEDAGO_PYTHON="${PEDAGO_PYTHON:-services/rag-pedago/.venv/bin/python3}"
ENGINE_PYTHON="${ENGINE_PYTHON:-services/rag-engine/.venv/bin/python}"

DECISION_SET="governance/pii-review-decisions/pii-review-2026-09-22-profile-gate-v3.json"
RECEIPT="governance/pii-review-bindings/pii-review-2026-09-22-profile-gate-v3.json"
ANCHOR="governance/trust-anchors/review-binding-v1.json"
INDEX="docs/reports/evidence-index/pii_review_index_20260922_profile_gate_v3.json"
EXCLUSION="docs/reports/evidence/release_currentness_exclusion_registry.json"
EXCLUSION_SHA="07a346b84ae4ebbf1ef7f14dd3f588c95acce36050e8c335f904c37cabe4c72c"
MATRIX="docs/reports/handoff/servability_matrix_v1.json"
MATRIX_SHA="5dc4c8983ec8feb4f7ce1a76babba4b75ff2840af00b4de880d4120c19d14f9c"
TRANSFER="docs/reports/evidence/external_staging_v2_artifact_transfer_manifest.json"
RIGHTS="services/rag-pedago/configs/rights_evidence_registry.yml"
REVIEWERS="scripts/github/trusted-reviewers.json"

for required in "$DECISION_SET" "$RECEIPT" "$ANCHOR" "$INDEX" "$EXCLUSION" "$MATRIX" \
                "$TRANSFER" "$RIGHTS" "$REFERENCE_DIR/production-profile-gate.release.json"; do
    [ -f "$required" ] || { echo "MISSING_INPUT: $required" >&2; exit 2; }
done
if ! git diff --quiet HEAD -- governance docs/reports/evidence docs/reports/evidence-index \
        docs/reports/handoff services/rag-pedago/configs services/rag-engine/configs; then
    echo "DIRTY_AUTHORITIES: les autorités lues doivent être celles d'un commit" >&2
    exit 2
fi
[ -e "$OUTPUT_DIR" ] && { echo "OUTPUT_EXISTS: $OUTPUT_DIR" >&2; exit 2; }
[ -e "$EVIDENCE" ] && { echo "EVIDENCE_EXISTS: $EVIDENCE" >&2; exit 2; }
mkdir -p "$EVIDENCE"

citations=()
IFS=: read -r -a chemins <<<"$MOTIVE_PATHS"
for chemin in "${chemins[@]}"; do
    [ -f "$chemin" ] || { echo "MOTIVE_PATH_MISSING: $chemin" >&2; exit 2; }
    citations+=("$(basename "$chemin") $(git log -1 --format=%H -- "$chemin")")
done
MOTIVE="$MOTIVE_LABEL : $(IFS=,; echo "${citations[*]}")."
printf '%s\n' "$MOTIVE" > "$EVIDENCE/authority-change-motive.txt"
git rev-parse HEAD > "$EVIDENCE/repository-head.txt"

builder=(
    "$PEDAGO_PYTHON" services/rag-pedago/scripts/build_production_profile_release.py
    --release-mode rehearsal --release-id "$RELEASE_ID"
    --source-release-root "$RELEASES/profile_gate"
    --pdf-root "$PDF_ROOT"
    --exclusion-registry "$EXCLUSION" --exclusion-registry-sha256 "$EXCLUSION_SHA"
    --servability-matrix "$MATRIX" --servability-matrix-sha256 "$MATRIX_SHA"
    --pii-decision-set "$DECISION_SET" --pii-review-receipt "$RECEIPT"
    --review-trust-anchor "$ANCHOR" --pii-review-index "$INDEX"
    --pii-review-reviewer abenrhouma
)

echo "== 1/4 essai à blanc"
"${builder[@]}" --dry-run 2>&1 | grep -v '^Ignoring wrong pointing object' | tee "$EVIDENCE/1-dry-run.log"

echo "== 2/4 construction"
"${builder[@]}" --reference-release "$REFERENCE_DIR" --authority-change-motive "$MOTIVE" \
    --output-dir "$OUTPUT_DIR" 2>&1 | grep -v '^Ignoring wrong pointing object' | tee "$EVIDENCE/2-build.log"
mapfile -t built < <(find "$OUTPUT_DIR" -mindepth 2 -maxdepth 2 -type d -name profile_gate)
[ "${#built[@]}" -eq 1 ] || { echo "BUILD_OUTPUT_AMBIGUOUS: ${built[*]:-aucun}" >&2; exit 3; }
RELEASE="${built[0]}"
echo "$RELEASE" > "$EVIDENCE/release-dir.txt"

echo "== 3/4 diff contre la référence"
python3 scripts/go_live/diff_profile_gate_releases.py \
    --base "$REFERENCE_DIR" --head "$RELEASE" --output "$EVIDENCE/3-diff.json"

echo "== 4/4 chargeurs canoniques"
sha() { sha256sum "$1" | cut -d' ' -f1; }
PYTHONPATH="services/rag-engine/src:packages/contracts/src:packages/release-chain/src:packages/pdf-page-policy/src" \
"$ENGINE_PYTHON" -m ingestor.ingestion_worker.attest_publication_cli verify-release-sources \
    --release-dir "$RELEASE" \
    --release-manifest-sha256 "$(sha "$RELEASE/production-profile-gate.release.json")" \
    --transfer-manifest-path "$TRANSFER" --transfer-manifest-sha256 "$(sha "$TRANSFER")" \
    --rights-registry-path "$RIGHTS" \
    --pii-decision-set-path "$DECISION_SET" --pii-review-receipt-path "$RECEIPT" \
    --review-trust-anchor-path "$ANCHOR" --pii-review-index-path "$INDEX" \
    --pii-review-reviewers-sha256 "$(sha "$REVIEWERS")" --repository-root "$ROOT" \
    --output "$EVIDENCE/4-canonical-loaders.json"

echo "RELEASE_BUILT=$RELEASE"
echo "RELEASE_EVIDENCE=$EVIDENCE"
