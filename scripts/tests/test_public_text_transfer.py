"""Le transfert public ne porte que les octets textuels du successeur."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))
from public_text_transfer import (
    TransferRefused,
    build_worker_transfer_manifest,
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
    contents = [b"NEXUS-STUDENT-TEXT-DERIVATIVE-V2\nTexte pedagogique A\n",
                b"NEXUS-STUDENT-TEXT-DERIVATIVE-V2\nTexte pedagogique B\n"]
    digests = [sha(raw) for raw in contents]
    candidates = []
    expected_files = []
    for index, (digest, raw) in enumerate(zip(digests, contents, strict=True)):
        filename = f"{digest}.txt"
        (source / "candidates" / filename).write_bytes(raw)
        (destination / filename).write_bytes(raw)
        receipt_raw = canonical({"source": f"{index + 1:064x}", "text": digest})
        receipt_sha = sha(receipt_raw)
        source_receipt = source / "derivative_receipts"
        source_receipt.mkdir(parents=True, exist_ok=True)
        (source_receipt / f"{receipt_sha}.json").write_bytes(receipt_raw)
        destination_receipt = destination / "derivative_receipts"
        destination_receipt.mkdir(exist_ok=True)
        (destination_receipt / f"{receipt_sha}.json").write_bytes(receipt_raw)
        candidates.append({
            "content_sha256": digest,
            "physical_path": filename,
            "media_type": "text/plain; charset=utf-8",
            "source_pdf_sha256": f"{index + 1:064x}",
            "derivative_receipt_sha256": receipt_sha,
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
    assert manifest["derivative_receipt_count"] == 2
    assert {row["sha256_expected"] for row in manifest["files"]} == set(digests)
    assert manifest["status"] == "PLANNED_NOT_TRANSFERRED"
    receipt = observe_destination(canonical(manifest), destination,
                                  target_identity="staging-final-isole",
                                  observed_at_utc="2026-10-10T17:00:00Z")
    assert receipt["status"] == "OBSERVED_NOT_PUBLICATION_AUTHORITY"
    assert receipt["target_identity_status"] == "CLAIMED_UNQUALIFIED"
    assert receipt["destination_realpath"] == str(destination.resolve())
    assert receipt["file_count"] == 2
    assert receipt["derivative_receipt_count"] == 2
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
    derivative_receipt = next((destination / "derivative_receipts").glob("*.json"))
    derivative_receipt.unlink()
    with pytest.raises(TransferRefused):
        observe_destination(manifest_raw, destination, "staging-final-isole", "2026-10-10T17:00:00Z")
    source_receipt = next((source / "derivative_receipts").rglob(derivative_receipt.name))
    derivative_receipt.write_bytes(source_receipt.read_bytes())
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
    document = json.loads(allowlist)
    document["expected_files"].append({
        "file": f"{'f' * 64}.txt", "sha256_expected": "f" * 64,
        "source_private_relpath": f"candidates/{'f' * 64}.txt",
        "media_type": "text/plain; charset=utf-8",
    })
    document["allowed_file_count"] = 3
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


def test_cli_horodate_l_observation_lui_meme(tmp_path: Path) -> None:
    inventory, allowlist, source, destination, _ = fixture(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(canonical(plan_text_transfer(inventory, allowlist, source)))
    receipt_path = tmp_path / "receipt.json"
    before = datetime.now(UTC)
    result = subprocess.run([
        sys.executable, str(Path(__file__).resolve().parents[1] / "go_live" / "public_text_transfer.py"),
        "--observe", "--manifest", str(manifest_path), "--destination-root", str(destination),
        "--target-identity", "staging-final-isole", "--output", str(receipt_path),
    ], capture_output=True, text=True, check=False)
    after = datetime.now(UTC)
    assert result.returncode == 0, result.stderr
    observed = datetime.fromisoformat(json.loads(receipt_path.read_bytes())["observed_at_utc"])
    assert before <= observed <= after


def test_manifeste_worker_a_exige_le_recu_et_les_octets_reobserves(tmp_path: Path) -> None:
    inventory, allowlist, source, destination, digests = fixture(tmp_path)
    plan_raw = canonical(plan_text_transfer(inventory, allowlist, source))
    receipt_raw = canonical(observe_destination(plan_raw, destination,
                                                "staging-final-isole", "2026-10-10T17:00:00Z"))
    transfer = build_worker_transfer_manifest(plan_raw, receipt_raw, destination,
                                               target_identity="staging-final-isole")
    assert transfer["manifest_kind"] == "NEXUS-STAGING-ARTIFACT-TRANSFER-V1"
    assert transfer["file_count"] == 2
    assert transfer["derivative_receipt_count"] == 2
    assert transfer["destination_identity_status"] == "CLAIMED_UNQUALIFIED"
    assert transfer["digest_missing"] == transfer["digest_mismatches"] == 0
    assert {row["sha256_observed"] for row in transfer["files"]} == set(digests)
    (destination / f"{digests[0]}.txt").write_bytes(b"substitution")
    with pytest.raises(TransferRefused):
        build_worker_transfer_manifest(plan_raw, receipt_raw, destination,
                                       target_identity="staging-final-isole")


def test_plan_refuse_pdf_renomme_et_recu_source_absent(tmp_path: Path) -> None:
    inventory, allowlist, source, _, digests = fixture(tmp_path)
    document = json.loads(inventory)
    allowed = json.loads(allowlist)
    fake_pdf = b"%PDF-1.7\n"
    fake_sha = sha(fake_pdf)
    old_sha = digests[0]
    (source / "candidates" / f"{old_sha}.txt").unlink()
    (source / "candidates" / f"{fake_sha}.txt").write_bytes(fake_pdf)
    document["collections"][0]["candidates"][0]["content_sha256"] = fake_sha
    document["collections"][0]["candidates"][0]["physical_path"] = f"{fake_sha}.txt"
    allowed["expected_files"][0]["sha256_expected"] = fake_sha
    allowed["expected_files"][0]["file"] = f"{fake_sha}.txt"
    allowed["expected_files"][0]["source_private_relpath"] = f"candidates/{fake_sha}.txt"
    allowed["candidate_inventory_sha256"] = sha(canonical(document))
    with pytest.raises(TransferRefused):
        plan_text_transfer(canonical(document), canonical(allowed), source)
    receipt_file = next((source / "derivative_receipts").rglob("*.json"))
    receipt_file.unlink()
    with pytest.raises(TransferRefused):
        plan_text_transfer(inventory, allowlist, source)


def test_plan_cli_refuse_un_bundle_non_scelle(tmp_path: Path) -> None:
    inventory, allowlist, source, _, _ = fixture(tmp_path)
    inventory_path = tmp_path / "inventory.json"
    allowlist_path = tmp_path / "allowlist.json"
    inventory_path.write_bytes(inventory)
    allowlist_path.write_bytes(allowlist)
    result = subprocess.run([
        sys.executable, str(Path(__file__).resolve().parents[1] / "go_live" / "public_text_transfer.py"),
        "--plan", "--inventory", str(inventory_path), "--allowlist", str(allowlist_path),
        "--source-root", str(source), "--evidence-root", str(source),
        "--repository-root", str(Path(__file__).resolve().parents[2]),
        "--output", str(tmp_path / "plan.json"),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "autorité scellée" in result.stderr
