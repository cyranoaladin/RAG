"""Projection explicite de la release V4 vers le complément HGGSP."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import load_producer

ROOT = Path(__file__).resolve().parents[3]
V4 = (
    ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v4"
    / "release-024f8625ebfeb7ce/profile_gate"
)
V1 = ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate"
MAPPING = ROOT / "services/rag-engine/configs/mappings/eduscol_profile_gate_subjects_hggsp.yml"
V4_MAPPING = ROOT / "services/rag-engine/configs/mappings/eduscol_profile_gate_subjects.yml"
MATRIX = ROOT / "docs/reports/handoff/servability_matrix_v1.json"
EXCLUSION = ROOT / "docs/reports/evidence/release_currentness_exclusion_registry.json"
HGGSP = (
    "rag_nexus_hggsp_premiere_specialite",
    "rag_nexus_hggsp_terminale_specialite",
)
RELEASE_ID = "production-profile-gate-2026-2027-v5-hggsp"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


V4_BINDINGS_SHA = _sha(V4 / "authority_bindings.json")


@pytest.fixture(scope="module")
def authorities():  # noqa: ANN201
    builder = load_producer()
    return (
        builder.load_and_validate_exclusion_registry(EXCLUSION),
        builder.load_governed_currentness_authority(MATRIX, _sha(MATRIX)),
    )


def _build(
    authorities, *, collections=HGGSP, mapping=MAPPING, mapping_sha=None,
    source_root=V4, bindings_sha=V4_BINDINGS_SHA,
):  # noqa: ANN001, ANN202
    builder = load_producer()
    excluded, currentness = authorities
    artifacts = json.loads((V4 / "artifacts.release.json").read_text())["artifacts"]
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("NEXUS_PROFILE_ROOT", str(ROOT / "services/rag-engine/configs/ingestion_profiles/v3_livraison_315"))
        patch.setenv("NEXUS_PROFILE_MANIFEST", str(ROOT / "services/rag-engine/configs/ingestion_profiles/ingestion_manifest_v3_livraison_315.yml"))
        patch.setenv("NEXUS_FINAL_SET_SHA256", builder._final_set_digest(sorted(a["artifact_id"] for a in artifacts)))
        # Le scan des vrais PDF appartient au build d'intégration. Cette épreuve
        # fixe la projection du produit et de ses autorités sans dépendance au
        # miroir du poste opérateur.
        patch.setattr(builder, "_rehearsal_pii_evidence", lambda *args, **kwargs: json.loads((V4 / "pii_evidence.json").read_text()))
        return builder.build_release(
            release_mode="rehearsal",
            pdf_root=ROOT,
            source_release_root=source_root,
            source_release_manifest_sha256=_sha(V4 / "production-profile-gate.release.json"),
            source_authority_bindings_sha256=bindings_sha,
            release_id=RELEASE_ID,
            exclusion_registry=excluded,
            currentness_authority=currentness,
            collections=collections,
            subject_mapping_path=mapping,
            subject_mapping_sha256=mapping_sha or _sha(mapping),
        )


@pytest.mark.parametrize(
    "source_file",
    [
        "candidate_inventory.json",
        "preflight_evidence.json",
        "programme_registry.json",
        "currentness_evidence.json",
        "currentness_network_audit.json",
        "pii_evidence.json",
        "models/embedding/SHA256SUMS",
        "models/embedding/manifest.json",
        "models/reranker/SHA256SUMS",
        "models/reranker/manifest.json",
    ],
)
def test_copied_source_rejects_unsealed_consumed_evidence(
    authorities, tmp_path: Path, source_file: str,
) -> None:  # noqa: ANN001
    source = tmp_path / "copied-v4"
    shutil.copytree(V4, source)
    path = source / source_file
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="source .*digest differs from sealed release"):
        _build(authorities, source_root=source)


def test_copied_source_rejects_binding_authority_drift(
    authorities, tmp_path: Path,
) -> None:  # noqa: ANN001
    source = tmp_path / "copied-v4"
    shutil.copytree(V4, source)
    path = source / "authority_bindings.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["bindings"]["candidate_inventory_sha256"]["authority_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="source authority binding differs from sealed release"):
        _build(authorities, source_root=source)


def test_collection_projection_requires_source_binding_digest(authorities) -> None:  # noqa: ANN001
    with pytest.raises(ValueError, match="source authority bindings SHA-256 is required"):
        _build(authorities, bindings_sha=None)


def test_complementary_release_contains_only_hggsp_and_seals_subject_mapping(authorities) -> None:  # noqa: ANN001
    builder = load_producer()
    docs = _build(authorities)
    root = builder.RELEASE_ROOT
    aggregate = json.loads(docs[root / "production-profile-gate.release.json"])
    artifacts = json.loads(docs[root / "artifacts.release.json"])
    registry = json.loads(docs[root.parent / "release-registry.json"])
    inventory = json.loads(docs[root / "candidate_inventory.json"])
    bindings = json.loads(docs[root / "authority_bindings.json"])

    assert aggregate["release_id"] == RELEASE_ID
    assert aggregate["expected_counts"] == {
        "unique_artifacts": 52,
        "placements": 74,
        "unique_chunks": 2590,
        "subjects": 2,
    }
    assert {subject["collection"] for subject in aggregate["subjects"]} == set(HGGSP)
    assert registry["releases"][0]["collections"] == sorted(HGGSP)
    assert len(artifacts["artifacts"]) == 52
    assert {row["collection"] for row in inventory["collections"]} == set(HGGSP)
    assert inventory["counts"]["placements"] == 74
    preflight = json.loads(docs[root / "preflight_evidence.json"])
    programme = json.loads(docs[root / "programme_registry.json"])
    assert preflight["counts"]["artifacts"] == 52
    assert preflight["counts"]["chunks"] == 2590
    assert {row["collection"] for row in programme["taxonomies"]} == set(HGGSP)
    v4_artifacts = {
        row["artifact_id"] for row in artifacts["artifacts"]
    }
    other_v4_artifacts = {
        placement["artifact_id"]
        for subject_path in (V4 / "subjects").glob("*.release.json")
        for subject in [json.loads(subject_path.read_text())]
        if subject["collection"] not in HGGSP
        for placement in subject["placements"]
    }
    assert len(other_v4_artifacts) == 263
    assert not v4_artifacts & other_v4_artifacts
    assert aggregate["authorities"]["subject_mapping_sha256"] == _sha(MAPPING)
    assert bindings["bindings"]["subject_mapping_sha256"]["path"] == MAPPING.relative_to(ROOT).as_posix()
    assert bindings["bindings"]["subject_mapping_sha256"]["file_sha256"] == _sha(MAPPING)
    assert _sha(V4_MAPPING) == "85a8efa17a9b04659800363ea3386208b46874ca673bdcb0889c6270bfc9c71c"


@pytest.mark.parametrize("collections", [HGGSP + ("rag_nexus_absente",), HGGSP + HGGSP[:1]])
def test_collection_selection_rejects_unknown_or_duplicate(authorities, collections) -> None:  # noqa: ANN001
    with pytest.raises(ValueError, match="collection"):
        _build(authorities, collections=collections)


def test_incorrect_mapping_digest_is_rejected(authorities) -> None:  # noqa: ANN001
    with pytest.raises(ValueError, match="subject mapping|subject_mapping"):
        _build(authorities, mapping_sha="0" * 64)


def test_source_manifest_digest_is_required_for_selected_collections(authorities) -> None:  # noqa: ANN001
    builder = load_producer()
    excluded, currentness = authorities
    with pytest.raises(ValueError, match="source release manifest SHA-256"):
        builder.build_release(
            release_mode="rehearsal", source_release_root=V4,
            release_id=RELEASE_ID, exclusion_registry=excluded,
            currentness_authority=currentness, collections=HGGSP,
        )


def test_mapping_authority_change_requires_real_commit_motive(tmp_path: Path) -> None:
    builder = load_producer()
    reference_bindings = json.loads((V4 / "authority_bindings.json").read_text())
    candidate_bindings = json.loads(json.dumps(reference_bindings))
    candidate_bindings["bindings"]["subject_mapping_sha256"] = {
        "path": MAPPING.relative_to(ROOT).as_posix(),
        "file_sha256": _sha(MAPPING),
        "authority_sha256": _sha(MAPPING),
        "authority_kind": "FILE_SHA256",
    }
    (tmp_path / "authority_bindings.json").write_text(json.dumps(candidate_bindings))
    with pytest.raises(ValueError, match="aucun motif"):
        builder._comparer_autorites_a_la_reference(
            tmp_path, reference=V4, motif=None, ecrites=set()
        )
    with pytest.raises(ValueError, match="commit atteignable"):
        builder._comparer_autorites_a_la_reference(
            tmp_path, reference=V4, motif="HGGSP : 0000000000000000000000000000000000000000", ecrites=set()
        )
    commit = subprocess.check_output(
        ["git", "log", "-1", "--format=%H", "--", MAPPING.relative_to(ROOT).as_posix()],
        cwd=ROOT, text=True,
    ).strip()
    assert commit == "fb8a7cc8e85448115a64de8ff5325d639ef9ee70"
    builder._comparer_autorites_a_la_reference(
        tmp_path, reference=V4, motif=f"Autorité HGGSP : {commit}", ecrites=set()
    )


def test_signed_pii_review_projects_only_a_proven_source_subset() -> None:
    builder = load_producer()
    source_pii = json.loads((V4 / "pii_evidence.json").read_text())
    source_contents = frozenset(
        row["artifact_id"]
        for row in json.loads((V4 / "artifacts.release.json").read_text())["artifacts"]
    )
    selected_contents = frozenset(
        placement["artifact_id"]
        for col in HGGSP
        for placement in json.loads((V4 / "subjects" / f"{col}.release.json").read_text())["placements"]
    )
    decisions = json.loads(
        (ROOT / "governance/pii-review-decisions/pii-review-2026-09-22-profile-gate-v3.json").read_text()
    )
    bundles = {
        row["content_sha256"]: row["bundle_sha256"]
        for row in json.loads(
            (ROOT / "docs/reports/evidence-index/pii_review_index_20260922_profile_gate_v3.json").read_text()
        )["bundles"]
    }
    args = {
        "decision_document": decisions,
        "review_bundles": bundles,
        "authority_digests": {"reviewed_content_set_sha256": builder._final_set_digest(sorted(source_contents))},
        "source_contents": source_contents,
        "selected_contents": selected_contents,
        "source_pii_evidence": source_pii,
        "source_pii_evidence_sha256": _sha(V4 / "pii_evidence.json"),
    }
    projected, indexed = builder._select_signed_review_subset(**args)
    assert len(source_contents) == 315
    assert len(selected_contents) == 52
    assert projected is None  # zéro détection HGGSP : aucune décision subset inventée
    assert indexed == {}

    with pytest.raises(ValueError, match="signed review population"):
        builder._select_signed_review_subset(
            **{**args, "authority_digests": {"reviewed_content_set_sha256": "0" * 64}}
        )
    with pytest.raises(ValueError, match="escapes the signed source"):
        builder._select_signed_review_subset(
            **{**args, "selected_contents": selected_contents | {"0" * 64}}
        )
    with pytest.raises(ValueError, match="source PII evidence population"):
        builder._select_signed_review_subset(
            **{**args, "source_pii_evidence": {"results": source_pii["results"][:-1]}}
        )


def test_complementary_scan_must_match_each_parent_result() -> None:
    builder = load_producer()
    parent = json.loads((V4 / "pii_evidence.json").read_text())
    row = parent["results"][0]
    builder._require_subscan_matches_source([row], parent)
    with pytest.raises(ValueError, match="scan differs from sealed source"):
        builder._require_subscan_matches_source([{**row, "pages_scanned": row["pages_scanned"] + 1}], parent)


def test_historical_rehearsal_without_new_options_keeps_all_v4_subjects(authorities) -> None:  # noqa: ANN001
    builder = load_producer()
    excluded, currentness = authorities
    docs = builder.build_release(
        release_mode="rehearsal",
        source_release_root=V1,
        release_id=RELEASE_ID,
        exclusion_registry=excluded,
        currentness_authority=currentness,
    )
    aggregate = json.loads(docs[builder.RELEASE_ROOT / "production-profile-gate.release.json"])
    assert aggregate["expected_counts"]["subjects"] == 11
    assert aggregate["expected_counts"]["placements"] == 479
    assert aggregate["authorities"]["subject_mapping_sha256"] == _sha(V4_MAPPING)
