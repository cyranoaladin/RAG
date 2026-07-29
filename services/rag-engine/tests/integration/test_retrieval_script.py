"""Integration tests for pgvector retrieval and indexing script (DETTE-16-ITEST-RETRIEVAL).

Requires a pgvector database instance (via DATABASE_URL_TEST).

Usage:
    DATABASE_URL_TEST="postgresql://raguser:test@localhost:5435/ragdb_test" \
    pytest tests/integration/test_retrieval_script.py -v
"""
from __future__ import annotations

import os

import pytest

from ingestor.database import RagDatabase

DSN = os.getenv(
    "DATABASE_URL_TEST",
    "postgresql://raguser:test@localhost:5435/ragdb_test",
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("DATABASE_URL_TEST"),
        reason="DATABASE_URL_TEST not set — skip integration tests",
    ),
]


@pytest.fixture
async def db():
    """Fixture: async connection to test database."""
    database = RagDatabase(DSN)
    await database.connect(min_size=1, max_size=3)
    yield database
    await database.disconnect()


@pytest.mark.asyncio
async def test_retrieval_integration_pipeline(db: RagDatabase) -> None:
    """Test full document upsert, chunk insertion, embedding search, and cleanup."""
    tenant = "libre_terminale"
    doc_id = await db.upsert_document(
        tenant=tenant,
        source_type="markdown",
        source_path="/test/maths_terminale_integration.md",
        title="Fiche de Test Intégration Limites",
        file_hash="hash_retrieval_test_123",
        embed_model="nomic-embed-text:v1.5",
        embed_dim=768,
    )
    assert doc_id is not None

    fake_embedding = [0.01] * 768
    chunk_id = await db.insert_chunk(
        doc_id=doc_id,
        chunk_index=0,
        content="La limite d'une fonction f en x0 est egale a L si pour tout epsilon...",
        content_hash="hash_chunk_limit_1",
        embedding=fake_embedding,
        metadata={
            "tenant": tenant,
            "matiere": "maths",
            "niveau": "terminale",
            "notion": "limites",
            "type": "cours",
        },
    )
    assert chunk_id is not None

    # Retrieve via vector similarity search
    results = await db.search_similar_chunks(
        tenant=tenant,
        query_embedding=fake_embedding,
        top_k=5,
        matiere="maths",
    )
    assert len(results) >= 1
    matched_ids = [str(r.get("id")) for r in results if r.get("id")]
    assert str(chunk_id) in matched_ids

    # Cleanup
    await db.delete_document(doc_id, tenant)
