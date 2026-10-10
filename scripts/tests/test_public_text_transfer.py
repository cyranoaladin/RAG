"""Le transfert public ne porte que les octets textuels du successeur."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))
from public_text_transfer import (
    TransferRefused,
    observe_destination,
    plan_text_transfer,
    verify_observed_destination,
)


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fixture(tmp_path: Path) -> tuple[bytes, bytes, Path, Path, list[str]]:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "candidates").mkdir(parents=True)
    destination.mkdir()
    contents = [b"Texte pedagogique A\n", b"Texte pedagogique B\n"]
    digests = [sha(raw) for raw in contents]
    candidates = []
    expected_files = []
    for index, (digest, raw) in enumerate(zip(digests, contents, strict=True)):
        filename = f"{digest}.txt"
        (source / "candidates" / filename).write_bytes(raw)
        (destination / filename).write_bytes(raw)
        candidates.append({
            "content_sha256": digest,
            "physical_path": filename,
            "media_type": "text/plain; charset=utf-8",
            "source_pdf_sha256": f"{index + 1:064x}",
            "placements": [{"source_placement_id": f"{index + 3:064x}"}],
        })
        expected_files.append({
            "file": filename,
            "media_type": "text/plain; charset=utf-8",
            "sha256_expected": digest,
            "source_private_relpath": f"candidates/{filename}",
        })
    inventory = {
        "inventory_kind": "NEXUS_STUDENT_PUBLIC_DERIVATIVE_CANDIDATE_INVENTORY_V1",
        "release_id": "student-public-successor-test",
        "counts": {"collections": 1, "placements": 2, "unique_artifacts": 2},
        "collections": [{"collection": "rag_nexus_nsi_terminale_specialite", "candidates": candidates}],
    }
    inventory_raw = canonical(inventory)
    allowlist = {
        "kind": "NEXUS_STUDENT_PUBLIC_PRIVATE_TRANSFER_ALLOWLIST_V1",
        "release_id": inventory["release_id"],
        "candidate_inventory_sha256": sha(inventory_raw),
        "transfer_status": "NOT_TRANSFERRED",
        "allowed_file_count": 2,
        "expected_files": expected_files,
    }
    return inventory_raw, canonical(allowlist), source, destination, digests


def test_plan_et_observation_exigent_octets_exacts(tmp_path: Path) -> None:
    inventory, allowlist, source, destination, digests = fixture(tmp_path)
    manifest = plan_text_transfer(inventory, allowlist, source)
    assert manifest["file_count"] == 2
    assert manifest["placement_count"] == 2
    assert {row["sha256_expected"] for row in manifest["files"]} == set(digests)
    assert manifest["status"] == "PLANNED_NOT_TRANSFERRED"
    receipt = observe_destination(canonical(manifest), destination,
                                  target_identity="staging-final-isole",
                                  observed_at_utc="2026-10-10T17:00:00Z")
    assert receipt["status"] == "OBSERVED_NOT_PUBLICATION_AUTHORITY"
    assert receipt["file_count"] == 2
    verify_observed_destination(canonical(manifest), canonical(receipt), destination,
                                target_identity="staging-final-isole")


def test_plan_refuse_pdf_ou_source_substituee(tmp_path: Path) -> None:
    inventory, allowlist, source, _, digests = fixture(tmp_path)
    (source / "candidates" / f"{digests[0]}.txt").write_bytes(b"substitution")
    with pytest.raises(TransferRefused):
        plan_text_transfer(inventory, allowlist, source)
    document = json.loads(inventory)
    document["collections"][0]["candidates"][0]["media_type"] = "application/pdf"
    with pytest.raises(TransferRefused):
        plan_text_transfer(canonical(document), allowlist, source)


def test_observation_refuse_absent_extra_pdf_et_recu_falsifie(tmp_path: Path) -> None:
    inventory, allowlist, source, destination, digests = fixture(tmp_path)
    manifest_raw = canonical(plan_text_transfer(inventory, allowlist, source))
    (destination / f"{digests[0]}.txt").unlink()
    with pytest.raises(TransferRefused):
        observe_destination(manifest_raw, destination, "staging-final-isole", "2026-10-10T17:00:00Z")
    (destination / f"{digests[0]}.txt").write_bytes((source / "candidates" / f"{digests[0]}.txt").read_bytes())
    (destination / "intrus.pdf").write_bytes(b"PDF")
    with pytest.raises(TransferRefused):
        observe_destination(manifest_raw, destination, "staging-final-isole", "2026-10-10T17:00:00Z")
    (destination / "intrus.pdf").unlink()
    receipt = observe_destination(manifest_raw, destination, "staging-final-isole", "2026-10-10T17:00:00Z")
    receipt["target_identity"] = "autre-cible"
    with pytest.raises(TransferRefused):
        verify_observed_destination(manifest_raw, canonical(receipt), destination,
                                    target_identity="staging-final-isole")


def test_allowlist_ne_peut_pas_masquer_un_artefact(tmp_path: Path) -> None:
    inventory, allowlist, source, _, _ = fixture(tmp_path)
    document = json.loads(allowlist)
    document["expected_files"].pop()
    document["allowed_file_count"] = 1
    with pytest.raises(TransferRefused):
        plan_text_transfer(inventory, canonical(document), source)


def test_meme_artefact_duplique_dans_une_collection_est_refuse(tmp_path: Path) -> None:
    inventory, allowlist, source, _, _ = fixture(tmp_path)
    document = json.loads(inventory)
    duplicate = document["collections"][0]["candidates"][0].copy()
    duplicate["placements"] = [{"source_placement_id": f"{99:064x}"}]
    document["collections"][0]["candidates"].append(duplicate)
    document["counts"]["placements"] = 3
    listed = json.loads(allowlist)
    listed["candidate_inventory_sha256"] = sha(canonical(document))
    with pytest.raises(TransferRefused):
        plan_text_transfer(canonical(document), canonical(listed), source)
