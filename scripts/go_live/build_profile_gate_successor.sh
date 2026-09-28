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
#   HGGSP_COMPLEMENTARY=1 active exclusivement le complément HGGSP de V4 ;
#   SUBJECT_MAPPING_PATH et SUBJECT_MAPPING_SHA256 deviennent obligatoires.
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
HGGSP_V4="${RELEASES}/profile_gate_v4/release-024f8625ebfeb7ce/profile_gate"
HGGSP_V4_SHA="bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be"
HGGSP_MAPPING="services/rag-engine/configs/mappings/eduscol_profile_gate_subjects_hggsp.yml"
HGGSP_MAPPING_SHA="b909c1fb0a8b874b2bbe53cdb1973d5eadce97823c987f4e2b75fefd0d48bb6a"
HGGSP_V4_MAPPING="services/rag-engine/configs/mappings/eduscol_profile_gate_subjects.yml"
HGGSP_V4_MAPPING_SHA="85a8efa17a9b04659800363ea3386208b46874ca673bdcb0889c6270bfc9c71c"
HGGSP_MAPPING_COMMIT="fb8a7cc8e85448115a64de8ff5325d639ef9ee70"
HGGSP_PROFILE_ROOT="services/rag-engine/configs/ingestion_profiles/v3_livraison_315"
HGGSP_PROFILE_MANIFEST="services/rag-engine/configs/ingestion_profiles/ingestion_manifest_v3_livraison_315.yml"
HGGSP_FINAL_SET_SHA="04b731e20a9ebd9dcd08f00fe516489191690f67ec18e4ba4996a8612961bd12"

if [[ "${HGGSP_COMPLEMENTARY:-0}" != 0 && "${HGGSP_COMPLEMENTARY}" != 1 ]]; then
    echo "HGGSP_MODE_INVALID: HGGSP_COMPLEMENTARY doit valoir 1 ou 0" >&2
    exit 2
fi

verifier_complement_hggsp() {
    [ "$RELEASE_ID" = "production-profile-gate-2026-2027-v5-hggsp" ] || {
        echo "HGGSP_RELEASE_ID_REQUIRED" >&2; exit 2;
    }
    [ "$(realpath -m -- "$REFERENCE_DIR")" = "$(realpath -m -- "$ROOT/$HGGSP_V4")" ] || {
        echo "HGGSP_V4_SOURCE_REQUIRED" >&2; exit 2;
    }
    [ -z "$(git status --porcelain=v1 --untracked-files=all -- \
        "$HGGSP_V4" "$HGGSP_PROFILE_ROOT" "$HGGSP_PROFILE_MANIFEST" \
        "$HGGSP_MAPPING" "$HGGSP_V4_MAPPING")" ] || {
        echo "HGGSP_AUTHORITIES_DIRTY" >&2; exit 2;
    }
    [ "${SUBJECT_MAPPING_PATH:-}" = "$HGGSP_MAPPING" ] && \
    [ "${SUBJECT_MAPPING_SHA256:-}" = "$HGGSP_MAPPING_SHA" ] && \
    [ "$(sha256sum "$HGGSP_MAPPING" | cut -d' ' -f1)" = "$HGGSP_MAPPING_SHA" ] && \
    [ "$(sha256sum "$HGGSP_V4_MAPPING" | cut -d' ' -f1)" = "$HGGSP_V4_MAPPING_SHA" ] || {
        echo "HGGSP_MAPPING_SHA_MISMATCH" >&2; exit 2;
    }
    [ "$MOTIVE_PATHS" = "$HGGSP_MAPPING" ] && \
    [ "$(git log -1 --format=%H -- "$HGGSP_MAPPING")" = "$HGGSP_MAPPING_COMMIT" ] || {
        echo "HGGSP_MAPPING_MOTIVE_REQUIRED" >&2; exit 2;
    }
    [ "${NEXUS_PROFILE_ROOT:-$HGGSP_PROFILE_ROOT}" = "$HGGSP_PROFILE_ROOT" ] && \
    [ "${NEXUS_PROFILE_MANIFEST:-$HGGSP_PROFILE_MANIFEST}" = "$HGGSP_PROFILE_MANIFEST" ] && \
    [ "${NEXUS_FINAL_SET_SHA256:-$HGGSP_FINAL_SET_SHA}" = "$HGGSP_FINAL_SET_SHA" ] || {
        echo "HGGSP_PROFILE_LINEAGE_MISMATCH" >&2; exit 2;
    }
    export NEXUS_PROFILE_ROOT="$HGGSP_PROFILE_ROOT"
    export NEXUS_PROFILE_MANIFEST="$HGGSP_PROFILE_MANIFEST"
    export NEXUS_FINAL_SET_SHA256="$HGGSP_FINAL_SET_SHA"
    python3 - "$REFERENCE_DIR" "$PDF_ROOT" "$HGGSP_V4_SHA" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

reference, pdf_root = (Path(arg).resolve() for arg in sys.argv[1:3])
manifest_sha = sys.argv[3]
manifest = reference / "production-profile-gate.release.json"
if hashlib.sha256(manifest.read_bytes()).hexdigest() != manifest_sha:
    sys.exit("HGGSP_V4_MANIFEST_SHA_MISMATCH")
release = json.loads(manifest.read_text(encoding="utf-8"))
if release["release_id"] != "production-profile-gate-2026-2027-v4" or release["expected_counts"] != {
    "placements": 479, "subjects": 11, "unique_artifacts": 315, "unique_chunks": 8268,
}:
    sys.exit("HGGSP_V4_SOURCE_COUNTS_MISMATCH")
def sealed(path, digest):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        sys.exit(f"HGGSP_V4_COMPONENT_SHA_MISMATCH: {path.name}")
    return json.loads(raw)

subjects = {
    row["collection"]: sealed(reference / row["path"], row["sha256"])
    for row in release["subjects"]
}
collections = {
    "rag_nexus_hggsp_premiere_specialite": 39,
    "rag_nexus_hggsp_terminale_specialite": 35,
}
if len(subjects) != 11 or not collections.keys() <= subjects.keys():
    sys.exit("HGGSP_V4_SUBJECTS_MISMATCH")
for collection, count in collections.items():
    subject = subjects[collection]
    if subject["collection"] != collection or len(subject["placements"]) != count:
        sys.exit("HGGSP_V4_PLACEMENTS_MISMATCH")
all_artifacts = {
    artifact["artifact_id"]: artifact
    for artifact in sealed(
        reference / release["artifact_registry"]["path"],
        release["artifact_registry"]["sha256"],
    )["artifacts"]
}
hggsp = {row["artifact_id"] for name in collections for row in subjects[name]["placements"]}
other = {
    row["artifact_id"]
    for name, subject in subjects.items() if name not in collections
    for row in subject["placements"]
}
chunks = sum(len(all_artifacts[artifact_id]["chunks"]) for artifact_id in hggsp)
if len(hggsp) != 52 or len(other) != 263 or hggsp & other or chunks != 2590:
    sys.exit("HGGSP_V4_DISJOINT_COUNTS_MISMATCH")
if sum(len(subject["placements"]) for name, subject in subjects.items() if name not in collections) != 405:
    sys.exit("HGGSP_V4_NON_HGGSP_PLACEMENTS_MISMATCH")
for artifact_id in sorted(hggsp):
    artifact = all_artifacts[artifact_id]
    path = (pdf_root / artifact["source_path"]).resolve()
    if not path.is_relative_to(pdf_root) or not path.is_file():
        sys.exit(f"HGGSP_PDF_MISSING: {artifact_id}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != artifact["content_sha256"]:
        sys.exit(f"HGGSP_PDF_SHA_MISMATCH: {artifact_id}")
print(f"HGGSP_V4_SOURCE_OK placements=74 artifacts=52 chunks={chunks} pdfs=52 disjoint=1")
PY
}

verifier_produit_hggsp() {
    python3 - "$REFERENCE_DIR" "$RELEASE" "$HGGSP_MAPPING_SHA" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

source, produced = (Path(arg).resolve() for arg in sys.argv[1:3])
mapping_sha = sys.argv[3]
def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

base = load(source / "production-profile-gate.release.json")
head = load(produced / "production-profile-gate.release.json")
names = {"rag_nexus_hggsp_premiere_specialite", "rag_nexus_hggsp_terminale_specialite"}
base_subjects = {row["collection"]: load(source / row["path"]) for row in base["subjects"]}
head_subjects = {row["collection"]: load(produced / row["path"]) for row in head["subjects"]}
if len(head["subjects"]) != 2 or set(head_subjects) != names or head["release_id"] != "production-profile-gate-2026-2027-v5-hggsp":
    sys.exit("HGGSP_PRODUCT_SCOPE_MISMATCH")
if head["authorities"].get("subject_mapping_sha256") != mapping_sha:
    sys.exit("HGGSP_PRODUCT_MAPPING_SHA_MISMATCH")
expected = {
    name: {row["artifact_id"] for row in base_subjects[name]["placements"]}
    for name in names
}
for name in names:
    base_placements = {row["placement_id"] for row in base_subjects[name]["placements"]}
    new_rows = head_subjects[name]["placements"]
    new_placements = {row["placement_id"] for row in new_rows}
    new_artifacts = {row["artifact_id"] for row in head_subjects[name]["placements"]}
    if (len(new_rows) != len(base_subjects[name]["placements"])
        or len(new_placements) != len(new_rows)
        or base_placements != new_placements
        or new_artifacts != expected[name]):
        sys.exit(f"HGGSP_PRODUCT_PLACEMENTS_MISMATCH: {name}")
all_ids = set().union(*expected.values())
other_ids = {
    row["artifact_id"]
    for name, subject in base_subjects.items() if name not in names
    for row in subject["placements"]
}
product_rows = load(produced / "artifacts.release.json")["artifacts"]
product_artifacts = {
    row["artifact_id"]: row
    for row in product_rows
}
source_registry = source / base["artifact_registry"]["path"]
if hashlib.sha256(source_registry.read_bytes()).hexdigest() != base["artifact_registry"]["sha256"]:
    sys.exit("HGGSP_V4_ARTIFACT_REGISTRY_SHA_MISMATCH")
source_artifacts = {row["artifact_id"]: row for row in load(source_registry)["artifacts"]}
expected_chunks = sum(len(source_artifacts[artifact_id]["chunks"]) for artifact_id in all_ids)
chunks = sum(len(row["chunks"]) for row in product_artifacts.values())
if (len(product_rows) != 52 or len(product_artifacts) != len(product_rows)
    or set(product_artifacts) != all_ids or all_ids & other_ids or expected_chunks != 2590):
    sys.exit("HGGSP_PRODUCT_ARTIFACTS_MISMATCH")
if chunks != expected_chunks or any(
    product_artifacts[artifact_id]["content_sha256"] != source_artifacts[artifact_id]["content_sha256"]
    or product_artifacts[artifact_id]["chunks"] != source_artifacts[artifact_id]["chunks"]
    for artifact_id in all_ids
):
    sys.exit("HGGSP_PRODUCT_CHUNKS_MISMATCH")
if head["expected_counts"] != {"placements": 74, "subjects": 2, "unique_artifacts": 52, "unique_chunks": chunks}:
    sys.exit("HGGSP_PRODUCT_COUNTS_MISMATCH")
print(f"HGGSP_PRODUCT_OK placements=74 artifacts=52 chunks={chunks} v4_other_placements=405")
PY
}

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
if [ "${HGGSP_COMPLEMENTARY:-0}" = 1 ]; then
    verifier_complement_hggsp
fi
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

SOURCE_RELEASE_ROOT="$RELEASES/profile_gate"
if [ "${HGGSP_COMPLEMENTARY:-0}" = 1 ]; then
    SOURCE_RELEASE_ROOT="$REFERENCE_DIR"
fi
builder=(
    "$PEDAGO_PYTHON" services/rag-pedago/scripts/build_production_profile_release.py
    --release-mode rehearsal --release-id "$RELEASE_ID"
    --source-release-root "$SOURCE_RELEASE_ROOT"
    --pdf-root "$PDF_ROOT"
    --exclusion-registry "$EXCLUSION" --exclusion-registry-sha256 "$EXCLUSION_SHA"
    --servability-matrix "$MATRIX" --servability-matrix-sha256 "$MATRIX_SHA"
    --pii-decision-set "$DECISION_SET" --pii-review-receipt "$RECEIPT"
    --review-trust-anchor "$ANCHOR" --pii-review-index "$INDEX"
    --pii-review-reviewer abenrhouma
)
if [ "${HGGSP_COMPLEMENTARY:-0}" = 1 ]; then
    builder+=(
        --source-release-manifest-sha256 "$HGGSP_V4_SHA"
        --subject-mapping-path "$SUBJECT_MAPPING_PATH"
        --subject-mapping-sha256 "$SUBJECT_MAPPING_SHA256"
        --collection rag_nexus_hggsp_premiere_specialite
        --collection rag_nexus_hggsp_terminale_specialite
    )
fi

echo "== 1/4 essai à blanc"
"${builder[@]}" --dry-run 2>&1 | grep -v '^Ignoring wrong pointing object' | tee "$EVIDENCE/1-dry-run.log"

echo "== 2/4 construction"
"${builder[@]}" --reference-release "$REFERENCE_DIR" --authority-change-motive "$MOTIVE" \
    --output-dir "$OUTPUT_DIR" 2>&1 | grep -v '^Ignoring wrong pointing object' | tee "$EVIDENCE/2-build.log"
mapfile -t built < <(find "$OUTPUT_DIR" -mindepth 2 -maxdepth 2 -type d -name profile_gate)
[ "${#built[@]}" -eq 1 ] || { echo "BUILD_OUTPUT_AMBIGUOUS: ${built[*]:-aucun}" >&2; exit 3; }
RELEASE="${built[0]}"
echo "$RELEASE" > "$EVIDENCE/release-dir.txt"
if [ "${HGGSP_COMPLEMENTARY:-0}" = 1 ]; then
    verifier_produit_hggsp | tee "$EVIDENCE/hggsp-complementary-counts.txt"
fi

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
