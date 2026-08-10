"""Tests H2-F pour publication_evidence.py — Défaut 6: Attribution durable."""
from dataclasses import fields

import pytest

from ingestor.ingestion_control.publication_evidence import PublicationFacts


class TestH2FDefaut6AttributionDurable:
    """H2-F Défaut 6: PublicationFacts doit inclure les attributs d'attribution durables."""

    def test_publication_facts_has_source_label_field(self) -> None:
        """PublicationFacts must have source_label field."""
        field_names = {f.name for f in fields(PublicationFacts)}
        assert "source_label" in field_names

    def test_publication_facts_has_official_field(self) -> None:
        """PublicationFacts must have official field."""
        field_names = {f.name for f in fields(PublicationFacts)}
        assert "official" in field_names

    def test_publication_facts_has_source_kind_field(self) -> None:
        """PublicationFacts must have source_kind field."""
        field_names = {f.name for f in fields(PublicationFacts)}
        assert "source_kind" in field_names

    def test_publication_facts_has_type_doc_field(self) -> None:
        """PublicationFacts must have type_doc field."""
        field_names = {f.name for f in fields(PublicationFacts)}
        assert "type_doc" in field_names

    def test_all_h2f_attribution_fields_are_required(self) -> None:
        """All H2-F attribution fields must be present (no Optional)."""
        required_fields = {"source_label", "official", "source_kind", "type_doc"}
        field_info = {f.name: f for f in fields(PublicationFacts)}

        for field_name in required_fields:
            assert field_name in field_info, f"{field_name} must be a field"
            # The field type should NOT be Optional (no None default)
            field = field_info[field_name]
            assert field.default is field.default_factory, \
                f"{field_name} must not have a default value"
