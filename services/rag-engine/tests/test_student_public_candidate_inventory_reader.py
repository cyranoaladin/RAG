"""Lecteur de l'inventaire texte, séparé du format PDF historique."""

from __future__ import annotations

import copy
import hashlib
import json
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
    assert all(p.physical_path == f"{p.content_sha256}.txt" for p in inventory.placements)
    discovery = worker._load_candidate_discovery(path, expected_sha256=sha)
    assert len(discovery) == 3
    assert discovery[(first, _sha("placement-a2"))]["source_url"] == (
        "https://eduscol.education.gouv.fr/5823/ressources"
    )
    assert discovery[(first, _sha("placement-a2"))]["external_document_type"] == (
        "ressource-accompagnement"
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
