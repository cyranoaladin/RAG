from __future__ import annotations

import pytest
from pydantic import ValidationError

from nexus_contracts import Citation


def _legacy_citation() -> dict[str, object]:
    return {
        "source_label": "Programme NSI",
        "page": 3,
        "source_uri": "https://eduscol.education.gouv.fr/document.pdf",
        "rights": "officiel_public",
    }


def test_legacy_citation_serializes_without_new_fields() -> None:
    assert Citation.model_validate(_legacy_citation()).model_dump() == _legacy_citation()


def test_explicit_null_attribution_is_accepted_as_absent() -> None:
    payload = {**_legacy_citation(), "licensor": None}
    assert Citation.model_validate(payload).model_dump() == _legacy_citation()


def test_serialization_schema_describes_citation_fields() -> None:
    schema = Citation.model_json_schema(mode="serialization")
    definition = schema.get("$defs", {}).get("SerializedCitation", schema)
    assert definition.get("additionalProperties") is False
    assert set(_legacy_citation()) <= set(definition["properties"])
    assert {"licensor", "licence_id", "source_updated_at", "derivative_notice"} <= set(
        definition["properties"]
    )


def test_public_text_derivative_citation_carries_attribution() -> None:
    payload = {
        **_legacy_citation(),
        "licensor": "Ministère de l’Éducation nationale – Dgesco / Éduscol",
        "licence_id": "ETALAB-2.0",
        "source_updated_at": "2026-09-12",
        "derivative_notice": "Extrait textuel dérivé ; PDF original non redistribué.",
    }
    assert Citation.model_validate(payload).model_dump() == payload


def test_public_derivative_preserves_source_timestamp_from_sealed_receipt() -> None:
    payload = {
        **_legacy_citation(),
        "licensor": "Ministère de l’Éducation nationale – Dgesco / Éduscol",
        "licence_id": "ETALAB-2.0",
        "source_updated_at": "2026-10-10T06:04:23.168Z",
        "derivative_notice": "Extrait textuel dérivé.",
    }
    assert Citation.model_validate(payload).source_updated_at == payload["source_updated_at"]


@pytest.mark.parametrize("source_updated_at", ["2026-02-30", "2025-02-29", "2026-13-01", "2026-10-10T25:04:23Z"])
def test_impossible_source_date_is_rejected(source_updated_at: str) -> None:
    with pytest.raises(ValidationError, match="source_updated_at"):
        Citation.model_validate({
            **_legacy_citation(),
            "licensor": "Ministère de l’Éducation nationale – Dgesco / Éduscol",
            "licence_id": "ETALAB-2.0",
            "source_updated_at": source_updated_at,
            "derivative_notice": "Extrait textuel dérivé.",
        })


def test_partial_public_derivative_attribution_is_rejected() -> None:
    with pytest.raises(ValidationError, match="public derivative attribution"):
        Citation.model_validate({**_legacy_citation(), "licence_id": "ETALAB-2.0"})


def test_public_derivative_attribution_requires_source_page() -> None:
    with pytest.raises(ValidationError, match="public derivative attribution requires page"):
        Citation.model_validate({
            **_legacy_citation(),
            "page": None,
            "licensor": "Ministère de l’Éducation nationale – Dgesco / Éduscol",
            "licence_id": "ETALAB-2.0",
            "source_updated_at": "2026-10-10T06:04:23.168Z",
            "derivative_notice": "Extrait textuel dérivé.",
        })
