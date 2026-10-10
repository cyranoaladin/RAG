"""Vérifie la proposition de politique étudiante sans émettre de scope actif."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import yaml
from nexus_contracts.scope import RetrievalScopeTargetPolicy
from pydantic import ValidationError

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
COLLECTION_COUNT = 11
ARTIFACT_COUNT = 253
AUTHORITY_ID = "EDUSCOL_ETALAB_2_0_SITEWIDE"
POLICY_KIND = "NEXUS_STUDENT_PUBLIC_DERIVATIVE_SCOPE_POLICY_PROPOSAL_V1"
BINDING_KEYS = {"collection", "candidate_subject_sha256", "candidate_profile_fingerprint",
                "evidence_visibility", "policy_visibility", "rights_basis", "rights",
                "material_kind", "target_policy", "final_subject_sha256", "scope_id"}


class PublicScopePolicyError(ValueError):
    """La proposition ne correspond pas au candidat ou élargit les droits."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(raw: bytes, code: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise PublicScopePolicyError(code) from error
    if not isinstance(value, dict):
        raise PublicScopePolicyError(code)
    return value


def _rows(value: object, code: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise PublicScopePolicyError(code)
    return value


def _unique(rows: list[Mapping[str, Any]], key: str, code: str) -> dict[str, Mapping[str, Any]]:
    values = [row.get(key) for row in rows]
    if any(not isinstance(value, str) or not value for value in values):
        raise PublicScopePolicyError(code)
    by_key = dict(zip(values, rows, strict=True))
    if len(by_key) != len(rows):
        raise PublicScopePolicyError(code)
    return by_key


def _require_sha(value: object, code: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise PublicScopePolicyError(code)
    return value


def check_public_scope_policy_authority(
    *,
    authority: Mapping[str, Any],
    aggregate_raw: bytes,
    profiles_raw: bytes,
    rights_raw: bytes,
    artifacts_raw: bytes,
    candidate_manifest_raw: bytes,
    rights_authority_raw: bytes,
    adr_raw: bytes,
    subjects_raw: Mapping[str, bytes],
) -> int:
    """Contrôle onze politiques *proposées*, sans créer un scope V3.

    La review humaine exacte de cette autorité, les nouveaux subjects finaux,
    les droits réévalués et les autorisations de publication restent distincts.
    """
    expected_top = {"authority_kind", "status", "adr", "adr_sha256", "candidate_release_id",
                    "candidate_release_manifest_sha256", "candidate_profiles_sha256",
                    "candidate_rights_registry_sha256", "candidate_derivative_manifest_sha256",
                    "rights_authority_id", "rights_authority_sha256", "student_visibility",
                    "publication_authorized", "full_pdf_redistribution_allowed",
                    "answer_generation_allowed", "bindings"}
    if (set(authority) != expected_top
            or authority.get("authority_kind") != POLICY_KIND
            or authority.get("status") != "PENDING_EXACT_HEAD_AUTHORITY_REVIEW"
            or authority.get("adr") != "ADR-0064"
            or authority.get("adr_sha256") != _sha(adr_raw)
            or authority.get("candidate_release_manifest_sha256") != _sha(aggregate_raw)
            or authority.get("candidate_profiles_sha256") != _sha(profiles_raw)
            or authority.get("candidate_rights_registry_sha256") != _sha(rights_raw)
            or authority.get("candidate_derivative_manifest_sha256") != _sha(candidate_manifest_raw)
            or authority.get("rights_authority_id") != AUTHORITY_ID
            or authority.get("rights_authority_sha256") != _sha(rights_authority_raw)
            or authority.get("student_visibility") != ["public"]
            or authority.get("publication_authorized") is not False
            or authority.get("full_pdf_redistribution_allowed") is not False
            or authority.get("answer_generation_allowed") is not False):
        raise PublicScopePolicyError("PUBLIC_SCOPE_AUTHORITY_BINDING_INVALID")
    try:
        rights_authority = yaml.safe_load(rights_authority_raw)
    except yaml.YAMLError as error:
        raise PublicScopePolicyError("ETALAB_AUTHORITY_INVALID") from error
    if (not isinstance(rights_authority, dict)
            or rights_authority.get("authority_id") != AUTHORITY_ID
            or rights_authority.get("licence_id") != "ETALAB-2.0"
            or rights_authority.get("full_pdf_redistribution_allowed_by_product") is not False
            or rights_authority.get("answer_generation_allowed") is not False):
        raise PublicScopePolicyError("ETALAB_AUTHORITY_INVALID")
    aggregate = _json(aggregate_raw, "CANDIDATE_RELEASE_INVALID")
    profiles = _json(profiles_raw, "CANDIDATE_PROFILES_INVALID")
    rights = _json(rights_raw, "CANDIDATE_RIGHTS_INVALID")
    artifacts = _json(artifacts_raw, "CANDIDATE_ARTIFACTS_INVALID")
    manifest = _json(candidate_manifest_raw, "CANDIDATE_MANIFEST_INVALID")
    refs = _unique(_rows(aggregate.get("subjects"), "CANDIDATE_SUBJECTS_INVALID"),
                   "collection", "CANDIDATE_SUBJECTS_INVALID")
    profile_by_collection = _unique(_rows(profiles.get("entries"), "CANDIDATE_PROFILES_INVALID"),
                                    "collection", "CANDIDATE_PROFILES_INVALID")
    bindings = _unique(_rows(authority.get("bindings"), "PUBLIC_SCOPE_BINDINGS_INVALID"),
                       "collection", "PUBLIC_SCOPE_BINDINGS_INVALID")
    artifact_rows = _rows(artifacts.get("artifacts"), "CANDIDATE_ARTIFACTS_INVALID")
    artifact_by_sha = _unique(artifact_rows, "content_sha256", "CANDIDATE_ARTIFACTS_INVALID")
    rights_rows = _rows(rights.get("entries"), "CANDIDATE_RIGHTS_INVALID")
    rights_by_sha = _unique(rights_rows, "content_sha256", "CANDIDATE_RIGHTS_INVALID")
    manifest_rows = _rows(manifest.get("entries"), "CANDIDATE_MANIFEST_INVALID")
    manifest_by_sha = _unique(manifest_rows, "derivative_content_sha256", "CANDIDATE_MANIFEST_INVALID")
    expected_collections = set(bindings)
    if (aggregate.get("release_id") != authority.get("candidate_release_id")
            or aggregate.get("release_mode") != "candidate"
            or aggregate.get("promotion_status") != "NOT_PROMOTABLE"
            or aggregate.get("activation_status") != "NO_PRODUCTION_ACTIVATION"
            or aggregate.get("review_status") != "PRE_REVIEW"
            or profiles.get("status") != "CANDIDATE_NOT_AUTHORIZED"
            or rights.get("status") != "CANDIDATE_NOT_AUTHORIZED"
            or manifest.get("status") != "PRE_REVIEW_NOT_PROMOTABLE"
            or aggregate.get("authorities", {}).get("public_profile_registry_sha256") != _sha(profiles_raw)
            or aggregate.get("authorities", {}).get("public_rights_registry_sha256") != _sha(rights_raw)
            or aggregate.get("authorities", {}).get("candidate_manifest_sha256") != _sha(candidate_manifest_raw)
            or aggregate.get("authorities", {}).get("rights_authority_sha256") != _sha(rights_authority_raw)
            or rights.get("rights_authority_sha256") != _sha(rights_authority_raw)
            or rights.get("authorized_use") != "student_retrieval_excerpt_only"
            or rights.get("full_pdf_redistribution_allowed") is not False
            or rights.get("answer_generation_allowed") is not False
            or len(expected_collections) != COLLECTION_COUNT
            or set(refs) != expected_collections
            or set(profile_by_collection) != expected_collections
            or set(subjects_raw) != expected_collections
            or len(artifact_by_sha) != ARTIFACT_COUNT
            or set(artifact_by_sha) != set(rights_by_sha)
            or set(artifact_by_sha) != set(manifest_by_sha)):
        raise PublicScopePolicyError("PUBLIC_SCOPE_CANDIDATE_POPULATION_INVALID")
    for sha, artifact in artifact_by_sha.items():
        source_sha = _require_sha(artifact.get("source_pdf_sha256"), "PUBLIC_SCOPE_SOURCE_SHA_INVALID")
        citation = artifact.get("citation")
        right = rights_by_sha[sha]
        manifest_row = manifest_by_sha[sha]
        if (source_sha == sha or artifact.get("artifact_id") != sha
                or artifact.get("source_path") != f"{sha}.txt"
                or artifact.get("media_type") != "text/plain; charset=utf-8"
                or not isinstance(citation, dict)
                or citation.get("source_pdf_sha256") != source_sha
                or citation.get("licence_id") != "ETALAB-2.0"
                or not isinstance(citation.get("source_updated_at"), str)
                or not citation["source_updated_at"].strip()
                or not isinstance(citation.get("source_uri"), str)
                or urlsplit(citation["source_uri"]).hostname != "eduscol.education.gouv.fr"
                or set(right) != {"content_sha256", "source_pdf_sha256",
                                      "derivative_receipt_sha256", "citation_sha256"}
                or right.get("source_pdf_sha256") != source_sha
                or right.get("derivative_receipt_sha256") != artifact.get("derivative_receipt_sha256")
                or right.get("citation_sha256") != _sha((json.dumps(
                    citation, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
                or manifest_row.get("source_content_sha256") != source_sha
                or manifest_row.get("media_type") != "text/plain; charset=utf-8"
                or manifest_row.get("citation") != {
                    key: value for key, value in citation.items()
                    if key != "source_pdf_sha256"
                }
                or manifest_row.get("derivative_receipt_sha256") != artifact.get("derivative_receipt_sha256")
                or manifest_row.get("derivative_disposition") != "APPROVE_PUBLIC"
                or manifest_row.get("source_disposition") != "REPLACE_WITH_NEW_CONTENT"):
            raise PublicScopePolicyError("PUBLIC_SCOPE_DERIVATIVE_RIGHTS_INVALID")
    for collection, binding in bindings.items():
        ref = refs[collection]
        profile = profile_by_collection[collection]
        raw = subjects_raw[collection]
        subject = _json(raw, "CANDIDATE_SUBJECT_INVALID")
        scope = profile.get("scope")
        target = binding.get("target_policy")
        if (set(binding) != BINDING_KEYS
                or _require_sha(ref.get("sha256"), "CANDIDATE_SUBJECT_SHA_INVALID") != _sha(raw)
                or binding.get("candidate_subject_sha256") != _sha(raw)
                or binding.get("candidate_profile_fingerprint") != profile.get("profile_fingerprint")
                or subject.get("collection") != collection
                or subject.get("profile", {}).get("fingerprint") != profile.get("profile_fingerprint")
                or not isinstance(scope, dict)
                or scope.get("collection") != collection
                or scope.get("visibility") != "public"
                or binding.get("evidence_visibility") != "public"
                or binding.get("policy_visibility") != "public"
                or binding.get("rights_basis") != AUTHORITY_ID
                or binding.get("rights") != ["public_allowed"]
                or binding.get("material_kind") != "text_derivative"
                or binding.get("final_subject_sha256") is not None
                or binding.get("scope_id") is not None
                or not isinstance(target, dict)):
            raise PublicScopePolicyError("PUBLIC_SCOPE_BINDING_INVALID")
        try:
            policy = RetrievalScopeTargetPolicy.model_validate(target)
        except ValidationError as error:
            raise PublicScopePolicyError("PUBLIC_SCOPE_TARGET_POLICY_INVALID") from error
        if (policy.roles != ["student"] or policy.audiences != ["libre"]
                or policy.candidates != ["libre"]
                or policy.audiences[0] not in scope.get("audience", [])
                or any(target.get(key) != scope.get(key) for key in (
                    "tenant", "niveau", "voie", "matiere", "statut_enseignement"))
                or policy.candidates[0] != scope.get("candidat")):
            raise PublicScopePolicyError("PUBLIC_SCOPE_TARGET_POLICY_INVALID")
        placements = _rows(subject.get("placements"), "CANDIDATE_PLACEMENTS_INVALID")
        if not placements or any(row.get("collection") != collection
                                 or row.get("visibility") != "public"
                                 or row.get("artifact_id") not in artifact_by_sha
                                 for row in placements):
            raise PublicScopePolicyError("PUBLIC_SCOPE_PLACEMENTS_INVALID")
    return COLLECTION_COUNT
