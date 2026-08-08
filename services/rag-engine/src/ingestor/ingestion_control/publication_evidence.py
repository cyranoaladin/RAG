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

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from nexus_contracts.document import Rights

#: Valeur exacte écrite par ``transitions.apply_resource_transition`` —
#: jamais une constante parallèle réinventée ici.
_TRANSITION_EVENT_TYPE = "transition"


class PublicationEvidenceMissingError(RuntimeError):
    """Le pipeline n'a pas produit tous les faits durables requis pour
    cette ressource — fail-closed. Une attestation ne peut jamais combler
    un fait manquant par une valeur par défaut ou une affirmation
    d'opérateur."""


@dataclass(frozen=True)
class PublicationFacts:
    """Ce que le pipeline a réellement produit, et rien d'autre."""

    resource_id: UUID
    artifact_id: UUID
    collection: str
    canonical_url: str
    content_sha256: str
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
        raise PublicationEvidenceMissingError(
            f"resource {resource_id}: no {event_type} workflow event carrying "
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
    )


__all__ = [
    "PublicationEvidenceMissingError",
    "PublicationFacts",
    "collect_publication_facts",
]
