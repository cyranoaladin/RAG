"""Rejouer les préconditions de scope sur l'ancrage A, sans émettre d'autorité.

Le reçu n'est qu'un checkpoint d'identité : toutes les approbations et le CAS
privé sont revérifiés au moment de l'appel. Il n'autorise ni ingestion ni
publication et ne remplace pas la revue exacte de politique ADR-0064.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from build_public_successor_content_anchor import (
    ContentAnchorError,
    _read,
    build_content_anchor,
    inspect_content_preparation,
)

KIND = "NEXUS_PUBLIC_SUCCESSOR_PREISSUANCE_CHECKPOINT_V1"
STATUS = "CHECKPOINT_ONLY_NOT_SCOPE_AUTHORITY"


class PreissuanceError(ValueError):
    """La précondition externe ne peut pas être établie."""


@dataclass(frozen=True)
class PreissuanceVerdict:
    content_anchor_sha256: str
    content_manifest_sha256: str
    subject_sha256_by_collection: dict[str, str]
    expires_at_utc: datetime
    preissuance_verified: bool
    publication_authorized: bool = False


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_paths(
    anchor_path: Path, anchor_sha256: str, manifest_path: Path, repository_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    root = repository_root.resolve()
    resolved = manifest_path.resolve()
    if not resolved.is_relative_to(root):
        raise PreissuanceError("manifest path escapes repository")
    try:
        anchor = _read(anchor_path, anchor_sha256)
        if build_content_anchor(resolved, anchor["content_manifest_sha256"]) != anchor:
            raise PreissuanceError("content anchor differs from manifest")
        index = _read(resolved.parent.parent / "preparation-index.json",
                      anchor["preparation_index_sha256"])
    except (ContentAnchorError, KeyError, OSError) as error:
        raise PreissuanceError("content anchor or preparation unavailable") from error
    return anchor, index, str(resolved.relative_to(root))


def build_preissuance_receipt(
    anchor_path: Path, anchor_sha256: str, manifest_path: Path,
    repository_root: Path, private_cas_root: Path,
) -> dict[str, Any]:
    """Construire un checkpoint non autorisant lié au CAS attendu par #323."""
    anchor, index, relative = _source_paths(
        anchor_path, anchor_sha256, manifest_path, repository_root,
    )
    if not private_cas_root.is_dir():
        raise PreissuanceError("private CAS root absent")
    return {
        "kind": KIND,
        "status": STATUS,
        "content_anchor_sha256": anchor_sha256,
        "content_manifest_sha256": anchor["content_manifest_sha256"],
        "manifest_relative_path": relative,
        "preparation_index_sha256": anchor["preparation_index_sha256"],
        "private_cas_index_sha256": index["private_cas_manifest_sha256"],
        "source_currentness_valid_until_utc": index["source_currentness_valid_until_utc"],
        "subject_sha256_by_collection": {
            row["collection"]: row["subject_sha256"] for row in anchor["subjects"]
        },
    }


def _require_cas_index_matches(private_cas_root: Path, expected_sha256: str) -> None:
    try:
        observed = _sha(private_cas_root / "index.json")
    except OSError as error:
        raise PreissuanceError("private CAS index absent") from error
    if observed != expected_sha256:
        raise PreissuanceError("private CAS index differs")


def verify_preissuance_authority(
    anchor_path: Path, anchor_sha256: str, manifest_sha256: str,
    receipt_path: Path, receipt_sha256: str, repository_root: Path,
    private_cas_root: Path, now_utc: datetime,
) -> PreissuanceVerdict:
    """Revérifier #300/#312/#313 et les octets CAS avant émission des scopes.

    Le retour positif est une précondition de construction. Il n'émet aucun
    scope et ne dispense jamais de la review exacte ADR-0064.
    """
    if now_utc.tzinfo is None or now_utc.utcoffset() != UTC.utcoffset(now_utc):
        raise PreissuanceError("now_utc must be UTC aware")
    try:
        receipt = _read(receipt_path, receipt_sha256)
    except (ContentAnchorError, OSError) as error:
        raise PreissuanceError("preissuance receipt digest or JSON differs") from error
    if set(receipt) != {
        "kind", "status", "content_anchor_sha256", "content_manifest_sha256",
        "manifest_relative_path", "preparation_index_sha256",
        "private_cas_index_sha256", "source_currentness_valid_until_utc",
        "subject_sha256_by_collection",
    } or receipt.get("kind") != KIND or receipt.get("status") != STATUS:
        raise PreissuanceError("preissuance receipt schema differs")
    relative = receipt.get("manifest_relative_path")
    if not isinstance(relative, str):
        raise PreissuanceError("manifest path absent")
    root = repository_root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise PreissuanceError("manifest path escapes repository")
    anchor, index, normalized_relative = _source_paths(
        anchor_path, anchor_sha256, path, root,
    )
    expected = {
        "kind": KIND,
        "status": STATUS,
        "content_anchor_sha256": anchor_sha256,
        "content_manifest_sha256": manifest_sha256,
        "manifest_relative_path": normalized_relative,
        "preparation_index_sha256": anchor["preparation_index_sha256"],
        "private_cas_index_sha256": index["private_cas_manifest_sha256"],
        "source_currentness_valid_until_utc": index["source_currentness_valid_until_utc"],
        "subject_sha256_by_collection": {
            row["collection"]: row["subject_sha256"] for row in anchor["subjects"]
        },
    }
    if receipt != expected or manifest_sha256 != anchor["content_manifest_sha256"]:
        raise PreissuanceError("preissuance receipt differs from content anchor")
    try:
        expires = datetime.fromisoformat(index["source_currentness_valid_until_utc"])
    except (TypeError, ValueError) as error:
        raise PreissuanceError("currentness expiry invalid") from error
    if expires.tzinfo is None or expires.utcoffset() != UTC.utcoffset(expires):
        raise PreissuanceError("currentness expiry must be UTC aware")
    if now_utc >= expires:
        raise PreissuanceError("source currentness expired")
    _require_cas_index_matches(private_cas_root, receipt["private_cas_index_sha256"])
    try:
        replay = inspect_content_preparation(
            path, manifest_sha256, private_cas_root=private_cas_root,
            repository_root=root,
        )
    except (ContentAnchorError, OSError) as error:
        raise PreissuanceError("private CAS or GitHub review replay refused") from error
    if not (
        replay.get("inclusion_population_verified") is True
        and replay.get("private_cas_replay_verified") is True
        and replay.get("source_currentness_window_open") is True
        and replay.get("activation_allowed") is False
    ):
        raise PreissuanceError("private CAS or GitHub review replay incomplete")
    return PreissuanceVerdict(
        content_anchor_sha256=anchor_sha256,
        content_manifest_sha256=manifest_sha256,
        subject_sha256_by_collection=expected["subject_sha256_by_collection"],
        expires_at_utc=expires,
        preissuance_verified=True,
    )
