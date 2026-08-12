"""Acceptance minimale avec les VRAIS modèles E5/reranker, exécutable sur un
runner GitHub-hosted (LOT H2-B remédiation, finding P2-real-model-ci-
coverage).

Ce que ce fichier prouve, honnêtement borné :

* le modèle E5 réel (pas un stub) encode du texte français en vecteurs
  1024-d plausibles (deux phrases proches sémantiquement se ressemblent
  plus qu'une phrase sans rapport) ;
* le reranker réel (pas un stub) ordonne un passage pertinent au-dessus
  d'un passage non pertinent pour une même requête ;
* ces vecteurs réels transitent par un VRAI pgvector éphémère (recherche
  ANN par cosinus), pas une valeur synthétique.

Ce que ce fichier NE prétend PAS prouver : l'ingestion multi-niveaux
complète avec le corpus propriétaire (``test_multilevel_real_ingestion.py``,
``test_wave0_french_pgvector.py``) — ces PDF ne sont délibérément pas
committés (droits d'auteur des manuels), donc hors de portée d'un runner
hosted. Voir docs/reports/h2_exact_head_remediation_pre_go_live.md pour la
portée exacte retenue.
"""

from __future__ import annotations

import math
import os
import uuid
from pathlib import Path

import psycopg
import pytest

from ingestor.embedding_contract import load_embedding_model, verify_embedding_artifact
from ingestor.reranker_contract import load_reranker_model, verify_reranker_artifact

pytestmark = [pytest.mark.integration]

E5_PATH = Path(os.environ.get("RAG_EMBEDDING_MODEL_CACHE_DIR", ""))
E5_INVENTORY_SHA256 = os.environ.get("RAG_EMBEDDING_MODEL_INVENTORY_SHA256", "")
RERANKER_PATH = Path(os.environ.get("RAG_RERANKER_MODEL_CACHE_DIR", ""))
RERANKER_INVENTORY_SHA256 = os.environ.get("RAG_RERANKER_MODEL_INVENTORY_SHA256", "")
PGVECTOR_DSN = os.environ.get("NEXUS_REAL_MODEL_PGVECTOR_DSN", "")

_REQUIRED_ENV = (
    "RAG_EMBEDDING_MODEL_CACHE_DIR",
    "RAG_EMBEDDING_MODEL_INVENTORY_SHA256",
    "RAG_RERANKER_MODEL_CACHE_DIR",
    "RAG_RERANKER_MODEL_INVENTORY_SHA256",
)
_missing = [name for name in _REQUIRED_ENV if not os.environ.get(name, "").strip()]
if _missing:
    pytest.skip(
        f"real-model acceptance requires {', '.join(_missing)} — opt-in, "
        "never run by default (see the real-model-acceptance CI job)",
        allow_module_level=True,
    )


@pytest.fixture(scope="module")
def real_embedder() -> object:
    artifact_root = verify_embedding_artifact(
        E5_PATH, expected_inventory_sha256=E5_INVENTORY_SHA256
    )
    return load_embedding_model(verified_artifact_root=artifact_root)


@pytest.fixture(scope="module")
def real_reranker() -> object:
    artifact_root = verify_reranker_artifact(
        RERANKER_PATH, expected_inventory_sha256=RERANKER_INVENTORY_SHA256
    )
    return load_reranker_model(verified_artifact_root=artifact_root)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)


def test_real_e5_embeddings_are_plausible(real_embedder: object) -> None:
    """Real model, real encode — not asserting a golden vector (which would
    pin an implementation detail), only that the geometry is sane."""
    near_a = "Les triangles rectangles vérifient le théorème de Pythagore."
    near_b = "Le théorème de Pythagore relie les côtés d'un triangle rectangle."
    unrelated = "La conjugaison du verbe être au présent de l'indicatif."

    vectors = real_embedder.encode(  # type: ignore[attr-defined]
        [near_a, near_b, unrelated], normalize_embeddings=True
    )
    vec_a, vec_b, vec_unrelated = (list(map(float, v)) for v in vectors)

    assert len(vec_a) == 1024
    assert not all(value == 0.0 for value in vec_a)

    similar_score = _cosine(vec_a, vec_b)
    unrelated_score = _cosine(vec_a, vec_unrelated)
    assert similar_score > unrelated_score
    assert similar_score > 0.8


def test_real_reranker_orders_passages_by_relevance(real_reranker: object) -> None:
    query = "Quel est le théorème qui relie les côtés d'un triangle rectangle ?"
    relevant = (
        "Le théorème de Pythagore énonce que dans un triangle rectangle, le "
        "carré de l'hypoténuse est égal à la somme des carrés des deux "
        "autres côtés."
    )
    irrelevant = (
        "La photosynthèse est le processus par lequel les plantes "
        "convertissent la lumière en énergie chimique."
    )

    scores = real_reranker.predict(  # type: ignore[attr-defined]
        [(query, relevant), (query, irrelevant)]
    )
    relevant_score, irrelevant_score = (float(score) for score in scores)
    assert relevant_score > irrelevant_score


@pytest.mark.skipif(
    not PGVECTOR_DSN,
    reason="NEXUS_REAL_MODEL_PGVECTOR_DSN not set — minimal pgvector acceptance opt-in",
)
def test_real_e5_vectors_round_trip_through_pgvector(real_embedder: object) -> None:
    """Minimal, self-contained pgvector acceptance: real E5 vectors in, a
    real ANN cosine query out — no ingestion pipeline, no schema history,
    just proving real vectors behave correctly once inside pgvector."""
    near_a = "Les triangles rectangles vérifient le théorème de Pythagore."
    near_b = "Le théorème de Pythagore relie les côtés d'un triangle rectangle."
    unrelated = "La conjugaison du verbe être au présent de l'indicatif."
    query_text = "théorème de Pythagore et triangle rectangle"

    vectors = real_embedder.encode(  # type: ignore[attr-defined]
        [near_a, near_b, unrelated, query_text], normalize_embeddings=True
    )
    vec_a, vec_b, vec_unrelated, vec_query = (
        "[" + ",".join(str(float(x)) for x in v) + "]" for v in vectors
    )

    table = f"real_model_acceptance_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(PGVECTOR_DSN, autocommit=True) as conn:
        with conn.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cursor.execute(
                f"CREATE TABLE {table} (id text PRIMARY KEY, content text, "
                f"embedding vector(1024))"
            )
            try:
                cursor.execute(
                    f"INSERT INTO {table} (id, content, embedding) VALUES "
                    f"(%s, %s, %s::vector), (%s, %s, %s::vector), "
                    f"(%s, %s, %s::vector)",
                    (
                        "near_a", near_a, vec_a,
                        "near_b", near_b, vec_b,
                        "unrelated", unrelated, vec_unrelated,
                    ),
                )
                cursor.execute(
                    f"SELECT id FROM {table} "
                    f"ORDER BY embedding <=> %s::vector ASC LIMIT 1",
                    (vec_query,),
                )
                (top_id,) = cursor.fetchone()  # type: ignore[misc]
                # Assert the robust invariant only: the real ANN query in
                # pgvector must rank one of the two topically-related
                # sentences above the unrelated one. Pinning which of the
                # two near-duplicates wins would be an implementation
                # detail of the real model's embedding space, not something
                # this acceptance test should assume.
                assert top_id in {"near_a", "near_b"}
            finally:
                cursor.execute(f"DROP TABLE IF EXISTS {table}")
