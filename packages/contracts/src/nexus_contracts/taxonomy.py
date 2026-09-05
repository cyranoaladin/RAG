"""Contrat partagé de la vue taxonomie servable (`GET /taxonomy/v2`).

Un `dict[str, Any]` publié dans OpenAPI est un objet sans forme : un
générateur de client ne peut y découvrir ni `version`, ni la structure d'une
collection, ni le type d'une valeur de dimension. L'agent extérieur devrait
alors deviner — c'est-à-dire coder contre une observation, pas contre un
contrat.

**Les dimensions décrites ici sont celles que le moteur peut réellement
rendre**, dérivées du scope serveur et du catalogue : `matiere`, `niveau`,
`voie`, `statut_enseignement`, `programme_version`, `school_year`. La
spécialité est portée par `statut_enseignement` (`specialite`,
`tronc_commun`, `option`), qui est la dimension réellement gouvernée.

`chapitre`, `notion` et `type_document` **ne figurent pas** : aucune
taxonomie fermée ne les borne côté moteur — `notion` est du texte libre
d'appelant, filtré mais jamais énuméré, et le type documentaire n'est pas une
dimension de collection. Les annoncer ici reviendrait à promettre une
énumération que rien ne peut produire.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nexus_contracts.document import Niveau, StatutEnseignement, Voie
from nexus_contracts.identity import BoundedSlug


class TaxonomyCollectionV2(BaseModel):
    """Une collection servable, telle que le scope serveur la dérive."""

    model_config = ConfigDict(extra="forbid")

    collection: BoundedSlug
    matiere: BoundedSlug
    niveau: Niveau
    voie: Voie
    statut_enseignement: StatutEnseignement
    programme_version: str = Field(min_length=1)
    school_year: str = Field(min_length=1)


class TaxonomyDimensionsV2(BaseModel):
    """Valeurs distinctes des dimensions, dans l'ordre d'apparition.

    L'ordre est un engagement : deux appels identiques rendent la même
    réponse, ce qu'un ensemble ne garantirait pas.
    """

    model_config = ConfigDict(extra="forbid")

    matiere: list[BoundedSlug] = Field(default_factory=list)
    niveau: list[Niveau] = Field(default_factory=list)
    voie: list[Voie] = Field(default_factory=list)
    statut_enseignement: list[StatutEnseignement] = Field(default_factory=list)
    programme_version: list[str] = Field(default_factory=list)
    school_year: list[str] = Field(default_factory=list)


class TaxonomyV2Response(BaseModel):
    """Réponse de `GET /taxonomy/v2` — les dimensions servables ET autorisées."""

    model_config = ConfigDict(extra="forbid")

    version: Literal[2] = 2
    collections: list[TaxonomyCollectionV2] = Field(default_factory=list)
    dimensions: TaxonomyDimensionsV2 = Field(default_factory=TaxonomyDimensionsV2)


__all__ = [
    "TaxonomyCollectionV2",
    "TaxonomyDimensionsV2",
    "TaxonomyV2Response",
]
