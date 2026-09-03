"""Propagation de l'admission après revue dans la chaîne d'enforcement (ADR-0047).

Trois points décident, en aval du registre de preuves, du sort d'un contenu
détecté puis admis par un humain autorisé :

`enforce_pii`
    le point de contrôle de scope, qui refusait toute détection sans nuance ;
`build_quality_report_core`
    qui inscrivait `pii_detected` comme motif de rejet ;
`decide_routing_core`
    qui envoyait en QUARANTINE tout rapport portant `pii_detected`.

Aucun des trois ne s'ouvre sur le seul booléen de détection : chacun exige le
fait **séparé** « cette détection a été examinée et admise », que seul le
registre scellé peut produire. Et aucun n'efface la détection au passage : un
document admis reste un document où l'on a trouvé quelque chose.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from nexus_contracts.document import Rights
from nexus_contracts.ingestion import ArtifactRecord, CollectionProfile

from ingestor.ingestion_agents.classifier import ConformityResult
from ingestor.ingestion_agents.quality_agent import (
    build_quality_report_core,
    decide_routing_core,
)
from ingestor.ingestion_control.scope_enforcement import (
    ScopeEnforcementViolation,
    enforce_pii,
)

SCOPE = {
    "tenant": "libre_terminale",
    "collection": "rag_nexus_nsi_terminale_specialite",
    "niveau": "terminale",
    "voie": "generale",
    "matiere": "nsi",
    "candidat": "libre",
    "audience": ["libre", "tous"],
    "visibility": "internal",
    "school_year": "2026-2027",
    "programme_version": "BOEN_special_8_2019-07-25",
}

CONFORMITY_OK = ConformityResult(
    niveau_conformity=True,
    voie_conformity=True,
    matiere_conformity=True,
    programme_conformity=True,
    matiere_evidence=("algorithmique", "récursivité"),
)


def _profile() -> CollectionProfile:
    return CollectionProfile.model_validate(
        {
            "profile_version": "v1",
            "enabled": True,
            "scope": SCOPE,
            "title": "NSI Terminale Spécialité",
            "owner": "equipe-nsi",
            "expected_topics": ["algorithmique", "récursivité"],
            "expected_resource_types": ["cours"],
            "allowed_domains": ["eduscol.education.fr"],
            "source_authority": "official",
            "search_cadence": "weekly",
            "max_queries_per_run": 10,
            "max_documents_per_run": 20,
            "max_chunk_size": 800,
            "chunk_overlap": 100,
            "min_source_confidence": 0.7,
            "min_scope_confidence": 0.7,
            "min_extraction_quality": 0.1,
        }
    )


def _artifact() -> ArtifactRecord:
    return ArtifactRecord.model_validate(
        {
            "artifact_id": uuid4(),
            "resource_id": uuid4(),
            "run_id": uuid4(),
            "scope": SCOPE,
            "sha256": "a" * 64,
            "size_bytes": 100,
            "mime_declared": "application/pdf",
            "mime_detected": "application/pdf",
            "original_url": "https://eduscol.education.fr/nsi/algo",
            "final_url": "https://eduscol.education.fr/nsi/algo",
            "collected_at": datetime(2026, 9, 3, tzinfo=UTC),
            "domain": "eduscol.education.fr",
            "rights_status": "officiel_public",
            "title": "Algorithmique",
            "publisher": "Eduscol",
            "license": "CC-BY-SA",
        }
    )


class _Authorization:
    """Une autorisation minimale : seuls les deux champs lus ici comptent."""

    authorization_id = "scope-test-authorization"
    pii_absence_attested = True


class TestEnforcePii:
    def test_no_detection_passes(self) -> None:
        enforce_pii(_Authorization(), pii_detected=False, reviewed_accepted=False)

    def test_detection_without_review_is_refused(self) -> None:
        with pytest.raises(ScopeEnforcementViolation) as excinfo:
            enforce_pii(_Authorization(), pii_detected=True, reviewed_accepted=False)
        assert excinfo.value.checkpoint == "pii"

    def test_detection_admitted_by_review_passes(self) -> None:
        enforce_pii(_Authorization(), pii_detected=True, reviewed_accepted=True)

    def test_review_flag_defaults_to_closed(self) -> None:
        """Un appelant qui omet le paramètre retombe sur le refus, pas sur
        l'admission — le défaut d'un garde-fou se choisit du côté fermé."""
        with pytest.raises(ScopeEnforcementViolation):
            enforce_pii(_Authorization(), pii_detected=True)


class TestQualityReportAndRouting:
    def _report(self, *, reviewed: bool):
        return build_quality_report_core(
            artifact=_artifact(),
            profile=_profile(),
            conformity=CONFORMITY_OK,
            rights=Rights.officiel_public,
            extracted_text="algorithmique et récursivité sont au programme. " * 20,
            declared_language="fr",
            pii_detected=True,
            duplicate_detected=False,
            report_id=uuid4(),
            evaluated_at=datetime(2026, 9, 3, tzinfo=UTC),
            pii_reviewed_accepted=reviewed,
        )

    def _route(self, report):
        return decide_routing_core(
            quality_report=report,
            profile=_profile(),
            decision_id=uuid4(),
            decided_at=datetime(2026, 9, 3, tzinfo=UTC),
        )

    def test_detection_without_review_is_a_rejection_reason(self) -> None:
        assert "pii_detected" in self._report(reviewed=False).rejection_reasons

    def test_admitted_detection_is_not_a_rejection_reason(self) -> None:
        assert "pii_detected" not in self._report(reviewed=True).rejection_reasons

    def test_admitted_detection_keeps_the_fact_on_the_report(self) -> None:
        """Le rapport porte toujours la détection, admise ou non."""
        assert self._report(reviewed=True).pii_detected is True

    def test_detection_without_review_routes_to_quarantine(self) -> None:
        decision = self._route(self._report(reviewed=False))
        assert decision.decision == "QUARANTINE"
        assert decision.rules_applied == ["pii_detected"]

    def test_admitted_detection_is_not_quarantined(self) -> None:
        assert self._route(self._report(reviewed=True)).decision != "QUARANTINE"

    def test_admitted_detection_with_no_other_defect_is_routed(self) -> None:
        assert self._route(self._report(reviewed=True)).decision == "ROUTE"
