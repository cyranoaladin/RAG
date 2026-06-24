from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class DocumentState(str, Enum):
    discovered = "discovered"
    fetched = "fetched"
    stored_raw = "stored_raw"
    parsed = "parsed"
    normalized = "normalized"
    classified = "classified"
    enriched = "enriched"
    chunked = "chunked"
    embedded_text = "embedded_text"
    embedded_visual = "embedded_visual"
    upserted = "upserted"
    verified = "verified"
    stale = "stale"
    failed = "failed"
    quarantined = "quarantined"


class RunStatus(str, Enum):
    running = "running"
    success = "success"
    failed = "failed"
    partial = "partial"


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    started_at: datetime
    finished_at: datetime | None = None
    status: RunStatus = RunStatus.running
    command: str | None = None
    git_commit: str | None = None
    report_path: str | None = None
    created_by: str | None = None
    notes: str | None = None


class DocumentStateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1)
    state: DocumentState
    run_id: str = Field(min_length=1)
    input_sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    updated_at: datetime


class ErrorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    step: str = Field(min_length=1)
    message: str = Field(min_length=1)
    doc_id: str | None = None
    recoverable: bool = True
    created_at: datetime
