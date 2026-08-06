"""Claim atomique — primitive de concurrence #1 (LOT44b).

Garantit que deux sessions concurrentes ne peuvent jamais obtenir
simultanément la même ressource.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
from nexus_contracts.resource_state import NORMAL_SEQUENCE, ResourceState

#: Durée de bail par défaut, en secondes — plafond explicite (LOT44a,
#: décisions opérationnelles par défaut : plafond de backoff 300s ; le bail
#: réutilise le même ordre de grandeur par cohérence, sans lien direct).
DEFAULT_LEASE_DURATION_S = 300

#: États qu'un appelant a le droit de réclamer : la séquence normale de
#: nexus_contracts.resource_state, à l'exclusion de RETRIEVAL_ELIGIBLE (le
#: succès terminal — plus aucun travail ne s'y réclame). Tous les états
#: d'échec/quarantaine/doublon (FAILED, DEAD_LETTER, CANCELLED, REJECTED,
#: QUARANTINED, DUPLICATE, SUPERSEDED) sont exclus par construction :
#: aucun appelant ne peut réclamer arbitrairement un état terminal ou
#: interdit, la liste n'est pas laissée à sa seule discrétion.
CLAIMABLE_STATES = frozenset(NORMAL_SEQUENCE) - {ResourceState.RETRIEVAL_ELIGIBLE}


class ResourceLeaseConflictError(RuntimeError):
    """Le bail de la ressource n'est plus détenu par le jeton attendu
    (perdu, expiré, ou déjà repris par un autre appelant) — jamais une
    écriture silencieuse. Remédiation revue PR#90 : miroir de
    ``JobLeaseConflictError`` (``ingestion_control.jobs``), pour les
    primitives de concurrence côté ``resources``."""


@dataclass(frozen=True)
class Claim:
    """Résultat d'une réclamation réussie.

    ``lease_token`` reste un identifiant **distinct** et **jamais réutilisé**
    comme ``job_id`` (LOT44a ne définit aucun contrat ``IngestionJob``
    séparé ; ce schéma ne crée pas de table "jobs" — cf. commentaire de la
    migration 003 — mais cela n'autorise pas à confondre les deux notions) :

    - ``lease_token`` : identifiant **secret** de possession temporaire du
      bail, connu uniquement du détenteur du verrou de ligne. Change à
      chaque réclamation, y compris deux réclamations successives de la
      même ressource par le même appelant.
    - ``job_id`` (paramètre de ``cas_transition``/colonne de
      ``workflow_events``) : identifiant **libre et optionnel**, jamais
      renseigné automatiquement par cette primitive — reste ``NULL`` tant
      qu'aucun appelant ne fournit explicitement une valeur (par exemple
      lorsqu'un futur contrat ``IngestionJob`` existera). Ne jamais
      assigner ``job_id = claim.lease_token`` : ce sont deux identités
      conceptuellement différentes (bail de concurrence vs. tentative
      d'exécution métier), même si elles peuvent, par hasard d'usage
      futur, être corrélées par l'appelant — jamais par cette primitive.
    """

    resource_id: UUID
    lease_token: UUID
    lease_expires_at: datetime
    resource_state: ResourceState
    state_version: int


def claim_resource(
    conn: psycopg.Connection,
    *,
    eligible_states: tuple[ResourceState, ...],
    owner: str,
    lease_duration_s: int = DEFAULT_LEASE_DURATION_S,
) -> Claim | None:
    """Réclame atomiquement une ressource éligible et lui attribue un bail.

    - **États éligibles** : fournis par l'appelant (``eligible_states``),
      mais **bornés** à ``CLAIMABLE_STATES`` — la séquence normale de la
      machine d'état, hors succès terminal (``RETRIEVAL_ELIGIBLE``).
      L'appelant ne peut jamais réclamer arbitrairement un état terminal ou
      interdit (``FAILED``, ``DEAD_LETTER``, ``CANCELLED``, ``REJECTED``,
      ``QUARANTINED``, ``DUPLICATE``, ``SUPERSEDED``, ``RETRIEVAL_ELIGIBLE``) —
      ``ValueError`` immédiate, avant tout accès base, si un état hors
      liste est fourni. Cette primitive reste générique et ne connaît
      aucune étape métier précise ; c'est un futur appelant (LOT44c+, hors
      périmètre ici) qui décidera du sous-ensemble pertinent à son travail.
    - **Verrou** : ``SELECT ... FOR UPDATE SKIP LOCKED``. Deux sessions
      concurrentes qui appellent cette fonction en même temps ne peuvent
      jamais obtenir la même ligne : la seconde saute silencieusement toute
      ligne déjà verrouillée par la première (elle en prend une autre
      disponible, ou aucune).
    - **Comportement sous concurrence** : sérialisé par le verrou de ligne
      Postgres — jamais de double réclamation, jamais d'attente bloquante
      artificielle (``SKIP LOCKED`` évite tout blocage sur une ligne prise).
    - **Identité du propriétaire** : ``owner`` (chaîne libre, ex. nom de
      process/worker — LOT44b n'impose aucun format, aucun registre de
      workers n'est créé).
    - **Token de bail** : ``lease_token``, UUID neuf à chaque réclamation
      réussie (jamais réutilisé, jamais dérivé d'un hash).
    - **Expiration** : ``lease_expires_at = now() + lease_duration_s``.
    - **Aucun élément disponible** : retourne ``None`` — jamais d'exception
      pour ce cas nominal (file vide ou entièrement verrouillée/en bail).

    Cette fonction ne committe pas la transaction : c'est la responsabilité
    de l'appelant (primitive minimale, pas d'opinion sur les limites de
    transaction du code appelant).
    """
    if not eligible_states:
        raise ValueError("eligible_states must not be empty")
    disallowed = set(eligible_states) - CLAIMABLE_STATES
    if disallowed:
        raise ValueError(
            "eligible_states contains non-claimable (terminal/forbidden) states: "
            f"{sorted(state.value for state in disallowed)}"
        )
    if lease_duration_s <= 0:
        raise ValueError(f"lease_duration_s must be > 0, got {lease_duration_s!r}")
    state_values = [state.value for state in eligible_states]
    lease_token = uuid4()
    lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_duration_s)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT resource_id, resource_state, state_version
            FROM ingestion_control.resources
            WHERE resource_state = ANY(%s)
              AND next_attempt_at <= now()
              AND (lease_token IS NULL OR lease_expires_at < now())
            ORDER BY next_attempt_at, resource_id
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """,
            (state_values,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        resource_id, state_value, state_version = row

        cur.execute(
            """
            UPDATE ingestion_control.resources
            SET claimed_by = %s, lease_token = %s, lease_expires_at = %s, updated_at = now()
            WHERE resource_id = %s
            RETURNING resource_id
            """,
            (owner, lease_token, lease_expires_at, resource_id),
        )
        if cur.fetchone() is None:  # pragma: no cover - le verrou FOR UPDATE l'exclut
            raise RuntimeError("claim lost between SELECT FOR UPDATE and UPDATE")

    return Claim(
        resource_id=resource_id,
        lease_token=lease_token,
        lease_expires_at=lease_expires_at,
        resource_state=ResourceState(state_value),
        state_version=state_version,
    )


__all__ = [
    "CLAIMABLE_STATES",
    "Claim",
    "DEFAULT_LEASE_DURATION_S",
    "ResourceLeaseConflictError",
    "claim_resource",
]
