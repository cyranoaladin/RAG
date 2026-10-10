"""Le transfert qualifié lie A et une cible observée, sans promouvoir le reçu V1."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))
from public_text_transfer import (  # noqa: E402
    TransferRefused,
    canonical,
    digest,
    observe_destination,
    plan_text_transfer,
)
from qualified_public_text_transfer import (  # noqa: E402
    attest_qualified_transfer_target,
    verify_qualified_transfer_target,
)
from test_public_text_transfer import fixture  # noqa: E402


ANCHOR = "a" * 64
HOST_ID = "b" * 64
SYSTEM_ID = "7549392456182038712"
NOW = datetime(2026, 10, 10, 18, 0, tzinfo=UTC)


def evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    inventory, allowlist, source, destination, digests = fixture(tmp_path)
    plan_raw = canonical(plan_text_transfer(inventory, allowlist, source))
    receipt_raw = canonical(observe_destination(
        plan_raw, destination, "staging-final", "2026-10-10T17:00:00Z",
    ))
    pin_raw = canonical({
        "kind": "NEXUS_STAGING_QUALIFIED_TARGET_PIN_V1",
        "content_anchor_sha256": ANCHOR,
        "release_id": "student-public-successor-test",
        "target_identity": "staging-final",
        "hostname": "staging-example",
        "host_machine_id_sha256": HOST_ID,
        "postgres_system_identifier": SYSTEM_ID,
        "database_name": "nexus_staging",
        "destination_realpath": str(destination.resolve()),
        "pinned_at_utc": "2026-10-10T16:00:00Z",
        "expires_at_utc": "2026-10-11T12:00:00Z",
    })
    import qualified_public_text_transfer as qualified
    monkeypatch.setattr(qualified, "observed_host_identity",
                        lambda: ("staging-example", HOST_ID))
    monkeypatch.setattr(qualified, "postgres_database_identity",
                        lambda dsn: (SYSTEM_ID, "nexus_staging"))
    monkeypatch.setattr(qualified, "utc_now", lambda: NOW)
    return plan_raw, receipt_raw, pin_raw, destination, digests


def attest(plan_raw: bytes, receipt_raw: bytes, pin_raw: bytes,
           destination: Path) -> bytes:
    return canonical(attest_qualified_transfer_target(
        plan_raw=plan_raw, receipt_v1_raw=receipt_raw,
        target_pin_raw=pin_raw, expected_target_pin_sha256=digest(pin_raw),
        expected_content_anchor_sha256=ANCHOR,
        destination_root=destination, database_dsn="postgresql://read-only",
    ))


def verify(attestation_raw: bytes, plan_raw: bytes, receipt_raw: bytes,
           pin_raw: bytes, destination: Path):
    return verify_qualified_transfer_target(
        attestation_raw=attestation_raw,
        expected_attestation_sha256=digest(attestation_raw),
        plan_raw=plan_raw, receipt_v1_raw=receipt_raw,
        target_pin_raw=pin_raw, expected_target_pin_sha256=digest(pin_raw),
        expected_content_anchor_sha256=ANCHOR,
        destination_root=destination, database_dsn="postgresql://read-only",
    )


def test_attestation_v2_lie_a_plan_recu_v1_cible_et_relecture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, receipt, pin, destination, _ = evidence(tmp_path, monkeypatch)
    raw = attest(plan, receipt, pin, destination)
    data = json.loads(raw)
    assert data["kind"] == "NEXUS_STUDENT_PUBLIC_QUALIFIED_TRANSFER_TARGET_ATTESTATION_V2"
    assert data["observed_v1_receipt_sha256"] == digest(receipt)
    assert json.loads(receipt)["target_identity_status"] == "CLAIMED_UNQUALIFIED"
    verdict = verify(raw, plan, receipt, pin, destination)
    assert verdict.attestation_sha256 == digest(raw)
    assert verdict.plan_sha256 == digest(plan)
    assert verdict.receipt_v1_sha256 == digest(receipt)
    assert verdict.content_anchor_sha256 == ANCHOR
    assert verdict.target_identity == "staging-final"
    assert verdict.file_count == 2
    assert verdict.expires_at_utc > NOW


@pytest.mark.parametrize("mutation", ["homonym_host", "other_db", "other_cluster"])
def test_cible_homonyme_ou_autre_db_refusee(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    plan, receipt, pin, destination, _ = evidence(tmp_path, monkeypatch)
    raw = attest(plan, receipt, pin, destination)
    import qualified_public_text_transfer as qualified
    if mutation == "homonym_host":
        monkeypatch.setattr(qualified, "observed_host_identity",
                            lambda: ("staging-example", "c" * 64))
    elif mutation == "other_db":
        monkeypatch.setattr(qualified, "postgres_database_identity",
                            lambda dsn: (SYSTEM_ID, "nexus_other"))
    else:
        monkeypatch.setattr(qualified, "postgres_database_identity",
                            lambda dsn: ("7" * 19, "nexus_staging"))
    with pytest.raises(TransferRefused):
        verify(raw, plan, receipt, pin, destination)


@pytest.mark.parametrize("mutation", ["missing", "added", "modified"])
def test_destination_modifiee_refusee(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    plan, receipt, pin, destination, digests = evidence(tmp_path, monkeypatch)
    raw = attest(plan, receipt, pin, destination)
    target = destination / f"{digests[0]}.txt"
    if mutation == "missing":
        target.unlink()
    elif mutation == "added":
        (destination / "intrus.txt").write_text("intrus")
    else:
        target.write_text("substitution")
    with pytest.raises(TransferRefused):
        verify(raw, plan, receipt, pin, destination)


@pytest.mark.parametrize("field", [
    "content_anchor_sha256", "transfer_manifest_sha256",
    "observed_v1_receipt_sha256", "target_pin_sha256", "host_machine_id_sha256",
])
def test_sha_lie_divergent_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str,
) -> None:
    plan, receipt, pin, destination, _ = evidence(tmp_path, monkeypatch)
    data = json.loads(attest(plan, receipt, pin, destination))
    data[field] = "f" * 64
    with pytest.raises(TransferRefused):
        verify(canonical(data), plan, receipt, pin, destination)


def test_pin_non_preexistant_ou_recu_v1_non_qualifie_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, receipt, pin, destination, _ = evidence(tmp_path, monkeypatch)
    pin_doc = json.loads(pin)
    pin_doc["pinned_at_utc"] = "2026-10-10T18:01:00Z"
    with pytest.raises(TransferRefused):
        attest(plan, receipt, canonical(pin_doc), destination)
    receipt_doc = json.loads(receipt)
    receipt_doc["target_identity_status"] = "QUALIFIED"
    with pytest.raises(TransferRefused):
        attest(plan, canonical(receipt_doc), pin, destination)


def test_attestation_expiree_refusee(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan, receipt, pin, destination, _ = evidence(tmp_path, monkeypatch)
    raw = attest(plan, receipt, pin, destination)
    import qualified_public_text_transfer as qualified
    monkeypatch.setattr(qualified, "utc_now", lambda: datetime(2026, 10, 12, tzinfo=UTC))
    with pytest.raises(TransferRefused):
        qualified.verify_qualified_transfer_target(
            attestation_raw=raw, expected_attestation_sha256=digest(raw),
            plan_raw=plan, receipt_v1_raw=receipt, target_pin_raw=pin,
            expected_target_pin_sha256=digest(pin),
            expected_content_anchor_sha256=ANCHOR, destination_root=destination,
            database_dsn="postgresql://read-only",
        )


def test_attestation_anterieure_au_recu_v1_refusee(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, receipt, pin, destination, _ = evidence(tmp_path, monkeypatch)
    data = json.loads(attest(plan, receipt, pin, destination))
    data["observed_at_utc"] = "2026-10-10T16:30:00Z"
    with pytest.raises(TransferRefused):
        verify(canonical(data), plan, receipt, pin, destination)


def test_digest_attestation_ou_pin_non_epingle_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, receipt, pin, destination, _ = evidence(tmp_path, monkeypatch)
    raw = attest(plan, receipt, pin, destination)
    with pytest.raises(TransferRefused):
        verify_qualified_transfer_target(
            attestation_raw=raw, expected_attestation_sha256="f" * 64,
            plan_raw=plan, receipt_v1_raw=receipt, target_pin_raw=pin,
            expected_target_pin_sha256=digest(pin),
            expected_content_anchor_sha256=ANCHOR,
            destination_root=destination, database_dsn="postgresql://read-only",
        )
    with pytest.raises(TransferRefused):
        attest_qualified_transfer_target(
            plan_raw=plan, receipt_v1_raw=receipt, target_pin_raw=pin,
            expected_target_pin_sha256="f" * 64,
            expected_content_anchor_sha256=ANCHOR,
            destination_root=destination, database_dsn="postgresql://read-only",
        )


def test_aucune_attestation_sans_identite_db_lue_en_direct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, receipt, pin, destination, _ = evidence(tmp_path, monkeypatch)
    import qualified_public_text_transfer as qualified
    monkeypatch.setattr(qualified, "postgres_database_identity",
                        lambda dsn: (_ for _ in ()).throw(TransferRefused("DB inaccessible")))
    with pytest.raises(TransferRefused, match="DB inaccessible"):
        attest(plan, receipt, pin, destination)
