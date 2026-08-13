"""Attribution durable d'un artefact d'ingestion (LOT H2-F, défaut 6).

**Ce que ce module résout.** Quatre faits — ``source_label``, ``official``,
``source_kind``, ``type_doc`` — décrivent *qui publie quoi*. Ils voyagent
jusqu'à ``public.rag_chunks`` et sont lus par le retrieval. Jusqu'ici ils
n'étaient produits nulle part dans le plan de contrôle : le publisher les
recevait de son appelant, et ``collect_publication_facts`` allait les
chercher dans ``public.rag_artifacts`` — une table qui n'existe pas encore
au moment de l'attestation (première publication) et que le rôle
``ingestion_control_attestor`` n'a jamais le droit de lire. Une attestation
scellait donc une publication dont l'attribution n'était ni revue, ni même
lisible.

**Où ils deviennent définitifs.** Chacun des quatre est dérivé d'une source
déjà gouvernée, jamais d'un texte libre d'opérateur :

===============  ==========================================================
``source_label`` ``candidate.publisher`` sinon ``candidate.domain`` — le
                 ``ResourceCandidate`` persisté par Scout (migration 006).
``official``     ``profile.source_authority == "official"`` — exactement le
                 fait de profil que ``assess_rights_core`` consomme déjà
                 pour décider des droits ; le profil lui-même est celui du
                 manifest approuvé, confronté à l'autorisation LOT41A au
                 point de contrôle ``pre_fetch``.
``source_kind``  ``candidate.domain`` — confronté à ``allowed_domains`` de
                 l'autorisation au point de contrôle ``destination``, donc
                 déjà borné par la revue humaine.
``type_doc``     ``candidate.proposed_type_doc``, **exigé** parmi
                 ``profile.expected_resource_types``. C'est cette
                 confrontation qui transforme une proposition de Scout en
                 fait : sans elle, un type hors périmètre du profil
                 traverserait la chaîne sans jamais être confronté à
                 quoi que ce soit.
===============  ==========================================================

**Quand ils sont écrits.** Le seul instant où les quatre sont
simultanément définitifs *et* antérieurs à toute attestation est le
franchissement du gate de routage (``QUALITY_CHECKED -> ROUTED``) : avant
lui ``type_doc`` n'est qu'une proposition et la ressource peut encore être
rejetée ; après lui plus aucune étape du pipeline ne touche à ces quatre
faits, et l'étape suivante est la mise en revue de publication. Le writer
est donc appelé par ``ingestion_worker.runner`` dans la **même
transaction** que la transition ``ROUTED`` et que l'événement
``PUBLICATION_GATE_EVALUATED`` — les trois écritures committent ensemble
ou aucune.

**Immuabilité.** Le digest canonique des quatre faits est une colonne
*générée* (migration 012) : aucun rôle ne peut l'écrire. Il est recalculé
ici en Python pour la comparaison — toute divergence entre les deux
implémentations fait échouer l'écriture plutôt que de passer inaperçue.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

import psycopg
from nexus_contracts.document import TypeDoc
from nexus_contracts.ingestion import CollectionProfile, ResourceCandidate

#: Version du protocole de digest — préfixe des octets canoniques, dupliqué
#: à l'identique dans ``ingestion_control.artifact_attribution_digest``
#: (migration 012). Les deux implémentations sont comparées à chaque
#: écriture ; une divergence est une erreur, jamais une tolérance.
ATTRIBUTION_PROTOCOL_VERSION = "NEXUS-ATTRIBUTION-V1"

#: Bornes alignées sur les ``CHECK`` de la migration 012 — refusées ici
#: avant l'aller-retour base, pour que le message nomme le champ fautif.
_MAX_LENGTHS = {"source_label": 512, "source_kind": 256, "type_doc": 128}


class ArtifactAttributionError(RuntimeError):
    """L'attribution ne peut pas être dérivée ou persistée telle quelle —
    fail-closed. Aucune valeur par défaut ne comble un fait manquant : une
    ressource sans attribution gouvernée n'est simplement jamais
    publiable."""


def _canonical_part(value: str) -> str:
    """Longueur en caractères, puis la valeur. Un séparateur présent dans
    une valeur ne peut donc jamais imiter la structure du document."""
    return f"{len(value)}:{value}"


def attribution_digest(
    *,
    ingestion_artifact_id: UUID,
    source_label: str,
    official: bool,
    source_kind: str,
    type_doc: str,
) -> str:
    """SHA-256 canonique des quatre faits, lié à l'artefact d'ingestion.

    Reproduit exactement ``ingestion_control.artifact_attribution_digest``
    (migration 012). L'identifiant fait partie du document : un digest ne
    peut jamais être recyclé d'un artefact vers un autre."""
    document = "|".join(
        (
            ATTRIBUTION_PROTOCOL_VERSION,
            _canonical_part(str(ingestion_artifact_id)),
            _canonical_part(source_label),
            _canonical_part("true" if official else "false"),
            _canonical_part(source_kind),
            _canonical_part(type_doc),
        )
    )
    return hashlib.sha256(document.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ArtifactAttribution:
    """Les quatre faits, déjà validés, liés à leur artefact d'ingestion."""

    ingestion_artifact_id: UUID
    source_label: str
    official: bool
    source_kind: str
    type_doc: str

    def __post_init__(self) -> None:
        if not isinstance(self.ingestion_artifact_id, UUID):
            raise ArtifactAttributionError(
                "ingestion_artifact_id must be the UUID of an "
                "ingestion_control.artifacts row — never the published "
                "artifact_id, which is the content SHA-256"
            )
        if not isinstance(self.official, bool):
            raise ArtifactAttributionError("official must be a boolean")
        for field, limit in _MAX_LENGTHS.items():
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ArtifactAttributionError(
                    f"{field} must be a non-empty, non-blank string"
                )
            if len(value) > limit:
                raise ArtifactAttributionError(
                    f"{field} exceeds the {limit}-character governed bound"
                )
        try:
            TypeDoc(self.type_doc)
        except ValueError as exc:
            raise ArtifactAttributionError(
                f"type_doc {self.type_doc!r} is not a canonical TypeDoc value"
            ) from exc

    @property
    def digest(self) -> str:
        return attribution_digest(
            ingestion_artifact_id=self.ingestion_artifact_id,
            source_label=self.source_label,
            official=self.official,
            source_kind=self.source_kind,
            type_doc=self.type_doc,
        )


def derive_artifact_attribution(
    *,
    ingestion_artifact_id: UUID,
    candidate: ResourceCandidate,
    profile: CollectionProfile,
) -> ArtifactAttribution:
    """Dérive les quatre faits depuis le candidat persisté et le profil
    approuvé — aucune E/S, aucun argument libre.

    ``type_doc`` est refusé s'il sort du périmètre déclaré par le profil :
    c'est la seule confrontation qui distingue le type *proposé* par Scout
    d'un type *gouverné*."""
    proposed = str(getattr(candidate.proposed_type_doc, "value", candidate.proposed_type_doc))
    expected = tuple(
        str(getattr(value, "value", value)) for value in profile.expected_resource_types
    )
    if proposed not in expected:
        raise ArtifactAttributionError(
            f"proposed_type_doc {proposed!r} is not among the resource types "
            f"expected by profile {profile.scope.collection}/"
            f"{profile.profile_version} ({list(expected)!r}) — a type nobody "
            "authorized never becomes a durable attribution"
        )

    publisher = (candidate.publisher or "").strip()
    source_label = publisher or candidate.domain.strip()

    return ArtifactAttribution(
        ingestion_artifact_id=ingestion_artifact_id,
        source_label=source_label,
        official=profile.source_authority == "official",
        source_kind=candidate.domain.strip(),
        type_doc=proposed,
    )


def lock_artifact_attribution(
    conn: psycopg.Connection, *, ingestion_artifact_id: UUID
) -> None:
    """Sérialise writer et attestation sur le même artefact.

    Un verrou *advisory* transactionnel, pas un ``SELECT ... FOR SHARE`` :
    PostgreSQL exige le privilège ``UPDATE`` pour verrouiller une ligne,
    or le rôle attestor ne l'a pas — et ne doit jamais l'avoir. Le verrou
    advisory est donc le seul mécanisme que les deux rôles peuvent prendre
    ensemble sans que l'un reçoive un droit d'écriture qu'il n'a pas à
    détenir. Même motif que les fences de ``governed_publisher_v2``."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"nexus:artifact-attribution:{ingestion_artifact_id}",),
        )


def _artifact_resource_id(
    conn: psycopg.Connection, *, ingestion_artifact_id: UUID
) -> UUID:
    """Verrouille l'artefact d'ingestion et rend sa ressource.

    ``FOR SHARE`` — pas seulement un ``SELECT`` : l'existence de l'artefact
    doit rester vraie jusqu'au commit de l'attribution qui le référence."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT resource_id FROM ingestion_control.artifacts "
            "WHERE artifact_id = %s FOR SHARE",
            (ingestion_artifact_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise ArtifactAttributionError(
            f"ingestion artifact {ingestion_artifact_id} does not exist — an "
            "attribution is never recorded for an artifact the pipeline never "
            "produced (a published artifact_id, being a content SHA-256, "
            "always lands here)"
        )
    resource_id: UUID = row[0]
    return resource_id


def persist_artifact_attribution(
    conn: psycopg.Connection,
    *,
    attribution: ArtifactAttribution,
    run_id: UUID,
    actor: str,
) -> str:
    """Écrit les quatre faits dans ``ingestion_control.artifact_attributions``
    et rend leur digest canonique.

    Ne committe pas — même convention que toutes les primitives
    ``ingestion_control`` : l'appelant possède la transaction, de sorte que
    l'attribution, la transition ``ROUTED`` et l'événement de gate soient
    durables ensemble ou pas du tout.

    Idempotence : une réécriture strictement identique est un no-op. Une
    réécriture divergente est un ``UPDATE`` — accepté avant attestation,
    refusé par le trigger de la migration 012 après.

    N'écrit jamais dans ``public.rag_artifacts`` : le plan de données est
    hors de portée du rôle applicatif du plan de contrôle, et le publisher
    y recopie ces valeurs plus tard sans jamais les redécider.
    """
    if not isinstance(attribution, ArtifactAttribution):
        raise TypeError("attribution must be an ArtifactAttribution")
    if not isinstance(run_id, UUID):
        raise ArtifactAttributionError("run_id must be a UUID")
    if not isinstance(actor, str) or not actor.strip():
        raise ArtifactAttributionError("actor must be a non-empty string")

    expected_digest = attribution.digest
    # Avant toute décision d'écriture : deux writers concurrents sur le même
    # artefact sont sérialisés, et une attestation concurrente (qui prend le
    # même verrou) ne peut pas s'intercaler entre la lecture des faits
    # qu'elle scelle et leur réécriture.
    lock_artifact_attribution(
        conn, ingestion_artifact_id=attribution.ingestion_artifact_id
    )
    resource_id = _artifact_resource_id(
        conn, ingestion_artifact_id=attribution.ingestion_artifact_id
    )

    with conn.cursor() as cur:
        cur.execute(
            "SELECT attribution_digest FROM ingestion_control.artifact_attributions "
            "WHERE ingestion_artifact_id = %s FOR UPDATE",
            (attribution.ingestion_artifact_id,),
        )
        existing = cur.fetchone()

        if existing is None:
            cur.execute(
                """
                INSERT INTO ingestion_control.artifact_attributions (
                    ingestion_artifact_id, resource_id,
                    source_label, official, source_kind, type_doc,
                    recorded_by_run_id, recorded_by_actor
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    attribution.ingestion_artifact_id,
                    resource_id,
                    attribution.source_label,
                    attribution.official,
                    attribution.source_kind,
                    attribution.type_doc,
                    run_id,
                    actor,
                ),
            )
        elif existing[0] != expected_digest:
            cur.execute(
                """
                UPDATE ingestion_control.artifact_attributions
                SET source_label = %s, official = %s, source_kind = %s,
                    type_doc = %s, recorded_at = now(),
                    recorded_by_run_id = %s, recorded_by_actor = %s
                WHERE ingestion_artifact_id = %s
                """,
                (
                    attribution.source_label,
                    attribution.official,
                    attribution.source_kind,
                    attribution.type_doc,
                    run_id,
                    actor,
                    attribution.ingestion_artifact_id,
                ),
            )

        # Relecture systématique : le digest stocké est calculé par
        # PostgreSQL, celui attendu par Python. Les comparer à chaque
        # écriture est le seul moyen de garantir que les deux définitions
        # canoniques ne divergent jamais en silence.
        cur.execute(
            "SELECT attribution_digest, source_label, official, source_kind, type_doc "
            "FROM ingestion_control.artifact_attributions "
            "WHERE ingestion_artifact_id = %s",
            (attribution.ingestion_artifact_id,),
        )
        stored = cur.fetchone()

    if stored is None:  # pragma: no cover - l'écriture ci-dessus vient d'aboutir
        raise ArtifactAttributionError(
            f"attribution of ingestion artifact {attribution.ingestion_artifact_id} "
            "disappeared immediately after being written"
        )
    if tuple(stored) != (
        expected_digest,
        attribution.source_label,
        attribution.official,
        attribution.source_kind,
        attribution.type_doc,
    ):
        raise ArtifactAttributionError(
            f"attribution readback drift for ingestion artifact "
            f"{attribution.ingestion_artifact_id}: stored {tuple(stored)!r} does "
            f"not match the written facts (expected digest {expected_digest})"
        )
    return expected_digest


def load_artifact_attribution(
    conn: psycopg.Connection, *, ingestion_artifact_id: UUID, lock: bool = False
) -> tuple[ArtifactAttribution, str]:
    """Relit l'attribution persistée et son digest tel que stocké.

    ``lock=True`` prend le verrou advisory de l'artefact — utilisé par
    l'outil d'attestation, qui doit empêcher toute écriture concurrente
    entre la lecture des faits et l'écriture de l'attestation qui les
    scelle."""
    if lock:
        lock_artifact_attribution(conn, ingestion_artifact_id=ingestion_artifact_id)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_label, official, source_kind, type_doc, attribution_digest "
            "FROM ingestion_control.artifact_attributions "
            "WHERE ingestion_artifact_id = %s",
            (ingestion_artifact_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise ArtifactAttributionError(
            f"ingestion artifact {ingestion_artifact_id} has no control-plane "
            "attribution record — the governed pipeline must record it before "
            "any attestation (migration 012)"
        )
    source_label, official, source_kind, type_doc, stored_digest = row
    attribution = ArtifactAttribution(
        ingestion_artifact_id=ingestion_artifact_id,
        source_label=source_label,
        official=official,
        source_kind=source_kind,
        type_doc=type_doc,
    )
    if stored_digest != attribution.digest:
        raise ArtifactAttributionError(
            f"attribution digest drift for ingestion artifact "
            f"{ingestion_artifact_id}: stored {stored_digest!r}, recomputed "
            f"{attribution.digest!r}"
        )
    return attribution, str(stored_digest)


__all__ = [
    "ATTRIBUTION_PROTOCOL_VERSION",
    "ArtifactAttribution",
    "ArtifactAttributionError",
    "attribution_digest",
    "lock_artifact_attribution",
    "derive_artifact_attribution",
    "load_artifact_attribution",
    "persist_artifact_attribution",
]
