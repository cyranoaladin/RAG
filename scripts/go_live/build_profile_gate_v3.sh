#!/usr/bin/env bash
# Construit le successeur profile-gate V3, puis le confronte à V2.
#
# Quatre étapes, chacune bloquante :
#   1. essai à blanc du producteur (comptes, sans écriture) ;
#   2. construction dans un répertoire NEUF (le producteur refuse l'existant) ;
#   3. diff machine V2 → V3 (scripts/go_live/diff_profile_gate_releases.py) ;
#   4. rejeu des chargeurs canoniques sur les octets de V3
#      (attest_publication_cli verify-release-sources), chaîne PII comprise.
#
# N'écrit que sous le répertoire de sortie et le répertoire de preuves. Ne
# publie rien, n'active rien, ne touche à aucune base.
#
# Le motif d'écart d'autorité n'est pas de la prose : pour chaque autorité de
# revue PII, il cite le dernier commit qui a touché son fichier — le producteur
# vérifie ensuite que ce commit est atteignable et porte l'empreinte liée.
#
# Variables (toutes facultatives) :
#   NEXUS_REPO_ROOT       racine du dépôt (défaut : dérivée de ce script)
#   V3_OUTPUT_DIR         sortie de la release (défaut : .../profile_gate_v3)
#   V3_EVIDENCE_DIR       preuves de l'orchestration (défaut : sous V3_OUTPUT_DIR/..)
#   PDF_ROOT              miroir des PDF (obligatoire, aucun défaut machine-local)
#   PEDAGO_PYTHON         interpréteur rag-pedago (défaut : son .venv)
#   ENGINE_PYTHON         interpréteur rag-engine (défaut : son .venv)
set -euo pipefail

ROOT="${NEXUS_REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$ROOT"

: "${PDF_ROOT:?PDF_ROOT est requis : le miroir des PDF de la release}"
RELEASES="services/rag-pedago/data/releases/prerentree_2026_2027"
V2="$RELEASES/profile_gate_v2/release-1b9eba0c0eb0ab13/profile_gate"
OUT="${V3_OUTPUT_DIR:-$RELEASES/profile_gate_v3}"
EVIDENCE="${V3_EVIDENCE_DIR:-$OUT.evidence}"
PEDAGO_PYTHON="${PEDAGO_PYTHON:-services/rag-pedago/.venv/bin/python3}"
ENGINE_PYTHON="${ENGINE_PYTHON:-services/rag-engine/.venv/bin/python}"
RELEASE_ID="production-profile-gate-2026-2027-v3"

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
                "$TRANSFER" "$RIGHTS" "$V2/production-profile-gate.release.json"; do
    [ -f "$required" ] || { echo "MISSING_INPUT: $required" >&2; exit 2; }
done
if ! git diff --quiet HEAD -- governance docs/reports/evidence docs/reports/evidence-index \
        docs/reports/handoff services/rag-pedago/configs; then
    echo "DIRTY_AUTHORITIES: les autorités lues doivent être celles d'un commit" >&2
    exit 2
fi
[ -e "$OUT" ] && { echo "OUTPUT_EXISTS: $OUT — le producteur n'écrit que dans un répertoire neuf" >&2; exit 2; }
[ -e "$EVIDENCE" ] && { echo "EVIDENCE_EXISTS: $EVIDENCE" >&2; exit 2; }
mkdir -p "$EVIDENCE"

commit_of() { git log -1 --format=%H -- "$1"; }
MOTIVE="Autorités de revue PII du successeur V3 (ADR-0047, ADR-0059 §6) : \
jeu de décisions $(commit_of "$DECISION_SET"), reçu ADR-0035 $(commit_of "$RECEIPT"), \
index de revue $(commit_of "$INDEX"), ancre de confiance $(commit_of "$ANCHOR")."
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
"${builder[@]}" --reference-release "$V2" --authority-change-motive "$MOTIVE" \
    --output-dir "$OUT" 2>&1 | grep -v '^Ignoring wrong pointing object' | tee "$EVIDENCE/2-build.log"
mapfile -t built < <(find "$OUT" -mindepth 2 -maxdepth 2 -type d -name profile_gate)
[ "${#built[@]}" -eq 1 ] || { echo "BUILD_OUTPUT_AMBIGUOUS: ${built[*]:-aucun}" >&2; exit 3; }
V3="${built[0]}"
echo "$V3" > "$EVIDENCE/release-dir.txt"

echo "== 3/4 diff V2 -> V3"
python3 scripts/go_live/diff_profile_gate_releases.py \
    --base "$V2" --head "$V3" --output "$EVIDENCE/3-diff-v2-v3.json"

echo "== 4/4 chargeurs canoniques sur V3"
sha() { sha256sum "$1" | cut -d' ' -f1; }
PYTHONPATH="services/rag-engine/src:packages/contracts/src" "$ENGINE_PYTHON" \
    -m ingestor.ingestion_worker.attest_publication_cli verify-release-sources \
    --release-dir "$V3" \
    --release-manifest-sha256 "$(sha "$V3/production-profile-gate.release.json")" \
    --transfer-manifest-path "$TRANSFER" --transfer-manifest-sha256 "$(sha "$TRANSFER")" \
    --rights-registry-path "$RIGHTS" \
    --pii-decision-set-path "$DECISION_SET" --pii-review-receipt-path "$RECEIPT" \
    --review-trust-anchor-path "$ANCHOR" --pii-review-index-path "$INDEX" \
    --pii-review-reviewers-sha256 "$(sha "$REVIEWERS")" --repository-root "$ROOT" \
    --output "$EVIDENCE/4-canonical-loaders.json"

echo "V3_BUILT=$V3"
echo "V3_EVIDENCE=$EVIDENCE"
