"""Worker B — reprise de publication après revue LOT42 (Phase B).

**Pourquoi un second consommateur et pas une étape de plus.** Le worker
d'ingestion ne peut pas attendre une revue humaine : il bloquerait sur un
délai qui se compte en heures ou en jours, et son bail de job expirerait.
Phase A s'arrête donc sur ``NEEDS_REVIEW``, et ce module reprend la
ressource *après* qu'une attestation valide existe. Les deux consomment
des ``job_type`` distincts et ne se croisent jamais.

**Rien n'est déduit.** Le job nomme la ressource, le run, la version
d'état attendue et l'attestation exacte. Aucune requête ne va chercher
« la dernière revue » ni « la dernière autorisation » : un
``ORDER BY created_at DESC LIMIT 1`` transformerait une approbation
humaine en variable d'environnement, puisque la dernière ligne insérée
déciderait de ce qui se publie.

**Tout est revérifié au moment de publier.** L'attestation, l'autorité
LOT41A, le SHA du contenu, l'empreinte du profil, le digest du manifeste,
l'attribution durable, la clairance PII et les droits. Ces faits étaient
vrais quand Phase A s'est arrêtée ; entre-temps une autorisation a pu
être révoquée, une preuve remplacée, un profil modifié. Publier sur des
constats périmés reviendrait à publier sans constats.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg

try:
    from ingestor.embedding_provider import (
        EmbeddingProvider,
        EmbeddingProviderError,
        coerce_embedding_provider,
    )
    from ingestor.governed_publisher_v2 import (
        GovernedArtifact,
        publish_governed_artifact,
    )
    from ingestor.ingestion_control.artifact_attribution import (
        load_artifact_attribution,
    )
    from ingestor.ingestion_control.governed_publication_path import (
        promote_reviewed_publication,
    )
    from ingestor.ingestion_control.jobs import (
        JobClaim,
        JobLeaseConflictError,
        claim_job,
        complete_job,
        record_job_retry,
    )
    from ingestor.ingestion_control.provisioning import (
        find_latest_artifact,
        get_resource_state,
    )
    from ingestor.ingestion_control.publication_evidence import (
        collect_publication_facts,
    )
    from ingestor.ingestion_control.sealed_evidence import SealedEvidenceError
    from ingestor.verified_pedagogical_placement import to_eligible_placement
except ImportError as _exc:  # repli à plat, cause réelle préservée
    if not (_exc.name is None and "relative import" in str(_exc)) and (
        _exc.name or ""
    ) not in ("ingestor", "src", "src.ingestor"):
        raise
    from embedding_provider import (
        EmbeddingProvider,
        EmbeddingProviderError,
        coerce_embedding_provider,
    )
    from governed_publisher_v2 import (
        GovernedArtifact,
        publish_governed_artifact,
    )
    from ingestion_control.artifact_attribution import (
        load_artifact_attribution,
    )
    from ingestion_control.governed_publication_path import (
        promote_reviewed_publication,
    )
    from ingestion_control.jobs import (
        JobClaim,
        JobLeaseConflictError,
        claim_job,
        complete_job,
        record_job_retry,
    )
    from ingestion_control.provisioning import (
        find_latest_artifact,
        get_resource_state,
    )
    from ingestion_control.publication_evidence import (
        collect_publication_facts,
    )
    from ingestion_control.sealed_evidence import (
        SealedEvidenceError,
    )
    from verified_pedagogical_placement import (
        to_eligible_placement,
    )

#: Type de job consommé par ce worker, et par lui seul.
PUBLICATION_RESUME_JOB_TYPE = "publication_resume"

#: Champs que le job doit nommer. Un champ absent est un refus : le worker
#: ne va pas chercher la valeur ailleurs.
REQUIRED_PAYLOAD_FIELDS = (
    "resource_id",
    "run_id",
    "expected_state_version",
    "publication_attestation_id",
)

#: État attendu. Toute autre valeur signifie que Phase A n'a pas fini, ou
#: qu'un autre worker a déjà repris la ressource.
EXPECTED_STATE = "NEEDS_REVIEW"


class PublicationResumeError(RuntimeError):
    """La reprise ne peut pas prouver ce qu'elle publierait — refus."""


@dataclass(frozen=True)
class PublicationResumeOutcome:
    worked: bool
    job_id: UUID | None
    status: str | None
    error: str | None
    artifact_id: str | None = None
    chunk_rows: int = 0
    placement_rows: int = 0


@dataclass
class PublicationResumeDeps:
    """Dépendances de Worker B.

    ``product_dsn`` est distinct de la connexion control : le publisher
    exige deux connexions séparées, et les rôles PostgreSQL qui les
    portent n'ont pas les mêmes droits."""

    owner: str
    product_dsn: str
    artifact_reader: Any
    extract_text: Any
    embedding_provider: EmbeddingProvider
    pii_evidence_registry: Any = None
    rights_evidence_registry: Any = None
    manifest_digest: str = ""
    placement_resolver: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.embedding_provider, EmbeddingProvider):
            raise PublicationResumeError(
                "publication worker requires an explicit embedding provider"
            )
        try:
            self.embedding_provider = coerce_embedding_provider(
                self.embedding_provider
            )
        except EmbeddingProviderError as exc:
            raise PublicationResumeError(str(exc)) from exc

    def require_sealed_evidence(self) -> tuple[Any, Any]:
        if self.pii_evidence_registry is None or self.rights_evidence_registry is None:
            raise SealedEvidenceError(
                f"publication worker {self.owner!r} has no sealed evidence; the "
                "clearances that justified staging must still hold at publication "
                "time, and a worker that cannot re-check them must not publish"
            )
        return self.pii_evidence_registry, self.rights_evidence_registry


def _require_payload(payload: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in REQUIRED_PAYLOAD_FIELDS if not payload.get(field)]
    if missing:
        raise PublicationResumeError(
            f"publication_resume payload is missing {missing} — this worker names "
            "what it publishes; it never resolves 'the latest' anything"
        )
    return payload


def _load_run_placement_context(
    conn: psycopg.Connection,
    *,
    run_id: UUID,
) -> tuple[str, str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT collection, profile_version, school_year "
            "FROM ingestion_control.ingestion_runs WHERE run_id = %s",
            (run_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise PublicationResumeError(f"ingestion run {run_id} does not exist")
    collection, profile_version, school_year = row
    return str(collection), str(profile_version), str(school_year)


def resume_publication(
    control_conn: psycopg.Connection,
    *,
    claim: JobClaim,
    deps: PublicationResumeDeps,
    build_placements: Any = None,
) -> PublicationResumeOutcome:
    """Reprend une ressource en revue et la publie, ou refuse.

    ``build_placements`` est conservé uniquement pour compatibilité d'appel.
    La publication exige toujours ``deps.placement_resolver`` afin de relire
    le catalogue, la currentness et le profil scellés."""
    payload = _require_payload(dict(claim.payload or {}))
    resource_id = UUID(str(payload["resource_id"]))
    payload_run_id = UUID(str(payload["run_id"]))
    if payload_run_id != claim.run_id:
        raise PublicationResumeError(
            "publication_resume payload run_id disagrees with the claimed job"
        )
    if claim.resource_id is not None and resource_id != claim.resource_id:
        raise PublicationResumeError(
            "publication_resume payload resource_id disagrees with the claimed job"
        )

    state = get_resource_state(control_conn, resource_id=resource_id)
    if state is None:
        raise PublicationResumeError(f"resource {resource_id} does not exist")
    current_state, current_version = state
    if current_state != EXPECTED_STATE:
        raise PublicationResumeError(
            f"resource {resource_id} is {current_state!r}, not {EXPECTED_STATE!r} — "
            "either phase A has not finished or another worker already resumed it"
        )
    if int(payload["expected_state_version"]) != current_version:
        raise PublicationResumeError(
            f"resource {resource_id} is at version {current_version}, the job "
            f"expected {payload['expected_state_version']} — refusing to publish "
            "against a state that moved since the job was created"
        )

    artifact_record = find_latest_artifact(control_conn, resource_id=resource_id)
    if artifact_record is None:
        raise PublicationResumeError(f"resource {resource_id} has no stored artifact")

    durable_facts = collect_publication_facts(
        control_conn,
        resource_id=resource_id,
        artifact_id=artifact_record.artifact_id,
    )
    if deps.placement_resolver is not None:
        if not deps.manifest_digest:
            raise PublicationResumeError(
                "the governed placement requires the approved profile manifest digest"
            )
        collection, profile_version, school_year = _load_run_placement_context(
            control_conn,
            run_id=payload_run_id,
        )
        if collection != durable_facts.collection:
            raise PublicationResumeError(
                "the ingestion run collection disagrees with the durable publication facts"
            )
        resolver_kwargs: dict[str, Any] = {
            "content_sha256": artifact_record.sha256,
            "collection": collection,
            "profile_version": profile_version,
            "school_year": school_year,
            "claimed_source_url": durable_facts.canonical_url,
            "claimed_type_doc": durable_facts.type_doc,
        }
        if payload.get("source_path") is not None:
            resolver_kwargs["claimed_source_path"] = str(payload["source_path"])
        verified = deps.placement_resolver.resolve(**resolver_kwargs)
        placements = (
            to_eligible_placement(
                verified,
                resource_id=resource_id,
                current_profile_manifest_digest=deps.manifest_digest,
            ),
        )
    else:
        raise PublicationResumeError(
            f"resource {resource_id} has no governed placement resolver"
        )
    if not placements:
        raise PublicationResumeError(
            f"resource {resource_id} has no eligible placement; publishing content "
            "no collection claims would make it unreachable and unattributable"
        )
    governed_source_paths = {placement.source_path for placement in placements}
    if len(governed_source_paths) != 1:
        raise PublicationResumeError(
            f"resource {resource_id} resolves to conflicting sealed source paths"
        )
    governed_source_path = next(iter(governed_source_paths))
    claimed_source_path = payload.get("source_path")
    if claimed_source_path is not None and str(claimed_source_path) != governed_source_path:
        raise PublicationResumeError(
            "the job source_path disagrees with the sealed pedagogical placement"
        )
    governed_source_uris = {placement.source_uri for placement in placements}
    if len(governed_source_uris) != 1:
        raise PublicationResumeError(
            f"resource {resource_id} resolves to conflicting governed source URIs"
        )
    governed_source_uri = next(iter(governed_source_uris))

    if governed_source_uri != durable_facts.canonical_url:
        raise PublicationResumeError(
            "the governed placement source URI disagrees with the durable canonical URL"
        )

    # Les clairances qui justifiaient la mise en revue doivent tenir
    # encore : une preuve remplacée entre-temps invalide la publication.
    pii_registry, rights_registry = deps.require_sealed_evidence()
    pii_registry.verify_content_clearance(artifact_record.sha256)
    rights_clearance = rights_registry.resolve_rights(
        content_sha256=artifact_record.sha256,
        source_path=governed_source_path,
    )

    # Les droits publiés sont ceux que le fait durable porte, et ils doivent
    # coïncider avec ce que le registre résout aujourd'hui. Publier la
    # valeur du registre seule laisserait une dérive du registre réécrire
    # silencieusement des droits déjà attestés ; publier le fait durable
    # seul ignorerait une restriction apparue depuis.
    durable_rights = durable_facts.rights_status.value
    if str(durable_rights) != rights_clearance.rights.value:
        raise PublicationResumeError(
            f"durable rights {durable_rights!r} disagree with the registry's "
            f"{rights_clearance.rights.value!r} for content "
            f"{artifact_record.sha256} — refusing rather than choosing one"
        )

    attribution, _digest = load_artifact_attribution(
        control_conn, ingestion_artifact_id=artifact_record.artifact_id
    )

    raw_bytes = deps.artifact_reader(
        extracted_text_ref=artifact_record.extracted_text_ref
    )

    governed = GovernedArtifact(
        content=raw_bytes,
        content_sha256=artifact_record.sha256,
        source_label=attribution.source_label,
        source_uri=governed_source_uri,
        rights=str(durable_rights),
        official=attribution.official,
        source_kind=attribution.source_kind,
        type_doc=attribution.type_doc,
        mime_detected=artifact_record.mime_detected,
    )

    # Les lectures de préflight ci-dessus ouvrent une transaction psycopg.
    # La promotion et le publisher gèrent chacun leurs propres transactions
    # racines et exigent donc une connexion control IDLE à leur entrée.
    control_conn.commit()

    promotion = promote_reviewed_publication(
        control_conn,
        resource_id=resource_id,
        run_id=payload_run_id,
        expected_version=current_version,
        actor=deps.owner,
        current_content_sha256=artifact_record.sha256,
        current_profile_fingerprint=placements[0].current_profile_fingerprint,
        current_manifest_digest=deps.manifest_digest
        or placements[0].current_manifest_digest,
        job_id=claim.job_id,
        expected_attestation_id=UUID(str(payload["publication_attestation_id"])),
    )
    if str(promotion.attestation.attestation_id) != str(
        payload["publication_attestation_id"]
    ):
        raise PublicationResumeError(
            "the attestation verified live is not the one the job names — refusing "
            "rather than publishing under a review the job did not cite"
        )

    with psycopg.connect(deps.product_dsn) as product_conn:
        result = publish_governed_artifact(
            control_conn,
            product_conn,
            governed,
            placements,
            deps.extract_text,
            deps.embedding_provider,
        )

    return PublicationResumeOutcome(
        worked=True,
        job_id=claim.job_id,
        status="succeeded",
        error=None,
        artifact_id=result.artifact_id,
        chunk_rows=result.chunk_rows,
        placement_rows=result.placement_rows,
    )


def run_publication_resume_iteration(
    control_conn: psycopg.Connection,
    *,
    deps: PublicationResumeDeps,
    build_placements: Any = None,
) -> PublicationResumeOutcome:
    """Une itération : réclame un job de reprise, publie, complète.

    Ne réclame que ``publication_resume`` : Phase A et Phase B ne peuvent
    pas se voler leurs jobs."""
    claim = claim_job(
        control_conn,
        owner=deps.owner,
        job_types=(PUBLICATION_RESUME_JOB_TYPE,),
    )
    if claim is None:
        return PublicationResumeOutcome(
            worked=False, job_id=None, status=None, error=None
        )

    # Le claim est rendu durable tout de suite. Le garder dans la même
    # transaction que la vérification GitHub, l'extraction et les
    # embeddings maintiendrait une transaction ouverte pendant des
    # minutes — et ``publish_governed_artifact`` exige de toute façon une
    # connexion control *idle*.
    control_conn.commit()

    try:
        outcome = resume_publication(
            control_conn, claim=claim, deps=deps, build_placements=build_placements
        )
    except JobLeaseConflictError:
        # Le bail a expiré pendant le travail : un autre worker a pu
        # reprendre le job. Terminer ici écraserait son verdict.
        control_conn.rollback()
        return PublicationResumeOutcome(
            worked=True,
            job_id=claim.job_id,
            status="lease_lost",
            error="lease expired during publication",
        )
    except Exception as exc:  # refus nommé, jamais silencieux
        control_conn.rollback()
        try:
            record_job_retry(
                control_conn,
                job_id=claim.job_id,
                lease_token=claim.lease_token,
                error=str(exc),
            )
            control_conn.commit()
        except JobLeaseConflictError:
            control_conn.rollback()
            return PublicationResumeOutcome(
                worked=True, job_id=claim.job_id, status="lease_lost", error=str(exc)
            )
        return PublicationResumeOutcome(
            worked=True, job_id=claim.job_id, status="retried", error=str(exc)
        )

    try:
        complete_job(
            control_conn,
            job_id=claim.job_id,
            lease_token=claim.lease_token,
            status="succeeded",
        )
        control_conn.commit()
    except JobLeaseConflictError:
        control_conn.rollback()
        return PublicationResumeOutcome(
            worked=True,
            job_id=claim.job_id,
            status="lease_lost",
            error="lease expired before completion",
        )
    return outcome


__all__ = [
    "EXPECTED_STATE",
    "PUBLICATION_RESUME_JOB_TYPE",
    "REQUIRED_PAYLOAD_FIELDS",
    "PublicationResumeDeps",
    "PublicationResumeError",
    "PublicationResumeOutcome",
    "resume_publication",
    "run_publication_resume_iteration",
]
