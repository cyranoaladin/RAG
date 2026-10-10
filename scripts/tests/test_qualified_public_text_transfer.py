"""Le transfert qualifié lie A et une cible observée, sans promouvoir le reçu V1."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))
from public_text_transfer import (
    TransferRefused,
    canonical,
    digest,
    observe_destination,
    plan_text_transfer,
)
from qualified_public_text_transfer import (
    attest_qualified_transfer_target,
    verify_qualified_transfer_target,
)
from test_public_text_transfer import fixture

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
        "destination_device": destination.stat().st_dev,
        "destination_inode": destination.stat().st_ino,
        "pinned_at_utc": "2026-10-10T16:00:00Z",
        "expires_at_utc": "2026-10-11T12:00:00Z",
    })
    (tmp_path / "candidate_inventory.json").write_bytes(inventory)
    (tmp_path / "private_transfer_allowlist.json").write_bytes(allowlist)
    import qualified_public_text_transfer as qualified
    monkeypatch.setattr(qualified, "observed_host_identity",
                        lambda: ("staging-example", HOST_ID))
    monkeypatch.setattr(qualified, "postgres_database_identity",
                        lambda dsn: (SYSTEM_ID, "nexus_staging"))
    monkeypatch.setattr(qualified, "utc_now", lambda: NOW)
    return plan_raw, receipt_raw, pin_raw, destination, digests


def expected_a(destination: Path) -> dict[str, object]:
    inventory = (destination.parent / "candidate_inventory.json").read_bytes()
    allowlist = (destination.parent / "private_transfer_allowlist.json").read_bytes()
    return {
        "expected_release_id": "student-public-successor-test",
        "candidate_inventory_raw": inventory,
        "expected_candidate_inventory_sha256": digest(inventory),
        "allowlist_raw": allowlist,
        "expected_allowlist_sha256": digest(allowlist),
    }


def attest(plan_raw: bytes, receipt_raw: bytes, pin_raw: bytes,
           destination: Path) -> bytes:
    return canonical(attest_qualified_transfer_target(
        plan_raw=plan_raw, receipt_v1_raw=receipt_raw,
        target_pin_raw=pin_raw, expected_target_pin_sha256=digest(pin_raw),
        expected_content_anchor_sha256=ANCHOR,
        **expected_a(destination),
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
        **expected_a(destination),
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


def test_pin_refuse_un_autre_inode_au_meme_chemin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, receipt, pin, destination, _ = evidence(tmp_path, monkeypatch)
    document = json.loads(pin)
    document["destination_inode"] += 1
    with pytest.raises(TransferRefused, match="pin"):
        attest(plan, receipt, canonical(document), destination)


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


def test_recu_v1_anterieur_au_pin_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, receipt, pin, destination, _ = evidence(tmp_path, monkeypatch)
    prior_receipt = json.loads(receipt)
    prior_receipt["observed_at_utc"] = "2026-10-10T15:00:00Z"
    with pytest.raises(TransferRefused, match="antérieur au pin"):
        attest(plan, canonical(prior_receipt), pin, destination)


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
            **expected_a(destination),
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
            **expected_a(destination),
            destination_root=destination, database_dsn="postgresql://read-only",
        )
    with pytest.raises(TransferRefused):
        attest_qualified_transfer_target(
            plan_raw=plan, receipt_v1_raw=receipt, target_pin_raw=pin,
            expected_target_pin_sha256="f" * 64,
            expected_content_anchor_sha256=ANCHOR,
            **expected_a(destination),
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


def test_plan_et_allowlist_doivent_couvrir_la_population_exacte_de_a(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _, pin, destination, digests = evidence(tmp_path, monkeypatch)
    changed = json.loads(plan)
    changed["inventory_sha256"] = "f" * 64
    receipt = canonical(observe_destination(
        canonical(changed), destination, "staging-final", "2026-10-10T17:00:00Z",
    ))
    with pytest.raises(TransferRefused):
        attest(canonical(changed), receipt, pin, destination)
    changed = json.loads(plan)
    changed["allowlist_sha256"] = "f" * 64
    receipt = canonical(observe_destination(
        canonical(changed), destination, "staging-final", "2026-10-10T17:00:00Z",
    ))
    with pytest.raises(TransferRefused):
        attest(canonical(changed), receipt, pin, destination)
    changed = json.loads(plan)
    changed["files"] = [row for row in changed["files"] if row["sha256_expected"] != digests[0]]
    changed["file_count"] = 1
    (destination / f"{digests[0]}.txt").unlink()
    receipt = canonical(observe_destination(
        canonical(changed), destination, "staging-final", "2026-10-10T17:00:00Z",
    ))
    with pytest.raises(TransferRefused):
        attest(canonical(changed), receipt, pin, destination)


def test_parent_symbolique_interdit_meme_si_destination_resout_au_bon_chemin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, receipt, pin, destination, _ = evidence(tmp_path, monkeypatch)
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(TransferRefused):
        attest(plan, receipt, pin, alias / destination.name)


def test_bascule_parent_pendant_rehash_refusee(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, _, pin, original, _ = evidence(tmp_path, monkeypatch)
    mount = tmp_path / "mount"
    mount.mkdir()
    destination = mount / "store"
    shutil.copytree(original, destination)
    shutil.copy2(tmp_path / "candidate_inventory.json", mount)
    shutil.copy2(tmp_path / "private_transfer_allowlist.json", mount)
    receipt = canonical(observe_destination(
        plan, destination, "staging-final", "2026-10-10T17:00:00Z",
    ))
    pin_doc = json.loads(pin)
    pin_doc["destination_realpath"] = str(destination.resolve())
    pin_doc["destination_device"] = destination.stat().st_dev
    pin_doc["destination_inode"] = destination.stat().st_ino
    pin = canonical(pin_doc)
    raw = attest(plan, receipt, pin, destination)
    other = tmp_path / "other"
    other.mkdir()
    shutil.copytree(original, other / "store")
    import qualified_public_text_transfer as qualified
    original_verify = qualified.verify_observed_destination

    def switch_after_hash(*args: object) -> None:
        original_verify(*args)
        mount.rename(tmp_path / "mount-old")
        mount.symlink_to(other, target_is_directory=True)

    monkeypatch.setattr(qualified, "verify_observed_destination", switch_after_hash)
    with pytest.raises(TransferRefused):
        verify(raw, plan, receipt, pin, destination)


def test_expiration_pendant_rehash_refusee(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, receipt, pin, destination, _ = evidence(tmp_path, monkeypatch)
    raw = attest(plan, receipt, pin, destination)
    import qualified_public_text_transfer as qualified
    times = iter((NOW, datetime(2026, 10, 12, tzinfo=UTC)))
    monkeypatch.setattr(qualified, "utc_now", lambda: next(times))
    with pytest.raises(TransferRefused):
        verify(raw, plan, receipt, pin, destination)


def test_expiration_apres_rehash_avant_verdict_refusee(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, receipt, pin, destination, _ = evidence(tmp_path, monkeypatch)
    raw = attest(plan, receipt, pin, destination)
    import qualified_public_text_transfer as qualified
    times = iter((NOW, NOW, datetime(2026, 10, 12, tzinfo=UTC)))
    monkeypatch.setattr(qualified, "utc_now", lambda: next(times))
    with pytest.raises(TransferRefused):
        verify(raw, plan, receipt, pin, destination)
