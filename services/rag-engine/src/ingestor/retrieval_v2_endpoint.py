"""Retrieval v2 endpoint — FastAPI router (FE-01).

Exposes POST /search/v2 wrapping the canonical LOT40 hybrid pipeline:
  resolve_collection_v2 → gate retrievable (fail-closed) → dense + lexical
  → RRF → rerank → seuil +1.90 → MMR.

Les modèles ML sont chargés une fois au démarrage. La frontière HTTP utilise
exclusivement RetrievalRequest → RetrievalResponse depuis nexus-contracts.
DSN via PG_RAG_DSN only (R-01: no owner/migration fallback).
Retrieval seulement : aucun champ ni appel de génération LLM.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from nexus_contracts import (
    ChatRequest,
    ChatResponse,
    Citation,
    RetrievalRequest,
    RetrievalResponse,
    RetrievalResult,
    RetrievalScopeArtifactV2,
    RetrievalScopeArtifactV3,
    ServableCorpus,
    load_retrieval_scope_registry,
)
from nexus_contracts.canonical_json import canonical_model_bytes
from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


def _missing_sibling(exc: ImportError) -> bool:
    """Le frère visé est-il absent, ou son exécution a-t-elle échoué ?

    Deux situations autorisent le repli : le module frère (ou son paquet
    parent) est introuvable, et le runtime aplati de l'image Docker, où
    les modules n'ont pas de paquet parent et ``from .x import y`` lève
    « attempted relative import with no known parent package ».

    Tout le reste — une dépendance transitive manquante, un ``cannot
    import name``, une configuration refusée — remonte intact : réessayer
    par un autre chemin rejouerait le même échec sous un autre nom.
    """
    if not isinstance(exc, ModuleNotFoundError):
        return exc.name is None and "relative import" in str(exc)
    name = exc.name or ""
    return name == name.rsplit(".", 1)[-1] or name in (
        "src", "src.ingestor", "ingestor",
    )


try:
    from .collection_config import (
        CollectionConfigError,
        list_instanciated_collections,
        load_collection_config,
        resolve_collection_v2,
    )
    from .embedding_contract import (
        EmbeddingContractError,
        declared_embedding_dim,
        load_embedding_model,
        runtime_embedding_dimension,
    )
    from .identity_v2 import (
        VerifiedInternalIdentity,
        load_identity_verifier_config,
        require_internal_identity,
    )
    from .inference_runtime import BoundedInferenceEmbedder, BoundedInferenceReranker
    from .pg_pool import (
        PoolSettings,
        execute_with_database_budget,
        pool_connection,
        remaining_database_budget_ms,
        runtime_database_budget,
        runtime_request_budget,
    )
    from .release_readiness import (
        ReleaseReadinessError,
        ReleaseRegistryExpectation,
        load_release_registry,
        load_release_registry_file,
        validate_release_collection_readiness,
        validate_release_registry_readiness,
    )
    from .reranker_contract import load_reranker_model
    from .retrieval_contract_adapter import adapt_retrieval_request
    from .retrieval_hybrid_v2 import (
        CHANNEL_LIMIT,
        EMBED_MODEL,
        MMR_LAMBDA,  # noqa: F401 -- public endpoint configuration surface
        RERANK_MODEL,
        RERANK_THRESHOLD,
        RRF_K,  # noqa: F401 -- public endpoint configuration surface
        HybridHit,
        retrieve_hybrid,
    )
    from .retrieval_pg_v2 import (
        _READINESS_SCOPE_PREDICATE_SQL,
        PgCandidateStore,
        _readiness_scope_params,
    )
    from .retrieval_scope_v2 import (
        RetrievalScopeError,
        ServerRetrievalScope,
        build_server_readiness_scope,
        build_server_retrieval_scope,
        effective_signed_collections,
    )
    from .security_v2 import SecurityRole, require_bff_service, require_role
    from .servable_corpus_api import configured_servable_corpus_repository
    from .servable_corpus_index import ServableCorpusRepositoryError
except ImportError as _exc:  # repli à plat, cause réelle préservée
    if not _missing_sibling(_exc):
        # Le module frère existe : c'est l'une de ses dépendances qui
        # manque, ou sa configuration qui a été refusée. Réessayer par un
        # autre chemin rejouerait le même échec sous un autre nom.
        raise
    from collection_config import (  # type: ignore[no-redef]
        CollectionConfigError,
        list_instanciated_collections,
        load_collection_config,
        resolve_collection_v2,
    )
    from embedding_contract import (  # type: ignore[no-redef]
        EmbeddingContractError,
        declared_embedding_dim,
        load_embedding_model,
        runtime_embedding_dimension,
    )
    from identity_v2 import (  # type: ignore[no-redef]
        VerifiedInternalIdentity,
        load_identity_verifier_config,
        require_internal_identity,
    )
    from inference_runtime import (  # type: ignore[no-redef]
        BoundedInferenceEmbedder,
        BoundedInferenceReranker,
    )
    from pg_pool import (  # type: ignore[no-redef]
        PoolSettings,
        execute_with_database_budget,
        pool_connection,
        remaining_database_budget_ms,
        runtime_database_budget,
        runtime_request_budget,
    )
    from release_readiness import (  # type: ignore[no-redef]
        ReleaseReadinessError,
        ReleaseRegistryExpectation,
        load_release_registry,
        load_release_registry_file,
        validate_release_collection_readiness,
        validate_release_registry_readiness,
    )
    from reranker_contract import load_reranker_model  # type: ignore[no-redef]
    from retrieval_contract_adapter import (  # type: ignore[no-redef]
        adapt_retrieval_request,
    )
    from retrieval_hybrid_v2 import (  # type: ignore[no-redef]
        CHANNEL_LIMIT,
        EMBED_MODEL,
        MMR_LAMBDA,  # noqa: F401 -- public endpoint configuration surface
        RERANK_MODEL,
        RERANK_THRESHOLD,
        RRF_K,  # noqa: F401 -- public endpoint configuration surface
        HybridHit,
        retrieve_hybrid,
    )
    from retrieval_pg_v2 import (  # type: ignore[no-redef]
        _READINESS_SCOPE_PREDICATE_SQL,
        PgCandidateStore,
        _readiness_scope_params,
    )
    from retrieval_scope_v2 import (  # type: ignore[no-redef]
        RetrievalScopeError,
        ServerRetrievalScope,
        build_server_readiness_scope,
        build_server_retrieval_scope,
        effective_signed_collections,
    )
    from security_v2 import (  # type: ignore[no-redef]
        SecurityRole,
        require_bff_service,
        require_role,
    )
    from servable_corpus_api import (  # type: ignore[no-redef]
        configured_servable_corpus_repository,
    )
    from servable_corpus_index import (  # type: ignore[no-redef]
        ServableCorpusRepositoryError,
    )

logger = logging.getLogger(__name__)

MIN_COLLECTION_SUBSTANCE_CHUNKS = int(os.environ.get("RAG_MIN_COLLECTION_SUBSTANCE_CHUNKS", "1"))

router = APIRouter(tags=["retrieval_v2"])

# --- Cache de warmup/administration (SCALE-V1-1) ---
# Key = normalized(query, collection, k). Value = (hits, timestamp).
# Invalidation is generation-based so a warmup started before a review change
# can never republish its stale snapshot afterward.
# Public search never reads this process-local cache: every request re-runs the
# canonical PostgreSQL pipeline and therefore observes the current review state.
#
# This cache is per-process: invalidate only clears the handling worker. The
# historical enablement flag remains visible in stats, but it cannot authorize
# serving cache entries on public search.
CACHE_TTL_S = int(os.environ.get("RERANK_CACHE_TTL", "300"))  # 5 min default
CACHE_ENABLED = False
_cache: dict[str, tuple[list, float]] = {}
_cache_lock = threading.Lock()
_cache_generation = 0
_REVIEWED_COUNTS_CACHE_TTL_S = 1.0
_reviewed_counts_cache: (
    tuple[tuple[str, ...], float, dict[str, int]] | None
) = None
_reviewed_counts_cache_generation = 0
_reviewed_counts_cache_lock = threading.Lock()


@dataclass
class _ReviewedCountsFlight:
    """Résultat partagé par les probes identiques lancées simultanément."""

    event: threading.Event
    generation: int
    result: dict[str, int] | None = None
    error: Exception | None = None


_reviewed_counts_inflight: dict[tuple[str, ...], _ReviewedCountsFlight] = {}
_CATALOGUE_ROLES = frozenset({"admin", "reviewer", "teacher", "ingest_agent"})


def _cache_key(query: str, collection: str, k: int) -> str:
    """Normalized cache key. Lowercased, stripped, unicode-normalized."""
    import unicodedata

    normalized = unicodedata.normalize("NFKC", query).strip().lower()
    # Collapse curly quotes/apostrophes to ASCII equivalents
    normalized = normalized.replace("\u2019", "'").replace("\u2018", "'")
    normalized = normalized.replace("\u201c", '"').replace("\u201d", '"')
    raw = f"{normalized}|{collection}|{k}"
    return hashlib.sha256(raw.encode()).hexdigest()


def invalidate_cache() -> int:
    """Invalidate all cache entries. Called when review_status changes."""
    global _cache_generation, _reviewed_counts_cache
    global _reviewed_counts_cache_generation
    with _cache_lock:
        n = len(_cache)
        _cache.clear()
        _cache_generation += 1
    with _reviewed_counts_cache_lock:
        _reviewed_counts_cache = None
        _reviewed_counts_cache_generation += 1
    return n


# --- Configuration figée par le noyau hybride LOT40 ---
RERANK_SCORE_THRESHOLD = RERANK_THRESHOLD
RERANK_CANDIDATES = CHANNEL_LIMIT

WARMUP_QUERIES = (
    "Comment fonctionne une boucle while en Python ?",
    "Quelle est la différence entre une pile et une file ?",
    "Qu'est-ce qu'un arbre binaire de recherche ?",
    "Comment fonctionne la récursivité ?",
    "Comment trier une liste en Python ?",
    "Qu'est-ce qu'un dictionnaire en Python ?",
    "Comment fonctionne une requête SQL avec jointure ?",
    "Qu'est-ce qu'une clé étrangère ?",
    "Comment parcourir un graphe en profondeur ?",
    "Comment fonctionne la programmation dynamique ?",
    "Qu'est-ce qu'un processus en système d'exploitation ?",
    "Expliquer le tri par insertion",
    "Comment représenter un entier en binaire ?",
    "À quoi sert le protocole HTTP ?",
    "Qu'est-ce qu'un type construit en Python ?",
    "Comment fonctionne une boucle for en Python ?",
    "Qu'est-ce qu'une variable locale et globale ?",
    "Comment fonctionne le protocole TCP/IP ?",
    "Qu'est-ce qu'un algorithme glouton ?",
    "Comment fonctionne la recherche dichotomique ?",
)

# --- Lazy-loaded models (cached at module level) ---
_embed_model = None
_reranker = None
_verified_embedding_artifact_root: Path | None = None
_verified_reranker_artifact_root: Path | None = None
_model_load_lock = threading.Lock()


def configure_verified_model_artifacts(
    *,
    embedding_root: Path,
    reranker_root: Path,
) -> None:
    """Transmettre les chemins attestés au lifespan sans rehacher les poids."""
    global _embed_model, _reranker
    global _verified_embedding_artifact_root, _verified_reranker_artifact_root
    with _model_load_lock:
        _embed_model = None
        _reranker = None
        _verified_embedding_artifact_root = embedding_root
        _verified_reranker_artifact_root = reranker_root


def reset_runtime_model_state() -> None:
    """Effacer les modèles et preuves process-local à l'arrêt ou en test."""
    global _embed_model, _reranker
    global _verified_embedding_artifact_root, _verified_reranker_artifact_root
    with _model_load_lock:
        _embed_model = None
        _reranker = None
        _verified_embedding_artifact_root = None
        _verified_reranker_artifact_root = None


def preload_runtime_models() -> None:
    """Construire les modèles et prouver la dimension native avant trafic."""
    embed_model = _get_embed_model()
    if runtime_embedding_dimension(embed_model) != declared_embedding_dim():
        raise EmbeddingContractError("EMBEDDING_RUNTIME_DIMENSION_MISMATCH")
    _get_reranker()


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        with _model_load_lock:
            if _embed_model is None:
                logger.info("Loading embedding model %s (one-time)", EMBED_MODEL)
                if _verified_embedding_artifact_root is None:
                    _embed_model = load_embedding_model()
                else:
                    _embed_model = load_embedding_model(
                        verified_artifact_root=_verified_embedding_artifact_root
                    )
    return _embed_model


def _get_reranker():
    global _reranker
    if _reranker is None:
        with _model_load_lock:
            if _reranker is None:
                logger.info("Loading reranker %s (one-time)", RERANK_MODEL)
                if _verified_reranker_artifact_root is None:
                    _reranker = load_reranker_model()
                else:
                    _reranker = load_reranker_model(
                        verified_artifact_root=_verified_reranker_artifact_root
                    )
    return _reranker


def _check_retrievable(
    collection: str,
    cfg: dict,
    verified: VerifiedInternalIdentity | None = None,
) -> dict:
    """Gate retrievable FAIL-CLOSED (GG-01).

    Reads domain from the collection's DECLARED definition.
    Refuses if domain absent, domains section malformed, or retrievable not True.
    """
    defn = resolve_collection_v2(collection, cfg)

    domain = defn.get("domain")
    if not isinstance(domain, str) or not domain:
        raise HTTPException(
            status_code=403,
            detail=f"Collection '{collection}' has no declared domain — cannot verify retrievable.",
        )

    domains = cfg.get("domains")
    if not isinstance(domains, dict):
        raise HTTPException(
            status_code=500,
            detail="Config 'domains' section absent or malformed — fail-closed.",
        )

    domain_cfg = domains.get(domain)
    if not isinstance(domain_cfg, dict):
        raise HTTPException(
            status_code=403,
            detail=f"Domain '{domain}' not found — collection '{collection}' not retrievable.",
        )

    if domain_cfg.get("retrievable") is not True:
        raise HTTPException(
            status_code=403,
            detail=f"Collection '{collection}' is not retrievable (domain '{domain}').",
        )

    _require_release_ready_if_governed(collection, cfg, verified=verified)
    return defn


def _configured_release_manifest() -> tuple[Path, str] | None:
    path_raw = os.environ.get("RAG_RELEASE_MANIFEST_PATH")
    digest = os.environ.get("RAG_RELEASE_MANIFEST_SHA256")
    if path_raw is None and digest is None:
        return None
    if not path_raw or not digest:
        raise ReleaseReadinessError("release manifest configuration incomplete")
    return Path(path_raw), digest


def _configured_release_registry_file() -> tuple[Path, str] | None:
    path_raw = os.environ.get("RAG_RELEASE_REGISTRY_PATH")
    digest = os.environ.get("RAG_RELEASE_REGISTRY_SHA256")
    if path_raw is None and digest is None:
        return None
    if not path_raw or not digest:
        raise ReleaseReadinessError("release registry configuration incomplete")
    return Path(path_raw), digest


def _configured_release_registry() -> ReleaseRegistryExpectation | None:
    """Charger l'autorité release active : registre canonique borné, couple
    de manifests explicite (``RAG_RELEASE_MANIFESTS_JSON``), ou manifest
    historique unique — jamais plus d'un mécanisme à la fois."""
    registry_file = _configured_release_registry_file()
    registry_raw = os.environ.get("RAG_RELEASE_MANIFESTS_JSON")
    legacy = _configured_release_manifest()
    configured_mechanisms = sum(
        mechanism is not None for mechanism in (registry_file, registry_raw, legacy)
    )
    if configured_mechanisms > 1:
        raise ReleaseReadinessError("release manifest configuration is ambiguous")
    if registry_file is not None:
        registry_file_path, registry_file_digest = registry_file
        return load_release_registry_file(registry_file_path, registry_file_digest)
    if registry_raw is None:
        return load_release_registry((legacy,)) if legacy is not None else None
    try:
        payload = json.loads(registry_raw)
    except json.JSONDecodeError as exc:
        raise ReleaseReadinessError("release manifest registry is not valid JSON") from exc
    if not isinstance(payload, list):
        raise ReleaseReadinessError("release manifest registry must be an array")
    configurations: list[tuple[Path, str]] = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, Mapping) or set(entry) != {"path", "sha256"}:
            raise ReleaseReadinessError(
                f"release manifest registry entry {index} is invalid"
            )
        path = entry.get("path")
        digest = entry.get("sha256")
        if not isinstance(path, str) or not path.strip() or not isinstance(digest, str):
            raise ReleaseReadinessError(
                f"release manifest registry entry {index} is invalid"
            )
        configurations.append((Path(path), digest))
    return load_release_registry(tuple(configurations))


def configured_release_model_contract() -> tuple[str, str, int, str, str] | None:
    """Retourner le contrat modèles complet scellé par la release active."""
    registry = _configured_release_registry()
    if registry is None:
        return None
    return registry.model_contract


def _release_evidence_for_collection(collection: str) -> bool | None:
    """Retourner None hors release configurée, sinon l'état exact de la release."""
    try:
        registry = _configured_release_registry()
    except ReleaseReadinessError:
        return False
    if registry is None:
        return None
    if collection not in registry.collections:
        return None
    try:
        settings = PoolSettings.from_env()
        with runtime_database_budget():
            with pool_connection(settings) as connection:
                return validate_release_collection_readiness(
                    registry,
                    collection,
                    connection,
                ).ready
    except Exception:
        logger.error("release readiness unavailable")
        return False


def _release_evidence_for_v2_artifact(
    artifact: RetrievalScopeArtifactV2,
) -> bool | None:
    """Lier les nouveaux scopes au subject release exact, en gardant Wave 0."""
    collection = str(artifact.evidence_subject.collection)
    state = _release_evidence_for_collection(collection)
    if state is not True:
        return state
    try:
        registry = _configured_release_registry()
        if registry is None:
            return state
    except ReleaseReadinessError:
        return False
    manifest = registry.manifest_for_collection(collection)
    if manifest is None:
        return None
    expectation = manifest.expectation
    if expectation.release_kind == "MULTILEVEL_AGGREGATE_RELEASE_V1":
        subject_sha_by_collection = dict(
            expectation.subject_manifest_sha256_by_collection
        )
        if artifact.source_sha256 != subject_sha_by_collection.get(collection):
            return False
    return state


def _v2_evidence_collections(
    artifacts: Mapping[str, object] | None = None,
) -> frozenset[str]:
    registry = load_retrieval_scope_registry() if artifacts is None else artifacts
    return frozenset(
        str(artifact.evidence_subject.collection)
        for artifact in registry.values()
        if isinstance(artifact, RetrievalScopeArtifactV2)
    )


def _instanciated_v2_collections(
    artifacts: Mapping[str, object],
    cfg: Mapping[str, Any],
) -> frozenset[str]:
    collections = cfg.get("collections")
    if not isinstance(collections, Mapping):
        raise RuntimeError("release collection catalogue malformed")
    return frozenset(
        collection
        for collection in _v2_evidence_collections(artifacts)
        if isinstance(collections.get(collection), Mapping)
        and collections[collection].get("instanciee") is True
    )


def validate_release_startup_configuration(
    artifacts: Mapping[str, object],
    cfg: Mapping[str, Any],
) -> None:
    """Exiger un manifest exact dès qu'un scope V2 est instancié."""
    required = _instanciated_v2_collections(artifacts, cfg)
    if not required:
        return
    try:
        registry = _configured_release_registry()
        if registry is None:
            raise ReleaseReadinessError("release manifest unavailable")
    except ReleaseReadinessError as exc:
        raise RuntimeError("release manifest unavailable or invalid") from exc
    configured_collections = set(registry.collections)
    catalogue = cfg.get("collections")
    if (
        not configured_collections
        or not configured_collections & set(required)
        or not isinstance(catalogue, Mapping)
        or not configured_collections <= set(catalogue)
    ):
        raise RuntimeError("release manifest collection set mismatch")
    subject_sha_by_collection = {
        collection: sha256
        for manifest in registry.manifests
        if manifest.expectation.release_kind == "MULTILEVEL_AGGREGATE_RELEASE_V1"
        for collection, sha256 in (
            manifest.expectation.subject_manifest_sha256_by_collection
        )
    }
    for collection, source_sha256 in subject_sha_by_collection.items():
        matches = [
            artifact
            for artifact in artifacts.values()
            if isinstance(artifact, RetrievalScopeArtifactV2)
            and artifact.evidence_subject.collection == collection
            and artifact.source_sha256 == source_sha256
        ]
        if not matches:
            raise RuntimeError("scope source SHA differs from subject release")
        if len(matches) != 1:
            raise RuntimeError("scope source SHA is ambiguous for subject release")


def validate_configured_release_database() -> None:
    """Vérifier le manifest configuré contre PostgreSQL avant tout trafic."""
    registry = _configured_release_registry()
    if registry is None:
        return
    settings = PoolSettings.from_env()
    with runtime_database_budget():
        with pool_connection(settings) as connection:
            reports = validate_release_registry_readiness(registry, connection)
    if set(reports) != set(registry.collections) or any(
        not report.ready for report in reports.values()
    ):
        raise RuntimeError("release database reconciliation unavailable")


def _require_release_ready_if_governed(
    collection: str,
    cfg: Mapping[str, Any],
    *,
    verified: VerifiedInternalIdentity | None = None,
) -> None:
    collections = cfg.get("collections")
    definition = collections.get(collection) if isinstance(collections, Mapping) else None
    if verified is None:
        return
    artifact = verified.artifact
    if not isinstance(artifact, RetrievalScopeArtifactV2):
        return
    if artifact.evidence_subject.collection != collection:
        return
    if (
        collection not in _v2_evidence_collections()
        or not isinstance(definition, Mapping)
        or definition.get("instanciee") is not True
    ):
        return
    state = _release_evidence_for_v2_artifact(artifact)
    if state is not True:
        raise HTTPException(status_code=503, detail="release evidence unavailable")


# --- Modèle interne d'un hit avant projection contractuelle ---


class SearchV2Hit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1, pattern=r".*\S.*")
    doc_id: str = Field(min_length=1, pattern=r".*\S.*")
    source_label: str = Field(min_length=1, pattern=r".*\S.*")
    source_uri: str = Field(min_length=1, pattern=r".*\S.*")
    rights: str = Field(min_length=1, pattern=r".*\S.*")
    type_doc: str
    review_status: Literal["reviewed"]  # SCALE-04: reviewed only
    artifact_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    placement_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    placement_source_scope: str | None = Field(
        default=None, min_length=1, pattern=r".*\S.*"
    )
    placement_source_id: str | None = Field(
        default=None, min_length=1, pattern=r".*\S.*"
    )
    placement_source_path: str | None = Field(
        default=None, min_length=1, pattern=r".*\S.*"
    )
    page: int | None = Field(default=None, ge=1)
    preview: str = Field(min_length=1, pattern=r".*\S.*")
    dense_score: float | None
    lexical_score: float | None
    rrf_score: float = Field(ge=0)
    rerank_score: float
    mmr_score: float
    score_final: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_governed_traceability(self) -> SearchV2Hit:
        trace = (
            self.artifact_id,
            self.content_sha256,
            self.placement_id,
            self.placement_source_scope,
            self.placement_source_id,
            self.placement_source_path,
        )
        if any(value is not None for value in trace):
            if any(value is None for value in trace):
                raise ValueError("governed traceability must be complete")
            if self.artifact_id != self.content_sha256 or self.doc_id != self.artifact_id:
                raise ValueError("governed identity must be content-bound")
        return self

    @computed_field(  # type: ignore[prop-decorator]
        return_type=float | None,
        json_schema_extra={"deprecated": True},
    )
    @property
    def dense_sim(self) -> float | None:
        """Alias de sérialisation déprécié, dérivé de l'unique score dense."""
        return self.dense_score


def _build_launch_readiness(
    cfg: Mapping[str, Any],
    reviewed_counts: Mapping[str, int],
    *,
    min_chunks: int,
    release_evidence_verified: bool | Mapping[str, bool],
) -> dict[str, Any]:
    """Expose diagnostics without turning a row count into release evidence.

    `release_evidence_verified` may only be supplied by a future exhaustive
    release-manifest validator. LOT41 always passes False: reviewed-row presence
    is informative, never a proof of pedagogical substance or 39-notion coverage.
    """
    collections_raw = cfg.get("collections")
    domains = cfg.get("domains")
    if not isinstance(collections_raw, Mapping) or not isinstance(domains, Mapping):
        raise ValueError("collections or domains config is malformed")

    collections: list[dict[str, Any]] = []
    blockers: list[str] = []
    aggregate_release_evidence = (
        release_evidence_verified
        if isinstance(release_evidence_verified, bool)
        else bool(release_evidence_verified)
        and all(release_evidence_verified.values())
    )
    if not aggregate_release_evidence:
        blockers.append("preuve exhaustive de release absente")
    for name in collections_raw:
        definition = collections_raw[name]
        if not isinstance(definition, Mapping):
            blockers.append(f"{name}: définition de collection invalide")
            collections.append(
                {
                    "name": name,
                    "instanciee": False,
                    "retrievable": False,
                    "reviewed_chunks": 0,
                    "reviewed_chunk_floor_met": False,
                    "ready": False,
                    "reasons": ["définition de collection invalide"],
                }
            )
            continue

        instanciee = definition.get("instanciee") is True
        domain = definition.get("domain")
        domain_cfg = domains.get(domain) if isinstance(domain, str) else None
        retrievable = isinstance(domain_cfg, Mapping) and domain_cfg.get("retrievable") is True
        reviewed_chunks = max(0, int(reviewed_counts.get(name, 0)))
        reviewed_chunk_floor_met = reviewed_chunks >= min_chunks
        collection_release_evidence = (
            release_evidence_verified
            if isinstance(release_evidence_verified, bool)
            else release_evidence_verified.get(name) is True
        )
        reasons: list[str] = []
        if not instanciee:
            reasons.append("collection non instanciée")
        if not retrievable:
            reasons.append("domaine non retrievable")
        if not reviewed_chunk_floor_met:
            reasons.append(
                f"plancher de chunks reviewed non atteint ({reviewed_chunks}/{min_chunks})",
            )
        if not collection_release_evidence:
            reasons.append("preuve exhaustive de release absente")
        ready = collection_release_evidence and not reasons
        if reasons:
            blockers.append(f"{name}: {', '.join(reasons)}")
        collections.append(
            {
                "name": name,
                "instanciee": instanciee,
                "retrievable": retrievable,
                "reviewed_chunks": reviewed_chunks,
                "reviewed_chunk_floor_met": reviewed_chunk_floor_met,
                "ready": ready,
                "reasons": reasons,
            }
        )

    return {
        "launch_ready": not blockers,
        "total_collections": len(collections),
        "ready_collections": sum(1 for item in collections if item["ready"]),
        "minimum_reviewed_chunks": min_chunks,
        "release_evidence_verified": aggregate_release_evidence,
        "blockers": blockers,
        "collections": collections,
    }


def _get_reviewed_chunk_counts(
    scopes: Iterable[ServerRetrievalScope],
) -> dict[str, int]:
    """Count scoped reviewed rows through a bounded pool and a short cache."""
    global _reviewed_counts_cache
    resolved_scopes = tuple(scopes)
    if not resolved_scopes:
        return {}
    cache_key = tuple(scope.filter_digest for scope in resolved_scopes)
    now = time.monotonic()
    with _reviewed_counts_cache_lock:
        cached = _reviewed_counts_cache
        if cached is not None and cached[0] == cache_key and cached[1] > now:
            return dict(cached[2])

    count_queries: list[str] = []
    params: list[object] = []
    for scope in resolved_scopes:
        count_queries.append(
            "SELECT %s::text AS collection, COUNT(*) "
            "FROM public.rag_chunks AS chunk WHERE "
            f"({_READINESS_SCOPE_PREDICATE_SQL})"
        )
        params.append(scope.collection)
        params.extend(_readiness_scope_params(scope))

    try:
        settings = PoolSettings.from_env()
        with _reviewed_counts_cache_lock:
            cached = _reviewed_counts_cache
            now = time.monotonic()
            if cached is not None and cached[0] == cache_key and cached[1] > now:
                return dict(cached[2])
            flight = _reviewed_counts_inflight.get(cache_key)
            is_leader = flight is None
            if flight is None:
                flight = _ReviewedCountsFlight(
                    event=threading.Event(),
                    generation=_reviewed_counts_cache_generation,
                )
                _reviewed_counts_inflight[cache_key] = flight

        if not is_leader:
            wait_timeout_s = remaining_database_budget_ms() / 1_000.0
            if not flight.event.wait(timeout=wait_timeout_s):
                raise RuntimeError("reviewed count query exceeded its bounded lifetime")
            if flight.error is not None:
                raise flight.error
            if flight.result is None:
                raise RuntimeError("reviewed count query completed without a result")
            return dict(flight.result)

        try:
            with pool_connection(settings) as connection:
                with connection.cursor() as cursor:
                    execute_with_database_budget(
                        cursor,
                        " UNION ALL ".join(count_queries),
                        tuple(params),
                        statement_timeout_ms=settings.statement_timeout_ms,
                    )
                    counts = {
                        str(collection): int(count)
                        for collection, count in cursor.fetchall()
                    }
            with _reviewed_counts_cache_lock:
                publication_error: RuntimeError | None = None
                if flight.generation == _reviewed_counts_cache_generation:
                    flight.result = dict(counts)
                    _reviewed_counts_cache = (
                        cache_key,
                        time.monotonic() + _REVIEWED_COUNTS_CACHE_TTL_S,
                        dict(counts),
                    )
                else:
                    publication_error = RuntimeError(
                        "reviewed count query invalidated by a review decision"
                    )
                    flight.error = publication_error
                _reviewed_counts_inflight.pop(cache_key, None)
                flight.event.set()
            if publication_error is not None:
                raise publication_error
            return counts
        except Exception as exc:
            with _reviewed_counts_cache_lock:
                flight.error = exc
                _reviewed_counts_inflight.pop(cache_key, None)
                flight.event.set()
            raise
    except Exception as exc:
        logger.error("pgvector readiness query failed: %s", exc)
        raise HTTPException(status_code=503, detail="launch readiness unavailable") from exc


# --- Cache management endpoints ---


@router.get("/cache/v2/stats")
def cache_stats(request: Request) -> dict[str, Any]:
    """Cache statistics for monitoring."""
    _enforce_security_v2(
        request,
        allowed_roles={
            SecurityRole.ADMIN,
            SecurityRole.REVIEWER,
            SecurityRole.TEACHER,
            SecurityRole.INGEST_AGENT,
            SecurityRole.STUDENT,
        },
        endpoint="/cache/v2/stats",
    )
    with _cache_lock:
        return {
            "enabled": CACHE_ENABLED,
            "ttl_s": CACHE_TTL_S,
            "entries": len(_cache),
            "generation": _cache_generation,
            "public_serving": False,
        }


@router.post("/cache/v2/invalidate")
def cache_invalidate(request: Request) -> dict[str, Any]:
    """Invalidate all cache entries. Call when review_status changes."""
    _enforce_security_v2(
        request,
        allowed_roles={SecurityRole.ADMIN, SecurityRole.REVIEWER},
        endpoint="/cache/v2/invalidate",
    )
    n = invalidate_cache()
    return {"invalidated": n}


@router.post("/cache/v2/warmup")
def cache_warmup(request: Request) -> dict[str, Any]:
    """Préchauffe le cache avec les requêtes pédagogiques courantes.

    Lorsque le cache est désactivé, après authentification, ce chemin purge
    atomiquement les entrées, avance la génération et retourne les compteurs à
    zéro, sans charger la configuration ni lancer le pipeline. Lorsque le cache
    est activé, il calcule puis publie atomiquement le pipeline hybride canonique.
    """
    _enforce_security_v2(
        request,
        allowed_roles={SecurityRole.ADMIN, SecurityRole.REVIEWER},
        endpoint="/cache/v2/warmup",
    )

    if not CACHE_ENABLED:
        invalidate_cache()
        return {"warmed": 0, "collections": 0, "queries": 0}

    raise _retrieval_unavailable()


# --- Endpoint to list retrievable collections (for UI picker) ---


def _list_retrievable_collections(
    cfg: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return collections that are instanciee:true AND retrievable:true.

    The UI picker derives its list from this endpoint (D-PICKER-DERIVE-CATALOGUE).
    Adding a new instanciated collection makes it appear without UI code change.
    """
    cfg = load_collection_config() if cfg is None else cfg
    instanciated = list_instanciated_collections(cfg)
    domains = cfg.get("domains", {})

    retrievable = []
    for name in sorted(instanciated):
        try:
            defn = resolve_collection_v2(name, cfg)
        except CollectionConfigError:
            continue
        domain = defn.get("domain")
        if not isinstance(domain, str):
            continue
        domain_cfg = domains.get(domain)
        if not isinstance(domain_cfg, dict):
            continue
        if domain_cfg.get("retrievable") is not True:
            continue
        retrievable.append(
            {
                "name": name,
                "matiere": defn.get("matiere"),
                "niveau": defn.get("niveau"),
                "voie": defn.get("voie"),
                "statut": defn.get("statut"),
                "domain": domain,
                "instanciee": True,
            }
        )

    return {"collections": retrievable}


@router.get("/collections/v2")
def list_retrievable_collections(request: Request) -> dict[str, Any]:
    """Return only collections authorized by the signed BFF identity."""
    verified = _require_retrieval_identity(request, endpoint="/collections/v2")
    try:
        cfg = load_collection_config()
        allowed = effective_signed_collections(verified)
        collections_raw = cfg.get("collections")
        if not isinstance(collections_raw, Mapping) or any(
            collection not in collections_raw for collection in allowed
        ):
            raise RetrievalScopeError("retrieval scope forbidden")
        catalogue = _list_retrievable_collections(cfg)
        catalogue_by_name = {item["name"]: item for item in catalogue["collections"]}
        require_exact_release = isinstance(
            getattr(verified, "artifact", None),
            RetrievalScopeArtifactV2,
        )
        verified_artifact = getattr(verified, "artifact", None)
        scoped_items = [
            catalogue_by_name[collection]
            for collection in allowed
            if collection in catalogue_by_name
            and (
                _release_evidence_for_v2_artifact(verified_artifact) is True
                if require_exact_release
                else _release_evidence_for_collection(collection) is not False
            )
        ]
        for item in scoped_items:
            build_server_retrieval_scope(
                verified,
                collection=item["name"],
                collection_config=cfg,
            )
    except (RetrievalScopeError, CollectionConfigError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="Forbidden") from exc
    return {"collections": scoped_items}


# --- Full catalogue endpoint (LOT 27) ---


def _full_catalogue() -> dict[str, Any]:
    """Return the complete v2 catalogue with instanciation/retrievable status.

    Unlike /collections/v2 (picker: instanciated+retrievable only),
    this returns ALL declared collections for Dashboard/Administration.
    Includes taxonomy_exists and coherence_issues for governance.
    """
    cfg = load_collection_config()
    collections_raw = cfg.get("collections", {})
    domains = cfg.get("domains", {})
    known_domains = set(domains.keys()) if isinstance(domains, dict) else set()

    # Resolve taxonomy base dir
    config_path = _resolve_taxonomy_base()

    collections = []
    by_level: dict[str, list[str]] = {}
    by_domain: dict[str, list[str]] = {}
    by_status: dict[str, list[str]] = {}

    for name in sorted(collections_raw):
        defn = collections_raw[name]
        if not isinstance(defn, dict):
            continue

        domain = defn.get("domain") or "unknown"
        domain_cfg = domains.get(domain, {}) if isinstance(domains, dict) else {}
        domain_retrievable = domain_cfg.get("retrievable", False) is True
        instanciee = defn.get("instanciee") is True
        retrievable = instanciee and domain_retrievable

        niveau = defn.get("niveau")
        voie = defn.get("voie")
        matiere = defn.get("matiere")
        statut = defn.get("statut")
        taxonomy_file = defn.get("taxonomy_file")

        # Check taxonomy file existence
        taxonomy_exists = bool(
            taxonomy_file
            and config_path is not None
            and (config_path / taxonomy_file).is_file()
        )

        # Coherence checks
        coherence_issues: list[str] = []
        if domain == "quarantine":
            pass  # quarantine is special
        else:
            if not taxonomy_file:
                coherence_issues.append("taxonomy_file absent")
            elif config_path is None:
                coherence_issues.append("taxonomy_file: vérification indisponible")
            elif not taxonomy_exists:
                coherence_issues.append(f"taxonomy_file '{taxonomy_file}' non trouv\u00e9")
            if domain not in known_domains:
                coherence_issues.append(f"domaine inconnu: {domain}")
            if instanciee and not domain_retrievable:
                coherence_issues.append("instanci\u00e9e mais domaine non retrievable")
            if retrievable and not instanciee:
                coherence_issues.append("retrievable sans \u00eatre instanci\u00e9e")

        # Reasons
        ingestion_reason = (
            "collection instanci\u00e9e" if instanciee else "collection non instanci\u00e9e"
        )
        search_reason = (
            "instanci\u00e9e + domaine retrievable"
            if retrievable
            else ("domaine non retrievable" if instanciee else "non instanci\u00e9e")
        )

        entry = {
            "name": name,
            "matiere": matiere,
            "niveau": niveau,
            "voie": voie,
            "statut": statut,
            "domain": domain,
            "instanciee": instanciee,
            "retrievable": retrievable,
            "taxonomy_file": taxonomy_file,
            "taxonomy_exists": taxonomy_exists,
            "ingestion_enabled": instanciee,
            "search_enabled": retrievable,
            "ingestion_enabled_reason": ingestion_reason,
            "search_enabled_reason": search_reason,
            "coherence_issues": coherence_issues,
        }
        collections.append(entry)

        # Group by level
        level_key = niveau or "transversal"
        by_level.setdefault(level_key, []).append(name)

        # Group by domain
        by_domain.setdefault(domain, []).append(name)

        # Group by status
        status_key = statut or "autre"
        by_status.setdefault(status_key, []).append(name)

    return {
        "version": 2,
        "collections": collections,
        "by_level": by_level,
        "by_domain": by_domain,
        "by_status": by_status,
    }


def _resolve_taxonomy_base() -> Path | None:
    """Resolve taxonomy base directory (services/rag-pedago/taxonomy/)."""
    # Navigate from this module: ingestor/ -> src/ -> rag-engine/ -> services/ -> rag-pedago/
    module_dir = Path(__file__).resolve().parent
    for parent in (module_dir, *module_dir.parents):
        candidate = parent / "taxonomy"
        if candidate.is_dir():
            return candidate
        # Also check peer service
        peer = parent.parent / "rag-pedago" / "taxonomy"
        if peer.is_dir():
            return peer
    return None


@router.get("/catalogue/v2")
def get_full_catalogue(request: Request) -> dict[str, Any]:
    """Full catalogue — all declared collections with status flags.

    Réservé au BFF et aux rôles humains signés autorisés. STUDENT est exclu,
    car ce catalogue expose des détails de gouvernance.
    """
    _require_catalogue_identity(request, endpoint="/catalogue/v2")
    return _full_catalogue()


@router.get("/collections/readiness")
def get_collection_readiness(request: Request) -> dict[str, Any]:
    """Expose signed-scope diagnostics while LOT41 remains release-closed."""
    verified = _require_retrieval_identity(
        request,
        endpoint="/collections/readiness",
    )
    try:
        cfg = load_collection_config()
        collections_raw = cfg.get("collections")
        if not isinstance(collections_raw, Mapping):
            raise ValueError("collections config is malformed")
        allowed = effective_signed_collections(verified)
        scopes = tuple(
            build_server_readiness_scope(
                verified,
                collection=collection,
                collection_config=cfg,
            )
            for collection in allowed
        )
        scoped_collections = {
            collection: collections_raw[collection]
            for collection in allowed
            if collection in collections_raw
        }
        if len(scoped_collections) != len(allowed):
            raise RetrievalScopeError("retrieval scope forbidden")
        with runtime_database_budget():
            counts = _get_reviewed_chunk_counts(scopes)
        release_evidence_verified = {
            collection: _release_evidence_for_collection(collection) is True
            for collection in allowed
        }
        return _build_launch_readiness(
            {**cfg, "collections": scoped_collections},
            counts,
            min_chunks=MIN_COLLECTION_SUBSTANCE_CHUNKS,
            release_evidence_verified=release_evidence_verified,
        )
    except (RetrievalScopeError, CollectionConfigError) as exc:
        raise HTTPException(status_code=403, detail="Forbidden") from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("launch readiness unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="launch readiness unavailable") from exc


def _retrieval_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="retrieval unavailable")


def _retrieve_hybrid_hits(
    query: str,
    collection: str,
    k: int,
    scope: ServerRetrievalScope,
) -> list[HybridHit]:
    """Compose the one canonical v2 pipeline without exposing failure context."""
    try:
        settings = PoolSettings.from_env()
        with runtime_request_budget(settings.database_budget_ms):
            store = PgCandidateStore(
                lambda: pool_connection(settings),
                scope,
                statement_timeout_ms=settings.statement_timeout_ms,
            )
            return retrieve_hybrid(
                query,
                collection,
                k,
                store=store,
                embedder=BoundedInferenceEmbedder(_get_embed_model()),
                reranker=BoundedInferenceReranker(_get_reranker()),
            )
    except Exception:
        logger.error("hybrid retrieval unavailable")
        raise _retrieval_unavailable() from None


def _retrieve_endpoint_hits(
    query: str,
    collection: str,
    k: int,
    scope: ServerRetrievalScope,
) -> list[SearchV2Hit]:
    try:
        return [
            _to_search_hit(hit, query=query)
            for hit in _retrieve_hybrid_hits(query, collection, k, scope)
        ]
    except Exception:
        raise _retrieval_unavailable() from None


def _retrieve_reviewed_hits(query: str, collection: str, k: int) -> list[SearchV2Hit]:
    """Refuser l'ancien évaluateur online dépourvu d'identité signée."""
    del query, collection, k
    raise _retrieval_unavailable()


_PREVIEW_LIMIT = 200
_QUERY_PREVIEW_STOP_WORDS = frozenset(
    {"avec", "cette", "comment", "dans", "pour", "sans", "une", "des"}
)


def _query_relevant_preview(text: str, query: str | None) -> str:
    source = text.strip()
    if len(source) <= _PREVIEW_LIMIT or not query:
        return source[:_PREVIEW_LIMIT]

    query_terms = {
        term
        for term in re.findall(r"[^\W\d_]{4,}", query.casefold(), flags=re.UNICODE)
        if term not in _QUERY_PREVIEW_STOP_WORDS
    }
    folded = source.casefold()
    anchors = sorted(
        {
            match.start()
            for term in query_terms
            for match in re.finditer(re.escape(term), folded)
        }
    )
    if not anchors:
        return source[:_PREVIEW_LIMIT]

    candidates: list[tuple[int, int, str]] = []
    for anchor in anchors:
        start = max(0, anchor - (_PREVIEW_LIMIT // 3))
        if start > 0:
            next_space = source.find(" ", start)
            if 0 < next_space < anchor:
                start = next_space + 1
        preview = source[start : start + _PREVIEW_LIMIT].strip()
        score = sum(term in preview.casefold() for term in query_terms)
        candidates.append((score, -start, preview))
    return max(candidates)[2]


def _to_search_hit(hit: HybridHit, *, query: str | None = None) -> SearchV2Hit:
    candidate = hit.candidate
    return SearchV2Hit(
        chunk_id=candidate.chunk_id,
        doc_id=candidate.doc_id,
        source_label=candidate.source_label,
        source_uri=candidate.source_uri,
        rights=candidate.rights,
        type_doc=candidate.type_doc,
        review_status=candidate.review_status,
        artifact_id=candidate.artifact_id,
        content_sha256=candidate.content_sha256,
        placement_id=candidate.placement_id,
        placement_source_scope=candidate.placement_source_scope,
        placement_source_id=candidate.placement_source_id,
        placement_source_path=candidate.placement_source_path,
        page=candidate.page_start,
        preview=_query_relevant_preview(candidate.text, query),
        dense_score=candidate.dense_score,
        lexical_score=candidate.lexical_score,
        rrf_score=hit.rrf_score,
        rerank_score=hit.rerank_score,
        mmr_score=hit.mmr_score,
        score_final=hit.score_final,
    )


def _to_retrieval_result(
    hit: SearchV2Hit,
    collection: str,
    *,
    include_citation: bool = True,
) -> RetrievalResult:
    metadata: dict[str, object] = {
        "collection": collection,
        "type_doc": hit.type_doc,
        "review_status": hit.review_status,
        "dense_score": hit.dense_score,
        "dense_sim": hit.dense_sim,
        "lexical_score": hit.lexical_score,
        "rrf_score": hit.rrf_score,
        "rerank_score": hit.rerank_score,
        "mmr_score": hit.mmr_score,
        "score_final": hit.score_final,
    }
    if hit.artifact_id is not None:
        metadata.update(
            {
                "artifact_id": hit.artifact_id,
                "content_sha256": hit.content_sha256,
                "placement_id": hit.placement_id,
                "placement_source_scope": hit.placement_source_scope,
                "placement_source_id": hit.placement_source_id,
                "placement_source_path": hit.placement_source_path,
            }
        )
    return RetrievalResult(
        chunk_id=hit.chunk_id,
        doc_id=hit.doc_id,
        score=hit.score_final,
        title=hit.source_label,
        excerpt=hit.preview,
        citation=(
            Citation(
                source_label=hit.source_label,
                page=hit.page,
                source_uri=hit.source_uri,
                rights=hit.rights,
            )
            if include_citation
            else None
        ),
        metadata=metadata,
    )


def _canonical_retrieval_request_sha256(payload: RetrievalRequest) -> str:
    """Digest exactly the strict shared request model used by the signed envelope."""

    return hashlib.sha256(canonical_model_bytes(payload)).hexdigest()


def _servable_corpus_repository():
    return configured_servable_corpus_repository()


def _require_manifest_bound_corpus(
    payload: RetrievalRequest,
    verified: VerifiedInternalIdentity,
    repository: object,
) -> ServableCorpus:
    """Resolve a canonical corpus only when request, envelope and scope agree."""

    manifest_sha256 = payload.manifest_sha256
    corpus_id = payload.corpus_id
    corpus_version_id = payload.corpus_version_id
    envelope = verified.envelope
    if (
        manifest_sha256 is None
        or corpus_id is None
        or corpus_version_id is None
        or envelope.manifest_sha256 != manifest_sha256
        or envelope.request_sha256 != _canonical_retrieval_request_sha256(payload)
    ):
        raise RetrievalScopeError("retrieval scope forbidden")
    try:
        corpus = repository.resolve_corpus(
            manifest_sha256=manifest_sha256,
            corpus_id=corpus_id,
            corpus_version_id=corpus_version_id,
        )
    except ServableCorpusRepositoryError as exc:
        raise HTTPException(status_code=409, detail="manifest incompatible") from exc
    except AttributeError as exc:
        raise RetrievalScopeError("retrieval scope forbidden") from exc
    if (
        not isinstance(corpus, ServableCorpus)
        or verified.artifact != corpus.retrieval_scope
        or corpus.physical_collection not in envelope.allowed_collections
    ):
        raise RetrievalScopeError("retrieval scope forbidden")
    return corpus


def _to_manifest_bound_retrieval_result(
    hit: SearchV2Hit,
    corpus: ServableCorpus,
    *,
    manifest_sha256: str,
    include_citation: bool,
) -> RetrievalResult:
    """Reconcile a database hit with immutable manifest identity before exposure."""

    matches = [
        (resource, chunk)
        for resource in corpus.resources
        for chunk in resource.chunks
        if chunk.chunk_id == hit.chunk_id
    ]
    if len(matches) != 1:
        raise HTTPException(status_code=503, detail="retrieval evidence unavailable")
    resource, chunk = matches[0]
    if not (
        hit.artifact_id == resource.content_sha256
        and hit.content_sha256 == resource.content_sha256
        and hit.doc_id == resource.content_sha256
    ):
        raise HTTPException(status_code=503, detail="retrieval evidence unavailable")
    base = _to_retrieval_result(
        hit,
        str(corpus.physical_collection),
        include_citation=include_citation,
    )
    return RetrievalResult(
        **base.model_dump(
            mode="python",
            exclude={
                "resource_id",
                "resource_version_id",
                "content_sha256",
                "locator",
                "corpus_id",
                "corpus_version_id",
                "manifest_sha256",
            },
        ),
        resource_id=resource.resource_id,
        resource_version_id=resource.resource_version_id,
        content_sha256=resource.content_sha256,
        locator=chunk.locator,
        corpus_id=corpus.corpus_id,
        corpus_version_id=corpus.corpus_version_id,
        manifest_sha256=manifest_sha256,
    )


def _chat_refusal(
    message: str,
    reason: str,
    retrieval_hits: list[RetrievalResult],
) -> ChatResponse:
    return ChatResponse(
        answer=message,
        grounded=False,
        citations=[],
        warnings=[reason],
        refusal_reason=reason,
        retrieval_hits=retrieval_hits,
    )


def _require_chat_profile_match(
    payload: ChatRequest,
    collections: list[str],
    scopes: Mapping[str, ServerRetrievalScope],
    *,
    verified: VerifiedInternalIdentity | None = None,
) -> None:
    """Refuser toute divergence entre le DTO historique et le scope signé."""
    if not collections:
        raise HTTPException(status_code=403, detail="Forbidden")
    first = scopes[collections[0]]
    artifact = getattr(verified, "artifact", None)
    if isinstance(artifact, RetrievalScopeArtifactV3):
        raise HTTPException(status_code=403, detail="Forbidden")
    if isinstance(artifact, RetrievalScopeArtifactV2):
        if collections != [artifact.evidence_subject.collection]:
            raise HTTPException(status_code=403, detail="Forbidden")
        target = artifact.target_identity
        expected = {
            "niveau": target.niveau.value,
            "voie": target.voie.value,
            "matieres": [target.matiere],
            "statut_enseignement": target.statut_enseignement.value,
            "candidat": target.candidates[0].value,
            "school_year": artifact.evidence_subject.school_year,
            "zone": target.audience,
        }
    else:
        expected = {
            "niveau": first.niveau,
            "voie": first.voie,
            "matieres": [scopes[collection].matiere for collection in collections],
            "statut_enseignement": first.statut_enseignement,
            "candidat": first.candidat,
            "school_year": first.school_year,
            "zone": first.audiences[0],
        }
    profile = payload.student_profile
    actual = {
        "niveau": profile.niveau.value,
        "voie": profile.voie.value,
        "matieres": [value for value in profile.matieres],
        "statut_enseignement": profile.statut_enseignement.value,
        "candidat": profile.candidat.value,
        "school_year": profile.school_year,
        "zone": profile.zone,
    }
    if actual != expected:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Retrieve reviewed evidence while generation remains governance-locked."""
    verified = _require_retrieval_identity(request, endpoint="/chat")
    cfg = load_collection_config()
    collections = list(dict.fromkeys(payload.collections))
    scopes: dict[str, ServerRetrievalScope] = {}
    for collection in collections:
        try:
            _check_retrievable(collection, cfg, verified)
            scopes[collection] = build_server_retrieval_scope(
                verified,
                collection=collection,
                collection_config=cfg,
            )
        except (RetrievalScopeError, CollectionConfigError, HTTPException) as exc:
            raise HTTPException(status_code=403, detail="Forbidden") from exc

    _require_chat_profile_match(
        payload,
        collections,
        scopes,
        verified=verified,
    )

    all_hits: list[tuple[str, SearchV2Hit]] = []
    with runtime_request_budget():
        for collection in collections:
            all_hits.extend(
                (collection, hit)
                for hit in _retrieve_endpoint_hits(
                    payload.query,
                    collection,
                    payload.top_k,
                    scopes[collection],
                )
            )

    unique_hits: list[tuple[str, SearchV2Hit]] = []
    seen_chunk_ids: set[str] = set()
    for collection, hit in all_hits:
        if hit.chunk_id not in seen_chunk_ids:
            seen_chunk_ids.add(hit.chunk_id)
            unique_hits.append((collection, hit))
    retrieval_hits = (
        [_to_retrieval_result(hit, collection) for collection, hit in unique_hits]
        if payload.include_retrieval
        else []
    )
    return _chat_refusal(
        "La génération de réponse reste verrouillée par la gouvernance.",
        "answer_generation_locked",
        retrieval_hits,
    )


# --- Main search endpoint ---


def _collection_for_retrieval_request(
    payload: RetrievalRequest,
    verified: VerifiedInternalIdentity,
) -> str:
    """Résoudre une matière contractuelle vers l'artefact signé du serveur."""
    artifact = verified.artifact
    if isinstance(artifact, RetrievalScopeArtifactV2 | RetrievalScopeArtifactV3):
        curriculum = payload.curriculum_scope
        evidence = artifact.evidence_subject
        if curriculum is None:
            raise RetrievalScopeError("retrieval scope forbidden")
        requested = (
            curriculum.niveau.value,
            curriculum.voie.value,
            curriculum.matiere,
            curriculum.statut_enseignement.value,
        )
        expected = (
            evidence.niveau.value,
            evidence.voie.value,
            evidence.matiere,
            evidence.statut_enseignement.value,
        )
        if requested != expected:
            raise RetrievalScopeError("retrieval scope forbidden")
        allowed = effective_signed_collections(verified)
        if allowed != (evidence.collection,):
            raise RetrievalScopeError("retrieval scope forbidden")
        return str(evidence.collection)

    matieres = payload.student_profile.matieres
    if len(matieres) != 1:
        raise RetrievalScopeError("retrieval scope forbidden")
    allowed_collections = set(effective_signed_collections(verified))
    matches = [
        subject.collection
        for subject in verified.artifact.subjects
        if subject.matiere == matieres[0]
        and subject.collection in allowed_collections
    ]
    if len(matches) != 1:
        raise RetrievalScopeError("retrieval scope forbidden")
    return str(matches[0])


def _require_retrieval_profile_match(
    payload: RetrievalRequest,
    scope: ServerRetrievalScope,
    verified: VerifiedInternalIdentity | None = None,
) -> None:
    """Refuser toute dimension contractuelle différente du scope signé."""
    artifact = getattr(verified, "artifact", None)
    if isinstance(artifact, RetrievalScopeArtifactV2 | RetrievalScopeArtifactV3):
        assert verified is not None
        _require_student_target_match(payload, verified)
        _require_curriculum_evidence_match(payload, scope, verified)
        return

    profile = payload.student_profile
    expected = {
        "niveau": scope.niveau,
        "voie": scope.voie,
        "matieres": [scope.matiere],
        "statut_enseignement": scope.statut_enseignement,
        "candidat": scope.candidat,
        "school_year": scope.school_year,
        "zone": scope.audiences[0],
        "audience": scope.audiences[0],
    }
    actual = {
        "niveau": profile.niveau.value,
        "voie": profile.voie.value,
        "matieres": list(profile.matieres),
        "statut_enseignement": profile.statut_enseignement.value,
        "candidat": profile.candidat.value,
        "school_year": profile.school_year,
        "zone": profile.zone,
        "audience": profile.audience,
    }
    if actual != expected:
        raise RetrievalScopeError("retrieval scope forbidden")
    curriculum = payload.curriculum_scope
    if curriculum is not None and (
        curriculum.niveau.value,
        curriculum.voie.value,
        curriculum.matiere,
        curriculum.statut_enseignement.value,
    ) != (
        scope.niveau,
        scope.voie,
        scope.matiere,
        scope.statut_enseignement,
    ):
        raise RetrievalScopeError("retrieval scope forbidden")


def _require_student_target_match(
    payload: RetrievalRequest,
    verified: VerifiedInternalIdentity,
) -> None:
    """Lier le profil de requête à la cible élève signée V2."""
    artifact = verified.artifact
    if not isinstance(artifact, RetrievalScopeArtifactV2 | RetrievalScopeArtifactV3):
        raise RetrievalScopeError("retrieval scope forbidden")
    profile = payload.student_profile
    target = (
        artifact.target_identity
        if isinstance(artifact, RetrievalScopeArtifactV2)
        else artifact.target_policy
    )
    actual = (
        profile.niveau.value,
        profile.voie.value,
        tuple(profile.matieres),
        profile.statut_enseignement.value,
        profile.candidat.value,
        profile.school_year,
        profile.zone,
        profile.audience,
    )
    expected = (
        target.niveau.value,
        target.voie.value,
        (target.matiere,),
        target.statut_enseignement.value,
        verified.envelope.identity.pedagogical_profile.candidat.value,
        artifact.evidence_subject.school_year,
        verified.envelope.identity.pedagogical_profile.audience,
        verified.envelope.identity.pedagogical_profile.audience,
    )
    if actual != expected:
        raise RetrievalScopeError("retrieval scope forbidden")


def _require_curriculum_evidence_match(
    payload: RetrievalRequest,
    scope: ServerRetrievalScope,
    verified: VerifiedInternalIdentity,
) -> None:
    """Lier la portée curriculaire aux dimensions SQL signées V2."""
    artifact = verified.artifact
    curriculum = payload.curriculum_scope
    if not isinstance(artifact, RetrievalScopeArtifactV2 | RetrievalScopeArtifactV3) or curriculum is None:
        raise RetrievalScopeError("retrieval scope forbidden")
    evidence = artifact.evidence_subject
    requested = (
        curriculum.niveau.value,
        curriculum.voie.value,
        curriculum.matiere,
        curriculum.statut_enseignement.value,
    )
    signed = (
        evidence.niveau.value,
        evidence.voie.value,
        evidence.matiere,
        evidence.statut_enseignement.value,
    )
    server = (
        scope.niveau,
        scope.voie,
        scope.matiere,
        scope.statut_enseignement,
    )
    if requested != signed or server != signed or scope.collection != evidence.collection:
        raise RetrievalScopeError("retrieval scope forbidden")


@router.post("/search/v2", response_model=RetrievalResponse)
def search_v2(payload: RetrievalRequest, request: Request) -> RetrievalResponse:
    """Retrieval v2: dense + lexical → RRF → rerank → seuil → MMR.

    Canonical pipeline LOT40. Gate retrievable fail-closed (GG-01).
    answer_generation_allowed = false.
    """
    verified = _require_retrieval_identity(
        request,
        endpoint="/search/v2",
        payload=payload,
    )

    cfg = load_collection_config()
    corpus: ServableCorpus | None = None
    try:
        if payload.manifest_sha256 is None:
            collection = _collection_for_retrieval_request(payload, verified)
        else:
            corpus = _require_manifest_bound_corpus(
                payload,
                verified,
                _servable_corpus_repository(),
            )
            collection = str(corpus.physical_collection)
        _check_retrievable(collection, cfg, verified)
        scope = build_server_retrieval_scope(
            verified,
            collection=collection,
            collection_config=cfg,
        )
        _require_retrieval_profile_match(payload, scope, verified)
        adapted = adapt_retrieval_request(
            payload,
            collection=collection,
            collection_config=cfg,
        )
    except HTTPException:
        raise
    except (RetrievalScopeError, CollectionConfigError) as exc:
        raise HTTPException(status_code=403, detail="Forbidden") from exc

    if (
        payload.need.notions
        or payload.need.desired_doc_types
        or payload.need.difficulty_max is not None
    ):
        raise HTTPException(status_code=422, detail="Unsupported retrieval filters")

    if not payload.retrieval.hybrid or not payload.retrieval.rerank:
        raise HTTPException(status_code=422, detail="Unsupported retrieval options")

    # Public retrieval always re-reads PostgreSQL through the canonical pipeline.
    hits = _retrieve_endpoint_hits(
        adapted.query,
        adapted.nexus_collection,
        adapted.top_k,
        scope,
    )

    results = [
        (
            _to_manifest_bound_retrieval_result(
                hit,
                corpus,
                manifest_sha256=str(payload.manifest_sha256),
                include_citation=adapted.include_citations,
            )
            if corpus is not None
            else _to_retrieval_result(
                hit,
                adapted.nexus_collection,
                include_citation=adapted.include_citations,
            )
        )
        for hit in hits
    ]
    filters_applied: dict[str, object] = {
        "collection": adapted.nexus_collection,
        "scope_digest": scope.filter_digest,
    }
    if corpus is not None:
        filters_applied.update(
            {
                "manifest_sha256": payload.manifest_sha256,
                "corpus_id": corpus.corpus_id,
                "corpus_version_id": corpus.corpus_version_id,
            }
        )
    return RetrievalResponse(
        results=results,
        warnings=list(adapted.warnings),
        filters_applied=filters_applied,
    )


def _enforce_security_v2(
    request: Request,
    *,
    allowed_roles: set[SecurityRole],
    endpoint: str,
) -> tuple[SecurityRole, str]:
    """Auth check via centralized role gates."""
    return require_role(request, allowed_roles=allowed_roles, endpoint=endpoint)


def _require_retrieval_identity(
    request: Request,
    *,
    endpoint: str,
    payload: RetrievalRequest | None = None,
) -> VerifiedInternalIdentity:
    """Exiger le credential BFF puis l'enveloppe signée avant tout retrieval."""
    require_bff_service(request, endpoint=endpoint)
    if payload is None or payload.manifest_sha256 is None:
        return require_internal_identity(request)
    if payload.corpus_id is None or payload.corpus_version_id is None:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        corpus = _servable_corpus_repository().resolve_corpus(
            manifest_sha256=payload.manifest_sha256,
            corpus_id=payload.corpus_id,
            corpus_version_id=payload.corpus_version_id,
        )
        base = load_identity_verifier_config()
        artifact = corpus.retrieval_scope
        config = replace(
            base,
            artifact=artifact,
            artifacts={artifact.scope_id: artifact},
        )
    except (ServableCorpusRepositoryError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="manifest incompatible") from exc
    return require_internal_identity(request, config=config)


def _require_catalogue_identity(
    request: Request,
    *,
    endpoint: str,
) -> VerifiedInternalIdentity:
    """Exiger le BFF, l'identité signée et un rôle autorisé au catalogue."""
    verified = _require_retrieval_identity(request, endpoint=endpoint)
    if verified.envelope.identity.role not in _CATALOGUE_ROLES:
        raise HTTPException(status_code=403, detail="Forbidden")
    return verified
