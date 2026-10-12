"""Rejouer les autorités externes du successeur public juste avant signature.

Ce pont n'interprète pas lui-même les décisions : chaque preuve est transmise
à son vérificateur canonique. L'absence d'un vérificateur ou d'une cible live
refuse la signature.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import psycopg
from nexus_release_chain.public_successor_activation import (
    PublicSuccessorActivationVerdict,
    PublicSuccessorLiveVerificationRequest,
    VerifiedPublicSuccessorLiveEvidence,
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
    target_pin_receipt_path: Path
    target_pin_pull_request: int
    observed_v1_receipt_path: Path
    database_dsn: str = field(repr=False)
    temporal_authority_path: Path | None = None
    source_private_root: Path | None = None
    source_checkpoint_root: Path | None = None
    source_fresh_root: Path | None = None
    lot41a_material_root: Path | None = None
    lot42_review_pr: int | None = None
    lot42_reviewed_head: str | None = None
    lot42_historical_receipt_path: Path | None = None


@dataclass(frozen=True)
class PublicationSigningReplayVerdict:
    """Résultat typé du rejeu externe; le digest du pin ne vient jamais de C."""

    activation: PublicSuccessorActivationVerdict
    target_pin_sha256: str
    expires_at_utc: datetime
    verified_at_utc: datetime


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


def _replay_live_scope_review(
    repository_root: Path, bundle_root: Path, scope_sha256: str, subject_count: int,
) -> None:
    """Le C scellé choisit seulement une liaison PR explicitement reconnue."""
    receipt_path = bundle_root / "authorities/exact_head_scope_review_receipt_sha256.bin"
    try:
        receipt = json.loads(_bytes(receipt_path))
    except (UnicodeDecodeError, ValueError) as error:
        raise PublicationSigningReplayRefused("scope review receipt invalid") from error
    if not isinstance(receipt, dict):
        raise PublicationSigningReplayRefused("scope review receipt invalid")
    review = (receipt.get("kind"), receipt.get("pull_request"))
    if review not in {
        ("PR294_STUDENT_PUBLIC_SCOPE_REVIEW_RECEIPT_V1", 294),
        ("PR330_STUDENT_PUBLIC_SCOPE_REVIEW_RECEIPT_V1", 330),
    }:
        raise PublicationSigningReplayRefused("scope review PR/kind not governed")
    checker = _checkout_module("pr294_scope_review_receipt")
    args = (
        repository_root, receipt_path,
        bundle_root / "authorities/public_scope_authority_sha256.bin",
        bundle_root,
    )
    if review[1] == 294:
        observed = checker.check_pr294_scope_review_receipt(*args)
    else:
        observed = checker.check_scope_review_receipt(
            *args, review_binding=checker.REVIEW_BINDINGS[330],
        )
    expected_flag = f"PR{review[1]}_SCOPE_REVIEW_PASS"
    if (not isinstance(observed, dict)
            or observed.get(expected_flag) is not True
            or observed.get("PUBLICATION_AUTHORIZED") is not False
            or observed.get("PUBLIC_SCOPE_AUTHORITY_SHA256") != scope_sha256
            or observed.get("SCOPE_COUNT") != subject_count):
        raise PublicationSigningReplayRefused("live scope review differs from C")


def _verified_external_target_pin_sha256(
    *, repository_root: Path, target_pin_receipt_path: Path,
    target_pin_path: Path, target_pin_pull_request: int,
    content_anchor_sha256: str, target_root: Path, database_dsn: str,
    now_utc: datetime,
) -> tuple[str, datetime]:
    """Rejouer la review historique et la cible live avant de lire le pin.

    Le reçu est un pointeur : seul le vérificateur canonique produit le digest
    opposable. Le digest de C, de V2 et des options CLI n'est jamais accepté.
    """
    if (type(target_pin_pull_request) is not int or target_pin_pull_request <= 0
            or now_utc.tzinfo != UTC or not database_dsn):
        raise PublicationSigningReplayRefused("independent target pin inputs incomplete")
    try:
        relative = (target_pin_path.relative_to(repository_root)
                    if target_pin_path.is_absolute() else target_pin_path)
    except ValueError as error:
        raise PublicationSigningReplayRefused("target pin outside signer checkout") from error
    if (relative.is_absolute() or ".." in relative.parts
            or relative.parent != Path("governance/staging_target_pins")
            or relative.suffix != ".json"):
        raise PublicationSigningReplayRefused("target pin outside governed directory")
    pin_raw = _bytes(repository_root / relative)
    _bytes(target_pin_receipt_path)
    checker = _checkout_module("historical_staging_target_pin_receipt")
    try:
        observed = checker.check_historical_pin_receipt(
            repository_root, target_pin_receipt_path, relative,
            target_pin_pull_request, content_anchor_sha256, target_root,
            database_dsn,
        )
    except Exception as error:  # noqa: BLE001 - frontière de droits fail-closed
        raise PublicationSigningReplayRefused("historical target pin verification failed") from error
    if not isinstance(observed, dict):
        raise PublicationSigningReplayRefused("historical pin verdict malformed")
    digest = observed.get("EXPECTED_TARGET_PIN_SHA256")
    if (observed.get("HISTORICAL_STAGING_TARGET_PIN_PASS") is not True
            or observed.get("PUBLICATION_AUTHORIZED") is not False
            or observed.get("CONTENT_ANCHOR_SHA256") != content_anchor_sha256
            or observed.get("PR_NUMBER") != target_pin_pull_request
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or digest != _sha(pin_raw)):
        raise PublicationSigningReplayRefused("historical pin differs from exact bytes or A")
    try:
        expires = datetime.fromisoformat(json.loads(pin_raw)["expires_at_utc"])
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        raise PublicationSigningReplayRefused("target pin expiry absent") from error
    if expires.tzinfo != UTC or now_utc >= expires:
        raise PublicationSigningReplayRefused("target pin expired")
    return digest, expires


def recheck_publication_pin_before_key(
    inputs: PublicationSigningInputs, *, expected_content_anchor_sha256: str,
    expected_pin_sha256: str, evidence_expires_at_utc: datetime,
    now_utc: datetime,
) -> None:
    """Relire review, cible et expiration du pin immédiatement avant la clé."""
    digest, expiry = _verified_external_target_pin_sha256(
        repository_root=inputs.repository_root,
        target_pin_receipt_path=inputs.target_pin_receipt_path,
        target_pin_path=inputs.target_pin_path,
        target_pin_pull_request=inputs.target_pin_pull_request,
        content_anchor_sha256=expected_content_anchor_sha256,
        target_root=inputs.target_root,
        database_dsn=inputs.database_dsn,
        now_utc=now_utc,
    )
    if (digest != expected_pin_sha256
            or datetime.now(UTC) >= min(expiry, evidence_expires_at_utc)):
        raise PublicationSigningReplayRefused("target pin changed before key access")


def _replay_publication_preissuance(
    inputs: PublicationSigningInputs, anchor_sha: str,
    manifest_sha256: str, now_utc: datetime,
) -> datetime:
    """Rejouer le CAS A1 et l'autorité temporelle A2 sans prolonger A1."""
    if inputs.temporal_authority_path is None:
        raise PublicationSigningReplayRefused("A2 authority required for publication replay")
    preissuance = _checkout_module("check_public_successor_preissuance")
    try:
        a2_raw = _bytes(inputs.temporal_authority_path)
        receipt_sha = _sha(_bytes(inputs.preissuance_receipt_path))
        result = preissuance.verify_preissuance_authority(
            inputs.content_anchor_path, anchor_sha, manifest_sha256,
            inputs.preissuance_receipt_path, receipt_sha,
            inputs.repository_root, inputs.private_cas_root, now_utc,
            temporal_authority_raw=a2_raw,
        )
    except Exception as error:  # noqa: BLE001 - frontière de signature fail-closed
        raise PublicationSigningReplayRefused("A2/CAS publication replay failed") from error
    if (result.preissuance_verified is not True
            or result.publication_authorized is not False
            or result.content_anchor_sha256 != anchor_sha):
        raise PublicationSigningReplayRefused("A2/CAS publication replay incomplete")
    return result.expires_at_utc


def _replay_publication_source_pulse(
    inputs: PublicationSigningInputs, pulse_path: Path, expected_sha256: str,
) -> datetime:
    """Recomposer les 253 reçus privés C avant toute autorité de publication."""
    roots = (
        inputs.source_private_root, inputs.source_checkpoint_root,
        inputs.source_fresh_root,
    )
    if any(path is None or path.is_symlink() or not path.is_dir() for path in roots):
        raise PublicationSigningReplayRefused("source pulse private inputs absent")
    raw = _bytes(pulse_path)
    if _sha(raw) != expected_sha256:
        raise PublicationSigningReplayRefused("source pulse digest differs from C")
    try:
        report = json.loads(raw)
        attested_at = report["attested_at_utc"]
        module = _checkout_module("attest_student_derivative_source_currentness")
        replayed = module.attest_repository(
            inputs.repository_root, roots[0], roots[1], roots[2],
            attested_at_utc=attested_at,
        )
        if module._canonical(replayed) != raw:
            raise PublicationSigningReplayRefused("source pulse differs from private replay")
    except (TypeError, ValueError, KeyError, OSError) as error:
        raise PublicationSigningReplayRefused("source pulse private replay failed") from error
    return datetime.now(UTC)


def _reviewed_head_tree(repository_root: Path, head_sha: str) -> str:
    """Exiger que l'objet Git relu localement soit le HEAD exact approuvé."""
    result = subprocess.run(
        ["git", "-C", str(repository_root), "rev-parse", "--verify", f"{head_sha}^{{tree}}"],
        capture_output=True, text=True, check=False,
    )
    tree = result.stdout.strip()
    if result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", tree) is None:
        raise PublicationSigningReplayRefused("LOT42 reviewed Git tree unavailable")
    return tree


def _load_lot41a_release_files(
    inputs: PublicationSigningInputs, members: tuple[object, ...],
) -> dict[str, bytes]:
    """Relire les 22 pièces privées exactes sans suivre de lien symbolique."""
    from nexus_contracts.authority_artifacts import canonical_authorization_path  # noqa: PLC0415
    from nexus_contracts.authorization_set import canonical_review_binding_path  # noqa: PLC0415

    root = inputs.lot41a_material_root
    if root is None or root.is_symlink() or not root.is_dir():
        raise PublicationSigningReplayRefused("LOT41A private material root absent")
    files: dict[str, bytes] = {}
    for member in members:
        authorization_id = member.authorization_id  # type: ignore[attr-defined]
        for relative in (
            canonical_authorization_path(authorization_id),
            canonical_review_binding_path(authorization_id),
        ):
            path = root
            for component in Path(relative).parts:
                path /= component
                if path.is_symlink():
                    raise PublicationSigningReplayRefused("LOT41A private material symlink")
            if not path.is_file() or relative in files:
                raise PublicationSigningReplayRefused("LOT41A private material incomplete")
            files[relative] = path.read_bytes()
    return files


def _verified_live_lot42_review_binding(
    inputs: PublicationSigningInputs, review: object, expected_digest: str,
) -> tuple[str, str, str, int, str, str]:
    """Relire l'APPROVED exacte et le blob LOT42 pendant que la PR est OPEN."""
    from nexus_contracts.authority_artifacts import (  # noqa: PLC0415
        canonical_publication_review_path,
        git_blob_sha1,
    )

    from ingestor.ingestion_control.github_authority import (  # noqa: PLC0415
        GitHubAuthorityError,
        fetch_blob_at_ref,
        verify_review,
    )

    number = inputs.lot42_review_pr
    head = inputs.lot42_reviewed_head
    if (type(number) is not int or number <= 0
            or not isinstance(head, str) or re.fullmatch(r"[0-9a-f]{40}", head) is None):
        raise PublicationSigningReplayRefused("LOT42 exact PR/head absent")
    try:
        raw = review.canonical_bytes()  # type: ignore[attr-defined]
        digest = review.digest()  # type: ignore[attr-defined]
        if digest != expected_digest or _sha(raw) != expected_digest:
            raise PublicationSigningReplayRefused("LOT42 reviewed digest differs from C")
        path = canonical_publication_review_path(
            review_id=review.review_id, digest=digest,  # type: ignore[attr-defined]
        )
        live = verify_review(
            repository="cyranoaladin/RAG", pull_request=number,
            expected_head=head,
        )
        if (live.approved is not True or live.reason != "approved"
                or live.repository != "cyranoaladin/RAG"
                or live.pull_request != number or live.head_sha != head
                or live.base_ref != "main" or live.head_pinned_status != "success"
                or live.reviewer != "abenrhouma"
                or type(live.review_id) is not int or live.review_id <= 0
                or not isinstance(live.challenge, str)
                or re.fullmatch(r"NEXUS-TRUSTED-REVIEW-V1:[0-9a-f]{64}", live.challenge) is None):
            raise PublicationSigningReplayRefused("LOT42 exact live review absent")
        blob = fetch_blob_at_ref(repository=live.repository, path=path, ref=head)
        if blob.content != raw or blob.blob_sha != git_blob_sha1(raw):
            raise PublicationSigningReplayRefused("LOT42 approved blob differs from C")
        tree = _reviewed_head_tree(inputs.repository_root, head)
    except (GitHubAuthorityError, OSError, TypeError, ValueError) as error:
        raise PublicationSigningReplayRefused("LOT42 live review replay failed") from error
    return (live.base_sha, head, tree, live.review_id, live.challenge, live.reviewer)


def _verified_lot42_review_binding(
    inputs: PublicationSigningInputs, review: object, expected_digest: str,
) -> tuple[str, str, str, int, str, str]:
    """Choisir OPEN ou merged depuis GitHub, jamais depuis un flag opérateur."""
    number = inputs.lot42_review_pr
    head = inputs.lot42_reviewed_head
    raw = review.canonical_bytes()  # type: ignore[attr-defined]
    if (type(number) is not int or number <= 0
            or not isinstance(head, str) or re.fullmatch(r"[0-9a-f]{40}", head) is None
            or not isinstance(raw, bytes) or _sha(raw) != expected_digest
            or review.digest() != expected_digest):  # type: ignore[attr-defined]
        raise PublicationSigningReplayRefused("LOT42 exact PR/head/blob absent")
    pr = _checkout_module("pr300_authority_receipt")._read_gh(
        f"repos/cyranoaladin/RAG/pulls/{number}"
    )
    if not isinstance(pr, dict):
        raise PublicationSigningReplayRefused("LOT42 GitHub PR state unavailable")
    historical_path = inputs.lot42_historical_receipt_path
    if pr.get("state") == "open" and pr.get("merged") is False:
        if historical_path is not None:
            raise PublicationSigningReplayRefused("LOT42 OPEN PR cannot use historical receipt")
        return _verified_live_lot42_review_binding(inputs, review, expected_digest)
    if pr.get("state") != "closed" or pr.get("merged") is not True:
        raise PublicationSigningReplayRefused("LOT42 PR not merged or OPEN")
    if historical_path is None:
        raise PublicationSigningReplayRefused("LOT42 historical receipt absent")
    from nexus_contracts.authority_artifacts import (
        canonical_publication_review_path,  # noqa: PLC0415
    )

    path = canonical_publication_review_path(
        review_id=review.review_id, digest=expected_digest,  # type: ignore[attr-defined]
    )
    binding = _checkout_module("historical_lot42_review_receipt").check_historical_lot42_receipt(
        inputs.repository_root, historical_path, number, path, raw,
    )
    if (not isinstance(binding, tuple) or len(binding) != 6
            or binding[1] != head or binding[5] != "abenrhouma"):
        raise PublicationSigningReplayRefused("LOT42 historical binding differs from C")
    return binding


def _lot42_review_evaluator(review: object) -> str:
    """Extraire l'exécutant scellé ; la reconstitution valide toute la note."""
    note = review.provenance_note  # type: ignore[attr-defined]
    if not isinstance(note, str):
        raise PublicationSigningReplayRefused("LOT42 reviewed evaluator absent")
    match = re.search(
        r"Public successor evidence: A2_SHA256=[0-9a-f]{64}; "
        r"TRANSFER_SHA256=[0-9a-f]{64}; TARGET_PIN_SHA256=[0-9a-f]{64}; "
        r"TRANSFER_V2_SHA256=[0-9a-f]{64}; PROJECTION_SHA256=[0-9a-f]{64}; "
        r"EVALUATOR=([^\s;]{1,128})\.$",
        note,
    )
    if match is None:
        raise PublicationSigningReplayRefused("LOT42 reviewed evaluator absent")
    return match.group(1)


def _require_c_reviewed_batch(
    check: Callable[..., None], review: object, *, facts: object,
    source: Any, target: Any, approved_pin_sha256: str,
    projection_digest: str, evaluator: str, now_utc: datetime,
) -> None:
    """Recouper le reçu LOT42 avec le pin et le transfert V2 observés."""
    check(
        review, facts=facts,
        a2_sha256=source.a2_sha256, a2_valid_until=source.a2_valid_until,
        transfer_sha256=target.plan_sha256,
        target_pin_sha256=approved_pin_sha256,
        transfer_v2_sha256=target.attestation_sha256,
        projection_digest=projection_digest,
        evaluator=evaluator, now_utc=now_utc,
    )


def _verify_live_publication(
    inputs: PublicationSigningInputs,
    request: PublicSuccessorLiveVerificationRequest,
    *, approved_pin_sha256: str,
    pin_expires_at_utc: datetime,
) -> VerifiedPublicSuccessorLiveEvidence:
    """Rejouer les pièces privées, GitHub et la DB avant de fournir C."""
    from nexus_contracts.review_binding import parse_trust_anchor  # noqa: PLC0415
    from nexus_release_chain.public_lot41a_adapter import (  # noqa: PLC0415
        verify_public_lot41a_set,
    )
    from nexus_release_chain.public_successor_activation import (  # noqa: PLC0415
        derive_worker_transfer_manifest_sha256,
    )

    from ingestor.ingestion_control.github_authority import (  # noqa: PLC0415
        load_trusted_reviewers,
    )
    from ingestor.ingestion_control.public_successor_batch_proposal import (  # noqa: PLC0415
        build_public_successor_batch_projections,
        load_public_successor_batch_source,
        require_reviewed_public_successor_batch,
    )
    from ingestor.ingestion_control.release_batch_attestation import (  # noqa: PLC0415
        measure_release_batch_facts,
        require_public_successor_batch_matches_release,
    )
    from ingestor.ingestion_control.scope_authority import (  # noqa: PLC0415
        verify_scope_authorization,
    )
    from ingestor.public_successor_db_guard import (  # noqa: PLC0415
        require_public_successor_live_controls,
        require_public_successor_startup_lot42,
    )

    root = request.bundle_root
    content = request.content
    authorities = request.authorities
    if request.target_pin_sha256 != approved_pin_sha256 or (
        request.pin_expires_at_utc != pin_expires_at_utc
    ):
        raise PublicationSigningReplayRefused("C target pin differs from live target")
    digests = {
        field: _sha(_bytes(root / "authorities" / f"{field}.bin"))
        for field in authorities
    }
    if digests != dict(authorities):
        raise PublicationSigningReplayRefused("C authority bytes differ during live replay")
    _replay_live_scope_review(
        inputs.repository_root, root,
        authorities["public_scope_authority_sha256"],
        content.expected_counts["subjects"],
    )
    preissuance_expiry = _replay_publication_preissuance(
        inputs, content.content_anchor_sha256, content.content_manifest_sha256,
        datetime.now(UTC),
    )
    pulse_at = _replay_publication_source_pulse(
        inputs, root / "authorities/temporal_c_attestation_sha256.bin",
        authorities["temporal_c_attestation_sha256"],
    )
    files = _load_lot41a_release_files(
        inputs, tuple(request.authorization_set.members),
    )
    authorization_set, verified_set = verify_public_lot41a_set(
        anchor_path=root / "content-anchor.json",
        anchor_sha256=content.content_anchor_sha256,
        release_root=root / "release",
        authorization_ids=tuple(
            member.authorization_id for member in request.authorization_set.members
        ),
        release_files=files,
        trust_anchor=parse_trust_anchor(_bytes(
            inputs.repository_root / "governance/trust-anchors/review-binding-v1.json"
        )),
        environment="production", now_utc=datetime.now(UTC),
        accepted_reviewers=load_trusted_reviewers(),
        revocation_registry_raw=_bytes(
            inputs.repository_root / "governance/trust-anchors/authorization-revocations-v1.json"
        ),
        temporal_authority_raw=_bytes(
            root / "authorities/temporal_a2_authority_sha256.bin"
        ),
    )
    if authorization_set.canonical_bytes() != request.authorization_set.canonical_bytes():
        raise PublicationSigningReplayRefused("live LOT41A set differs from C")

    qualified = _checkout_module("qualified_public_text_transfer")
    plan_raw = _bytes(root / "authorities/artifact_transfer_manifest_sha256.bin")
    transfer_raw = _bytes(root / "authorities/observed_transfer_receipt_sha256.bin")
    plan_doc = json.loads(plan_raw)
    pin_raw = _bytes(
        inputs.target_pin_path if inputs.target_pin_path.is_absolute()
        else inputs.repository_root / inputs.target_pin_path
    )
    target = qualified.verify_qualified_transfer_target(
        attestation_raw=transfer_raw,
        expected_attestation_sha256=authorities["observed_transfer_receipt_sha256"],
        plan_raw=plan_raw,
        receipt_v1_raw=_bytes(inputs.observed_v1_receipt_path),
        target_pin_raw=pin_raw,
        expected_target_pin_sha256=approved_pin_sha256,
        expected_content_anchor_sha256=content.content_anchor_sha256,
        candidate_inventory_raw=_bytes(
            root / "release/profile_gate/candidate_inventory.json"
        ),
        expected_candidate_inventory_sha256=content.candidate_inventory_sha256,
        allowlist_raw=_bytes(
            root / "release/profile_gate/private_transfer_allowlist.json"
        ),
        expected_allowlist_sha256=plan_doc["allowlist_sha256"],
        expected_release_id=content.release_id,
        destination_root=inputs.target_root,
        database_dsn=inputs.database_dsn,
    )
    if (target.attestation_sha256 != authorities["observed_transfer_receipt_sha256"]
            or target.plan_sha256 != authorities["artifact_transfer_manifest_sha256"]
            or target.content_anchor_sha256 != content.content_anchor_sha256
            or target.release_id != content.release_id):
        raise PublicationSigningReplayRefused("qualified target differs from C")
    worker_transfer_sha = derive_worker_transfer_manifest_sha256(
        plan_raw, _bytes(inputs.observed_v1_receipt_path),
    )
    binding = _verified_lot42_review_binding(
        inputs, request.publication_batch_review,
        authorities["publication_batch_review_receipt_sha256"],
    )
    evaluator = _lot42_review_evaluator(request.publication_batch_review)
    source = load_public_successor_batch_source(
        release_root=root / "release", anchor_path=root / "content-anchor.json",
        anchor_sha256=content.content_anchor_sha256,
        a2_path=root / "authorities/temporal_a2_authority_sha256.bin",
        transfer_manifest_sha256=worker_transfer_sha,
        now_utc=datetime.now(UTC),
    )
    if source.a2_sha256 != authorities["temporal_a2_authority_sha256"]:
        raise PublicationSigningReplayRefused("LOT42 A2 source differs from C")
    expected_reviews = tuple(sorted((
        str(member.scope.collection), member.authorization_id,
        member.authorization_digest, member.review_binding_digest,
    ) for member in request.authorization_set.members))
    expected = PublicSuccessorActivationVerdict(
        release_id=content.release_id,
        content_anchor_sha256=content.content_anchor_sha256,
        content_manifest_sha256=content.content_manifest_sha256,
        authority_envelope_sha256=request.authority_envelope_sha256,
        artifact_registry_sha256=content.artifact_registry_sha256,
        release_registry_sha256=content.release_registry_sha256,
        scope_authority_sha256=authorities["public_scope_authority_sha256"],
        subject_sha256_by_collection=content.subject_sha256_by_collection,
        scope_sha256_by_id=dict(request.scope_sha256_by_id),
        counts=content.expected_counts,
        expires_at_utc=min(
            request.a2_expires_at_utc, pin_expires_at_utc,
            verified_set.authorizations_effective_valid_until,
            verified_set.earliest_review_binding_expires_at,
            request.publication_batch_review.valid_until,
            target.expires_at_utc, preissuance_expiry,
        ),
        authorization_review_evidence_by_id=expected_reviews,
        transfer_manifest_sha256=target.plan_sha256,
        publication_batch_review_id=request.publication_batch_review.review_id,
        publication_batch_review_digest=(
            authorities["publication_batch_review_receipt_sha256"]
        ),
        publication_batch_review_binding=binding,
    )
    observed_auth_ids: list[str] = []
    auth_by_collection = {
        str(member.scope.collection): member.authorization_id
        for member in request.authorization_set.members
    }
    with psycopg.connect(
        inputs.database_dsn, options="-c default_transaction_read_only=on",
    ) as conn:
        for member in request.authorization_set.members:
            observed = verify_scope_authorization(
                conn, authorization_id=member.authorization_id, scope=member.scope,
            )
            if (observed.authorization_digest != member.authorization_digest
                    or observed.valid_until != verified_set.authorizations_effective_valid_until
                    or observed.authorization_id != member.authorization_id):
                raise PublicationSigningReplayRefused("live LOT41A DB row differs from C")
            observed_auth_ids.append(observed.authorization_id)
        facts = measure_release_batch_facts(conn, release_id=content.release_id)
        require_public_successor_batch_matches_release(
            facts, source.release, auth_by_collection,
        )
        _projections, projection_digest = build_public_successor_batch_projections(
            source, facts, evaluator=evaluator, now_utc=datetime.now(UTC),
        )
        _require_c_reviewed_batch(
            require_reviewed_public_successor_batch,
            request.publication_batch_review, facts=facts, source=source,
            target=target, approved_pin_sha256=approved_pin_sha256,
            projection_digest=projection_digest,
            evaluator=evaluator, now_utc=datetime.now(UTC),
        )
        require_public_successor_live_controls(conn, expected)
        revocations_at = datetime.now(UTC)
        lot42_count = require_public_successor_startup_lot42(conn, expected, root)
        conn.rollback()
    checked_at = datetime.now(UTC)
    if checked_at >= expected.expires_at_utc:
        raise PublicationSigningReplayRefused("public authority expired during live replay")
    return VerifiedPublicSuccessorLiveEvidence(
        authority_sha256_by_field=digests,
        content_anchor_sha256=content.content_anchor_sha256,
        authority_envelope_sha256=request.authority_envelope_sha256,
        target_pin_sha256=approved_pin_sha256,
        release_id=content.release_id,
        content_manifest_sha256=content.content_manifest_sha256,
        counts=content.expected_counts,
        scope_sha256_by_id=dict(request.scope_sha256_by_id),
        verified_authorization_set=verified_set,
        authorization_review_evidence_by_id=expected_reviews,
        publication_batch_review_id=request.publication_batch_review.review_id,
        publication_batch_review_digest=(
            authorities["publication_batch_review_receipt_sha256"]
        ),
        publication_batch_review_binding=binding,
        verified_at_utc=checked_at,
        revocations_checked_at_utc=revocations_at,
        source_pulse_replayed_at_utc=pulse_at,
        active_authorization_ids=tuple(observed_auth_ids),
        lot42_attestation_count=lot42_count,
        revoked_authorization_ids=(), revoked_review_ids=(),
        target_pin_expires_at_utc=pin_expires_at_utc,
        expires_at_utc=expected.expires_at_utc,
    )


def replay_public_successor_publication(
    inputs: PublicationSigningInputs, *, expected_release_id: str,
    expected_manifest_sha256: str, now_utc: datetime,
) -> PublicationSigningReplayVerdict:
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
    approved_pin_sha, pin_expires_at = _verified_external_target_pin_sha256(
        repository_root=inputs.repository_root,
        target_pin_receipt_path=inputs.target_pin_receipt_path,
        target_pin_path=inputs.target_pin_path,
        target_pin_pull_request=inputs.target_pin_pull_request,
        content_anchor_sha256=anchor_sha,
        target_root=inputs.target_root,
        database_dsn=inputs.database_dsn,
        now_utc=now_utc,
    )
    verdict = verify_public_successor_activation(
        root,
        expected_content_anchor_sha256=anchor_sha,
        expected_authority_envelope_sha256=envelope_sha,
        expected_release_id=expected_release_id,
        expected_registry_sha256=content.release_registry_sha256,
        expected_scope_authority_sha256=scope_sha,
        expected_target_pin_sha256=approved_pin_sha,
        now_utc=now_utc,
        live_verifier=lambda request: _verify_live_publication(
            inputs, request, approved_pin_sha256=approved_pin_sha,
            pin_expires_at_utc=pin_expires_at,
        ),
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

    _replay_live_scope_review(
        inputs.repository_root, root, scope_sha, verdict.counts["subjects"],
    )

    preissuance_expiry = _replay_publication_preissuance(
        inputs, anchor_sha, expected_manifest_sha256, datetime.now(UTC),
    )

    qualified = _checkout_module("qualified_public_text_transfer")
    attestation_path = root / "authorities/observed_transfer_receipt_sha256.bin"
    plan_path = root / "authorities/artifact_transfer_manifest_sha256.bin"
    attestation_raw = _bytes(attestation_path)
    plan_raw = _bytes(plan_path)
    pin_raw = _bytes(
        inputs.target_pin_path if inputs.target_pin_path.is_absolute()
        else inputs.repository_root / inputs.target_pin_path
    )
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

    from nexus_release_chain.public_successor_activation import (  # noqa: PLC0415
        derive_worker_transfer_manifest_sha256,
    )

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
        authority_envelope_path=root / "authority-envelope.json",
        temporal_authority_path=root / "authorities/temporal_a2_authority_sha256.bin",
    )
    with psycopg.connect(
        inputs.database_dsn, options="-c default_transaction_read_only=on",
    ) as conn:
        require_public_lot42_db(
            conn, activation=verdict, authorities=runtime,
            transfer_sha256=derive_worker_transfer_manifest_sha256(
                plan_raw, _bytes(inputs.observed_v1_receipt_path),
            ),
        )
    if datetime.now(UTC) >= min(
        verdict.expires_at_utc, target_verdict.expires_at_utc,
        preissuance_expiry, pin_expires_at,
    ):
        raise PublicationSigningReplayRefused("public authority expired during replay")
    return PublicationSigningReplayVerdict(
        activation=verdict,
        target_pin_sha256=approved_pin_sha,
        expires_at_utc=min(
            verdict.expires_at_utc, target_verdict.expires_at_utc,
            preissuance_expiry, pin_expires_at,
        ),
        verified_at_utc=datetime.now(UTC),
    )
