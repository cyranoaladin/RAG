"""Primitives de gestion des jobs — cinquième primitive de concurrence (LOT44e).

Nouveau fichier additif : n'importe aucun module de ``ingestion_control``
autre que ``db`` (déjà partagé) et ne modifie aucun fichier existant de
LOT44b (``claim.py``, ``transitions.py``, ``retry.py``, ``lease_reaper.py``,
``__init__.py`` restent inchangés — cf. migration 004, additive).

``ingestion_control.jobs`` (migration 004) porte le cycle de vie d'une
tentative d'exécution métier — distinct de ``resources.resource_state``
(machine d'état à 20 valeurs, LOT44a) : un job peut réclamer/relâcher
plusieurs baux de ressources au cours de son exécution, ce sont deux
concepts orthogonaux (cf. commentaire de migration 003, non contredit ici).

Divergence assumée par rapport au motif ``resources`` (LOT44b) : pour les
ressources, le bail (``claim_resource``) et l'état métier
(``cas_transition``) sont deux primitives strictement séparées, parce que
``resource_state`` porte 20 valeurs gouvernées par un contrat externe
(``nexus_contracts.resource_state``). Pour les jobs, aucun contrat
``IngestionJob`` n'existe (ADR-0027, ADR-0028) : le statut à 6 valeurs
défini ici est une notion strictement locale à ce module, donc le bail et
le statut sont gérés ensemble par les mêmes primitives (``claim_job``,
``complete_job``, ``record_job_retry``) — un choix de simplicité délibéré,
pas un oubli de séparation.

Réconciliation LOT44f (migration 005, ADR-0029) : la contrainte SQL
``jobs_status_valid`` portait historiquement une 7e valeur (``'claimed'``)
absente de ce ``Literal`` et jamais écrite par aucune fonction de ce module
— ``claim_job`` fait transitionner directement ``'queued' -> 'running'``,
l'information "réclamé" étant déjà portée par ``lease_token``/
``lease_expires_at``. La migration 005 aligne la contrainte SQL sur ce
``Literal`` (6 valeurs) plutôt que d'ajouter un état ``'claimed'`` réellement
traversé côté Python, qui aurait exigé une transition supplémentaire sans
aucun appelant actuel.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

JobStatus = Literal[
    "queued", "running", "succeeded", "failed", "dead_letter", "cancelled"
]

#: Statuts qu'un appelant peut réclamer — seul un job en file d'attente est
#: réclamable ; un job déjà en cours, terminé ou définitivement échoué ne
#: l'est jamais.
CLAIMABLE_JOB_STATUSES: frozenset[str] = frozenset({"queued"})

DEFAULT_LEASE_DURATION_S = 300
DEFAULT_BASE_DELAY_S = 5.0
DEFAULT_BACKOFF_FACTOR = 2.0
DEFAULT_MAX_DELAY_S = 300.0


class JobLeaseConflictError(RuntimeError):
    """Le job n'est plus détenu par le bail attendu (perdu/expiré/déjà
    complété par un autre appelant) — jamais une complétion silencieuse."""


def find_active_job_by_dedup_key(conn: psycopg.Connection, *, dedup_key: str) -> UUID | None:
    """Recherche un job non terminal (``queued``/``running``) portant ce
    ``dedup_key`` dans son ``payload`` — primitive d'idempotence LOT44f
    utilisée par le pont best-effort ``/ingest/v2`` pour éviter de créer un
    doublon lors d'une nouvelle tentative applicative (retry HTTP, double
    clic, etc.). Un job déjà terminal (``succeeded``/``failed``/
    ``dead_letter``/``cancelled``) n'est jamais considéré comme un doublon
    actif : une tentative après complétion doit pouvoir créer un nouveau
    job — cette fonction ne fait donc jamais barrage à une ré-ingestion
    volontaire, seulement à un doublon concurrent du même envoi.

    Requête sur ``payload->>'dedup_key'`` (pas d'index dédié — table à
    faible volume à ce stade, cf. ADR-0029 ; à revisiter si le volume de
    jobs actifs simultanés le justifie un jour)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT job_id FROM ingestion_control.jobs
            WHERE payload->>'dedup_key' = %s AND status IN ('queued', 'running')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (dedup_key,),
        )
        row = cur.fetchone()
    return row[0] if row is not None else None


def create_job(
    conn: psycopg.Connection,
    *,
    run_id: UUID,
    job_type: str,
    resource_id: UUID | None = None,
    payload: dict[str, object] | None = None,
) -> UUID:
    """Crée un job en file d'attente (``status='queued'``) — aucune
    réclamation, aucune exécution. ``job_type`` doit être non vide ; aucune
    valeur par défaut n'est devinée."""
    if not job_type or not job_type.strip():
        raise ValueError("job_type must not be blank")

    job_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.jobs (job_id, run_id, resource_id, job_type, payload)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING job_id
            """,
            (job_id, run_id, resource_id, job_type, Jsonb(payload or {})),
        )
        row = cur.fetchone()
        if row is None:  # pragma: no cover - RETURNING garantit une ligne
            raise RuntimeError("INSERT ... RETURNING job_id produced no row")
    return job_id


def set_job_resource_id(conn: psycopg.Connection, *, job_id: UUID, resource_id: UUID) -> None:
    """Rattache un ``resource_id`` à un job qui n'en avait pas encore
    (LOT44f, reprise multi-claims) — appelée par le worker juste après avoir
    créé la ressource associée à un job soumis sans ressource préexistante
    (ex. pont ``/ingest/v2``), dans le même commit que cette création.

    Sans cet appel, un job réclamé à nouveau après un crash (bail expiré,
    ``reap_expired_job_leases``) verrait toujours ``resource_id IS NULL`` et
    tenterait de recréer une ressource — collision garantie avec la
    contrainte ``resources_collection_dedup_key_unique`` (migration 001),
    puisque la ressource existe déjà. Idempotent : réécrire la même valeur
    ne change rien ; ``resource_id`` n'est jamais réassigné à une valeur
    différente une fois posé (aucun appelant de ce module ne le fait)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE ingestion_control.jobs SET resource_id = %s, updated_at = now() "
            "WHERE job_id = %s",
            (resource_id, job_id),
        )


@dataclass(frozen=True)
class JobClaim:
    job_id: UUID
    run_id: UUID
    resource_id: UUID | None
    job_type: str
    payload: dict[str, object]
    lease_token: UUID
    lease_expires_at: datetime
    attempt_count: int


def claim_job(
    conn: psycopg.Connection,
    *,
    owner: str,
    eligible_statuses: tuple[str, ...] = ("queued",),
    lease_duration_s: int = DEFAULT_LEASE_DURATION_S,
) -> JobClaim | None:
    """Réclame atomiquement un job éligible et le fait passer à ``running``.

    Même discipline que ``claim_resource`` (LOT44b) : ``SELECT ... FOR
    UPDATE SKIP LOCKED``, ``eligible_statuses`` borné à
    ``CLAIMABLE_JOB_STATUSES``, ``None`` si aucun job disponible (jamais une
    exception pour ce cas nominal). Ne committe pas la transaction.
    """
    if not eligible_statuses:
        raise ValueError("eligible_statuses must not be empty")
    disallowed = set(eligible_statuses) - CLAIMABLE_JOB_STATUSES
    if disallowed:
        raise ValueError(
            f"eligible_statuses contains non-claimable statuses: {sorted(disallowed)}"
        )

    lease_token = uuid4()
    lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_duration_s)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT job_id, run_id, resource_id, job_type, payload, attempt_count
            FROM ingestion_control.jobs
            WHERE status = ANY(%s)
              AND next_attempt_at <= now()
              AND (lease_token IS NULL OR lease_expires_at < now())
            ORDER BY next_attempt_at, job_id
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """,
            (list(eligible_statuses),),
        )
        row = cur.fetchone()
        if row is None:
            return None
        job_id, run_id, resource_id, job_type, payload, attempt_count = row

        cur.execute(
            """
            UPDATE ingestion_control.jobs
            SET status = 'running', claimed_by = %s, lease_token = %s,
                lease_expires_at = %s, updated_at = now()
            WHERE job_id = %s
            RETURNING job_id
            """,
            (owner, lease_token, lease_expires_at, job_id),
        )
        if cur.fetchone() is None:  # pragma: no cover - le verrou FOR UPDATE l'exclut
            raise RuntimeError("claim lost between SELECT FOR UPDATE and UPDATE")

    return JobClaim(
        job_id=job_id,
        run_id=run_id,
        resource_id=resource_id,
        job_type=job_type,
        payload=payload,
        lease_token=lease_token,
        lease_expires_at=lease_expires_at,
        attempt_count=attempt_count,
    )


def complete_job(
    conn: psycopg.Connection,
    *,
    job_id: UUID,
    lease_token: UUID,
    status: Literal["succeeded", "cancelled"],
) -> None:
    """Termine un job détenu par ``lease_token`` — échec explicite
    (``JobLeaseConflictError``) si le bail ne correspond plus (expiré,
    perdu, ou déjà complété par un autre appelant). Jamais de complétion
    silencieuse d'un job qu'on ne détient plus."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingestion_control.jobs
            SET status = %s, claimed_by = NULL, lease_token = NULL,
                lease_expires_at = NULL, updated_at = now()
            WHERE job_id = %s AND lease_token = %s AND status = 'running'
            RETURNING job_id
            """,
            (status, job_id, lease_token),
        )
        if cur.fetchone() is None:
            raise JobLeaseConflictError(
                f"job {job_id}: lease {lease_token} no longer held (expired, lost, "
                "or already completed) — refusing silent completion"
            )


@dataclass(frozen=True)
class JobRetryOutcome:
    job_id: UUID
    attempt_count: int
    next_attempt_at: datetime | None
    exhausted: bool


def record_job_retry(
    conn: psycopg.Connection,
    *,
    job_id: UUID,
    lease_token: UUID,
    error: str,
    base_delay_s: float = DEFAULT_BASE_DELAY_S,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    max_delay_s: float = DEFAULT_MAX_DELAY_S,
) -> JobRetryOutcome:
    """Incrémente ``attempt_count``, libère le bail, et — divergence
    assumée par rapport à ``record_retry`` (resources) — fait aussi
    progresser ``status`` : ``queued`` avec un nouveau ``next_attempt_at``
    si des tentatives restent, ``dead_letter`` si ``max_attempts`` est
    atteint (jamais un ``status`` laissé à ``running`` après un échec).

    ``lease_token`` est obligatoire et vérifié (même garde que
    ``complete_job``) : un worker dont le bail a expiré et a été repris par
    un autre worker ne peut **jamais** planifier de retry ni faire
    régresser le job d'un autre détenteur — échec explicite
    (``JobLeaseConflictError``), jamais un écrasement silencieux du
    travail en cours d'un autre worker."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingestion_control.jobs
            SET attempt_count = attempt_count + 1,
                last_error = %s,
                claimed_by = NULL,
                lease_token = NULL,
                lease_expires_at = NULL,
                updated_at = now()
            WHERE job_id = %s AND lease_token = %s AND status = 'running'
            RETURNING attempt_count, max_attempts
            """,
            (error, job_id, lease_token),
        )
        row = cur.fetchone()
        if row is None:
            raise JobLeaseConflictError(
                f"job {job_id}: lease {lease_token} no longer held (expired, lost, "
                "or already completed) — refusing to record a retry that could "
                "clobber another worker's in-progress claim"
            )
        attempt_count, max_attempts = row

        if attempt_count >= max_attempts:
            cur.execute(
                "UPDATE ingestion_control.jobs SET status = 'dead_letter' WHERE job_id = %s",
                (job_id,),
            )
            return JobRetryOutcome(
                job_id=job_id, attempt_count=attempt_count,
                next_attempt_at=None, exhausted=True,
            )

        delay = min(base_delay_s * (backoff_factor**attempt_count), max_delay_s)
        next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
        cur.execute(
            "UPDATE ingestion_control.jobs SET status = 'queued', next_attempt_at = %s "
            "WHERE job_id = %s",
            (next_attempt_at, job_id),
        )

    return JobRetryOutcome(
        job_id=job_id, attempt_count=attempt_count,
        next_attempt_at=next_attempt_at, exhausted=False,
    )


@dataclass(frozen=True)
class ReapedJobLease:
    job_id: UUID
    previous_owner: str | None
    previous_lease_token: UUID


def reap_expired_job_leases(conn: psycopg.Connection, *, limit: int = 100) -> list[ReapedJobLease]:
    """Libère les baux de jobs expirés et remet ``status`` à ``queued`` —
    divergence assumée par rapport à ``reap_expired_leases`` (resources),
    qui ne touche jamais ``resource_state``. Ici, un job dont le bail a
    expiré en cours d'exécution (``running``) doit redevenir réclamable :
    laisser ``status='running'`` sans bail actif le rendrait à jamais
    invisible à ``claim_job`` (qui ne sélectionne que ``status IN
    eligible_statuses``)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH expired AS (
                SELECT job_id, claimed_by, lease_token
                FROM ingestion_control.jobs
                WHERE lease_token IS NOT NULL AND lease_expires_at < now()
                ORDER BY lease_expires_at
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            UPDATE ingestion_control.jobs AS j
            SET status = 'queued', claimed_by = NULL, lease_token = NULL,
                lease_expires_at = NULL, updated_at = now()
            FROM expired AS e
            WHERE j.job_id = e.job_id
            RETURNING j.job_id, e.claimed_by, e.lease_token
            """,
            (limit,),
        )
        rows = cur.fetchall()

    return [
        ReapedJobLease(job_id=job_id, previous_owner=owner, previous_lease_token=token)
        for job_id, owner, token in rows
    ]


__all__ = [
    "CLAIMABLE_JOB_STATUSES",
    "DEFAULT_BACKOFF_FACTOR",
    "DEFAULT_BASE_DELAY_S",
    "DEFAULT_LEASE_DURATION_S",
    "DEFAULT_MAX_DELAY_S",
    "JobClaim",
    "JobLeaseConflictError",
    "JobRetryOutcome",
    "JobStatus",
    "ReapedJobLease",
    "claim_job",
    "complete_job",
    "create_job",
    "find_active_job_by_dedup_key",
    "reap_expired_job_leases",
    "record_job_retry",
    "set_job_resource_id",
]
