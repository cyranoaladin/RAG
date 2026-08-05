"""Itération de worker déterministe — un job, une chaîne complète (LOT44e).

Une itération : réclame **un** job (``claim_job``, LOT44e), si le job n'a
pas encore de ressource associée (soumission fraîche, ex. ``/ingest/v2``),
crée la ressource (``create_resource``), sélectionne et valide le profil
via le moteur LOT44c **sans jamais le contourner**, puis exécute la chaîne
complète Scout → Fetcher → Extractor → Classifier → RightsAgent →
QualityAgent en propageant le **même** ``job_id`` à chaque transition.
Complète le job en cas de succès, planifie un retry (ou marque
``dead_letter``) en cas d'échec — jamais d'exception qui remonte
silencieusement sans laisser de trace dans ``ingestion_control``.

``QUALITY_CHECKED -> ROUTED`` n'est jamais appliquée ici non plus (hérité
de LOT44d, ADR-0027, Décision 3 — non rouvert par ce module).

Aucun profil par défaut, aucune sélection de "dernière version" : le
``profile_version`` doit être fourni explicitement dans le payload du job.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from nexus_contracts.ingestion import ResourceScope, SearchPlan
from nexus_contracts.resource_state import ResourceState

try:
    from ingestor.ingestion_agents.classifier import run_classifier
    from ingestor.ingestion_agents.dependencies import (
        ArtifactReader,
        ArtifactStore,
        DestinationValidator,
        SafeFetcher,
        default_safe_fetch,
        default_validate_destination,
    )
    from ingestor.ingestion_agents.extractor import run_extractor
    from ingestor.ingestion_agents.fetcher import run_fetcher
    from ingestor.ingestion_agents.quality_agent import run_quality_agent
    from ingestor.ingestion_agents.rights_agent import run_rights_agent
    from ingestor.ingestion_agents.scout import run_scout
    from ingestor.ingestion_control.jobs import (
        JobClaim,
        JobLeaseConflictError,
        claim_job,
        complete_job,
        record_job_retry,
        set_job_resource_id,
    )
    from ingestor.ingestion_control.provisioning import (
        create_resource,
        find_latest_artifact,
        find_resource_candidate,
        get_resource_state,
        persist_artifact,
        persist_resource_candidate,
    )
    from ingestor.ingestion_profiles.registry import load_profile_registry, select_profile
    from ingestor.ingestion_profiles.validation import validate_scope_against_profile
except (ImportError, ValueError):
    # Image Docker aplatie (LOT44f, ADR-0029) : "ingestor" n'existe pas comme
    # paquet — ces sous-paquets sont importables directement au premier
    # niveau. Même discipline que api.py.
    from ingestion_agents.classifier import run_classifier
    from ingestion_agents.dependencies import (
        ArtifactReader,
        ArtifactStore,
        DestinationValidator,
        SafeFetcher,
        default_safe_fetch,
        default_validate_destination,
    )
    from ingestion_agents.extractor import run_extractor
    from ingestion_agents.fetcher import run_fetcher
    from ingestion_agents.quality_agent import run_quality_agent
    from ingestion_agents.rights_agent import run_rights_agent
    from ingestion_agents.scout import run_scout
    from ingestion_control.jobs import (
        JobClaim,
        JobLeaseConflictError,
        claim_job,
        complete_job,
        record_job_retry,
        set_job_resource_id,
    )
    from ingestion_control.provisioning import (
        create_resource,
        find_latest_artifact,
        find_resource_candidate,
        get_resource_state,
        persist_artifact,
        persist_resource_candidate,
    )
    from ingestion_profiles.registry import (
        load_profile_registry,
        select_profile,
    )
    from ingestion_profiles.validation import (
        validate_scope_against_profile,
    )

#: Champs obligatoires du payload d'un job "resource_pipeline" — absence de
#: l'un d'eux échoue explicitement (ValueError, capturé et transformé en
#: retry par l'appelant), jamais une valeur devinée.
REQUIRED_PAYLOAD_KEYS = (
    "scope", "dedup_key", "source_url", "canonical_url", "domain",
    "proposed_type_doc", "profile_version",
)


@dataclass(frozen=True)
class WorkerDeps:
    owner: str
    profiles_dir: Path
    artifact_store: ArtifactStore
    artifact_reader: ArtifactReader
    max_bytes: int = 20_000_000
    validate_destination: DestinationValidator = default_validate_destination
    safe_fetch: SafeFetcher = default_safe_fetch


@dataclass(frozen=True)
class IterationOutcome:
    worked: bool
    job_id: UUID | None
    status: str | None
    error: str | None


class MissingPayloadFieldError(ValueError):
    """Un champ requis manque dans ``claim.payload`` — rejet explicite,
    jamais une valeur par défaut devinée."""


class ResumeStateInconsistentError(RuntimeError):
    """La ressource est dans un état qui implique qu'un candidat/artefact
    aurait déjà dû être persisté (LOT44f), mais aucun n'est trouvé — jamais
    une reprise silencieuse sur une hypothèse fausse. Situation qui ne
    devrait jamais survenir en fonctionnement normal (les commits
    intermédiaires de ``_process_claimed_job`` gardent état de ressource et
    persistance de l'enregistrement dans la même transaction) ; sa
    présence signale une incohérence à investiguer, pas un cas à masquer
    par un retry aveugle infini (elle finira en ``dead_letter`` comme
    n'importe quelle autre erreur, via ``record_job_retry``)."""


def _process_claimed_job(conn: psycopg.Connection, *, claim: JobClaim, deps: WorkerDeps) -> None:
    """Traite un job du début (ou du point de reprise) à la fin.

    Reprise multi-claims (LOT44f) : un job réclamé après expiration de bail
    (crash worker, cf. ``reap_expired_job_leases``) porte déjà
    ``claim.resource_id`` si une ressource a été créée lors d'une tentative
    précédente. L'état durable de cette ressource (``resources.
    resource_state``, committé) détermine alors quelles étapes ont déjà
    réellement abouti :

    - ``DISCOVERED`` (ou ressource fraîchement créée) : Scout doit encore
      s'exécuter.
    - ``CANDIDATE`` : Scout a committé, pas Fetcher — le ``ResourceCandidate``
      persisté (migration 006) est relu, Fetcher s'exécute.
    - tout état ``>= STORED`` : Fetcher a committé — l'``ArtifactRecord``
      persisté est relu, Scout ET Fetcher sont sautés.

    Aucun état intermédiaire (``EXTRACTED``/``CLASSIFIED``/
    ``RIGHTS_CHECKED``) n'est jamais observé comme point de reprise durable :
    ``run_worker_iteration`` ne committe qu'après chaque point de contrôle
    explicite ci-dessous, jamais entre Extractor et QualityAgent — un crash
    dans ce groupe fait donc toujours réapparaître la ressource à
    ``STORED`` après rollback, jamais à un état intermédiaire non géré ici.
    """
    payload = claim.payload
    missing = [key for key in REQUIRED_PAYLOAD_KEYS if key not in payload]
    if missing:
        raise MissingPayloadFieldError(f"job {claim.job_id} payload missing keys: {missing}")

    scope = ResourceScope.model_validate(payload["scope"])

    registry = load_profile_registry(deps.profiles_dir)
    profile = select_profile(
        registry, collection=scope.collection, profile_version=payload["profile_version"]
    )
    validation_result = validate_scope_against_profile(
        raw_scope=payload["scope"],
        registry=registry,
        collection=scope.collection,
        profile_version=payload["profile_version"],
    )
    if validation_result.status != "passed":
        raise ValueError(
            f"job {claim.job_id}: scope validation against profile did not pass "
            f"(status={validation_result.status}, issues={validation_result.issues})"
        )

    if claim.resource_id is not None:
        resource_id = claim.resource_id
    else:
        resource_id = create_resource(
            conn, run_id=claim.run_id, dedup_key=payload["dedup_key"], scope=scope
        )
        # Rattache resource_id au job dans le même commit : sans ça, une
        # reprise après crash (claim.resource_id lu depuis jobs.resource_id
        # à la prochaine réclamation) ne verrait jamais cette ressource et
        # retenterait create_resource — collision garantie avec
        # resources_collection_dedup_key_unique, la ressource existant déjà.
        set_job_resource_id(conn, job_id=claim.job_id, resource_id=resource_id)
        conn.commit()  # point de contrôle LOT44f : ressource durablement créée et rattachée

    now = datetime.now(UTC)
    search_plan = SearchPlan(
        search_plan_id=uuid4(),
        run_id=claim.run_id,
        scope=profile.scope,
        generated_at=now,
        profile_version=payload["profile_version"],
        queries=[str(payload.get("query", "worker-submitted"))],
        allowed_domains=profile.allowed_domains,
        max_results=profile.max_documents_per_run,
        reason=f"soumission directe (worker CLI, job_id={claim.job_id})",
    )

    current_state = get_resource_state(conn, resource_id=resource_id)
    if current_state is None:  # pragma: no cover - la ressource vient d'être créée/lue ci-dessus
        raise RuntimeError(f"resource {resource_id} not found immediately after creation/lookup")
    resource_state, state_version = current_state

    if resource_state == ResourceState.DISCOVERED:
        candidate, scout_transition = run_scout(
            conn,
            search_plan=search_plan,
            resource_id=resource_id,
            candidate_id=uuid4(),
            discovered_at=now,
            source_url=str(payload["source_url"]),
            canonical_url=str(payload["canonical_url"]),
            domain=str(payload["domain"]),
            proposed_type_doc=payload["proposed_type_doc"],
            expected_version=state_version,
            actor=deps.owner,
            job_id=claim.job_id,
            validate_destination=deps.validate_destination,
        )
        persist_resource_candidate(conn, candidate=candidate)
        conn.commit()  # point de contrôle LOT44f : Scout durablement franchi
        state_version = scout_transition.state_version
    else:
        candidate = find_resource_candidate(conn, resource_id=resource_id, run_id=claim.run_id)
        if candidate is None:
            raise ResumeStateInconsistentError(
                f"resource {resource_id} at state={resource_state} but no persisted "
                "ResourceCandidate found (expected after Scout committed)"
            )

    if resource_state in (ResourceState.DISCOVERED, ResourceState.CANDIDATE):
        artifact, _fetched, stored_transition = run_fetcher(
            conn,
            candidate=candidate,
            artifact_id=uuid4(),
            collected_at=now,
            expected_version=state_version,
            actor=deps.owner,
            max_bytes=deps.max_bytes,
            store_artifact=deps.artifact_store,
            safe_fetch=deps.safe_fetch,
            job_id=claim.job_id,
        )
        persist_artifact(conn, artifact=artifact)
        conn.commit()  # point de contrôle LOT44f : Fetcher durablement franchi
        state_version = stored_transition.state_version
    else:
        artifact = find_latest_artifact(conn, resource_id=resource_id)
        if artifact is None:
            raise ResumeStateInconsistentError(
                f"resource {resource_id} at state={resource_state} but no persisted "
                "ArtifactRecord found (expected after Fetcher committed)"
            )

    extracted_text, extract_transition = run_extractor(
        conn,
        artifact=artifact,
        expected_version=state_version,
        actor=deps.owner,
        read_artifact=deps.artifact_reader,
        job_id=claim.job_id,
    )

    conformity, classify_transition = run_classifier(
        conn,
        resource_id=resource_id,
        run_id=claim.run_id,
        extracted_text=extracted_text,
        profile=profile,
        expected_version=extract_transition.state_version,
        actor=deps.owner,
        job_id=claim.job_id,
    )

    licensed_artifact = artifact
    if payload.get("license"):
        licensed_artifact = artifact.model_copy(update={"license": str(payload["license"])})

    rights, rights_transition = run_rights_agent(
        conn,
        artifact=licensed_artifact,
        profile=profile,
        expected_version=classify_transition.state_version,
        actor=deps.owner,
        job_id=claim.job_id,
    )

    # pii_detected/duplicate_detected : aucun détecteur réel dans ce lot,
    # toujours False — placeholder explicite, cohérent avec LOT44d
    # (ADR-0027, Décision 5), jamais une détection fabriquée.
    run_quality_agent(
        conn,
        artifact=licensed_artifact,
        profile=profile,
        conformity=conformity,
        rights=rights,
        extracted_text=extracted_text,
        declared_language=candidate.language,
        pii_detected=False,
        duplicate_detected=False,
        report_id=uuid4(),
        decision_id=uuid4(),
        evaluated_at=now,
        expected_version=rights_transition.state_version,
        actor=deps.owner,
        job_id=claim.job_id,
    )


def run_worker_iteration(conn: psycopg.Connection, *, deps: WorkerDeps) -> IterationOutcome:
    """Une itération complète : réclame, traite, complète/planifie un retry.

    Protection contre un worker périmé (contrainte LOT44e explicite) : la
    complétion ET la planification d'un retry vérifient toutes deux
    ``lease_token`` (``complete_job``/``record_job_retry``, LOT44e). Si le
    bail de ce worker a expiré et a été repris par un autre (reaper +
    nouveau claim), l'une ou l'autre lève ``JobLeaseConflictError`` — ce
    worker s'arrête alors immédiatement sans toucher au job (``status`` =
    ``"lease_lost"``), jamais une écriture qui écraserait le travail du
    nouveau détenteur.

    Ne committe et ne rollback que ce que cette fonction contrôle
    directement — l'appelant reste responsable de la connexion elle-même
    (fermeture, pool), comme pour toutes les primitives LOT44b/44d/44e.
    """
    claim = claim_job(conn, owner=deps.owner)
    conn.commit()
    if claim is None:
        return IterationOutcome(worked=False, job_id=None, status=None, error=None)

    try:
        _process_claimed_job(conn, claim=claim, deps=deps)
    except Exception as exc:  # noqa: BLE001 - frontière volontaire : tout échec devient un retry tracé
        conn.rollback()
        try:
            outcome = record_job_retry(
                conn, job_id=claim.job_id, lease_token=claim.lease_token, error=str(exc)
            )
        except JobLeaseConflictError as lease_exc:
            conn.rollback()
            return IterationOutcome(
                worked=True, job_id=claim.job_id, status="lease_lost", error=str(lease_exc)
            )
        conn.commit()
        return IterationOutcome(
            worked=True,
            job_id=claim.job_id,
            status="dead_letter" if outcome.exhausted else "retried",
            error=str(exc),
        )

    try:
        complete_job(conn, job_id=claim.job_id, lease_token=claim.lease_token, status="succeeded")
    except JobLeaseConflictError as lease_exc:
        conn.rollback()
        return IterationOutcome(
            worked=True, job_id=claim.job_id, status="lease_lost", error=str(lease_exc)
        )
    conn.commit()
    return IterationOutcome(worked=True, job_id=claim.job_id, status="succeeded", error=None)


__all__ = [
    "REQUIRED_PAYLOAD_KEYS",
    "IterationOutcome",
    "MissingPayloadFieldError",
    "ResumeStateInconsistentError",
    "WorkerDeps",
    "run_worker_iteration",
]
