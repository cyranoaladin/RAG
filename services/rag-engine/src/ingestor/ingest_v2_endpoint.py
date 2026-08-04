"""Ingestion v2 endpoints — FastAPI router (FE-03).

Exposes POST /ingest/v2/upload-files, /ingest/v2/urls, /ingest/v2/drive.
All routes use the ingest_v2 pipeline (governance-compliant).
Legacy /ingest/* endpoints (defined in api.py) are still registered on this
FastAPI app for internal/back-compat reasons, but Nginx closes them (410) at
the edge — see infra/nginx/rag-v2.conf and rag-api.conf.template (LOT43).
"""
from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

try:
    from .ingest_v2 import IngestV2Request, Provenance, _get_default_scope, ingest_document
    from .security_v2 import SecurityRole, require_role, token_hash
    from .ssrf_guard import ResponseTooLargeError, SSRFValidationError, safe_fetch
except (ImportError, ValueError):
    from ingest_v2 import (  # type: ignore[no-redef]
        IngestV2Request,
        Provenance,
        _get_default_scope,
        ingest_document,
    )
    from security_v2 import SecurityRole, require_role, token_hash  # type: ignore[no-redef]
    from ssrf_guard import (  # type: ignore[no-redef]
        ResponseTooLargeError,
        SSRFValidationError,
        safe_fetch,
    )

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest/v2", tags=["ingestion_v2"])


def _best_effort_track_job(req: IngestV2Request, *, dedup_key: str) -> None:
    """Câblage best-effort LOT44e (job de suivi ``ingestion_control``) —
    ne modifie jamais la réponse, ne bloque jamais, ne lève jamais.
    Aucun profil de production LOT44c n'est consulté ni contourné ici : ce
    job de suivi n'est traité par aucun worker tant que LOT44c reste
    bloqué (``PRODUCTION_BLOCKED_NO_PRODUCTION_PROFILES``)."""
    try:
        from .ingestion_worker.ingest_v2_bridge import best_effort_create_ingest_job
    except (ImportError, ValueError):
        try:
            from ingestion_worker.ingest_v2_bridge import (  # type: ignore[no-redef]
                best_effort_create_ingest_job,
            )
        except Exception:
            logger.warning("ingest_v2_job_tracking_unavailable", exc_info=True)
            return

    try:
        default_scope = _get_default_scope()
        best_effort_create_ingest_job(
            collection=req.collection,
            source_label=req.source_label,
            source_uri=req.source_uri,
            rights=req.rights,
            type_doc=req.type_doc,
            matiere=req.matiere,
            niveau=req.niveau,
            voie=req.voie,
            audience=req.audience,
            default_tenant=default_scope.tenant,
            default_candidat=default_scope.candidat,
            default_visibility=default_scope.visibility,
            default_school_year=default_scope.school_year,
            default_programme_version=default_scope.programme_version,
            dedup_key=dedup_key,
        )
    except Exception:
        logger.warning("ingest_v2_job_tracking_failed", exc_info=True)


MAX_REMOTE_BYTES = int(os.environ.get("MAX_REMOTE_BYTES", 50 * 1024 * 1024))  # 50 MB max per URL fetch
MAX_UPLOAD_FILE_BYTES = int(os.environ.get("MAX_UPLOAD_FILE_BYTES", 50 * 1024 * 1024))  # 50 MB max per uploaded file
MAX_FILES_PER_UPLOAD = int(os.environ.get("MAX_FILES_PER_UPLOAD", 20))
MAX_URLS_PER_REQUEST = int(os.environ.get("MAX_URLS_PER_REQUEST", 20))
MAX_URLS_PER_DOMAIN_PER_REQUEST = int(os.environ.get("MAX_URLS_PER_DOMAIN_PER_REQUEST", 10))
MAX_EXTRACTED_TEXT_CHARS = int(os.environ.get("MAX_EXTRACTED_TEXT_CHARS", 5_000_000))
MAX_PDF_PAGES = int(os.environ.get("MAX_PDF_PAGES", 2000))


def _read_upload_bounded(upload_file: UploadFile, max_bytes: int) -> bytes:
    """Read an uploaded file's content, aborting before buffering past max_bytes+1.

    Never calls the unbounded ``upload_file.file.read()`` — a single large
    upload must not be able to exhaust worker memory.
    """
    chunk_size = 1024 * 1024
    buffer = bytearray()
    while True:
        chunk = upload_file.file.read(chunk_size)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            return bytes(buffer[: max_bytes + 1])
    return bytes(buffer)


def _enforce_security(request: Request) -> str:
    """Auth + IP allowlist check. Returns token for provenance."""
    _role, token = require_role(
        request,
        allowed_roles={SecurityRole.ADMIN, SecurityRole.INGEST_AGENT},
        endpoint="/ingest/v2/*",
        enforce_ip_allowlist=True,
    )
    return token


def _extract_text_from_file(file_path: Path) -> str:
    """Extract text from a file (PDF, DOCX, MD, TXT, IPYNB, TEX)."""
    suffix = file_path.suffix.lower()

    if suffix in (".md", ".txt", ".tex"):
        return file_path.read_text(encoding="utf-8", errors="replace")

    if suffix == ".pdf":
        import pypdf
        reader = pypdf.PdfReader(str(file_path))
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ValueError(
                f"PDF has too many pages ({len(reader.pages)} > {MAX_PDF_PAGES})"
            )
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)

    if suffix == ".docx":
        import docx
        doc = docx.Document(str(file_path))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())

    if suffix == ".ipynb":
        import json
        nb = json.loads(file_path.read_text(encoding="utf-8"))
        parts = []
        for cell in nb.get("cells", []):
            if cell.get("cell_type") in ("markdown", "code"):
                source = cell.get("source", [])
                if isinstance(source, list):
                    parts.append("".join(source))
                elif isinstance(source, str):
                    parts.append(source)
            # Outputs intentionally excluded (LOT 25a: no base64 images)
        return "\n\n".join(parts)

    return file_path.read_text(encoding="utf-8", errors="replace")


# --- Request models ---

class UploadV2Hints(BaseModel):
    collection: str = Field(..., min_length=1)
    rights: str = Field(..., min_length=1)
    matiere: str = Field(..., min_length=1)
    niveau: str = Field(..., min_length=1)
    voie: str = Field(default="gen")
    type_doc: str = Field(default="cours")


class UrlsV2Request(BaseModel):
    urls: list[str] = Field(..., min_length=1)
    collection: str = Field(..., min_length=1)
    rights: str = Field(..., min_length=1)
    matiere: str = Field(..., min_length=1)
    niveau: str = Field(..., min_length=1)
    voie: str = Field(default="gen")
    type_doc: str = Field(default="cours")


class DriveV2Request(BaseModel):
    folder_id: str = Field(..., min_length=1)
    collection: str = Field(..., min_length=1)
    rights: str = Field(..., min_length=1)
    matiere: str = Field(..., min_length=1)
    niveau: str = Field(..., min_length=1)
    voie: str = Field(default="gen")
    type_doc: str = Field(default="cours")


# --- Endpoints ---

@router.post("/upload-files")
def ingest_upload_v2(
    request: Request,
    collection: str,
    rights: str,
    matiere: str,
    niveau: str,
    voie: str = "gen",
    type_doc: str = "cours",
    files: list[UploadFile] = File(),  # noqa: B008
) -> dict[str, Any]:
    """Upload files and ingest them through the v2 pipeline.

    All chunks get review_status=needs_review. F-01 guaranteed.
    """
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=400,
            detail=f"too many files: {len(files)} > {MAX_FILES_PER_UPLOAD}",
        )

    token = _enforce_security(request)
    provenance = Provenance(
        route="upload",
        timestamp=time.time(),
        token_hash=token_hash(token),
        source_type="file",
    )

    results: list[dict[str, Any]] = []
    for upload_file in files:
        fname = upload_file.filename or "unknown"
        content = _read_upload_bounded(upload_file, MAX_UPLOAD_FILE_BYTES)
        if len(content) > MAX_UPLOAD_FILE_BYTES:
            results.append({
                "file": fname,
                "error": f"file too large (>{MAX_UPLOAD_FILE_BYTES} bytes)",
            })
            continue

        with tempfile.NamedTemporaryFile(suffix=Path(fname).suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            text = _extract_text_from_file(tmp_path)
            if not text.strip():
                results.append({"file": fname, "error": "empty content"})
                continue
            if len(text) > MAX_EXTRACTED_TEXT_CHARS:
                results.append({
                    "file": fname,
                    "error": f"extracted text too large (>{MAX_EXTRACTED_TEXT_CHARS} chars)",
                })
                continue

            req = IngestV2Request(
                collection=collection,
                source_label=fname,
                source_uri=f"upload://{fname}",
                rights=rights,
                type_doc=type_doc,
                matiere=matiere,
                niveau=niveau,
                voie=voie,
            )
            doc_id = hashlib.sha256(f"{collection}|".encode() + content).hexdigest()
            result = ingest_document(text, req, provenance, doc_id=doc_id)
            _best_effort_track_job(req, dedup_key=doc_id)
            results.append({
                "file": fname,
                "doc_id": result.doc_id,
                "chunks_written": result.chunks_written,
                "chunks_filtered": result.chunks_filtered,
                "chunks_dedup": result.chunks_dedup,
                "review_status": result.review_status,
            })
        except (ValueError, RuntimeError) as exc:
            results.append({"file": fname, "error": str(exc)})
        finally:
            tmp_path.unlink(missing_ok=True)

    return {"route": "upload_v2", "files": len(files), "results": results}


@router.post("/urls")
def ingest_urls_v2(payload: UrlsV2Request, request: Request) -> dict[str, Any]:
    """Ingest content from URLs through the v2 pipeline."""
    if len(payload.urls) > MAX_URLS_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"too many urls: {len(payload.urls)} > {MAX_URLS_PER_REQUEST}",
        )

    token = _enforce_security(request)
    provenance = Provenance(
        route="urls",
        timestamp=time.time(),
        token_hash=token_hash(token),
        source_type="url",
    )

    results: list[dict[str, Any]] = []
    domain_counts: dict[str, int] = {}
    for url in payload.urls:
        domain = urlparse(url).hostname or ""
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        if domain_counts[domain] > MAX_URLS_PER_DOMAIN_PER_REQUEST:
            results.append({
                "url": url,
                "error": (
                    f"too many requests to this domain in this batch "
                    f"(>{MAX_URLS_PER_DOMAIN_PER_REQUEST} for {domain})"
                ),
            })
            continue
        try:
            try:
                resp = safe_fetch(url, max_bytes=MAX_REMOTE_BYTES)
            except ResponseTooLargeError:
                results.append({"url": url, "error": f"too large (>{MAX_REMOTE_BYTES} bytes)"})
                continue
            except SSRFValidationError as exc:
                results.append({"url": url, "error": f"blocked destination: {exc}"})
                continue
            resp.raise_for_status()
            text = resp.text
            if not text.strip():
                results.append({"url": url, "error": "empty content"})
                continue

            # Extract title from HTML if possible
            source_label = url
            if "<title>" in text.lower():
                import re
                m = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
                if m:
                    source_label = m.group(1).strip()[:200]

            # Strip HTML tags for plain text
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(text, "html.parser")
            clean_text = soup.get_text(separator="\n\n")

            req = IngestV2Request(
                collection=payload.collection,
                source_label=source_label,
                source_uri=url,
                rights=payload.rights,
                type_doc=payload.type_doc,
                matiere=payload.matiere,
                niveau=payload.niveau,
                voie=payload.voie,
            )
            doc_id = hashlib.sha256(f"{payload.collection}|{url}".encode()).hexdigest()
            result = ingest_document(clean_text, req, provenance, doc_id=doc_id)
            _best_effort_track_job(req, dedup_key=doc_id)
            results.append({
                "url": url,
                "doc_id": result.doc_id,
                "chunks_written": result.chunks_written,
                "chunks_filtered": result.chunks_filtered,
                "review_status": result.review_status,
            })
        except Exception as exc:
            results.append({"url": url, "error": str(exc)[:200]})

    return {"route": "urls_v2", "urls": len(payload.urls), "results": results}


@router.post("/drive")
def ingest_drive_v2(payload: DriveV2Request, request: Request) -> dict[str, Any]:
    """Ingest files from a Google Drive folder through the v2 pipeline.

    Uses the service account credentials to list and fetch files.
    All chunks get review_status=needs_review.
    """
    _enforce_security(request)

    # Validate collection first (fail fast)
    try:
        from .collection_config import load_collection_config, resolve_collection_v2
    except (ImportError, ValueError):
        from collection_config import (  # type: ignore[no-redef]
            load_collection_config,
            resolve_collection_v2,
        )

    try:
        cfg = load_collection_config()
        resolve_collection_v2(payload.collection, cfg)
    except Exception as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    # Drive v2 ingestion requires the DriveSyncManager + service account credentials
    # available only on the production server. Collection validated above.
    raise HTTPException(
        status_code=501,
        detail=(
            f"Drive v2 ingestion not yet implemented on this instance. "
            f"Collection '{payload.collection}' validated. "
            f"Deploy with Drive credentials to enable."
        ),
    )
