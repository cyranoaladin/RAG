"""Lier l'autorité temporelle A2 aux pin et plan V1 immuables.

Le binding est un candidat de review. Il ne remplace ni l'observation live du
pin, ni la vérification CAS du plan, ni la revalidation de révocation à C.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from .public_successor_temporal import APPROVED_A2_AUTHORITY_SHA256
from .public_successor_temporal import KIND as A2_KIND

KIND = "NEXUS_STUDENT_PUBLIC_A2_TRANSFER_BINDING_V1"
STATUS = "REVIEW_CANDIDATE_NOT_AUTHORIZED"
PIN_KIND = "NEXUS_STAGING_QUALIFIED_TARGET_PIN_V1"
PLAN_KIND = "NEXUS_STUDENT_PUBLIC_TEXT_TRANSFER_MANIFEST_V1"
FIELDS = frozenset({
    "kind", "status", "a2_sha256", "pin_sha256", "plan_sha256",
    "content_anchor_sha256", "release_id", "inventory_sha256",
    "allowlist_sha256", "target_identity", "pin_expires_at_utc", "counts",
})


class A2TransferBindingError(ValueError):
    """Le triplet temporel/physique/CAS ne concorde pas."""


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _document(raw: bytes, label: str, *, pretty: bool = False) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise A2TransferBindingError(f"{label} invalid JSON") from error
    expected = ((json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
                if pretty else canonical_bytes(value))
    if not isinstance(value, dict) or raw != expected:
        raise A2TransferBindingError(f"{label} not canonical")
    return value


def _utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise A2TransferBindingError("pin expiry UTC missing")
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise A2TransferBindingError("pin expiry invalid") from error
    if stamp.tzinfo != UTC:
        raise A2TransferBindingError("pin expiry non-UTC")
    return stamp


def build_a2_transfer_binding(a2_raw: bytes, pin_raw: bytes, plan_raw: bytes) -> dict[str, Any]:
    """Sceller les trois identités, sans prononcer de verdict de cible live."""
    a2 = _document(a2_raw, "A2", pretty=True)
    pin = _document(pin_raw, "pin")
    plan = _document(plan_raw, "plan")
    return {
        "kind": KIND, "status": STATUS,
        "a2_sha256": _digest(a2_raw), "pin_sha256": _digest(pin_raw),
        "plan_sha256": _digest(plan_raw),
        "content_anchor_sha256": a2.get("content_anchor_sha256"),
        "release_id": a2.get("release_id"),
        "inventory_sha256": plan.get("inventory_sha256"),
        "allowlist_sha256": plan.get("allowlist_sha256"),
        "target_identity": pin.get("target_identity"),
        "pin_expires_at_utc": pin.get("expires_at_utc"),
        "counts": {"collections": 11, "derivatives": plan.get("file_count"),
                   "placements": plan.get("placement_count")},
    }


def verify_a2_transfer_binding(
    binding_raw: bytes, a2_raw: bytes, pin_raw: bytes, plan_raw: bytes, *,
    now_utc: datetime,
) -> dict[str, Any]:
    """Refuser substitution ou expiration ; C doit encore rejouer les preuves."""
    if now_utc.tzinfo != UTC:
        raise A2TransferBindingError("UTC clock required")
    binding = _document(binding_raw, "A2 transfer binding")
    if set(binding) != FIELDS or binding != build_a2_transfer_binding(a2_raw, pin_raw, plan_raw):
        raise A2TransferBindingError("A2, pin or plan binding differs")
    a2 = _document(a2_raw, "A2", pretty=True)
    pin = _document(pin_raw, "pin")
    plan = _document(plan_raw, "plan")
    if (_digest(a2_raw) != APPROVED_A2_AUTHORITY_SHA256
            or a2.get("kind") != A2_KIND
            or a2.get("status") != "TEMPORAL_AUTHORITY_ONLY_NOT_ACTIVABLE"
            or a2.get("activation_allowed") is not False
            or a2.get("c_time_source_revalidation_required") is not True
            or pin.get("kind") != PIN_KIND
            or pin.get("content_anchor_sha256") != a2.get("content_anchor_sha256")
            or pin.get("release_id") != a2.get("release_id")
            or plan.get("kind") != PLAN_KIND
            or plan.get("status") != "PLANNED_NOT_TRANSFERRED"
            or plan.get("release_id") != a2.get("release_id")
            or plan.get("file_count") != 253
            or plan.get("derivative_receipt_count") != 253
            or plan.get("placement_count") != 377
            or a2.get("expected_counts") != {
                "subjects": 11, "unique_artifacts": 253, "placements": 377,
                "unique_chunks": 3975,
            }):
        raise A2TransferBindingError("A2, pin or plan scope differs")
    pinned = _utc(pin.get("pinned_at_utc"))
    expires = _utc(pin.get("expires_at_utc"))
    if not pinned <= now_utc < expires or expires - pinned > timedelta(hours=24):
        raise A2TransferBindingError("pin outside short validity window")
    a2_expires = _utc(a2.get("valid_until_utc"))
    if a2_expires - now_utc < timedelta(hours=24):
        raise A2TransferBindingError("A2 residual validity insufficient")
    return binding
