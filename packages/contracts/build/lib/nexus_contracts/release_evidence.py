"""Preuves canoniques H2 et promotion pour une release multi-autorisation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal

from pydantic import (
    AwareDatetime,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from nexus_contracts.document import StrictBaseModel

H2_EVIDENCE_V2_PROTOCOL_VERSION = "NEXUS-H2-EVIDENCE-V2"
PROMOTION_EVIDENCE_V2_PROTOCOL_VERSION = "NEXUS-PROMOTION-EVIDENCE-V2"
EXACT_HEAD_RECEIPT_MAX_AGE = timedelta(days=7)

_HEX40 = r"^[0-9a-f]{40}$"
_HEX64 = r"^[0-9a-f]{64}$"
_OCI_DIGEST = r"^sha256:[0-9a-f]{64}$"
_CAMPAIGN_ID = r"^[a-z0-9][a-z0-9._-]{2,63}$"
_REQUIRED_INPUT_DIGESTS = frozenset(
    {
        "authorization_set",
        "authority_revocations",
        "catalog",
        "currentness_verification",
        "golden",
        "pii",
        "release_scope_placement",
        "review_binding_trust_anchor",
        "rights",
        "routing",
        "trusted_reviewers",
    }
)


class ReleaseEvidenceError(ValueError):
    """La preuve ne lie pas exactement une release promouvable."""


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def _canonical_moment(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _parse_canonical(
    raw: bytes,
    *,
    protocol: str,
    model: type[H2EvidenceBundleV2] | type[PromotionEvidenceV2],
) -> H2EvidenceBundleV2 | PromotionEvidenceV2:
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseEvidenceError(f"release evidence is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ReleaseEvidenceError("release evidence must be a JSON object")
    if document.get("protocol_version") != protocol:
        raise ReleaseEvidenceError(f"protocol_version is not {protocol!r}")
    try:
        parsed = model.model_validate(document)
    except Exception as exc:  # noqa: BLE001 - frontière stricte de contrat
        raise ReleaseEvidenceError(f"release evidence failed validation: {exc}") from exc
    if parsed.canonical_bytes() != raw:
        raise ReleaseEvidenceError("release evidence bytes are not canonical")
    return parsed


class H2EvidenceBundleV2(StrictBaseModel):
    """Identité globale d'une preuve H2 multi-autorisation."""

    protocol_version: Literal["NEXUS-H2-EVIDENCE-V2"]
    repository: StrictStr = Field(pattern=r"^[^/\s]+/[^/\s]+$")
    pull_request_number: StrictInt = Field(gt=0)
    pr_head_sha: StrictStr = Field(pattern=_HEX40)
    pr_head_tree_sha: StrictStr = Field(pattern=_HEX40)
    merge_sha: StrictStr = Field(pattern=_HEX40)
    merge_tree_sha: StrictStr = Field(pattern=_HEX40)

    campaign_id: StrictStr = Field(pattern=_CAMPAIGN_ID)
    campaign_digest: StrictStr = Field(pattern=_HEX64)
    source_oci_digest: StrictStr = Field(pattern=_OCI_DIGEST)
    source_archive_sha256: StrictStr = Field(pattern=_HEX64)
    source_tree_digest: StrictStr = Field(pattern=_HEX64)
    corpus_manifest_sha256: StrictStr = Field(pattern=_HEX64)
    catalog_sha256: StrictStr = Field(pattern=_HEX64)
    review_view_sha256: StrictStr = Field(pattern=_HEX64)
    profile_manifest_digest: StrictStr = Field(pattern=_HEX64)

    authorization_set_digest: StrictStr = Field(pattern=_HEX64)
    authorization_count: StrictInt = Field(gt=0)
    authority_required_count: StrictInt = Field(gt=0)
    authority_required_set_sha256: StrictStr = Field(pattern=_HEX64)
    release_scope_source_tree_sha: StrictStr = Field(pattern=_HEX40)
    release_scope_placement_digest: StrictStr = Field(pattern=_HEX64)
    release_scope_source_blob_digests: dict[StrictStr, StrictStr] = Field(min_length=1)
    revocation_registry_sha256: StrictStr = Field(pattern=_HEX64)
    review_binding_trust_anchor_sha256: StrictStr = Field(pattern=_HEX64)
    trusted_reviewers_sha256: StrictStr = Field(pattern=_HEX64)
    input_file_digests: dict[StrictStr, StrictStr]

    authorization_set_verified_at: AwareDatetime
    earliest_review_submitted_at: AwareDatetime
    earliest_review_binding_verified_at: AwareDatetime
    earliest_review_binding_expires_at: AwareDatetime
    authorizations_effective_valid_from: AwareDatetime
    authorizations_effective_valid_until: AwareDatetime

    h2_coverage_generated_at: AwareDatetime
    h2_coverage_evidence_sha256: StrictStr = Field(pattern=_HEX64)
    h2_coverage_gate_pass: StrictBool
    authority_revocations_checked: StrictBool
    authority_review_bindings_verified: StrictBool
    coverage_complete: StrictBool
    authority_covered_count: StrictInt = Field(ge=0)
    authorization_overlap_count: StrictInt = Field(ge=0)
    authorization_gap_count: StrictInt = Field(ge=0)
    authorization_extra_count: StrictInt = Field(ge=0)

    environment: Literal["production"]
    workflow_path: Literal[".github/workflows/_produce-h2-evidence.yml"]
    run_id: StrictStr = Field(min_length=1)
    run_attempt: StrictInt = Field(gt=0)

    @field_validator("input_file_digests", "release_scope_source_blob_digests")
    @classmethod
    def _mapping_values_are_sha256(
        cls, value: dict[str, str]
    ) -> dict[str, str]:
        invalid = sorted(
            key
            for key, digest in value.items()
            if len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        )
        if invalid:
            raise ValueError(f"mapping values must be lowercase SHA-256: {invalid}")
        return value

    @model_validator(mode="after")
    def _exact_release_is_passing(self) -> H2EvidenceBundleV2:
        if self.pr_head_tree_sha != self.merge_tree_sha:
            raise ValueError("pr_head_tree_sha does not equal merge_tree_sha")
        if self.release_scope_source_tree_sha != self.merge_tree_sha:
            raise ValueError(
                "release_scope_source_tree_sha does not equal merge_tree_sha"
            )
        if set(self.input_file_digests) != _REQUIRED_INPUT_DIGESTS:
            raise ValueError(
                "input_file_digests has an unexpected key set "
                f"(got={sorted(self.input_file_digests)}, "
                f"expected={sorted(_REQUIRED_INPUT_DIGESTS)})"
            )
        digest_links = {
            "authorization_set": self.authorization_set_digest,
            "authority_revocations": self.revocation_registry_sha256,
            "catalog": self.catalog_sha256,
            "release_scope_placement": self.release_scope_placement_digest,
            "review_binding_trust_anchor": self.review_binding_trust_anchor_sha256,
            "trusted_reviewers": self.trusted_reviewers_sha256,
        }
        for key, expected in digest_links.items():
            if self.input_file_digests.get(key) != expected:
                raise ValueError(f"input_file_digests[{key!r}] does not match {key}")
        if self.authorization_count > self.authority_required_count:
            raise ValueError("authorization_count exceeds authority_required_count")
        if self.authority_covered_count != self.authority_required_count:
            raise ValueError("authority_covered_count does not equal authority_required_count")
        if not (
            self.h2_coverage_gate_pass
            and self.authority_revocations_checked
            and self.authority_review_bindings_verified
            and self.coverage_complete
            and self.authorization_overlap_count == 0
            and self.authorization_gap_count == 0
            and self.authorization_extra_count == 0
        ):
            raise ValueError("H2 evidence bundle does not prove an exact passing release")
        if not (
            self.earliest_review_submitted_at
            <= self.earliest_review_binding_verified_at
            <= self.authorization_set_verified_at
            <= self.h2_coverage_generated_at
            < self.earliest_review_binding_expires_at
        ):
            raise ValueError("review binding aggregate chronology is inconsistent")
        if self.authorizations_effective_valid_until <= self.authorizations_effective_valid_from:
            raise ValueError("authorization-set effective window is empty")
        if not all(
            path
            and not path.startswith("/")
            and ".." not in path.split("/")
            for path in self.release_scope_source_blob_digests
        ):
            raise ValueError("release scope source path is unsafe")
        return self

    @property
    def artifact_name(self) -> str:
        return f"h2-evidence-{self.merge_sha}-{self.campaign_id}"

    def canonical_document(self) -> dict[str, Any]:
        document = self.model_dump(mode="json")
        for field_name in (
            "authorization_set_verified_at",
            "earliest_review_submitted_at",
            "earliest_review_binding_verified_at",
            "earliest_review_binding_expires_at",
            "authorizations_effective_valid_from",
            "authorizations_effective_valid_until",
            "h2_coverage_generated_at",
        ):
            document[field_name] = _canonical_moment(getattr(self, field_name))
        document["input_file_digests"] = dict(sorted(self.input_file_digests.items()))
        document["release_scope_source_blob_digests"] = dict(
            sorted(self.release_scope_source_blob_digests.items())
        )
        return document

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.canonical_document())

    def digest(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()


def parse_h2_evidence_bundle_v2(raw: bytes) -> H2EvidenceBundleV2:
    parsed = _parse_canonical(
        raw,
        protocol=H2_EVIDENCE_V2_PROTOCOL_VERSION,
        model=H2EvidenceBundleV2,
    )
    assert isinstance(parsed, H2EvidenceBundleV2)
    return parsed


def verify_h2_evidence_bundle_v2_freshness(
    bundle: H2EvidenceBundleV2, *, now: datetime
) -> None:
    """Vérifie les bornes temporelles à l'instant de promotion."""
    if now.tzinfo is None:
        raise ReleaseEvidenceError("now must carry an explicit timezone")
    reference = now.astimezone(UTC)
    for field_name in (
        "earliest_review_binding_verified_at",
        "earliest_review_submitted_at",
    ):
        moment = getattr(bundle, field_name).astimezone(UTC)
        if moment > reference:
            raise ReleaseEvidenceError(f"{field_name} is in the future")
        if reference - moment > EXACT_HEAD_RECEIPT_MAX_AGE:
            raise ReleaseEvidenceError(f"{field_name} is older than 7 days")
    for field_name in (
        "authorization_set_verified_at",
        "h2_coverage_generated_at",
    ):
        if getattr(bundle, field_name).astimezone(UTC) > reference:
            raise ReleaseEvidenceError(f"{field_name} is in the future")
    if reference >= bundle.earliest_review_binding_expires_at.astimezone(UTC):
        raise ReleaseEvidenceError("one or more review bindings expired")
    if reference < bundle.authorizations_effective_valid_from.astimezone(UTC):
        raise ReleaseEvidenceError("one or more authorizations are not yet valid")
    if reference >= bundle.authorizations_effective_valid_until.astimezone(UTC):
        raise ReleaseEvidenceError("one or more authorizations expired")


class PromotionEvidenceV2(StrictBaseModel):
    """Preuve de promotion liée à un bundle H2 V2 exact."""

    protocol_version: Literal["NEXUS-PROMOTION-EVIDENCE-V2"]
    repository: StrictStr = Field(pattern=r"^[^/\s]+/[^/\s]+$")
    pull_request_number: StrictInt = Field(gt=0)
    pr_head_sha: StrictStr = Field(pattern=_HEX40)
    pr_head_tree_sha: StrictStr = Field(pattern=_HEX40)
    merge_sha: StrictStr = Field(pattern=_HEX40)
    merge_tree_sha: StrictStr = Field(pattern=_HEX40)
    campaign_id: StrictStr = Field(pattern=_CAMPAIGN_ID)
    campaign_digest: StrictStr = Field(pattern=_HEX64)
    authorization_set_digest: StrictStr = Field(pattern=_HEX64)
    authorization_count: StrictInt = Field(gt=0)
    authority_required_count: StrictInt = Field(gt=0)
    authority_required_set_sha256: StrictStr = Field(pattern=_HEX64)
    h2_artifact_name: StrictStr = Field(min_length=1)
    h2_evidence_bundle_digest: StrictStr = Field(pattern=_HEX64)
    h2_coverage_evidence_sha256: StrictStr = Field(pattern=_HEX64)
    corpus_manifest_sha256: StrictStr = Field(pattern=_HEX64)
    catalog_sha256: StrictStr = Field(pattern=_HEX64)
    review_view_sha256: StrictStr = Field(pattern=_HEX64)
    profile_manifest_digest: StrictStr = Field(pattern=_HEX64)
    release_scope_placement_digest: StrictStr = Field(pattern=_HEX64)
    revocation_registry_sha256: StrictStr = Field(pattern=_HEX64)
    review_binding_trust_anchor_sha256: StrictStr = Field(pattern=_HEX64)
    trusted_reviewers_sha256: StrictStr = Field(pattern=_HEX64)
    image_provenance_run_id: StrictInt = Field(gt=0)
    image_provenance_run_attempt: StrictInt = Field(gt=0)
    promotion_workflow_path: Literal[".github/workflows/promote.yml"]
    promotion_run_id: StrictInt = Field(gt=0)
    promotion_run_attempt: StrictInt = Field(gt=0)
    promotion_workflow_ref: Literal["refs/heads/main"]

    @model_validator(mode="after")
    def _tree_identity_is_exact(self) -> PromotionEvidenceV2:
        if self.pr_head_tree_sha != self.merge_tree_sha:
            raise ValueError("pr_head_tree_sha does not equal merge_tree_sha")
        return self

    @classmethod
    def fields_from_h2_bundle(
        cls,
        bundle: H2EvidenceBundleV2,
        *,
        image_provenance_run_id: int,
        image_provenance_run_attempt: int,
        promotion_workflow_path: str,
        promotion_run_id: int,
        promotion_run_attempt: int,
        promotion_workflow_ref: str,
    ) -> dict[str, Any]:
        return {
            "protocol_version": PROMOTION_EVIDENCE_V2_PROTOCOL_VERSION,
            "repository": bundle.repository,
            "pull_request_number": bundle.pull_request_number,
            "pr_head_sha": bundle.pr_head_sha,
            "pr_head_tree_sha": bundle.pr_head_tree_sha,
            "merge_sha": bundle.merge_sha,
            "merge_tree_sha": bundle.merge_tree_sha,
            "campaign_id": bundle.campaign_id,
            "campaign_digest": bundle.campaign_digest,
            "authorization_set_digest": bundle.authorization_set_digest,
            "authorization_count": bundle.authorization_count,
            "authority_required_count": bundle.authority_required_count,
            "authority_required_set_sha256": bundle.authority_required_set_sha256,
            "h2_artifact_name": bundle.artifact_name,
            "h2_evidence_bundle_digest": bundle.digest(),
            "h2_coverage_evidence_sha256": bundle.h2_coverage_evidence_sha256,
            "corpus_manifest_sha256": bundle.corpus_manifest_sha256,
            "catalog_sha256": bundle.catalog_sha256,
            "review_view_sha256": bundle.review_view_sha256,
            "profile_manifest_digest": bundle.profile_manifest_digest,
            "release_scope_placement_digest": bundle.release_scope_placement_digest,
            "revocation_registry_sha256": bundle.revocation_registry_sha256,
            "review_binding_trust_anchor_sha256": (
                bundle.review_binding_trust_anchor_sha256
            ),
            "trusted_reviewers_sha256": bundle.trusted_reviewers_sha256,
            "image_provenance_run_id": image_provenance_run_id,
            "image_provenance_run_attempt": image_provenance_run_attempt,
            "promotion_workflow_path": promotion_workflow_path,
            "promotion_run_id": promotion_run_id,
            "promotion_run_attempt": promotion_run_attempt,
            "promotion_workflow_ref": promotion_workflow_ref,
        }

    def canonical_document(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.canonical_document())

    def digest(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()


def parse_promotion_evidence_v2(raw: bytes) -> PromotionEvidenceV2:
    parsed = _parse_canonical(
        raw,
        protocol=PROMOTION_EVIDENCE_V2_PROTOCOL_VERSION,
        model=PromotionEvidenceV2,
    )
    assert isinstance(parsed, PromotionEvidenceV2)
    return parsed


def verify_promotion_evidence_v2(
    promotion: PromotionEvidenceV2, *, h2_bundle: H2EvidenceBundleV2
) -> None:
    expected = PromotionEvidenceV2.fields_from_h2_bundle(
        h2_bundle,
        image_provenance_run_id=promotion.image_provenance_run_id,
        image_provenance_run_attempt=promotion.image_provenance_run_attempt,
        promotion_workflow_path=promotion.promotion_workflow_path,
        promotion_run_id=promotion.promotion_run_id,
        promotion_run_attempt=promotion.promotion_run_attempt,
        promotion_workflow_ref=promotion.promotion_workflow_ref,
    )
    for field_name, expected_value in expected.items():
        if getattr(promotion, field_name) != expected_value:
            raise ReleaseEvidenceError(f"{field_name} does not match the H2 bundle")


__all__ = [
    "EXACT_HEAD_RECEIPT_MAX_AGE",
    "H2_EVIDENCE_V2_PROTOCOL_VERSION",
    "PROMOTION_EVIDENCE_V2_PROTOCOL_VERSION",
    "H2EvidenceBundleV2",
    "PromotionEvidenceV2",
    "ReleaseEvidenceError",
    "parse_h2_evidence_bundle_v2",
    "parse_promotion_evidence_v2",
    "verify_h2_evidence_bundle_v2_freshness",
    "verify_promotion_evidence_v2",
]
