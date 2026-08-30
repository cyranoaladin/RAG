"""Private read-only HTTP surface for immutable servable corpus artifacts."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from nexus_contracts import ServableCorpusIndex, ServableCorpusManifest

try:
    from .security_v2 import require_bff_service
    from .servable_corpus_index import (
        FilesystemServableCorpusRepository,
        ServableCorpusRepositoryError,
    )
except ImportError:
    from security_v2 import require_bff_service  # type: ignore[no-redef]
    from servable_corpus_index import (  # type: ignore[no-redef]
        FilesystemServableCorpusRepository,
        ServableCorpusRepositoryError,
    )

router = APIRouter(tags=["servable_corpus"])


def configured_servable_corpus_repository() -> FilesystemServableCorpusRepository:
    """Build the one fail-closed repository from an externally pinned index."""

    directory = os.environ.get("RAG_SERVABLE_CORPUS_DIRECTORY", "").strip()
    expected_index_sha256 = os.environ.get(
        "RAG_SERVABLE_CORPUS_INDEX_SHA256",
        "",
    ).strip()
    if not directory or not re.fullmatch(r"[0-9a-f]{64}", expected_index_sha256):
        raise HTTPException(status_code=503, detail="servable corpus unavailable")
    return FilesystemServableCorpusRepository(
        directory=Path(directory),
        expected_index_sha256=expected_index_sha256,
        now=lambda: datetime.now(UTC),
    )


@router.get("/corpora/servable/v1", response_model=ServableCorpusIndex)
def get_servable_corpus_index(request: Request) -> ServableCorpusIndex:
    require_bff_service(request, endpoint="/corpora/servable/v1")
    try:
        return configured_servable_corpus_repository().index()
    except ServableCorpusRepositoryError as exc:
        raise HTTPException(status_code=503, detail="servable corpus unavailable") from exc


@router.get(
    "/corpora/servable/v1/{manifest_sha256}",
    response_model=ServableCorpusManifest,
)
def get_servable_corpus_manifest(
    manifest_sha256: str,
    request: Request,
) -> ServableCorpusManifest:
    require_bff_service(request, endpoint="/corpora/servable/v1/manifest")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
        raise HTTPException(status_code=404, detail="manifest unavailable")
    try:
        return configured_servable_corpus_repository().manifest(manifest_sha256)
    except ServableCorpusRepositoryError as exc:
        raise HTTPException(status_code=404, detail="manifest unavailable") from exc


__all__ = ["configured_servable_corpus_repository", "router"]
