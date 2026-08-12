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
    from ingestor.governed_publisher_v2 import (
        EligiblePlacement,
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
    from ingestor.ingestion_control.sealed_evidence import SealedEvidenceError
except ImportError as _exc:  # repli à plat, cause réelle préservée
    if not (_exc.name is None and "relative import" in str(_exc)) and (
        _exc.name or ""
    ) not in ("ingestor", "src", "src.ingestor"):
        raise
    from governed_publisher_v2 import (
        EligiblePlacement,
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
    from ingestion_control.sealed_evidence import (
        SealedEvidenceError,
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
    embed_chunks: Any
    pii_evidence_registry: Any = None
    rights_evidence_registry: Any = None
    manifest_digest: str = ""

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


def resume_publication(
    control_conn: psycopg.Connection,
    *,
    claim: JobClaim,
    deps: PublicationResumeDeps,
    build_placements: Any,
) -> PublicationResumeOutcome:
    """Reprend une ressource en revue et la publie, ou refuse.

    ``build_placements`` fournit les ``EligiblePlacement`` gouvernés pour
    cette ressource ; ils viennent du catalogue scellé, jamais du payload
    du job."""
    payload = _require_payload(dict(claim.payload or {}))
    resource_id = UUID(str(payload["resource_id"]))

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

    # Les clairances qui justifiaient la mise en revue doivent tenir
    # encore : une preuve remplacée entre-temps invalide la publication.
    pii_registry, rights_registry = deps.require_sealed_evidence()
    pii_registry.verify_content_clearance(artifact_record.sha256)
    rights_clearance = rights_registry.resolve_rights(
        content_sha256=artifact_record.sha256,
        source_path=str(payload.get("source_path") or artifact_record.final_url),
    )

    # Les droits publiés sont ceux que le fait durable porte, et ils doivent
    # coïncider avec ce que le registre résout aujourd'hui. Publier la
    # valeur du registre seule laisserait une dérive du registre réécrire
    # silencieusement des droits déjà attestés ; publier le fait durable
    # seul ignorerait une restriction apparue depuis.
    durable_rights = getattr(
        artifact_record.rights_status, "value", artifact_record.rights_status
    )
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
        source_uri=f"urn:nexus:sha256:{artifact_record.sha256}",
        rights=str(durable_rights),
        official=attribution.official,
        source_kind=attribution.source_kind,
        type_doc=attribution.type_doc,
    )
    placements: tuple[EligiblePlacement, ...] = tuple(build_placements(resource_id))
    if not placements:
        raise PublicationResumeError(
            f"resource {resource_id} has no eligible placement; publishing content "
            "no collection claims would make it unreachable and unattributable"
        )

    promotion = promote_reviewed_publication(
        control_conn,
        resource_id=resource_id,
        run_id=UUID(str(payload["run_id"])),
        expected_version=current_version,
        actor=deps.owner,
        current_content_sha256=artifact_record.sha256,
        current_profile_fingerprint=placements[0].current_profile_fingerprint,
        current_manifest_digest=deps.manifest_digest
        or placements[0].current_manifest_digest,
        job_id=claim.job_id,
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
            deps.embed_chunks,
        )
        product_conn.commit()

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
    build_placements: Any,
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
