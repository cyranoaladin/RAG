"""Promotion des candidats dont seule la currentness bloquait l'INGEST.

Corrige le constat de l'audit Tier A du 2026-08-15 : 11 objets sont déjà
preuve-résolus (currentness=actuel par identité d'octets contre la source
primaire, droits et PII déjà clairs) mais restent REVIEW_REQUIRED car
``corpus_zone_routing.yml`` route ``01_EDUSCOL_OFFICIEL/`` sans sous-dossier
de statut vers ``base_disposition=REVIEW_REQUIRED`` de façon purement
statique, jamais par contenu. Ce fichier teste les deux fonctions ajoutées
pour fermer ce gap : le chargeur d'évidence (fail-closed, jamais le
drapeau ``byte_identity`` seul) et la fonction de promotion elle-même
(jamais un défaut CURRENT implicite).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from rag_pedago.imports.h2b_coverage_report import (
    _load_currentness_verification_evidence,
    _promote_currentness_verified_candidates,
    generate_coverage_report,
)

MANIFEST_SHA256 = "d" * 64
CONTENT_A = "a" * 64  # unclassified, currentness-verified, rights+PII clear
CONTENT_B = "b" * 64  # a_verifier, currentness-verified, rights+PII clear
CONTENT_C = "c" * 64  # unclassified, currentness-verified, but PII NOT clear
CONTENT_D = "d" * 64  # unclassified, NOT covered by currentness evidence
CONTENT_E = "e" * 64  # already base_disposition=INGEST -- never touched
CONTENT_F = "f" * 64  # unclassified, currentness-verified, but currentness="transition" already decided


def _evidence_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "evidence_kind": "MULTILEVEL_ARTIFACT_CURRENTNESS_V1",
        "corpus_manifest_sha256": MANIFEST_SHA256,
        "artifacts": [
            {
                "content_sha256": CONTENT_A,
                "decision": "CURRENT",
                "byte_identity": True,
                "current_download_sha256": CONTENT_A,
                "effective_currentness": "actuel",
            },
            {
                "content_sha256": CONTENT_B,
                "decision": "CURRENT",
                "byte_identity": True,
                "current_download_sha256": CONTENT_B,
                "effective_currentness": "actuel",
            },
            {
                "content_sha256": CONTENT_C,
                "decision": "CURRENT",
                "byte_identity": True,
                "current_download_sha256": CONTENT_C,
                "effective_currentness": "actuel",
            },
            {
                "content_sha256": CONTENT_F,
                "decision": "CURRENT",
                "byte_identity": True,
                "current_download_sha256": CONTENT_F,
                "effective_currentness": "actuel",
            },
            {
                "content_sha256": "9" * 64,
                "decision": "REVIEW_REQUIRED",
                "byte_identity": False,
                "current_download_sha256": None,
                "effective_currentness": None,
            },
        ],
    }
    document.update(overrides)
    return document


def _write_evidence(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


class TestLoadCurrentnessVerificationEvidence:
    def test_real_evidence_yields_only_current_byte_identity_confirmed_entries(
        self, tmp_path: Path
    ) -> None:
        path = _write_evidence(tmp_path / "evidence.yml", _evidence_document())
        verified = _load_currentness_verification_evidence(
            path, manifest_sha256=MANIFEST_SHA256
        )
        assert verified == frozenset({CONTENT_A, CONTENT_B, CONTENT_C, CONTENT_F})

    def test_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            _load_currentness_verification_evidence(
                tmp_path / "missing.yml", manifest_sha256=MANIFEST_SHA256
            )

    def test_wrong_evidence_kind_is_refused(self, tmp_path: Path) -> None:
        path = _write_evidence(
            tmp_path / "evidence.yml",
            _evidence_document(evidence_kind="SOMETHING_ELSE_V1"),
        )
        with pytest.raises(ValueError, match="evidence_kind"):
            _load_currentness_verification_evidence(
                path, manifest_sha256=MANIFEST_SHA256
            )

    def test_manifest_mismatch_is_refused(self, tmp_path: Path) -> None:
        path = _write_evidence(
            tmp_path / "evidence.yml",
            _evidence_document(corpus_manifest_sha256="0" * 64),
        )
        with pytest.raises(ValueError, match="another manifest"):
            _load_currentness_verification_evidence(
                path, manifest_sha256=MANIFEST_SHA256
            )

    def test_current_without_byte_identity_flag_is_refused(self, tmp_path: Path) -> None:
        document = _evidence_document()
        document["artifacts"][0]["byte_identity"] = False
        path = _write_evidence(tmp_path / "evidence.yml", document)
        with pytest.raises(ValueError, match="byte_identity=true"):
            _load_currentness_verification_evidence(
                path, manifest_sha256=MANIFEST_SHA256
            )

    def test_byte_identity_flag_alone_is_not_trusted_download_sha_must_match(
        self, tmp_path: Path
    ) -> None:
        """La preuve retenue est l'égalité des empreintes, jamais le
        booléen seul -- un booléen positionné sans preuve concordante est
        un refus."""
        document = _evidence_document()
        document["artifacts"][0]["current_download_sha256"] = "9" * 64
        path = _write_evidence(tmp_path / "evidence.yml", document)
        with pytest.raises(ValueError, match="does not equal"):
            _load_currentness_verification_evidence(
                path, manifest_sha256=MANIFEST_SHA256
            )

    def test_current_without_actuel_currentness_is_refused(self, tmp_path: Path) -> None:
        document = _evidence_document()
        document["artifacts"][0]["effective_currentness"] = "transition"
        path = _write_evidence(tmp_path / "evidence.yml", document)
        with pytest.raises(ValueError, match="effective_currentness"):
            _load_currentness_verification_evidence(
                path, manifest_sha256=MANIFEST_SHA256
            )


def _item(
    content_sha256: str,
    *,
    base_disposition: str = "REVIEW_REQUIRED",
    disposition: str = "REVIEW_REQUIRED",
    currentness: str = "unclassified",
) -> dict[str, Any]:
    return {
        "content_sha256": content_sha256,
        "path": f"01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/MATHS/{content_sha256[:8]}.pdf",
        "base_disposition": base_disposition,
        "disposition": disposition,
        "currentness": currentness,
        "gate_statuses": {},
    }


class TestPromoteCurrentnessVerifiedCandidates:
    def test_real_verified_unclassified_and_a_verifier_items_are_promoted(self) -> None:
        objects = [
            _item(CONTENT_A, currentness="unclassified"),
            _item(CONTENT_B, currentness="a_verifier"),
        ]
        promoted = _promote_currentness_verified_candidates(
            objects,
            currentness_verified_sha256=frozenset({CONTENT_A, CONTENT_B}),
            rights_cleared_sha256=frozenset({CONTENT_A, CONTENT_B}),
            pii_cleared_sha256=frozenset({CONTENT_A, CONTENT_B}),
            pii_quarantined_sha256=frozenset(),
        )
        assert promoted == 2
        for item in objects:
            assert item["base_disposition"] == "INGEST"
            assert item["currentness"] == "actuel"
            assert item["gate_statuses"]["rights"] == "PASS"
            assert item["gate_statuses"]["pii"] == "PASS"
            # L'autorité reste non franchie -- seule l'étape d'autorité
            # peut jamais l'accorder.
            assert item["gate_statuses"]["authority"] == "BLOCKED_NOT_CLEARED"
            assert item["disposition"] == "REVIEW_REQUIRED"

    def test_item_not_covered_by_evidence_is_never_touched(self) -> None:
        objects = [_item(CONTENT_D, currentness="unclassified")]
        promoted = _promote_currentness_verified_candidates(
            objects,
            currentness_verified_sha256=frozenset({CONTENT_A}),
            rights_cleared_sha256=frozenset({CONTENT_D}),
            pii_cleared_sha256=frozenset({CONTENT_D}),
            pii_quarantined_sha256=frozenset(),
        )
        assert promoted == 0
        assert objects[0]["base_disposition"] == "REVIEW_REQUIRED"
        assert objects[0]["currentness"] == "unclassified"

    def test_rights_not_cleared_blocks_promotion(self) -> None:
        objects = [_item(CONTENT_A, currentness="unclassified")]
        promoted = _promote_currentness_verified_candidates(
            objects,
            currentness_verified_sha256=frozenset({CONTENT_A}),
            rights_cleared_sha256=frozenset(),  # NOT cleared
            pii_cleared_sha256=frozenset({CONTENT_A}),
            pii_quarantined_sha256=frozenset(),
        )
        assert promoted == 0
        assert objects[0]["base_disposition"] == "REVIEW_REQUIRED"

    def test_pii_not_cleared_blocks_promotion(self) -> None:
        objects = [_item(CONTENT_C, currentness="unclassified")]
        promoted = _promote_currentness_verified_candidates(
            objects,
            currentness_verified_sha256=frozenset({CONTENT_C}),
            rights_cleared_sha256=frozenset({CONTENT_C}),
            pii_cleared_sha256=frozenset(),  # NOT cleared
            pii_quarantined_sha256=frozenset(),
        )
        assert promoted == 0
        assert objects[0]["base_disposition"] == "REVIEW_REQUIRED"

    def test_pii_quarantined_blocks_promotion(self) -> None:
        objects = [_item(CONTENT_C, currentness="unclassified")]
        promoted = _promote_currentness_verified_candidates(
            objects,
            currentness_verified_sha256=frozenset({CONTENT_C}),
            rights_cleared_sha256=frozenset({CONTENT_C}),
            pii_cleared_sha256=frozenset(),
            pii_quarantined_sha256=frozenset({CONTENT_C}),
        )
        assert promoted == 0
        assert objects[0]["base_disposition"] == "REVIEW_REQUIRED"

    def test_ingest_base_disposition_is_never_touched_even_if_currentness_looks_unclassified(
        self,
    ) -> None:
        """Isole la garde ``base_disposition`` de la garde ``currentness``
        -- une combinaison qu'un vrai compilateur ne produit jamais, mais
        la garde doit rester indépendamment nécessaire (défense en
        profondeur)."""
        objects = [
            _item(CONTENT_A, base_disposition="INGEST", currentness="unclassified")
        ]
        original = dict(objects[0])
        promoted = _promote_currentness_verified_candidates(
            objects,
            currentness_verified_sha256=frozenset({CONTENT_A}),
            rights_cleared_sha256=frozenset({CONTENT_A}),
            pii_cleared_sha256=frozenset({CONTENT_A}),
            pii_quarantined_sha256=frozenset(),
        )
        assert promoted == 0
        assert objects[0] == original

    def test_already_ingest_base_disposition_is_never_touched(self) -> None:
        objects = [
            _item(
                CONTENT_E,
                base_disposition="INGEST",
                disposition="INGEST",
                currentness="actuel",
            )
        ]
        original = dict(objects[0])
        promoted = _promote_currentness_verified_candidates(
            objects,
            currentness_verified_sha256=frozenset({CONTENT_E}),
            rights_cleared_sha256=frozenset({CONTENT_E}),
            pii_cleared_sha256=frozenset({CONTENT_E}),
            pii_quarantined_sha256=frozenset(),
        )
        assert promoted == 0
        assert objects[0] == original

    def test_a_decided_currentness_other_than_unclassified_or_a_verifier_is_never_overridden(
        self,
    ) -> None:
        """``transition``/``archive``/``conflict`` sont des motifs déjà
        décidés -- même couverts par l'évidence, ce mécanisme ne les
        touche jamais."""
        objects = [_item(CONTENT_F, currentness="transition")]
        promoted = _promote_currentness_verified_candidates(
            objects,
            currentness_verified_sha256=frozenset({CONTENT_F}),
            rights_cleared_sha256=frozenset({CONTENT_F}),
            pii_cleared_sha256=frozenset({CONTENT_F}),
            pii_quarantined_sha256=frozenset(),
        )
        assert promoted == 0
        assert objects[0]["currentness"] == "transition"

    def test_empty_verified_set_is_a_cheap_noop(self) -> None:
        objects = [_item(CONTENT_A, currentness="unclassified")]
        promoted = _promote_currentness_verified_candidates(
            objects,
            currentness_verified_sha256=frozenset(),
            rights_cleared_sha256=frozenset({CONTENT_A}),
            pii_cleared_sha256=frozenset({CONTENT_A}),
            pii_quarantined_sha256=frozenset(),
        )
        assert promoted == 0
        assert objects[0]["base_disposition"] == "REVIEW_REQUIRED"

    def test_disposition_reason_documents_the_promotion(self) -> None:
        objects = [_item(CONTENT_A, currentness="unclassified")]
        _promote_currentness_verified_candidates(
            objects,
            currentness_verified_sha256=frozenset({CONTENT_A}),
            rights_cleared_sha256=frozenset({CONTENT_A}),
            pii_cleared_sha256=frozenset({CONTENT_A}),
            pii_quarantined_sha256=frozenset(),
        )
        assert "Currentness verified" in objects[0]["disposition_reason"]


# ---------------------------------------------------------------------------
# Integration: the real generate_coverage_report() wiring, not just the two
# isolated functions above -- proves the plumbing (manifest binding, entries
# derivation, rights/PII re-derivation) is correct end-to-end.
# ---------------------------------------------------------------------------

CONTENT_ACTUEL = "1" * 64
CONTENT_UNCLASSIFIED = "2" * 64
_MANIFEST_LINES = (
    f"{CONTENT_ACTUEL}  01_EDUSCOL_OFFICIEL/10_ACTUEL_CONFIRME/current.pdf\n"
    f"{CONTENT_UNCLASSIFIED}  "
    "01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/MATHEMATIQUES/unclassified.pdf\n"
)
_INTEGRATION_MANIFEST_SHA256 = hashlib.sha256(_MANIFEST_LINES.encode()).hexdigest()


def _write_integration_fixtures(tmp_path: Path) -> dict[str, Path]:
    manifest_path = tmp_path / "00_ADMIN" / "SHA256SUMS.txt"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(_MANIFEST_LINES, encoding="utf-8")

    routing = {
        "config_id": "currentness-integration-routing-v1",
        "manifest_sha256": _INTEGRATION_MANIFEST_SHA256,
        "rights_evidence_perimeter": ["00_ADMIN/", "01_EDUSCOL_OFFICIEL/"],
        "zone_rules": [
            {"zone_prefix": "00_ADMIN/", "disposition": "EXCLUDE", "reason": "admin"},
            {
                "zone_prefix": "01_EDUSCOL_OFFICIEL/",
                "disposition": "INGEST",
                "currentness": "actuel",
            },
        ],
    }
    rights = {
        "registry_id": "currentness-integration-rights-v1",
        "human_rights_decisions": {
            "eduscol": {
                "decision_type": "HUMAN_ORGANIZATIONAL_RIGHTS_APPROVAL",
                "decision_maker": "Nexus Réussite",
                "decision_date": "2026-08-08",
                "scope_manifest_sha256": _INTEGRATION_MANIFEST_SHA256,
                "scope_zone": "01_EDUSCOL_OFFICIEL/",
                "approved_for_production_rag": True,
                "generic_rights_blocker": False,
            }
        },
        "source_evidence": {
            "admin": {
                "zone": "00_ADMIN/",
                "rights_status": "REVIEW_REQUIRED",
                "disposition_override": "EXCLUDE",
            },
            "eduscol": {
                "zone": "01_EDUSCOL_OFFICIEL/",
                "rights_status": "CLEARED_BY_HUMAN_DECISION",
                "rights_decision_ref": "eduscol",
            },
        },
        "summary": {"total_zones": 2},
    }
    pii = {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "scanner_version": "currentness-integration-scanner-v1",
        "scanner_sha256": "1" * 64,
        "policy_version": "currentness-integration-policy-v1",
        "policy_sha256": "2" * 64,
        "corpus_manifest_sha256": _INTEGRATION_MANIFEST_SHA256,
        "remote_access_mode": "READ_ONLY",
        "remote_write_operations": 0,
        "raw_pii_in_output": False,
        "raw_pii_in_logs": False,
        "required_pdf_path_count": 2,
        "required_pdf_path_set_digest": hashlib.sha256(
            
                b"01_EDUSCOL_OFFICIEL/10_ACTUEL_CONFIRME/current.pdf\n"
                b"01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/MATHEMATIQUES/unclassified.pdf\n"
            
        ).hexdigest(),
        "summary": {
            "sha256_mismatches": 0,
            "pii_scan_scope": "ALL_CORPUS_PDFS",
            "pii_scan_required": 2,
            "pii_scan_exempt": 0,
        },
        "results": [
            {
                "content_sha256": CONTENT_ACTUEL,
                "physical_object_count": 1,
                "status": "CLEARED",
                "error_code": None,
            },
            {
                "content_sha256": CONTENT_UNCLASSIFIED,
                "physical_object_count": 1,
                "status": "CLEARED",
                "error_code": None,
            },
        ],
    }

    routing_path = tmp_path / "routing.yml"
    rights_path = tmp_path / "rights.yml"
    pii_path = tmp_path / "pii.json"
    routing_path.write_text(yaml.safe_dump(routing), encoding="utf-8")
    rights_path.write_text(yaml.safe_dump(rights), encoding="utf-8")
    pii_path.write_text(json.dumps(pii), encoding="utf-8")

    catalog = {
        "catalog_kind": "REAL_SEALED_CORPUS",
        "manifest_sha256": _INTEGRATION_MANIFEST_SHA256,
        "manifest_entries": 2,
        "physical_object_count": 3,
        "content_artifact_count": 2,
        "eduscol_unique_artifacts": 2,
        "eduscol_placement_count": 2,
        "eduscol_placements_classified": 1,
        "eduscol_placements_unclassified": 1,
        "multi_placement_artifacts": 0,
        "disposition_counts": {
            "INGEST": 0,
            "REVIEW_REQUIRED": 2,
            "QUARANTINE": 0,
            "ARCHIVE_ONLY": 0,
            "EXCLUDE": 1,
            "UNSUPPORTED": 0,
        },
        "unclassified": 0,
        "multiple_primary_disposition": 0,
        "verification_passed": True,
        "verification_errors": [],
        "physical_objects": [
            {
                "content_sha256": CONTENT_ACTUEL,
                "path": "01_EDUSCOL_OFFICIEL/10_ACTUEL_CONFIRME/current.pdf",
                "base_disposition": "INGEST",
                "disposition": "REVIEW_REQUIRED",
                "zone": "01_EDUSCOL_OFFICIEL/",
                "currentness": "actuel",
                "rights_category_candidate": "officiel_public",
                "gate_statuses": {
                    "rights": "PASS",
                    "pii": "PASS",
                    "authority": "BLOCKED_NOT_CLEARED",
                },
                "provenance_status": "VERIFIED",
                "attribution_metadata": {
                    "source": "Eduscol",
                    "source_url": "https://eduscol.education.gouv.fr/test",
                },
            },
            {
                "content_sha256": CONTENT_UNCLASSIFIED,
                "path": (
                    "01_EDUSCOL_OFFICIEL/LYCEE/SECONDE/MATHEMATIQUES/"
                    "unclassified.pdf"
                ),
                "base_disposition": "REVIEW_REQUIRED",
                "disposition": "REVIEW_REQUIRED",
                "zone": "01_EDUSCOL_OFFICIEL/",
                "currentness": "unclassified",
                "rights_category_candidate": "officiel_public",
                "gate_statuses": {},
                "provenance_status": "VERIFIED",
                "attribution_metadata": {
                    "source": "Eduscol",
                    "source_url": "https://eduscol.education.gouv.fr/test2",
                },
            },
            {
                "content_sha256": _INTEGRATION_MANIFEST_SHA256,
                "path": "00_ADMIN/SHA256SUMS.txt",
                "base_disposition": "EXCLUDE",
                "disposition": "EXCLUDE",
                "zone": "00_ADMIN/",
                "currentness": None,
                "gate_statuses": {},
                "provenance_status": "VERIFIED",
                "attribution_metadata": {
                    "source": "NEXUS_CORPUS_GOVERNANCE",
                    "source_reference": "00_ADMIN/SHA256SUMS.txt",
                },
            },
        ],
    }
    catalog_path = tmp_path / "real-catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    golden = {
        "spec_id": "currentness_integration_fixture_v1",
        "catalog_kind_required": "REAL_SEALED_CORPUS",
        "positive_controls": [
            {
                "control_id": "pos_actuel",
                "sha256_prefix": CONTENT_ACTUEL[:12],
                "expected_base_disposition": "INGEST",
                "expected_final_disposition": "REVIEW_REQUIRED",
                "expected_currentness": "actuel",
                "expected_gate_statuses": {
                    "rights": "PASS",
                    "pii": "PASS",
                    "authority": "BLOCKED_NOT_CLEARED",
                },
            }
        ],
        "boundary_controls": [],
        "negative_controls": [
            {
                "control_id": "neg_manifest",
                "path": "00_ADMIN/SHA256SUMS.txt",
                "expected_count": 1,
                "expected_disposition": "EXCLUDE",
            }
        ],
        "descriptive_assertions": {"authoritative": False, "items": []},
        "coverage_summary": {
            "total_controls": 2,
            "positive_controls": 1,
            "boundary_controls": 0,
            "negative_controls": 1,
        },
    }
    golden_path = tmp_path / "golden.yml"
    golden_path.write_text(yaml.safe_dump(golden, sort_keys=False), encoding="utf-8")

    evidence_path = _write_evidence(
        tmp_path / "currentness_evidence.yml",
        {
            "evidence_kind": "MULTILEVEL_ARTIFACT_CURRENTNESS_V1",
            "corpus_manifest_sha256": _INTEGRATION_MANIFEST_SHA256,
            "artifacts": [
                {
                    "content_sha256": CONTENT_UNCLASSIFIED,
                    "decision": "CURRENT",
                    "byte_identity": True,
                    "current_download_sha256": CONTENT_UNCLASSIFIED,
                    "effective_currentness": "actuel",
                }
            ],
        },
    )

    return {
        "manifest": manifest_path,
        "routing": routing_path,
        "rights": rights_path,
        "pii": pii_path,
        "catalog": catalog_path,
        "golden": golden_path,
        "currentness_evidence": evidence_path,
    }


class TestGenerateCoverageReportWiresCurrentnessPromotion:
    def test_currentness_verification_path_promotes_the_real_candidate(
        self, tmp_path: Path
    ) -> None:
        paths = _write_integration_fixtures(tmp_path)

        report = generate_coverage_report(
            paths["catalog"],
            rights_path=paths["rights"],
            pii_path=paths["pii"],
            routing_path=paths["routing"],
            golden_path=paths["golden"],
            manifest_path=paths["manifest"],
            expected_total=3,
            expected_manifest_sha256=_INTEGRATION_MANIFEST_SHA256,
            currentness_verification_path=paths["currentness_evidence"],
        )

        # Both real INGEST candidates (the always-actuel one, and the
        # newly currentness-promoted one) now block only on authority --
        # never on rights/PII, which were freshly, correctly evaluated.
        assert report.blocked_ingest_candidates == 2
        assert report.mandatory_gate_blockers == {"authority": 2}
        assert report.safety_invariants["INGEST_WITHOUT_RIGHTS_CLEARANCE"] == 0
        assert report.safety_invariants["INGEST_WITHOUT_PII_CLEARANCE"] == 0

    def test_without_currentness_verification_path_the_candidate_stays_blocked(
        self, tmp_path: Path
    ) -> None:
        paths = _write_integration_fixtures(tmp_path)

        report = generate_coverage_report(
            paths["catalog"],
            rights_path=paths["rights"],
            pii_path=paths["pii"],
            routing_path=paths["routing"],
            golden_path=paths["golden"],
            manifest_path=paths["manifest"],
            expected_total=3,
            expected_manifest_sha256=_INTEGRATION_MANIFEST_SHA256,
            currentness_verification_path=None,
        )

        # Without the evidence path, only the always-actuel candidate is
        # a real INGEST candidate -- the unclassified one never appears.
        assert report.blocked_ingest_candidates == 1
        assert report.mandatory_gate_blockers == {"authority": 1}
