"""Liaison pure des droits #300 aux octets dérivés #312.

Le reçu d'approbation #300 doit d'abord être validé contre GitHub par
``check_pr300_authority``. Cette fonction ne valide ni une review en ligne ni
une autorisation de scope ; elle ne consulte aucun registre de zones PDF.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import yaml

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
LEGAL_NOTICE = "https://eduscol.education.gouv.fr/4656/mentions-legales"
AUTHORITY_ID = "EDUSCOL_ETALAB_2_0_SITEWIDE"
LICENCE_URL = "https://www.data.gouv.fr/pages/legal/licences/etalab-2.0"
RIGHTS_FIELDS = frozenset({"content_sha256", "source_pdf_sha256",
                          "derivative_receipt_sha256", "citation_sha256"})


class DerivativeRightsBridgeError(ValueError):
    """Une liaison de droits est absente, ambiguë ou incompatible."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _compact(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode()


def _pretty(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       indent=2) + "\n").encode()


def _mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DerivativeRightsBridgeError(code)
    return value


def _rows(value: object, code: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
        raise DerivativeRightsBridgeError(code)
    return value


def _unique(rows: Sequence[Mapping[str, Any]], key: str, code: str) -> dict[str, Mapping[str, Any]]:
    values = [row.get(key) for row in rows]
    if any(not isinstance(value, str) or SHA256.fullmatch(value) is None for value in values):
        raise DerivativeRightsBridgeError(code)
    result = dict(zip(values, rows, strict=True))
    if len(result) != len(rows):
        raise DerivativeRightsBridgeError(code)
    return result


def _json(raw: bytes, code: str, *, trailing_newline: bool = True) -> Mapping[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise DerivativeRightsBridgeError(code) from error
    result = _mapping(value, code)
    expected = _compact(result)
    if raw != (expected if trailing_newline else expected.rstrip(b"\n")):
        raise DerivativeRightsBridgeError(code)
    return result


def _attribution(value: object, authority: Mapping[str, Any]) -> Mapping[str, Any]:
    citation = _mapping(value, "DERIVATIVE_ATTRIBUTION_INVALID")
    expected = {"source_uri", "source_label", "source_updated_at",
                "source_date_kind", "licensor", "licence_id", "derivative_notice"}
    if (set(citation) != expected or any(
            not isinstance(citation[key], str) or not citation[key].strip()
            for key in expected)
            or citation["licensor"] != authority["licensor"]
            or citation["licence_id"] != "ETALAB-2.0"
            or citation["source_date_kind"] not in {
                "PDF_EXPLICIT_UPDATE_DATE", "OFFICIAL_RESOURCE_UPDATE_DATE",
                "DATED_OFFICIAL_SNAPSHOT"}
            or citation["source_uri"] != citation["source_uri"].strip()):
        raise DerivativeRightsBridgeError("DERIVATIVE_ATTRIBUTION_INVALID")
    source = urlsplit(citation["source_uri"])
    if (source.scheme != "https" or source.hostname != "eduscol.education.gouv.fr"
            or source.username is not None or source.password is not None):
        raise DerivativeRightsBridgeError("DERIVATIVE_SOURCE_NOT_EDUSCOL")
    try:
        updated = datetime.fromisoformat(citation["source_updated_at"])
    except ValueError as error:
        raise DerivativeRightsBridgeError("DERIVATIVE_ATTRIBUTION_DATE_INVALID") from error
    if updated.tzinfo is None or updated > datetime.now(UTC):
        raise DerivativeRightsBridgeError("DERIVATIVE_ATTRIBUTION_DATE_INVALID")
    if (citation["source_date_kind"] == "DATED_OFFICIAL_SNAPSHOT"
            and f"snapshot du {citation['source_updated_at']}".lower()
            not in citation["derivative_notice"].lower()):
        raise DerivativeRightsBridgeError("DERIVATIVE_SNAPSHOT_NOTICE_MISSING")
    return citation


def _verify_derivative_rights_bindings(
    *,
    approval: Mapping[str, Any],
    authority_raw: bytes,
    decision_sheet_raw: bytes,
    manifest_raw: bytes,
    artifacts: Sequence[Mapping[str, Any]],
    rights_registry: Mapping[str, Any],
    receipt_bytes: Mapping[str, bytes],
    derivative_bytes: Mapping[str, bytes],
    expected_count: int,
) -> int:
    """Vérifie un ensemble exact de dérivés ; taille variable pour les tests.

    ``approval`` est le reçu déjà vérifié par ``check_pr300_authority`` ; son
    contenu seul ne prouve pas qu'une review GitHub existe encore.
    """
    if type(expected_count) is not int or expected_count < 1:
        raise DerivativeRightsBridgeError("DERIVATIVE_POPULATION_INVALID")
    digests = _mapping(approval.get("sha256"), "PR300_APPROVAL_INVALID")
    if (approval.get("kind") != "PR300_DELEGATED_STUDENT_RIGHTS_APPROVAL_V1"
            or approval.get("reviewer") != "abenrhouma"
            or any(digests.get(label) != _sha(raw) for label, raw in (
                ("authority", authority_raw),
                ("decision_sheet", decision_sheet_raw),
                ("candidate_manifest", manifest_raw),
            ))):
        raise DerivativeRightsBridgeError("PR300_APPROVAL_DIGEST_MISMATCH")
    try:
        authority = _mapping(yaml.safe_load(authority_raw), "ETALAB_AUTHORITY_INVALID")
    except yaml.YAMLError as error:
        raise DerivativeRightsBridgeError("ETALAB_AUTHORITY_INVALID") from error
    authority_sha = _sha(authority_raw)
    if (authority.get("authority_kind") != "SITEWIDE_DOWNLOAD_AUTHORITY"
            or authority.get("authority_id") != AUTHORITY_ID
            or authority.get("legal_notice_url") != LEGAL_NOTICE
            or authority.get("licence_id") != "ETALAB-2.0"
            or authority.get("licence_url") != LICENCE_URL
            or authority.get("full_pdf_redistribution_allowed_by_product") is not False
            or authority.get("answer_generation_allowed") is not False
            or "documents proposés en téléchargement sur le site Éduscol"
            not in authority.get("applies_to", [])):
        raise DerivativeRightsBridgeError("ETALAB_AUTHORITY_INVALID")
    manifest = _json(manifest_raw, "PR300_MANIFEST_INVALID")
    manifest_rows = _rows(manifest.get("entries"), "PR300_MANIFEST_INVALID")
    artifact_rows = list(artifacts)
    rights_rows = _rows(rights_registry.get("entries"), "DERIVATIVE_RIGHTS_REGISTRY_INVALID")
    if (manifest.get("status") != "PRE_REVIEW_NOT_PROMOTABLE"
            or manifest.get("rights_authority_sha256") != authority_sha
            or manifest.get("counts", {}).get("public_derivative_artifacts") != expected_count
            or manifest.get("counts", {}).get("original_pdf_public_count") != 0
            or len(manifest_rows) != expected_count
            or len(artifact_rows) != expected_count
            or len(rights_rows) != expected_count):
        raise DerivativeRightsBridgeError("DERIVATIVE_POPULATION_INVALID")
    if (rights_registry.get("kind") != "NEXUS_STUDENT_PUBLIC_DERIVATIVE_RIGHTS_REGISTRY_V1"
            or rights_registry.get("status") != "CANDIDATE_NOT_AUTHORIZED"
            or rights_registry.get("rights_authority_sha256") != authority_sha
            or rights_registry.get("authorized_use") != "student_retrieval_excerpt_only"
            or rights_registry.get("full_pdf_redistribution_allowed") is not False
            or rights_registry.get("answer_generation_allowed") is not False):
        raise DerivativeRightsBridgeError("DERIVATIVE_RIGHTS_REGISTRY_INVALID")
    manifests = _unique(manifest_rows, "derivative_content_sha256", "PR300_MANIFEST_IDENTITY_INVALID")
    artifact_by_sha = _unique(artifact_rows, "content_sha256", "DERIVATIVE_ARTIFACT_IDENTITY_INVALID")
    rights_by_sha = _unique(rights_rows, "content_sha256", "DERIVATIVE_RIGHTS_REGISTRY_INVALID")
    if set(manifests) != set(artifact_by_sha) or set(manifests) != set(rights_by_sha):
        raise DerivativeRightsBridgeError("DERIVATIVE_CONTENT_SET_MISMATCH")
    try:
        reader = csv.DictReader(io.StringIO(decision_sheet_raw.decode("utf-8")), delimiter="\t")
        decisions = _unique(list(reader), "content_sha256", "PR300_DECISION_SHEET_INVALID")
    except UnicodeDecodeError as error:
        raise DerivativeRightsBridgeError("PR300_DECISION_SHEET_INVALID") from error
    if set(receipt_bytes) != {
            row.get("derivative_receipt_sha256") for row in manifest_rows}:
        raise DerivativeRightsBridgeError("DERIVATIVE_RECEIPT_SET_MISMATCH")
    if set(derivative_bytes) != set(manifests):
        raise DerivativeRightsBridgeError("DERIVATIVE_BYTES_SET_MISMATCH")
    seen_sources: set[str] = set()
    for sha, manifest_row in manifests.items():
        artifact = artifact_by_sha[sha]
        rights = rights_by_sha[sha]
        source_sha = manifest_row.get("source_content_sha256")
        receipt_sha = manifest_row.get("derivative_receipt_sha256")
        if (not isinstance(source_sha, str) or SHA256.fullmatch(source_sha) is None
                or source_sha == sha or source_sha in seen_sources
                or not isinstance(receipt_sha, str) or SHA256.fullmatch(receipt_sha) is None):
            raise DerivativeRightsBridgeError("DERIVATIVE_SOURCE_IDENTITY_INVALID")
        seen_sources.add(source_sha)
        decision = decisions.get(source_sha)
        if (decision is None
                or decision.get("source_disposition") != "REPLACE_WITH_NEW_CONTENT"
                or decision.get("derivative_disposition") != "APPROVE_PUBLIC"
                or decision.get("derivative_content_sha256") != sha
                or decision.get("derivative_receipt_sha256") != receipt_sha
                or decision.get("rights_authority_id") != AUTHORITY_ID
                or decision.get("rights_authority_sha256") != authority_sha
                or decision.get("rights_evidence_ref") != LEGAL_NOTICE
                or manifest_row.get("source_disposition") != "REPLACE_WITH_NEW_CONTENT"
                or manifest_row.get("derivative_disposition") != "APPROVE_PUBLIC"
                or manifest_row.get("media_type") != "text/plain; charset=utf-8"
                or manifest_row.get("private_candidate_relpath") != f"candidates/{sha}.txt"):
            raise DerivativeRightsBridgeError("PR300_DECISION_BINDING_INVALID")
        raw = receipt_bytes[receipt_sha]
        receipt = _json(raw, "DERIVATIVE_RECEIPT_INVALID", trailing_newline=False)
        if (_sha(raw) != receipt_sha
                or receipt.get("kind") != "NEXUS-STUDENT-NATIVE-TEXT-DERIVATIVE-V1"
                or receipt.get("status") != "PREPARED_PRIVATE"
                or receipt.get("publication_authorized") is not False
                or receipt.get("rights_authority_sha256") != authority_sha
                or receipt.get("source_content_sha256") != source_sha
                or receipt.get("derivative_content_sha256") != sha
                or receipt.get("candidate_relpath") != f"candidates/{sha}.txt"
                or receipt.get("all_source_pages_inspected") is not True
                or receipt.get("images_copied") is not False
                or receipt.get("graphic_renders_copied") is not False
                or receipt.get("ocr_used") is not False):
            raise DerivativeRightsBridgeError("DERIVATIVE_RECEIPT_BINDING_INVALID")
        content = derivative_bytes[sha]
        if not isinstance(content, bytes) or _sha(content) != sha:
            raise DerivativeRightsBridgeError("DERIVATIVE_CONTENT_SHA_MISMATCH")
        attribution = _attribution(receipt.get("source_attribution"), authority)
        citation = {**attribution, "source_pdf_sha256": source_sha}
        if (manifest_row.get("citation") != attribution
                or artifact.get("citation") != citation
                or artifact.get("artifact_id") != sha
                or artifact.get("source_pdf_sha256") != source_sha
                or artifact.get("source_path") != f"{sha}.txt"
                or artifact.get("source_url") != attribution["source_uri"]
                or artifact.get("media_type") != "text/plain; charset=utf-8"
                or artifact.get("derivative_receipt_sha256") != receipt_sha
                or artifact.get("derivative_receipt_path") != f"derivative_receipts/{receipt_sha}.json"):
            raise DerivativeRightsBridgeError("DERIVATIVE_CITATION_OR_ARTIFACT_MISMATCH")
        if (set(rights) != RIGHTS_FIELDS
                or rights.get("source_pdf_sha256") != source_sha
                or rights.get("derivative_receipt_sha256") != receipt_sha
                or rights.get("citation_sha256") != _sha(_pretty(citation))):
            raise DerivativeRightsBridgeError("DERIVATIVE_RIGHTS_ENTRY_INVALID")
    return expected_count


def verify_derivative_rights_bridge(
    *,
    approval: Mapping[str, Any],
    authority_raw: bytes,
    decision_sheet_raw: bytes,
    manifest_raw: bytes,
    artifacts: Sequence[Mapping[str, Any]],
    rights_registry: Mapping[str, Any],
    receipt_bytes: Mapping[str, bytes],
    derivative_bytes: Mapping[str, bytes],
) -> int:
    """Refuse toute release dont les 253 dérivés ne sont pas liés à #300."""
    return _verify_derivative_rights_bindings(
        approval=approval,
        authority_raw=authority_raw,
        decision_sheet_raw=decision_sheet_raw,
        manifest_raw=manifest_raw,
        artifacts=artifacts,
        rights_registry=rights_registry,
        receipt_bytes=receipt_bytes,
        derivative_bytes=derivative_bytes,
        expected_count=253,
    )
