"""Read-only LOT42 source for the A2 public-text successor.

This prepares review material only. A2 never authorizes publication, and no
control-plane row or projection is written here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from nexus_contracts.authority_artifacts import ReleaseBatchPublicationReviewArtifact
from nexus_release_chain.public_successor_activation import verify_content_anchor
from nexus_release_chain.public_successor_temporal import (
    verify_temporal_authority_preissuance,
)
from nexus_release_chain.release_readiness import load_release_expectation

from ingestor.ingestion_control.release_batch_attestation import (
    ReleaseBatchAttestationError,
    build_release_batch_review_artifact,
)
from ingestor.ingestion_control.sealed_release_projection import (
    DERIVATION,
    DimensionProjetee,
    ProjectionRow,
    _digest_projection,
)

_SHA = re.compile(r"[0-9a-f]{64}\Z")
TEXT_MEDIA_TYPE = "text/plain; charset=utf-8"


@dataclass(frozen=True)
class PublicBatchPlacement:
    collection: str
    artifact_id: str
    placement_id: str
    review_status: str
    placement_status: str
    currentness: str
    scope_dimensions: dict[str, str]


@dataclass(frozen=True)
class PublicBatchRelease:
    release_id: str
    release_manifest_sha256: str
    artifacts_release_sha256: str
    candidate_inventory_sha256: str
    artifact_transfer_manifest_sha256: str
    expected_counts: dict[str, int]
    collections: tuple[str, ...]
    artifact_ids: frozenset[str]
    artifact_media_types: dict[str, str]
    artifact_chunk_counts: dict[str, int]
    placements: tuple[PublicBatchPlacement, ...]


@dataclass(frozen=True)
class PublicBatchSource:
    release: PublicBatchRelease
    a2_sha256: str
    a2_valid_until: datetime
    rights_sha256: str
    pii_sha256: str
    currentness_sha256: str
    artifacts_by_sha: dict[str, dict[str, Any]]
    rights_by_sha: dict[str, dict[str, Any]]
    pii_by_sha: dict[str, dict[str, Any]]
    currentness_by_sha: dict[str, dict[str, Any]]


def _bound_json(path: Path, sha: str) -> dict[str, Any]:
    if _SHA.fullmatch(sha) is None or path.is_symlink() or not path.is_file():
        raise ReleaseBatchAttestationError(f"public source absent or unsafe: {path.name}")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ReleaseBatchAttestationError(f"public source digest differs: {path.name}")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseBatchAttestationError(f"public source JSON invalid: {path.name}") from exc
    if not isinstance(value, dict):
        raise ReleaseBatchAttestationError(f"public source object invalid: {path.name}")
    return value


def _indexed_entries(document: dict[str, Any], expected: set[str], label: str) -> dict[str, dict[str, Any]]:
    rows = document.get("entries")
    if not isinstance(rows, list) or len(rows) != len(expected) or any(
        not isinstance(row, dict) or row.get("content_sha256") not in expected
        for row in rows
    ):
        raise ReleaseBatchAttestationError(f"public {label} population invalid")
    result = {row["content_sha256"]: row for row in rows}
    if set(result) != expected or len(result) != len(rows):
        raise ReleaseBatchAttestationError(f"public {label} duplicate or missing content")
    return result


def load_public_successor_batch_source(
    *,
    release_root: Path,
    anchor_path: Path,
    anchor_sha256: str,
    a2_path: Path,
    transfer_manifest_sha256: str,
    now_utc: datetime,
) -> PublicBatchSource:
    """Replay A2 and all 253 public sidecars before examining any DB facts.

    The transfer digest must be returned by ``verify_public_transfer_offline``
    on the target's V1/V2 receipts; this loader does not assert transfer on its
    own. The canonical CLI performs that verification before calling us.
    """
    if _SHA.fullmatch(transfer_manifest_sha256) is None:
        raise ReleaseBatchAttestationError("public transfer digest invalid")
    content = verify_content_anchor(anchor_path, anchor_sha256, release_root)
    a2_raw = a2_path.read_bytes()
    expiry = verify_temporal_authority_preissuance(
        content, a2_raw, now_utc=now_utc,
    )
    expectation = load_release_expectation(
        release_root / "profile_gate/production-profile-gate.release.json",
        content.content_manifest_sha256,
    )
    if (
        expectation.release_id != content.release_id
        or expectation.release_mode != "candidate"
        or set(expectation.collections) != set(content.subject_sha256_by_collection)
        or len(expectation.placements) != content.expected_counts["placements"]
        or len(expectation.artifacts) != content.expected_counts["unique_artifacts"]
        or sum(len(row.chunks) for row in expectation.artifacts)
        != content.expected_counts["unique_chunks"]
    ):
        raise ReleaseBatchAttestationError("public A2 release identity or counts differ")
    gate = release_root / "profile_gate"
    anchor = _bound_json(anchor_path, anchor_sha256)
    sidecars = anchor["preparation_sidecars"]
    registry = _bound_json(gate / "artifacts.release.json", content.artifact_registry_sha256)
    rights_sha = sidecars["public_rights_registry.json"]
    pii_sha = sidecars["public_pii_registry.json"]
    rights = _bound_json(gate / "public_rights_registry.json", rights_sha)
    pii = _bound_json(gate / "public_pii_registry.json", pii_sha)
    currentness = _bound_json(
        gate / "public_currentness_registry.json", content.currentness_registry_sha256,
    )
    artifact_rows = registry.get("artifacts")
    if not isinstance(artifact_rows, list) or len(artifact_rows) != len(expectation.artifacts):
        raise ReleaseBatchAttestationError("public artifact registry population differs")
    artifacts = {row["content_sha256"]: row for row in artifact_rows}
    shas = {row.content_sha256 for row in expectation.artifacts}
    if len(artifacts) != len(artifact_rows) or set(artifacts) != shas:
        raise ReleaseBatchAttestationError("public artifact identities differ")
    rights_by_sha = _indexed_entries(rights, shas, "rights")
    pii_by_sha = _indexed_entries(pii, shas, "PII")
    current_by_sha = _indexed_entries(currentness, shas, "currentness")
    if (
        rights.get("release_id") != content.release_id
        or rights.get("authorized_use") != "student_retrieval_excerpt_only"
        or rights.get("full_pdf_redistribution_allowed") is not False
        or rights.get("answer_generation_allowed") is not False
        or pii.get("release_id") != content.release_id
        or currentness.get("release_id") != content.release_id
    ):
        raise ReleaseBatchAttestationError("public rights scope or sidecar release differs")
    for sha, artifact in artifacts.items():
        citation = artifact.get("citation")
        rights_row = rights_by_sha[sha]
        pii_row = pii_by_sha[sha]
        current_row = current_by_sha[sha]
        citation_raw = (
            json.dumps(citation, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        if (
            artifact.get("media_type") != TEXT_MEDIA_TYPE
            or artifact.get("source_path") != f"{sha}.txt"
            or artifact.get("source_pdf_sha256") == sha
            or not isinstance(citation, dict)
            or citation.get("licence_id") != "ETALAB-2.0"
            or citation.get("source_uri") != artifact.get("source_url")
            or not all(citation.get(key) for key in (
                "licensor", "source_updated_at", "source_label", "derivative_notice",
            ))
            or rights_row.get("rights_basis") != "EDUSCOL_ETALAB_2_0_SITEWIDE"
            or rights_row.get("citation_sha256") != hashlib.sha256(citation_raw).hexdigest()
            or pii_row.get("pii_gate_status")
            != "PASS_BY_DERIVATIVE_FULL_TEXT_ADJUDICATION"
            or current_row.get("currentness_status") != "PASS"
            or current_row.get("revocation_status") != "PASS_CURRENT_OFFICIAL_PUBLICATION"
            or any(row.get("source_pdf_sha256") != artifact.get("source_pdf_sha256")
                   for row in (rights_row, pii_row, current_row))
            or any(row.get("derivative_receipt_sha256")
                   != artifact.get("derivative_receipt_sha256")
                   for row in (rights_row, pii_row))
        ):
            raise ReleaseBatchAttestationError(f"public derivative evidence differs for {sha}")
    placements = tuple(
        PublicBatchPlacement(
            collection=row.collection,
            artifact_id=row.artifact_id,
            placement_id=str(row.payload["placement_id"]),
            review_status=str(row.payload["review_status"]),
            placement_status=str(row.payload["placement_status"]),
            currentness=str(row.payload["currentness"]),
            scope_dimensions={
                name: str(row.payload[name])
                for name in (
                    "tenant", "collection", "niveau", "voie", "matiere",
                    "candidat", "visibility", "school_year", "programme_version",
                )
            },
        ) for row in expectation.placements
    )
    release = PublicBatchRelease(
        release_id=content.release_id,
        release_manifest_sha256=content.content_manifest_sha256,
        artifacts_release_sha256=content.artifact_registry_sha256,
        candidate_inventory_sha256=content.candidate_inventory_sha256,
        artifact_transfer_manifest_sha256=transfer_manifest_sha256,
        expected_counts=dict(content.expected_counts),
        collections=tuple(sorted(expectation.collections)),
        artifact_ids=frozenset(shas),
        artifact_media_types={sha: row["media_type"] for sha, row in artifacts.items()},
        artifact_chunk_counts={row.content_sha256: len(row.chunks)
                               for row in expectation.artifacts},
        placements=placements,
    )
    return PublicBatchSource(
        release=release,
        a2_sha256=hashlib.sha256(a2_raw).hexdigest(),
        a2_valid_until=expiry,
        rights_sha256=rights_sha,
        pii_sha256=pii_sha,
        currentness_sha256=content.currentness_registry_sha256,
        artifacts_by_sha=artifacts,
        rights_by_sha=rights_by_sha,
        pii_by_sha=pii_by_sha,
        currentness_by_sha=current_by_sha,
    )


def build_public_successor_batch_projections(
    source: PublicBatchSource,
    facts: Any,
    *,
    evaluator: str,
    now_utc: datetime,
) -> tuple[tuple[ProjectionRow, ...], str]:
    """Project the measured DB population in memory, refusing any negative fact.

    Technical quality here means that the digest-verified release carries
    nonempty, page-bound chunk identities for every derivative. It does not
    claim retrieval or pedagogical quality; those remain separate gates.
    """
    if not evaluator.strip() or now_utc.tzinfo is None:
        raise ReleaseBatchAttestationError("public projection evaluator or UTC time absent")
    rows: list[ProjectionRow] = []
    for resource_id, (artifact_id, sha, collection, authorization) in sorted(
        facts.par_ressource.items(), key=lambda item: str(item[0])
    ):
        artifact = source.artifacts_by_sha.get(sha)
        rights = source.rights_by_sha.get(sha)
        pii = source.pii_by_sha.get(sha)
        currentness = source.currentness_by_sha.get(sha)
        if not all(isinstance(item, dict) for item in (artifact, rights, pii, currentness)):
            raise ReleaseBatchAttestationError(f"public projection evidence missing for {sha}")
        assert artifact is not None and rights is not None and pii is not None and currentness is not None
        chunks = artifact.get("chunks")
        pages = artifact.get("page_count")
        if (
            not isinstance(pages, int) or pages < 1
            or not isinstance(chunks, list) or not chunks
            or len(chunks) != source.release.artifact_chunk_counts.get(sha)
            or any(not isinstance(chunk, dict)
                   or _SHA.fullmatch(str(chunk.get("chunk_id", ""))) is None
                   or _SHA.fullmatch(str(chunk.get("chunk_sha256", ""))) is None
                   or not isinstance(chunk.get("page_start"), int)
                   or not isinstance(chunk.get("page_end"), int)
                   or not 1 <= chunk["page_start"] <= chunk["page_end"] <= pages
                   for chunk in chunks)
        ):
            raise ReleaseBatchAttestationError(f"public projection quality evidence missing for {sha}")
        if (
            rights.get("rights_basis") != "EDUSCOL_ETALAB_2_0_SITEWIDE"
            or pii.get("pii_gate_status") != "PASS_BY_DERIVATIVE_FULL_TEXT_ADJUDICATION"
            or currentness.get("currentness_status") != "PASS"
            or currentness.get("revocation_status") != "PASS_CURRENT_OFFICIAL_PUBLICATION"
        ):
            raise ReleaseBatchAttestationError(f"public projection negative authority for {sha}")
        quality_raw = json.dumps(
            {"sha": sha, "page_count": pages, "chunks": chunks},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        row = ProjectionRow(
            resource_id=resource_id,
            artifact_id=artifact_id,
            content_sha256=sha,
            collection=collection,
            scope_authorization_id=authorization,
            droits=DimensionProjetee(
                valeur="public_allowed", origine=DERIVATION,
                source="A2/public_rights_registry.json", digest=source.rights_sha256,
            ),
            qualite=DimensionProjetee(
                valeur=True, origine=DERIVATION,
                source="A2/sealed_text_chunk_structure",
                digest=hashlib.sha256(quality_raw).hexdigest(),
            ),
            actualite=DimensionProjetee(
                valeur=facts.currentness, origine=DERIVATION,
                source="A2/public_currentness_registry.json",
                digest=source.currentness_sha256,
            ),
            pii=DimensionProjetee(
                valeur="CLEARED", origine=DERIVATION,
                source="A2/public_pii_registry.json", digest=source.pii_sha256,
            ),
            gate_evaluator=evaluator,
            gate_evaluated_at=now_utc,
        )
        if not row.gate_passed:
            raise ReleaseBatchAttestationError(f"public projection gate refused {resource_id}")
        rows.append(row)
    if len(rows) != facts.placements:
        raise ReleaseBatchAttestationError("public projection population incomplete")
    digests = [_digest_projection(row, release_id=facts.release_id) for row in rows]
    digest = hashlib.sha256(
        json.dumps(digests, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return tuple(rows), digest


def build_public_successor_batch_review_artifact(
    *, review_id: str, facts: Any, valid_from: datetime, valid_until: datetime,
    a2_sha256: str, transfer_sha256: str, projection_digest: str, evaluator: str,
) -> ReleaseBatchPublicationReviewArtifact:
    """Bind the public evidence to the existing canonical LOT42 review contract.

    The existing provenance field is part of the reviewed canonical bytes. No
    new contract field or weaker, out-of-band sidecar is needed for this mode.
    """
    if any(_SHA.fullmatch(value) is None for value in (
        a2_sha256, transfer_sha256, projection_digest,
    )) or not evaluator.strip():
        raise ReleaseBatchAttestationError("public review evidence digest/evaluator invalid")
    if transfer_sha256 != facts.artifact_transfer_manifest_sha256:
        raise ReleaseBatchAttestationError("public review transfer digest differs")
    base = build_release_batch_review_artifact(
        review_id=review_id, facts=facts,
        valid_from=valid_from, valid_until=valid_until,
    )
    note = (
        f"{base.provenance_note} Public successor evidence: "
        f"A2_SHA256={a2_sha256}; TRANSFER_SHA256={transfer_sha256}; "
        f"PROJECTION_SHA256={projection_digest}; EVALUATOR={evaluator}."
    )
    return ReleaseBatchPublicationReviewArtifact.model_validate({
        **base.model_dump(mode="python"), "provenance_note": note,
    })


def require_reviewed_public_successor_batch(
    artifact: ReleaseBatchPublicationReviewArtifact, *, facts: Any,
    a2_sha256: str, a2_valid_until: datetime, transfer_sha256: str,
    projection_digest: str, evaluator: str, now_utc: datetime,
) -> None:
    """Rebuild reviewed bytes from live DB facts and bound A2/transfer evidence."""
    if now_utc >= a2_valid_until or artifact.valid_until > a2_valid_until:
        raise ReleaseBatchAttestationError("A2 temporal authority expired or review outlives A2")
    if now_utc < artifact.valid_from or now_utc >= artifact.valid_until:
        raise ReleaseBatchAttestationError("public batch review is not currently valid")
    expected = build_public_successor_batch_review_artifact(
        review_id=artifact.review_id, facts=facts,
        valid_from=artifact.valid_from, valid_until=artifact.valid_until,
        a2_sha256=a2_sha256, transfer_sha256=transfer_sha256,
        projection_digest=projection_digest, evaluator=evaluator,
    )
    if artifact.canonical_bytes() != expected.canonical_bytes():
        raise ReleaseBatchAttestationError(
            "public batch A2/transfer/projection binding differs from reviewed bytes"
        )


__all__ = [
    "PublicBatchRelease",
    "PublicBatchSource",
    "build_public_successor_batch_review_artifact",
    "build_public_successor_batch_projections",
    "load_public_successor_batch_source",
    "require_reviewed_public_successor_batch",
]
