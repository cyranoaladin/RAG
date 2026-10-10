"""Attestation V2 d'une cible de transfert réellement observée.

Le reçu V1 reste ``CLAIMED_UNQUALIFIED``. Ce module le relit, compare un pin
préexistant à l'hôte et à PostgreSQL en lecture seule, puis rehache la cible.
Un pin fourni par le même poste n'est pas une autorisation : son empreinte doit
être approuvée par l'autorité C avant de devenir preuve de publication.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from public_text_transfer import (
    TransferRefused,
    _document,
    _manifest,
    _sha,
    digest,
    verify_observed_destination,
)

PIN_KIND = "NEXUS_STAGING_QUALIFIED_TARGET_PIN_V1"
ATTESTATION_KIND = "NEXUS_STUDENT_PUBLIC_QUALIFIED_TRANSFER_TARGET_ATTESTATION_V2"
ATTESTATION_STATUS = "QUALIFIED_OBSERVED_NOT_PUBLICATION_AUTHORITY"
_SYSTEM_ID = re.compile(r"[0-9]{1,20}\Z")
_PIN_FIELDS = frozenset({
    "kind", "content_anchor_sha256", "release_id", "target_identity",
    "hostname", "host_machine_id_sha256", "postgres_system_identifier",
    "database_name", "destination_realpath", "pinned_at_utc", "expires_at_utc",
})
_ATTESTATION_FIELDS = frozenset({
    "kind", "status", "content_anchor_sha256", "release_id",
    "transfer_manifest_sha256", "observed_v1_receipt_sha256", "target_pin_sha256",
    "target_identity", "hostname", "host_machine_id_sha256",
    "postgres_system_identifier", "database_name", "destination_realpath",
    "observed_at_utc", "expires_at_utc", "file_count", "derivative_receipt_count",
    "total_bytes",
})


@dataclass(frozen=True)
class QualifiedTransferVerdict:
    attestation_sha256: str
    content_anchor_sha256: str
    plan_sha256: str
    receipt_v1_sha256: str
    target_pin_sha256: str
    release_id: str
    target_identity: str
    hostname: str
    host_machine_id_sha256: str
    postgres_system_identifier: str
    database_name: str
    destination_realpath: str
    file_count: int
    expires_at_utc: datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def _utc(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise TransferRefused(f"{label}: UTC absent")
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as error:
        raise TransferRefused(f"{label}: UTC invalide") from error
    if instant.tzinfo != UTC:
        raise TransferRefused(f"{label}: UTC invalide")
    return instant


def _pin(raw: bytes, expected_sha256: str, expected_anchor_sha256: str,
         destination_root: Path) -> dict[str, object]:
    if not _sha(expected_sha256) or digest(raw) != expected_sha256:
        raise TransferRefused("digest du pin de cible divergent")
    pin = _document(raw, "pin de cible", canonical_required=True)
    if (set(pin) != _PIN_FIELDS or pin.get("kind") != PIN_KIND
            or pin.get("content_anchor_sha256") != expected_anchor_sha256
            or not _sha(expected_anchor_sha256)
            or not isinstance(pin.get("release_id"), str)
            or not pin["release_id"].startswith("student-public-")
            or not isinstance(pin.get("target_identity"), str)
            or not pin["target_identity"].strip()
            or not isinstance(pin.get("hostname"), str) or not pin["hostname"].strip()
            or not _sha(pin.get("host_machine_id_sha256"))
            or not isinstance(pin.get("postgres_system_identifier"), str)
            or _SYSTEM_ID.fullmatch(pin["postgres_system_identifier"]) is None
            or not isinstance(pin.get("database_name"), str)
            or not pin["database_name"].strip()
            or pin.get("destination_realpath") != str(destination_root.resolve(strict=True))
            or not destination_root.is_absolute() or destination_root.is_symlink()):
        raise TransferRefused("pin de cible invalide ou ne désigne pas cette destination")
    if _utc(pin["pinned_at_utc"], "date du pin") >= _utc(pin["expires_at_utc"], "expiration du pin"):
        raise TransferRefused("validité du pin inversée")
    return pin


def observed_host_identity() -> tuple[str, str]:
    """Observer l'hôte d'exécution ; ne jamais accepter un nom seul."""
    machine_id = Path("/etc/machine-id")
    if machine_id.is_symlink() or not machine_id.is_file():
        raise TransferRefused("machine-id de l'hôte indisponible")
    raw = machine_id.read_bytes().strip()
    if not raw or not re.fullmatch(rb"[0-9a-fA-F]{32}", raw):
        raise TransferRefused("machine-id de l'hôte invalide")
    hostname = socket.gethostname()
    if not hostname:
        raise TransferRefused("hostname de la cible indisponible")
    return hostname, hashlib.sha256(raw.lower()).hexdigest()


def postgres_database_identity(dsn: str) -> tuple[str, str]:
    """Réutiliser la sonde canonique en lecture seule, sans venv éditable implicite."""
    source = (Path(__file__).resolve().parents[2] / "services" / "rag-engine" / "src"
              / "ingestor" / "readiness_db.py")
    if not source.is_file():
        raise TransferRefused("readiness_db du checkout courant absent")
    try:
        spec = importlib.util.spec_from_file_location("nexus_current_readiness_db", source)
        if spec is None or spec.loader is None:
            raise ImportError("readiness_db non chargeable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except (ImportError, OSError) as error:
        raise TransferRefused("readiness_db du checkout courant indisponible") from error
    try:
        return module.postgres_database_identity(dsn)
    except Exception as error:
        raise TransferRefused("identité PostgreSQL non vérifiée") from error


def _basis(plan_raw: bytes, receipt_v1_raw: bytes, target_pin_raw: bytes, *,
           expected_target_pin_sha256: str, expected_content_anchor_sha256: str,
           destination_root: Path, database_dsn: str,
           now_utc: datetime) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    if not database_dsn or now_utc.tzinfo != UTC:
        raise TransferRefused("DSN read-only ou temps UTC absent")
    pin = _pin(target_pin_raw, expected_target_pin_sha256,
               expected_content_anchor_sha256, destination_root)
    plan = _manifest(plan_raw)
    receipt = _document(receipt_v1_raw, "reçu V1", canonical_required=True)
    if (plan["release_id"] != pin["release_id"]
            or receipt.get("kind") != "NEXUS_STUDENT_PUBLIC_TEXT_OBSERVED_TRANSFER_V1"
            or receipt.get("status") != "OBSERVED_NOT_PUBLICATION_AUTHORITY"
            or receipt.get("target_identity_status") != "CLAIMED_UNQUALIFIED"
            or receipt.get("target_identity") != pin["target_identity"]
            or receipt.get("transfer_manifest_sha256") != digest(plan_raw)
            or receipt.get("release_id") != plan["release_id"]):
        raise TransferRefused("reçu V1 non lié ou prétendument qualifié")
    if not (_utc(pin["pinned_at_utc"], "date du pin")
            < now_utc < _utc(pin["expires_at_utc"], "expiration du pin")):
        raise TransferRefused("pin absent avant observation ou expiré")
    if _utc(receipt["observed_at_utc"], "observation V1") > now_utc:
        raise TransferRefused("observation V1 future")
    hostname, machine_id_sha256 = observed_host_identity()
    db_system_id, db_name = postgres_database_identity(database_dsn)
    if (hostname != pin["hostname"] or machine_id_sha256 != pin["host_machine_id_sha256"]
            or db_system_id != pin["postgres_system_identifier"]
            or db_name != pin["database_name"]):
        raise TransferRefused("cible hôte/PostgreSQL différente du pin")
    verify_observed_destination(plan_raw, receipt_v1_raw, destination_root,
                                str(pin["target_identity"]))
    return pin, plan, receipt


def attest_qualified_transfer_target(*, plan_raw: bytes, receipt_v1_raw: bytes,
                                     target_pin_raw: bytes,
                                     expected_target_pin_sha256: str,
                                     expected_content_anchor_sha256: str,
                                     destination_root: Path,
                                     database_dsn: str) -> dict[str, object]:
    """Créer V2 depuis la cible *et la DB* vivantes, jamais depuis un checkout seul."""
    now = utc_now()
    if now.tzinfo != UTC:
        raise TransferRefused("horloge de la cible non UTC")
    observed_at_utc = now.isoformat().replace("+00:00", "Z")
    pin, plan, receipt = _basis(
        plan_raw, receipt_v1_raw, target_pin_raw,
        expected_target_pin_sha256=expected_target_pin_sha256,
        expected_content_anchor_sha256=expected_content_anchor_sha256,
        destination_root=destination_root, database_dsn=database_dsn, now_utc=now,
    )
    return {
        "kind": ATTESTATION_KIND,
        "status": ATTESTATION_STATUS,
        "content_anchor_sha256": expected_content_anchor_sha256,
        "release_id": plan["release_id"],
        "transfer_manifest_sha256": digest(plan_raw),
        "observed_v1_receipt_sha256": digest(receipt_v1_raw),
        "target_pin_sha256": expected_target_pin_sha256,
        "target_identity": pin["target_identity"],
        "hostname": pin["hostname"],
        "host_machine_id_sha256": pin["host_machine_id_sha256"],
        "postgres_system_identifier": pin["postgres_system_identifier"],
        "database_name": pin["database_name"],
        "destination_realpath": pin["destination_realpath"],
        "observed_at_utc": observed_at_utc,
        "expires_at_utc": pin["expires_at_utc"],
        "file_count": receipt["file_count"],
        "derivative_receipt_count": receipt["derivative_receipt_count"],
        "total_bytes": receipt["total_bytes"],
    }


def verify_qualified_transfer_target(*, attestation_raw: bytes,
                                     expected_attestation_sha256: str,
                                     plan_raw: bytes, receipt_v1_raw: bytes,
                                     target_pin_raw: bytes,
                                     expected_target_pin_sha256: str,
                                     expected_content_anchor_sha256: str,
                                     destination_root: Path,
                                     database_dsn: str) -> QualifiedTransferVerdict:
    """Rejouer V2 en direct avant la signature C ; un digest seul ne suffit pas."""
    now_utc = utc_now()
    if now_utc.tzinfo != UTC:
        raise TransferRefused("horloge de la cible non UTC")
    if not _sha(expected_attestation_sha256) or digest(attestation_raw) != expected_attestation_sha256:
        raise TransferRefused("digest de l'attestation V2 divergent")
    attestation = _document(attestation_raw, "attestation V2", canonical_required=True)
    if set(attestation) != _ATTESTATION_FIELDS or attestation.get("kind") != ATTESTATION_KIND:
        raise TransferRefused("attestation V2 malformée")
    if attestation.get("status") != ATTESTATION_STATUS:
        raise TransferRefused("statut de l'attestation V2 invalide")
    observed_at = _utc(attestation["observed_at_utc"], "observation V2")
    if observed_at > now_utc:
        raise TransferRefused("attestation V2 future")
    pin, plan, receipt = _basis(
        plan_raw, receipt_v1_raw, target_pin_raw,
        expected_target_pin_sha256=expected_target_pin_sha256,
        expected_content_anchor_sha256=expected_content_anchor_sha256,
        destination_root=destination_root, database_dsn=database_dsn, now_utc=now_utc,
    )
    if observed_at < _utc(pin["pinned_at_utc"], "date du pin"):
        raise TransferRefused("attestation antérieure au pin")
    if observed_at < _utc(receipt["observed_at_utc"], "observation V1"):
        raise TransferRefused("attestation antérieure au reçu V1")
    expected = {
        "kind": ATTESTATION_KIND,
        "status": ATTESTATION_STATUS,
        "content_anchor_sha256": expected_content_anchor_sha256,
        "release_id": plan["release_id"],
        "transfer_manifest_sha256": digest(plan_raw),
        "observed_v1_receipt_sha256": digest(receipt_v1_raw),
        "target_pin_sha256": expected_target_pin_sha256,
        "target_identity": pin["target_identity"],
        "hostname": pin["hostname"],
        "host_machine_id_sha256": pin["host_machine_id_sha256"],
        "postgres_system_identifier": pin["postgres_system_identifier"],
        "database_name": pin["database_name"],
        "destination_realpath": pin["destination_realpath"],
        "observed_at_utc": attestation["observed_at_utc"],
        "expires_at_utc": pin["expires_at_utc"],
        "file_count": receipt["file_count"],
        "derivative_receipt_count": receipt["derivative_receipt_count"],
        "total_bytes": receipt["total_bytes"],
    }
    if attestation != expected:
        raise TransferRefused("attestation V2 non concordante avec les preuves et la cible")
    return QualifiedTransferVerdict(
        attestation_sha256=expected_attestation_sha256,
        content_anchor_sha256=expected_content_anchor_sha256,
        plan_sha256=digest(plan_raw), receipt_v1_sha256=digest(receipt_v1_raw),
        target_pin_sha256=expected_target_pin_sha256,
        release_id=str(plan["release_id"]), target_identity=str(pin["target_identity"]),
        hostname=str(pin["hostname"]),
        host_machine_id_sha256=str(pin["host_machine_id_sha256"]),
        postgres_system_identifier=str(pin["postgres_system_identifier"]),
        database_name=str(pin["database_name"]),
        destination_realpath=str(pin["destination_realpath"]),
        file_count=int(receipt["file_count"]),
        expires_at_utc=_utc(pin["expires_at_utc"], "expiration du pin"),
    )
