from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from rag_pedago.reference.loader import load_official_reference_index
from rag_pedago.reference.resolver import CompatibilityExplanation, OfficialReferenceResolver

if TYPE_CHECKING:
    from rag_pedago.imports.manifest import DirectoryImportReport


class Severity(str, Enum):
    info = "info"
    warning = "warning"
    error = "error"
    critical = "critical"


class QualityIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    severity: Severity
    message: str = Field(min_length=1)
    doc_id: str | None = None
    manifest_path: str | None = None
    field: str | None = None
    compatibility_explanation: CompatibilityExplanation | None = None


class QualityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_on_invalid_lines: bool = True
    block_on_duplicate_doc_id_payload_conflict: bool = True
    block_on_duplicate_source_uri: bool = True
    block_on_duplicate_sha256: bool = False
    block_on_unknown_rights: bool = False
    require_programme_version_for_pedagogical_docs: bool = True
    require_niveau_for_pedagogical_docs: bool = True
    require_epreuve_for_exam_docs: bool = True
    require_official_refs_for_official_docs: bool = True
    require_official_refs_for_exam_docs: bool = True
    require_verified_claim_for_regulatory_docs: bool = True
    block_on_unknown_official_refs: bool = True
    block_on_pending_only_regulatory_claims: bool = True
    block_on_deprecated_candidate_status_ref: bool = False
    warn_on_deprecated_candidate_status_ref: bool = True


class QualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    issues: list[QualityIssue]
    blocking_issue_count: int
    warning_count: int
    info_count: int


PEDAGOGICAL_DOC_TYPES = {
    "programme_officiel",
    "ressource_officielle",
    "cours",
    "fiche_synthese",
    "fiche_methode",
    "td",
    "tp",
    "exercice",
    "exercice_corrige",
    "devoir",
    "devoir_corrige",
    "evaluation",
    "evaluation_corrigee",
    "annale",
    "sujet_zero",
    "corrige",
    "bareme",
}

EXAM_DOC_TYPES = {
    "annale",
    "sujet_zero",
    "corrige",
    "bareme",
    "bac_blanc",
    "brevet_blanc",
    "grille_evaluation",
    "grille_grand_oral",
}

OFFICIAL_DOC_TYPES = {
    "programme_officiel",
    "ressource_officielle",
}

REGULATORY_DOC_TYPES = {
    "programme_officiel",
    "ressource_officielle",
    "bareme",
    "grille_evaluation",
    "grille_grand_oral",
}


def _severity(blocks: bool) -> Severity:
    return Severity.error if blocks else Severity.warning


def _status(issues: list[QualityIssue]) -> str:
    if any(issue.severity in {Severity.error, Severity.critical} for issue in issues):
        return "quality_blocked"
    if any(issue.severity is Severity.warning for issue in issues):
        return "quality_warn"
    return "quality_pass"


def _issue_counts(issues: list[QualityIssue]) -> tuple[int, int, int]:
    blocking = sum(1 for issue in issues if issue.severity in {Severity.error, Severity.critical})
    warnings = sum(1 for issue in issues if issue.severity is Severity.warning)
    infos = sum(1 for issue in issues if issue.severity is Severity.info)
    return blocking, warnings, infos


def strict_quality_policy(*, allow_unknown_rights: bool = False) -> QualityPolicy:
    return QualityPolicy(
        block_on_unknown_rights=not allow_unknown_rights,
        block_on_deprecated_candidate_status_ref=True,
        block_on_pending_only_regulatory_claims=True,
        require_official_refs_for_exam_docs=True,
        require_official_refs_for_official_docs=True,
        require_verified_claim_for_regulatory_docs=True,
    )


def _unknown_ref_severity(policy: QualityPolicy) -> Severity:
    return _severity(policy.block_on_unknown_official_refs)


def _pending_severity(policy: QualityPolicy) -> Severity:
    return _severity(policy.block_on_pending_only_regulatory_claims)


def _add_missing(
    issues: list[QualityIssue],
    *,
    code: str,
    doc_id: str,
    field: str,
    message: str,
) -> None:
    issues.append(
        QualityIssue(
            code=code,
            severity=Severity.error,
            message=message,
            doc_id=doc_id,
            field=field,
        )
    )


def _evaluate_official_refs(issues: list[QualityIssue], meta, policy: QualityPolicy) -> None:
    index = load_official_reference_index(Path("data/reference"))
    resolver = OfficialReferenceResolver(index)
    doc_id = meta.doc_id
    type_doc = meta.type_doc.value

    if meta.official_level_ref:
        if not index.has_level(meta.official_level_ref):
            issues.append(
                QualityIssue(
                    code="unknown_official_level_ref",
                    severity=_unknown_ref_severity(policy),
                    message=f"unknown official_level_ref: {meta.official_level_ref}",
                    doc_id=doc_id,
                    field="official_level_ref",
                )
            )
    elif type_doc in OFFICIAL_DOC_TYPES and policy.require_official_refs_for_official_docs:
        _add_missing(
            issues,
            code="missing_official_level_ref",
            doc_id=doc_id,
            field="official_level_ref",
            message="official document is missing official_level_ref",
        )

    if meta.official_subject_ref:
        subject = index.subjects.get(meta.official_subject_ref)
        if subject is None:
            issues.append(
                QualityIssue(
                    code="unknown_official_subject_ref",
                    severity=_unknown_ref_severity(policy),
                    message=f"unknown official_subject_ref: {meta.official_subject_ref}",
                    doc_id=doc_id,
                    field="official_subject_ref",
                )
            )
        elif meta.official_level_ref and subject.level_id != meta.official_level_ref:
            allowed = set(subject.allowed_level_ids)
            if meta.official_level_ref not in allowed:
                issues.append(
                    QualityIssue(
                        code="official_subject_level_mismatch",
                        severity=Severity.error,
                        message="official_subject_ref level does not match official_level_ref",
                        doc_id=doc_id,
                        field="official_subject_ref",
                    )
                )
    elif type_doc in OFFICIAL_DOC_TYPES and meta.matiere and policy.require_official_refs_for_official_docs:
        _add_missing(
            issues,
            code="missing_official_subject_ref",
            doc_id=doc_id,
            field="official_subject_ref",
            message="official document is missing official_subject_ref",
        )

    if meta.official_exam_ref:
        exam = index.exams.get(meta.official_exam_ref)
        if exam is None:
            issues.append(
                QualityIssue(
                    code="unknown_official_exam_ref",
                    severity=_unknown_ref_severity(policy),
                    message=f"unknown official_exam_ref: {meta.official_exam_ref}",
                    doc_id=doc_id,
                    field="official_exam_ref",
                )
            )
        elif meta.official_level_ref and exam.level_id != meta.official_level_ref:
            issues.append(
                QualityIssue(
                    code="official_exam_level_mismatch",
                    severity=Severity.error,
                    message="official_exam_ref level does not match official_level_ref",
                    doc_id=doc_id,
                    field="official_exam_ref",
                )
            )
    elif type_doc in EXAM_DOC_TYPES and policy.require_official_refs_for_exam_docs:
        _add_missing(
            issues,
            code="missing_official_exam_ref",
            doc_id=doc_id,
            field="official_exam_ref",
            message="exam document is missing official_exam_ref",
        )

    if meta.candidate_status_ref:
        status = index.candidate_statuses.get(meta.candidate_status_ref)
        if status is None:
            issues.append(
                QualityIssue(
                    code="unknown_candidate_status_ref",
                    severity=_unknown_ref_severity(policy),
                    message=f"unknown candidate_status_ref: {meta.candidate_status_ref}",
                    doc_id=doc_id,
                    field="candidate_status_ref",
                )
            )
        elif status.deprecated and policy.warn_on_deprecated_candidate_status_ref:
            issues.append(
                QualityIssue(
                    code="deprecated_candidate_status_ref",
                    severity=_severity(policy.block_on_deprecated_candidate_status_ref),
                    message=f"deprecated candidate_status_ref: {meta.candidate_status_ref}",
                    doc_id=doc_id,
                    field="candidate_status_ref",
                )
            )
    elif type_doc in EXAM_DOC_TYPES and policy.require_official_refs_for_exam_docs:
        _add_missing(
            issues,
            code="missing_candidate_status_ref",
            doc_id=doc_id,
            field="candidate_status_ref",
            message="exam document is missing candidate_status_ref",
        )

    if meta.establishment_context_ref and meta.establishment_context_ref not in index.establishment_contexts:
        issues.append(
            QualityIssue(
                code="unknown_establishment_context_ref",
                severity=_unknown_ref_severity(policy),
                message=f"unknown establishment_context_ref: {meta.establishment_context_ref}",
                doc_id=doc_id,
                field="establishment_context_ref",
            )
        )

    for source_id in meta.official_source_refs:
        source = index.sources.get(source_id)
        if source is None:
            issues.append(
                QualityIssue(
                    code="unknown_official_source_ref",
                    severity=_unknown_ref_severity(policy),
                    message=f"unknown official_source_ref: {source_id}",
                    doc_id=doc_id,
                    field="official_source_refs",
                )
            )
            continue
        if source.verification_status == "pending":
            issues.append(
                QualityIssue(
                    code="pending_official_source",
                    severity=_pending_severity(policy),
                    message=f"pending official source: {source_id}",
                    doc_id=doc_id,
                    field="official_source_refs",
                )
            )
        explanation = resolver.explain_source_compatibility(source_id, meta)
        if resolver.refs_for_document(meta) and not explanation.compatible:
            issues.append(
                QualityIssue(
                    code="official_source_applies_to_mismatch",
                    severity=Severity.error,
                    message=(
                        f"Source {source_id} does not apply to refs "
                        f"{set(explanation.document_refs)}"
                    ),
                    doc_id=doc_id,
                    field="official_source_refs",
                    compatibility_explanation=explanation,
                )
            )

    for claim_id in meta.official_claim_refs:
        claim = index.claims.get(claim_id)
        if claim is None:
            issues.append(
                QualityIssue(
                    code="unknown_official_claim_ref",
                    severity=_unknown_ref_severity(policy),
                    message=f"unknown official_claim_ref: {claim_id}",
                    doc_id=doc_id,
                    field="official_claim_refs",
                )
            )
            continue
        if claim.verification_status == "pending":
            issues.append(
                QualityIssue(
                    code="pending_official_claim",
                    severity=_pending_severity(policy),
                    message=f"pending official claim: {claim_id}",
                    doc_id=doc_id,
                    field="official_claim_refs",
                )
            )
        elif claim.verification_status != "verified":
            issues.append(
                QualityIssue(
                    code="official_claim_not_verified",
                    severity=_pending_severity(policy),
                    message=f"official claim is not verified: {claim_id}",
                    doc_id=doc_id,
                    field="official_claim_refs",
                )
            )
        explanation = resolver.explain_claim_compatibility(claim_id, meta)
        if resolver.refs_for_document(meta) and not explanation.compatible:
            issues.append(
                QualityIssue(
                    code="official_claim_applies_to_mismatch",
                    severity=Severity.error,
                    message=(
                        f"Claim {claim_id} does not apply to refs "
                        f"{set(explanation.document_refs)}"
                    ),
                    doc_id=doc_id,
                    field="official_claim_refs",
                    compatibility_explanation=explanation,
                )
            )

    if type_doc in OFFICIAL_DOC_TYPES and policy.require_official_refs_for_official_docs:
        has_verified_source = any(index.source_is_verified(source_id) for source_id in meta.official_source_refs)
        has_verified_claim = any(index.claim_is_verified(claim_id) for claim_id in meta.official_claim_refs)
        if not has_verified_source and not has_verified_claim:
            issues.append(
                QualityIssue(
                    code="official_doc_without_verified_source",
                    severity=Severity.error,
                    message="official document has no verified official source or claim",
                    doc_id=doc_id,
                    field="official_source_refs",
                )
            )

    if (
        type_doc in REGULATORY_DOC_TYPES
        and policy.require_verified_claim_for_regulatory_docs
        and not meta.official_claim_refs
    ):
        issues.append(
            QualityIssue(
                code="missing_official_claim_ref",
                severity=Severity.error,
                message="regulatory document is missing official_claim_refs",
                doc_id=doc_id,
                field="official_claim_refs",
            )
        )


def evaluate_manifest_directory_quality(
    directory_report: DirectoryImportReport,
    policy: QualityPolicy,
) -> QualityReport:
    issues: list[QualityIssue] = []

    if directory_report.documents_invalid:
        issues.append(
            QualityIssue(
                code="invalid_lines",
                severity=_severity(policy.block_on_invalid_lines),
                message=f"{directory_report.documents_invalid} invalid manifest line(s)",
            )
        )

    for doc_id in directory_report.duplicate_doc_id_exact:
        issues.append(
            QualityIssue(
                code="duplicate_doc_id_exact",
                severity=Severity.warning,
                message="same doc_id appears multiple times with identical payload",
                doc_id=doc_id,
                field="doc_id",
            )
        )

    for doc_id in directory_report.duplicate_doc_id_conflicts:
        issues.append(
            QualityIssue(
                code="duplicate_doc_id_conflict",
                severity=_severity(policy.block_on_duplicate_doc_id_payload_conflict),
                message="same doc_id appears with different payload or hash",
                doc_id=doc_id,
                field="doc_id",
            )
        )

    for source_uri in directory_report.duplicate_source_uris:
        issues.append(
            QualityIssue(
                code="duplicate_source_uri",
                severity=_severity(policy.block_on_duplicate_source_uri),
                message=f"same source_uri is attached to multiple doc_ids: {source_uri}",
                field="source_uri",
            )
        )

    for sha256 in directory_report.duplicate_sha256:
        issues.append(
            QualityIssue(
                code="duplicate_sha256",
                severity=_severity(policy.block_on_duplicate_sha256),
                message=f"same sha256 is attached to multiple doc_ids: {sha256}",
                field="sha256",
            )
        )

    for meta in directory_report.valid_metas:
        if meta.rights.value == "unknown":
            issues.append(
                QualityIssue(
                    code="unknown_rights",
                    severity=_severity(policy.block_on_unknown_rights),
                    message="document rights are unknown",
                    doc_id=meta.doc_id,
                    field="rights",
                )
            )

        if meta.type_doc.value in PEDAGOGICAL_DOC_TYPES:
            if policy.require_programme_version_for_pedagogical_docs and not meta.programme_version:
                issues.append(
                    QualityIssue(
                        code="missing_programme_version",
                        severity=Severity.error,
                        message="pedagogical document is missing programme_version",
                        doc_id=meta.doc_id,
                        field="programme_version",
                    )
                )
            if policy.require_niveau_for_pedagogical_docs and meta.niveau is None:
                issues.append(
                    QualityIssue(
                        code="missing_niveau",
                        severity=Severity.error,
                        message="pedagogical document is missing niveau",
                        doc_id=meta.doc_id,
                        field="niveau",
                    )
                )

        if (
            policy.require_epreuve_for_exam_docs
            and meta.type_doc.value in EXAM_DOC_TYPES
            and meta.epreuve.value == "aucune"
        ):
            issues.append(
                QualityIssue(
                    code="missing_epreuve",
                    severity=Severity.error,
                    message="exam document is missing epreuve",
                    doc_id=meta.doc_id,
                    field="epreuve",
                )
            )

        _evaluate_official_refs(issues, meta, policy)

    blocking, warnings, infos = _issue_counts(issues)
    return QualityReport(
        status=_status(issues),
        issues=issues,
        blocking_issue_count=blocking,
        warning_count=warnings,
        info_count=infos,
    )
