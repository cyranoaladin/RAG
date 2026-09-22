"""Bootstrap fail-closed des autorités de release multi-niveaux staging."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from ingestor.collection_config import load_collection_config
from ingestor.ingestion_control.sealed_evidence import (
    VerifiedPIIEvidenceRegistry,
    VerifiedRightsEvidenceRegistry,
)
from ingestor.ingestion_profiles.manifest import verify_profile_manifest
from ingestor.ingestion_profiles.registry import ProfileRegistry
from ingestor.multilevel_evidence import (
    load_multilevel_candidate_inventory,
    load_multilevel_currentness,
)
from ingestor.multilevel_mapping import load_multilevel_mapping
from ingestor.multilevel_verified_placement import (
    MultilevelVerifiedPedagogicalPlacementResolver,
    load_multilevel_release_eligibility,
    production_profile_manifest_verification,
)
from ingestor.programme_registry import load_programme_index_registry
from ingestor.staging_profile_manifest import verify_staging_profile_manifest
from ingestor.wave0_release import require_file_digest

from .runtime_authority import (
    GovernedRuntimeAuthorities,
    RuntimeAuthorityStartupError,
    add_review_authority_arguments,
    require_canonical_worker_runtime,
    require_runtime_review_chain_matches_release,
    review_authority_arguments_from_args,
)


@dataclass(frozen=True)
class MultilevelRuntimeAuthorityInputs:
    candidate_inventory_path: Path
    candidate_inventory_sha256: str
    currentness_evidence_path: Path
    currentness_evidence_sha256: str
    levels_mapping_path: Path
    levels_mapping_sha256: str
    subjects_mapping_path: Path
    subjects_mapping_sha256: str
    document_types_mapping_path: Path
    document_types_mapping_sha256: str
    release_manifest_path: Path
    release_manifest_sha256: str
    programme_registry_path: Path
    programme_registry_sha256: str
    profile_manifest_path: Path
    profile_manifest_sha256: str
    collection_config_path: Path
    collection_config_sha256: str
    pii_evidence_path: Path
    pii_evidence_sha256: str
    rights_evidence_path: Path
    rights_evidence_sha256: str
    corpus_manifest_sha256: str
    repository_root: Path
    #: Manifeste de transfert de la release SCELLÉE. Il établit l'invariant
    #: de format du catalogue, et il est transporté comme toute autre
    #: autorité : un chemin et l'empreinte attendue de ses octets. La chaîne
    #: d'autorités d'une release multi-niveaux est fermée et ne peut pas le
    #: déclarer ; l'inventer en devinant un fichier voisin laissait
    #: l'invariant NON ÉTABLI, donc toute lecture scellée refusée.
    artifact_transfer_manifest_path: Path | None = None
    artifact_transfer_manifest_sha256: str | None = None
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


_MULTILEVEL_RUNTIME_FILE_ARGUMENTS = (
    ("candidate-inventory", "sealed multi-level candidate inventory"),
    ("currentness-evidence", "artifact-bound multi-level currentness evidence"),
    ("levels-mapping", "closed external level mapping"),
    ("subjects-mapping", "closed external subject mapping"),
    ("document-types-mapping", "closed external document type mapping"),
    ("release-manifest", "aggregate multi-level release manifest"),
    ("programme-registry", "canonical multi-level programme registry"),
    ("profile-manifest", "sealed multi-level staging profile manifest"),
    ("collection-config", "canonical Nexus collection catalogue"),
    ("pii-evidence", "sealed targeted PII evidence"),
    ("rights-evidence", "sealed rights registry"),
)


def add_multilevel_runtime_authority_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    """Déclarer toutes les autorités nécessaires avant ouverture de PostgreSQL."""
    for name, description in _MULTILEVEL_RUNTIME_FILE_ARGUMENTS:
        parser.add_argument(
            f"--{name}-path",
            required=True,
            type=Path,
            help=description,
        )
        parser.add_argument(
            f"--{name}-sha256",
            required=True,
            help=f"expected SHA-256: {description}",
        )
    parser.add_argument("--corpus-manifest-sha256", required=True)
    parser.add_argument("--repository-root", required=True, type=Path)
    # Optionnel : une release multi-niveaux classique n'est pas scellée et
    # n'a pas de manifeste de transfert. Une release scellée en a un, et
    # sans lui son invariant de format reste non établi — ce qui vaut refus
    # à la lecture, jamais publication d'un format supposé.
    parser.add_argument(
        "--artifact-transfer-manifest-path",
        type=Path,
        default=None,
        help="sealed release artifact transfer manifest",
    )
    parser.add_argument(
        "--artifact-transfer-manifest-sha256",
        default=None,
        help="expected SHA-256: sealed release artifact transfer manifest",
    )
    add_review_authority_arguments(parser)


def multilevel_runtime_authority_inputs_from_args(
    args: argparse.Namespace,
) -> MultilevelRuntimeAuthorityInputs:
    """Construire l'entrée typée sans dériver ni deviner une autorité."""
    return MultilevelRuntimeAuthorityInputs(
        candidate_inventory_path=args.candidate_inventory_path,
        candidate_inventory_sha256=args.candidate_inventory_sha256,
        currentness_evidence_path=args.currentness_evidence_path,
        currentness_evidence_sha256=args.currentness_evidence_sha256,
        levels_mapping_path=args.levels_mapping_path,
        levels_mapping_sha256=args.levels_mapping_sha256,
        subjects_mapping_path=args.subjects_mapping_path,
        subjects_mapping_sha256=args.subjects_mapping_sha256,
        document_types_mapping_path=args.document_types_mapping_path,
        document_types_mapping_sha256=args.document_types_mapping_sha256,
        release_manifest_path=args.release_manifest_path,
        release_manifest_sha256=args.release_manifest_sha256,
        programme_registry_path=args.programme_registry_path,
        programme_registry_sha256=args.programme_registry_sha256,
        profile_manifest_path=args.profile_manifest_path,
        profile_manifest_sha256=args.profile_manifest_sha256,
        collection_config_path=args.collection_config_path,
        collection_config_sha256=args.collection_config_sha256,
        pii_evidence_path=args.pii_evidence_path,
        pii_evidence_sha256=args.pii_evidence_sha256,
        rights_evidence_path=args.rights_evidence_path,
        rights_evidence_sha256=args.rights_evidence_sha256,
        corpus_manifest_sha256=args.corpus_manifest_sha256,
        repository_root=args.repository_root,
        **_transfer_manifest_arguments_from_args(args),  # type: ignore[arg-type]
        **review_authority_arguments_from_args(args),  # type: ignore[arg-type]
    )


def _transfer_manifest_arguments_from_args(
    args: argparse.Namespace,
) -> dict[str, object]:
    """Le couple chemin/empreinte du manifeste de transfert, ou aucun.

    Une moitié de couple n'est pas une demi-garantie : un chemin sans son
    empreinte n'est pas épinglé, et une empreinte sans chemin n'épingle
    rien. Même règle que pour l'autorité de revue.
    """
    path = getattr(args, "artifact_transfer_manifest_path", None)
    digest = getattr(args, "artifact_transfer_manifest_sha256", None)
    if path is not None and not digest:
        raise RuntimeAuthorityStartupError(
            "--artifact-transfer-manifest-path was supplied without "
            "--artifact-transfer-manifest-sha256: an authority path without "
            "its expected digest is not pinned, and an unpinned authority is "
            "no authority"
        )
    if digest and path is None:
        raise RuntimeAuthorityStartupError(
            "--artifact-transfer-manifest-sha256 was supplied without "
            "--artifact-transfer-manifest-path: there is nothing for that "
            "digest to pin"
        )
    return {
        "artifact_transfer_manifest_path": path,
        "artifact_transfer_manifest_sha256": digest,
    }


def review_verification_environment(environment: str) -> str:
    """Traduit l'environnement de release en environnement de vérification ADR-0035.

    Une répétition et une production ne sont pas signées par la même clé : le
    contrat refuse explicitement qu'une clé de fixture valide un gate de
    production, et qu'une clé de production soit exercée par une répétition.

    **Ce mode ne retire aucune garde.** Signature Ed25519, liaison du challenge,
    empreintes du decision set, du reçu et de l'ancre, allowlist de reviewers et
    liaison au corpus restent tous vérifiés à l'identique. Seule change la clé
    recevable."""
    if environment == "production":
        return "production"
    if environment == "rehearsal":
        return "test"
    raise ValueError(
        f"environment {environment!r} is neither rehearsal nor production"
    )


def load_multilevel_runtime_authorities(
    inputs: MultilevelRuntimeAuthorityInputs,
    *,
    profile_registry: ProfileRegistry,
    environment: str,
) -> GovernedRuntimeAuthorities:
    """Construire une seule autorité cohérente avant toute connexion DB."""
    # Le worker extrait : il porte le runtime pypdf déclaré par la release
    # (une seule autorité, `nexus_pdf_page_policy.CANONICAL_PYPDF_VERSION`),
    # sinon il découperait d'autres chunks que ceux attendus. Refus AVANT toute
    # lecture de preuve.
    require_canonical_worker_runtime()
    try:
        collection_config_sha = require_file_digest(
            inputs.collection_config_path,
            inputs.collection_config_sha256,
            label="runtime collection config",
        )
        profile_manifest_sha = require_file_digest(
            inputs.profile_manifest_path,
            inputs.profile_manifest_sha256,
            label="multilevel staging profile manifest",
        )
        inventory = load_multilevel_candidate_inventory(
            inputs.candidate_inventory_path,
            expected_sha256=inputs.candidate_inventory_sha256,
        )
        currentness = load_multilevel_currentness(
            inputs.currentness_evidence_path,
            expected_sha256=inputs.currentness_evidence_sha256,
            candidate_inventory=inventory,
        )
        mapping = load_multilevel_mapping(
            levels_path=inputs.levels_mapping_path,
            expected_levels_sha256=inputs.levels_mapping_sha256,
            subjects_path=inputs.subjects_mapping_path,
            expected_subjects_sha256=inputs.subjects_mapping_sha256,
            document_types_path=inputs.document_types_mapping_path,
            expected_document_types_sha256=inputs.document_types_mapping_sha256,
        )
        programme = load_programme_index_registry(
            registry_path=inputs.programme_registry_path,
            expected_registry_sha256=inputs.programme_registry_sha256,
            repository_root=inputs.repository_root,
        )
        if environment == "production":
            profile_manifest = production_profile_manifest_verification(
                verify_profile_manifest(profile_registry, inputs.profile_manifest_path)
            )
        elif environment == "rehearsal":
            profile_manifest = verify_staging_profile_manifest(
                profile_registry, inputs.profile_manifest_path
            )
            if profile_manifest.manifest_sha256 != profile_manifest_sha:
                raise RuntimeAuthorityStartupError("profile manifest digest differs")
        else:
            raise RuntimeAuthorityStartupError(
                "multilevel authority environment must be rehearsal or production"
            )
        release = load_multilevel_release_eligibility(
            inputs.release_manifest_path,
            expected_sha256=inputs.release_manifest_sha256,
        )
        resolver = MultilevelVerifiedPedagogicalPlacementResolver.from_authorities(
            candidate_inventory=inventory,
            currentness=currentness,
            mapping=mapping,
            profiles=profile_registry,
            profile_manifest=profile_manifest,
            environment=environment,
            programme_registry=programme,
            collection_config=load_collection_config(inputs.collection_config_path),
            release_eligibility=release,
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
            # L'index et l'allowlist ne sont plus « portés » sans être lus :
            # les deux chargeurs les remettent au foyer, qui seul les ouvre,
            # les hache et les confronte.
            review_index_path=inputs.pii_review_index_path,
            expected_review_index_sha256=inputs.pii_review_index_sha256,
            repository_root=inputs.repository_root,
            expected_reviewers_sha256=inputs.pii_review_reviewers_sha256,
            environment=review_verification_environment(environment),
        )
        rights = VerifiedRightsEvidenceRegistry.load(
            inputs.rights_evidence_path,
            expected_registry_sha256=inputs.rights_evidence_sha256,
            expected_corpus_manifest_sha256=inputs.corpus_manifest_sha256,
        )
    except Exception as exc:
        if isinstance(exc, RuntimeAuthorityStartupError):
            raise
        raise RuntimeAuthorityStartupError(str(exc)) from exc

    if resolver.release_pii_evidence_sha256 != pii.evidence_sha256:
        raise RuntimeAuthorityStartupError("release PII evidence digest differs")
    if resolver.release_pii_policy_sha256 != pii.policy_sha256:
        raise RuntimeAuthorityStartupError("release PII policy digest differs")
    if resolver.release_rights_registry_sha256 != rights.registry_sha256:
        raise RuntimeAuthorityStartupError("release rights registry digest differs")
    # Le chemin multi-niveaux portait les mêmes autorités que le chemin simple
    # mais ne confrontait pas la chaîne de la release à celle qu'il vérifiait :
    # une release pouvait annoncer la chaîne A tandis que ce worker en validait
    # une B, chacune cohérente de son côté.
    try:
        require_runtime_review_chain_matches_release(
            declared=resolver.release_review_chain,
            runtime=pii.verified_review_chain(),
        )
    except ValueError as exc:
        raise RuntimeAuthorityStartupError(str(exc)) from exc
    # Le catalogue de la release SCELLEE, quand elle en porte un. Il est
    # charge par le chemin canonique — le fichier que le manifeste NOMME et
    # dont il DECLARE l'empreinte — jamais reconstruit ici.
    #
    # Une release multi-niveaux classique n'en a pas : l'absence n'est donc
    # pas une erreur de chargement. Elle devient un refus au moment de LIRE
    # un artefact scelle, ou le catalogue est indispensable.
    sealed_catalog = _charger_catalogue_scelle(inputs)

    return GovernedRuntimeAuthorities(
        placement_resolver=resolver,
        pii_evidence_registry=pii,
        rights_evidence_registry=rights,
        collection_config_sha256=collection_config_sha,
        sealed_release_catalog=sealed_catalog,
    )


def _charger_catalogue_scelle(
    inputs: MultilevelRuntimeAuthorityInputs,
) -> object | None:
    """Charge le catalogue scelle depuis le manifeste deja verifie.

    Le manifeste est celui que ``--release-manifest-path`` designe, son
    empreinte celle que ``--release-manifest-sha256`` attend, et la
    reference du catalogue vient du manifeste lui-meme.

    Le manifeste de TRANSFERT, lui, ne peut pas venir de la : la chaine
    d'autorites d'une release multi-niveaux est FERMEE et ne comporte aucun
    champ pour lui. Le deviner comme fichier voisin et lire son empreinte
    attendue dans un champ que le contrat interdit ne pouvait donc jamais
    reussir : l'invariant de format restait vide, et toute lecture scellee
    refusait. Il est desormais transporte comme les autres autorites, par
    son couple chemin/empreinte.

    Un manifeste qui ne nomme aucun catalogue d'artefacts n'est pas une
    release scellee : ``None``, et la branche scellee refusera plus tard.
    Un manifeste qui en nomme un mais dont le contenu ne correspond pas est
    en revanche une ERREUR — jamais un silence.
    """
    from ingestor.ingestion_control.sealed_release_catalog import (
        SealedReleaseCatalogError,
        load_sealed_release_catalog,
    )

    repertoire = inputs.release_manifest_path.parent
    if inputs.release_manifest_path.name != "production-profile-gate.release.json":
        return None
    try:
        manifeste = json.loads(inputs.release_manifest_path.read_bytes())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(manifeste.get("artifact_registry"), dict):
        return None
    try:
        return load_sealed_release_catalog(
            repertoire,
            expected_release_manifest_sha256=inputs.release_manifest_sha256,
            transfer_manifest_path=inputs.artifact_transfer_manifest_path,
            expected_transfer_manifest_sha256=inputs.artifact_transfer_manifest_sha256,
        )
    except SealedReleaseCatalogError as exc:
        raise RuntimeAuthorityStartupError(
            f"the release names an artifact catalogue that cannot be "
            f"established: {exc}"
        ) from exc


__all__ = [
    "MultilevelRuntimeAuthorityInputs",
    "add_multilevel_runtime_authority_arguments",
    "load_multilevel_runtime_authorities",
    "multilevel_runtime_authority_inputs_from_args",
]
