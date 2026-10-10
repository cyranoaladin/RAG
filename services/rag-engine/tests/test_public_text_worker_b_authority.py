"""Worker B public : A/C, dérivés texte et placements sans V4/V5 PDF."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from nexus_release_chain.public_successor_activation import (
    PublicSuccessorActivationVerdict,
    verify_content_anchor,
)

from ingestor.ingestion_worker.public_text_runtime_authority import (
    PublicTextRuntimeAuthorityError,
    load_public_text_runtime_authorities,
)

ROOT = Path(__file__).resolve().parents[3]
ANCHOR = ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261010.json"
RELEASE = (
    ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027"
    / "profile_gate_student_public_successor_v1/release-fcc84331e7700042"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _activation(*, expires_at: datetime | None = None) -> PublicSuccessorActivationVerdict:
    content = verify_content_anchor(ANCHOR, _sha(ANCHOR), RELEASE)
    return PublicSuccessorActivationVerdict(
        release_id=content.release_id,
        content_anchor_sha256=content.content_anchor_sha256,
        content_manifest_sha256=content.content_manifest_sha256,
        authority_envelope_sha256="a" * 64,
        artifact_registry_sha256=content.artifact_registry_sha256,
        release_registry_sha256=content.release_registry_sha256,
        scope_authority_sha256="b" * 64,
        subject_sha256_by_collection=content.subject_sha256_by_collection,
        counts=content.expected_counts,
        expires_at_utc=expires_at or datetime.now(UTC) + timedelta(minutes=5),
    )


def _transfer_manifest(tmp_path: Path) -> tuple[Path, str]:
    registry = json.loads((RELEASE / "profile_gate/artifacts.release.json").read_text())
    path = tmp_path / "transfer.json"
    path.write_text(
        json.dumps(
            {"files": [{"file": f"{row['content_sha256']}.txt"} for row in registry["artifacts"]]},
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path, _sha(path)


def _load(tmp_path: Path, *, activation: PublicSuccessorActivationVerdict | None = None):
    transfer, digest = _transfer_manifest(tmp_path)
    return load_public_text_runtime_authorities(
        release_root=RELEASE,
        content_anchor_path=ANCHOR,
        expected_content_anchor_sha256=_sha(ANCHOR),
        activation=activation,
        transfer_manifest_path=transfer,
        expected_transfer_manifest_sha256=digest,
    )


def test_worker_b_public_adapter_requires_typed_c_before_building_any_authority(
    tmp_path: Path,
) -> None:
    with pytest.raises(PublicTextRuntimeAuthorityError, match="activation C"):
        _load(tmp_path)


def test_worker_b_public_adapter_rejects_expired_or_foreign_c(tmp_path: Path) -> None:
    with pytest.raises(PublicTextRuntimeAuthorityError, match="expired"):
        _load(tmp_path, activation=_activation(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    foreign = _activation()
    object.__setattr__(foreign, "content_manifest_sha256", "f" * 64)
    with pytest.raises(PublicTextRuntimeAuthorityError, match="differs"):
        _load(tmp_path, activation=foreign)


def test_worker_b_public_adapter_resolves_text_derivative_and_exact_student_scope(
    tmp_path: Path,
) -> None:
    authorities = _load(tmp_path, activation=_activation())
    assert authorities.release_id.startswith("student-public-successor-")
    assert len(authorities.sealed_release_catalog.artifacts) == 253
    assert authorities.sealed_release_catalog.media_type_invariant == "text/plain; charset=utf-8"
    assert len(authorities.placement_resolver.collections) == 11

    inventory = json.loads((RELEASE / "profile_gate/candidate_inventory.json").read_text())
    first = inventory["collections"][0]
    candidate = first["candidates"][0]
    placement = candidate["placements"][0]
    collection = first["collection"]
    resolver = authorities.placement_resolver
    subject = json.loads((RELEASE / "profile_gate/subjects" / f"{collection}.release.json").read_text())
    verified = resolver.resolve(
        content_sha256=candidate["content_sha256"],
        collection=collection,
        profile_version=subject["profile"]["version"],
        school_year=subject["school_year"],
        claimed_source_path=candidate["physical_path"],
        claimed_type_doc=authorities.sealed_release_catalog.artifacts[candidate["content_sha256"]]["type_doc"],
    )
    assert verified.nexus_scope.visibility == "public"
    assert verified.source_path.endswith(".txt")
    assert verified.source_placement_id == placement["source_placement_id"]
    authorities.pii_evidence_registry.verify_content_clearance(candidate["content_sha256"])
    rights = authorities.rights_evidence_registry.resolve_rights(
        content_sha256=candidate["content_sha256"], source_path=candidate["physical_path"]
    )
    assert rights.rights.value == "public_allowed"
    with pytest.raises(PublicTextRuntimeAuthorityError):
        resolver.resolve(
            content_sha256=candidate["source_pdf_sha256"],
            collection=collection,
            profile_version=subject["profile"]["version"],
            school_year=subject["school_year"],
        )


def test_worker_b_public_adapter_resolves_all_377_A_placements(tmp_path: Path) -> None:
    authorities = _load(tmp_path, activation=_activation())
    inventory = json.loads((RELEASE / "profile_gate/candidate_inventory.json").read_text())
    tested = 0
    for collection_row in inventory["collections"]:
        collection = collection_row["collection"]
        subject = json.loads(
            (RELEASE / "profile_gate/subjects" / f"{collection}.release.json").read_text()
        )
        for candidate in collection_row["candidates"]:
            resolved = authorities.placement_resolver.resolve(
                content_sha256=candidate["content_sha256"],
                collection=collection,
                profile_version=subject["profile"]["version"],
                school_year=subject["school_year"],
            )
            assert resolved.nexus_collection == collection
            assert resolved.nexus_scope.visibility == "public"
            assert resolved.source_path == candidate["physical_path"]
            tested += 1
    assert tested == 377
