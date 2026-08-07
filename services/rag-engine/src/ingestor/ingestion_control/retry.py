"""Retry et backoff déterministe — primitive de concurrence #3 (LOT44b).

Calcul et persistance uniquement. Aucun scheduler, aucun worker : cette
primitive ne décide jamais *quand* être rappelée — elle calcule et
enregistre ``next_attempt_at`` ; un futur appelant (LOT44c+, hors périmètre
ici) décide de rappeler ``claim_resource`` en fonction de cette date.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import psycopg

from .claim import ResourceLeaseConflictError

#: Valeurs par défaut actées (décisions opérationnelles LOT44a) :
#: max_attempts = 3 (porté par resources.max_attempts, colonne, pas ici),
#: backoff exponentiel, plafond 300s. Le jitter ±20% recommandé n'est
#: **volontairement pas appliqué** dans cette primitive : la consigne de ce
#: lot demande un « backoff déterministe » pour la primitive de calcul —
#: une composante aléatoire romprait la déterminisme testable de cette
#: fonction pure. Un futur appelant peut appliquer un jitter par-dessus la
#: valeur retournée ici sans que cette primitive n'ait à en décider.
DEFAULT_BASE_DELAY_S = 5.0
DEFAULT_BACKOFF_FACTOR = 2.0
DEFAULT_MAX_DELAY_S = 300.0


def compute_backoff_seconds(
    attempt_count: int,
    *,
    base_delay_s: float = DEFAULT_BASE_DELAY_S,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    max_delay_s: float = DEFAULT_MAX_DELAY_S,
) -> float:
    """Backoff exponentiel déterministe, plafonné.

    Fonction pure — aucun accès base, aucune horloge, aucun aléa — testable
    sans PostgreSQL. ``compute_backoff_seconds(n)`` retourne toujours la
    même valeur pour le même ``n`` et les mêmes paramètres.
    """
    if attempt_count < 0:
        raise ValueError("attempt_count must be >= 0")
    delay = base_delay_s * (backoff_factor**attempt_count)
    return min(delay, max_delay_s)


@dataclass(frozen=True)
class RetryOutcome:
    resource_id: UUID
    attempt_count: int
    next_attempt_at: datetime | None
    exhausted: bool


def record_retry(
    conn: psycopg.Connection,
    *,
    resource_id: UUID,
    lease_token: UUID,
    error: str,
    base_delay_s: float = DEFAULT_BASE_DELAY_S,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    max_delay_s: float = DEFAULT_MAX_DELAY_S,
) -> RetryOutcome:
    """Incrémente ``attempt_count`` et persiste ``next_attempt_at``.

    - **Nombre de tentatives** : ``attempt_count`` (colonne, incrémentée
      atomiquement par cet ``UPDATE``).
    - **Prochaine date d'exécution** : ``next_attempt_at``, calculée par
      ``compute_backoff_seconds`` — jamais avancée si les tentatives sont
      épuisées (cf. ci-dessous).
    - **Limite explicite** : ``max_attempts`` (colonne ``resources``,
      valeur par défaut 3, LOT44a). Distinction stricte entre erreur
      réessayable (``exhausted=False``, ``next_attempt_at`` renseigné) et
      erreur définitive (``exhausted=True``, ``next_attempt_at`` reste
      ``None``, l'appelant décide séparément — via ``cas_transition`` —
      de faire progresser la ressource vers ``DEAD_LETTER``, ce que cette
      primitive ne fait jamais elle-même).
    - Libère le bail courant (``lease_token``/``lease_expires_at`` remis à
      ``NULL``) — la ressource redevient éligible à un nouveau claim dès
      que ``next_attempt_at`` est atteint.

    Remédiation revue PR#90 : ``lease_token`` est désormais obligatoire et
    vérifié, avec ``lease_expires_at > clock_timestamp()`` (même sémantique
    stricte que ``ingestion_control.jobs.record_job_retry``) — avant ce
    correctif, cette primitive acceptait n'importe quel ``resource_id``
    sans vérifier aucune possession de bail, permettant à un appelant
    périmé d'effacer le bail d'un détenteur plus récent et de faire
    retraiter la même ressource par deux workers concurrents. Lève
    ``ResourceLeaseConflictError`` (jamais silencieux) si le bail ne
    correspond plus ou si la ressource n'existe pas — les deux cas sont
    indiscernables depuis l'extérieur de cette fonction par construction
    (aucun appelant réel n'existe encore dans ce dépôt qui ait besoin de
    les distinguer ; cf. absence totale d'appelant avant ce correctif).

    ``clock_timestamp()``, pas ``now()`` (revue incrémentale PR#90, Cubic
    P2) : ``now()`` reste figé à l'heure de début de la transaction
    PostgreSQL de l'appelant — si cette transaction est restée ouverte
    depuis avant l'expiration réelle du bail (ex. le temps d'un appel
    réseau lent), ``now() > lease_expires_at`` resterait faux même après
    l'expiration réelle, défaisant silencieusement la garde stricte
    promise. ``clock_timestamp()`` renvoie l'heure murale réelle au
    moment de l'évaluation.

    Ne committe pas la transaction : responsabilité de l'appelant.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingestion_control.resources
            SET attempt_count = attempt_count + 1,
                last_error = %s,
                claimed_by = NULL,
                lease_token = NULL,
                lease_expires_at = NULL,
                updated_at = now()
            WHERE resource_id = %s AND lease_token = %s
              AND lease_expires_at > clock_timestamp()
            RETURNING attempt_count, max_attempts
            """,
            (error, resource_id, lease_token),
        )
        row = cur.fetchone()
        if row is None:
            raise ResourceLeaseConflictError(
                f"resource {resource_id}: lease {lease_token} not held (not found, "
                "expired, or already released) — refusing to record a retry that "
                "could clobber another worker's in-progress claim"
            )
        attempt_count, max_attempts = row

        if attempt_count >= max_attempts:
            return RetryOutcome(
                resource_id=resource_id,
                attempt_count=attempt_count,
                next_attempt_at=None,
                exhausted=True,
            )

        delay = compute_backoff_seconds(
            attempt_count,
            base_delay_s=base_delay_s,
            backoff_factor=backoff_factor,
            max_delay_s=max_delay_s,
        )
        next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
        cur.execute(
            "UPDATE ingestion_control.resources SET next_attempt_at = %s WHERE resource_id = %s",
            (next_attempt_at, resource_id),
        )

    return RetryOutcome(
        resource_id=resource_id,
        attempt_count=attempt_count,
        next_attempt_at=next_attempt_at,
        exhausted=False,
    )


__all__ = [
    "DEFAULT_BASE_DELAY_S",
    "DEFAULT_BACKOFF_FACTOR",
    "DEFAULT_MAX_DELAY_S",
    "RetryOutcome",
    "compute_backoff_seconds",
    "record_retry",
]
