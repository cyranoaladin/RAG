"""Filtres de métadonnées de chunk — restrictifs, jamais autorisants.

Deux familles de dimensions coexistent et ne doivent jamais être confondues.

* Les **dix dimensions de placement** (`audience`, `candidat`, `collection`,
  `matiere`, `niveau`, `programme_version`, `school_year`, `tenant`,
  `visibility`, `voie`) font autorité sur l'ACCÈS. Elles vivent dans
  `rag_artifact_placements` et sont projetées par `ServerRetrievalScope`.
* Les dimensions **pédagogiques** (`notion`, `chapitre`, `type_document`)
  vivent sur les métadonnées de chunk (`nexus_contracts.chunk.ChunkMetadata`).
  Elles décrivent le contenu ; elles ne décident de rien.

D'où la règle que ce module rend structurelle : un filtre de métadonnée est
toujours **conjoint** au prédicat de placement. La sélection est

    AUTORISÉ_PAR_PLACEMENT **ET** CORRESPOND_AUX_MÉTADONNÉES

et jamais un OU. C'est pour cela que le fragment SQL produit ici ne peut
qu'ajouter des conditions : il n'ouvre aucune branche alternative, et un
filtre absent laisse le prédicat de placement décider seul.

Périmètre volontairement réduit à `notions`. `type_document` porte deux
valeurs concurrentes en base (`rag_artifacts.type_doc` fait autorité pour un
contenu gouverné, `rag_chunks.type_doc` pour l'historique) : le filtrer
demanderait de trancher cette autorité, ce qui n'appartient pas à ce lot.
`chapitre` et `difficulte` n'ont, eux, aucune colonne en base — les filtrer
reviendrait à annoncer une restriction que le SQL ne pourrait pas appliquer.
Ces trois dimensions restent donc refusées en amont, jamais ignorées en
silence.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

#: Borne de sécurité : une requête ne peut pas demander une liste de notions
#: arbitrairement longue, qui ferait dégénérer le plan d'exécution.
MAX_NOTIONS = 16

#: Longueur maximale d'une notion, alignée sur les slugs de taxonomie.
MAX_NOTION_LENGTH = 128


class ChunkMetadataFilterError(ValueError):
    """Filtre de métadonnée irrecevable — refusé, jamais tronqué."""


@dataclass(frozen=True)
class ChunkMetadataFilters:
    """Restrictions pédagogiques demandées par l'appelant.

    Immuable et normalisée : le SQL ne voit jamais une valeur que la
    validation n'a pas déjà acceptée.
    """

    notions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.notions) > MAX_NOTIONS:
            raise ChunkMetadataFilterError("too many notions requested")
        if len(set(self.notions)) != len(self.notions):
            raise ChunkMetadataFilterError("duplicate notion requested")
        for notion in self.notions:
            if not isinstance(notion, str) or not notion.strip():
                raise ChunkMetadataFilterError("invalid notion")
            if len(notion) > MAX_NOTION_LENGTH:
                raise ChunkMetadataFilterError("invalid notion")
            if notion != notion.strip():
                raise ChunkMetadataFilterError("invalid notion")

    @property
    def is_empty(self) -> bool:
        return not self.notions


def build_chunk_metadata_filters(notions: Iterable[str] | None) -> ChunkMetadataFilters:
    """Normaliser une demande contractuelle en filtre validé.

    L'ordre d'apparition est conservé et les doublons refusés : un filtre
    silencieusement réécrit ne serait plus celui que l'appelant a demandé.
    """
    if notions is None:
        return ChunkMetadataFilters()
    return ChunkMetadataFilters(notions=tuple(notions))


#: Fragment SQL conjoint. Il s'ajoute au prédicat de placement par un `AND`,
#: jamais par un `OR` : sur un filtre absent (`NULL`), il est neutre et
#: laisse l'autorité de placement décider seule ; sur un filtre présent, il
#: ne peut que retirer des lignes.
CHUNK_METADATA_FILTER_SQL = """
        (%s::text[] IS NULL OR chunk.notions && %s::text[])
"""


def chunk_metadata_filter_params(
    filters: ChunkMetadataFilters | None,
) -> tuple[object, ...]:
    """Paramètres de ``CHUNK_METADATA_FILTER_SQL``, dans son ordre exact."""
    notions = None if filters is None or not filters.notions else list(filters.notions)
    return (notions, notions)


__all__ = [
    "CHUNK_METADATA_FILTER_SQL",
    "MAX_NOTIONS",
    "MAX_NOTION_LENGTH",
    "ChunkMetadataFilterError",
    "ChunkMetadataFilters",
    "build_chunk_metadata_filters",
    "chunk_metadata_filter_params",
]
