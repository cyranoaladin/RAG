"""Vérifie la proposition de politique étudiante sans émettre de scope actif."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from nexus_contracts import load_retrieval_scope_registry
from nexus_contracts.ingestion import CollectionProfile, collection_profile_fingerprint
from nexus_contracts.scope import RetrievalScopeTargetPolicy
from nexus_release_chain.release_readiness import (
    ReleaseReadinessError,
    load_release_expectation,
)
from pydantic import ValidationError

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
COLLECTION_COUNT = 11
ARTIFACT_COUNT = 253
AUTHORITY_ID = "EDUSCOL_ETALAB_2_0_SITEWIDE"
POLICY_KIND = "NEXUS_STUDENT_PUBLIC_DERIVATIVE_SCOPE_POLICY_PROPOSAL_V1"
BINDING_KEYS = {"collection", "candidate_subject_sha256", "candidate_profile_fingerprint",
                "evidence_visibility", "policy_visibility", "rights_basis", "rights",
                "material_kind", "target_policy", "final_subject_sha256", "scope_id"}
SUCCESSOR_DIR = Path(
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_student_public_successor_v1/release-fcc84331e7700042"
)
SUCCESSOR_INDEX_SHA256 = "bd1f714594ca17dbbe7d3cfdf255c8c270003c63bd4d267971a17b2afdb08ca4"
SUCCESSOR_MANIFEST_SHA256 = "b79246ff356b919aeb3dcb7f640a1a554e338899128a7c5acdcfaa9b7bcb1c78"
SUCCESSOR_RELEASE_ID = "student-public-successor-20261010-fcc84331e7700042"
SUCCESSOR_PROPOSAL_KIND = "NEXUS_STUDENT_PUBLIC_SUCCESSOR_SCOPE_PROPOSAL_V1"
SUCCESSOR_RIGHTS_AUTHORITY = Path(
    "governance/student_public_rights/authorities/"
    "eduscol_etalab_2_0_sitewide_20261010.yml"
)
SUCCESSOR_BINDING_KEYS = {
    "collection", "prepared_subject_sha256", "final_subject_sha256",
    "profile_fingerprint", "complete_profile_version",
    "complete_profile_fingerprint", "complete_profile_sha256",
    "proposed_scope_id", "status", "visibility", "rights_basis", "target_policy",
}


class PublicScopePolicyError(ValueError):
    """La proposition ne correspond pas au candidat ou élargit les droits."""


def check_public_successor_scope_proposal(root: Path, proposal: Mapping[str, Any]) -> int:
    """Vérifier onze scopes proposés #323 sans émettre d'artefact de scope.

    Les SHA du paquet préparatoire sont épinglés dans le code et vérifiés par
    le lecteur canonique. Ce contrôle n'autorise ni release finale ni review.
    """
    expected_top = {
        "authority_kind", "status", "source_pr", "successor_release_id",
        "successor_release_manifest_sha256", "preparation_index_sha256",
        "public_profile_registry_sha256", "rights_authority_sha256",
        "expected_population", "scope_issuance_authorized",
        "publication_authorized", "full_pdf_redistribution_allowed",
        "answer_generation_allowed", "exact_head_authority_reviewer",
        "exact_head_review_receipt", "bindings",
    }
    counts = {"subjects": 11, "unique_artifacts": 253, "placements": 377,
              "unique_chunks": 3975}
    if (
        set(proposal) != expected_top
        or proposal.get("authority_kind") != SUCCESSOR_PROPOSAL_KIND
        or proposal.get("status") != "PENDING_EXACT_HEAD_AUTHORITY_REVIEW"
        or proposal.get("source_pr") != 323
        or proposal.get("successor_release_id") != SUCCESSOR_RELEASE_ID
        or proposal.get("successor_release_manifest_sha256") != SUCCESSOR_MANIFEST_SHA256
        or proposal.get("preparation_index_sha256") != SUCCESSOR_INDEX_SHA256
        or proposal.get("expected_population") != counts
        or proposal.get("scope_issuance_authorized") is not False
        or proposal.get("publication_authorized") is not False
        or proposal.get("full_pdf_redistribution_allowed") is not False
        or proposal.get("answer_generation_allowed") is not False
        or proposal.get("exact_head_authority_reviewer") != "abenrhouma"
        or proposal.get("exact_head_review_receipt") is not None
    ):
        raise PublicScopePolicyError("SUCCESSOR_SCOPE_PROPOSAL_NOT_PENDING")
    release_dir = root / SUCCESSOR_DIR
    index_path = release_dir / "preparation-index.json"
    manifest_path = release_dir / "profile_gate/production-profile-gate.release.json"
    index_raw = index_path.read_bytes()
    if _sha(index_raw) != SUCCESSOR_INDEX_SHA256:
        raise PublicScopePolicyError("SUCCESSOR_PREPARATION_INDEX_DIVERGENT")
    index = _json(index_raw, "SUCCESSOR_PREPARATION_INDEX_INVALID")
    try:
        release = load_release_expectation(manifest_path, SUCCESSOR_MANIFEST_SHA256)
    except (ReleaseReadinessError, OSError) as error:
        raise PublicScopePolicyError("SUCCESSOR_RELEASE_INVALID") from error
    manifest = _json(manifest_path.read_bytes(), "SUCCESSOR_RELEASE_INVALID")
    if (
        release.release_id != SUCCESSOR_RELEASE_ID
        or release.release_mode != "candidate"
        or release.promotion_status != "NOT_PROMOTABLE"
        or release.activation_status != "NO_PRODUCTION_ACTIVATION"
        or release.review_status != "PRE_REVIEW"
        or len(release.collections) != 11
        or len(release.artifacts) != 253
        or len(release.placements) != 377
        or sum(len(artifact.chunks) for artifact in release.artifacts) != 3975
        or index.get("release_manifest_sha256") != SUCCESSOR_MANIFEST_SHA256
        or index.get("release_id") != SUCCESSOR_RELEASE_ID
        or index.get("expected_counts") != counts
        or manifest.get("expected_counts") != counts
        or proposal.get("public_profile_registry_sha256")
        != manifest.get("authorities", {}).get("public_profile_registry_sha256")
        or proposal.get("rights_authority_sha256")
        != manifest.get("authorities", {}).get("rights_authority_sha256")
    ):
        raise PublicScopePolicyError("SUCCESSOR_RELEASE_BINDING_INVALID")
    if _sha((root / SUCCESSOR_RIGHTS_AUTHORITY).read_bytes()) != proposal["rights_authority_sha256"]:
        raise PublicScopePolicyError("SUCCESSOR_RIGHTS_AUTHORITY_DIVERGENT")
    profile_path = release_dir / "profile_gate/public_profiles.json"
    if _sha(profile_path.read_bytes()) != proposal["public_profile_registry_sha256"]:
        raise PublicScopePolicyError("SUCCESSOR_PROFILE_DIGEST_DIVERGENT")
    profiles = _json(profile_path.read_bytes(), "SUCCESSOR_PROFILES_INVALID")
    by_profile = _unique(
        _rows(profiles.get("entries"), "SUCCESSOR_PROFILES_INVALID"),
        "collection", "SUCCESSOR_PROFILES_INVALID",
    )
    scope_rows = _unique(
        _rows(index.get("proposed_scopes"), "SUCCESSOR_SCOPES_INVALID"),
        "collection", "SUCCESSOR_SCOPES_INVALID",
    )
    bindings = _unique(
        _rows(proposal.get("bindings"), "SUCCESSOR_SCOPE_BINDINGS_INVALID"),
        "collection", "SUCCESSOR_SCOPE_BINDINGS_INVALID",
    )
    refs = _unique(
        _rows(manifest.get("subjects"), "SUCCESSOR_SUBJECTS_INVALID"),
        "collection", "SUCCESSOR_SUBJECTS_INVALID",
    )
    complete_profiles = _unique(
        _rows(index.get("complete_profiles"), "SUCCESSOR_COMPLETE_PROFILES_INVALID"),
        "collection", "SUCCESSOR_COMPLETE_PROFILES_INVALID",
    )
    collections = set(release.collections)
    if not (set(by_profile) == set(scope_rows) == set(bindings) == set(refs)
            == set(complete_profiles) == collections):
        raise PublicScopePolicyError("SUCCESSOR_SCOPE_COLLECTIONS_DIVERGENT")
    if len({row.get("proposed_scope_id") for row in bindings.values()}) != 11:
        raise PublicScopePolicyError("SUCCESSOR_SCOPE_IDS_DUPLICATED")
    active = load_retrieval_scope_registry()
    for collection, binding in bindings.items():
        profile = by_profile[collection]
        scope = profile.get("scope")
        ref = refs[collection]
        prepared = scope_rows[collection]
        complete = complete_profiles[collection]
        target = binding.get("target_policy")
        expected_profile_path = f"profile_gate/profiles/{collection}.yml"
        if complete.get("path") != expected_profile_path:
            raise PublicScopePolicyError("SUCCESSOR_PROFILE_BINDING_INVALID")
        profile_raw = (release_dir / expected_profile_path).read_bytes()
        if _sha(profile_raw) != complete.get("sha256"):
            raise PublicScopePolicyError("SUCCESSOR_PROFILE_BINDING_INVALID")
        try:
            complete_profile = CollectionProfile.model_validate(yaml.safe_load(profile_raw))
        except (ValidationError, yaml.YAMLError) as error:
            raise PublicScopePolicyError("SUCCESSOR_PROFILE_BINDING_INVALID") from error
        subject_path = release_dir / "profile_gate" / ref["path"]
        subject = _json(subject_path.read_bytes(), "SUCCESSOR_SUBJECT_INVALID")
        if (
            _sha(subject_path.read_bytes()) != ref.get("sha256")
            or complete_profile.scope.collection != collection
            or complete_profile.scope.visibility != "public"
            or complete_profile.profile_version != complete.get("profile_version")
            or collection_profile_fingerprint(complete_profile) != complete.get("fingerprint")
            or subject.get("profile") != {
                "version": complete.get("profile_version"),
                "fingerprint": complete.get("fingerprint"),
                "manifest_digest": proposal.get("public_profile_registry_sha256"),
            }
        ):
            raise PublicScopePolicyError("SUCCESSOR_PROFILE_BINDING_INVALID")
        if (
            set(binding) != SUCCESSOR_BINDING_KEYS
            or binding.get("prepared_subject_sha256") != ref.get("sha256")
            or prepared.get("final_subject_sha256") != ref.get("sha256")
            or prepared.get("proposed_scope_id") != binding.get("proposed_scope_id")
            or prepared.get("status") != "NOT_ISSUED"
            or binding.get("status") != "NOT_ISSUED"
            or binding.get("final_subject_sha256") is not None
            or binding.get("proposed_scope_id") in active
            or binding.get("profile_fingerprint") != profile.get("profile_fingerprint")
            or binding.get("complete_profile_version") != complete.get("profile_version")
            or binding.get("complete_profile_fingerprint") != complete.get("fingerprint")
            or binding.get("complete_profile_sha256") != complete.get("sha256")
            or binding.get("visibility") != "public"
            or binding.get("rights_basis") != AUTHORITY_ID
            or not isinstance(scope, dict)
            or scope.get("visibility") != "public"
            or not isinstance(target, dict)
        ):
            raise PublicScopePolicyError("SUCCESSOR_SCOPE_BINDING_INVALID")
        try:
            policy = RetrievalScopeTargetPolicy.model_validate(target)
        except ValidationError as error:
            raise PublicScopePolicyError("SUCCESSOR_SCOPE_TARGET_INVALID") from error
        if (
            policy.roles != ["student"]
            or policy.audiences != ["libre"]
            or policy.candidates != ["libre"]
            or "libre" not in scope.get("audience", [])
            or any(target.get(key) != scope.get(key) for key in (
                "tenant", "niveau", "voie", "matiere", "statut_enseignement"
            ))
            or target.get("candidates") != [scope.get("candidat")]
            or scope.get("collection") != collection
        ):
            raise PublicScopePolicyError("SUCCESSOR_SCOPE_TARGET_INVALID")
    for placement in release.placements:
        if (
            placement.artifact_id not in {a.content_sha256 for a in release.artifacts}
            or placement.payload.get("visibility") != "public"
            or placement.payload.get("placement_status") != "active"
            or placement.payload.get("review_status") != "reviewed"
            or placement.payload.get("currentness") not in {"current", "official_snapshot"}
        ):
            raise PublicScopePolicyError("SUCCESSOR_SCOPE_PLACEMENT_INVALID")
    artifacts_path = release_dir / "profile_gate/artifacts.release.json"
    if _sha(artifacts_path.read_bytes()) != index.get("artifact_registry_sha256"):
        raise PublicScopePolicyError("SUCCESSOR_ARTIFACT_REGISTRY_DIVERGENT")
    artifacts = _json(artifacts_path.read_bytes(), "SUCCESSOR_ARTIFACT_REGISTRY_INVALID")
    if any(
        row.get("media_type") != "text/plain; charset=utf-8"
        or row.get("source_pdf_sha256") == row.get("content_sha256")
        for row in _rows(artifacts.get("artifacts"), "SUCCESSOR_ARTIFACT_REGISTRY_INVALID")
    ):
        raise PublicScopePolicyError("SUCCESSOR_SCOPE_PDF_NOT_PUBLIC")
    return 11


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
