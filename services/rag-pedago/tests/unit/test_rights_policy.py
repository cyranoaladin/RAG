from __future__ import annotations

from datetime import datetime, timezone

from schema.document import AccessContext, DocumentMeta, Rights, SourceType, TypeDoc


def document_with_rights(rights: Rights) -> DocumentMeta:
    return DocumentMeta.model_validate(
        {
            "doc_id": f"doc-{rights.value}",
            "source_uri": "file:///data/raw/test.md",
            "source_type": SourceType.nexus,
            "sha256": "c" * 64,
            "discovered_at": datetime(2026, 6, 13, tzinfo=timezone.utc),
            "rights": rights,
            "visibility": "internal",
            "matiere": "mathematiques",
            "type_doc": TypeDoc.cours,
        }
    )


def test_unknown_rights_are_not_retrievable() -> None:
    meta = document_with_rights(Rights.unknown)

    assert meta.is_retrievable is False
    assert meta.allowed_contexts == []


def test_commercial_confidential_is_not_exposable_to_parent() -> None:
    meta = document_with_rights(Rights.commercial_confidential)

    assert meta.is_allowed_in_context(AccessContext.parent) is False
    assert AccessContext.admin in meta.allowed_contexts


def test_student_private_is_only_available_to_owner_or_admin() -> None:
    meta = document_with_rights(Rights.student_private)

    assert meta.is_allowed_in_context(AccessContext.owner_student) is True
    assert meta.is_allowed_in_context(AccessContext.enrolled_student) is False
    assert meta.is_allowed_in_context(AccessContext.parent) is False

