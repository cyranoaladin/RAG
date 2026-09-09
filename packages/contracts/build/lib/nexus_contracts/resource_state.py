"""Machine d'état des ressources du moteur d'ingestion (LOT44a).

Périmètre strict de LOT44a : la ressource progresse jusqu'à
``RETRIEVAL_ELIGIBLE`` au maximum. ``PUBLISHED`` n'existe pas dans cette
énumération — la publication produit est un sous-système distinct, hors
périmètre, et l'auto-publication n'est pas implémentée. Toute réintroduction
future d'un état de publication devra vivre dans un module séparé décrivant
explicitement ce futur sous-système, jamais ici.

Distinction stricte imposée par LOT44a :
- ``REVIEWED`` signifie uniquement que la décision humaine a été validée
  côté rag-engine (``review_status = 'reviewed'``) ;
- ``RETRIEVAL_ELIGIBLE`` est une vérification déterministe et automatique
  (constat, pas une décision) qu'une ressource ``REVIEWED`` satisfait le
  prédicat de scope du retrieval. Les deux ne sont jamais synonymes.

``CANDIDATE`` et ``STAGED`` sont volontairement non adjacents dans la
séquence normale : sept états intermédiaires les séparent, si bien
qu'aucune transition directe ``CANDIDATE -> STAGED`` n'est représentable.
"""
from __future__ import annotations

from enum import Enum


class ResourceState(str, Enum):
    """Les 20 états d'une ressource, sans notion de publication produit."""

    # Séquence normale (progression stricte, un pas à la fois)
    DISCOVERED = "DISCOVERED"
    CANDIDATE = "CANDIDATE"
    FETCHED = "FETCHED"
    STORED = "STORED"
    EXTRACTED = "EXTRACTED"
    CLASSIFIED = "CLASSIFIED"
    RIGHTS_CHECKED = "RIGHTS_CHECKED"
    QUALITY_CHECKED = "QUALITY_CHECKED"
    ROUTED = "ROUTED"
    STAGED = "STAGED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REVIEWED = "REVIEWED"
    RETRIEVAL_ELIGIBLE = "RETRIEVAL_ELIGIBLE"

    # États d'échec / annulation
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"
    CANCELLED = "CANCELLED"

    # États de rejet / quarantaine / doublon
    REJECTED = "REJECTED"
    QUARANTINED = "QUARANTINED"
    DUPLICATE = "DUPLICATE"
    SUPERSEDED = "SUPERSEDED"


#: Progression normale, un pas à la fois. L'ordre de cette liste EST la
#: définition des transitions "vers l'avant" autorisées : aucun saut.
NORMAL_SEQUENCE: tuple[ResourceState, ...] = (
    ResourceState.DISCOVERED,
    ResourceState.CANDIDATE,
    ResourceState.FETCHED,
    ResourceState.STORED,
    ResourceState.EXTRACTED,
    ResourceState.CLASSIFIED,
    ResourceState.RIGHTS_CHECKED,
    ResourceState.QUALITY_CHECKED,
    ResourceState.ROUTED,
    ResourceState.STAGED,
    ResourceState.NEEDS_REVIEW,
    ResourceState.REVIEWED,
    ResourceState.RETRIEVAL_ELIGIBLE,
)

#: États atteignables (en plus du pas suivant de la séquence normale) depuis
#: n'importe quel état actif — c'est-à-dire tout état de NORMAL_SEQUENCE à
#: l'exception du succès terminal RETRIEVAL_ELIGIBLE.
_UNIVERSAL_ESCAPE_STATES: frozenset[ResourceState] = frozenset(
    {
        ResourceState.FAILED,
        ResourceState.REJECTED,
        ResourceState.QUARANTINED,
        ResourceState.CANCELLED,
    }
)

#: DUPLICATE ne peut être constaté qu'après récupération d'un artefact réel
#: (comparaison de contenu) — jamais avant FETCHED.
_DUPLICATE_REACHABLE_FROM: frozenset[ResourceState] = frozenset(
    NORMAL_SEQUENCE[NORMAL_SEQUENCE.index(ResourceState.FETCHED):NORMAL_SEQUENCE.index(ResourceState.STAGED)]
)

#: SUPERSEDED ne s'applique qu'à une ressource déjà traitée jusqu'au
#: staging ou au-delà (une nouvelle version en remplace une existante).
_SUPERSEDED_REACHABLE_FROM: frozenset[ResourceState] = frozenset(
    NORMAL_SEQUENCE[NORMAL_SEQUENCE.index(ResourceState.STAGED):]
)

#: États sans aucune transition sortante (terminaux stricts).
_NO_OUTGOING_TRANSITIONS: frozenset[ResourceState] = frozenset(
    {
        ResourceState.REJECTED,
        ResourceState.QUARANTINED,
        ResourceState.DUPLICATE,
        ResourceState.SUPERSEDED,
        ResourceState.DEAD_LETTER,
        ResourceState.CANCELLED,
    }
)


def _build_allowed_transitions() -> dict[ResourceState, frozenset[ResourceState]]:
    allowed: dict[ResourceState, set[ResourceState]] = {state: set() for state in ResourceState}

    for index in range(len(NORMAL_SEQUENCE) - 1):
        allowed[NORMAL_SEQUENCE[index]].add(NORMAL_SEQUENCE[index + 1])

    for state in NORMAL_SEQUENCE[:-1]:  # tout état actif, hors RETRIEVAL_ELIGIBLE
        allowed[state] |= _UNIVERSAL_ESCAPE_STATES

    for state in _DUPLICATE_REACHABLE_FROM:
        allowed[state].add(ResourceState.DUPLICATE)

    for state in _SUPERSEDED_REACHABLE_FROM:
        allowed[state].add(ResourceState.SUPERSEDED)

    allowed[ResourceState.FAILED] |= {ResourceState.DEAD_LETTER, ResourceState.CANCELLED}

    for state in _NO_OUTGOING_TRANSITIONS:
        allowed[state] = set()

    return {state: frozenset(targets) for state, targets in allowed.items()}


ALLOWED_RESOURCE_TRANSITIONS: dict[ResourceState, frozenset[ResourceState]] = (
    _build_allowed_transitions()
)


def is_valid_resource_transition(from_state: ResourceState, to_state: ResourceState) -> bool:
    """Vérifie qu'une transition d'état de ressource est autorisée.

    Fonction pure, sans effet de bord — le point de vérité unique pour
    décider si une transition est structurellement valide. N'écrit rien ;
    l'écriture effective (CAS Postgres + journalisation append-only)
    relève du moteur de jobs (LOT44b), hors périmètre de ce module.
    """
    return to_state in ALLOWED_RESOURCE_TRANSITIONS.get(from_state, frozenset())


__all__ = [
    "ALLOWED_RESOURCE_TRANSITIONS",
    "NORMAL_SEQUENCE",
    "ResourceState",
    "is_valid_resource_transition",
]
