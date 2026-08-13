"""Faits durables de publication LOT42 (ADR-0033 § 3bis).

Remédiation GATE H1, item **E**.

**Le problème résolu ici.** L'outil d'attestation acceptait
``--content-sha256``, ``--rights-status``, ``--quality-passed``,
``--gate-passed``… en arguments libres. Un opérateur pouvait donc attester
une publication conforme pour une ressource dont le gate avait échoué :
rien dans la chaîne ne confrontait ces affirmations aux faits réellement
produits par le pipeline.

Ce module est la seule source de ces faits. Il ne lit que des données que
le pipeline a écrites lui-même :

- ``resources`` / ``artifacts`` / ``resource_candidates`` — collection,
  ``content_sha256``, ``canonical_url`` ;
- ``workflow_events`` (append-only, aucun UPDATE accordé à quiconque) —
  résultat des droits, résultat qualité, verdict du gate.

Il n'existe **aucun** paramètre par lequel un appelant pourrait fournir
l'une de ces valeurs. Une attestation se construit depuis
``collect_publication_facts`` ou ne se construit pas.

Chaque fait retenu porte l'``event_id`` de l'événement qui l'a produit :
l'artefact de revue les cite, et la relecture les recharge — une preuve
qui ne nomme pas son événement n'est pas une preuve.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from nexus_contracts.document import Rights

from .artifact_attribution import (
    ArtifactAttributionError,
    attribution_digest,
    load_artifact_attribution,
)

#: Valeur exacte écrite par ``transitions.apply_resource_transition`` —
#: jamais une constante parallèle réinventée ici.
_TRANSITION_EVENT_TYPE = "transition"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PublicationEvidenceMissingError(RuntimeError):
    """Le pipeline n'a pas produit tous les faits durables requis pour
    cette ressource — fail-closed. Une attestation ne peut jamais combler
    un fait manquant par une valeur par défaut ou une affirmation
    d'opérateur."""


@dataclass(frozen=True)
class PublicationFacts:
    """Ce que le pipeline a réellement produit, et rien d'autre.

    H2-F Défaut 6: Les quatre champs d'attribution (source_label,
    official, source_kind, type_doc) sont requis et vérifiés avant
    publication. Ils proviennent de ``ingestion_control
    .artifact_attributions`` — le plan de contrôle, écrit par le pipeline
    gouverné lui-même — jamais de ``public.rag_artifacts``, qui n'existe
    pas encore lors d'une première publication et que le rôle attestor n'a
    pas le droit de lire.
    """

    resource_id: UUID
    artifact_id: UUID
    collection: str
    canonical_url: str
    content_sha256: str
    content_event_id: UUID
    content_scope_authorization_id: str
    content_scope_authorization_digest: str
    content_scope_authorization_protocol_version: str
    rights_status: Rights
    rights_assessed_at: datetime
    rights_event_id: UUID
    quality_passed: bool
    quality_report_digest: str
    quality_assessed_at: datetime
    quality_event_id: UUID
    gate_passed: bool
    gate_name: str
    gate_evaluated_at: datetime
    gate_event_id: UUID
    # H2-F Défaut 6: Attribution durable liée aux faits revus
    source_label: str
    official: bool
    source_kind: str
    type_doc: str

    @property
    def attribution_digest(self) -> str:
        """Digest canonique des quatre faits d'attribution.

        C'est cette valeur que l'attestation mémorise et que le publisher
        recompare avant d'écrire : une attribution modifiée après revue
        change son digest, et la publication s'arrête."""
        return attribution_digest(
            ingestion_artifact_id=self.artifact_id,
            source_label=self.source_label,
            official=self.official,
            source_kind=self.source_kind,
            type_doc=self.type_doc,
        )

    @property
    def evidence_event_ids(self) -> tuple[str, ...]:
        """Triés — même ordre canonique que l'artefact de revue, de sorte
        que la comparaison DB ↔ artefact soit une simple égalité."""
        return tuple(
            sorted(
                {
                    str(self.rights_event_id),
                    str(self.quality_event_id),
                    str(self.gate_event_id),
                    str(self.content_event_id),
                }
            )
        )


def _latest_event(
    conn: psycopg.Connection,
    *,
    resource_id: UUID,
    event_type: str,
    to_state: str | None,
    required_key: str,
) -> tuple[UUID, dict[str, Any]]:
    """Dernier événement d'un type donné portant réellement le fait attendu.

    Le filtre ``payload ? required_key`` est délibéré : un événement du bon
    type mais dont le payload ne porte pas le fait (écrit par une version
    antérieure du pipeline, par exemple) ne doit pas être retenu et
    complété par une valeur devinée — il doit être invisible, et la
    ressource déclarée sans évidence."""
    clauses = ["resource_id = %(resource_id)s", "event_type = %(event_type)s"]
    params: dict[str, Any] = {"resource_id": resource_id, "event_type": event_type}
    if to_state is not None:
        clauses.append("to_state = %(to_state)s")
        params["to_state"] = to_state
    where = " AND ".join(clauses)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT event_id, payload FROM ingestion_control.workflow_events "  # noqa: S608 - clauses littérales, valeurs paramétrées
            f"WHERE {where} AND payload ? %(required_key)s "
            "ORDER BY occurred_at DESC, event_id DESC LIMIT 1",
            {**params, "required_key": required_key},
        )
        row = cur.fetchone()
    if row is None:
        event_label = f"{to_state} {event_type}" if to_state is not None else event_type
        raise PublicationEvidenceMissingError(
            f"resource {resource_id}: no {event_label} workflow event carrying "
            f"{required_key!r} — the pipeline never produced this fact, so it "
            "can never be attested"
        )
    event_id, payload = row
    if not isinstance(payload, dict):  # pragma: no cover - colonne JSONB, toujours un objet
        raise PublicationEvidenceMissingError(
            f"resource {resource_id}: {event_type} payload is not a JSON object"
        )
    return event_id, payload


def _require(payload: dict[str, Any], key: str, *, resource_id: UUID, event_type: str) -> Any:
    if key not in payload:
        raise PublicationEvidenceMissingError(
            f"resource {resource_id}: {event_type} payload is missing {key!r}"
        )
    return payload[key]


def _require_string(
    payload: dict[str, Any], key: str, *, resource_id: UUID, event_type: str
) -> str:
    value = _require(
        payload,
        key,
        resource_id=resource_id,
        event_type=event_type,
    )
    if not isinstance(value, str) or not value:
        raise PublicationEvidenceMissingError(
            f"resource {resource_id}: {event_type} payload {key!r} "
            "must be a non-empty string"
        )
    return value


def _parse_moment(value: Any, *, resource_id: UUID, label: str) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublicationEvidenceMissingError(
            f"resource {resource_id}: {label} is not an ISO-8601 instant: {value!r}"
        ) from exc


def collect_publication_facts(
    conn: psycopg.Connection, *, resource_id: UUID, artifact_id: UUID
) -> PublicationFacts:
    """Rassemble **tous** les faits durables de publication d'une ressource.

    Lève ``PublicationEvidenceMissingError`` dès qu'un seul manque : il n'y
    a pas d'évidence partielle acceptable. Retourne les faits tels quels,
    y compris négatifs (``quality_passed=False``, ``gate_passed=False``) —
    c'est à l'appelant de refuser, jamais à ce module de filtrer, pour que
    le refus soit visible et testable là où il compte."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT collection FROM ingestion_control.resources WHERE resource_id = %s",
            (resource_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise PublicationEvidenceMissingError(f"resource {resource_id} does not exist")
    (collection,) = row

    with conn.cursor() as cur:
        cur.execute(
            "SELECT sha256 FROM ingestion_control.artifacts "
            "WHERE artifact_id = %s AND resource_id = %s",
            (artifact_id, resource_id),
        )
        row = cur.fetchone()
    if row is None:
        raise PublicationEvidenceMissingError(
            f"artifact {artifact_id} does not belong to resource {resource_id}"
        )
    (content_sha256,) = row

    with conn.cursor() as cur:
        cur.execute(
            "SELECT canonical_url FROM ingestion_control.resource_candidates "
            "WHERE resource_id = %s ORDER BY discovered_at DESC, candidate_id DESC LIMIT 1",
            (resource_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise PublicationEvidenceMissingError(
            f"resource {resource_id} has no persisted resource_candidate"
        )
    (canonical_url,) = row

    content_event_id, content_payload = _latest_event(
        conn,
        resource_id=resource_id,
        event_type=_TRANSITION_EVENT_TYPE,
        to_state="FETCHED",
        required_key="sha256",
    )
    fetched_artifact_id = _require_string(
        content_payload,
        "artifact_id",
        resource_id=resource_id,
        event_type="FETCHED transition",
    )
    if fetched_artifact_id != str(artifact_id):
        raise PublicationEvidenceMissingError(
            f"resource {resource_id}: FETCHED artifact_id {fetched_artifact_id!r} "
            f"does not match artifact {artifact_id}"
        )
    fetched_sha256 = _require_string(
        content_payload,
        "sha256",
        resource_id=resource_id,
        event_type="FETCHED transition",
    )
    if _SHA256.fullmatch(fetched_sha256) is None or fetched_sha256 != content_sha256:
        raise PublicationEvidenceMissingError(
            f"resource {resource_id}: FETCHED sha256 does not match artifact {artifact_id}"
        )
    content_authorization_id = _require_string(
        content_payload,
        "scope_authorization_id",
        resource_id=resource_id,
        event_type="FETCHED transition",
    )
    content_authorization_digest = _require_string(
        content_payload,
        "scope_authorization_digest",
        resource_id=resource_id,
        event_type="FETCHED transition",
    )
    content_authorization_protocol = _require_string(
        content_payload,
        "scope_authorization_protocol_version",
        resource_id=resource_id,
        event_type="FETCHED transition",
    )
    if _SHA256.fullmatch(content_authorization_digest) is None:
        raise PublicationEvidenceMissingError(
            f"resource {resource_id}: FETCHED scope_authorization_digest is malformed"
        )
    if content_authorization_protocol not in {"LOT41A-V1", "LOT41A-V2"}:
        raise PublicationEvidenceMissingError(
            f"resource {resource_id}: FETCHED authority protocol is unsupported"
        )

    rights_event_id, rights_payload = _latest_event(
        conn,
        resource_id=resource_id,
        event_type=_TRANSITION_EVENT_TYPE,
        to_state="RIGHTS_CHECKED",
        required_key="rights_status",
    )
    quality_event_id, quality_payload = _latest_event(
        conn,
        resource_id=resource_id,
        event_type=_TRANSITION_EVENT_TYPE,
        to_state="QUALITY_CHECKED",
        required_key="quality_passed",
    )
    gate_event_id, gate_payload = _latest_event(
        conn,
        resource_id=resource_id,
        event_type="PUBLICATION_GATE_EVALUATED",
        to_state=None,
        required_key="gate_passed",
    )

    # H2-F (défaut 6) : l'attribution est lue dans le PLAN DE CONTRÔLE, sous
    # la clé canonique ``ingestion_artifact_id``. Jamais dans
    # ``public.rag_artifacts`` : cette table n'existe pas encore lors d'une
    # première publication (le publisher l'écrit *après* l'attestation) et
    # le rôle attestor n'a aucun privilège sur le schéma ``public``. La
    # lecture recalcule le digest canonique et refuse toute dérive entre
    # les quatre faits et le digest que PostgreSQL a généré pour eux.
    #
    # Lue APRÈS les faits du pipeline, délibérément : une ressource que le
    # pipeline n'a jamais menée jusqu'au gate doit être refusée en nommant
    # l'étape qui manque (droits, qualité, gate), pas son attribution — le
    # message d'un refus est ce qui rend ce refus diagnosticable.
    try:
        attribution, _stored_digest = load_artifact_attribution(
            conn, ingestion_artifact_id=artifact_id
        )
    except ArtifactAttributionError as exc:
        raise PublicationEvidenceMissingError(
            f"resource {resource_id}: {exc}"
        ) from exc

    rights_value = str(_require(
        rights_payload, "rights_status", resource_id=resource_id, event_type="RIGHTS_CHECKED transition"
    ))
    try:
        rights_status = Rights(rights_value)
    except ValueError as exc:
        raise PublicationEvidenceMissingError(
            f"resource {resource_id}: rights_status {rights_value!r} is not a known category"
        ) from exc

    return PublicationFacts(
        resource_id=resource_id,
        artifact_id=artifact_id,
        collection=collection,
        canonical_url=canonical_url,
        content_sha256=content_sha256,
        content_event_id=content_event_id,
        content_scope_authorization_id=content_authorization_id,
        content_scope_authorization_digest=content_authorization_digest,
        content_scope_authorization_protocol_version=content_authorization_protocol,
        rights_status=rights_status,
        rights_assessed_at=_parse_moment(
            _require(
                rights_payload, "rights_assessed_at",
                resource_id=resource_id, event_type="RIGHTS_CHECKED transition",
            ),
            resource_id=resource_id, label="rights_assessed_at",
        ),
        rights_event_id=rights_event_id,
        quality_passed=bool(_require(
            quality_payload, "quality_passed",
            resource_id=resource_id, event_type="QUALITY_CHECKED transition",
        )),
        quality_report_digest=str(_require(
            quality_payload, "quality_report_digest",
            resource_id=resource_id, event_type="QUALITY_CHECKED transition",
        )),
        quality_assessed_at=_parse_moment(
            _require(
                quality_payload, "quality_assessed_at",
                resource_id=resource_id, event_type="QUALITY_CHECKED transition",
            ),
            resource_id=resource_id, label="quality_assessed_at",
        ),
        quality_event_id=quality_event_id,
        gate_passed=bool(_require(
            gate_payload, "gate_passed",
            resource_id=resource_id, event_type="PUBLICATION_GATE_EVALUATED",
        )),
        gate_name=str(_require(
            gate_payload, "gate_name",
            resource_id=resource_id, event_type="PUBLICATION_GATE_EVALUATED",
        )),
        gate_evaluated_at=_parse_moment(
            _require(
                gate_payload, "gate_evaluated_at",
                resource_id=resource_id, event_type="PUBLICATION_GATE_EVALUATED",
            ),
            resource_id=resource_id, label="gate_evaluated_at",
        ),
        gate_event_id=gate_event_id,
        # H2-F Défaut 6 : attribution durable du plan de contrôle, écrite
        # par le pipeline gouverné avant toute attestation.
        source_label=attribution.source_label,
        official=attribution.official,
        source_kind=attribution.source_kind,
        type_doc=attribution.type_doc,
    )


__all__ = [
    "PublicationEvidenceMissingError",
    "PublicationFacts",
    "collect_publication_facts",
]
