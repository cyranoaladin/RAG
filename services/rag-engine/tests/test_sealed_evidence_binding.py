"""Le worker ne décide plus des droits ni de la PII sans preuve.

Deux faits étaient inventés : ``pii_detected = False``, écrit en dur, et
``artifact.license``, venu du payload du job — donc de l'opérateur qui
soumet la ressource.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from nexus_contracts.document import Rights

from ingestor.ingestion_control.sealed_evidence import (
    SealedEvidenceError,
    VerifiedPIIEvidenceRegistry,
    VerifiedRightsEvidenceRegistry,
)

MANIFEST = "d" * 64
SHA_A = "a" * 64
SHA_B = "b" * 64


def write_pii(tmp_path: Path, **overrides) -> tuple[Path, str]:
    document = {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "corpus_manifest_sha256": MANIFEST,
        "remote_access_mode": "READ_ONLY",
        "remote_write_operations": 0,
        "raw_pii_in_output": False,
        "raw_pii_in_logs": False,
        "policy_sha256": "e" * 64,
        "results": [
            {"content_sha256": SHA_A, "status": "CLEARED", "pii_detected": False,
             "pages_scanned": 60, "characters_scanned": 178559},
            {"content_sha256": SHA_B, "status": "QUARANTINED_PII",
             "pii_detected": True, "pages_scanned": 3, "characters_scanned": 900},
        ],
    }
    document.update(overrides)
    path = tmp_path / "pii.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def load_pii(tmp_path: Path, **overrides) -> VerifiedPIIEvidenceRegistry:
    path, digest = write_pii(tmp_path, **overrides)
    return VerifiedPIIEvidenceRegistry.load(
        path,
        expected_evidence_sha256=digest,
        expected_corpus_manifest_sha256=MANIFEST,
    )


def write_rights(tmp_path: Path, **overrides) -> tuple[Path, str]:
    document = {
        "registry_id": "test_registry",
        "human_rights_decisions": {
            "eduscol": {
                "scope_manifest_sha256": MANIFEST,
                "scope_zone": "01_EDUSCOL_OFFICIEL/",
                "approved_for_production_rag": True,
            }
        },
        "source_evidence": {
            "eduscol": {
                "zone": "01_EDUSCOL_OFFICIEL/",
                "recommended_rights_category": "officiel_public",
            }
        },
    }
    document.update(overrides)
    path = tmp_path / "rights.yml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def load_rights(tmp_path: Path, **overrides) -> VerifiedRightsEvidenceRegistry:
    path, digest = write_rights(tmp_path, **overrides)
    return VerifiedRightsEvidenceRegistry.load(
        path,
        expected_registry_sha256=digest,
        expected_corpus_manifest_sha256=MANIFEST,
    )


class TestPIIIsProvenNotAssumed:
    def test_a_cleared_content_yields_a_clearance(self, tmp_path: Path) -> None:
        clearance = load_pii(tmp_path).verify_content_clearance(SHA_A)
        assert clearance.pii_detected is False
        assert clearance.pages_scanned == 60

    def test_pii_detected_is_a_consequence_not_a_field(self, tmp_path: Path) -> None:
        """La valeur ne peut pas être fabriquée : elle découle d'avoir
        obtenu la clairance."""
        clearance = load_pii(tmp_path).verify_content_clearance(SHA_A)
        with pytest.raises((AttributeError, TypeError)):
            clearance.pii_detected = True  # type: ignore[misc]

    def test_an_unscanned_content_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(SealedEvidenceError, match="never scanned"):
            load_pii(tmp_path).verify_content_clearance("c" * 64)

    def test_a_quarantined_content_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(SealedEvidenceError, match="QUARANTINED"):
            load_pii(tmp_path).verify_content_clearance(SHA_B)

    def test_evidence_for_another_corpus_is_refused(self, tmp_path: Path) -> None:
        path, digest = write_pii(tmp_path, corpus_manifest_sha256="f" * 64)
        with pytest.raises(SealedEvidenceError, match="proves nothing about this one"):
            VerifiedPIIEvidenceRegistry.load(
                path,
                expected_evidence_sha256=digest,
                expected_corpus_manifest_sha256=MANIFEST,
            )

    def test_a_tampered_evidence_file_is_refused(self, tmp_path: Path) -> None:
        path, _ = write_pii(tmp_path)
        with pytest.raises(SealedEvidenceError, match="not the evidence that was"):
            VerifiedPIIEvidenceRegistry.load(
                path,
                expected_evidence_sha256="0" * 64,
                expected_corpus_manifest_sha256=MANIFEST,
            )

    def test_evidence_carrying_raw_pii_is_refused(self, tmp_path: Path) -> None:
        path, digest = write_pii(tmp_path, raw_pii_in_output=True)
        with pytest.raises(SealedEvidenceError, match="raw_pii_in_output"):
            VerifiedPIIEvidenceRegistry.load(
                path,
                expected_evidence_sha256=digest,
                expected_corpus_manifest_sha256=MANIFEST,
            )

    def test_self_contradicting_evidence_is_refused(self, tmp_path: Path) -> None:
        """CLEARED tout en signalant des données personnelles."""
        registry = load_pii(
            tmp_path,
            results=[{"content_sha256": SHA_A, "status": "CLEARED",
                      "pii_detected": True, "pages_scanned": 1,
                      "characters_scanned": 10}],
        )
        with pytest.raises(SealedEvidenceError, match="contradicts itself"):
            registry.verify_content_clearance(SHA_A)

    def test_a_duplicated_verdict_is_refused(self, tmp_path: Path) -> None:
        path, digest = write_pii(
            tmp_path,
            results=[
                {"content_sha256": SHA_A, "status": "CLEARED", "pii_detected": False},
                {"content_sha256": SHA_A, "status": "QUARANTINED_PII",
                 "pii_detected": True},
            ],
        )
        with pytest.raises(SealedEvidenceError, match="twice"):
            VerifiedPIIEvidenceRegistry.load(
                path,
                expected_evidence_sha256=digest,
                expected_corpus_manifest_sha256=MANIFEST,
            )


class TestRightsComeFromEvidenceNotFromThePayload:
    def test_an_approved_zone_resolves_to_its_declared_category(
        self, tmp_path: Path
    ) -> None:
        clearance = load_rights(tmp_path).resolve_rights(
            content_sha256=SHA_A, source_path="01_EDUSCOL_OFFICIEL/x.pdf"
        )
        assert clearance.rights is Rights.officiel_public
        assert clearance.decision_id == "eduscol"

    def test_a_zone_nobody_approved_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(SealedEvidenceError, match="outside every zone"):
            load_rights(tmp_path).resolve_rights(
                content_sha256=SHA_A, source_path="03_RESSOURCES_INTERACTIVES/x.ggb"
            )

    def test_the_most_specific_zone_wins(self, tmp_path: Path) -> None:
        """Un contenu auteur ne doit pas hériter des droits d'une zone
        institutionnelle qui le contient."""
        registry = load_rights(
            tmp_path,
            human_rights_decisions={
                "inst": {"scope_manifest_sha256": MANIFEST,
                         "scope_zone": "04_COMPLEMENTS/",
                         "approved_for_production_rag": True},
                "auteur": {"scope_manifest_sha256": MANIFEST,
                           "scope_zones": ["04_COMPLEMENTS/02_NEXUS/"],
                           "approved_for_production_rag": True},
            },
            source_evidence={
                "inst": {"zone": "04_COMPLEMENTS/",
                         "recommended_rights_category": "officiel_public"},
                "auteur": {"zone": "04_COMPLEMENTS/02_NEXUS/",
                           "recommended_rights_category": "nexus_proprietaire"},
            },
        )
        assert registry.resolve_rights(
            content_sha256=SHA_A, source_path="04_COMPLEMENTS/02_NEXUS/a.pdf"
        ).rights is Rights.nexus_proprietaire
        assert registry.resolve_rights(
            content_sha256=SHA_A, source_path="04_COMPLEMENTS/01_INST/b.pdf"
        ).rights is Rights.officiel_public

    def test_a_decision_taken_on_another_corpus_does_not_transfer(
        self, tmp_path: Path
    ) -> None:
        path, digest = write_rights(
            tmp_path,
            human_rights_decisions={
                "eduscol": {"scope_manifest_sha256": "9" * 64,
                            "scope_zone": "01_EDUSCOL_OFFICIEL/",
                            "approved_for_production_rag": True}
            },
        )
        with pytest.raises(SealedEvidenceError, match="does not transfer"):
            VerifiedRightsEvidenceRegistry.load(
                path,
                expected_registry_sha256=digest,
                expected_corpus_manifest_sha256=MANIFEST,
            )

    def test_an_unbounded_approval_is_refused(self, tmp_path: Path) -> None:
        path, digest = write_rights(
            tmp_path,
            human_rights_decisions={
                "everything": {"scope_manifest_sha256": MANIFEST,
                               "approved_for_production_rag": True}
            },
        )
        with pytest.raises(SealedEvidenceError, match="without naming a"):
            VerifiedRightsEvidenceRegistry.load(
                path,
                expected_registry_sha256=digest,
                expected_corpus_manifest_sha256=MANIFEST,
            )

    def test_an_internal_only_decision_does_not_authorize_production(
        self, tmp_path: Path
    ) -> None:
        path, digest = write_rights(
            tmp_path,
            human_rights_decisions={
                "eduscol": {"scope_manifest_sha256": MANIFEST,
                            "scope_zone": "01_EDUSCOL_OFFICIEL/",
                            "approved_for_internal_rag": True,
                            "approved_for_production_rag": False}
            },
        )
        with pytest.raises(SealedEvidenceError, match="no human decision approves"):
            VerifiedRightsEvidenceRegistry.load(
                path,
                expected_registry_sha256=digest,
                expected_corpus_manifest_sha256=MANIFEST,
            )

    def test_a_third_party_exception_overrides_the_zone(self, tmp_path: Path) -> None:
        """Une approbation de zone ne peut pas éteindre un droit d'auteur
        constaté sur un document précis."""
        registry = load_rights(
            tmp_path,
            document_specific_exceptions=[{"content_sha256": SHA_A}],
        )
        with pytest.raises(SealedEvidenceError, match="third-party restriction"):
            registry.resolve_rights(
                content_sha256=SHA_A, source_path="01_EDUSCOL_OFFICIEL/x.pdf"
            )

    def test_a_registry_without_a_human_decision_is_refused(
        self, tmp_path: Path
    ) -> None:
        path, digest = write_rights(tmp_path, human_rights_decisions={})
        with pytest.raises(SealedEvidenceError, match="no human decision"):
            VerifiedRightsEvidenceRegistry.load(
                path,
                expected_registry_sha256=digest,
                expected_corpus_manifest_sha256=MANIFEST,
            )

    def test_unknown_rights_cannot_be_granted(self, tmp_path: Path) -> None:
        path, digest = write_rights(
            tmp_path,
            source_evidence={
                "eduscol": {"zone": "01_EDUSCOL_OFFICIEL/",
                            "recommended_rights_category": "unknown"}
            },
        )
        with pytest.raises(SealedEvidenceError, match="a right nobody named"):
            VerifiedRightsEvidenceRegistry.load(
                path,
                expected_registry_sha256=digest,
                expected_corpus_manifest_sha256=MANIFEST,
            )


class TestAgainstTheRealSealedEvidence:
    """Les preuves réellement scellées du dépôt et de la revue H2-F."""

    REGISTRY = (
        Path(__file__).resolve().parents[3]
        / "services/rag-pedago/configs/rights_evidence_registry.yml"
    )
    REAL_MANIFEST = (
        "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
    )

    def test_the_repository_registry_resolves_eduscol_to_official_public(
        self,
    ) -> None:
        registry = VerifiedRightsEvidenceRegistry.load(
            self.REGISTRY,
            expected_registry_sha256=hashlib.sha256(
                self.REGISTRY.read_bytes()
            ).hexdigest(),
            expected_corpus_manifest_sha256=self.REAL_MANIFEST,
        )
        clearance = registry.resolve_rights(
            content_sha256="371d0c82ed1f47614ee9cbfdaa86cfb4add1f239a84882d9731fbd125105925d",
            source_path="01_EDUSCOL_OFFICIEL/LYCEE/TRANSVERSAL/x.pdf",
        )
        assert clearance.rights is Rights.officiel_public

    def test_nexus_authored_content_is_not_official_public(self) -> None:
        """La distinction compte : une ressource écrite par Nexus n'est pas
        un document institutionnel."""
        registry = VerifiedRightsEvidenceRegistry.load(
            self.REGISTRY,
            expected_registry_sha256=hashlib.sha256(
                self.REGISTRY.read_bytes()
            ).hexdigest(),
            expected_corpus_manifest_sha256=self.REAL_MANIFEST,
        )
        clearance = registry.resolve_rights(
            content_sha256=SHA_A, source_path="02_NEXUS_DIAGNOSTICS/d.pdf"
        )
        assert clearance.rights is Rights.nexus_proprietaire

    def test_geogebra_has_no_production_approval(self) -> None:
        registry = VerifiedRightsEvidenceRegistry.load(
            self.REGISTRY,
            expected_registry_sha256=hashlib.sha256(
                self.REGISTRY.read_bytes()
            ).hexdigest(),
            expected_corpus_manifest_sha256=self.REAL_MANIFEST,
        )
        with pytest.raises(SealedEvidenceError, match="outside every zone"):
            registry.resolve_rights(
                content_sha256=SHA_A,
                source_path="03_RESSOURCES_INTERACTIVES/x.ggb",
            )
