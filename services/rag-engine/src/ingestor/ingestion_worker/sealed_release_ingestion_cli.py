"""CLI du point d'entrée d'ingestion orienté release scellée (ADR-0056).

Frontière fail-closed : tout est refusé avant PostgreSQL, puis l'ingestion
entière se fait dans une seule transaction — elle aboutit complètement ou
ne laisse rien.

Ce CLI ne connaît pas ``PG_RAG_DSN``, n'ouvre que la connexion
``ingestion_control``, et refuse de s'exécuter en production.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from nexus_release_chain.public_successor_activation import (
    PublicSuccessorActivationError,
    PublicSuccessorContentVerdict,
    verify_content_anchor,
    verify_content_currentness,
)

from ingestor.ingestion_control.attestation import (
    WorkerAttestationError,
    attest_runtime_role,
)
from ingestor.ingestion_control.db import get_ingestion_control_dsn
from ingestor.ingestion_profiles.registry import load_profile_registry
from ingestor.ingestion_profiles.staging_readiness_gate import (
    enforce_staging_readiness_gate,
    require_control_dsn_differs_from_product,
    require_running_image_matches_manifest,
)

from .runtime_authority import RuntimeAuthorityStartupError
from .sealed_release_attribution_backfill import (
    AttributionBackfillError,
    backfill_sealed_release_attributions,
)
from .sealed_release_ingestion import (
    SealedReleaseIngestionError,
    ingest_sealed_release,
    load_sealed_release,
)

#: Le seul environnement où ce point d'entrée s'exécute. La production est
#: refusée **nommément** : ce lot ingère un corpus qui n'a pas encore reçu
#: son attestation LOT42 batch, et rien de tel n'a sa place en production.
#:
#: Le refus lui-même est appliqué par ``enforce_staging_readiness_gate``, dont
#: c'est la première garde. Cette constante reste ici parce qu'elle documente
#: le périmètre de ce CLI, et parce qu'un test l'y lit.
REQUIRED_ENVIRONMENT = "rehearsal"


def _non_blank(raw: str) -> str:
    if not raw.strip():
        raise argparse.ArgumentTypeError("must not be blank")
    return raw


def _mapping_entry(raw: str) -> tuple[str, str]:
    collection, separator, authorization_id = raw.partition("=")
    if not separator or not collection.strip() or not authorization_id.strip():
        raise argparse.ArgumentTypeError(
            "expected collection=authorization_id (both non-blank)"
        )
    return collection.strip(), authorization_id.strip()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Ingestion d'une release scellée jusqu'à NEEDS_REVIEW — "
            "ne publie rien, n'atteste rien"
        )
    )
    parser.add_argument("--release-dir", required=True, type=Path)
    parser.add_argument("--release-manifest-sha256", required=True, type=_non_blank)
    parser.add_argument("--artifacts-release-sha256", required=True, type=_non_blank)
    parser.add_argument("--candidate-inventory-sha256", required=True, type=_non_blank)
    parser.add_argument(
        "--artifact-transfer-manifest-path", required=True, type=Path
    )
    parser.add_argument(
        "--artifact-transfer-manifest-sha256", required=True, type=_non_blank
    )
    parser.add_argument("--artifact-store-dir", required=True, type=Path)
    parser.add_argument("--profiles-dir", required=True, type=Path)
    parser.add_argument("--owner", required=True, type=_non_blank)
    parser.add_argument("--expected-role", required=True, type=_non_blank)
    parser.add_argument(
        "--scope-authorization",
        required=True,
        action="append",
        type=_mapping_entry,
        metavar="COLLECTION=AUTHORIZATION_ID",
        help=(
            "Autorisation LOT41A nommée pour une collection. Répéter une fois "
            "par collection : aucune autorisation n'est devinée ni choisie "
            "par ancienneté."
        ),
    )
    parser.add_argument(
        "--expected-collection",
        action="append",
        default=None,
        type=_non_blank,
        help=(
            "Collection attendue. Quand l'option est fournie, une collection "
            "manquante ET une collection en surplus sont toutes deux refusées."
        ),
    )
    parser.add_argument(
        "--only-attributions",
        action="store_true",
        help=(
            "N'ingère RIEN : établit seulement les quatre faits d'attribution "
            "manquants des artefacts déjà ingérés de cette release, dérivés de "
            "son propre catalogue. Une release ingérée avant que ce point "
            "d'entrée ne les écrive n'en porte aucun, et la publication refuse "
            "— à raison. Réingérer ferait perdre les ressources, runs et "
            "événements que la revue a couverts."
        ),
    )
    parser.add_argument("--report-path", type=Path, default=None)
    parser.add_argument("--public-successor-content-anchor-path", type=Path)
    parser.add_argument("--public-successor-preissuance-receipt-path", type=Path)
    parser.add_argument("--public-successor-preissuance-receipt-sha256")
    return parser


def _scope_authorization_ids(
    entries: list[tuple[str, str]],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for collection, authorization_id in entries:
        if collection in mapping and mapping[collection] != authorization_id:
            raise SealedReleaseIngestionError(
                f"{collection} : deux autorisations nommées "
                f"({mapping[collection]!r} et {authorization_id!r}) — l'ambiguïté "
                "est refusée, jamais arbitrée"
            )
        mapping[collection] = authorization_id
    return mapping


def _require_readiness_covers_this_release(readiness: object, facts: object) -> None:
    """L'autorisation de répétition nomme un corpus. Ce doit être celui-ci.

    Sans cette liaison, un manifeste valide autoriserait l'ingestion de
    n'importe quelle release — l'autorité porterait sur l'hôte, pas sur ce
    qu'on y écrit."""
    manifest = readiness.manifest  # type: ignore[attr-defined]
    release_id = facts.release_id  # type: ignore[attr-defined]
    digest = facts.release_manifest_sha256  # type: ignore[attr-defined]
    if manifest.allowed_release_id != release_id:
        raise SealedReleaseIngestionError(
            f"staging readiness authorises release {manifest.allowed_release_id!r}, "
            f"but this run ingests {release_id!r}"
        )
    if manifest.allowed_release_manifest_sha256 != digest:
        raise SealedReleaseIngestionError(
            "staging readiness authorises release manifest "
            f"{manifest.allowed_release_manifest_sha256}, but this run loaded "
            f"{digest}"
        )


def _require_public_candidate_ingestion_authority(
    readiness: object,
    release_dir: Path,
    anchor_path: Path,
    receipt_path: Path,
    receipt_sha256: str,
) -> PublicSuccessorContentVerdict:
    """Relire A et son checkpoint sous la readiness INGESTION déjà vérifiée.

    Le checkpoint n'est pas une approbation autonome : l'orchestrateur doit
    rejouer #300/#312/CAS avant la signature de cette readiness. Ici, la
    signature lie explicitement son SHA à cette phase et à A.
    """
    manifest = readiness.manifest  # type: ignore[attr-defined]
    if getattr(manifest, "public_successor_phase", None) != "INGESTION":
        raise SealedReleaseIngestionError("public successor requires signed INGESTION phase")
    anchor_sha = getattr(manifest, "public_successor_content_anchor_digest", None)
    signed_receipt_sha = getattr(manifest, "public_successor_phase_authority_digest", None)
    if not isinstance(anchor_sha, str) or not isinstance(signed_receipt_sha, str):
        raise SealedReleaseIngestionError("public successor signed phase incomplete")
    if signed_receipt_sha != receipt_sha256:
        raise SealedReleaseIngestionError("public successor phase authority digest differs")
    try:
        content = verify_content_anchor(anchor_path, anchor_sha, release_dir.parent)
        verify_content_currentness(release_dir.parent, content, datetime.now(UTC))
        raw = receipt_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != receipt_sha256:
            raise SealedReleaseIngestionError("preissuance checkpoint digest differs")
        receipt = json.loads(raw)
        canonical = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        index_path = release_dir.parent / "preparation-index.json"
        index_raw = index_path.read_bytes()
        if hashlib.sha256(index_raw).hexdigest() != content.preparation_index_sha256:
            raise SealedReleaseIngestionError("preparation index differs from A")
        index = json.loads(index_raw)
    except (PublicSuccessorActivationError, OSError, ValueError) as error:
        raise SealedReleaseIngestionError("public successor checkpoint or A invalid") from error
    if not isinstance(receipt, dict) or raw != canonical or set(receipt) != {
        "kind", "status", "content_anchor_sha256", "content_manifest_sha256",
        "manifest_relative_path", "preparation_index_sha256",
        "private_cas_index_sha256", "source_currentness_valid_until_utc",
        "subject_sha256_by_collection",
    } or receipt != {
        "kind": "NEXUS_PUBLIC_SUCCESSOR_PREISSUANCE_CHECKPOINT_V1",
        "status": "CHECKPOINT_ONLY_NOT_SCOPE_AUTHORITY",
        "content_anchor_sha256": content.content_anchor_sha256,
        "content_manifest_sha256": content.content_manifest_sha256,
        "manifest_relative_path": receipt.get("manifest_relative_path"),
        "preparation_index_sha256": content.preparation_index_sha256,
        "private_cas_index_sha256": index.get("private_cas_manifest_sha256"),
        "source_currentness_valid_until_utc": index.get("source_currentness_valid_until_utc"),
        "subject_sha256_by_collection": content.subject_sha256_by_collection,
    } or not isinstance(receipt["manifest_relative_path"], str) or not receipt[
        "manifest_relative_path"
    ].endswith("/profile_gate/production-profile-gate.release.json"):
        raise SealedReleaseIngestionError("public successor checkpoint differs from A")
    if (
        manifest.allowed_release_id != content.release_id
        or manifest.allowed_release_manifest_sha256 != content.content_manifest_sha256
    ):
        raise SealedReleaseIngestionError("signed INGESTION readiness differs from A")
    return content


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        # La chaîne de répétition (ADR-0057), jamais celle de production :
        # ``enforce_readiness_gate`` répond à « cet hôte exécute-t-il la
        # release promue ? », qui n'est pas la question posée ici.
        readiness = enforce_staging_readiness_gate()
        if readiness.environment != REQUIRED_ENVIRONMENT:
            # Redondant : le gate refuse déjà tout autre environnement. La
            # garde ne coûte rien, ne ment pas, et couvre le cas où un
            # appelant fournirait lui-même un résultat de readiness.
            raise RuntimeAuthorityStartupError(
                "sealed release ingestion runs only under "
                f"{REQUIRED_ENVIRONMENT!r}; refusing to run under "
                f"{readiness.environment!r}"
            )
        # Avant toute autre chose : l'image qui exécute ce code est-elle celle
        # que la signature couvre ? Une réponse négative rend tout le reste
        # sans objet, et cette garde précède donc l'ouverture de la moindre
        # connexion comme la moindre écriture.
        image = require_running_image_matches_manifest(readiness.manifest)
        require_control_dsn_differs_from_product(
            control_dsn=get_ingestion_control_dsn(),
            product_dsn=os.environ.get("PG_RAG_DSN"),
        )
        public_args = (
            args.public_successor_content_anchor_path,
            args.public_successor_preissuance_receipt_path,
            args.public_successor_preissuance_receipt_sha256,
        )
        public_phase = getattr(readiness.manifest, "public_successor_phase", None)
        if public_phase is not None or any(value is not None for value in public_args):
            if any(value is None for value in public_args):
                raise SealedReleaseIngestionError(
                    "public successor INGESTION requires A and preissuance checkpoint"
                )
            public_content = _require_public_candidate_ingestion_authority(
                readiness, args.release_dir,
                args.public_successor_content_anchor_path,
                args.public_successor_preissuance_receipt_path,
                args.public_successor_preissuance_receipt_sha256,
            )
        else:
            public_content = None
        profiles = load_profile_registry(args.profiles_dir)
        facts = load_sealed_release(
            args.release_dir,
            release_manifest_sha256=args.release_manifest_sha256,
            artifacts_release_sha256=args.artifacts_release_sha256,
            candidate_inventory_sha256=args.candidate_inventory_sha256,
            artifact_transfer_manifest_path=args.artifact_transfer_manifest_path,
            artifact_transfer_manifest_sha256=args.artifact_transfer_manifest_sha256,
            public_successor_content=public_content,
        )
        authorizations = _scope_authorization_ids(args.scope_authorization)
        _require_readiness_covers_this_release(readiness, facts)
    except Exception as exc:
        print(f"SEALED_RELEASE_INGESTION_STARTUP_FAILED: {exc}", file=sys.stderr)
        return 1

    print(
        "SEALED_RELEASE_INGESTION_STARTUP "
        f"environment={readiness.environment} "
        f"readiness_key_id={readiness.manifest.key_id} "
        f"readiness_manifest_sha256={readiness.manifest_sha256} "
        f"worker_image={image} "
        f"release_id={facts.release_id} "
        f"release_manifest_sha256={facts.release_manifest_sha256} "
        f"subjects={len(facts.collections)} "
        f"unique_artifacts={len(facts.artifact_ids)} "
        f"placements={len(facts.placements)} "
        f"unique_chunks={facts.unique_chunk_count}"
    )

    try:
        with psycopg.connect(get_ingestion_control_dsn()) as conn:
            try:
                attestation = attest_runtime_role(
                    conn, expected_role=args.expected_role
                )
            except WorkerAttestationError as exc:
                print(
                    f"SEALED_RELEASE_INGESTION_ATTESTATION_FAILED: {exc}",
                    file=sys.stderr,
                )
                return 1
            print(
                "SEALED_RELEASE_INGESTION_ATTESTATION_OK "
                f"current_user={attestation.current_user}"
            )
            if args.only_attributions:
                rattrapage = backfill_sealed_release_attributions(
                    conn,
                    facts=facts,
                    profile_registry=profiles,
                    owner=args.owner,
                )
                # Un placement prescrit sans ligne acquise n'est pas un
                # rattrapage fait : c'est un rattrapage IMPOSSIBLE. Le taire
                # derrière un code 0 laissait croire la release attribuée
                # alors qu'aucune ligne — ou pas toutes — n'avait été vue
                # (par exemple en nommant une release successeur, dont les
                # lignes sont adoptées et non acquises). Rien n'est validé.
                if rattrapage.missing_rows:
                    conn.rollback()
                    print(
                        "SEALED_RELEASE_ATTRIBUTION_BACKFILL_REFUSED "
                        f"release_id={rattrapage.release_id} "
                        f"examined={rattrapage.examined} "
                        f"missing_rows={len(rattrapage.missing_rows)} — "
                        f"{len(rattrapage.missing_rows)} prescribed placement(s) "
                        "have no acquired row under this release "
                        f"(first: {rattrapage.missing_rows[0]})",
                        file=sys.stderr,
                    )
                    return 1
                conn.commit()
                payload = rattrapage.as_dict()
                if args.report_path is not None:
                    args.report_path.write_text(
                        json.dumps(
                            payload, ensure_ascii=False, indent=2, sort_keys=True
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                print(
                    "SEALED_RELEASE_ATTRIBUTION_BACKFILL_DONE "
                    f"release_id={rattrapage.release_id} "
                    f"examined={rattrapage.examined} "
                    f"written={rattrapage.written} "
                    f"already_present={rattrapage.already_present} "
                    f"missing_rows={len(rattrapage.missing_rows)}"
                )
                return 0
            report = ingest_sealed_release(
                conn,
                facts=facts,
                artifact_store_dir=args.artifact_store_dir,
                profile_registry=profiles,
                scope_authorization_ids=authorizations,
                owner=args.owner,
                expected_collections=args.expected_collection,
                public_successor_ingestion_content=public_content,
                public_successor_release_dir=args.release_dir if public_content else None,
                public_successor_anchor_path=(
                    args.public_successor_content_anchor_path if public_content else None
                ),
                public_successor_preissuance_receipt_path=(
                    args.public_successor_preissuance_receipt_path if public_content else None
                ),
                public_successor_preissuance_receipt_sha256=(
                    args.public_successor_preissuance_receipt_sha256 if public_content else None
                ),
            )
            conn.commit()
    except AttributionBackfillError as exc:
        print(f"SEALED_RELEASE_ATTRIBUTION_BACKFILL_REFUSED: {exc}", file=sys.stderr)
        return 1
    except SealedReleaseIngestionError as exc:
        print(f"SEALED_RELEASE_INGESTION_REFUSED: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"SEALED_RELEASE_INGESTION_FAILED: {exc}", file=sys.stderr)
        return 1

    payload = report.as_dict()
    if args.report_path is not None:
        args.report_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        "SEALED_RELEASE_INGESTION_DONE "
        f"runs={report.runs} resources={report.resources} "
        f"candidates={report.resource_candidates} artifacts={report.artifacts} "
        f"workflow_events={report.workflow_events} "
        f"terminal_state={report.terminal_state} "
        f"published_rows={report.published_rows} "
        f"attestations={report.attestations}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["REQUIRED_ENVIRONMENT", "main"]
