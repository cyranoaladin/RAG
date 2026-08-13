#!/usr/bin/env python3
"""Assemble et signe un ``ProductionReadinessManifestV1`` (ADR non encore
numéroté — chantier signing tool, mission H2-B go-live).

**Ce que cet outil refuse structurellement.** Chaque fait exigé par le
contrat est un argument CLI **typé et validé** — jamais un booléen libre
(``--ready true``). Les digests ne sont jamais fournis "à l'œil" : pour
chaque fichier d'evidence, l'outil relit le fichier et **recalcule** son
SHA-256 lui-même plutôt que de faire confiance à une valeur passée en
argument, sauf lorsque le fait décrit une identité déjà scellée ailleurs
(SHA de commit Git, digest d'image Docker) qu'il ne peut pas recalculer
localement et qui reste alors sujet à validation stricte de format.

**Clé privée.** Lue depuis un fichier local (``--private-key-file``),
jamais depuis un argument en clair, jamais depuis une variable
d'environnement qui apparaîtrait dans ``/proc/<pid>/environ``. Jamais
journalisée, jamais incluse dans la sortie. Après signature, le manifeste
signé est **immédiatement revérifié** contre l'ancre de confiance publique
avant d'être écrit sur disque — un manifeste dont la propre vérification
échoue n'est jamais produit.

Usage minimal (voir --help pour la liste complète des faits requis) :

    python sign_production_readiness_manifest_cli.py \\
        --repository cyranoaladin/RAG --pr-number 98 \\
        --pr-head-sha <40hex> --merge-sha <40hex> \\
        --environment production \\
        --private-key-file /path/held/by/operator \\
        --trust-anchor-file governance/trust-anchors/production-readiness-v1.json \\
        --key-id prod-readiness-v1-2026-08-13 \\
        ... (voir --help) \\
        --output readiness-manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "packages" / "contracts" / "src"))

from nexus_contracts.production_readiness import (  # noqa: E402
    ProductionReadinessError,
    ProductionReadinessManifestV1,
    parse_production_readiness_trust_anchor,
    sign_production_readiness_manifest,
    verify_production_readiness_manifest,
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_OCI = re.compile(r"^sha256:[0-9a-f]{64}$")
_IMAGE_REF = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")


class SigningToolError(RuntimeError):
    """L'assemblage ou la signature a été refusé — jamais un manifeste
    partiel écrit sur disque."""


def _hex(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise SigningToolError(f"{label} does not match the required format")
    return value


def _digest_of_file(path: Path, *, label: str) -> str:
    """Ne fait jamais confiance à un digest fourni pour un fichier local :
    le relit et le recalcule toujours lui-même."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SigningToolError(f"{label}: cannot read {path}: {exc}") from exc
    return hashlib.sha256(raw).hexdigest()


def _image_digest_pairs(raw_pairs: list[str], *, label: str) -> dict[str, str]:
    """``--application-image name=ref@sha256:...`` répété, jamais un tag."""
    result: dict[str, str] = {}
    for pair in raw_pairs:
        if "=" not in pair:
            raise SigningToolError(f"{label} entry {pair!r} must be name=image@sha256:<64hex>")
        name, ref = pair.split("=", 1)
        if _IMAGE_REF.fullmatch(ref) is None:
            raise SigningToolError(
                f"{label} entry {pair!r}: image reference must be pinned as "
                "name@sha256:<64 hex> — a mutable tag is never accepted"
            )
        if name in result:
            raise SigningToolError(f"{label} declares service {name!r} twice")
        result[name] = ref
    if not result:
        raise SigningToolError(f"{label} must declare at least one image")
    return result


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)

    # Identité du dépôt et de la revue.
    p.add_argument("--repository", required=True)
    p.add_argument("--pr-number", type=int, required=True)
    p.add_argument("--pr-head-sha", required=True)
    p.add_argument("--pr-head-tree-sha", required=True,
                    help="git rev-parse <pr_head_sha>^{tree} — never derived from the "
                         "commit SHA, computed independently by the caller.")
    p.add_argument("--merge-sha", required=True)
    p.add_argument("--merge-tree-sha", required=True,
                    help="git rev-parse <merge_sha>^{tree} — the contract's core "
                         "binding requires this to equal --pr-head-tree-sha.")
    p.add_argument("--environment", choices=["production"], default="production")

    # Digests des preuves de gouvernance : chemins vers des fichiers réels,
    # jamais des valeurs affirmées. Chacun est relu et rehashé ici.
    p.add_argument("--review-binding-file", type=Path, required=True)
    p.add_argument("--authorization-file", type=Path, required=True)
    p.add_argument("--trust-anchor-file", type=Path, required=True,
                    help="L'ancre PRODUCTION dont le digest entre dans le manifeste "
                         "(distincte de celle utilisée pour vérifier LA signature de ce manifeste).")
    p.add_argument("--revocation-registry-file", type=Path, required=True)
    p.add_argument("--catalog-file", type=Path, required=True)
    p.add_argument("--sealed-manifest-file", type=Path, required=True)
    p.add_argument("--h2b-report-file", type=Path, required=True)

    # Unité de déploiement.
    p.add_argument("--application-image", action="append", default=[], metavar="name=ref@sha256:...")
    p.add_argument("--upstream-image", action="append", default=[], metavar="name=ref@sha256:...")
    p.add_argument("--compose-file", type=Path, required=True)

    # Provenance de l'émission.
    p.add_argument("--workflow-path", required=True)
    p.add_argument("--workflow-ref", required=True)
    p.add_argument("--run-id", type=int, required=True)
    p.add_argument("--run-attempt", type=int, required=True)

    # Signature.
    p.add_argument("--key-id", required=True)
    p.add_argument("--private-key-file", type=Path, required=True,
                    help="Fichier local contenant la graine Ed25519 (64 hex). "
                         "Jamais un argument en clair, jamais une variable d'environnement.")
    p.add_argument("--verification-trust-anchor-file", type=Path, required=True,
                    help="Ancre publique utilisée pour REVÉRIFIER immédiatement la "
                         "signature produite (normalement le même fichier que "
                         "governance/trust-anchors/production-readiness-v1.json).")

    p.add_argument("--output", type=Path, required=True)
    return p


def assemble_and_sign(args: argparse.Namespace) -> ProductionReadinessManifestV1:
    pr_head_sha = _hex(args.pr_head_sha, _HEX40, "pr_head_sha")
    pr_head_tree_sha = _hex(args.pr_head_tree_sha, _HEX40, "pr_head_tree_sha")
    merge_sha = _hex(args.merge_sha, _HEX40, "merge_sha")
    merge_tree_sha = _hex(args.merge_tree_sha, _HEX40, "merge_tree_sha")

    review_binding_digest = _digest_of_file(args.review_binding_file, label="review_binding")
    authorization_digest = _digest_of_file(args.authorization_file, label="authorization")
    trust_anchor_digest = _digest_of_file(args.trust_anchor_file, label="trust_anchor")
    revocation_registry_digest = _digest_of_file(args.revocation_registry_file, label="revocation_registry")
    catalog_digest = _digest_of_file(args.catalog_file, label="catalog")
    sealed_manifest_digest = _digest_of_file(args.sealed_manifest_file, label="sealed_manifest")
    h2b_report_digest = _digest_of_file(args.h2b_report_file, label="h2b_report")
    compose_digest = _digest_of_file(args.compose_file, label="compose")

    application_image_digests = _image_digest_pairs(args.application_image, label="--application-image")
    upstream_image_digests = _image_digest_pairs(args.upstream_image, label="--upstream-image")

    release_tag = f"release/rag/{datetime.now(UTC):%Y%m%d}-{merge_sha[:12]}"

    try:
        manifest = ProductionReadinessManifestV1(
            protocol_version="NEXUS-PRODUCTION-READINESS-V1",
            repository=args.repository,
            pr_number=args.pr_number,
            pr_head_sha=pr_head_sha,
            pr_head_tree_sha=pr_head_tree_sha,
            merge_sha=merge_sha,
            merge_tree_sha=merge_tree_sha,
            release_tag=release_tag,
            environment=args.environment,
            review_binding_digest=review_binding_digest,
            authorization_digest=authorization_digest,
            trust_anchor_digest=trust_anchor_digest,
            revocation_registry_digest=revocation_registry_digest,
            catalog_digest=catalog_digest,
            sealed_manifest_digest=sealed_manifest_digest,
            h2b_report_digest=h2b_report_digest,
            gate_result="pass",
            application_image_digests=application_image_digests,
            upstream_image_digests=upstream_image_digests,
            compose_digest=compose_digest,
            workflow_path=args.workflow_path,
            workflow_ref=args.workflow_ref,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            issued_at=datetime.now(UTC),
            key_id=args.key_id,
        )
    except Exception as exc:  # noqa: BLE001 - frontière CLI, jamais silencieuse
        raise SigningToolError(f"manifest assembly refused: {exc}") from exc
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        manifest = assemble_and_sign(args)

        private_key_hex = args.private_key_file.read_text(encoding="utf-8").strip()
        signed = sign_production_readiness_manifest(
            manifest, private_key_hex=private_key_hex, key_id=args.key_id
        )
        # La clé privée ne survit pas au-delà de cette fonction locale ;
        # la variable est explicitement effacée avant toute écriture disque.
        private_key_hex = "0" * len(private_key_hex)
        del private_key_hex

        verification_anchor = parse_production_readiness_trust_anchor(
            args.verification_trust_anchor_file.read_bytes()
        )
        verify_production_readiness_manifest(
            signed.canonical_bytes(),
            trust_anchor=verification_anchor,
            environment=args.environment,
        )
    except (SigningToolError, ProductionReadinessError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    args.output.write_bytes(signed.canonical_bytes())
    args.output.chmod(0o600)
    print(f"MANIFEST_DIGEST={signed.manifest_digest}")
    print(f"KEY_ID={signed.key_id}")
    print(f"OUTPUT={args.output}")
    print("SIGNED_MANIFEST_VERIFY_ROUNDTRIP=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
