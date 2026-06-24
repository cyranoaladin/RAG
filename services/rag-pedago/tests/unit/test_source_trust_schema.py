from __future__ import annotations

from datetime import UTC, datetime

from schema.document import SourceType
from schema.source import SourceAuthorityLevel, SourceTrust, VerificationStatus


def test_official_verified_source_trust_allows_retrieval() -> None:
    trust = SourceTrust.model_validate(
        {
            "source_type": SourceType.eduscol,
            "authority_level": SourceAuthorityLevel.official_verified,
            "last_verified_at": datetime(2026, 6, 13, tzinfo=UTC),
            "verification_status": VerificationStatus.verified,
            "official_url": "https://eduscol.education.fr/",
            "retrieval_allowed": True,
            "notes": "Programme officiel verifie.",
        }
    )

    assert trust.retrieval_allowed is True


def test_generated_draft_source_trust_defaults_to_not_allowed() -> None:
    trust = SourceTrust.model_validate(
        {
            "source_type": SourceType.generated,
            "authority_level": SourceAuthorityLevel.generated_draft,
            "verification_status": VerificationStatus.draft,
        }
    )

    assert trust.retrieval_allowed is False

