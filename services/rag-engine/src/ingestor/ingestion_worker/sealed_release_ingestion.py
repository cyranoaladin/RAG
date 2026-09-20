"""Point d'entrée d'ingestion pour une release SCELLÉE, jusqu'à ``NEEDS_REVIEW``.

**Pourquoi un second point d'entrée plutôt qu'un job de plus.** Le pipeline
``resource_pipeline`` DÉCOUVRE : une URL trouvée, une ressource, un
``proposed_type_doc`` proposé par Scout puis confronté au mapping gouverné.
C'est exact pour ce qu'on trouve sur le web.

Une release scellée est l'inverse : le corpus est déjà choisi, typé, chunké et
relu au scellement. Le faire passer par le front de découverte demandait deux
fabrications, mesurées sur ``production-profile-gate-2026-2027-v2`` :

  * **le type de document.** Les 315 artefacts ne sont annoncés que par 19
    pages de découverte, et un job est identifié par son URL. Un seul
    ``proposed_type_doc`` par job écraserait donc les six types réellement
    distincts que la release a scellés (``ressource_officielle``,
    ``programme_officiel``, ``modalite_examen``, ``diaporama``, ``annale``,
    ``autre``) ;
  * **l'URL canonique.** La release n'en connaît aucune par artefact ;
    promouvoir une page de provenance en identité de document affirmerait ce
    que personne n'a établi (ADR-0056 § 3).

Ce module itère donc sur les **placements** — la granularité à laquelle le
scope et le type sont gouvernés — lit les PDF du store déjà transféré et
vérifié plutôt que de recrawler, et pose
``pipeline_kind='sealed_release_pipeline'`` avec ``canonical_url = NULL``, ce
que la migration 014 rend non seulement possible mais OBLIGATOIRE pour cette
origine : une URL y serait refusée par la base elle-même.

**Ce qu'il ne fait pas.** Il ne publie rien. Il s'arrête à ``NEEDS_REVIEW``,
là où Phase A s'arrête, parce que la publication reste soumise à une
attestation LOT42 — ici le protocole batch d'ADR-0056. Il n'ouvre aucune
connexion vers la base produit, ne connaît pas ``PG_RAG_DSN``, et refuse de
s'exécuter en production.

**Ce qu'il refuse.** Tout, plutôt qu'une ingestion à moitié faite : un digest
qui diverge, un PDF absent du store, une collection sans autorisation LOT41A,
une collection en trop ou en moins, un compte qui ne tombe pas juste. Les
refus sont levés AVANT la première écriture.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import psycopg
from nexus_contracts.ingestion import ResourceScope
from nexus_contracts.resource_state import ResourceState

from ingestor.ingestion_control.provisioning import (
    SEALED_RELEASE_PIPELINE,
    create_ingestion_run,
    create_resource,
    persist_sealed_release_artifact,
    persist_sealed_release_candidate,
)
from ingestor.ingestion_control.scope_authority import (
    VerifiedAuthorization,
    verify_scope_authorization,
)
from ingestor.ingestion_control.transitions import cas_transition
from ingestor.ingestion_profiles.registry import ProfileRegistry

#: Le protocole sous lequel ces lignes sont écrites (ADR-0056). Il figure
#: dans chaque ``payload`` : une ligne dit d'elle-même sous quel régime elle
#: a été créée, sans qu'un lecteur ait à le déduire.
PROTOCOL_VERSION = "LOT42-RELEASE-BATCH-V1"

#: Le seul ``release_kind`` que ce point d'entrée accepte. Une release qui
#: n'est pas cet agrégat scellé n'est pas ce que ce module sait lire.
SEALED_RELEASE_KIND = "MULTILEVEL_AGGREGATE_RELEASE_V2"

#: L'état où Phase A s'arrête. Aller au-delà exige une attestation LOT42.
TERMINAL_STATE = ResourceState.NEEDS_REVIEW

#: La séquence que la machine d'états impose. ``DISCOVERED -> NEEDS_REVIEW``
#: est refusé par ``is_valid_resource_transition`` : les dix pas sont
#: obligatoires, et chacun laisse une trace dans ``workflow_events``.
STATE_SEQUENCE: tuple[ResourceState, ...] = (
    ResourceState.CANDIDATE,
    ResourceState.FETCHED,
    ResourceState.STORED,
    ResourceState.EXTRACTED,
    ResourceState.CLASSIFIED,
    ResourceState.RIGHTS_CHECKED,
    ResourceState.QUALITY_CHECKED,
    ResourceState.ROUTED,
    ResourceState.STAGED,
    TERMINAL_STATE,
)

PDF_MIME = "application/pdf"

#: Les quatre grandeurs que la release déclare et que ce module recompte.
EXPECTED_COUNT_KEYS = ("subjects", "unique_artifacts", "placements", "unique_chunks")

ScopeAuthorizationVerifier = Callable[..., VerifiedAuthorization]


class SealedReleaseIngestionError(RuntimeError):
    """Refus d'ingestion. Levé avant toute écriture — jamais après."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SealedReleaseIngestionError(message)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_with_digest(path: Path, expected: str, label: str) -> bytes:
    """Lire un fichier et refuser s'il n'est pas exactement celui annoncé."""
    _require(path.is_file(), f"{label} absent : {path}")
    raw = path.read_bytes()
    observed = _sha256(raw)
    _require(
        observed == expected,
        f"{label} : digest annoncé {expected}, observé {observed}",
    )
    return raw


@dataclass(frozen=True)
class SealedReleasePlacement:
    """Un placement de la release — l'unité gouvernée en scope et en type."""

    collection: str
    artifact_id: str
    placement_id: str
    source_placement_id: str
    #: Vocabulaire externe observé à la découverte (``ressource-accompagnement``,
    #: ``programme-officiel``, …). Conservé comme fait, jamais écrit tel quel
    #: dans ``proposed_type_doc`` : ce n'est pas le vocabulaire Nexus.
    external_document_type: str
    #: Le type Nexus que la release a scellé pour cet artefact — la valeur
    #: gouvernée, et la seule que ``TypeDoc`` reconnaisse.
    type_doc: str
    #: Page sur laquelle ce placement a été découvert.
    discovery_url: str
    #: URL d'où les octets proviennent — parfois la page, parfois le fichier
    #: direct. Provenance dans les deux cas, jamais une identité canonique.
    provenance_url: str
    chunk_count: int
    review_status: str
    placement_status: str
    currentness: str
    scope_dimensions: Mapping[str, str]


@dataclass(frozen=True)
class SealedReleaseFacts:
    """Ce que la release déclare, une fois chacun de ses digests vérifié."""

    release_id: str
    release_kind: str
    release_manifest_sha256: str
    artifacts_release_sha256: str
    candidate_inventory_sha256: str
    artifact_transfer_manifest_sha256: str
    expected_counts: Mapping[str, int]
    collections: tuple[str, ...]
    profile_versions: Mapping[str, str]
    artifact_ids: frozenset[str]
    transferred_artifact_ids: frozenset[str]
    placements: tuple[SealedReleasePlacement, ...]

    @property
    def unique_chunk_count(self) -> int:
        return sum(self.artifact_chunk_counts.values())

    @property
    def artifact_chunk_counts(self) -> Mapping[str, int]:
        return self._artifact_chunk_counts

    _artifact_chunk_counts: Mapping[str, int] = field(default_factory=dict)


@dataclass
class IngestionReport:
    """Le compte rendu — mesuré ligne à ligne, jamais recopié de la release."""

    release_id: str
    collections: tuple[str, ...] = ()
    runs: int = 0
    resources: int = 0
    resource_candidates: int = 0
    artifacts: int = 0
    workflow_events: int = 0
    unique_artifacts: int = 0
    placements: int = 0
    chunks: int = 0
    terminal_state: str = TERMINAL_STATE.value
    #: Ce module n'a aucun moyen d'écrire dans la base produit ni d'attester
    #: une publication. Ces deux compteurs restent donc à zéro par
    #: construction, et le rapport le dit explicitement.
    published_rows: int = 0
    attestations: int = 0
    placements_by_collection: dict[str, int] = field(default_factory=dict)
    resource_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "protocol_version": PROTOCOL_VERSION,
            "pipeline_kind": SEALED_RELEASE_PIPELINE,
            "collections": list(self.collections),
            "runs": self.runs,
            "resources": self.resources,
            "resource_candidates": self.resource_candidates,
            "artifacts": self.artifacts,
            "workflow_events": self.workflow_events,
            "unique_artifacts": self.unique_artifacts,
            "placements": self.placements,
            "chunks": self.chunks,
            "terminal_state": self.terminal_state,
            "published_rows": self.published_rows,
            "attestations": self.attestations,
            "placements_by_collection": dict(self.placements_by_collection),
        }


def load_sealed_release(
    release_dir: Path,
    *,
    release_manifest_sha256: str,
    artifacts_release_sha256: str,
    candidate_inventory_sha256: str,
    artifact_transfer_manifest_path: Path,
    artifact_transfer_manifest_sha256: str,
) -> SealedReleaseFacts:
    """Lire la release et son manifeste de transfert, tout vérifié par digest.

    Les quatre digests sont vérifiés deux fois, et c'est voulu : contre les
    octets réellement lus, et contre ce que le manifeste de release DÉCLARE
    pour ses propres autorités. Un appelant qui nommerait un
    ``artifacts.release.json`` cohérent avec lui-même mais étranger à cette
    release serait refusé par la seconde vérification.
    """
    manifest_raw = _read_with_digest(
        release_dir / "production-profile-gate.release.json",
        release_manifest_sha256,
        "manifeste de release",
    )
    manifest = json.loads(manifest_raw.decode("utf-8"))

    # --- Scellement : ce qu'une release non scellée ne porte pas. ---------
    _require(
        manifest.get("release_kind") == SEALED_RELEASE_KIND,
        f"release non scellée : release_kind={manifest.get('release_kind')!r}, "
        f"attendu {SEALED_RELEASE_KIND!r}",
    )
    counts = manifest.get("expected_counts")
    _require(
        isinstance(counts, Mapping) and all(k in counts for k in EXPECTED_COUNT_KEYS),
        "release non scellée : expected_counts absent ou incomplet "
        f"(attendu {list(EXPECTED_COUNT_KEYS)})",
    )
    registry = manifest.get("artifact_registry")
    authorities = manifest.get("authorities")
    _require(
        isinstance(registry, Mapping) and "sha256" in registry,
        "release non scellée : artifact_registry absent du manifeste",
    )
    _require(
        isinstance(authorities, Mapping)
        and "candidate_inventory_sha256" in authorities,
        "release non scellée : autorités absentes du manifeste",
    )
    subjects = manifest.get("subjects")
    _require(
        isinstance(subjects, Sequence) and bool(subjects),
        "release non scellée : aucun subject déclaré",
    )

    # --- Les digests attendus doivent être ceux que la release nomme. -----
    _require(
        registry["sha256"] == artifacts_release_sha256,
        f"artifacts.release.json : la release nomme {registry['sha256']}, "
        f"l'appelant attend {artifacts_release_sha256}",
    )
    _require(
        authorities["candidate_inventory_sha256"] == candidate_inventory_sha256,
        "candidate_inventory.json : la release nomme "
        f"{authorities['candidate_inventory_sha256']}, l'appelant attend "
        f"{candidate_inventory_sha256}",
    )

    artifacts_raw = _read_with_digest(
        release_dir / str(registry["path"]),
        artifacts_release_sha256,
        "artefacts de release",
    )
    artifacts = {
        str(entry["artifact_id"]): entry
        for entry in json.loads(artifacts_raw.decode("utf-8"))["artifacts"]
    }

    inventory_raw = _read_with_digest(
        release_dir / "candidate_inventory.json",
        candidate_inventory_sha256,
        "inventaire de candidats",
    )
    inventory = json.loads(inventory_raw.decode("utf-8"))
    discovery = _index_inventory_placements(inventory)

    transfer_raw = _read_with_digest(
        artifact_transfer_manifest_path,
        artifact_transfer_manifest_sha256,
        "manifeste de transfert",
    )
    transfer = json.loads(transfer_raw.decode("utf-8"))
    _require(
        str(transfer.get("release_id")) == str(manifest["release_id"]),
        f"manifeste de transfert : release_id {transfer.get('release_id')!r} "
        f"≠ {manifest['release_id']!r}",
    )
    transferred = _transferred_artifact_ids(transfer)

    collections: list[str] = []
    profile_versions: dict[str, str] = {}
    placements: list[SealedReleasePlacement] = []
    for subject in subjects:
        collection = str(subject["collection"])
        subject_raw = _read_with_digest(
            release_dir / str(subject["path"]),
            str(subject["sha256"]),
            f"subject {collection}",
        )
        subject_doc = json.loads(subject_raw.decode("utf-8"))
        collections.append(collection)
        profile_versions[collection] = str(subject_doc["profile"]["version"])
        placements.extend(
            _placements_of_subject(
                collection=collection,
                subject=subject_doc,
                artifacts=artifacts,
                discovery=discovery,
            )
        )

    _require(
        len(set(collections)) == len(collections),
        f"collections dupliquées dans le manifeste : {sorted(collections)}",
    )

    return SealedReleaseFacts(
        release_id=str(manifest["release_id"]),
        release_kind=str(manifest["release_kind"]),
        release_manifest_sha256=release_manifest_sha256,
        artifacts_release_sha256=artifacts_release_sha256,
        candidate_inventory_sha256=candidate_inventory_sha256,
        artifact_transfer_manifest_sha256=artifact_transfer_manifest_sha256,
        expected_counts={k: int(counts[k]) for k in EXPECTED_COUNT_KEYS},
        collections=tuple(sorted(collections)),
        profile_versions=profile_versions,
        artifact_ids=frozenset(artifacts),
        transferred_artifact_ids=transferred,
        placements=tuple(placements),
        _artifact_chunk_counts={
            artifact_id: len(entry.get("chunks", []))
            for artifact_id, entry in artifacts.items()
        },
    )


def _index_inventory_placements(
    inventory: Mapping[str, Any],
) -> Mapping[tuple[str, str], Mapping[str, Any]]:
    """Indexer l'inventaire par ``(content_sha256, source_placement_id)``.

    Cette paire est la clé de jointure exacte vers le subject : ni le
    contenu seul (un artefact peut être placé plusieurs fois), ni l'URL
    (une page en annonce des dizaines)."""
    index: dict[tuple[str, str], Mapping[str, Any]] = {}
    for entry in inventory.get("collections", []):
        for candidate in entry.get("candidates", []):
            content = str(candidate["content_sha256"])
            for placement in candidate.get("placements", []):
                key = (content, str(placement["source_placement_id"]))
                _require(
                    key not in index,
                    f"inventaire ambigu pour {key!r} : deux placements "
                    "partagent la même clé de jointure",
                )
                index[key] = placement
    return index


def _transferred_artifact_ids(transfer: Mapping[str, Any]) -> frozenset[str]:
    """Les artefacts que le transfert déclare avoir posés ET vérifiés.

    Un fichier dont le digest observé diffère de l'attendu n'est pas
    « transféré avec une réserve » : il est absent de cet ensemble."""
    _require(
        int(transfer.get("digest_mismatches", -1)) == 0
        and int(transfer.get("digest_missing", -1)) == 0,
        "manifeste de transfert : le transfert déclare des digests manquants "
        f"({transfer.get('digest_missing')!r}) ou divergents "
        f"({transfer.get('digest_mismatches')!r})",
    )
    identifiers: set[str] = set()
    for entry in transfer.get("files", []):
        expected = str(entry["sha256_expected"])
        observed = str(entry["sha256_observed"])
        _require(
            expected == observed,
            f"manifeste de transfert : {entry.get('file')!r} attendu {expected}, "
            f"observé {observed}",
        )
        identifiers.add(expected)
    _require(
        len(identifiers) == int(transfer.get("file_count", -1)),
        f"manifeste de transfert : file_count={transfer.get('file_count')!r} "
        f"mais {len(identifiers)} digests distincts",
    )
    return frozenset(identifiers)


def _placements_of_subject(
    *,
    collection: str,
    subject: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
    discovery: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[SealedReleasePlacement]:
    resolved: list[SealedReleasePlacement] = []
    for placement in subject["placements"]:
        artifact_id = str(placement["artifact_id"])
        source_placement_id = str(placement["source_placement_id"])
        _require(
            artifact_id in artifacts,
            f"{collection} : placement vers l'artefact {artifact_id}, absent "
            "d'artifacts.release.json",
        )
        key = (artifact_id, source_placement_id)
        _require(
            key in discovery,
            f"{collection} : provenance introuvable dans l'inventaire pour "
            f"{key!r} — aucune provenance n'est inventée",
        )
        inventory_placement = discovery[key]
        artifact = artifacts[artifact_id]
        discovery_url = str(inventory_placement["source_url"])
        provenance_url = str(artifact["source_url"])
        _require(
            bool(discovery_url.strip()) and bool(provenance_url.strip()),
            f"{collection}/{artifact_id} : provenance vide",
        )
        resolved.append(
            SealedReleasePlacement(
                collection=collection,
                artifact_id=artifact_id,
                placement_id=str(placement["placement_id"]),
                source_placement_id=source_placement_id,
                external_document_type=str(
                    inventory_placement["external_document_type"]
                ),
                type_doc=str(artifact["type_doc"]),
                discovery_url=discovery_url,
                provenance_url=provenance_url,
                chunk_count=len(artifact.get("chunks", [])),
                review_status=str(placement["review_status"]),
                placement_status=str(placement["placement_status"]),
                currentness=str(placement["currentness"]),
                scope_dimensions={
                    dimension: str(placement[dimension])
                    for dimension in (
                        "tenant", "collection", "niveau", "voie", "matiere",
                        "candidat", "visibility", "school_year", "programme_version",
                    )
                },
            )
        )
    return resolved


def require_expected_counts(facts: SealedReleaseFacts) -> None:
    """Recompter les quatre grandeurs et refuser le moindre écart.

    Recompter, et non relire : ``expected_counts`` est ce que la release
    annonce, les valeurs ci-dessous sont ce que ce module a effectivement
    trouvé dans ses fichiers."""
    observed = {
        "subjects": len(facts.collections),
        "unique_artifacts": len(facts.artifact_ids),
        "placements": len(facts.placements),
        "unique_chunks": facts.unique_chunk_count,
    }
    for key in EXPECTED_COUNT_KEYS:
        _require(
            facts.expected_counts.get(key) == observed[key],
            f"expected_counts.{key} : la release déclare "
            f"{facts.expected_counts.get(key)!r}, recompté {observed[key]}",
        )
    _require(
        {placement.artifact_id for placement in facts.placements}
        == set(facts.artifact_ids),
        "les placements ne couvrent pas exactement les artefacts de la release",
    )


def require_collections_match(
    facts: SealedReleaseFacts, expected_collections: Iterable[str]
) -> None:
    """Ni collection manquante, ni collection en surplus — les deux refusées.

    Une collection en trop n'est pas un bonus : c'est du contenu que
    personne n'a demandé, et dont l'autorisation n'a pas été vérifiée sous
    ce périmètre."""
    expected = set(expected_collections)
    declared = set(facts.collections)
    missing = sorted(expected - declared)
    extra = sorted(declared - expected)
    _require(not missing, f"collections manquantes : {missing}")
    _require(not extra, f"collections en surplus : {extra}")


def require_artifact_store_is_complete(
    facts: SealedReleaseFacts, artifact_store_dir: Path
) -> dict[str, Path]:
    """Exiger les 315 PDF, chacun aux octets exacts. Un seul manquant refuse.

    Le digest est recalculé sur les octets du store : le manifeste de
    transfert dit ce qui a été posé, ce contrôle dit ce qui est là
    maintenant."""
    _require(
        facts.artifact_ids <= facts.transferred_artifact_ids,
        "manifeste de transfert : "
        f"{len(facts.artifact_ids - facts.transferred_artifact_ids)} artefact(s) "
        "de la release n'y figurent pas",
    )
    resolved: dict[str, Path] = {}
    missing: list[str] = []
    divergent: list[str] = []
    for artifact_id in sorted(facts.artifact_ids):
        path = artifact_store_dir / f"{artifact_id}.pdf"
        if not path.is_file():
            missing.append(artifact_id)
            continue
        if _sha256(path.read_bytes()) != artifact_id:
            divergent.append(artifact_id)
            continue
        resolved[artifact_id] = path
    _require(
        not missing,
        f"{len(missing)} artefact(s) absent(s) du store : {missing[:3]}",
    )
    _require(
        not divergent,
        f"{len(divergent)} artefact(s) au digest divergent : {divergent[:3]}",
    )
    return resolved


def resolve_scopes(
    facts: SealedReleaseFacts, profile_registry: ProfileRegistry
) -> dict[str, ResourceScope]:
    """Le scope vient du profil gouverné, confronté à ce que la release porte.

    Les deux sources sont nécessaires et aucune ne suffit : le profil porte
    les dix dimensions (dont ``audience``, que la release ne déclare pas),
    la release porte le fait que ce placement appartient bien à ce scope.
    Le moindre désaccord sur les neuf dimensions communes est un refus."""
    scopes: dict[str, ResourceScope] = {}
    for collection in facts.collections:
        profile_version = facts.profile_versions[collection]
        profile = profile_registry.get((collection, profile_version))
        _require(
            profile is not None,
            f"{collection} : aucun profil gouverné {profile_version!r} — "
            "le scope n'est jamais reconstruit à partir de la seule release",
        )
        assert profile is not None  # noqa: S101 - la garde précédente l'établit
        _require(
            profile.enabled,
            f"{collection} : profil {profile_version!r} désactivé",
        )
        scope = profile.scope
        for placement in facts.placements:
            if placement.collection != collection:
                continue
            for dimension, value in placement.scope_dimensions.items():
                governed = _dimension_value(getattr(scope, dimension))
                _require(
                    governed == value,
                    f"{collection}/{placement.placement_id} : la release déclare "
                    f"{dimension}={value!r}, le profil gouverné dit {governed!r}",
                )
        scopes[collection] = scope
    return scopes


def _dimension_value(value: Any) -> str:
    """Valeur textuelle d'une dimension, Enum ou chaîne."""
    return str(getattr(value, "value", value))


def require_scope_authorizations(
    conn: psycopg.Connection,
    *,
    facts: SealedReleaseFacts,
    scopes: Mapping[str, ResourceScope],
    scope_authorization_ids: Mapping[str, str],
    verifier: ScopeAuthorizationVerifier = verify_scope_authorization,
) -> dict[str, VerifiedAuthorization]:
    """Revérifier l'autorisation LOT41A **nommée** de chaque collection.

    Aucune autorisation n'est cherchée : elle est nommée par l'appelant,
    puis intégralement revérifiée (révocation, fenêtre de validité, revue
    humaine vivante, artefact relu) par ``verify_scope_authorization``.
    Choisir « la plus récente » ferait dépendre l'ingestion d'un tri, pas
    d'une décision."""
    missing = sorted(set(facts.collections) - set(scope_authorization_ids))
    extra = sorted(set(scope_authorization_ids) - set(facts.collections))
    _require(
        not missing,
        f"autorisation LOT41A non fournie pour : {missing}",
    )
    _require(
        not extra,
        f"autorisation LOT41A fournie pour des collections hors release : {extra}",
    )

    verified: dict[str, VerifiedAuthorization] = {}
    for collection in facts.collections:
        authorization_id = scope_authorization_ids[collection]
        authorization = verifier(
            conn, authorization_id=authorization_id, scope=scopes[collection]
        )
        _require_provenance_hosts_are_authorized(
            facts=facts, collection=collection, authorization=authorization
        )
        verified[collection] = authorization
    return verified


def _require_provenance_hosts_are_authorized(
    *,
    facts: SealedReleaseFacts,
    collection: str,
    authorization: VerifiedAuthorization,
) -> None:
    """Les hôtes de provenance doivent être ceux que l'autorisation nomme.

    Ce n'est pas un contrôle de destination réseau — ce module n'atteint
    aucune URL. C'est la vérification que le corpus scellé vient bien des
    domaines sous lesquels il a été autorisé, sans élargissement implicite
    à un sous-domaine (l'autorisation nomme un hôte, jamais un suffixe)."""
    allowed = set(authorization.allowed_domains)
    for placement in facts.placements:
        if placement.collection != collection:
            continue
        for url in (placement.discovery_url, placement.provenance_url):
            host = (urlsplit(url).hostname or "").lower()
            _require(
                host in allowed,
                f"{collection} : provenance {host!r} hors des domaines "
                f"autorisés {sorted(allowed)}",
            )


def ingest_sealed_release(
    conn: psycopg.Connection,
    *,
    facts: SealedReleaseFacts,
    artifact_store_dir: Path,
    profile_registry: ProfileRegistry,
    scope_authorization_ids: Mapping[str, str],
    owner: str,
    expected_collections: Iterable[str] | None = None,
    verifier: ScopeAuthorizationVerifier = verify_scope_authorization,
) -> IngestionReport:
    """Créer les lignes de contrôle jusqu'à ``NEEDS_REVIEW``, et rien au-delà.

    Toutes les vérifications ont lieu AVANT la première écriture : une
    ingestion interrompue à mi-chemin laisserait un état que personne ne
    saurait interpréter, ni comme faite, ni comme à refaire.

    Ne committe pas : la transaction appartient à l'appelant, comme pour
    toutes les primitives ``ingestion_control``."""
    require_expected_counts(facts)
    if expected_collections is not None:
        require_collections_match(facts, expected_collections)
    paths = require_artifact_store_is_complete(facts, artifact_store_dir)
    scopes = resolve_scopes(facts, profile_registry)
    authorizations = require_scope_authorizations(
        conn,
        facts=facts,
        scopes=scopes,
        scope_authorization_ids=scope_authorization_ids,
        verifier=verifier,
    )

    report = IngestionReport(
        release_id=facts.release_id,
        collections=facts.collections,
        unique_artifacts=len(facts.artifact_ids),
        placements=len(facts.placements),
        chunks=facts.unique_chunk_count,
    )

    by_collection: dict[str, list[SealedReleasePlacement]] = {
        collection: [] for collection in facts.collections
    }
    for placement in facts.placements:
        by_collection[placement.collection].append(placement)

    for collection in facts.collections:
        placements = by_collection[collection]
        _require(placements != [], f"{collection} : aucun placement à ingérer")
        scope = scopes[collection]
        authorization = authorizations[collection]
        run_id = create_ingestion_run(
            conn,
            scope=scope,
            profile_version=facts.profile_versions[collection],
            trigger="manual",
        )
        report.runs += 1
        report.placements_by_collection[collection] = len(placements)

        for placement in placements:
            _ingest_placement(
                conn,
                placement=placement,
                run_id=run_id,
                scope=scope,
                authorization=authorization,
                path=paths[placement.artifact_id],
                facts=facts,
                owner=owner,
                report=report,
            )

    return report


def _ingest_placement(
    conn: psycopg.Connection,
    *,
    placement: SealedReleasePlacement,
    run_id: UUID,
    scope: ResourceScope,
    authorization: VerifiedAuthorization,
    path: Path,
    facts: SealedReleaseFacts,
    owner: str,
    report: IngestionReport,
) -> None:
    evidence = {
        "protocol_version": PROTOCOL_VERSION,
        "pipeline_kind": SEALED_RELEASE_PIPELINE,
        "release_id": facts.release_id,
        "release_manifest_sha256": facts.release_manifest_sha256,
        "artifacts_release_sha256": facts.artifacts_release_sha256,
        "candidate_inventory_sha256": facts.candidate_inventory_sha256,
        "artifact_transfer_manifest_sha256": facts.artifact_transfer_manifest_sha256,
        "collection": placement.collection,
        "content_sha256": placement.artifact_id,
        "placement_id": placement.placement_id,
        "source_placement_id": placement.source_placement_id,
        "external_document_type": placement.external_document_type,
        "type_doc": placement.type_doc,
        # Provenance, explicitement nommée comme telle. Ce protocole ne
        # porte aucune URL canonique (ADR-0056 § 3).
        "provenance_discovery_url": placement.discovery_url,
        "provenance_artifact_url": placement.provenance_url,
        "chunk_count": placement.chunk_count,
        "review_status": placement.review_status,
        "placement_status": placement.placement_status,
        "currentness": placement.currentness,
        "scope_authorization_id": authorization.authorization_id,
        "scope_authorization_digest": authorization.authorization_digest,
    }

    # ``dedup_key`` dérive du CONTENU, jamais de l'URL. Les 479 placements
    # ne viennent que de 19 pages de découverte, pour 27 URL d'artefact :
    # une clé dérivée d'une URL ferait disparaître le reste du corpus.
    resource_id = create_resource(
        conn,
        run_id=run_id,
        dedup_key=placement.artifact_id,
        scope=scope,
        pipeline_kind=SEALED_RELEASE_PIPELINE,
    )
    persist_sealed_release_candidate(
        conn,
        resource_id=resource_id,
        run_id=run_id,
        dedup_key=placement.artifact_id,
        source_url=placement.discovery_url,
        domain=(urlsplit(placement.discovery_url).hostname or "").lower(),
        proposed_type_doc=placement.type_doc,
        payload=dict(evidence),
    )
    persist_sealed_release_artifact(
        conn,
        resource_id=resource_id,
        run_id=run_id,
        sha256=placement.artifact_id,
        size_bytes=path.stat().st_size,
        mime_declared=PDF_MIME,
        mime_detected=PDF_MIME,
        provenance_url=placement.provenance_url,
        payload=dict(evidence),
    )
    report.resources += 1
    report.resource_candidates += 1
    report.artifacts += 1
    report.resource_ids.append(str(resource_id))

    _advance_to_needs_review(
        conn,
        resource_id=resource_id,
        run_id=run_id,
        owner=owner,
        evidence=evidence,
        report=report,
    )


def _advance_to_needs_review(
    conn: psycopg.Connection,
    *,
    resource_id: UUID,
    run_id: UUID,
    owner: str,
    evidence: Mapping[str, Any],
    report: IngestionReport,
) -> None:
    """Franchir les dix états un par un, par la primitive CAS canonique.

    Aucun raccourci : ``cas_transition`` refuse toute transition que la
    machine d'états n'autorise pas, et journalise chacune. Parcourir la
    séquence n'est donc pas une formalité — c'est ce qui rend l'ingestion
    observable état par état."""

    current = ResourceState.DISCOVERED
    version = 0
    for target in STATE_SEQUENCE:
        result = cas_transition(
            conn,
            resource_id=resource_id,
            expected_state=current,
            expected_version=version,
            new_state=target,
            actor=owner,
            run_id=run_id,
            payload=dict(evidence),
        )
        current = result.to_state
        version = result.state_version
        report.workflow_events += 1

    _require(
        current is TERMINAL_STATE,
        f"ressource {resource_id} : état final {current.value}, attendu "
        f"{TERMINAL_STATE.value}",
    )


__all__ = [
    "EXPECTED_COUNT_KEYS",
    "PDF_MIME",
    "PROTOCOL_VERSION",
    "SEALED_RELEASE_KIND",
    "STATE_SEQUENCE",
    "TERMINAL_STATE",
    "IngestionReport",
    "SealedReleaseFacts",
    "SealedReleaseIngestionError",
    "SealedReleasePlacement",
    "ingest_sealed_release",
    "load_sealed_release",
    "require_artifact_store_is_complete",
    "require_collections_match",
    "require_expected_counts",
    "require_scope_authorizations",
    "resolve_scopes",
]
