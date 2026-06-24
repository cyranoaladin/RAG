from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

RUN_STATUSES = ("running", "success", "failed", "partial")

DOCUMENT_STATES = (
    "discovered",
    "fetched",
    "stored_raw",
    "parsed",
    "normalized",
    "classified",
    "enriched",
    "chunked",
    "embedded_text",
    "embedded_visual",
    "upserted",
    "verified",
    "stale",
    "failed",
    "quarantined",
)

@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    apply: Callable[[sqlite3.Connection], None]


class ReviewPackageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_id: str = Field(min_length=1)
    batch_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    gate_status: str = Field(min_length=1)
    readiness_status: str = Field(min_length=1)
    coverage_status: str = Field(min_length=1)
    review_package_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    gate_json_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    readiness_json_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    coverage_json_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    official_reference_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    manifests_sha256_json: str
    taxonomy_sha256_json: str
    package_json_path: str | None = None
    package_markdown_path: str | None = None
    created_at: datetime
    metadata_json: str


class ReviewDecisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=1)
    package_id: str = Field(min_length=1)
    batch_id: str = Field(min_length=1)
    decision: str = Field(pattern=r"^(approved|rejected)$")
    reviewer: str = Field(min_length=1)
    reviewed_at: datetime
    review_package_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    gate_json_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    notes: str | None = None
    decision_json_path: str | None = None
    metadata_json: str


class ControlledImportAttemptRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str = Field(min_length=1)
    batch_id: str = Field(min_length=1)
    status: str = Field(pattern=r"^(imported|blocked_by_gate|failed)$")
    gate_status: str = Field(min_length=1)
    review_required: bool
    review_id: str | None = None
    package_id: str | None = None
    documents_valid: int = Field(ge=0)
    documents_invalid: int = Field(ge=0)
    documents_not_retrievable: int = Field(ge=0)
    run_ids_json: str
    reasons_json: str
    report_markdown_path: str | None = None
    report_json_path: str | None = None
    created_at: datetime
    metadata_json: str


class ControlledImportVerificationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str = Field(min_length=1)
    check_name: str = Field(min_length=1)
    passed: bool
    message: str | None = None
    created_at: datetime
