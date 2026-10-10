#!/usr/bin/env python3
"""Assemble et signe un ``NEXUS-STAGING-READINESS-V1`` (ADR-0057).

**Ce que cet outil refuse structurellement.** Aucun fait n'est saisi « à
l'œil » : le digest du manifeste de release est **recalculé** depuis le
fichier, le commit est **vérifié** présent dans ce dépôt, et la référence
d'image doit porter un digest — un tag est refusé. Le manifeste signé est
**revérifié** contre l'ancre publique avant d'être écrit : un manifeste dont
la propre vérification échoue n'est jamais produit.

**Clé privée.** Lue depuis un fichier local (``--private-key-file``), jamais
depuis un argument en clair, jamais depuis une variable d'environnement qui
apparaîtrait dans ``/proc/<pid>/environ``. Jamais journalisée, jamais incluse
dans la sortie, jamais citée dans un message d'erreur.

**Cet outil ne génère aucune clé.** La paire Ed25519 est produite hors dépôt
et hors hôte par le propriétaire, et la clé privée n'entre jamais dans ce
dépôt. ``--show-public-key`` permet seulement de relire la clé publique d'une
graine existante, pour publier une ancre — jamais pour en fabriquer une.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "packages/contracts/src"))
sys.path.insert(0, str(REPO_ROOT / "packages/release-chain/src"))

from nexus_contracts.staging_readiness import (  # noqa: E402
    StagingReadinessError,
    StagingReadinessManifestV1,
    parse_staging_readiness_trust_anchor,
    sign_staging_readiness_manifest,
    staging_public_key_hex,
    verify_staging_readiness_manifest,
)

_IMAGE_REF = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")
_GIT_SHA1 = re.compile(r"^[0-9a-f]{40}$")


class SigningRefused(RuntimeError):
    """Refus de signature. Aucun fichier n'est écrit quand il est levé."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SigningRefused(message)


def _read_private_key(path: Path) -> str:
    """Lit la graine. Ne la journalise pas, ne la cite dans aucune erreur."""
    _require(path.is_file(), f"private key file {path} does not exist")
    seed = path.read_text(encoding="utf-8").strip()
    _require(
        re.fullmatch(r"[0-9a-f]{64}", seed) is not None,
        "the private key file must contain exactly 64 lowercase hex characters "
        "(an Ed25519 seed) and nothing else",
    )
    return seed


def _require_commit_exists(merge_sha: str) -> None:
    """Le commit signé doit exister ici — pas seulement ressembler à un SHA."""
    _require(
        _GIT_SHA1.fullmatch(merge_sha) is not None,
        f"merge_sha {merge_sha!r} must be 40 lowercase hex characters",
    )
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "-t", merge_sha],
        capture_output=True,
        text=True,
        check=False,
    )
    _require(
        result.returncode == 0 and result.stdout.strip() == "commit",
        f"merge_sha {merge_sha} is not a commit in this repository — a readiness "
        "manifest never names a revision that does not exist",
    )


def _require_public_checkout_matches_merge(merge_sha: str) -> None:
    """Refuser un signer public lancé depuis un autre commit ou un arbre modifié."""
    head = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    _require(
        head.returncode == 0 and head.stdout.strip() == merge_sha,
        "public successor signer HEAD differs from signed merge_sha",
    )
    tree = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD^{tree}"],
        capture_output=True, text=True, check=False,
    )
    signed_tree = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", f"{merge_sha}^{{tree}}"],
        capture_output=True, text=True, check=False,
    )
    _require(
        tree.returncode == signed_tree.returncode == 0
        and tree.stdout.strip() == signed_tree.stdout.strip(),
        "public successor signer tree differs from signed merge_sha",
    )
    tracked = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "status", "--porcelain=v1", "--untracked-files=no"],
        capture_output=True, text=True, check=False,
    )
    _require(
        tracked.returncode == 0 and not tracked.stdout.strip(),
        "public successor signer tracked tree is dirty",
    )
    from sign_production_readiness_manifest_cli import (  # noqa: PLC0415
        SigningToolError,
        _require_live_main_head,
    )

    try:
        _require_live_main_head(merge_sha)
    except SigningToolError as error:
        raise SigningRefused("public successor live main differs") from error


def _reject_output_aliasing_inputs(args: Any) -> None:
    """La readiness ne peut écraser ni clé ni preuve, même via hard link."""
    output = args.output
    _require(not output.is_symlink(), "output aliases a symlink")
    resolved = output.resolve(strict=False)
    for name, candidate in vars(args).items():
        if name == "output" or not isinstance(candidate, Path):
            continue
        target = candidate.resolve(strict=False)
        if candidate.is_dir() and resolved.is_relative_to(target):
            raise SigningRefused(f"output aliases input directory --{name.replace('_', '-')}")
        if resolved == target or (
            output.exists() and candidate.exists() and os.path.samefile(output, candidate)
        ):
            raise SigningRefused(f"output aliases --{name.replace('_', '-')}")


def _atomic_private_write(path: Path, raw: bytes) -> None:
    """Réutiliser l'écriture privée atomique du signer production."""
    from sign_production_readiness_manifest_cli import (  # noqa: PLC0415
        SigningToolError,
    )
    from sign_production_readiness_manifest_cli import (
        _atomic_private_write as production_atomic_write,
    )

    try:
        production_atomic_write(path, raw)
    except SigningToolError as error:
        raise SigningRefused("staging readiness atomic output refused") from error


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Signe un manifeste de readiness de répétition (staging)"
    )
    parser.add_argument("--repository", default="cyranoaladin/RAG")
    parser.add_argument(
        "--merge-sha",
        required=False,
        help="commit de main dont l'image worker a été construite",
    )
    parser.add_argument(
        "--worker-image",
        required=False,
        help="référence épinglée par digest : name@sha256:<64 hex>",
    )
    parser.add_argument("--allowed-release-id", required=False)
    parser.add_argument(
        "--release-manifest-file",
        type=Path,
        required=False,
        help="le manifeste de la release ; son sha256 est RECALCULÉ ici",
    )
    parser.add_argument("--key-id", required=False)
    parser.add_argument("--private-key-file", type=Path, required=False)
    parser.add_argument(
        "--trust-anchor-file",
        type=Path,
        required=False,
        help="ancre publique de répétition ; sert à revérifier avant écriture",
    )
    parser.add_argument(
        "--valid-days",
        type=int,
        default=30,
        help="durée de validité ; une autorisation de répétition expire",
    )
    parser.add_argument("--output", type=Path, required=False)
    parser.add_argument("--public-successor-phase", choices=("INGESTION", "PUBLICATION"))
    parser.add_argument("--public-successor-content-anchor-path", type=Path)
    parser.add_argument("--public-successor-preissuance-receipt-path", type=Path)
    parser.add_argument("--public-successor-private-cas-root", type=Path)
    parser.add_argument("--public-successor-repository-root", type=Path)
    parser.add_argument("--public-successor-bundle-root", type=Path)
    parser.add_argument("--public-successor-target-root", type=Path)
    parser.add_argument("--public-successor-target-pin-path", type=Path)
    parser.add_argument("--public-successor-target-pin-receipt-path", type=Path)
    parser.add_argument("--public-successor-target-pin-pull-request", type=int)
    parser.add_argument("--public-successor-observed-v1-receipt-path", type=Path)
    parser.add_argument("--public-successor-database-dsn-file", type=Path)
    parser.add_argument(
        "--show-public-key",
        type=Path,
        default=None,
        metavar="PRIVATE_KEY_FILE",
        help="affiche la clé PUBLIQUE d'une graine existante, et sort",
    )
    return parser


def _verify_public_successor_ingestion_replay(
    args: Any, release_digest: str, issued_at: datetime,
) -> tuple[str, str, datetime]:
    """Rejouer #300/#312/CAS à l'instant même où la clé va être lue."""
    required = (
        args.public_successor_content_anchor_path,
        args.public_successor_preissuance_receipt_path,
        args.public_successor_private_cas_root,
        args.public_successor_repository_root,
    )
    _require(all(value is not None for value in required),
             "public successor preissuance inputs incomplete")
    _require(
        args.public_successor_repository_root.resolve() == REPO_ROOT.resolve(),
        "public successor preissuance repository differs from signer checkout",
    )
    sys.path.insert(0, str(REPO_ROOT / "scripts/go_live"))
    from check_public_successor_preissuance import (  # noqa: PLC0415
        PreissuanceError,
        verify_preissuance_authority,
    )

    try:
        anchor_sha = hashlib.sha256(
            args.public_successor_content_anchor_path.read_bytes()
        ).hexdigest()
        receipt_sha = hashlib.sha256(
            args.public_successor_preissuance_receipt_path.read_bytes()
        ).hexdigest()
        verdict = verify_preissuance_authority(
            args.public_successor_content_anchor_path, anchor_sha, release_digest,
            args.public_successor_preissuance_receipt_path, receipt_sha,
            args.public_successor_repository_root, args.public_successor_private_cas_root,
            issued_at,
        )
    except (OSError, PreissuanceError) as error:
        raise SigningRefused("public successor preissuance replay failed") from error
    _require(
        verdict.preissuance_verified is True
        and verdict.publication_authorized is False
        and verdict.content_anchor_sha256 == anchor_sha
        and verdict.content_manifest_sha256 == release_digest
        and issued_at < verdict.expires_at_utc,
        "public successor preissuance replay incomplete",
    )
    return anchor_sha, receipt_sha, verdict.expires_at_utc


def _verify_public_successor_publication_replay(
    args: Any, release_digest: str, issued_at: datetime,
) -> tuple[str, str, str, datetime]:
    """Rejouer C et les preuves live avant la lecture de la clé staging."""
    required = (
        args.public_successor_bundle_root,
        args.public_successor_content_anchor_path,
        args.public_successor_preissuance_receipt_path,
        args.public_successor_private_cas_root,
        args.public_successor_repository_root,
        args.public_successor_target_root,
        args.public_successor_target_pin_path,
        args.public_successor_target_pin_receipt_path,
        args.public_successor_target_pin_pull_request,
        args.public_successor_observed_v1_receipt_path,
        args.public_successor_database_dsn_file,
    )
    _require(all(value is not None for value in required),
             "public successor PUBLICATION replay inputs incomplete")
    try:
        from public_successor_signing_replay import (  # noqa: PLC0415
            PublicationSigningInputs,
            replay_public_successor_publication,
        )

        dsn_file = args.public_successor_database_dsn_file
        _require(not dsn_file.is_symlink() and dsn_file.is_file(),
                 "public successor DB target file unavailable")
        verdict = replay_public_successor_publication(
            PublicationSigningInputs(
                bundle_root=args.public_successor_bundle_root,
                repository_root=args.public_successor_repository_root,
                content_anchor_path=args.public_successor_content_anchor_path,
                preissuance_receipt_path=args.public_successor_preissuance_receipt_path,
                private_cas_root=args.public_successor_private_cas_root,
                target_root=args.public_successor_target_root,
                target_pin_path=args.public_successor_target_pin_path,
                target_pin_receipt_path=args.public_successor_target_pin_receipt_path,
                target_pin_pull_request=args.public_successor_target_pin_pull_request,
                observed_v1_receipt_path=args.public_successor_observed_v1_receipt_path,
                database_dsn=dsn_file.read_text(encoding="utf-8").strip(),
            ),
            expected_release_id=args.allowed_release_id,
            expected_manifest_sha256=release_digest,
            now_utc=issued_at,
        )
    except Exception as error:  # noqa: BLE001 - frontière de signature fail-closed
        raise SigningRefused("public successor PUBLICATION authority replay failed") from error
    return (
        verdict.activation.content_anchor_sha256,
        verdict.activation.authority_envelope_sha256,
        verdict.target_pin_sha256,
        verdict.expires_at_utc,
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    if args.show_public_key is not None:
        try:
            seed = _read_private_key(args.show_public_key)
            print(staging_public_key_hex(seed))
        except (SigningRefused, StagingReadinessError) as exc:
            print(f"STAGING_READINESS_SIGNING_REFUSED: {exc}", file=sys.stderr)
            return 1
        return 0

    required = {
        "--merge-sha": args.merge_sha,
        "--worker-image": args.worker_image,
        "--allowed-release-id": args.allowed_release_id,
        "--release-manifest-file": args.release_manifest_file,
        "--key-id": args.key_id,
        "--private-key-file": args.private_key_file,
        "--trust-anchor-file": args.trust_anchor_file,
        "--output": args.output,
    }
    missing = sorted(name for name, value in required.items() if value is None)
    if missing:
        print(
            f"STAGING_READINESS_SIGNING_REFUSED: missing required arguments {missing}",
            file=sys.stderr,
        )
        return 1

    try:
        _reject_output_aliasing_inputs(args)
        _require(
            _IMAGE_REF.fullmatch(args.worker_image) is not None,
            f"worker image {args.worker_image!r} must be pinned as "
            "name@sha256:<64 hex> — a mutable tag is never an execution unit",
        )
        _require_commit_exists(args.merge_sha)
        _require(
            args.release_manifest_file.is_file(),
            f"release manifest {args.release_manifest_file} does not exist",
        )
        _require(args.valid_days > 0, "--valid-days must be strictly positive")

        # Recalculé, jamais saisi.
        release_digest = hashlib.sha256(
            args.release_manifest_file.read_bytes()
        ).hexdigest()

        issued_at = datetime.now(UTC)
        phase = args.public_successor_phase
        public_options = (
            args.public_successor_content_anchor_path,
            args.public_successor_preissuance_receipt_path,
            args.public_successor_private_cas_root,
            args.public_successor_repository_root,
            args.public_successor_bundle_root,
            args.public_successor_target_root,
            args.public_successor_target_pin_path,
            args.public_successor_target_pin_receipt_path,
            args.public_successor_target_pin_pull_request,
            args.public_successor_observed_v1_receipt_path,
            args.public_successor_database_dsn_file,
        )
        if phase is None:
            _require(all(value is None for value in public_options),
                     "public successor inputs require an explicit phase")
            anchor_sha = phase_authority_sha = target_pin_sha = None
            expires_at = issued_at + timedelta(days=args.valid_days)
        elif phase == "INGESTION":
            _require(all(value is None for value in public_options[4:]),
                     "PUBLICATION replay inputs are not INGESTION inputs")
            _require_public_checkout_matches_merge(args.merge_sha)
            anchor_sha, phase_authority_sha, evidence_expiry = (
                _verify_public_successor_ingestion_replay(
                    args, release_digest, issued_at,
                )
            )
            target_pin_sha = None
            expires_at = min(issued_at + timedelta(days=args.valid_days), evidence_expiry)
        else:
            _require_public_checkout_matches_merge(args.merge_sha)
            anchor_sha, phase_authority_sha, target_pin_sha, evidence_expiry = (
                _verify_public_successor_publication_replay(
                    args, release_digest, issued_at,
                )
            )
            expires_at = min(issued_at + timedelta(days=args.valid_days), evidence_expiry)
        manifest = StagingReadinessManifestV1(
            protocol_version="NEXUS-STAGING-READINESS-V1",
            environment="rehearsal",
            repository=args.repository,
            merge_sha=args.merge_sha,
            worker_image=args.worker_image,
            allowed_release_id=args.allowed_release_id,
            allowed_release_manifest_sha256=release_digest,
            control_dsn_differs_from_product=True,
            key_id=args.key_id,
            issued_at=issued_at,
            expires_at=expires_at,
            public_successor_phase=phase,
            public_successor_content_anchor_digest=anchor_sha,
            public_successor_phase_authority_digest=phase_authority_sha,
            public_successor_target_pin_digest=target_pin_sha,
        )

        if phase is not None:
            _require_public_checkout_matches_merge(args.merge_sha)
            _require(datetime.now(UTC) < expires_at,
                     "public successor authority expired before key access")
        if phase == "PUBLICATION":
            if anchor_sha is None or target_pin_sha is None:
                raise SigningRefused("public successor A or target pin absent before key")
            from public_successor_signing_replay import (  # noqa: PLC0415
                PublicationSigningInputs,
                recheck_publication_pin_before_key,
            )

            dsn_file = args.public_successor_database_dsn_file
            _require(isinstance(dsn_file, Path) and not dsn_file.is_symlink() and dsn_file.is_file(),
                     "public successor DB target file unavailable before key")
            try:
                recheck_publication_pin_before_key(
                    PublicationSigningInputs(
                        bundle_root=args.public_successor_bundle_root,
                        repository_root=args.public_successor_repository_root,
                        content_anchor_path=args.public_successor_content_anchor_path,
                        preissuance_receipt_path=args.public_successor_preissuance_receipt_path,
                        private_cas_root=args.public_successor_private_cas_root,
                        target_root=args.public_successor_target_root,
                        target_pin_path=args.public_successor_target_pin_path,
                        target_pin_receipt_path=args.public_successor_target_pin_receipt_path,
                        target_pin_pull_request=args.public_successor_target_pin_pull_request,
                        observed_v1_receipt_path=args.public_successor_observed_v1_receipt_path,
                        database_dsn=dsn_file.read_text(encoding="utf-8").strip(),
                    ),
                    expected_content_anchor_sha256=anchor_sha,
                    expected_pin_sha256=target_pin_sha,
                    evidence_expires_at_utc=expires_at,
                    now_utc=datetime.now(UTC),
                )
            except Exception as error:  # noqa: BLE001 - frontière de signature
                raise SigningRefused("public successor target pin changed before key") from error
        seed = _read_private_key(args.private_key_file)
        signed = sign_staging_readiness_manifest(
            manifest, private_key_hex=seed, key_id=args.key_id
        )
        del seed

        # Revérification avant écriture : un manifeste qui ne se vérifie pas
        # lui-même ne doit jamais atteindre le disque.
        anchor = parse_staging_readiness_trust_anchor(
            args.trust_anchor_file.read_bytes()
        )
        raw = signed.canonical_bytes()
        verify_staging_readiness_manifest(raw, trust_anchor=anchor, now=issued_at)
        _atomic_private_write(args.output, raw)
    except (SigningRefused, StagingReadinessError, ValueError, OSError) as exc:
        print(f"STAGING_READINESS_SIGNING_REFUSED: {exc}", file=sys.stderr)
        return 1

    print(
        "STAGING_READINESS_SIGNED "
        f"output={args.output} "
        f"manifest_sha256={hashlib.sha256(raw).hexdigest()} "
        f"key_id={args.key_id} "
        f"expires_at={manifest.expires_at.isoformat()}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["SigningRefused", "main"]
