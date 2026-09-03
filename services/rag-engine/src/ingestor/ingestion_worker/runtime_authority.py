"""Bootstrap commun fail-closed des workers publiables Wave 0."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from nexus_pdf_page_policy import CanonicalRuntimeError, require_canonical_pypdf

try:
    from ingestor.collection_config import load_collection_config
    from ingestor.ingestion_control.sealed_evidence import (
        VerifiedPIIEvidenceRegistry,
        VerifiedRightsEvidenceRegistry,
    )
    from ingestor.ingestion_profiles.registry import ProfileRegistry
    from ingestor.verified_pedagogical_placement import (
        VerifiedPedagogicalPlacementResolver,
    )
    from ingestor.wave0_release import require_file_digest
except ImportError as _exc:  # image worker aplatie
    if (_exc.name or "") not in ("ingestor", "src", "src.ingestor"):
        raise
    from collection_config import load_collection_config
    from ingestion_control.sealed_evidence import (
        VerifiedPIIEvidenceRegistry,
        VerifiedRightsEvidenceRegistry,
    )
    from ingestion_profiles.registry import ProfileRegistry
    from verified_pedagogical_placement import (
        VerifiedPedagogicalPlacementResolver,
    )
    from wave0_release import (
        require_file_digest,
    )


class RuntimeAuthorityStartupError(RuntimeError):
    """Le worker ne peut pas prouver ses autorités avant connexion."""


def require_canonical_worker_runtime() -> str:
    """Le worker extrait : il doit porter le runtime pypdf déclaré par la release.

    Une seule autorité (`nexus_pdf_page_policy.CANONICAL_PYPDF_VERSION`), la
    même que le verrou D-41 du producteur. Un autre runtime découperait d'autres
    chunks que ceux que la release attend : refus au démarrage, avant toute
    lecture de preuve et toute connexion."""
    try:
        return require_canonical_pypdf()
    except CanonicalRuntimeError as exc:
        raise RuntimeAuthorityStartupError(str(exc)) from exc


@dataclass(frozen=True)
class RuntimeAuthorityInputs:
    catalog_path: Path
    catalog_sha256: str
    candidate_inventory_path: Path
    candidate_inventory_sha256: str
    currentness_evidence_path: Path
    currentness_evidence_sha256: str
    mapping_path: Path
    mapping_sha256: str
    release_manifest_path: Path
    release_manifest_sha256: str
    programme_index_path: Path
    programme_index_sha256: str
    collection_config_path: Path
    collection_config_sha256: str
    pii_evidence_path: Path
    pii_evidence_sha256: str
    rights_evidence_path: Path
    rights_evidence_sha256: str
    corpus_manifest_sha256: str
    pii_decision_set_path: Path | None = None
    pii_decision_set_sha256: str | None = None
    pii_review_receipt_path: Path | None = None
    pii_review_receipt_sha256: str | None = None
    review_trust_anchor_path: Path | None = None
    review_trust_anchor_sha256: str | None = None
    pii_review_reviewers: tuple[str, ...] = ()


@dataclass(frozen=True)
class GovernedRuntimeAuthorities:
    placement_resolver: VerifiedPedagogicalPlacementResolver
    pii_evidence_registry: VerifiedPIIEvidenceRegistry
    rights_evidence_registry: VerifiedRightsEvidenceRegistry
    collection_config_sha256: str


_RUNTIME_FILE_ARGUMENTS = (
    ("catalog", "sealed H2-E catalog"),
    ("candidate-inventory", "exact-grade candidate inventory"),
    ("currentness-evidence", "artifact-bound currentness V2 evidence"),
    ("mapping", "closed external-to-Nexus mapping"),
    ("release-manifest", "aggregate Wave 0 release manifest"),
    ("programme-index", "canonical Troisième programme index"),
    ("collection-config", "Nexus collection catalogue or staging overlay"),
)


#: Autorité de revue PII (ADR-0047), injectée comme toute autre autorité :
#: des couples chemin/empreinte et une allowlist de reviewers. Optionnelle,
#: parce qu'une release sans contenu détecté n'a pas de décisions à joindre —
#: l'absence n'ouvre rien, le registre refuse toute admission non fondée.
_REVIEW_AUTHORITY_ARGUMENTS = (
    ("pii-decision-set", "sealed PII human review decision set"),
    ("pii-review-receipt", "ADR-0035 receipt sealing the decision set"),
    ("review-trust-anchor", "trust anchor verifying the review receipt"),
)


def add_review_authority_arguments(parser: argparse.ArgumentParser) -> None:
    for name, description in _REVIEW_AUTHORITY_ARGUMENTS:
        parser.add_argument(f"--{name}-path", type=Path, default=None, help=description)
        parser.add_argument(
            f"--{name}-sha256", default=None, help=f"expected SHA-256: {description}"
        )
    parser.add_argument(
        "--pii-review-reviewer",
        action="append",
        default=None,
        dest="pii_review_reviewers",
        help=(
            "GitHub login allowed to approve a PII review decision set. Repeatable. "
            "Absent means no review is accepted — never means any reviewer will do."
        ),
    )


def review_authority_arguments_from_args(args: argparse.Namespace) -> dict[str, object]:
    return {
        "pii_decision_set_path": args.pii_decision_set_path,
        "pii_decision_set_sha256": args.pii_decision_set_sha256,
        "pii_review_receipt_path": args.pii_review_receipt_path,
        "pii_review_receipt_sha256": args.pii_review_receipt_sha256,
        "review_trust_anchor_path": args.review_trust_anchor_path,
        "review_trust_anchor_sha256": args.review_trust_anchor_sha256,
        "pii_review_reviewers": tuple(args.pii_review_reviewers or ()),
    }


def add_runtime_authority_arguments(parser: argparse.ArgumentParser) -> None:
    for name, description in _RUNTIME_FILE_ARGUMENTS:
        parser.add_argument(
            f"--{name}-path", required=True, type=Path, help=description
        )
        parser.add_argument(
            f"--{name}-sha256", required=True, help=f"expected SHA-256: {description}"
        )
    add_review_authority_arguments(parser)


def runtime_authority_inputs_from_args(args: argparse.Namespace) -> RuntimeAuthorityInputs:
    return RuntimeAuthorityInputs(
        catalog_path=args.catalog_path,
        catalog_sha256=args.catalog_sha256,
        candidate_inventory_path=args.candidate_inventory_path,
        candidate_inventory_sha256=args.candidate_inventory_sha256,
        currentness_evidence_path=args.currentness_evidence_path,
        currentness_evidence_sha256=args.currentness_evidence_sha256,
        mapping_path=args.mapping_path,
        mapping_sha256=args.mapping_sha256,
        release_manifest_path=args.release_manifest_path,
        release_manifest_sha256=args.release_manifest_sha256,
        programme_index_path=args.programme_index_path,
        programme_index_sha256=args.programme_index_sha256,
        collection_config_path=args.collection_config_path,
        collection_config_sha256=args.collection_config_sha256,
        pii_evidence_path=args.pii_evidence_path,
        pii_evidence_sha256=args.pii_evidence_sha256,
        rights_evidence_path=args.rights_evidence_path,
        rights_evidence_sha256=args.rights_evidence_sha256,
        corpus_manifest_sha256=args.corpus_manifest_sha256,
        **review_authority_arguments_from_args(args),  # type: ignore[arg-type]
    )


def load_governed_runtime_authorities(
    inputs: RuntimeAuthorityInputs,
    *,
    profile_registry: ProfileRegistry,
    profile_manifest_digest: str,
) -> GovernedRuntimeAuthorities:
    """Charge toutes les preuves une fois, avant toute boucle ou connexion."""
    require_canonical_worker_runtime()
    try:
        collection_config_sha = require_file_digest(
            inputs.collection_config_path,
            inputs.collection_config_sha256,
            label="runtime collection config",
        )
        collection_config = load_collection_config(inputs.collection_config_path)
        resolver = VerifiedPedagogicalPlacementResolver.load(
            catalog_path=inputs.catalog_path,
            expected_catalog_sha256=inputs.catalog_sha256,
            candidate_inventory_path=inputs.candidate_inventory_path,
            expected_candidate_inventory_sha256=inputs.candidate_inventory_sha256,
            currentness_evidence_path=inputs.currentness_evidence_path,
            expected_currentness_evidence_sha256=inputs.currentness_evidence_sha256,
            mapping_path=inputs.mapping_path,
            expected_mapping_sha256=inputs.mapping_sha256,
            release_manifest_path=inputs.release_manifest_path,
            expected_release_manifest_sha256=inputs.release_manifest_sha256,
            expected_manifest_sha256=inputs.corpus_manifest_sha256,
            profile_registry=profile_registry,
            collection_config=collection_config,
            programme_index_path=inputs.programme_index_path,
            expected_programme_index_sha256=inputs.programme_index_sha256,
        )
        pii = VerifiedPIIEvidenceRegistry.load(
            inputs.pii_evidence_path,
            expected_evidence_sha256=inputs.pii_evidence_sha256,
            expected_corpus_manifest_sha256=inputs.corpus_manifest_sha256,
            decision_set_path=inputs.pii_decision_set_path,
            expected_decision_set_sha256=inputs.pii_decision_set_sha256,
            receipt_path=inputs.pii_review_receipt_path,
            expected_receipt_sha256=inputs.pii_review_receipt_sha256,
            trust_anchor_path=inputs.review_trust_anchor_path,
            expected_trust_anchor_sha256=inputs.review_trust_anchor_sha256,
            accepted_reviewers=inputs.pii_review_reviewers or None,
        )
        rights = VerifiedRightsEvidenceRegistry.load(
            inputs.rights_evidence_path,
            expected_registry_sha256=inputs.rights_evidence_sha256,
            expected_corpus_manifest_sha256=inputs.corpus_manifest_sha256,
        )
    except Exception as exc:
        raise RuntimeAuthorityStartupError(str(exc)) from exc

    if resolver.release_profile_manifest_digest != profile_manifest_digest:
        raise RuntimeAuthorityStartupError(
            "release profile manifest digest differs from the startup gate"
        )
    if resolver.release_pii_evidence_sha256 != pii.evidence_sha256:
        raise RuntimeAuthorityStartupError(
            "release PII evidence digest differs from the loaded registry"
        )
    if resolver.release_pii_policy_sha256 != pii.policy_sha256:
        raise RuntimeAuthorityStartupError(
            "release PII policy digest differs from the loaded registry"
        )
    if resolver.release_rights_registry_sha256 != rights.registry_sha256:
        raise RuntimeAuthorityStartupError(
            "release rights registry digest differs from the loaded registry"
        )
    return GovernedRuntimeAuthorities(
        placement_resolver=resolver,
        pii_evidence_registry=pii,
        rights_evidence_registry=rights,
        collection_config_sha256=collection_config_sha,
    )


__all__ = [
    "GovernedRuntimeAuthorities",
    "RuntimeAuthorityInputs",
    "RuntimeAuthorityStartupError",
    "add_runtime_authority_arguments",
    "load_governed_runtime_authorities",
    "runtime_authority_inputs_from_args",
]
