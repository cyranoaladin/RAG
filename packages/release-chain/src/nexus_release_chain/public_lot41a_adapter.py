"""Assembler LOT41A-V2 public depuis A et des reviews réellement scellées."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from nexus_contracts.authority_artifacts import (
    ScopeAuthorizationArtifactV2,
    canonical_authorization_path,
    parse_scope_authorization_artifact,
)
from nexus_contracts.authorization_set import (
    AuthorizationSetV2,
    ReleaseScopePlacementEntryV1,
    VerifiedProfileFactV1,
    canonical_review_binding_path,
    scope_digest,
    verify_authorization_set_v2,
)
from nexus_contracts.review_binding import TrustAnchor

from nexus_release_chain.authorization_v2_producer import (
    AuthorizationFactsV1,
    produce_authorization_set_v2,
)
from nexus_release_chain.ingestion_profiles.registry import (
    load_profile_registry,
    profile_fingerprint,
)
from nexus_release_chain.public_successor_activation import (
    derive_public_release_scope_placement,
    verify_content_anchor,
    verify_content_currentness,
)


class PublicLot41AError(ValueError):
    """Les onze autorités exactes ne sont pas établies."""


def _sealed_json(path: Path, expected_sha256: str) -> dict:
    if path.is_symlink() or not path.is_file():
        raise PublicLot41AError(f"sealed material absent: {path.name}")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected_sha256:
        raise PublicLot41AError(f"sealed material digest differs: {path.name}")
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicLot41AError(f"sealed material invalid: {path.name}") from error
    if not isinstance(document, dict):
        raise PublicLot41AError(f"sealed material malformed: {path.name}")
    return document


def _positive_derivative_facts(
    release_root: Path, content, anchor_path: Path
) -> dict[str, str]:
    """Chaque dérivé de A possède droits et PII positifs sur les mêmes octets."""
    anchor = _sealed_json(anchor_path, content.content_anchor_sha256)
    gate = release_root / "profile_gate"
    rights = _sealed_json(
        gate / "public_rights_registry.json",
        anchor["preparation_sidecars"]["public_rights_registry.json"],
    )
    pii = _sealed_json(
        gate / "public_pii_registry.json",
        anchor["preparation_sidecars"]["public_pii_registry.json"],
    )
    artifacts = _sealed_json(
        gate / "artifacts.release.json", content.artifact_registry_sha256
    )
    rows = artifacts.get("artifacts")
    rights_rows = rights.get("entries")
    pii_rows = pii.get("entries")
    if (
        not isinstance(rows, list)
        or not isinstance(rights_rows, list)
        or not isinstance(pii_rows, list)
        or len(rows) != content.expected_counts["unique_artifacts"]
        or len(rights_rows) != len(rows)
        or len(pii_rows) != len(rows)
        or rights.get("kind")
        != "NEXUS_STUDENT_PUBLIC_DERIVATIVE_RIGHTS_REGISTRY_V2"
        or pii.get("kind") != "NEXUS_STUDENT_PUBLIC_DERIVATIVE_PII_REGISTRY_V2"
        or rights.get("status") != "CANDIDATE_NOT_AUTHORIZED"
        or pii.get("status") != "CANDIDATE_NOT_AUTHORIZED"
        or rights.get("release_id") != content.release_id
        or pii.get("release_id") != content.release_id
        or rights.get("authorized_use") != "student_retrieval_excerpt_only"
        or rights.get("full_pdf_redistribution_allowed") is not False
        or rights.get("answer_generation_allowed") is not False
    ):
        raise PublicLot41AError("A rights or PII population incomplete")
    artifact_by_sha = {
        row.get("content_sha256"): row for row in rows if isinstance(row, dict)
    }
    rights_by_sha = {
        row.get("content_sha256"): row for row in rights_rows if isinstance(row, dict)
    }
    pii_by_sha = {
        row.get("content_sha256"): row for row in pii_rows if isinstance(row, dict)
    }
    if any(
        len(index) != len(rows)
        for index in (artifact_by_sha, rights_by_sha, pii_by_sha)
    ):
        raise PublicLot41AError("A rights or PII identity duplicated")
    if set(artifact_by_sha) != set(rights_by_sha) or set(artifact_by_sha) != set(
        pii_by_sha
    ):
        raise PublicLot41AError("A rights or PII identity missing")
    domains: dict[str, str] = {}
    for content_sha, artifact in artifact_by_sha.items():
        if not isinstance(content_sha, str):
            raise PublicLot41AError("A derivative identity malformed")
        right = rights_by_sha[content_sha]
        pii_evidence = pii_by_sha[content_sha]
        if (
            right.get("rights_basis") != "EDUSCOL_ETALAB_2_0_SITEWIDE"
            or pii_evidence.get("pii_gate_status")
            != "PASS_BY_DERIVATIVE_FULL_TEXT_ADJUDICATION"
            or any(
                row.get("source_pdf_sha256") != artifact.get("source_pdf_sha256")
                or row.get("derivative_receipt_sha256")
                != artifact.get("derivative_receipt_sha256")
                for row in (right, pii_evidence)
            )
        ):
            raise PublicLot41AError("A rights or PII proof differs from derivative")
        source_url = artifact.get("source_url")
        if not isinstance(source_url, str):
            raise PublicLot41AError("A source URI missing")
        url = urlsplit(source_url)
        if url.scheme != "https" or url.netloc != "eduscol.education.gouv.fr":
            raise PublicLot41AError("A source is outside the sealed Eduscol authority")
        domains[content_sha] = url.netloc
    return domains


def build_public_lot41a_set(
    *,
    anchor_path: Path,
    anchor_sha256: str,
    release_root: Path,
    authorization_ids: tuple[str, ...],
    release_files: Mapping[str, bytes],
    trust_anchor: TrustAnchor,
    environment: Literal["production", "test"],
    now_utc: datetime,
    accepted_reviewers: tuple[str, ...],
    revocation_registry_raw: bytes,
) -> AuthorizationSetV2:
    """Dériver le set V2 de A puis vérifier chaque revue signée avant sortie.

    Aucun SHA d'autorisation ou de revue n'est fabriqué depuis les placements.
    """
    content = verify_content_anchor(anchor_path, anchor_sha256, release_root)
    expiry = verify_content_currentness(release_root, content, now_utc)
    projection = derive_public_release_scope_placement(release_root, content)
    if len(authorization_ids) != len(content.subject_sha256_by_collection) or len(
        set(authorization_ids)
    ) != len(authorization_ids):
        raise PublicLot41AError("11 reviewed authorizations required for A")
    expected_paths = {
        path
        for authorization_id in authorization_ids
        for path in (
            canonical_authorization_path(authorization_id),
            canonical_review_binding_path(authorization_id),
        )
    }
    if set(release_files) != expected_paths:
        raise PublicLot41AError("reviewed authorization material incomplete or extra")
    domains_by_content = _positive_derivative_facts(release_root, content, anchor_path)
    profiles = load_profile_registry(release_root / "profile_gate/profiles")
    by_collection = {
        str(profile.scope.collection): profile for profile in profiles.values()
    }
    if set(by_collection) != set(content.subject_sha256_by_collection):
        raise PublicLot41AError("A profile population differs")
    profile_facts = []
    projection_by_scope: dict[str, list[ReleaseScopePlacementEntryV1]] = {}
    for entry in projection.placements:
        digest = scope_digest(entry.scope)
        projection_by_scope.setdefault(digest, []).append(entry)
    for collection, profile in sorted(by_collection.items()):
        profile_entries = [
            entry for entry in projection.placements if entry.profile_id == collection
        ]
        if not profile_entries or any(
            entry.profile_fingerprint != profile_fingerprint(profile)
            or entry.profile_version != profile.profile_version
            or scope_digest(entry.scope) != scope_digest(profile.scope)
            for entry in profile_entries
        ):
            raise PublicLot41AError("A profile facts differ from sealed profile")
        profile_facts.append(
            VerifiedProfileFactV1(
                profile_id=collection,
                profile_version=profile.profile_version,
                profile_fingerprint=profile_fingerprint(profile),
                scope=profile.scope,
            )
        )
    facts = {}
    observed_collections = set()
    pii_ref = (
        "profile_gate/public_pii_registry.json@sha256:"
        + _sealed_json(anchor_path, anchor_sha256)["preparation_sidecars"][
            "public_pii_registry.json"
        ]
    )
    for authorization_id in authorization_ids:
        raw = release_files[canonical_authorization_path(authorization_id)]
        authorization = parse_scope_authorization_artifact(raw)
        if not isinstance(authorization, ScopeAuthorizationArtifactV2):
            raise PublicLot41AError("public LOT41A requires V2 artifacts")
        if authorization.exclusions:
            raise PublicLot41AError("public LOT41A authorization exclusions refused")
        digest = scope_digest(authorization.scope)
        scope_entries = projection_by_scope.get(digest)
        collection = str(authorization.scope.collection)
        if (
            authorization.authorization_id != authorization_id
            or scope_entries is None
            or digest in facts
            or collection in observed_collections
            or authorization.scope.visibility != "public"
            or tuple(right.value for right in authorization.rights_categories)
            != ("public_allowed",)
            or authorization.pii_absence_evidence != pii_ref
            or authorization.valid_until > expiry
            or tuple(authorization.allowed_domains)
            != tuple(
                sorted(
                    {
                        domains_by_content[entry.content_sha256]
                        for entry in scope_entries
                    }
                )
            )
        ):
            raise PublicLot41AError(
                "public LOT41A scope, rights or validity differs from A"
            )
        observed_collections.add(collection)
        facts[digest] = AuthorizationFactsV1(
            authorization_id=authorization_id,
            authorization_digest=sha256(raw).hexdigest(),
            review_binding_digest=sha256(
                release_files[canonical_review_binding_path(authorization_id)]
            ).hexdigest(),
            valid_from=authorization.valid_from,
            valid_until=authorization.valid_until,
        )
    if observed_collections != set(content.subject_sha256_by_collection):
        raise PublicLot41AError("public LOT41A collection population incomplete")
    authorization_set = produce_authorization_set_v2(
        release_scope_placement=projection,
        authorization_facts_by_scope_digest=facts,
        corpus_manifest_sha256=content.content_manifest_sha256,
    )
    verify_authorization_set_v2(
        authorization_set,
        release_files=release_files,
        trust_anchor=trust_anchor,
        environment=environment,
        now=now_utc,
        expected_repository="cyranoaladin/RAG",
        accepted_reviewers=accepted_reviewers,
        release_scope_placement=projection,
        verified_profiles=tuple(profile_facts),
        revocation_registry_raw=revocation_registry_raw,
    )
    return authorization_set
