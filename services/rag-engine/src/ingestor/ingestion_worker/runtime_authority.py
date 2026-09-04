"""Bootstrap commun fail-closed des workers publiables Wave 0."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
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
    pii_review_index_path: Path | None = None
    pii_review_index_sha256: str | None = None
    pii_review_reviewers_path: Path | None = None
    pii_review_reviewers_sha256: str | None = None
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
    ("pii-review-index", "index of the review bundles that founded the decisions"),
    ("pii-review-reviewers", "versioned trusted reviewer allowlist (NEXUS-TRUSTED-REVIEW-V1)"),
)

#: Protocole et dépôt attendus de l'allowlist versionnée. Ce sont ceux que le
#: reste de la chaîne d'autorité GitHub lit déjà dans le même fichier ; les
#: redéfinir autrement ferait accepter ici une allowlist qu'elle refuse.
_TRUSTED_REVIEW_PROTOCOL = "NEXUS-TRUSTED-REVIEW-V1"
_TRUSTED_REVIEW_REPOSITORY = "cyranoaladin/RAG"


def add_review_authority_arguments(parser: argparse.ArgumentParser) -> None:
    for name, description in _REVIEW_AUTHORITY_ARGUMENTS:
        parser.add_argument(f"--{name}-path", type=Path, default=None, help=description)
        parser.add_argument(
            f"--{name}-sha256", default=None, help=f"expected SHA-256: {description}"
        )


def load_trusted_reviewers(path: Path, expected_sha256: str) -> tuple[str, ...]:
    """Lit l'allowlist versionnée des reviewers, épinglée par son empreinte.

    **Pourquoi ce n'est plus une liste passée en ligne de commande.** Un
    `--pii-review-reviewer <login>` faisait confiance à n'importe quel compte
    que l'appelant nommait : celui qui lance le worker choisissait qui a le
    droit d'approuver une admission de PII. L'allowlist est un artefact
    VERSIONNÉ — `scripts/github/trusted-reviewers.json` — que le reste de la
    chaîne d'autorité GitHub lit déjà. Elle est ici injectée comme les autres
    autorités : un chemin, et l'empreinte qui le fige."""
    if not path.is_file():
        raise ValueError(f"trusted reviewer allowlist is missing: {path}")
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise ValueError(
            f"trusted reviewer allowlist at {path.name} hashes to {actual}, not the "
            f"expected {expected_sha256} — this is not the allowlist that was approved"
        )
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"trusted reviewer allowlist is not readable: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("trusted reviewer allowlist must be a JSON object")
    if document.get("protocol") != _TRUSTED_REVIEW_PROTOCOL:
        raise ValueError(
            f"trusted reviewer allowlist declares protocol {document.get('protocol')!r}, "
            f"not {_TRUSTED_REVIEW_PROTOCOL!r}"
        )
    if document.get("repository") != _TRUSTED_REVIEW_REPOSITORY:
        raise ValueError(
            f"trusted reviewer allowlist covers repository "
            f"{document.get('repository')!r}, not {_TRUSTED_REVIEW_REPOSITORY!r} — "
            "an allowlist for another repository names nobody here"
        )
    reviewers = document.get("reviewers")
    if not isinstance(reviewers, list) or not reviewers:
        raise ValueError("trusted reviewer allowlist declares no reviewer")
    if any(not isinstance(login, str) or not login for login in reviewers):
        raise ValueError("trusted reviewer allowlist contains a non-login entry")
    if len(set(reviewers)) != len(reviewers):
        raise ValueError("trusted reviewer allowlist contains duplicates")
    return tuple(reviewers)


def review_authority_arguments_from_args(args: argparse.Namespace) -> dict[str, object]:
    """Rend les entrées d'autorité de revue, ou refuse un couple incomplet.

    Un chemin sans son empreinte faisait sauter la vérification de digest et
    acceptait une chaîne d'autorité non épinglée. Les deux vont ensemble, ou
    aucun des deux : une moitié de couple n'est pas une demi-garantie, c'est
    aucune."""
    resolved: dict[str, object] = {}
    for name, _description in _REVIEW_AUTHORITY_ARGUMENTS:
        field = name.replace("-", "_")
        path = getattr(args, f"{field}_path", None)
        digest = getattr(args, f"{field}_sha256", None)
        if path is not None and not digest:
            raise ValueError(
                f"--{name}-path was supplied without --{name}-sha256: an authority "
                "path without its expected digest is not pinned, and an unpinned "
                "authority is no authority"
            )
        if digest and path is None:
            raise ValueError(
                f"--{name}-sha256 was supplied without --{name}-path: there is "
                "nothing for that digest to pin"
            )
        resolved[f"{field}_path"] = path
        resolved[f"{field}_sha256"] = digest

    reviewers_path = resolved.get("pii_review_reviewers_path")
    reviewers_digest = resolved.get("pii_review_reviewers_sha256")
    resolved["pii_review_reviewers"] = (
        load_trusted_reviewers(reviewers_path, str(reviewers_digest))  # type: ignore[arg-type]
        if reviewers_path is not None
        else ()
    )
    return resolved


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


#: Les quatre empreintes que le manifeste de release et le runtime doivent
#: désigner à l'identique.
_REVIEW_CHAIN_FIELDS = (
    "pii_decision_set_sha256",
    "pii_review_receipt_sha256",
    "pii_review_trust_anchor_sha256",
    "pii_review_index_sha256",
)


def require_runtime_review_chain_matches_release(
    *, declared: Mapping[str, str | None], runtime: Mapping[str, str | None]
) -> None:
    """Confronte la chaîne de revue du manifeste à celle que le worker charge.

    Porter les deux ne prouve rien tant que personne ne les compare. Sans cette
    confrontation, une release peut annoncer la chaîne A pendant que le worker
    en vérifie une B — chacune valide de son côté, et aucune des deux ne
    couvrant ce que l'autre affirme.

    Les quatre champs sont comparés INDÉPENDAMMENT : une chaîne dont trois
    éléments concordent et dont le quatrième vient d'ailleurs n'est pas une
    chaîne aux trois quarts sûre."""
    divergent = [
        (
            field,
            declared.get(field),
            runtime.get(field),
        )
        for field in _REVIEW_CHAIN_FIELDS
        if declared.get(field) != runtime.get(field)
    ]
    if divergent:
        details = "; ".join(
            f"{field}: release declares {str(left)[:16]}…, runtime loaded {str(right)[:16]}…"
            for field, left, right in divergent
        )
        raise ValueError(
            "the review authority chain the release declares is not the one this "
            f"worker verifies ({details}) — a release that advertises one chain "
            "while another is checked proves nothing about either"
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
    # La chaîne de revue que la release déclare doit être exactement celle que
    # ce worker vient de charger et de vérifier.
    try:
        require_runtime_review_chain_matches_release(
            declared=resolver.release_review_chain,
            runtime={
                "pii_decision_set_sha256": inputs.pii_decision_set_sha256,
                "pii_review_receipt_sha256": inputs.pii_review_receipt_sha256,
                "pii_review_trust_anchor_sha256": inputs.review_trust_anchor_sha256,
                "pii_review_index_sha256": inputs.pii_review_index_sha256,
            },
        )
    except ValueError as exc:
        raise RuntimeAuthorityStartupError(str(exc)) from exc
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
