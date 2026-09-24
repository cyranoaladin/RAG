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
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import psycopg

if TYPE_CHECKING:
    from ingestor.ingestion_control.scope_authority import VerifiedAuthorization

ADOPTION_VERSION = "SEALED-RELEASE-ADOPTION-V1"
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

    def digest(self) -> str:
        """Identité du CONTENU adopté : un rejeu identique a la même empreinte."""
        document = {
            "adoption_version": ADOPTION_VERSION,
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


def load_acquired_rows(conn: psycopg.Connection, *, release_id: str) -> list[AcquiredRow]:
    lignes = conn.execute(
        "SELECT r.resource_id, a.artifact_id, a.sha256, r.collection, a.payload"
        "  FROM ingestion_control.resources r"
        "  JOIN ingestion_control.artifacts a USING (resource_id)"
        " WHERE r.pipeline_kind = %s"
        "   AND a.payload->>'release_id' = %s"
        " ORDER BY r.resource_id",
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


def load_adopted_rows(
    conn: psycopg.Connection, *, release_id: str
) -> list[tuple[UUID, UUID, str, str, dict[str, Any]]]:
    """Les lignes couvertes par un successeur, sous la forme que mesurent les
    faits batch : ``(resource_id, artifact_id, sha256, collection, payload)``.

    Le payload rendu est celui de la ligne ACQUISE, dont l'identité et
    l'actualité sont remplacées par celles que l'adoption nomme. La ligne
    acquise elle-même n'est jamais modifiée.
    """
    lignes = conn.execute(
        "SELECT r.resource_id, a.artifact_id, a.sha256, r.collection, a.payload,"
        "       ad.release_id, ad.release_manifest_sha256,"
        "       ad.artifacts_release_sha256, ad.candidate_inventory_sha256,"
        "       ad.artifact_transfer_manifest_sha256, ad.currentness,"
        "       ad.content_sha256, ad.collection, ad.placement_id,"
        "       pa.scope_authorization_id, pa.scope_authorization_digest,"
        "       pa.acquisition_scope_authorization_id"
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
        rendues.append((resource_id, artifact_id, str(sha256), str(collection), acquis))
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
        "   WHERE artifact_id = %s AND release_id = %s"
        ")",
        (artifact_id, release_id, artifact_id, release_id),
    ).fetchone()
    return bool(ligne and ligne[0])


__all__ = [
    "ADOPTION_VERSION",
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
]
