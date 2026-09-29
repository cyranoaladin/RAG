"""Adoption, par une release successeur, des placements acquis sous son prédécesseur.

ADR-0059 § 5. Les lignes acquises sont liées à leur release par le
``release_id`` de leur payload. Un successeur — mêmes octets, autorités
corrigées, identité neuve (ADR-0050) — ne peut les couvrir ni en réécrivant
ces payloads (réécriture silencieuse de faits historiques), ni en réingérant
les mêmes contenus (réingestion de convenance). Il les **adopte** : une ligne
en ajout seul dit qu'un placement acquis est couvert par le successeur, et
nomme les preuves du successeur qui le fondent.

L'adoption exige, placement par placement, l'égalité exacte de tout ce qui
n'est pas une autorité corrigée. Elle couvre l'ensemble ou rien : un écart
est un refus, jamais une adoption partielle.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg
from psycopg.types.json import Jsonb

if TYPE_CHECKING:
    from ingestor.ingestion_control.scope_authority import VerifiedAuthorization

ADOPTION_VERSION = "SEALED-RELEASE-ADOPTION-V1"
SUCCESSOR_CONTROL_ADOPTION_VERSION = "SEALED-RELEASE-ADOPTION-V2"
PUBLICATION_AUTHORITY_VERSION = "SEALED-RELEASE-PUBLICATION-AUTHORITY-V1"
SEALED_RELEASE_PIPELINE = "sealed_release_pipeline"

#: Ce qu'un successeur a le droit de changer : son identité, les autorités
#: qu'il corrige, et l'actualité du placement qui en découle. Rien d'autre.
IDENTITE_DU_SUCCESSEUR = frozenset(
    {
        "release_id",
        "release_manifest_sha256",
        "artifacts_release_sha256",
        "candidate_inventory_sha256",
        "artifact_transfer_manifest_sha256",
        "currentness",
    }
)
#: Ce que Worker A a écrit et que le successeur doit prescrire à l'identique.
FAITS_INVARIANTS = (
    "protocol_version",
    "pipeline_kind",
    "collection",
    "content_sha256",
    "placement_id",
    "source_placement_id",
    "external_document_type",
    "type_doc",
    "provenance_discovery_url",
    "provenance_artifact_url",
    "chunk_count",
    "review_status",
    "placement_status",
)
ACTUALITES_ADOPTABLES = frozenset({"current", "official_snapshot"})


class SealedReleaseAdoptionError(RuntimeError):
    """Refus explicite — jamais une adoption partielle ni un écrasement."""


@dataclass(frozen=True)
class AcquiredRow:
    """Une ligne acquise sous le prédécesseur, telle que la base la porte."""

    resource_id: UUID
    artifact_id: UUID
    content_sha256: str
    collection: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class SuccessorIdentity:
    """L'identité du successeur et les preuves qui fondent l'adoption."""

    release_id: str
    release_manifest_sha256: str
    artifacts_release_sha256: str
    candidate_inventory_sha256: str
    artifact_transfer_manifest_sha256: str
    currentness_evidence_sha256: str
    pii_evidence_sha256: str


@dataclass(frozen=True)
class AdoptionRow:
    resource_id: UUID
    artifact_id: UUID
    content_sha256: str
    collection: str
    placement_id: str
    currentness: str
    successor: SuccessorIdentity
    predecessor_release_id: str
    predecessor_release_manifest_sha256: str
    adoption_version: str = ADOPTION_VERSION
    successor_resource_id: UUID | None = None
    successor_artifact_id: UUID | None = None

    def digest(self) -> str:
        """Identité du CONTENU adopté : un rejeu identique a la même empreinte."""
        document = {
            "adoption_version": self.adoption_version,
            "resource_id": str(self.resource_id),
            "artifact_id": str(self.artifact_id),
            "content_sha256": self.content_sha256,
            "collection": self.collection,
            "placement_id": self.placement_id,
            "currentness": self.currentness,
            "successor": {
                "release_id": self.successor.release_id,
                "release_manifest_sha256": self.successor.release_manifest_sha256,
                "artifacts_release_sha256": self.successor.artifacts_release_sha256,
                "candidate_inventory_sha256": self.successor.candidate_inventory_sha256,
                "artifact_transfer_manifest_sha256": (
                    self.successor.artifact_transfer_manifest_sha256
                ),
                "currentness_evidence_sha256": self.successor.currentness_evidence_sha256,
                "pii_evidence_sha256": self.successor.pii_evidence_sha256,
            },
            "predecessor_release_id": self.predecessor_release_id,
            "predecessor_release_manifest_sha256": self.predecessor_release_manifest_sha256,
        }
        if self.adoption_version == SUCCESSOR_CONTROL_ADOPTION_VERSION:
            if self.successor_resource_id is None or self.successor_artifact_id is None:
                raise SealedReleaseAdoptionError("V2 requires both successor control identities")
            document["successor_resource_id"] = str(self.successor_resource_id)
            document["successor_artifact_id"] = str(self.successor_artifact_id)
        return hashlib.sha256(
            json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


def _cle(collection: object, content_sha256: object, placement_id: object) -> tuple[str, str, str]:
    return (str(collection), str(content_sha256), str(placement_id))


def plan_adoption(
    *,
    acquired: Sequence[AcquiredRow],
    successor_placements: Sequence[Mapping[str, Any]],
    successor: SuccessorIdentity,
    predecessor_release_id: str,
    predecessor_release_manifest_sha256: str,
) -> list[AdoptionRow]:
    """Apparie les placements acquis à ceux que le successeur prescrit.

    ``successor_placements`` est ce que Worker A écrirait pour le successeur
    (``sealed_placement_evidence``). L'appariement doit être une bijection,
    et chaque paire égale sur tous les ``FAITS_INVARIANTS``.
    """
    if successor.release_id == predecessor_release_id:
        raise SealedReleaseAdoptionError(
            "a release cannot adopt its own placements — adoption is for a successor"
        )
    if not acquired:
        raise SealedReleaseAdoptionError(
            f"no placement was acquired under {predecessor_release_id!r} — there "
            "is nothing to adopt"
        )
    manifestes = {str(row.payload.get("release_manifest_sha256")) for row in acquired}
    if manifestes != {predecessor_release_manifest_sha256}:
        raise SealedReleaseAdoptionError(
            f"the acquired rows name release manifest(s) {sorted(manifestes)!r}, "
            f"not the predecessor {predecessor_release_manifest_sha256!r}"
        )
    if successor.release_manifest_sha256 == predecessor_release_manifest_sha256:
        raise SealedReleaseAdoptionError(
            "the successor names the predecessor's manifest — it is the same release"
        )

    par_cle_acquis: dict[tuple[str, str, str], AcquiredRow] = {}
    for row in acquired:
        if row.payload.get("release_id") != predecessor_release_id:
            raise SealedReleaseAdoptionError(
                f"acquired row {row.resource_id} belongs to "
                f"{row.payload.get('release_id')!r}, not {predecessor_release_id!r}"
            )
        if row.collection != row.payload.get("collection") or row.content_sha256 != row.payload.get(
            "content_sha256"
        ):
            raise SealedReleaseAdoptionError(
                f"acquired row {row.resource_id} contradicts its own payload"
            )
        cle = _cle(row.collection, row.content_sha256, row.payload.get("placement_id"))
        if cle in par_cle_acquis:
            raise SealedReleaseAdoptionError(f"placement {cle!r} was acquired twice")
        par_cle_acquis[cle] = row

    par_cle_successeur: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for prescrit in successor_placements:
        if prescrit.get("release_id") != successor.release_id:
            raise SealedReleaseAdoptionError(
                "a prescribed placement does not belong to the successor"
            )
        cle = _cle(
            prescrit.get("collection"), prescrit.get("content_sha256"), prescrit.get("placement_id")
        )
        if cle in par_cle_successeur:
            raise SealedReleaseAdoptionError(f"placement {cle!r} is prescribed twice")
        par_cle_successeur[cle] = prescrit

    absents = sorted(set(par_cle_successeur) - set(par_cle_acquis))
    orphelins = sorted(set(par_cle_acquis) - set(par_cle_successeur))
    if absents or orphelins:
        raise SealedReleaseAdoptionError(
            f"the successor and the acquired placements are not in bijection: "
            f"{len(absents)} prescribed but never acquired, {len(orphelins)} acquired "
            "but not prescribed — an adoption covers the whole release or nothing"
        )

    lignes: list[AdoptionRow] = []
    for cle in sorted(par_cle_successeur):
        prescrit = par_cle_successeur[cle]
        acquis = par_cle_acquis[cle]
        ecarts = [
            (champ, acquis.payload.get(champ), prescrit.get(champ))
            for champ in FAITS_INVARIANTS
            if acquis.payload.get(champ) != prescrit.get(champ)
        ]
        if ecarts:
            details = "; ".join(f"{c}: acquired={a!r} successor={s!r}" for c, a, s in ecarts)
            raise SealedReleaseAdoptionError(
                f"placement {cle!r} differs from what was acquired ({details}) — a "
                "successor may correct authorities, not the placement itself"
            )
        actualite = str(prescrit.get("currentness"))
        if actualite not in ACTUALITES_ADOPTABLES:
            raise SealedReleaseAdoptionError(
                f"placement {cle!r} is prescribed with currentness {actualite!r}, "
                "which is never published"
            )
        lignes.append(
            AdoptionRow(
                resource_id=acquis.resource_id,
                artifact_id=acquis.artifact_id,
                content_sha256=acquis.content_sha256,
                collection=acquis.collection,
                placement_id=cle[2],
                currentness=actualite,
                successor=successor,
                predecessor_release_id=predecessor_release_id,
                predecessor_release_manifest_sha256=predecessor_release_manifest_sha256,
            )
        )
    return lignes


def _control_identity_document(row: AdoptionRow) -> str:
    """Canonical V2 input; the role is appended separately as a domain separator."""
    return json.dumps(
        {
            "version": SUCCESSOR_CONTROL_ADOPTION_VERSION,
            "release_id": row.successor.release_id,
            "placement_id": row.placement_id,
            "content_sha256": row.content_sha256,
            "collection": row.collection,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def successor_control_dedup_key(row: AdoptionRow) -> str:
    """Domain-separated from the V1 content SHA used as a resource dedup key."""
    return "successor-control-v2:" + hashlib.sha256(
        ("nexus:successor-control:dedup-key:v2\0" + _control_identity_document(row)).encode(
            "utf-8"
        )
    ).hexdigest()


def plan_successor_control_adoption(
    *,
    acquired: Sequence[AcquiredRow],
    successor_placements: Sequence[Mapping[str, Any]],
    successor: SuccessorIdentity,
    predecessor_release_id: str,
    predecessor_release_manifest_sha256: str,
) -> list[AdoptionRow]:
    """Plan a V2 adoption without changing the predecessor's V1 identity.

    UUIDv5 receives canonical UTF-8 JSON prefixed by a distinct role label.
    The release, placement, content SHA and collection are all bound. Ordering,
    clock and random state play no part in either identity.
    """
    prior = plan_adoption(
        acquired=acquired,
        successor_placements=successor_placements,
        successor=successor,
        predecessor_release_id=predecessor_release_id,
        predecessor_release_manifest_sha256=predecessor_release_manifest_sha256,
    )
    result = [
        replace(
            row,
            adoption_version=SUCCESSOR_CONTROL_ADOPTION_VERSION,
            successor_resource_id=uuid5(
                NAMESPACE_URL, "nexus:successor-control:resource:v2\0" +
                _control_identity_document(row),
            ),
            successor_artifact_id=uuid5(
                NAMESPACE_URL, "nexus:successor-control:artifact:v2\0" +
                _control_identity_document(row),
            ),
        )
        for row in prior
    ]
    if len({row.successor_resource_id for row in result}) != len(result):
        raise SealedReleaseAdoptionError("two V2 placements derive the same resource identity")
    if len({row.successor_artifact_id for row in result}) != len(result):
        raise SealedReleaseAdoptionError("two V2 placements derive the same artifact identity")
    if any(
        row.successor_resource_id == row.resource_id
        or row.successor_artifact_id == row.artifact_id
        for row in result
    ):
        raise SealedReleaseAdoptionError("V2 control identity collides with predecessor")
    return result


def successor_identity_schema_available(conn: psycopg.Connection) -> bool:
    """Detect 020 without querying a column that rollback 020 removes.

    V1 still runs after the governed rollback to schema head 019. A V2
    adoption separately requires this result to be true before any write.
    """
    row = conn.execute(
        "SELECT count(*) = 2 FROM pg_catalog.pg_attribute"
        " WHERE attrelid = 'ingestion_control.sealed_release_adoptions'::regclass"
        "   AND attname IN ('successor_resource_id', 'successor_artifact_id')"
        "   AND NOT attisdropped"
    ).fetchone()
    return bool(row and row[0])


def load_acquired_rows(conn: psycopg.Connection, *, release_id: str) -> list[AcquiredRow]:
    exclude_v2 = (
        "   AND NOT EXISTS ("
        "       SELECT 1 FROM ingestion_control.sealed_release_adoptions ad"
        "        WHERE ad.adoption_version = 'SEALED-RELEASE-ADOPTION-V2'"
        "          AND ad.successor_artifact_id = a.artifact_id"
        "   )"
        if successor_identity_schema_available(conn) else ""
    )
    lignes = conn.execute(
        "SELECT r.resource_id, a.artifact_id, a.sha256, r.collection, a.payload"
        "  FROM ingestion_control.resources r"
        "  JOIN ingestion_control.artifacts a USING (resource_id)"
        " WHERE r.pipeline_kind = %s"
        "   AND a.payload->>'release_id' = %s"
        + exclude_v2 + " ORDER BY r.resource_id",
        (SEALED_RELEASE_PIPELINE, release_id),
    ).fetchall()
    return [
        AcquiredRow(
            resource_id=resource_id,
            artifact_id=artifact_id,
            content_sha256=str(sha256),
            collection=str(collection),
            payload=dict(payload),
        )
        for resource_id, artifact_id, sha256, collection, payload in lignes
    ]


def persist_adoption(
    conn: psycopg.Connection, *, lignes: Iterable[AdoptionRow], adopted_by: str
) -> tuple[int, int]:
    """Écrit les adoptions. Un rejeu identique est reconnu ; un conflit refuse."""
    lignes = list(lignes)
    versions = {ligne.adoption_version for ligne in lignes}
    if versions == {SUCCESSOR_CONTROL_ADOPTION_VERSION}:
        raise SealedReleaseAdoptionError(
            "V2 requires persist_successor_control_adoption and the dedicated adopter role"
        )
    if versions != {ADOPTION_VERSION}:
        raise SealedReleaseAdoptionError("adoption rows must all use one supported version")
    ecrites = 0
    deja = 0
    for ligne in lignes:
        digest = ligne.digest()
        existante = conn.execute(
            "SELECT adoption_digest FROM ingestion_control.sealed_release_adoptions"
            " WHERE release_id = %s AND resource_id = %s AND artifact_id = %s",
            (ligne.successor.release_id, ligne.resource_id, ligne.artifact_id),
        ).fetchone()
        if existante is not None:
            if existante[0] != digest:
                raise SealedReleaseAdoptionError(
                    f"resource {ligne.resource_id} is already adopted by "
                    f"{ligne.successor.release_id!r} with other facts — refusing "
                    "rather than overwriting"
                )
            deja += 1
            continue
        conn.execute(
            "INSERT INTO ingestion_control.sealed_release_adoptions ("
            " adoption_id, adoption_version, release_id, release_manifest_sha256,"
            " artifacts_release_sha256, candidate_inventory_sha256,"
            " artifact_transfer_manifest_sha256, currentness_evidence_sha256,"
            " pii_evidence_sha256, predecessor_release_id,"
            " predecessor_release_manifest_sha256, resource_id, artifact_id,"
            " content_sha256, collection, placement_id, currentness, adopted_by,"
            " adoption_digest"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
            " %s, %s, %s, %s)",
            (
                uuid4(),
                ADOPTION_VERSION,
                ligne.successor.release_id,
                ligne.successor.release_manifest_sha256,
                ligne.successor.artifacts_release_sha256,
                ligne.successor.candidate_inventory_sha256,
                ligne.successor.artifact_transfer_manifest_sha256,
                ligne.successor.currentness_evidence_sha256,
                ligne.successor.pii_evidence_sha256,
                ligne.predecessor_release_id,
                ligne.predecessor_release_manifest_sha256,
                ligne.resource_id,
                ligne.artifact_id,
                ligne.content_sha256,
                ligne.collection,
                ligne.placement_id,
                ligne.currentness,
                adopted_by,
                digest,
            ),
        )
        ecrites += 1
    return ecrites, deja


_SCOPE_COLUMNS = (
    "tenant", "collection", "niveau", "voie", "matiere", "candidat",
    "audience", "visibility", "school_year", "programme_version",
)


def _successor_control_run_id(row: AdoptionRow) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        "nexus:successor-control:run:v2\0" +
        json.dumps(
            {"release_id": row.successor.release_id, "collection": row.collection},
            sort_keys=True, separators=(",", ":"),
        ),
    )


def persist_successor_control_adoption(
    conn: psycopg.Connection, *, lignes: Sequence[AdoptionRow], adopted_by: str
) -> tuple[int, int, int, int]:
    """Create V2 control metadata and lineage in the caller's single transaction.

    Every predecessor is read in the serializable transaction; no predecessor
    row is updated by the append-only adopter role.
    Existing successor identities are accepted only after immutable facts and
    the adoption digest agree. A failure at row N rolls the entire transaction
    back at the CLI boundary.
    """
    if not lignes or not adopted_by.strip():
        raise SealedReleaseAdoptionError("V2 requires placements and a named adopter")
    if any(
        row.adoption_version != SUCCESSOR_CONTROL_ADOPTION_VERSION
        or row.successor_resource_id is None
        or row.successor_artifact_id is None
        for row in lignes
    ):
        raise SealedReleaseAdoptionError("V2 requires both successor identities on every row")
    ecrites = deja = ressources_creees = artefacts_crees = 0
    for row in lignes:
        predecessor = conn.execute(
            "SELECT r.run_id, r.dedup_key, r.tenant, r.collection, r.niveau, r.voie,"
            " r.matiere, r.candidat, r.audience, r.visibility, r.school_year,"
            " r.programme_version, r.resource_state, r.pipeline_kind,"
            " a.sha256, a.size_bytes, a.mime_declared, a.mime_detected,"
            " a.original_url, a.final_url, a.payload, ir.profile_version"
            " FROM ingestion_control.resources r"
            " JOIN ingestion_control.artifacts a ON a.resource_id = r.resource_id"
            " JOIN ingestion_control.ingestion_runs ir ON ir.run_id = r.run_id"
            " WHERE r.resource_id = %s AND a.artifact_id = %s",
            (row.resource_id, row.artifact_id),
        ).fetchone()
        if predecessor is None:
            raise SealedReleaseAdoptionError("predecessor control pair no longer exists")
        (
            _old_run, old_dedup, *tail,
        ) = predecessor
        scope = tuple(tail[:10])
        _old_state, pipeline, sha, size, mime_declared, mime_detected, original_url, final_url, payload, profile = tail[10:]
        if (
            scope[1] != row.collection or sha != row.content_sha256
            or pipeline != SEALED_RELEASE_PIPELINE
            or payload.get("release_id") != row.predecessor_release_id
            or payload.get("placement_id") != row.placement_id
        ):
            raise SealedReleaseAdoptionError("predecessor metadata diverges from the V2 plan")
        run_id = _successor_control_run_id(row)
        new_dedup = successor_control_dedup_key(row)
        if new_dedup == old_dedup:
            raise SealedReleaseAdoptionError("successor dedup key collides with predecessor")
        existing_run = conn.execute(
            "SELECT tenant, collection, niveau, voie, matiere, candidat, audience,"
            " visibility, school_year, programme_version, profile_version, trigger, status"
            " FROM ingestion_control.ingestion_runs WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        expected_run = (*scope, profile, "manual", "succeeded")
        if existing_run is None:
            conn.execute(
                "INSERT INTO ingestion_control.ingestion_runs ("
                "run_id, tenant, collection, niveau, voie, matiere, candidat, audience,"
                " visibility, school_year, programme_version, profile_version, trigger, status"
                ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (run_id, *expected_run),
            )
        elif tuple(existing_run) != expected_run:
            raise SealedReleaseAdoptionError(f"control run {run_id} has divergent facts")
        existing_resource = conn.execute(
            "SELECT run_id, dedup_key, tenant, collection, niveau, voie, matiere,"
            " candidat, audience, visibility, school_year, programme_version, pipeline_kind"
            " FROM ingestion_control.resources WHERE resource_id = %s",
            (row.successor_resource_id,),
        ).fetchone()
        expected_resource = (run_id, new_dedup, *scope, SEALED_RELEASE_PIPELINE)
        if existing_resource is None:
            conn.execute(
                "INSERT INTO ingestion_control.resources ("
                "resource_id, run_id, dedup_key, tenant, collection, niveau, voie,"
                " matiere, candidat, audience, visibility, school_year, programme_version,"
                " resource_state, pipeline_kind"
                ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (row.successor_resource_id, *expected_resource[:-1], "NEEDS_REVIEW", SEALED_RELEASE_PIPELINE),
            )
            ressources_creees += 1
        elif tuple(existing_resource) != expected_resource:
            raise SealedReleaseAdoptionError(
                f"successor resource {row.successor_resource_id} has divergent facts"
            )
        successor_payload = dict(payload)
        successor_payload.update({
            "release_id": row.successor.release_id,
            "release_manifest_sha256": row.successor.release_manifest_sha256,
            "artifacts_release_sha256": row.successor.artifacts_release_sha256,
            "candidate_inventory_sha256": row.successor.candidate_inventory_sha256,
            "artifact_transfer_manifest_sha256": row.successor.artifact_transfer_manifest_sha256,
            "currentness": row.currentness,
        })
        artifact_facts = (
            row.successor_resource_id, run_id, sha, size, mime_declared,
            mime_detected, original_url, final_url, successor_payload,
        )
        existing_artifact = conn.execute(
            "SELECT resource_id, run_id, sha256, size_bytes, mime_declared,"
            " mime_detected, original_url, final_url, payload"
            " FROM ingestion_control.artifacts WHERE artifact_id = %s",
            (row.successor_artifact_id,),
        ).fetchone()
        if existing_artifact is None:
            conn.execute(
                "INSERT INTO ingestion_control.artifacts ("
                "artifact_id, resource_id, run_id, sha256, size_bytes, mime_declared,"
                " mime_detected, original_url, final_url, payload"
                ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (row.successor_artifact_id, *artifact_facts[:-1], Jsonb(successor_payload)),
            )
            artefacts_crees += 1
        elif tuple(existing_artifact) != artifact_facts:
            raise SealedReleaseAdoptionError(
                f"successor artifact {row.successor_artifact_id} has divergent facts"
            )
        predecessor_attribution = conn.execute(
            "SELECT source_label, official, source_kind, type_doc"
            " FROM ingestion_control.artifact_attributions"
            " WHERE ingestion_artifact_id = %s AND resource_id = %s",
            (row.artifact_id, row.resource_id),
        ).fetchone()
        if predecessor_attribution is None:
            raise SealedReleaseAdoptionError(
                f"predecessor artifact {row.artifact_id} has no governed attribution"
            )
        expected_attribution = (row.successor_resource_id, *predecessor_attribution)
        existing_attribution = conn.execute(
            "SELECT resource_id, source_label, official, source_kind, type_doc"
            " FROM ingestion_control.artifact_attributions"
            " WHERE ingestion_artifact_id = %s",
            (row.successor_artifact_id,),
        ).fetchone()
        if existing_attribution is None:
            conn.execute(
                "INSERT INTO ingestion_control.artifact_attributions ("
                "ingestion_artifact_id, resource_id, source_label, official, source_kind,"
                " type_doc, recorded_by_run_id, recorded_by_actor"
                ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (row.successor_artifact_id, *expected_attribution, run_id, adopted_by),
            )
        elif tuple(existing_attribution) != expected_attribution:
            raise SealedReleaseAdoptionError("successor attribution has divergent facts")
        digest = row.digest()
        existing_adoption = conn.execute(
            "SELECT adoption_digest, successor_resource_id, successor_artifact_id"
            " FROM ingestion_control.sealed_release_adoptions"
            " WHERE release_id = %s AND resource_id = %s AND artifact_id = %s",
            (row.successor.release_id, row.resource_id, row.artifact_id),
        ).fetchone()
        if existing_adoption is None:
            conn.execute(
                "INSERT INTO ingestion_control.sealed_release_adoptions ("
                "adoption_id, adoption_version, release_id, release_manifest_sha256,"
                " artifacts_release_sha256, candidate_inventory_sha256,"
                " artifact_transfer_manifest_sha256, currentness_evidence_sha256,"
                " pii_evidence_sha256, predecessor_release_id,"
                " predecessor_release_manifest_sha256, resource_id, artifact_id,"
                " successor_resource_id, successor_artifact_id, content_sha256,"
                " collection, placement_id, currentness, adopted_by, adoption_digest"
                ") VALUES (" + ", ".join(["%s"] * 21) + ")",
                (
                    uuid4(), row.adoption_version, row.successor.release_id,
                    row.successor.release_manifest_sha256,
                    row.successor.artifacts_release_sha256,
                    row.successor.candidate_inventory_sha256,
                    row.successor.artifact_transfer_manifest_sha256,
                    row.successor.currentness_evidence_sha256,
                    row.successor.pii_evidence_sha256,
                    row.predecessor_release_id, row.predecessor_release_manifest_sha256,
                    row.resource_id, row.artifact_id, row.successor_resource_id,
                    row.successor_artifact_id, row.content_sha256, row.collection,
                    row.placement_id, row.currentness, adopted_by, digest,
                ),
            )
            ecrites += 1
        elif tuple(existing_adoption) == (
            digest, row.successor_resource_id, row.successor_artifact_id
        ):
            deja += 1
        else:
            raise SealedReleaseAdoptionError("V2 adoption identity carries divergent facts")
        event_key = f"successor-control-v2:{row.successor_resource_id}"
        existing_event = conn.execute(
            "SELECT run_id, resource_id, event_type, actor, payload"
            " FROM ingestion_control.workflow_events WHERE idempotency_key = %s",
            (event_key,),
        ).fetchone()
        event_payload = {
            "adoption_version": SUCCESSOR_CONTROL_ADOPTION_VERSION,
            "adoption_digest": digest,
            "predecessor_resource_id": str(row.resource_id),
            "predecessor_artifact_id": str(row.artifact_id),
        }
        expected_event = (
            run_id, row.successor_resource_id, "successor_control_adopted",
            adopted_by, event_payload,
        )
        if existing_event is None:
            conn.execute(
                "INSERT INTO ingestion_control.workflow_events ("
                "run_id, resource_id, event_type, actor, payload, idempotency_key"
                ") VALUES (%s, %s, %s, %s, %s, %s)",
                (*expected_event[:-1], Jsonb(event_payload), event_key),
            )
        elif tuple(existing_event) != expected_event:
            raise SealedReleaseAdoptionError("successor adoption event has divergent facts")
    return ressources_creees, artefacts_crees, ecrites, deja


def load_adopted_rows(
    conn: psycopg.Connection, *, release_id: str
) -> list[tuple[UUID, UUID, str, str, dict[str, Any]]]:
    """Les lignes couvertes par un successeur, sous la forme que mesurent les
    faits batch : ``(resource_id, artifact_id, sha256, collection, payload)``.

    Le payload rendu est celui de la ligne ACQUISE, dont l'identité et
    l'actualité sont remplacées par celles que l'adoption nomme. La ligne
    acquise elle-même n'est jamais modifiée.
    """
    identity_columns = (
        "ad.successor_resource_id, ad.successor_artifact_id"
        if successor_identity_schema_available(conn)
        else "NULL::uuid, NULL::uuid"
    )
    lignes = conn.execute(
        "SELECT r.resource_id, a.artifact_id, a.sha256, r.collection, a.payload,"
        "       ad.release_id, ad.release_manifest_sha256,"
        "       ad.artifacts_release_sha256, ad.candidate_inventory_sha256,"
        "       ad.artifact_transfer_manifest_sha256, ad.currentness,"
        "       ad.content_sha256, ad.collection, ad.placement_id,"
        "       pa.scope_authorization_id, pa.scope_authorization_digest,"
        "       pa.acquisition_scope_authorization_id,"
        "       ad.adoption_version, " + identity_columns +
        "  FROM ingestion_control.sealed_release_adoptions ad"
        "  JOIN ingestion_control.resources r ON r.resource_id = ad.resource_id"
        "  JOIN ingestion_control.artifacts a ON a.artifact_id = ad.artifact_id"
        "  LEFT JOIN ingestion_control.sealed_release_publication_authorizations pa"
        "    ON pa.release_id = ad.release_id AND pa.resource_id = ad.resource_id"
        "   AND pa.artifact_id = ad.artifact_id"
        " WHERE ad.release_id = %s AND r.pipeline_kind = %s"
        " ORDER BY r.resource_id",
        (release_id, SEALED_RELEASE_PIPELINE),
    ).fetchall()
    rendues: list[tuple[UUID, UUID, str, str, dict[str, Any]]] = []
    for (
        resource_id, artifact_id, sha256, collection, payload,
        rel, manifeste, registre, inventaire, transfert, actualite,
        contenu_adopte, collection_adoptee, placement_adopte,
        autorite_publication, empreinte_publication, autorite_acquisition,
        version, successor_resource_id, successor_artifact_id,
    ) in lignes:
        acquis = dict(payload)
        if (
            contenu_adopte != sha256
            or collection_adoptee != collection
            or placement_adopte != acquis.get("placement_id")
        ):
            raise SealedReleaseAdoptionError(
                f"adoption of resource {resource_id} names another placement than "
                "the acquired row"
            )
        acquis.update(
            {
                "release_id": rel,
                "release_manifest_sha256": manifeste,
                "artifacts_release_sha256": registre,
                "candidate_inventory_sha256": inventaire,
                "artifact_transfer_manifest_sha256": transfert,
                "currentness": actualite,
            }
        )
        # ADR-0060 : l'autorité de PUBLICATION liée à ce placement, si le
        # successeur en a lié une, gouverne ce que les faits batch mesurent.
        # Le payload acquis n'est pas modifié ; la liaison doit nommer
        # l'autorité d'acquisition qu'il porte, faute de quoi elle décrit
        # une autre ligne.
        if autorite_publication is not None:
            if autorite_acquisition != payload.get("scope_authorization_id"):
                raise SealedReleaseAdoptionError(
                    f"publication authority of resource {resource_id} names another "
                    "acquisition authority than the acquired row"
                )
            acquis["scope_authorization_id"] = autorite_publication
            acquis["scope_authorization_digest"] = empreinte_publication
        if version == SUCCESSOR_CONTROL_ADOPTION_VERSION:
            if successor_resource_id is None or successor_artifact_id is None:
                raise SealedReleaseAdoptionError("V2 adoption lacks successor identities")
            successor_fact = conn.execute(
                "SELECT r.collection, a.resource_id, a.sha256, a.payload"
                " FROM ingestion_control.resources r"
                " JOIN ingestion_control.artifacts a ON a.resource_id = r.resource_id"
                " WHERE r.resource_id = %s AND a.artifact_id = %s",
                (successor_resource_id, successor_artifact_id),
            ).fetchone()
            expected_successor_payload = {
                "release_id": rel,
                "release_manifest_sha256": manifeste,
                "artifacts_release_sha256": registre,
                "candidate_inventory_sha256": inventaire,
                "artifact_transfer_manifest_sha256": transfert,
                "content_sha256": contenu_adopte,
                "collection": collection_adoptee,
                "placement_id": placement_adopte,
                "currentness": actualite,
            }
            if successor_fact is None or (
                successor_fact[0] != collection
                or successor_fact[1] != successor_resource_id
                or successor_fact[2] != sha256
                or any(
                    successor_fact[3].get(name) != value
                    for name, value in expected_successor_payload.items()
                )
            ):
                raise SealedReleaseAdoptionError(
                    f"V2 successor control pair for {resource_id} has divergent facts"
                )
            rendues.append((
                successor_resource_id, successor_artifact_id, str(sha256),
                str(collection), acquis,
            ))
        elif version == ADOPTION_VERSION:
            if successor_resource_id is not None or successor_artifact_id is not None:
                raise SealedReleaseAdoptionError("V1 adoption unexpectedly has successor identities")
            rendues.append((resource_id, artifact_id, str(sha256), str(collection), acquis))
        else:
            raise SealedReleaseAdoptionError(f"unsupported adoption version {version!r}")
    liees = sum(1 for ligne in lignes if ligne[14] is not None)
    if liees not in (0, len(lignes)):
        raise SealedReleaseAdoptionError(
            f"successor {release_id!r} binds a publication authority to {liees} of "
            f"{len(lignes)} adopted placement(s) — all or none, never a mixture"
        )
    return rendues


def require_publication_authority_covers(
    authorization: VerifiedAuthorization, *, content_sha256: str, collection: str
) -> None:
    """Une autorité de publication couvre CE contenu, dans CETTE collection.

    Elle est liée au contenu (LOT41A-V2) : une autorisation V1 ne décrit
    aucune frontière de contenu et ne fonde donc aucune publication."""
    if authorization.protocol_version != "LOT41A-V2":
        raise SealedReleaseAdoptionError(
            f"authorization {authorization.authorization_id!r} is "
            f"{authorization.protocol_version}; a publication requires LOT41A-V2"
        )
    if content_sha256 not in (authorization.allowed_content_sha256 or ()):
        raise SealedReleaseAdoptionError(
            f"authorization {authorization.authorization_id!r} does not name content "
            f"{content_sha256}"
        )
    if getattr(authorization.scope, "collection", None) != collection:
        raise SealedReleaseAdoptionError(
            f"authorization {authorization.authorization_id!r} covers collection "
            f"{getattr(authorization.scope, 'collection', None)!r}, not {collection!r}"
        )


def bind_publication_authorities(
    conn: psycopg.Connection,
    *,
    release_id: str,
    authorities: Mapping[str, VerifiedAuthorization],
    bound_by: str,
) -> tuple[int, int]:
    """Lie à chaque placement adopté par ``release_id`` l'autorité de sa collection.

    ``authorities`` est indexé par collection et vient de
    ``verify_scope_authorization`` : revue vivante, artefact relu, fenêtre de
    validité, non-révocation. Rien n'est choisi par ancienneté ou par date :
    chaque collection nomme son autorité, et chaque placement doit y figurer.
    Un rejeu identique est reconnu ; un conflit refuse."""
    adoptions = conn.execute(
        "SELECT ad.resource_id, ad.artifact_id, ad.content_sha256, ad.collection,"
        "       a.payload->>'scope_authorization_id'"
        "  FROM ingestion_control.sealed_release_adoptions ad"
        "  JOIN ingestion_control.artifacts a ON a.artifact_id = ad.artifact_id"
        " WHERE ad.release_id = %s ORDER BY ad.resource_id",
        (release_id,),
    ).fetchall()
    if not adoptions:
        raise SealedReleaseAdoptionError(f"successor {release_id!r} has adopted nothing")
    sans_autorite = sorted({str(c) for _r, _a, _s, c, _p in adoptions} - set(authorities))
    if sans_autorite:
        raise SealedReleaseAdoptionError(
            f"no publication authority is named for collection(s) {sans_autorite}"
        )
    ecrites = 0
    deja = 0
    for resource_id, artifact_id, contenu, collection, acquisition in adoptions:
        autorite = authorities[str(collection)]
        require_publication_authority_covers(
            autorite, content_sha256=str(contenu), collection=str(collection)
        )
        if not acquisition:
            raise SealedReleaseAdoptionError(
                f"acquired row of resource {resource_id} names no acquisition authority"
            )
        digest = _digest_de_liaison(
            release_id=release_id, resource_id=resource_id, artifact_id=artifact_id,
            content_sha256=str(contenu), collection=str(collection),
            acquisition=str(acquisition), autorite=autorite,
        )
        existante = conn.execute(
            "SELECT binding_digest FROM ingestion_control.sealed_release_publication_authorizations"
            " WHERE release_id = %s AND resource_id = %s AND artifact_id = %s",
            (release_id, resource_id, artifact_id),
        ).fetchone()
        if existante is not None:
            if existante[0] != digest:
                raise SealedReleaseAdoptionError(
                    f"resource {resource_id} already carries another publication "
                    f"authority under {release_id!r} — refusing rather than overwriting"
                )
            deja += 1
            continue
        conn.execute(
            "INSERT INTO ingestion_control.sealed_release_publication_authorizations ("
            " binding_id, binding_version, release_id, resource_id, artifact_id,"
            " content_sha256, collection, acquisition_scope_authorization_id,"
            " scope_authorization_id, scope_authorization_digest, bound_by,"
            " binding_digest"
            ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                uuid4(), PUBLICATION_AUTHORITY_VERSION, release_id, resource_id,
                artifact_id, str(contenu), str(collection), str(acquisition),
                autorite.authorization_id, autorite.authorization_digest, bound_by,
                digest,
            ),
        )
        ecrites += 1
    return ecrites, deja


def _digest_de_liaison(
    *,
    release_id: str,
    resource_id: UUID,
    artifact_id: UUID,
    content_sha256: str,
    collection: str,
    acquisition: str,
    autorite: VerifiedAuthorization,
) -> str:
    document = {
        "binding_version": PUBLICATION_AUTHORITY_VERSION,
        "release_id": release_id,
        "resource_id": str(resource_id),
        "artifact_id": str(artifact_id),
        "content_sha256": content_sha256,
        "collection": collection,
        "acquisition_scope_authorization_id": acquisition,
        "scope_authorization_id": autorite.authorization_id,
        "scope_authorization_digest": autorite.authorization_digest,
    }
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def artifact_belongs_to_release(
    conn: psycopg.Connection, *, artifact_id: UUID, release_id: str
) -> bool:
    """L'artefact a-t-il été acquis sous cette release, ou adopté par elle ?"""
    ligne = conn.execute(
        "SELECT EXISTS ("
        "  SELECT 1 FROM ingestion_control.artifacts"
        "   WHERE artifact_id = %s AND payload->>'release_id' = %s"
        ") OR EXISTS ("
        "  SELECT 1 FROM ingestion_control.sealed_release_adoptions"
        "   WHERE ((adoption_version = 'SEALED-RELEASE-ADOPTION-V1'"
        "             AND artifact_id = %s)"
        "       OR (adoption_version = 'SEALED-RELEASE-ADOPTION-V2'"
        "             AND successor_artifact_id = %s))"
        "     AND release_id = %s"
        ")",
        (artifact_id, release_id, artifact_id, artifact_id, release_id),
    ).fetchone()
    return bool(ligne and ligne[0])


__all__ = [
    "ADOPTION_VERSION",
    "SUCCESSOR_CONTROL_ADOPTION_VERSION",
    "FAITS_INVARIANTS",
    "IDENTITE_DU_SUCCESSEUR",
    "AcquiredRow",
    "AdoptionRow",
    "SealedReleaseAdoptionError",
    "SuccessorIdentity",
    "artifact_belongs_to_release",
    "load_acquired_rows",
    "load_adopted_rows",
    "persist_adoption",
    "plan_adoption",
    "plan_successor_control_adoption",
    "successor_control_dedup_key",
]
