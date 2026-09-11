"""SERVABILITY_GATE — compose les autorités, n'en possède aucune.

La servabilité n'appartient à personne en particulier : elle est le produit de
plusieurs décisions prises ailleurs. Ce gate les compose et nomme, pour chaque
refus, l'autorité qui l'a prononcé. Sans ce nommage, un contenu refusé
donnerait un verdict sans adresse, et corriger la cause supposerait de deviner
laquelle des six dimensions a parlé.

Ce que le gate NE fait pas :

- il ne décide aucune dimension. S'il tranchait la PII, il y aurait deux
  endroits où la PII se décide, et un jour ils ne diraient plus la même chose ;
- il n'invente pas de dimension absente. Une dimension qu'on ne lui donne pas
  est une dimension qu'il ne peut pas composer, et il le refuse plutôt que de
  supposer qu'elle passe.

Le défaut que ce gate corrige : la matrice de servabilité calculait une
colonne d'actualité que son verdict ne consultait jamais. Quarante contenus
que la source déclare archivés ressortaient candidats servables, dont trois
étaient déjà dans la release promue. Une dimension calculée mais non consommée
est pire qu'une dimension absente : elle donne l'apparence d'un contrôle.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rag_pedago.governance.currentness_disposition import (
    NOT_CURRENT_DECLARED_BY_SOURCE,
    UNKNOWN,
)

GATE = "SERVABILITY_GATE"

CANDIDATE = "CANDIDATE"
BLOCKED = "BLOCKED"

#: Les autorités composées, dans l'ordre où elles sont interrogées.
AUTORITE_PII = "PII_GATE"
AUTORITE_ACTUALITE = "CURRENTNESS_GATE"
AUTORITE_PROGRAMME = "PROGRAM_GATE"
AUTORITE_ROLE = "ROLE_GATE"
AUTORITE_PROVENANCE = "PROVENANCE_GATE"
AUTORITE_DROITS = "RIGHTS_GATE"
AUTORITE_CLASSIFICATION = "CLASSIFICATION_GATE"
AUTORITE_PLACEMENT = "PLACEMENT_GATE"

#: Dispositions PII qui interdisent de servir. « Non évaluable » bloque autant
#: que « rejeté » : ne pas savoir n'est pas une autorisation.
PII_BLOQUANTES = frozenset({"NOT_ASSESSABLE", "REJECTED", "PII_UNDECIDED"})


class DimensionManquante(RuntimeError):
    """Une dimension nécessaire n'a pas été fournie au gate."""


def composer(
    cas: Mapping[str, Any], disposition_actualite: str
) -> tuple[str, str | None]:
    """Rend (verdict, autorité qui refuse). L'autorité vaut None si candidat.

    L'ordre suit la gravité : ce qui protège une personne passe avant ce qui
    protège une cohérence.
    """
    if disposition_actualite not in {
        NOT_CURRENT_DECLARED_BY_SOURCE,
        UNKNOWN,
        "VERIFIED_CURRENT",
        "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE",
    }:
        raise DimensionManquante(
            f"disposition d'actualité inconnue : {disposition_actualite!r}"
        )

    # Une incompatibilité de programme PROUVÉE prime sur toute autre
    # dimension : le document n'enseigne pas le programme en vigueur, et
    # aucune autre qualité ne rattrape cela. Cet ordre est antérieur à ce
    # gate ; il n'est pas renversé ici.
    if cas.get("program") == "INCOMPATIBLE":
        return BLOCKED, AUTORITE_PROGRAMME

    if cas.get("pii_gate") in PII_BLOQUANTES:
        return BLOCKED, AUTORITE_PII

    # Une archive déclarée par la source ne redevient jamais servable. C'est
    # le refus que la matrice ne prononçait pas.
    if disposition_actualite == NOT_CURRENT_DECLARED_BY_SOURCE:
        return BLOCKED, AUTORITE_ACTUALITE

    # Le rôle passe avant la provenance : un contenu non indexable par rôle ne
    # devient pas indexable parce qu'on lui trouverait une URL. Refuser
    # d'abord sur la provenance enverrait chercher une preuve qui ne servirait
    # à rien.
    if cas.get("indexable") is False:
        return BLOCKED, AUTORITE_ROLE

    if cas.get("url_provenance") is False:
        return BLOCKED, AUTORITE_PROVENANCE

    for dimension, autorite in (
        ("rights_gate", AUTORITE_DROITS),
        ("classification_gate", AUTORITE_CLASSIFICATION),
        ("placement_gate", AUTORITE_PLACEMENT),
    ):
        if cas.get(dimension, "PASS") != "PASS":
            return BLOCKED, autorite

    # Une actualité indécidable bloque : « on ne sait pas » n'autorise pas.
    if disposition_actualite == UNKNOWN:
        return BLOCKED, AUTORITE_ACTUALITE

    # ADR-0051 : une compatibilité de programme INCONNUE ne bloque pas. Refuser
    # sur une absence retirerait la quasi-totalité du corpus sur ce qu'on
    # ignore, et non sur ce qu'on a établi.
    return CANDIDATE, None
