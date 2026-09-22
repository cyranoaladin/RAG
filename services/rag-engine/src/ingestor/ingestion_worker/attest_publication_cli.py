"""Outil opérateur LOT42 — chaîne d'attestations de publication (ADR-0033).

Remédiation GATE H1 (items **E**, **F**, **K**).

**Ce que cet outil ne fait plus.** Il n'accepte plus ``--content-sha256``,
``--rights-status``, ``--quality-passed``, ``--quality-score``,
``--gate-passed``, ``--gate-name``, ni aucune des dates associées. Ces
valeurs existent déjà dans le système : les accepter en argument libre
permettait d'attester une publication conforme pour une ressource dont le
gate avait échoué. Elles sont désormais **lues** depuis les faits durables
du pipeline (``publication_evidence.collect_publication_facts``).

Deux sous-commandes, une par étape du protocole :

``propose-review``
    Lit les faits durables, refuse immédiatement toute chaîne négative
    (item F), et écrit sur la sortie standard l'artefact de revue
    canonique **et** le chemin Git où le commiter. C'est ce fichier, et
    lui seul, que l'humain relit dans la PR de revue de publication.

``record-attestation``
    Après approbation : revérifie la review en direct, relit l'artefact
    depuis le blob Git approuvé, **recompare champ par champ à la base**,
    et n'écrit qu'ensuite. Une divergence DB ↔ artefact est un refus.

**Rôle PostgreSQL (item K).** Les deux sous-commandes se connectent via
``PG_INGESTION_CONTROL_ATTESTOR_DSN``, et **uniquement** lui — jamais le
DSN applicatif du worker. Le rôle attestor détient SELECT sur les tables
du pipeline et sur ``workflow_events``, INSERT sur
``publication_attestations``, et rien d'autre : ce conteneur ne porte
donc qu'un seul secret, jamais deux.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from uuid import UUID

import psycopg

try:
    from ingestor.ingestion_control.artifact_attribution import (
        ArtifactAttributionError,
        load_artifact_attribution,
    )
    from ingestor.ingestion_control.db import get_attestor_dsn
    from ingestor.ingestion_control.github_authority import (
        GitHubAuthorityError,
        ReviewVerification,
        fetch_blob_at_ref,
        verify_review,
    )
    from ingestor.ingestion_control.publication_evidence import (
        PublicationEvidenceMissingError,
        PublicationFacts,
        collect_publication_facts,
    )
    from ingestor.ingestion_control.scope_authority import (
        ScopeAuthorizationDeniedError,
        VerifiedAuthorization,
        authorization_allows_rights,
        verify_scope_authorization,
    )
except (ImportError, ValueError):
    # Image Docker aplatie (LOT44f, ADR-0029/ADR-0031) : "ingestor" n'existe
    # pas comme paquet ici — même discipline que create_job_cli.py.
    from ingestion_control.artifact_attribution import (
        ArtifactAttributionError,
        load_artifact_attribution,
    )
    from ingestion_control.db import get_attestor_dsn
    from ingestion_control.github_authority import (
        GitHubAuthorityError,
        ReviewVerification,
        fetch_blob_at_ref,
        verify_review,
    )
    from ingestion_control.publication_evidence import (
        PublicationEvidenceMissingError,
        PublicationFacts,
        collect_publication_facts,
    )
    from ingestion_control.scope_authority import (
        ScopeAuthorizationDeniedError,
        VerifiedAuthorization,
        authorization_allows_rights,
        verify_scope_authorization,
    )

from nexus_contracts.authority_artifacts import (
    LOT42_V2_PROTOCOL_VERSION,
    CanonicalArtifactError,
    PublicationReviewArtifactV2,
    canonical_publication_review_path,
    parse_publication_review_artifact,
    require_publication_review_v2,
)
from nexus_contracts.document import Rights

#: INSERT d'attestation portant AUSSI l'identite de release (migration 016).
#: Les colonnes batch sont NULL pour les protocoles unitaires : le schema
#: l'exige, et c'est ce qui empeche une identite de release fabriquee sur un
#: chemin qui n'en a pas.
_INSERT_ATTESTATION = """
    INSERT INTO ingestion_control.publication_attestations (
        resource_id, artifact_id, content_sha256, canonical_url, collection,
        scope_authorization_id, profile_id, profile_version, profile_fingerprint,
        manifest_digest,
        rights_status, rights_assessed_at,
        quality_passed, quality_report_digest, quality_assessed_at,
        gate_passed, gate_name, gate_evaluated_at,
        evidence_event_ids,
        review_id, review_artifact_path, review_artifact_blob_sha, attestation_digest,
        human_review_repository, human_review_pull_request, human_review_base_sha,
        human_review_head_sha, human_review_review_id, human_review_reviewer,
        human_review_submitted_at, human_review_challenge,
        protocol_version, attributed_facts_digest,
        release_id, release_manifest_sha256, artifacts_release_sha256,
        candidate_inventory_sha256, artifact_transfer_manifest_sha256,
        release_batch_review_digest
    ) VALUES (
        %(resource_id)s, %(artifact_id)s, %(content_sha256)s, %(canonical_url)s,
        %(collection)s,
        %(scope_authorization_id)s, %(profile_id)s, %(profile_version)s,
        %(profile_fingerprint)s,
        %(manifest_digest)s,
        %(rights_status)s, %(rights_assessed_at)s,
        %(quality_passed)s, %(quality_report_digest)s, %(quality_assessed_at)s,
        %(gate_passed)s, %(gate_name)s, %(gate_evaluated_at)s,
        %(evidence_event_ids)s,
        %(review_id)s, %(review_artifact_path)s, %(review_artifact_blob_sha)s,
        %(attestation_digest)s,
        %(human_review_repository)s, %(human_review_pull_request)s,
        %(human_review_base_sha)s,
        %(human_review_head_sha)s, %(human_review_review_id)s,
        %(human_review_reviewer)s,
        %(human_review_submitted_at)s, %(human_review_challenge)s,
        %(protocol_version)s, %(attributed_facts_digest)s,
        %(release_id)s, %(release_manifest_sha256)s, %(artifacts_release_sha256)s,
        %(candidate_inventory_sha256)s, %(artifact_transfer_manifest_sha256)s,
        %(release_batch_review_digest)s
    )
"""


def _non_blank(raw: str) -> str:
    if not raw.strip():
        raise argparse.ArgumentTypeError("must not be blank")
    return raw


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prépare puis enregistre une chaîne d'attestations de publication "
            "LOT42 à partir des faits durables du pipeline et d'une PR de "
            "revue approuvée. Outil opérateur uniquement : jamais un endpoint "
            "réseau."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    propose = subparsers.add_parser(
        "propose-review",
        help=(
            "Produit l'artefact de revue canonique depuis les faits durables. "
            "Lecture seule — n'écrit jamais en base."
        ),
    )
    propose.add_argument("--resource-id", required=True, type=UUID)
    propose.add_argument("--artifact-id", required=True, type=UUID)
    propose.add_argument("--scope-authorization-id", required=True)
    propose.add_argument(
        "--review-id", required=True,
        help="Identifiant canonique de cette revue de publication (minuscules, [a-z0-9._-]).",
    )

    record = subparsers.add_parser(
        "record-attestation",
        help="Enregistre l'attestation après approbation humaine de l'artefact de revue.",
    )
    record.add_argument("--resource-id", required=True, type=UUID)
    record.add_argument("--artifact-id", required=True, type=UUID)
    record.add_argument("--scope-authorization-id", required=True)
    record.add_argument("--review-id", required=True)
    record.add_argument("--repository", required=True)
    record.add_argument("--pull-request", required=True, type=int)
    record.add_argument(
        "--expected-head", required=True,
        help="SHA (40 hex) du HEAD exact de la PR de revue de publication.",
    )

    propose_batch = subparsers.add_parser(
        "propose-release-batch-review",
        help=(
            "Projette les faits d'une release scellee puis produit l'artefact "
            "de revue LOT42-RELEASE-BATCH-V1. N'approuve rien, ne publie rien."
        ),
    )
    propose_batch.add_argument("--release-id", required=True, type=_non_blank)
    propose_batch.add_argument("--release-dir", required=True, type=Path)
    propose_batch.add_argument(
        "--release-manifest-sha256", required=True, type=_non_blank
    )
    propose_batch.add_argument("--transfer-manifest-path", required=True, type=Path)
    propose_batch.add_argument(
        "--transfer-manifest-sha256", required=True, type=_non_blank
    )
    propose_batch.add_argument("--rights-registry-path", required=True, type=Path)
    propose_batch.add_argument("--review-id", required=True, type=_non_blank)
    propose_batch.add_argument("--valid-days", type=int, default=30)
    propose_batch.add_argument(
        "--evaluator", required=True, type=_non_blank,
        help="Identite de l'evaluateur de la porte de publication — datee et reelle.",
    )

    record_batch = subparsers.add_parser(
        "record-release-batch-attestation",
        help=(
            "Enregistre les attestations batch apres approbation humaine de "
            "l'artefact de revue."
        ),
    )
    record_batch.add_argument("--release-id", required=True, type=_non_blank)
    record_batch.add_argument("--review-id", required=True, type=_non_blank)
    record_batch.add_argument("--repository", required=True, type=_non_blank)
    record_batch.add_argument("--pull-request", required=True, type=int)
    record_batch.add_argument("--expected-head", required=True, type=_non_blank)
    record_batch.add_argument(
        "--review-artifact-path", required=True, type=_non_blank,
        help=(
            "Chemin canonique de l'artefact de revue APPROUVE, tel que "
            "propose-release-batch-review l'a affiche. Il porte le digest de "
            "l'artefact : un contenu different aurait un autre chemin. Le "
            "contenu relu est de toute facon reconfronte aux faits persistes."
        ),
    )

    return parser


def _reject_negative_chain(facts: PublicationFacts) -> str | None:
    """Item F, première barrière côté outil : une chaîne négative est
    refusée *avant* toute construction d'artefact, avec un message qui
    nomme le fait exact qui bloque."""
    if not facts.quality_passed:
        return (
            f"PUBLICATION_DENIED_QUALITY: resource {facts.resource_id} has "
            "quality_passed=false in its durable evidence"
        )
    if not facts.gate_passed:
        return (
            f"PUBLICATION_DENIED_GATE: resource {facts.resource_id} has "
            f"gate_passed=false ({facts.gate_name}) in its durable evidence"
        )
    if facts.rights_status == Rights.unknown:
        return (
            f"PUBLICATION_DENIED_RIGHTS: resource {facts.resource_id} has "
            "rights_status='unknown' in its durable evidence"
        )
    return None


def _build_artifact(
    *,
    review_id: str,
    facts: PublicationFacts,
    authorization: VerifiedAuthorization,
) -> PublicationReviewArtifactV2:
    """Construit l'artefact **entièrement** depuis les faits durables et
    l'autorisation vérifiée. Aucun champ n'a d'autre origine.

    ADR-0035 : le producteur n'émet plus que du LOT42-V2.
    ``attributed_facts_digest`` vient de ``facts.attribution_digest``,
    c'est-à-dire de la colonne générée par PostgreSQL — jamais d'un calcul
    côté client, qui pourrait diverger de ce que la base scelle."""
    return PublicationReviewArtifactV2(
        protocol_version=LOT42_V2_PROTOCOL_VERSION,
        attributed_facts_digest=facts.attribution_digest,
        review_id=review_id,
        decision="AUTHORIZE_PUBLICATION",
        resource_id=str(facts.resource_id),
        artifact_id=str(facts.artifact_id),
        collection=facts.collection,
        canonical_url=facts.canonical_url,
        content_sha256=facts.content_sha256,
        scope_authorization_id=authorization.authorization_id,
        profile_id=authorization.profile_id,
        profile_version=authorization.profile_version,
        profile_fingerprint=authorization.profile_fingerprint,
        manifest_digest=authorization.manifest_digest,
        rights_status=facts.rights_status,
        rights_assessed_at=facts.rights_assessed_at,
        quality_passed=facts.quality_passed,
        quality_report_digest=facts.quality_report_digest,
        quality_assessed_at=facts.quality_assessed_at,
        gate_passed=facts.gate_passed,
        gate_name=facts.gate_name,
        gate_evaluated_at=facts.gate_evaluated_at,
        evidence_event_ids=facts.evidence_event_ids,
    )


def _load_facts_and_authorization(
    conn: psycopg.Connection, *, resource_id: UUID, artifact_id: UUID, authorization_id: str
) -> tuple[PublicationFacts, VerifiedAuthorization] | None:
    try:
        facts = collect_publication_facts(
            conn, resource_id=resource_id, artifact_id=artifact_id
        )
    except PublicationEvidenceMissingError as exc:
        print(f"DURABLE_EVIDENCE_MISSING: {exc}", file=sys.stderr)
        return None

    denial = _reject_negative_chain(facts)
    if denial is not None:
        print(denial, file=sys.stderr)
        return None

    try:
        authorization = verify_scope_authorization(conn, authorization_id=authorization_id)
    except ScopeAuthorizationDeniedError as exc:
        print(f"SCOPE_AUTHORIZATION_DENIED: {exc}", file=sys.stderr)
        return None

    if authorization.scope.collection != facts.collection:
        print(
            f"SCOPE_COLLECTION_MISMATCH: authorization covers "
            f"{authorization.scope.collection!r}, resource is in {facts.collection!r}",
            file=sys.stderr,
        )
        return None
    if not authorization_allows_rights(authorization, facts.rights_status):
        print(
            f"RIGHTS_NOT_AUTHORIZED: {facts.rights_status.value!r} is not among "
            f"{list(authorization.rights_categories)!r}",
            file=sys.stderr,
        )
        return None
    return facts, authorization


def _cmd_propose_review(args: argparse.Namespace) -> int:
    with psycopg.connect(get_attestor_dsn()) as conn:
        loaded = _load_facts_and_authorization(
            conn,
            resource_id=args.resource_id,
            artifact_id=args.artifact_id,
            authorization_id=args.scope_authorization_id,
        )
        if loaded is None:
            return 1
        facts, authorization = loaded

    try:
        artifact = _build_artifact(
            review_id=args.review_id, facts=facts, authorization=authorization
        )
    except ValueError as exc:
        print(f"REVIEW_ARTIFACT_INVALID: {exc}", file=sys.stderr)
        return 1

    print(f"REVIEW_ARTIFACT_PATH {artifact.canonical_path()}")
    print(f"REVIEW_ARTIFACT_DIGEST {artifact.digest()}")
    sys.stdout.write(artifact.canonical_bytes().decode("utf-8"))
    return 0


def _verified_approval(args: argparse.Namespace) -> ReviewVerification | None:
    try:
        live = verify_review(
            repository=args.repository,
            pull_request=args.pull_request,
            expected_head=args.expected_head,
        )
    except GitHubAuthorityError as exc:
        print(f"LIVE_REVIEW_VERIFICATION_FAILED: {exc}", file=sys.stderr)
        return None
    if not live.approved:
        print(
            f"ATTESTATION_DENIED: publication review PR #{args.pull_request} is "
            f"not APPROVED at head {args.expected_head} — reason={live.reason}",
            file=sys.stderr,
        )
        return None
    return live


def _cmd_record_attestation(args: argparse.Namespace) -> int:
    # Lecture des faits sous le rôle attestor lui-même : il détient SELECT
    # sur les tables du pipeline et sur workflow_events, mais aucune
    # écriture. Ce conteneur ne reçoit donc qu'UN seul credential (item K)
    # — jamais aussi celui du worker sous prétexte de lire des faits.
    with psycopg.connect(get_attestor_dsn()) as read_conn:
        loaded = _load_facts_and_authorization(
            read_conn,
            resource_id=args.resource_id,
            artifact_id=args.artifact_id,
            authorization_id=args.scope_authorization_id,
        )
        if loaded is None:
            return 1
        facts, authorization = loaded

    live = _verified_approval(args)
    if live is None:
        return 1

    # L'artefact attendu est recalculé depuis la base, puis le blob approuvé
    # est relu et comparé octet à octet à ce calcul : c'est cette double
    # dérivation qui interdit toute divergence DB ↔ artefact revu.
    try:
        expected_artifact = _build_artifact(
            review_id=args.review_id, facts=facts, authorization=authorization
        )
    except ValueError as exc:
        print(f"REVIEW_ARTIFACT_INVALID: {exc}", file=sys.stderr)
        return 1

    digest = expected_artifact.digest()
    path = canonical_publication_review_path(review_id=args.review_id, digest=digest)

    try:
        blob = fetch_blob_at_ref(repository=live.repository, path=path, ref=live.head_sha)
    except GitHubAuthorityError as exc:
        print(
            f"REVIEWED_ARTIFACT_UNREADABLE: {path}@{live.head_sha}: {exc}\n"
            "Hint: the committed artifact must match the database exactly — its "
            "digest is part of its canonical path, so any divergence changes "
            "the path and makes it unreadable here.",
            file=sys.stderr,
        )
        return 1

    if blob.content != expected_artifact.canonical_bytes():
        print(
            f"REVIEWED_ARTIFACT_DIVERGES_FROM_DB: {path}@{live.head_sha} does not "
            "byte-match the artifact derived from durable evidence",
            file=sys.stderr,
        )
        return 1

    try:
        reviewed = require_publication_review_v2(
            parse_publication_review_artifact(blob.content)
        )
    except CanonicalArtifactError as exc:
        print(f"REVIEWED_ARTIFACT_NOT_CANONICAL: {exc}", file=sys.stderr)
        return 1

    with psycopg.connect(get_attestor_dsn()) as conn:
        # H2-F (défaut 6) : les faits ont été lus sur une connexion déjà
        # refermée. Ils sont donc relus ICI, dans la transaction qui écrit
        # l'attestation et sous ``FOR SHARE`` : un writer concurrent qui
        # voudrait changer l'attribution est bloqué jusqu'au commit, et une
        # attribution qui aurait changé depuis la revue est refusée plutôt
        # que scellée à l'insu de l'humain qui a approuvé.
        try:
            _attribution, attributed_facts_digest = load_artifact_attribution(
                conn, ingestion_artifact_id=args.artifact_id, lock=True
            )
        except ArtifactAttributionError as exc:
            print(f"ATTRIBUTION_EVIDENCE_MISSING: {exc}", file=sys.stderr)
            return 1
        if attributed_facts_digest != facts.attribution_digest:
            print(
                "ATTRIBUTION_DRIFTED_SINCE_REVIEW: the control-plane attribution "
                f"of artifact {args.artifact_id} changed between the reviewed "
                f"proposal ({facts.attribution_digest}) and this attestation "
                f"({attributed_facts_digest}) — re-propose the review",
                file=sys.stderr,
            )
            return 1
        # ADR-0035 : troisième branche. Les deux comparaisons ci-dessus
        # relient la base d'alors à la base de maintenant ; celle-ci relie
        # les **octets que l'humain a effectivement approuvés** à
        # l'attribution vivante. Sans elle, un artefact byte-identique aux
        # faits d'alors resterait acceptable alors même que son digest
        # d'attribution désignerait autre chose.
        if reviewed.attributed_facts_digest != attributed_facts_digest:
            print(
                "REVIEWED_ATTRIBUTION_MISMATCH: the human-reviewed artifact names "
                f"attribution digest {reviewed.attributed_facts_digest} but the "
                f"control plane currently holds {attributed_facts_digest} for "
                f"artifact {args.artifact_id}",
                file=sys.stderr,
            )
            return 1

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_control.publication_attestations (
                    resource_id, artifact_id, content_sha256, canonical_url, collection,
                    scope_authorization_id, profile_id, profile_version, profile_fingerprint,
                    manifest_digest,
                    rights_status, rights_assessed_at,
                    quality_passed, quality_report_digest, quality_assessed_at,
                    gate_passed, gate_name, gate_evaluated_at,
                    evidence_event_ids,
                    review_id, review_artifact_path, review_artifact_blob_sha, attestation_digest,
                    human_review_repository, human_review_pull_request, human_review_base_sha,
                    human_review_head_sha, human_review_review_id, human_review_reviewer,
                    human_review_submitted_at, human_review_challenge,
                    protocol_version, attributed_facts_digest
                ) VALUES (
                    %(resource_id)s, %(artifact_id)s, %(content_sha256)s, %(canonical_url)s, %(collection)s,
                    %(scope_authorization_id)s, %(profile_id)s, %(profile_version)s, %(profile_fingerprint)s,
                    %(manifest_digest)s,
                    %(rights_status)s, %(rights_assessed_at)s,
                    %(quality_passed)s, %(quality_report_digest)s, %(quality_assessed_at)s,
                    %(gate_passed)s, %(gate_name)s, %(gate_evaluated_at)s,
                    %(evidence_event_ids)s,
                    %(review_id)s, %(review_artifact_path)s, %(review_artifact_blob_sha)s, %(attestation_digest)s,
                    %(human_review_repository)s, %(human_review_pull_request)s, %(human_review_base_sha)s,
                    %(human_review_head_sha)s, %(human_review_review_id)s, %(human_review_reviewer)s,
                    %(human_review_submitted_at)s, %(human_review_challenge)s,
                    %(protocol_version)s, %(attributed_facts_digest)s
                )
                """,
                {
                    "resource_id": args.resource_id,
                    "artifact_id": args.artifact_id,
                    "content_sha256": reviewed.content_sha256,
                    "canonical_url": reviewed.canonical_url,
                    "collection": reviewed.collection,
                    "scope_authorization_id": reviewed.scope_authorization_id,
                    "profile_id": reviewed.profile_id,
                    "profile_version": reviewed.profile_version,
                    "profile_fingerprint": reviewed.profile_fingerprint,
                    "manifest_digest": reviewed.manifest_digest,
                    "rights_status": reviewed.rights_status.value,
                    "rights_assessed_at": reviewed.rights_assessed_at,
                    "quality_passed": reviewed.quality_passed,
                    "quality_report_digest": facts.quality_report_digest,
                    "quality_assessed_at": reviewed.quality_assessed_at,
                    "gate_passed": reviewed.gate_passed,
                    "gate_name": reviewed.gate_name,
                    "gate_evaluated_at": reviewed.gate_evaluated_at,
                    "evidence_event_ids": list(reviewed.evidence_event_ids),
                    "review_id": reviewed.review_id,
                    "review_artifact_path": path,
                    "review_artifact_blob_sha": blob.blob_sha,
                    "attestation_digest": digest,
                    "human_review_repository": live.repository,
                    "human_review_pull_request": live.pull_request,
                    "human_review_base_sha": live.base_sha,
                    "human_review_head_sha": live.head_sha,
                    "human_review_review_id": live.review_id,
                    "human_review_reviewer": live.reviewer,
                    "human_review_submitted_at": live.submitted_at,
                    "human_review_challenge": live.challenge,
                    "protocol_version": LOT42_V2_PROTOCOL_VERSION,
                    "attributed_facts_digest": attributed_facts_digest,
                },
            )
        conn.commit()

    print(
        f"ATTESTATION_RECORDED resource_id={args.resource_id} "
        f"artifact_id={args.artifact_id} review={path}@{live.head_sha} "
        f"blob_sha={blob.blob_sha} digest={digest}"
    )
    return 0


def _charger_sources_scellees(args: argparse.Namespace) -> dict[str, object]:
    """Charge les autorites scellees, chacune verifiee par son empreinte."""
    from ingestor.ingestion_control.sealed_release_catalog import (
        load_sealed_release_catalog,
    )

    catalogue = load_sealed_release_catalog(
        args.release_dir,
        expected_release_manifest_sha256=args.release_manifest_sha256,
        transfer_manifest_path=args.transfer_manifest_path,
        expected_transfer_manifest_sha256=args.transfer_manifest_sha256,
    )
    manifeste = json.loads(
        (args.release_dir / "production-profile-gate.release.json").read_bytes()
    )
    autorites = manifeste["authorities"]

    def _lire(nom: str, attendu: str) -> tuple[dict, str]:
        brut = (args.release_dir / nom).read_bytes()
        digest = hashlib.sha256(brut).hexdigest()
        if digest != attendu:
            raise SystemExit(
                f"SEALED_SOURCE_DIGEST_MISMATCH: {nom} hashes to {digest}, "
                f"the release manifest declares {attendu}"
            )
        return json.loads(brut.decode("utf-8")), digest

    preflight, _ = _lire("preflight_evidence.json", autorites["preflight_evidence_sha256"])
    currentness, _ = _lire(
        "currentness_evidence.json", autorites["currentness_evidence_sha256"]
    )
    pii, pii_digest = _lire("pii_evidence.json", autorites["pii_evidence_sha256"])

    from ingestor.ingestion_control.sealed_evidence import (
        VerifiedRightsEvidenceRegistry,
    )

    droits = VerifiedRightsEvidenceRegistry.load(
        args.rights_registry_path,
        expected_registry_sha256=autorites["rights_registry_sha256"],
        expected_corpus_manifest_sha256=autorites["corpus_manifest_sha256"],
    )
    par_pii: dict[str, dict] = {}
    for entree in pii["results"]:
        par_pii.setdefault(entree["content_sha256"], entree)
    return {
        "catalogue": catalogue,
        "preflight": {a["content_sha256"]: a for a in preflight["artifacts"]},
        "currentness": {
            a.get("content_sha256"): a for a in currentness["artifacts"]
        },
        "pii": par_pii,
        "pii_digest": pii_digest,
        "droits": droits,
    }


def _cmd_propose_release_batch_review(args: argparse.Namespace) -> int:
    from datetime import timedelta

    from ingestor.ingestion_control.release_batch_attestation import (
        ReleaseBatchAttestationError,
        build_release_batch_review_artifact,
        measure_release_batch_facts,
        require_facts_match_catalog,
    )
    from ingestor.ingestion_control.sealed_release_projection import (
        DERIVATION,
        DimensionProjetee,
        ProjectionRow,
        SealedReleaseProjectionError,
        derive_currentness,
        derive_pii,
        derive_quality,
        now_utc,
        persist_projection,
    )

    try:
        sources = _charger_sources_scellees(args)
    except Exception as exc:  # noqa: BLE001 - frontiere CLI fail-closed
        print(f"SEALED_SOURCES_UNUSABLE: {exc}", file=sys.stderr)
        return 1

    evalue_a = now_utc()
    with psycopg.connect(get_attestor_dsn()) as conn:
        try:
            facts = measure_release_batch_facts(conn, release_id=args.release_id)
            require_facts_match_catalog(facts, sources["catalogue"])
        except ReleaseBatchAttestationError as exc:
            print(f"RELEASE_BATCH_FACTS_REFUSED: {exc}", file=sys.stderr)
            return 1

        lignes: list[ProjectionRow] = []
        for resource_id, (artifact_id, sha, collection, autorisation) in (
            facts.par_ressource.items()
        ):
            scelle = dict(sources["catalogue"].artifacts[sha])
            entree_qualite = dict(sources["preflight"].get(sha, {}))
            entree_qualite.setdefault("content_sha256", sha)
            entree_qualite.setdefault(
                "chunk_id_set_digest", scelle.get("chunk_id_set_digest")
            )
            entree_qualite.setdefault(
                "chunk_sha256_set_digest", scelle.get("chunk_sha256_set_digest")
            )
            entree_qualite.setdefault(
                "ignored_empty_pages", scelle.get("ignored_empty_pages") or []
            )
            try:
                clearance = sources["droits"].resolve_rights(
                    content_sha256=sha, source_path=scelle["source_path"]
                )
            except Exception as exc:  # noqa: BLE001
                print(f"RIGHTS_UNRESOLVED: {sha[:12]}…: {exc}", file=sys.stderr)
                return 1
            lignes.append(
                ProjectionRow(
                    resource_id=resource_id,
                    artifact_id=artifact_id,
                    content_sha256=sha,
                    collection=collection,
                    scope_authorization_id=autorisation,
                    droits=DimensionProjetee(
                        valeur=clearance.rights.value,
                        origine=DERIVATION,
                        source=clearance.decision_id,
                        digest=clearance.registry_sha256,
                    ),
                    qualite=derive_quality(entree_qualite),
                    actualite=derive_currentness(sources["currentness"].get(sha)),
                    pii=derive_pii(
                        sources["pii"].get(sha),
                        evidence_sha256=str(sources["pii_digest"]),
                    ),
                    gate_evaluator=args.evaluator,
                    gate_evaluated_at=evalue_a,
                )
            )
        try:
            ecrites, deja = persist_projection(conn, facts=facts, lignes=lignes)
        except SealedReleaseProjectionError as exc:
            print(f"PROJECTION_CONFLICT: {exc}", file=sys.stderr)
            return 1
        conn.commit()

    bloquees = [ligne for ligne in lignes if not ligne.gate_passed]
    print(
        f"PROJECTION_PERSISTED release_id={facts.release_id} "
        f"written={ecrites} already_present={deja} blocked={len(bloquees)}"
    )
    if bloquees:
        for ligne in bloquees[:5]:
            print(
                f"  BLOCKED resource_id={ligne.resource_id} "
                f"unresolved={ligne.unresolved}",
                file=sys.stderr,
            )
        print(
            "RELEASE_BATCH_REVIEW_REFUSED: "
            f"{len(bloquees)} resource(s) carry an unresolved or negative "
            "condition — the review cannot cover what is not established",
            file=sys.stderr,
        )
        return 1

    try:
        artifact = build_release_batch_review_artifact(
            review_id=args.review_id,
            facts=facts,
            valid_from=evalue_a,
            valid_until=evalue_a + timedelta(days=args.valid_days),
        )
    except ValueError as exc:
        print(f"REVIEW_ARTIFACT_INVALID: {exc}", file=sys.stderr)
        return 1

    chemin = canonical_publication_review_path(
        review_id=artifact.review_id, digest=artifact.digest()
    )
    print(f"REVIEW_ARTIFACT_PATH {chemin}")
    print(f"REVIEW_ARTIFACT_DIGEST {artifact.digest()}")
    sys.stdout.write(artifact.canonical_bytes().decode("utf-8"))
    return 0


def _cmd_record_release_batch_attestation(args: argparse.Namespace) -> int:
    """Enregistre N attestations batch apres approbation humaine.

    L'artefact approuve est relu sur GitHub au head exact, puis reconfronte
    aux faits PERSISTES : une modification survenue entre la proposition et
    l'enregistrement est detectee ici, et refusee.
    """
    from nexus_contracts.authority_artifacts import (
        parse_release_batch_publication_review_artifact,
    )

    from ingestor.ingestion_control.release_batch_attestation import (
        BATCH_PROTOCOL,
        ReleaseBatchAttestationError,
        measure_release_batch_facts,
        require_artifact_matches_facts,
        require_resource_is_covered,
    )
    from ingestor.ingestion_control.sealed_release_projection import (
        SealedReleaseProjectionError,
        load_applicable_projection,
        require_projection_authorises,
    )

    live = _verified_approval(args)
    if live is None:
        return 1

    with psycopg.connect(get_attestor_dsn()) as conn:
        try:
            facts = measure_release_batch_facts(conn, release_id=args.release_id)
        except ReleaseBatchAttestationError as exc:
            print(f"RELEASE_BATCH_FACTS_REFUSED: {exc}", file=sys.stderr)
            return 1

        # L'artefact APPROUVE, relu au head exact. Son chemin canonique
        # contient son digest : une divergence change le chemin et le rend
        # illisible ici, ce qui est deja un refus.
        path = args.review_artifact_path
        try:
            blob = fetch_blob_at_ref(
                repository=live.repository, path=path, ref=live.head_sha
            )
        except GitHubAuthorityError as exc:
            print(
                f"REVIEWED_ARTIFACT_UNREADABLE: {path}@{live.head_sha}: {exc}",
                file=sys.stderr,
            )
            return 1

        try:
            artifact = parse_release_batch_publication_review_artifact(blob.content)
        except Exception as exc:  # noqa: BLE001
            print(f"REVIEWED_ARTIFACT_INVALID: {exc}", file=sys.stderr)
            return 1

        attendu = canonical_publication_review_path(
            review_id=artifact.review_id, digest=artifact.digest()
        )
        if attendu != path:
            print(
                f"REVIEWED_ARTIFACT_PATH_MISMATCH: the artifact read at {path} "
                f"derives the canonical path {attendu} — its "
                "content does not match the location it was approved at",
                file=sys.stderr,
            )
            return 1
        if artifact.review_id != args.review_id:
            print(
                f"REVIEWED_ARTIFACT_REVIEW_MISMATCH: artifact carries review_id "
                f"{artifact.review_id!r}, the command names {args.review_id!r}",
                file=sys.stderr,
            )
            return 1

        try:
            require_artifact_matches_facts(artifact, facts)
        except ReleaseBatchAttestationError as exc:
            print(f"REVIEWED_ARTIFACT_DIVERGES_FROM_DB: {exc}", file=sys.stderr)
            return 1

        digest = artifact.digest()
        ecrites = deja = 0
        for resource_id, (artifact_id, sha, collection, autorisation) in (
            facts.par_ressource.items()
        ):
            try:
                require_resource_is_covered(artifact, facts, resource_id=resource_id)
                projection = load_applicable_projection(
                    conn, release_id=facts.release_id,
                    resource_id=resource_id, artifact_id=artifact_id,
                )
                require_projection_authorises(projection, resource_id=resource_id)
            except (ReleaseBatchAttestationError, SealedReleaseProjectionError) as exc:
                print(f"ATTESTATION_REFUSED: {exc}", file=sys.stderr)
                return 1

            existante = conn.execute(
                "SELECT attestation_digest FROM ingestion_control.publication_attestations"
                " WHERE resource_id = %s AND invalidated_at IS NULL",
                (resource_id,),
            ).fetchone()
            if existante is not None:
                if existante[0] != digest:
                    print(
                        f"ATTESTATION_CONFLICT: resource {resource_id} already "
                        f"carries attestation {existante[0][:16]}…, the new one "
                        f"is {digest[:16]}… — no silent overwrite",
                        file=sys.stderr,
                    )
                    return 1
                deja += 1
                continue

            conn.execute(
                _INSERT_ATTESTATION,
                {
                    "resource_id": resource_id,
                    "artifact_id": artifact_id,
                    "content_sha256": sha,
                    # Une release scellee n'a PAS d'URL canonique : le schema
                    # l'interdit pour ce protocole.
                    "canonical_url": None,
                    "collection": collection,
                    "scope_authorization_id": autorisation,
                    "profile_id": collection,
                    "profile_version": "v2-livraison-319",
                    "profile_fingerprint": facts.artifacts_release_sha256,
                    "manifest_digest": facts.release_manifest_sha256,
                    "rights_status": projection["rights_status"],
                    "rights_assessed_at": projection["gate_evaluated_at"],
                    "quality_passed": projection["quality_passed"],
                    "quality_report_digest": projection["quality_report_digest"],
                    "quality_assessed_at": projection["gate_evaluated_at"],
                    "gate_passed": projection["gate_passed"],
                    "gate_name": projection["gate_name"],
                    "gate_evaluated_at": projection["gate_evaluated_at"],
                    "evidence_event_ids": _evenements_de(conn, resource_id),
                    "review_id": artifact.review_id,
                    "review_artifact_path": path,
                    "review_artifact_blob_sha": blob.blob_sha,
                    "attestation_digest": digest,
                    "human_review_repository": live.repository,
                    "human_review_pull_request": live.pull_request,
                    "human_review_base_sha": live.base_sha,
                    "human_review_head_sha": live.head_sha,
                    "human_review_review_id": live.review_id,
                    "human_review_reviewer": live.reviewer,
                    "human_review_submitted_at": live.submitted_at,
                    "human_review_challenge": live.challenge,
                    "protocol_version": BATCH_PROTOCOL,
                    # Reserve a V2 : le schema l'INTERDIT pour le batch.
                    "attributed_facts_digest": None,
                    "release_id": facts.release_id,
                    "release_manifest_sha256": facts.release_manifest_sha256,
                    "artifacts_release_sha256": facts.artifacts_release_sha256,
                    "candidate_inventory_sha256": facts.candidate_inventory_sha256,
                    "artifact_transfer_manifest_sha256":
                        facts.artifact_transfer_manifest_sha256,
                    "release_batch_review_digest": digest,
                },
            )
            ecrites += 1
        conn.commit()

    print(
        f"RELEASE_BATCH_ATTESTATIONS_RECORDED release_id={facts.release_id} "
        f"written={ecrites} already_present={deja} review={path}@{live.head_sha} "
        f"digest={digest}"
    )
    return 0


def _evenements_de(conn: object, resource_id: object) -> list:
    """Les evenements HISTORIQUES de cette ressource, references tels quels."""
    lignes = conn.execute(  # type: ignore[attr-defined]
        "SELECT event_id FROM ingestion_control.workflow_events "
        " WHERE resource_id = %s ORDER BY occurred_at, event_id",
        (resource_id,),
    ).fetchall()
    return [ligne[0] for ligne in lignes]


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if args.command == "propose-review":
        return _cmd_propose_review(args)
    if args.command == "record-attestation":
        return _cmd_record_attestation(args)
    if args.command == "propose-release-batch-review":
        return _cmd_propose_release_batch_review(args)
    if args.command == "record-release-batch-attestation":
        return _cmd_record_release_batch_attestation(args)
    raise AssertionError(f"unreachable: unknown command {args.command!r}")  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover - couvert par appel direct de main() dans les tests
    sys.exit(main())


__all__ = ["main"]
