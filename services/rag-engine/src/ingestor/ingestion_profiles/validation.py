"""Moteur de validation déterministe scope/profil (LOT44c).

Fonction pure : sans accès réseau, sans téléchargement, sans horloge, sans
état global mutable. À entrée identique (scope brut, registre, collection,
profile_version), le résultat est toujours identique.

Réutilise ``ResourceScope`` et ``CollectionProfile`` (LOT44a, non modifiés).
Ne réutilise ni ne redéfinit la machine d'état ``ResourceState`` : ce module
ne produit ni ne consomme d'état de ressource, ne déclenche aucune
transition — seul un futur appelant explicite peut relier un résultat de
validation à ``cas_transition`` (LOT44b), jamais ce module lui-même.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from nexus_contracts.ingestion import CollectionProfile, ResourceScope
from pydantic import ValidationError

from .registry import (
    ProfileDisabledError,
    ProfileKey,
    ProfileUnknownError,
    profile_fingerprint,
    select_profile,
)

#: Ordre canonique des dix dimensions de ResourceScope (LOT44a) — c'est
#: aussi l'ordre de déclaration des champs du modèle, jamais réordonné.
SCOPE_DIMENSIONS: tuple[str, ...] = (
    "tenant",
    "collection",
    "niveau",
    "voie",
    "matiere",
    "candidat",
    "audience",
    "visibility",
    "school_year",
    "programme_version",
)

#: Statuts effectivement produits par ce moteur. "review_required" (concept
#: existant : ResourceState.NEEDS_REVIEW) n'est volontairement pas inclus :
#: cette comparaison structurelle scope/profil n'a pas de zone grise — soit
#: le scope correspond exactement au profil, soit non. Documenté dans le
#: rapport de lot plutôt qu'ajouté sans cas d'usage réel.
ValidationStatus = Literal[
    "passed",
    "failed",
    "profile_unknown",
    "profile_disabled",
    "incomplete_input",
    "technical_error",
]


@dataclass(frozen=True)
class ValidationIssue:
    """Une non-conformité structurée — jamais seulement un texte libre."""

    code: str
    path: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    """Résultat typé et traçable : statut, motifs, profil référencé.

    ``profile_fingerprint`` : empreinte SHA-256 déterministe du contenu du
    profil réellement sélectionné (``None`` si aucun profil n'a pu être
    résolu — ``profile_unknown``, ``profile_disabled``, ou un
    ``technical_error`` survenu avant sélection). Distincte de l'identité
    ``(collection, profile_version)`` : permet à un futur appelant (LOT44d+)
    de détecter, en comparant deux résultats persistés de même identité, une
    modification silencieuse du contenu d'un profil déjà utilisé — cette
    détection n'est PAS effectuée par ce module lui-même (fonction pure,
    sans historique), cf. ADR-0026.
    """

    status: ValidationStatus
    issues: tuple[ValidationIssue, ...]
    collection: str
    profile_version: str
    profile_fingerprint: str | None = None


def _scope_error_code(error: Mapping[str, object]) -> str:
    error_type = str(error.get("type", ""))
    if error_type == "missing":
        return "SCOPE_FIELD_MISSING"
    if error_type in {"string_too_short", "too_short"}:
        return "SCOPE_FIELD_EMPTY"
    return "SCOPE_FIELD_INVALID"


def _issue_path(error: Mapping[str, object]) -> str:
    loc = error.get("loc", ())
    if isinstance(loc, list | tuple) and loc:
        return ".".join(str(part) for part in loc)
    return "scope"


def _validate_scope_against_profile(
    *,
    raw_scope: Mapping[str, object],
    registry: Mapping[ProfileKey, CollectionProfile],
    collection: str,
    profile_version: str,
) -> ValidationResult:
    try:
        profile = select_profile(registry, collection=collection, profile_version=profile_version)
    except ProfileUnknownError as exc:
        return ValidationResult(
            status="profile_unknown",
            issues=(ValidationIssue(code="PROFILE_UNKNOWN", path="profile", message=str(exc)),),
            collection=collection,
            profile_version=profile_version,
        )
    except ProfileDisabledError as exc:
        return ValidationResult(
            status="profile_disabled",
            issues=(ValidationIssue(code="PROFILE_DISABLED", path="profile", message=str(exc)),),
            collection=collection,
            profile_version=profile_version,
        )

    fingerprint = profile_fingerprint(profile)

    try:
        scope = ResourceScope.model_validate(raw_scope)
    except ValidationError as exc:
        issues = tuple(
            ValidationIssue(
                code=_scope_error_code(cast_error),
                path=_issue_path(cast_error),
                message=str(cast_error.get("msg", "invalid scope field")),
            )
            for cast_error in exc.errors()
        )
        return ValidationResult(
            status="incomplete_input",
            issues=issues,
            collection=collection,
            profile_version=profile_version,
            profile_fingerprint=fingerprint,
        )

    mismatches = tuple(
        ValidationIssue(
            code="SCOPE_DIMENSION_MISMATCH",
            path=dimension,
            message=(
                f"profile expects {getattr(profile.scope, dimension)!r}, "
                f"got {getattr(scope, dimension)!r}"
            ),
        )
        for dimension in SCOPE_DIMENSIONS
        if getattr(scope, dimension) != getattr(profile.scope, dimension)
    )
    if mismatches:
        return ValidationResult(
            status="failed",
            issues=mismatches,
            collection=collection,
            profile_version=profile_version,
            profile_fingerprint=fingerprint,
        )

    return ValidationResult(
        status="passed",
        issues=(),
        collection=collection,
        profile_version=profile_version,
        profile_fingerprint=fingerprint,
    )


def validate_scope_against_profile(
    *,
    raw_scope: Mapping[str, object],
    registry: Mapping[ProfileKey, CollectionProfile],
    collection: str,
    profile_version: str,
) -> ValidationResult:
    """Point d'entrée public — jamais d'exception non gérée : toute erreur
    inattendue est convertie en ``technical_error`` plutôt que de se
    propager, pour rester une primitive fail-closed et prévisible."""
    try:
        return _validate_scope_against_profile(
            raw_scope=raw_scope,
            registry=registry,
            collection=collection,
            profile_version=profile_version,
        )
    except Exception as exc:  # noqa: BLE001 - frontière fail-closed volontaire
        return ValidationResult(
            status="technical_error",
            issues=(
                ValidationIssue(
                    code="VALIDATION_ENGINE_ERROR",
                    path="engine",
                    message=str(exc),
                ),
            ),
            collection=collection,
            profile_version=profile_version,
        )


__all__ = [
    "SCOPE_DIMENSIONS",
    "ValidationIssue",
    "ValidationResult",
    "ValidationStatus",
    "validate_scope_against_profile",
]
