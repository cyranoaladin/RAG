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

``QUALITY_CHECKED -> ROUTED`` est appliquée par ``run_quality_agent`` lui-même
(LOT44f, ADR-0029) quand la ``RoutingDecision`` calculée vaut ``"ROUTE"`` —
ce module ne fait qu'appeler la chaîne, sans logique de routage propre.

Aucun profil par défaut, aucune sélection de "dernière version" : le
``profile_version`` doit être fourni explicitement dans le payload du job.

LOT41A (ADR-0032/ADR-0034, remédiation GATE H1 items **C** et **D**) — l'autorisation
n'est pas un feu vert calculé une fois puis oublié, c'est une contrainte
appliquée tout au long de la chaîne, à cinq points de contrôle :

1. **pre_fetch** — avant toute requête sortante et avant toute création de
   ressource : l'autorisation *nommée par le job* (``scope_authorization_id``,
   champ obligatoire du payload — jamais « la plus récente pour ce scope »)
   est revérifiée en direct contre GitHub, puis confrontée au scope, au
   digest de manifest du worker, et à l'empreinte du profil sélectionné.
2. **destination** — les URL source/canonique du payload sont confrontées
   à ``allowed_domains``/``exclusions`` avant même leur résolution DNS.
3. **redirect** — chaque saut réellement suivi par ``safe_fetch``
   (cf. ``_authorized_fetcher``) repasse par le même enforcement : une
   redirection hors domaine autorisé interrompt le téléchargement.
4. **content** — après le téléchargement borné, l'autorisation est revérifiée
   en direct et le SHA-256 des octets bruts est confronté à l'allowlist V2,
   avant ``FETCHED``, tout stockage et toute extraction.
5. **rights** — la catégorie de droits *produite* par le RightsAgent est
   confrontée à ``rights_categories``, et l'autorisation est **revérifiée
   en direct une troisième fois** : une révocation ou une expiration
   survenue pendant Scout/Fetcher/Extractor prend effet avant que la
   ressource n'avance, jamais seulement au job suivant.

Tout refus est journalisé (``SCOPE_AUTHORIZATION_DENIED``, avec le nom du
point de contrôle) et committé avant de se propager ; le job échoue
explicitement, jamais traité en supposant une autorisation implicite.

``verify_scope_authorization`` est injectable via ``WorkerDeps`` (même
motif que ``safe_fetch``/``validate_destination``) : la production utilise
toujours la vérification live réelle ; seuls des tests qui ne portent pas
sur LOT41A lui-même peuvent y substituer un stub, plutôt que de
reconstruire une frontière GitHub complète pour un scénario qui n'en a pas
besoin.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
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
    from ingestor.ingestion_agents.fetcher import ContentAuthorizationBinding, run_fetcher
    from ingestor.ingestion_agents.quality_agent import run_quality_agent
    from ingestor.ingestion_agents.rights_agent import run_rights_agent
    from ingestor.ingestion_agents.scout import run_scout
    from ingestor.ingestion_control.artifact_attribution import (
        derive_artifact_attribution,
        persist_artifact_attribution,
    )
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
    from ingestor.ingestion_control.scope_authority import (
        ScopeAuthorizationDeniedError,
        VerifiedAuthorization,
        record_scope_authorization_denied,
    )
    from ingestor.ingestion_control.scope_authority import (
        verify_scope_authorization as verify_scope_authorization_default,
    )
    from ingestor.ingestion_control.scope_enforcement import (
        enforce_before_fetch,
        enforce_content_sha256,
        enforce_destination,
        enforce_pii,
        enforce_rights,
    )
    from ingestor.ingestion_profiles.registry import (
        ProfileRegistry,
        profile_fingerprint,
        select_profile,
    )
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
    from ingestion_agents.fetcher import ContentAuthorizationBinding, run_fetcher
    from ingestion_agents.quality_agent import run_quality_agent
    from ingestion_agents.rights_agent import run_rights_agent
    from ingestion_agents.scout import run_scout
    from ingestion_control.artifact_attribution import (
        derive_artifact_attribution,
        persist_artifact_attribution,
    )
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
    from ingestion_control.scope_authority import (
        ScopeAuthorizationDeniedError,
        VerifiedAuthorization,
        record_scope_authorization_denied,
    )
    from ingestion_control.scope_authority import (
        verify_scope_authorization as verify_scope_authorization_default,
    )
    from ingestion_control.scope_enforcement import (
        enforce_before_fetch,
        enforce_content_sha256,
        enforce_destination,
        enforce_pii,
        enforce_rights,
    )
    from ingestion_profiles.registry import (
        ProfileRegistry,
        profile_fingerprint,
        select_profile,
    )
    from ingestion_profiles.validation import (
        validate_scope_against_profile,
    )

#: Seul type de job que cette boucle sait traiter — remédiation revue
#: PR#90 (Cubic P2) : sans ce filtre explicite passé à ``claim_job``, un
#: job d'un autre type (ex. un futur job "planner_run") aurait été réclamé
#: ici, interprété comme un "resource_pipeline" incomplet (échec sur
#: REQUIRED_PAYLOAD_KEYS), et épuisé en retries jusqu'au dead_letter au
#: lieu d'être laissé disponible pour son propre consommateur.
SUPPORTED_JOB_TYPES = ("resource_pipeline",)

#: Champs obligatoires du payload d'un job "resource_pipeline" — absence de
#: l'un d'eux échoue explicitement (ValueError, capturé et transformé en
#: retry par l'appelant), jamais une valeur devinée.
REQUIRED_PAYLOAD_KEYS = (
    "scope", "dedup_key", "source_url", "canonical_url", "domain",
    "proposed_type_doc", "profile_version", "scope_authorization_id",
)


class ScopeAuthorizationVerifier(Protocol):
    """Signature de ``scope_authority.verify_scope_authorization``.

    ``authorization_id`` est **obligatoire** (item C) : il n'existe aucune
    surcharge qui déduirait l'autorisation depuis le seul scope."""

    def __call__(
        self,
        conn: psycopg.Connection,
        *,
        authorization_id: str,
        scope: ResourceScope | None = ...,
        now: datetime | None = ...,
    ) -> VerifiedAuthorization: ...


@dataclass(frozen=True)
class WorkerDeps:
    """``profile_registry`` (remédiation revue PR#90) : le ``ProfileRegistry``
    exact chargé et vérifié une fois au démarrage par ``enforce_production_
    manifest_gate`` (``StartupGateResult.registry``) — jamais un ``Path``
    rechargé depuis le disque à chaque itération. Avant ce correctif,
    ``_process_claimed_job`` rappelait ``load_profile_registry(profiles_dir)``
    à chaque job, ce qui permettait à un profil modifié sur l'hôte après le
    démarrage (le montage lecture seule ne protège que le conteneur, pas le
    fichier côté hôte) d'être utilisé sans jamais être revérifié contre le
    manifest approuvé — le worker traitait alors un contenu dont
    l'empreinte n'avait jamais été validée."""

    owner: str
    profile_registry: ProfileRegistry
    artifact_store: ArtifactStore
    artifact_reader: ArtifactReader
    max_bytes: int = 20_000_000
    validate_destination: DestinationValidator = default_validate_destination
    safe_fetch: SafeFetcher = default_safe_fetch
    verify_scope_authorization: ScopeAuthorizationVerifier = verify_scope_authorization_default
    #: Empreinte du manifest de production réellement chargé au démarrage
    #: (``StartupGateResult.manifest.manifest_fingerprint``). Confrontée au
    #: ``manifest_digest`` de l'autorisation à chaque job (item D) : un
    #: worker qui tourne sur un autre manifest que celui autorisé ne
    #: traite plus rien. La valeur par défaut vide ne peut satisfaire
    #: aucune autorisation réelle — un appelant qui oublie de la fournir
    #: échoue fail-closed, jamais silencieusement en mode « non vérifié ».
    manifest_digest: str = ""


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


def _authorize_or_record_denial(
    conn: psycopg.Connection,
    *,
    claim: JobClaim,
    deps: WorkerDeps,
    authorization_id: str,
    scope: ResourceScope,
    checkpoint: str,
    then: Callable[[VerifiedAuthorization], None] | None = None,
) -> VerifiedAuthorization:
    """Revalide **en direct** l'autorisation nommée, puis applique le point
    de contrôle ``then``.

    Tout refus — absence, révocation, expiration, divergence GitHub,
    divergence d'artefact, ou violation d'un point de contrôle — est
    journalisé dans ``workflow_events`` (``SCOPE_AUTHORIZATION_DENIED``,
    avec le nom du point de contrôle) **et committé immédiatement** avant
    de se propager : le rollback que l'appelant effectue sur l'exception
    effacerait sinon la seule trace durable du refus. Le job échoue
    ensuite normalement (retry/dead_letter) — jamais une poursuite vers
    l'étape suivante.

    Appelé à chaque point de contrôle sensible, pas une seule fois au
    début : c'est ce qui rend une révocation intervenue *pendant* un run
    effective avant que la ressource n'avance."""
    try:
        authorization = deps.verify_scope_authorization(
            conn, authorization_id=authorization_id, scope=scope
        )
        if then is not None:
            then(authorization)
    except ScopeAuthorizationDeniedError as exc:
        conn.rollback()
        record_scope_authorization_denied(
            conn,
            run_id=claim.run_id,
            job_id=claim.job_id,
            actor=deps.owner,
            reason=str(exc),
            checkpoint=checkpoint,
            authorization_id=authorization_id,
        )
        conn.commit()
        raise
    return authorization


def _enforce_scope_destinations(
    conn: psycopg.Connection,
    *,
    claim: JobClaim,
    deps: WorkerDeps,
    authorization: VerifiedAuthorization,
    authorization_id: str,
    urls: tuple[str, ...],
) -> None:
    """Applique l'enforcement de domaine à des URL déjà connues du payload.

    Pas de revalidation live ici : l'autorisation vient d'être revérifiée
    au point de contrôle précédent, et ces URL sont statiques (elles ne
    dépendent d'aucun aller-retour réseau). Les sauts dynamiques, eux,
    passent par ``_authorized_fetcher``."""
    try:
        for url in urls:
            enforce_destination(authorization, url=url, checkpoint="destination")
    except ScopeAuthorizationDeniedError as exc:
        conn.rollback()
        record_scope_authorization_denied(
            conn,
            run_id=claim.run_id,
            job_id=claim.job_id,
            actor=deps.owner,
            reason=str(exc),
            checkpoint="destination",
            authorization_id=authorization_id,
        )
        conn.commit()
        raise


def _authorized_fetcher(
    deps: WorkerDeps, authorization: VerifiedAuthorization
) -> SafeFetcher:
    """Enveloppe ``deps.safe_fetch`` d'un rappel d'enforcement par saut.

    Conserve exactement la signature de ``SafeFetcher`` : le Fetcher
    n'apprend rien de LOT41A, il reçoit simplement un téléchargeur dont la
    politique de destination est déjà celle de l'autorisation. Un appelant
    qui fournirait explicitement ``on_destination`` verrait sa valeur
    ignorée au profit de la politique d'autorisation — c'est voulu : cette
    politique n'est jamais désactivable depuis un appelant."""

    def fetch(
        url: str,
        *,
        max_bytes: int,
        max_redirects: int = 5,
        timeout: Any = None,
        transport: Any = None,
        on_destination: Callable[[str], None] | None = None,
    ) -> Any:
        del on_destination  # jamais honoré : la politique d'autorisation prime
        kwargs: dict[str, Any] = {
            "max_bytes": max_bytes,
            "max_redirects": max_redirects,
            "on_destination": lambda hop: enforce_destination(
                authorization, url=hop, checkpoint="redirect"
            ),
        }
        if timeout is not None:
            kwargs["timeout"] = timeout
        if transport is not None:
            kwargs["transport"] = transport
        return deps.safe_fetch(url, **kwargs)

    return fetch


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
    authorization_id = str(payload["scope_authorization_id"])

    # Remédiation revue PR#90 : jamais un rechargement depuis le disque ici
    # — le registre approuvé au démarrage (deps.profile_registry) reste la
    # seule source pour toute la durée de vie du worker (cf. WorkerDeps).
    registry = deps.profile_registry
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

    # LOT41A (ADR-0032, item D) : premier point de contrôle, avant toute
    # requête sortante et avant toute création de ressource. Le profil est
    # sélectionné juste au-dessus parce que le point de contrôle confronte
    # aussi son empreinte — mais aucun octet n'a encore quitté le worker.
    #
    # ``profile_id`` : l'identité d'un profil dans ce dépôt est le couple
    # (collection, profile_version) — cf. ProfileKey. La collection en est
    # la composante stable, et c'est elle que l'artefact d'autorité nomme.
    authorization = _authorize_or_record_denial(
        conn,
        claim=claim,
        deps=deps,
        authorization_id=authorization_id,
        scope=scope,
        checkpoint="pre_fetch",
        then=lambda auth: enforce_before_fetch(
            auth,
            authorization_id=authorization_id,
            scope=scope,
            manifest_digest=deps.manifest_digest,
            profile_id=profile.scope.collection,
            profile_version=profile.profile_version,
            profile_fingerprint=profile_fingerprint(profile),
            now=datetime.now(UTC),
        ),
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
        set_job_resource_id(
            conn, job_id=claim.job_id, resource_id=resource_id, lease_token=claim.lease_token
        )
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

    # LOT41A (item D) : deuxième point de contrôle, au moment où les URL
    # réellement visées sont connues. Appliqué AVANT Scout, donc avant la
    # première résolution DNS de ``validate_destination`` — une URL hors
    # domaine autorisé n'est jamais résolue, encore moins contactée.
    _enforce_scope_destinations(
        conn,
        claim=claim,
        deps=deps,
        authorization=authorization,
        authorization_id=authorization_id,
        urls=(str(payload["source_url"]), str(payload["canonical_url"])),
    )

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
        # La preuve de droits vient exclusivement de l'autorisation LOT41A
        # revérifiée ci-dessus, jamais d'un champ libre du payload opérateur.
        # Elle est propagée avant persist_artifact : une reprise après crash
        # relit donc le même ArtifactRecord, lié au digest exact approuvé.
        def authorize_downloaded_content(
            *, content_sha256: str, final_url: str
        ) -> ContentAuthorizationBinding:
            """Revérifie après le téléchargement, avant ``FETCHED``.

            La destination finale est reconfrontée à l'autorisation fraîche
            avant le SHA. Une révocation/expiration/head drift survenue
            pendant le transfert est donc durablement refusée au checkpoint
            ``content`` avant que les octets ne quittent le buffer borné.
            """
            fresh_authorization = _authorize_or_record_denial(
                conn,
                claim=claim,
                deps=deps,
                authorization_id=authorization_id,
                scope=scope,
                checkpoint="content",
                then=lambda auth: (
                    enforce_destination(auth, url=final_url, checkpoint="destination"),
                    enforce_content_sha256(auth, content_sha256=content_sha256),
                )[-1],
            )
            return ContentAuthorizationBinding(
                authorization_id=fresh_authorization.authorization_id,
                authorization_digest=fresh_authorization.authorization_digest,
                protocol_version=fresh_authorization.protocol_version,
            )

        artifact, _fetched, stored_transition = run_fetcher(
            conn,
            candidate=candidate,
            artifact_id=uuid4(),
            collected_at=now,
            expected_version=state_version,
            actor=deps.owner,
            max_bytes=deps.max_bytes,
            store_artifact=deps.artifact_store,
            # LOT41A (item D) : chaque saut réseau — URL initiale ET toute
            # redirection — repasse par l'enforcement de domaine avant
            # d'être contacté. C'est le seul endroit d'où la chaîne de
            # redirection est observable ; une redirection hors domaine
            # autorisé interrompt le téléchargement immédiatement.
            safe_fetch=_authorized_fetcher(deps, authorization),
            authorize_content=authorize_downloaded_content,
            job_id=claim.job_id,
            # LOT41A borne le scope et les catégories de droits admises ;
            # il n'est jamais une preuve de licence sur l'artefact. Le job
            # ne porte aucune preuve de droits gouvernée et ne peut donc pas
            # en injecter une : RightsAgent doit rester fail-closed sur
            # Rights.unknown jusqu'à l'arrivée d'une preuve distincte.
            license=None,
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

    rights, rights_transition = run_rights_agent(
        conn,
        artifact=artifact,
        profile=profile,
        expected_version=classify_transition.state_version,
        actor=deps.owner,
        job_id=claim.job_id,
    )

    # LOT41A (item D) : troisième point de contrôle. La catégorie de droits
    # vient d'être *produite* par le pipeline ; c'est maintenant, et
    # seulement maintenant, qu'on peut la confronter aux catégories
    # autorisées. L'autorisation est **revalidée en direct** ici : une
    # révocation ou une expiration survenue pendant Scout/Fetcher/Extractor
    # (qui peuvent être longs) prend effet avant que la ressource ne
    # franchisse la qualité, jamais seulement au job suivant.
    pii_detected = False
    _authorize_or_record_denial(
        conn,
        claim=claim,
        deps=deps,
        authorization_id=authorization_id,
        scope=scope,
        checkpoint="rights",
        then=lambda auth: (
            enforce_rights(auth, rights=rights, now=datetime.now(UTC)),
            enforce_pii(auth, pii_detected=pii_detected),
        )[-1],
    )

    # pii_detected/duplicate_detected : aucun détecteur réel dans ce lot,
    # toujours False — placeholder explicite, cohérent avec LOT44d
    # (ADR-0029, Décision 5), jamais une détection fabriquée. La valeur
    # traverse quand même le point de contrôle PII ci-dessus : le jour où
    # un détecteur réel la renseigne, l'enforcement est déjà en place.
    run_quality_agent(
        conn,
        artifact=artifact,
        profile=profile,
        conformity=conformity,
        rights=rights,
        extracted_text=extracted_text,
        declared_language=candidate.language,
        pii_detected=pii_detected,
        duplicate_detected=False,
        report_id=uuid4(),
        decision_id=uuid4(),
        evaluated_at=now,
        expected_version=rights_transition.state_version,
        actor=deps.owner,
        job_id=claim.job_id,
    )

    # LOT H2-F (défaut 6) : les quatre faits d'attribution deviennent
    # définitifs exactement ici — au **verdict** du gate, quel que soit son
    # signe. Avant lui, ``type_doc`` n'est qu'une proposition de Scout et
    # rien n'a confronté cette proposition au profil approuvé ; après lui,
    # aucune étape du pipeline ne les touche plus et l'étape suivante est
    # la mise en revue de publication.
    #
    # Écrit aussi pour une ressource refusée, délibérément : un refus doit
    # rester attribuable (« quelle source a produit cette ressource
    # rejetée ? »), et l'ordre des refus en aval reste celui de leur
    # gravité — une chaîne qualité négative est nommée comme telle plutôt
    # que masquée par une attribution absente. La publication reste bloquée
    # par ``gate_passed=false`` à trois niveaux indépendants.
    #
    # L'écriture partage la transaction de l'événement
    # ``PUBLICATION_GATE_EVALUATED`` et, le cas échéant, de la transition
    # ``ROUTED`` (aucun commit entre les deux) : une ressource ne peut donc
    # jamais atteindre ``ROUTED`` sans son attribution. Toute erreur se
    # propage et fait échouer le job — jamais une publication ultérieure
    # sur une attribution absente ou devinée.
    persist_artifact_attribution(
        conn,
        attribution=derive_artifact_attribution(
            ingestion_artifact_id=artifact.artifact_id,
            candidate=candidate,
            profile=profile,
        ),
        run_id=claim.run_id,
        actor=deps.owner,
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
    claim = claim_job(conn, owner=deps.owner, job_types=SUPPORTED_JOB_TYPES)
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
    "SUPPORTED_JOB_TYPES",
    "IterationOutcome",
    "MissingPayloadFieldError",
    "ResumeStateInconsistentError",
    "WorkerDeps",
    "run_worker_iteration",
]
