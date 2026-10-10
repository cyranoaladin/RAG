"""Contrôles DB vivants de la release publique, depuis le pool retrieval existant.

Les attentes proviennent du verdict C authentifié hors DB. Ce module ne
transforme jamais une ligne de contrôle en autorité de publication.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nexus_contracts.authority_artifacts import canonical_publication_review_path
from nexus_release_chain.public_successor_activation import (
    PublicSuccessorActivationVerdict,
    verify_content_anchor,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_AUTH_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")


class PublicSuccessorDBRefused(RuntimeError):
    """LOT41A, LOT42 ou les révocations vivantes ne sont pas conformes à C."""


def _expected_authorizations(
    verdict: PublicSuccessorActivationVerdict,
) -> tuple[tuple[str, str, str, str], ...]:
    entries = verdict.authorization_review_evidence_by_id
    if (
        not isinstance(entries, tuple)
        or len(entries) != verdict.counts["subjects"]
        or any(
            not isinstance(entry, tuple)
            or len(entry) != 4
            or not isinstance(entry[0], str) or not entry[0]
            or not isinstance(entry[1], str) or _AUTH_ID.fullmatch(entry[1]) is None
            or any(not isinstance(value, str) or _SHA256.fullmatch(value) is None
                   for value in entry[2:])
            for entry in entries
        )
        or len({entry[0] for entry in entries}) != len(entries)
        or len({entry[1] for entry in entries}) != len(entries)
    ):
        raise PublicSuccessorDBRefused("C lacks exact LOT41A sealed review expectations")
    return entries


def _json_under_digest(path: Path, expected_sha256: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or _SHA256.fullmatch(expected_sha256) is None:
        raise PublicSuccessorDBRefused("A file unavailable or unsafe")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise PublicSuccessorDBRefused("A file digest differs")
    try:
        result = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicSuccessorDBRefused("A file JSON invalid") from error
    if not isinstance(result, dict):
        raise PublicSuccessorDBRefused("A file object invalid")
    return result


def _expected_lot42_population(
    verdict: PublicSuccessorActivationVerdict, bundle_root: Path,
) -> tuple[dict[tuple[str, str, str], tuple[str, str, str, str, int]], str]:
    """Dériver collection/contenu/placement de A, jamais des lignes DB."""
    content = verify_content_anchor(
        bundle_root / "content-anchor.json", verdict.content_anchor_sha256,
        bundle_root / "release",
    )
    if (
        content.release_id != verdict.release_id
        or content.content_manifest_sha256 != verdict.content_manifest_sha256
        or content.artifact_registry_sha256 != verdict.artifact_registry_sha256
        or content.expected_counts != verdict.counts
    ):
        raise PublicSuccessorDBRefused("C differs from A at LOT42 startup")
    gate = bundle_root / "release/profile_gate"
    artifacts = _json_under_digest(
        gate / "artifacts.release.json", content.artifact_registry_sha256,
    ).get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != verdict.counts["unique_artifacts"]:
        raise PublicSuccessorDBRefused("A artifact population invalid")
    by_content = {row["content_sha256"]: row for row in artifacts}
    if len(by_content) != len(artifacts):
        raise PublicSuccessorDBRefused("A artifact duplicate")
    expected: dict[tuple[str, str, str], tuple[str, str, str, str, int]] = {}
    for collection, sha in content.subject_sha256_by_collection.items():
        subject = _json_under_digest(gate / f"subjects/{collection}.release.json", sha)
        profile = subject.get("profile")
        for placement in subject.get("placements", []):
            content_sha = placement["artifact_id"]
            artifact = by_content.get(content_sha)
            if artifact is None or not isinstance(profile, dict):
                raise PublicSuccessorDBRefused("A placement artifact or profile absent")
            key = (collection, content_sha, placement["source_placement_id"])
            if key in expected:
                raise PublicSuccessorDBRefused("A placement duplicate")
            # LOT42-RELEASE-BATCH-V1 stocke ici le SHA du registre d'artefacts
            # du lot (attest_publication_cli), pas le fingerprint du profil
            # unitaire. Les profils A sont vérifiés séparément par C/LOT41A.
            expected[key] = (
                placement["placement_id"], placement["currentness"],
                content.artifact_registry_sha256, artifact["source_url"],
                len(artifact["chunks"]),
            )
    if len(expected) != verdict.counts["placements"] or len(by_content) != len({key[1] for key in expected}):
        raise PublicSuccessorDBRefused("A LOT42 population differs")
    if sum(len(row["chunks"]) for row in artifacts) != verdict.counts["unique_chunks"]:
        raise PublicSuccessorDBRefused("A chunk population differs")
    return expected, content.candidate_inventory_sha256


def require_public_successor_startup_lot42(
    conn: Any,
    verdict: PublicSuccessorActivationVerdict,
    bundle_root: Path,
) -> None:
    """Mesurer les 377 lignes et attestations LOT42 avant le premier trafic."""
    if datetime.now(UTC) >= verdict.expires_at_utc:
        raise PublicSuccessorDBRefused("C expired before LOT42 startup replay")
    authorities = _expected_authorizations(verdict)
    auth_by_collection = {collection: auth_id for collection, auth_id, _, _ in authorities}
    transfer_sha = verdict.transfer_manifest_sha256
    review_id = verdict.publication_batch_review_id
    review_digest = verdict.publication_batch_review_digest
    review_binding = verdict.publication_batch_review_binding
    if (
        not isinstance(transfer_sha, str) or _SHA256.fullmatch(transfer_sha) is None
        or not isinstance(review_id, str) or _AUTH_ID.fullmatch(review_id) is None
        or not isinstance(review_digest, str) or _SHA256.fullmatch(review_digest) is None
        or not isinstance(review_binding, tuple) or len(review_binding) != 5
        or any(not isinstance(value, str) or _SHA1.fullmatch(value) is None
               for value in review_binding[:3])
        or type(review_binding[3]) is not int or review_binding[3] <= 0
        or not isinstance(review_binding[4], str) or not review_binding[4]
    ):
        raise PublicSuccessorDBRefused("C lacks exact LOT42 signed review expectations")
    expected, inventory_sha = _expected_lot42_population(verdict, bundle_root)
    if set(auth_by_collection) != {key[0] for key in expected}:
        raise PublicSuccessorDBRefused("LOT42 collections differ from C LOT41A")
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT r.resource_id, a.artifact_id, r.collection, a.sha256, a.payload "
                "FROM ingestion_control.resources r "
                "JOIN ingestion_control.artifacts a USING (resource_id) "
                "WHERE r.pipeline_kind = %s AND a.payload->>'release_id' = %s",
                ("sealed_release_pipeline", verdict.release_id),
            )
            rows = cursor.fetchall()
            cursor.execute(
                "SELECT resource_id, artifact_id, content_sha256, collection, "
                "scope_authorization_id, protocol_version, release_manifest_sha256, "
                "artifacts_release_sha256, candidate_inventory_sha256, "
                "artifact_transfer_manifest_sha256, release_batch_review_digest, "
                "review_id, review_artifact_path, review_artifact_blob_sha, "
                "profile_fingerprint, rights_status, rights_assessed_at, "
                "quality_passed, quality_report_digest, quality_assessed_at, "
                "gate_passed, gate_evaluated_at, evidence_event_ids, "
                "human_review_repository, human_review_base_sha, "
                "human_review_head_sha, human_review_review_id, "
                "human_review_reviewer, human_review_challenge, "
                "invalidated_at, attestation_id, attestation_digest "
                "FROM ingestion_control.publication_attestations WHERE release_id = %s",
                (verdict.release_id,),
            )
            attestations = cursor.fetchall()
            cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM ingestion_control.sealed_release_adoptions "
                "WHERE release_id = %s)", (verdict.release_id,),
            )
            adopted = cursor.fetchone()
    except Exception as error:
        raise PublicSuccessorDBRefused("full LOT42 control database unavailable") from error
    if adopted != (False,) or len(rows) != len(expected) or len(attestations) != len(expected):
        raise PublicSuccessorDBRefused("LOT42 row population incomplete or adopted")
    observed: dict[tuple[str, str, str], tuple[Any, Any, str]] = {}
    for resource_id, artifact_id, collection, content_sha, payload in rows:
        if (
            not isinstance(payload, dict)
            or not isinstance(collection, str)
            or not isinstance(content_sha, str)
            or not isinstance(payload.get("source_placement_id"), str)
            or collection not in auth_by_collection
        ):
            raise PublicSuccessorDBRefused("LOT42 payload invalid")
        key = (collection, content_sha, payload["source_placement_id"])
        facts = expected.get(key)
        if key in observed or facts is None or any((
            payload.get("release_manifest_sha256") != verdict.content_manifest_sha256,
            payload.get("artifacts_release_sha256") != verdict.artifact_registry_sha256,
            payload.get("candidate_inventory_sha256") != inventory_sha,
            payload.get("artifact_transfer_manifest_sha256") != transfer_sha,
            payload.get("placement_id") != facts[0],
            payload.get("currentness") != facts[1],
            payload.get("provenance_artifact_url") != facts[3],
            payload.get("chunk_count") != facts[4],
            payload.get("scope_authorization_id") != auth_by_collection[collection],
            payload.get("review_status") != "reviewed",
            payload.get("placement_status") != "active",
            payload.get("media_type") != "text/plain; charset=utf-8",
        )):
            raise PublicSuccessorDBRefused("LOT42 sealed row differs from A/C")
        observed[key] = (resource_id, artifact_id, facts[2])
    seen: set[tuple[str, str, str]] = set()
    now = datetime.now(UTC)
    for row in attestations:
        (resource_id, artifact_id, content_sha, collection, auth_id, protocol,
         manifest, artifacts_sha, inventory, transfer, batch_digest, batch_id,
         review_path, review_blob, fingerprint, rights, rights_at,
         quality, quality_digest, quality_at, gate, gate_at, event_ids,
         review_repo, review_base, review_head, github_review_id,
         reviewer, challenge, invalidated, attestation_id, attestation_digest) = row
        keys = [key for key, ids in observed.items() if ids[:2] == (resource_id, artifact_id)]
        if len(keys) != 1 or collection not in auth_by_collection:
            raise PublicSuccessorDBRefused("LOT42 attestation resource differs")
        key = keys[0]
        if key in seen or any((
            content_sha != key[1], collection != key[0],
            auth_id != auth_by_collection[collection],
            protocol != "LOT42-RELEASE-BATCH-V1",
            manifest != verdict.content_manifest_sha256,
            artifacts_sha != verdict.artifact_registry_sha256,
            inventory != inventory_sha, transfer != transfer_sha,
            batch_digest != review_digest, batch_id != review_id,
            review_path != canonical_publication_review_path(
                review_id=review_id, digest=review_digest,
            ),
            review_blob != review_binding[2],
            fingerprint != observed[key][2], rights != "public_allowed",
            not isinstance(rights_at, datetime) or rights_at > now,
            quality is not True,
            not isinstance(quality_digest, str) or _SHA256.fullmatch(quality_digest) is None,
            not isinstance(quality_at, datetime) or quality_at > now,
            gate is not True, not isinstance(gate_at, datetime) or gate_at > now,
            not isinstance(event_ids, list | tuple) or not event_ids,
            review_repo != "cyranoaladin/RAG",
            review_base != review_binding[0], review_head != review_binding[1],
            github_review_id != review_binding[3], reviewer != "abenrhouma",
            challenge != review_binding[4],
            invalidated is not None, attestation_id is None,
            attestation_digest != review_digest,
        )):
            raise PublicSuccessorDBRefused("LOT42 attestation differs from A/C")
        seen.add(key)
    if seen != set(expected):
        raise PublicSuccessorDBRefused("LOT42 attestation coverage incomplete")
    if datetime.now(UTC) >= verdict.expires_at_utc:
        raise PublicSuccessorDBRefused("C expired during LOT42 startup replay")


def require_public_successor_live_controls(
    conn: Any,
    verdict: PublicSuccessorActivationVerdict,
) -> None:
    """Rechercher 11 autorisations/révocations et toute invalidation LOT42.

    Appelé à chaque requête avec la connexion déjà acquise par l'API. Le
    mesurage complet des 377 placements appartient au démarrage.
    """
    expected = _expected_authorizations(verdict)
    expected_by_id = {row[1]: row[2:] for row in expected}
    now = datetime.now(UTC)
    if now >= verdict.expires_at_utc:
        raise PublicSuccessorDBRefused("C expired")
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT authorization_id, authorization_digest, review_evidence_digest, "
                "revoked_at, valid_from, valid_until "
                "FROM ingestion_control.scope_authorizations "
                "WHERE authorization_id = ANY(%s)",
                (list(expected_by_id),),
            )
            rows = cursor.fetchall()
            if len(rows) != len(expected_by_id) or any(
                len(row) != 6
                or expected_by_id.get(row[0]) != (row[1], row[2])
                or row[3] is not None
                or not (row[4] <= now < row[5])
                for row in rows
            ):
                raise PublicSuccessorDBRefused("live LOT41A rows differ from C")
            cursor.execute(
                "SELECT review_evidence_digest "
                "FROM ingestion_control.revoked_review_evidence "
                "WHERE review_evidence_digest = ANY(%s)",
                ([row[3] for row in expected],),
            )
            if cursor.fetchall():
                raise PublicSuccessorDBRefused("sealed LOT41A review evidence revoked")
            cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM ingestion_control.publication_attestations "
                "WHERE release_id = %s AND release_manifest_sha256 = %s "
                "AND invalidated_at IS NOT NULL)",
                (verdict.release_id, verdict.content_manifest_sha256),
            )
            row = cursor.fetchone()
            if row != (False,):
                raise PublicSuccessorDBRefused("live LOT42 invalidation or result unavailable")
    except PublicSuccessorDBRefused:
        raise
    except Exception as error:
        raise PublicSuccessorDBRefused("live public control database unavailable") from error
    if datetime.now(UTC) >= verdict.expires_at_utc:
        raise PublicSuccessorDBRefused("C expired during live control replay")
