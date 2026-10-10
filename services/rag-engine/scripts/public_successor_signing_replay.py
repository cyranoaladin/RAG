"""Rejouer les autorités externes du successeur public juste avant signature.

Ce pont n'interprète pas lui-même les décisions : chaque preuve est transmise
à son vérificateur canonique. L'absence d'un vérificateur ou d'une cible live
refuse la signature.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import psycopg
from nexus_release_chain.public_successor_activation import (
    PublicSuccessorActivationVerdict,
    verify_content_anchor,
    verify_public_successor_activation,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts/go_live"))
sys.path.insert(0, str(REPO_ROOT / "services/rag-engine/src"))


class PublicationSigningReplayRefused(ValueError):
    """Une des autorités externes ou son rejeu live manque."""


@dataclass(frozen=True)
class PublicationSigningInputs:
    bundle_root: Path
    repository_root: Path
    content_anchor_path: Path
    preissuance_receipt_path: Path
    private_cas_root: Path
    target_root: Path
    target_pin_path: Path
    observed_v1_receipt_path: Path
    database_dsn: str


def _bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise PublicationSigningReplayRefused("publication evidence absent or symlink")
    return path.read_bytes()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _checkout_module(name: str) -> ModuleType:
    expected = REPO_ROOT / "scripts/go_live" / f"{name}.py"
    if not expected.is_file() or expected.is_symlink():
        raise PublicationSigningReplayRefused("canonical checker absent from current checkout")
    module = importlib.import_module(name)
    if Path(getattr(module, "__file__", "")).resolve() != expected.resolve():
        raise PublicationSigningReplayRefused("canonical checker differs from current checkout")
    return module


def _verified_external_target_pin_sha256() -> str:
    """Aucun digest fourni par le bundle C ou par un flag libre ne vaut pin.

    Le protocole externe signé de qualification de cible n'existe pas encore.
    Garder ce refus explicite jusqu'à l'intégration de son vérificateur.
    """
    raise PublicationSigningReplayRefused(
        "independent target pin authority unavailable"
    )


def replay_public_successor_publication(
    inputs: PublicationSigningInputs, *, expected_release_id: str,
    expected_manifest_sha256: str, now_utc: datetime,
) -> PublicSuccessorActivationVerdict:
    """C, #294, CAS, cible V2 et LOT42 DB sont relus dans cet ordre.

    ``database_dsn`` n'est jamais écrit dans un rapport ou une exception.
    La connexion PostgreSQL est forcée en lecture seule.
    """
    if now_utc.tzinfo is None or now_utc.utcoffset() != UTC.utcoffset(now_utc):
        raise PublicationSigningReplayRefused("publication clock is not UTC")
    if inputs.repository_root.resolve() != REPO_ROOT.resolve():
        raise PublicationSigningReplayRefused("publication repository differs from signer checkout")
    if not inputs.database_dsn or not inputs.target_root.is_absolute():
        raise PublicationSigningReplayRefused("live target or read-only DB unavailable")

    root = inputs.bundle_root
    anchor_sha = _sha(_bytes(inputs.content_anchor_path))
    if _sha(_bytes(root / "content-anchor.json")) != anchor_sha:
        raise PublicationSigningReplayRefused("bundle A differs from reviewed A")
    content = verify_content_anchor(root / "content-anchor.json", anchor_sha, root / "release")
    if (content.release_id != expected_release_id
            or content.content_manifest_sha256 != expected_manifest_sha256):
        raise PublicationSigningReplayRefused("signed release differs from A")
    envelope_raw = _bytes(root / "authority-envelope.json")
    envelope_sha = _sha(envelope_raw)
    envelope = json.loads(envelope_raw)
    authorities = envelope.get("authorities")
    if not isinstance(authorities, dict):
        raise PublicationSigningReplayRefused("C authorities absent")
    scope_sha = authorities.get("public_scope_authority_sha256")
    if not isinstance(scope_sha, str):
        raise PublicationSigningReplayRefused("C scope authority absent")
    verdict = verify_public_successor_activation(
        root,
        expected_content_anchor_sha256=anchor_sha,
        expected_authority_envelope_sha256=envelope_sha,
        expected_release_id=expected_release_id,
        expected_registry_sha256=content.release_registry_sha256,
        expected_scope_authority_sha256=scope_sha,
        now_utc=now_utc,
    )
    if not isinstance(verdict, PublicSuccessorActivationVerdict) or (
        verdict.release_id != expected_release_id
        or verdict.content_manifest_sha256 != expected_manifest_sha256
        or verdict.content_anchor_sha256 != anchor_sha
        or verdict.authority_envelope_sha256 != envelope_sha
        or verdict.scope_authority_sha256 != scope_sha
        or now_utc >= verdict.expires_at_utc
    ):
        raise PublicationSigningReplayRefused("typed C verdict differs from signed release")

    # Module #294: tant que sa PR n'est pas fusionnée dans ce checkout, il
    # reste volontairement absent et l'émission est refusée.
    scope_review = _checkout_module("pr294_scope_review_receipt")
    scope_result = scope_review.check_pr294_scope_review_receipt(
        inputs.repository_root,
        root / "authorities/exact_head_scope_review_receipt_sha256.bin",
        root / "authorities/public_scope_authority_sha256.bin",
        root / "scopes",
    )
    if (scope_result.get("PR294_SCOPE_REVIEW_PASS") is not True
            or scope_result.get("PUBLIC_SCOPE_AUTHORITY_SHA256") != scope_sha
            or scope_result.get("SCOPE_COUNT") != verdict.counts["subjects"]):
        raise PublicationSigningReplayRefused("live #294 scope review differs from C")

    preissuance = _checkout_module("check_public_successor_preissuance")
    receipt_sha = _sha(_bytes(inputs.preissuance_receipt_path))
    preissuance_result = preissuance.verify_preissuance_authority(
        inputs.content_anchor_path, anchor_sha, expected_manifest_sha256,
        inputs.preissuance_receipt_path, receipt_sha,
        inputs.repository_root, inputs.private_cas_root, datetime.now(UTC),
    )
    if (preissuance_result.preissuance_verified is not True
            or preissuance_result.publication_authorized is not False
            or preissuance_result.content_anchor_sha256 != anchor_sha):
        raise PublicationSigningReplayRefused("CAS and currentness replay incomplete")

    approved_pin_sha = _verified_external_target_pin_sha256()
    qualified = _checkout_module("qualified_public_text_transfer")
    attestation_path = root / "authorities/observed_transfer_receipt_sha256.bin"
    plan_path = root / "authorities/artifact_transfer_manifest_sha256.bin"
    attestation_raw = _bytes(attestation_path)
    plan_raw = _bytes(plan_path)
    pin_raw = _bytes(inputs.target_pin_path)
    candidate_raw = _bytes(root / "release/profile_gate/candidate_inventory.json")
    allowlist_raw = _bytes(root / "release/profile_gate/private_transfer_allowlist.json")
    transfer_doc = json.loads(attestation_raw)
    plan_doc = json.loads(plan_raw)
    target_verdict = qualified.verify_qualified_transfer_target(
        attestation_raw=attestation_raw,
        expected_attestation_sha256=authorities["observed_transfer_receipt_sha256"],
        plan_raw=plan_raw,
        receipt_v1_raw=_bytes(inputs.observed_v1_receipt_path),
        target_pin_raw=pin_raw,
        expected_target_pin_sha256=approved_pin_sha,
        expected_content_anchor_sha256=anchor_sha,
        candidate_inventory_raw=candidate_raw,
        expected_candidate_inventory_sha256=content.candidate_inventory_sha256,
        allowlist_raw=allowlist_raw,
        expected_allowlist_sha256=plan_doc["allowlist_sha256"],
        expected_release_id=expected_release_id,
        destination_root=inputs.target_root,
        database_dsn=inputs.database_dsn,
    )
    if (target_verdict.attestation_sha256
            != authorities["observed_transfer_receipt_sha256"]
            or target_verdict.plan_sha256
            != authorities["artifact_transfer_manifest_sha256"]
            or target_verdict.content_anchor_sha256 != anchor_sha
            or target_verdict.release_id != expected_release_id
            or transfer_doc["target_pin_sha256"] != approved_pin_sha):
        raise PublicationSigningReplayRefused("qualified target differs from C")

    from ingestor.ingestion_worker.public_text_publication_resume_cli import (  # noqa: PLC0415
        require_public_lot42_db,
    )
    from ingestor.ingestion_worker.public_text_runtime_authority import (  # noqa: PLC0415
        load_public_text_runtime_authorities,
    )

    runtime = load_public_text_runtime_authorities(
        release_root=root / "release",
        content_anchor_path=root / "content-anchor.json",
        expected_content_anchor_sha256=anchor_sha,
        activation=verdict,
        transfer_manifest_path=plan_path,
        expected_transfer_manifest_sha256=target_verdict.plan_sha256,
        now_utc=datetime.now(UTC),
    )
    with psycopg.connect(
        inputs.database_dsn, options="-c default_transaction_read_only=on",
    ) as conn:
        require_public_lot42_db(
            conn, activation=verdict, authorities=runtime,
            transfer_sha256=target_verdict.plan_sha256,
        )
    if datetime.now(UTC) >= min(
        verdict.expires_at_utc, target_verdict.expires_at_utc,
        preissuance_result.expires_at_utc,
    ):
        raise PublicationSigningReplayRefused("public authority expired during replay")
    return verdict
