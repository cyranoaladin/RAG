"""Lecteur de l'inventaire texte, séparé du format PDF historique."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from ingestor.ingestion_worker import sealed_release_ingestion as worker
from ingestor.multilevel_evidence import (
    MultilevelEvidenceError,
    load_multilevel_candidate_inventory,
    load_student_public_candidate_inventory,
)

ROOT = Path(__file__).resolve().parents[3]
V4 = ROOT / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_v4/release-024f8625ebfeb7ce/profile_gate/candidate_inventory.json"
)
PREPARATION_ROOT = ROOT / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_student_public_successor_v1"
)


def _preparation() -> Path:
    releases = sorted(PREPARATION_ROOT.glob("release-*/preparation-index.json"))
    assert len(releases) == 1, "expected one current prepared successor"
    return releases[0].parent


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _source(source_id: str, title: str) -> dict:
    return {
        "source_placement_id": source_id,
        "source_url": "https://eduscol.education.gouv.fr/5823/ressources",
        "title": title,
        "external_level": "terminale",
        "external_subject": "nsi",
        "external_scope": "lycee/general/nsi",
        "external_document_type": "ressource-accompagnement",
        "year": "2021",
        "placement_origin": "PRODUCTION_PROFILE_GATE_20260825",
        "placement_reason_code": "P_1",
    }


def _candidate(sha: str, source_sha: str, placements: list[dict]) -> dict:
    return {
        "content_sha256": sha,
        "source_pdf_sha256": source_sha,
        "physical_path": f"{sha}.txt",
        "media_type": "text/plain; charset=utf-8",
        "derivative_receipt_sha256": _sha(f"receipt-{sha}"),
        "placements": placements,
    }


def _document() -> dict:
    first, second = _sha("text-a"), _sha("text-b")
    document = {
        "inventory_kind": "NEXUS_STUDENT_PUBLIC_DERIVATIVE_CANDIDATE_INVENTORY_V1",
        "release_id": "student-public-test-v1",
        "release_manifest_sha256": _sha("release"),
        "artifact_registry_sha256": _sha("artifacts"),
        "candidate_manifest_sha256": _sha("#300"),
        "source_candidate_inventory_sha256": {"v4": _sha("v4"), "v5": _sha("v5")},
        "counts": {"collections": 2, "unique_artifacts": 2, "placements": 3},
        "collections": [
            {"collection": "rag_nexus_nsi_premiere_specialite", "candidates": [
                _candidate(first, _sha("pdf-a"), [_source(_sha("placement-a1"), "A")]),
            ]},
            {"collection": "rag_nexus_nsi_terminale_specialite", "candidates": [
                _candidate(first, _sha("pdf-a"), [_source(_sha("placement-a2"), "A")]),
                _candidate(second, _sha("pdf-b"), [_source(_sha("placement-b"), "B")]),
            ]},
        ],
    }
    document["collections"][1]["candidates"].sort(key=lambda row: row["content_sha256"])
    return document


def _write(tmp_path: Path, document: dict) -> tuple[Path, str]:
    path = tmp_path / "candidate_inventory.json"
    raw = (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def test_text_inventory_loads_exact_worker_join_without_pdf_path(tmp_path):
    document = _document()
    path, sha = _write(tmp_path, document)
    inventory = load_student_public_candidate_inventory(path, expected_sha256=sha)
    first = _sha("text-a")
    assert inventory.sha256 == sha
    assert inventory.unique_content_sha256 == frozenset({_sha("text-a"), _sha("text-b")})
    assert len(inventory.placements_for(
        content_sha256=first, collection="rag_nexus_nsi_terminale_specialite"
    )) == 1
    assert inventory.derivative_identities[first] == (
        _sha("pdf-a"), _sha(f"receipt-{first}"),
    )
    assert all(p.physical_path == f"{p.content_sha256}.txt" for p in inventory.placements)
    discovery = worker._load_candidate_discovery(path, expected_sha256=sha)
    assert len(discovery) == 3
    assert discovery[(first, _sha("placement-a2"))]["source_url"] == (
        "https://eduscol.education.gouv.fr/5823/ressources"
    )
    assert discovery[(first, _sha("placement-a2"))]["external_document_type"] == (
        "ressource-accompagnement"
    )
    assert discovery[(first, _sha("placement-a2"))]["collection"] == (
        "rag_nexus_nsi_terminale_specialite"
    )


def test_worker_subject_join_rejects_resealed_inventory_collection(tmp_path):
    document = _document()
    document["collections"][0]["collection"] += "X"
    path, sha = _write(tmp_path, document)
    discovery = worker._load_candidate_discovery(path, expected_sha256=sha)
    artifact_id = _sha("text-a")
    source_id = _sha("placement-a1")
    subject = {"placements": [{"artifact_id": artifact_id,
                               "source_placement_id": source_id}]}
    with pytest.raises(worker.SealedReleaseIngestionError, match="collection"):
        worker._placements_of_subject(
            collection="rag_nexus_nsi_premiere_specialite",
            subject=subject,
            artifacts={artifact_id: {"source_url": "https://eduscol.education.gouv.fr/a"}},
            discovery=discovery,
        )


def test_worker_binds_text_inventory_to_exact_preparation_chain(tmp_path):
    preparation = _preparation()
    gate = preparation / "profile_gate"
    inventory_path = gate / "candidate_inventory.json"
    inventory = load_student_public_candidate_inventory(
        inventory_path, expected_sha256=hashlib.sha256(inventory_path.read_bytes()).hexdigest()
    )
    registry = json.loads((gate / "artifacts.release.json").read_bytes())
    artifacts = {row["artifact_id"]: row for row in registry["artifacts"]}
    index_path = preparation / "preparation-index.json"
    index = json.loads(index_path.read_bytes())
    sidecar = tmp_path / "source_preparation"
    sidecar.mkdir()
    for name, origin in (
        ("production-profile-gate.release.json", gate / "production-profile-gate.release.json"),
        ("preparation-index.json", index_path),
        ("candidate_inventory.json", inventory_path),
    ):
        shutil.copy2(origin, sidecar / name)
    manifest = {
        "release_id": inventory.release_id,
        "release_mode": "public_successor",
        "authorities": {
            "source_preparation_release_manifest_sha256": inventory.release_manifest_sha256,
            "source_preparation_index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
            "source_candidate_release_manifest_sha256": index["source_candidate_manifest_sha256"],
        },
    }
    worker._require_student_public_inventory_binding(
        inventory, manifest=manifest,
        artifact_registry_sha256=inventory.artifact_registry_sha256,
        release_dir=tmp_path, artifacts=artifacts,
    )
    for change, reason in (
        ({"release_id": "other-release"}, "release_id"),
        ({"artifact_registry_sha256": "a" * 64}, "artifact registry"),
        ({"candidate_manifest_sha256": "b" * 64}, "candidate manifest"),
        ({"source_candidate_inventory_sha256": {"v4": "c" * 64,
                                                 "v5": inventory.source_candidate_inventory_sha256["v5"]}},
         "source inventory"),
    ):
        with pytest.raises(worker.SealedReleaseIngestionError, match=reason):
            worker._require_student_public_inventory_binding(
                replace(inventory, **change), manifest=manifest,
                artifact_registry_sha256=inventory.artifact_registry_sha256,
                release_dir=tmp_path, artifacts=artifacts,
            )
    with pytest.raises(worker.SealedReleaseIngestionError, match="collection"):
        worker._require_student_public_inventory_binding(
            replace(inventory, placements=(replace(inventory.placements[0],
                                                   collection="wrong_collection"),
                                           *inventory.placements[1:])),
            manifest=manifest,
            artifact_registry_sha256=inventory.artifact_registry_sha256,
            release_dir=tmp_path, artifacts=artifacts,
        )
    swapped = json.loads(inventory_path.read_bytes())
    swapped["collections"][0]["collection"] += "X"
    swapped_path, swapped_sha = _write(tmp_path, swapped)
    resealed = load_student_public_candidate_inventory(
        swapped_path, expected_sha256=swapped_sha,
    )
    with pytest.raises(worker.SealedReleaseIngestionError, match="collection"):
        worker._require_student_public_inventory_binding(
            resealed, manifest=manifest,
            artifact_registry_sha256=inventory.artifact_registry_sha256,
            release_dir=tmp_path, artifacts=artifacts,
        )
    for field in ("source_pdf_sha256", "derivative_receipt_sha256"):
        tampered = json.loads(inventory_path.read_bytes())
        tampered["collections"][0]["candidates"][0][field] = "f" * 64
        tampered_path, tampered_sha = _write(tmp_path, tampered)
        resealed = load_student_public_candidate_inventory(
            tampered_path, expected_sha256=tampered_sha,
        )
        with pytest.raises(worker.SealedReleaseIngestionError, match="source PDF|receipt"):
            worker._require_student_public_inventory_binding(
                resealed, manifest=manifest,
                artifact_registry_sha256=inventory.artifact_registry_sha256,
                release_dir=tmp_path, artifacts=artifacts,
            )
        altered_registry = copy.deepcopy(artifacts)
        first = next(iter(altered_registry))
        altered_registry[first][field] = "f" * 64
        with pytest.raises(worker.SealedReleaseIngestionError, match="source PDF|receipt"):
            worker._require_student_public_inventory_binding(
                inventory, manifest=manifest,
                artifact_registry_sha256=inventory.artifact_registry_sha256,
                release_dir=tmp_path, artifacts=altered_registry,
            )
    manifest["authorities"].pop("source_preparation_index_sha256")
    with pytest.raises(worker.SealedReleaseIngestionError, match="preparation index"):
        worker._require_student_public_inventory_binding(
            inventory, manifest=manifest,
            artifact_registry_sha256=inventory.artifact_registry_sha256,
            release_dir=tmp_path, artifacts=artifacts,
        )


def test_sealed_loader_refuses_text_without_dereferenceable_preparation(tmp_path):
    gate = _preparation() / "profile_gate"
    final = tmp_path / "final"
    shutil.copytree(gate, final)
    manifest_path = final / "production-profile-gate.release.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest.update(
        release_mode="public_successor", promotion_status="PROMOTABLE",
        review_status="REVIEWED", activation_status="PRODUCTION_ACTIVATION_ALLOWED",
    )
    inventory_sha = hashlib.sha256((final / "candidate_inventory.json").read_bytes()).hexdigest()
    manifest["authorities"]["candidate_inventory_sha256"] = inventory_sha
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    with pytest.raises(worker.SealedReleaseIngestionError,
                       match="source preparation release manifest authority absent"):
        worker.load_sealed_release(
            final,
            release_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            artifacts_release_sha256=manifest["artifact_registry"]["sha256"],
            candidate_inventory_sha256=inventory_sha,
            artifact_transfer_manifest_path=tmp_path / "unused-transfer.json",
            artifact_transfer_manifest_sha256="0" * 64,
        )


def test_full_loader_still_refuses_after_exact_preparation_chain(tmp_path):
    preparation = _preparation()
    final = tmp_path / "final"
    shutil.copytree(preparation / "profile_gate", final)
    sidecar = final / "source_preparation"
    sidecar.mkdir()
    for name, origin in (
        ("production-profile-gate.release.json",
         preparation / "profile_gate/production-profile-gate.release.json"),
        ("preparation-index.json", preparation / "preparation-index.json"),
        ("candidate_inventory.json", preparation / "profile_gate/candidate_inventory.json"),
    ):
        shutil.copy2(origin, sidecar / name)
    manifest_path = final / "production-profile-gate.release.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest.update(release_mode="public_successor", promotion_status="PROMOTABLE",
                    review_status="REVIEWED",
                    activation_status="PRODUCTION_ACTIVATION_ALLOWED")
    manifest["authorities"].update(
        candidate_inventory_sha256=hashlib.sha256(
            (final / "candidate_inventory.json").read_bytes()
        ).hexdigest(),
        source_candidate_release_manifest_sha256=json.loads(
            (sidecar / "preparation-index.json").read_bytes()
        )["source_candidate_manifest_sha256"],
        source_preparation_release_manifest_sha256=hashlib.sha256(
            (sidecar / "production-profile-gate.release.json").read_bytes()
        ).hexdigest(),
        source_preparation_index_sha256=hashlib.sha256(
            (sidecar / "preparation-index.json").read_bytes()
        ).hexdigest(),
    )
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    with pytest.raises(worker.SealedReleaseIngestionError,
                       match="external authority gate unavailable"):
        worker.load_sealed_release(
            final,
            release_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            artifacts_release_sha256=manifest["artifact_registry"]["sha256"],
            candidate_inventory_sha256=manifest["authorities"]["candidate_inventory_sha256"],
            artifact_transfer_manifest_path=tmp_path / "unused-transfer.json",
            artifact_transfer_manifest_sha256="0" * 64,
        )


def test_full_loader_refuses_377_text_placements_relabelled_as_v1(tmp_path):
    gate = _preparation() / "profile_gate"
    final = tmp_path / "final"
    shutil.copytree(gate, final)
    inventory_path = final / "candidate_inventory.json"
    inventory = json.loads(inventory_path.read_bytes())
    assert inventory["counts"]["placements"] == 377
    inventory["inventory_kind"] = "MULTILEVEL_CANDIDATE_INVENTORY_V1"
    inventory_path.write_text(json.dumps(inventory, sort_keys=True), encoding="utf-8")
    inventory_sha = hashlib.sha256(inventory_path.read_bytes()).hexdigest()
    manifest_path = final / "production-profile-gate.release.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest.update(release_mode="public_successor", promotion_status="PROMOTABLE",
                    review_status="REVIEWED",
                    activation_status="PRODUCTION_ACTIVATION_ALLOWED")
    manifest["authorities"]["candidate_inventory_sha256"] = inventory_sha
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    with pytest.raises(worker.SealedReleaseIngestionError, match="text inventory kind"):
        worker.load_sealed_release(
            final,
            release_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            artifacts_release_sha256=manifest["artifact_registry"]["sha256"],
            candidate_inventory_sha256=inventory_sha,
            artifact_transfer_manifest_path=tmp_path / "unused-transfer.json",
            artifact_transfer_manifest_sha256="0" * 64,
        )


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda d: d["collections"][0]["candidates"][0].update(
            physical_path=f"{_sha('text-a')}.pdf"), "text path"),
        (lambda d: d["collections"][0]["candidates"][0].update(
            physical_path=f"01_EDUSCOL_OFFICIEL/{_sha('text-a')}.txt"), "text path"),
        (lambda d: d["collections"][0]["candidates"][0].update(
            media_type="application/pdf"), "media type"),
        (lambda d: d["collections"][0]["candidates"][0].update(
            source_pdf_sha256=_sha("text-a")), "source PDF SHA"),
        (lambda d: d["collections"][0]["candidates"][0].update(
            derivative_receipt_sha256="bad"), "receipt SHA"),
        (lambda d: d["collections"][1]["candidates"][0]["placements"][0].update(
            source_placement_id=_sha("placement-a1")), "source placement.*duplicate"),
        (lambda d: d["collections"][0]["candidates"][0]["placements"][0].update(
            source_url="https://example.invalid/file.pdf"), "source URL"),
        (lambda d: d["counts"].update(placements=4), "placements count"),
        (lambda d: d.update(unexpected="ignored"), "fields"),
        (lambda d: d["source_candidate_inventory_sha256"].update(v4="bad"), "v4.*SHA"),
    ],
)
def test_text_inventory_semantic_sabotages_fail_even_when_digest_is_resealed(
    tmp_path, change, reason
):
    document = copy.deepcopy(_document())
    change(document)
    path, sha = _write(tmp_path, document)
    with pytest.raises(MultilevelEvidenceError, match=reason):
        load_student_public_candidate_inventory(path, expected_sha256=sha)


def test_text_inventory_wrong_file_digest_fails(tmp_path):
    path, _ = _write(tmp_path, _document())
    with pytest.raises(MultilevelEvidenceError, match="digest differs"):
        load_student_public_candidate_inventory(path, expected_sha256="a" * 64)


def test_worker_rejects_unknown_inventory_kind(tmp_path):
    document = _document()
    document["inventory_kind"] = "UNKNOWN_INVENTORY_KIND"
    path, sha = _write(tmp_path, document)
    with pytest.raises(worker.SealedReleaseIngestionError, match="inventory kind"):
        worker._load_candidate_discovery(path, expected_sha256=sha)


def test_text_inventory_rejects_invalid_source_url_port(tmp_path):
    document = _document()
    document["collections"][0]["candidates"][0]["placements"][0]["source_url"] = (
        "https://eduscol.education.gouv.fr:bad/5823/ressources"
    )
    path, sha = _write(tmp_path, document)
    with pytest.raises(MultilevelEvidenceError, match="source URL"):
        load_student_public_candidate_inventory(path, expected_sha256=sha)


def test_v1_pdf_reader_and_worker_join_are_unchanged():
    sha = hashlib.sha256(V4.read_bytes()).hexdigest()
    inventory = load_multilevel_candidate_inventory(V4, expected_sha256=sha)
    discovery = worker._load_candidate_discovery(V4, expected_sha256=sha)
    assert len(inventory.placements) == len(discovery)
    assert len(inventory.placements) == 479
    assert all(p.physical_path.startswith("01_EDUSCOL_OFFICIEL/")
               for p in inventory.placements)
