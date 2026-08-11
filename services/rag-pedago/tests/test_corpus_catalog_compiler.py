"""Tests for corpus catalog compiler — H2-B."""
import hashlib
from pathlib import Path

import pytest

from rag_pedago.imports.corpus_catalog_compiler import (
    Disposition,
    _determine_disposition,
    _parse_sealed_manifest,
    compile_catalog,
    compile_governed_sealed_catalog,
    compile_sealed_catalog,
    compute_file_sha256,
    load_routing_config,
)

FIXTURES = Path(__file__).parent.parent / "data" / "fixtures" / "corpus_h2b"


def _sha(value: str) -> str:
    return value * 64


def _write_sealed_fixture(tmp_path: Path) -> tuple[Path, Path, dict]:
    manifest = tmp_path / "SHA256SUMS.txt"
    manifest.write_text(
        "\n".join(
            (
                f"{_sha('a')}  01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/10_ACTUEL_CONFIRME/MATHS/doc.pdf",
                f"{_sha('a')}  00_INDEX_PROVENANCE/EDUSCOL_META/doc.pdf",
                f"{_sha('b')}  00_ADMIN/BUILD_INFO.json",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    placements = tmp_path / "catalogue-complet.tsv"
    placements.write_text(
        "\t".join(
            (
                "sha256",
                "scope",
                "famille",
                "matiere_ou_rubrique",
                "niveau",
                "type_document",
                "annee",
                "statut",
                "titre",
                "url_source",
                "objet_source",
                "chemin_technique_existant",
                "chemin_par_niveau",
                "chemin_par_scope",
                "taille_octets",
                "pages_pdf",
                "integrite",
            )
        )
        + "\n"
        + "\t".join(
            (
                _sha("a"),
                "lycee/general/mathematiques",
                "lycee",
                "mathematiques",
                "terminale",
                "cours",
                "2026",
                "actuel",
                "Document test",
                "https://eduscol.education.gouv.fr/test",
                "source/doc.pdf",
                "by_scope/terminale/doc.pdf",
                "by_level/terminale/doc.pdf",
                "by_scope/terminale/doc.pdf",
                "100",
                "1",
                "ok",
            )
        )
        + "\n"
        + "\t".join(
            (
                _sha("a"),
                "lycee/seconde/mathematiques",
                "lycee",
                "mathematiques",
                "seconde",
                "cours",
                "2026",
                "actuel",
                "Document test",
                "https://eduscol.education.gouv.fr/test",
                "source/doc.pdf",
                "by_scope/seconde/doc.pdf",
                "by_level/seconde/doc.pdf",
                "by_scope/seconde/doc.pdf",
                "100",
                "1",
                "ok",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    config = {
        "config_id": "sealed-test-v1",
        "manifest_sha256": manifest_digest,
        "rights_evidence_perimeter": [
            "00_ADMIN/",
            "00_INDEX_PROVENANCE/",
            "01_EDUSCOL_OFFICIEL/",
        ],
        "zone_rules": [
            {
                "zone_prefix": "00_ADMIN/",
                "disposition": "EXCLUDE",
                "reason": "admin",
            },
            {
                "zone_prefix": "00_INDEX_PROVENANCE/",
                "disposition": "EXCLUDE",
                "reason": "index",
            },
            {
                "zone_prefix": "01_EDUSCOL_OFFICIEL/",
                "sub_zone_routing": [
                    {
                        "sub_zone_suffix": "/10_ACTUEL_CONFIRME/",
                        "disposition": "INGEST",
                        "currentness": "actuel",
                    },
                    {
                        "sub_zone_suffix": None,
                        "disposition": "REVIEW_REQUIRED",
                        "currentness": "unclassified",
                    },
                ],
            },
        ],
    }
    return manifest, placements, config


def _rights_registry(manifest_sha256: str) -> dict:
    return {
        "registry_id": "rights-test-v1",
        "human_rights_decisions": {
            "eduscol": {
                "decision_type": "HUMAN_ORGANIZATIONAL_RIGHTS_APPROVAL",
                "decision_maker": "Nexus Réussite",
                "decision_date": "2026-08-08",
                "scope_manifest_sha256": manifest_sha256,
                "scope_zone": "01_EDUSCOL_OFFICIEL/",
                "approved_for_production_rag": True,
                "generic_rights_blocker": False,
            }
        },
        "source_evidence": {
            "eduscol": {
                "zone": "01_EDUSCOL_OFFICIEL/",
                "rights_status": "CLEARED_BY_HUMAN_DECISION",
                "rights_decision_ref": "eduscol",
            },
            "index": {
                "zone": "00_INDEX_PROVENANCE/",
                "rights_status": "REVIEW_REQUIRED",
                "disposition_override": "EXCLUDE",
            },
            "admin": {
                "zone": "00_ADMIN/",
                "rights_status": "REVIEW_REQUIRED",
                "disposition_override": "EXCLUDE",
            },
        },
        "summary": {"total_zones": 3},
    }


def _pii_evidence(manifest_sha256: str, status: str = "CLEARED") -> dict:
    pdf_paths = {
        "01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/10_ACTUEL_CONFIRME/MATHS/doc.pdf",
        "00_INDEX_PROVENANCE/EDUSCOL_META/doc.pdf",
    }
    return {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "scanner_version": "pii_scanner_h2b_v2",
        "scanner_sha256": "1" * 64,
        "policy_version": "pii-test-v1",
        "policy_sha256": "2" * 64,
        "corpus_manifest_sha256": manifest_sha256,
        "remote_root": "gdrive_ert:NEXUS_RAG/NEXUS_RAG_GDRIVE_READY",
        "remote_access_mode": "READ_ONLY",
        "remote_write_operations": 0,
        "raw_pii_in_output": False,
        "raw_pii_in_logs": False,
        "required_pdf_path_count": 2,
        "required_pdf_path_set_digest": hashlib.sha256(
            "".join(f"{value}\n" for value in sorted(pdf_paths)).encode()
        ).hexdigest(),
        "summary": {
            "sha256_mismatches": 0,
            "pii_scan_scope": "ALL_CORPUS_PDFS",
            "pii_scan_required": 2,
            "pii_scan_exempt": 0,
        },
        "results": [
            {
                "content_sha256": _sha("a"),
                "physical_object_count": 2,
                "status": status,
                "error_code": None,
            }
        ],
    }


class TestCorpusCatalogCompiler:
    """Test corpus catalog compilation with disposition assignment."""

    @pytest.fixture
    def manifest_path(self) -> Path:
        return FIXTURES / "test_manifest.tsv"

    @pytest.fixture
    def config_path(self) -> Path:
        return FIXTURES / "test_routing_config.yml"

    @pytest.fixture
    def config(self, config_path: Path) -> dict:
        return load_routing_config(config_path)

    def test_compile_catalog_assigns_dispositions(
        self, manifest_path: Path, config: dict
    ) -> None:
        """Compiler assigns exactly one disposition per object."""
        report = compile_catalog(manifest_path, config)

        assert report.corpus_total_objects == 10
        assert len(report.objects) == 10

        # Each object has a disposition
        for obj in report.objects:
            assert obj.disposition is not None
            assert isinstance(obj.disposition, Disposition)

    def test_totals_sum_equals_corpus_total(
        self, manifest_path: Path, config: dict
    ) -> None:
        """SUM(dispositions) = corpus_total_objects."""
        report = compile_catalog(manifest_path, config)

        total = report.totals.total()
        assert total == report.corpus_total_objects
        assert total == 10

    def test_no_duplicate_sha256(
        self, manifest_path: Path, config: dict
    ) -> None:
        """No duplicate SHA256 values (no overlap)."""
        report = compile_catalog(manifest_path, config)

        sha256_values = [obj.sha256 for obj in report.objects]
        assert len(sha256_values) == len(set(sha256_values))

    def test_zone_routing_actuel_confirme(
        self, manifest_path: Path, config: dict
    ) -> None:
        """10_ACTUEL_CONFIRME → INGEST."""
        report = compile_catalog(manifest_path, config)

        actuel_objects = [
            obj for obj in report.objects
            if "/10_ACTUEL_CONFIRME/" in obj.path
        ]
        assert len(actuel_objects) == 1
        assert actuel_objects[0].disposition == Disposition.INGEST
        assert actuel_objects[0].currentness == "actuel"

    def test_zone_routing_transition(
        self, manifest_path: Path, config: dict
    ) -> None:
        """20_TRANSITION_OU_ACTUEL → REVIEW_REQUIRED."""
        report = compile_catalog(manifest_path, config)

        transition_objects = [
            obj for obj in report.objects
            if "/20_TRANSITION_OU_ACTUEL/" in obj.path
        ]
        assert len(transition_objects) == 1
        assert transition_objects[0].disposition == Disposition.REVIEW_REQUIRED
        assert transition_objects[0].currentness == "transition"

    def test_zone_routing_a_verifier(
        self, manifest_path: Path, config: dict
    ) -> None:
        """80_A_VERIFIER → REVIEW_REQUIRED."""
        report = compile_catalog(manifest_path, config)

        a_verifier_objects = [
            obj for obj in report.objects
            if "/80_A_VERIFIER/" in obj.path
        ]
        assert len(a_verifier_objects) == 1
        assert a_verifier_objects[0].disposition == Disposition.REVIEW_REQUIRED
        assert a_verifier_objects[0].currentness == "a_verifier"

    def test_zone_routing_archive(
        self, manifest_path: Path, config: dict
    ) -> None:
        """90_ARCHIVE_CATALOGUE → ARCHIVE_ONLY."""
        report = compile_catalog(manifest_path, config)

        archive_objects = [
            obj for obj in report.objects
            if "/90_ARCHIVE_CATALOGUE/" in obj.path
        ]
        assert len(archive_objects) == 1
        assert archive_objects[0].disposition == Disposition.ARCHIVE_ONLY
        assert archive_objects[0].currentness == "archive"

    def test_zone_routing_admin_excluded(
        self, manifest_path: Path, config: dict
    ) -> None:
        """00_ADMIN/ → EXCLUDE."""
        report = compile_catalog(manifest_path, config)

        admin_objects = [
            obj for obj in report.objects
            if obj.path.startswith("00_ADMIN/")
        ]
        assert len(admin_objects) == 1
        assert admin_objects[0].disposition == Disposition.EXCLUDE

    def test_zone_routing_index_excluded(
        self, manifest_path: Path, config: dict
    ) -> None:
        """00_INDEX_PROVENANCE/ → EXCLUDE."""
        report = compile_catalog(manifest_path, config)

        index_objects = [
            obj for obj in report.objects
            if obj.path.startswith("00_INDEX_PROVENANCE/")
        ]
        assert len(index_objects) == 1
        assert index_objects[0].disposition == Disposition.EXCLUDE

    def test_zone_routing_geogebra_unsupported(
        self, manifest_path: Path, config: dict
    ) -> None:
        """03_RESSOURCES_INTERACTIVES/ → UNSUPPORTED."""
        report = compile_catalog(manifest_path, config)

        ggb_objects = [
            obj for obj in report.objects
            if obj.path.startswith("03_RESSOURCES_INTERACTIVES/")
        ]
        assert len(ggb_objects) == 1
        assert ggb_objects[0].disposition == Disposition.UNSUPPORTED

    def test_zone_routing_nexus_diagnostics(
        self, manifest_path: Path, config: dict
    ) -> None:
        """02_NEXUS_DIAGNOSTICS/ → REVIEW_REQUIRED with nexus_proprietaire."""
        report = compile_catalog(manifest_path, config)

        nexus_objects = [
            obj for obj in report.objects
            if obj.path.startswith("02_NEXUS_DIAGNOSTICS/")
        ]
        assert len(nexus_objects) == 1
        assert nexus_objects[0].disposition == Disposition.REVIEW_REQUIRED

    def test_zone_routing_complements(
        self, manifest_path: Path, config: dict
    ) -> None:
        """04_COMPLEMENTS_PEDAGOGIQUES/ → REVIEW_REQUIRED."""
        report = compile_catalog(manifest_path, config)

        complement_objects = [
            obj for obj in report.objects
            if obj.path.startswith("04_COMPLEMENTS_PEDAGOGIQUES/")
        ]
        assert len(complement_objects) == 2
        for obj in complement_objects:
            assert obj.disposition == Disposition.REVIEW_REQUIRED

    def test_verification_passes_for_valid_catalog(
        self, manifest_path: Path, config: dict
    ) -> None:
        """Verification passes when totals match."""
        report = compile_catalog(manifest_path, config)
        assert report.verification_passed
        assert len(report.verification_errors) == 0

    def test_expected_disposition_totals(
        self, manifest_path: Path, config: dict
    ) -> None:
        """Check expected totals match fixture."""
        report = compile_catalog(manifest_path, config)

        # Based on the fixture:
        # 1 INGEST (10_ACTUEL_CONFIRME)
        # 5 REVIEW_REQUIRED (transition + a_verifier + nexus + 2 complements)
        # 0 QUARANTINE
        # 1 ARCHIVE_ONLY
        # 2 EXCLUDE (admin + index)
        # 1 UNSUPPORTED (geogebra)
        assert report.totals.ingest == 1
        assert report.totals.review_required == 5
        assert report.totals.quarantine == 0
        assert report.totals.archive_only == 1
        assert report.totals.exclude == 2
        assert report.totals.unsupported == 1

    def test_root_import_readme_is_structurally_excluded(
        self, tmp_path: Path
    ) -> None:
        """The Drive import README is metadata, never pedagogical content."""
        manifest = tmp_path / "manifest.tsv"
        manifest.write_text(
            "sha256\tpath\ttaille_octets\n"
            f"{_sha('a')}\tREADME_GDRIVE_IMPORT.md\t100\n",
            encoding="utf-8",
        )
        config = load_routing_config(
            Path(__file__).parent.parent / "configs" / "corpus_zone_routing.yml"
        )
        config["corpus_total_objects"] = 1

        report = compile_catalog(manifest, config)

        assert report.objects[0].disposition == Disposition.EXCLUDE
        assert report.objects[0].disposition_reason == (
            "Root import instructions — administrative metadata"
        )

    @pytest.mark.parametrize(
        ("path", "expected_reason"),
        [
            (
                "00_ADMIN/EXCLUSIONS_HORS_CORPUS/DOCUMENTS_INFORMATION_FAMILLES/"
                "Nexus_Reussite_Guide_Candidat_Individuel_2026_2027.pdf",
                "Information for families, not pedagogical content",
            ),
            (
                "00_ADMIN/EXCLUSIONS_HORS_CORPUS/PDF_NON_PEDAGOGIQUES/"
                "t_nexus_scan_blanc_non_pedagogique.pdf",
                "Non-pedagogical test scan",
            ),
        ],
    )
    def test_explicit_exclusions_override_the_zone_disposition(
        self,
        path: str,
        expected_reason: str,
    ) -> None:
        config = load_routing_config(
            Path(__file__).parent.parent / "configs" / "corpus_zone_routing.yml"
        )

        disposition, reason, zone, currentness, rights = _determine_disposition(
            path, config
        )

        assert disposition == Disposition.EXCLUDE
        assert reason == expected_reason
        assert zone == "00_ADMIN/"
        assert currentness is None
        assert rights is None

    def test_explicit_exclusion_overrides_an_otherwise_ingest_route(
        self,
    ) -> None:
        config = {
            "explicit_exclusions": [
                {
                    "pattern": "blocked.pdf",
                    "disposition": "EXCLUDE",
                    "reason": "explicitly outside the pedagogical corpus",
                }
            ],
            "zone_rules": [
                {
                    "zone_prefix": "01_EDUSCOL_OFFICIEL/",
                    "disposition": "INGEST",
                    "reason": "otherwise eligible",
                }
            ],
        }

        disposition, reason, *_ = _determine_disposition(
            "01_EDUSCOL_OFFICIEL/blocked.pdf", config
        )

        assert disposition == Disposition.EXCLUDE
        assert reason == "explicitly outside the pedagogical corpus"


class TestDispositionCoverageInvariant:
    """Test the SUM(dispositions) = TOTAL invariant."""

    @pytest.fixture
    def manifest_path(self) -> Path:
        return FIXTURES / "test_manifest.tsv"

    @pytest.fixture
    def config(self) -> dict:
        return load_routing_config(FIXTURES / "test_routing_config.yml")

    def test_every_object_has_exactly_one_disposition(
        self, manifest_path: Path, config: dict
    ) -> None:
        """Each object receives exactly one disposition (no gap, no overlap)."""
        report = compile_catalog(manifest_path, config)

        # Count by disposition
        by_disposition = {}
        for obj in report.objects:
            key = obj.disposition.value
            by_disposition[key] = by_disposition.get(key, 0) + 1

        # Verify counts match totals
        assert by_disposition.get("INGEST", 0) == report.totals.ingest
        assert by_disposition.get("REVIEW_REQUIRED", 0) == report.totals.review_required
        assert by_disposition.get("QUARANTINE", 0) == report.totals.quarantine
        assert by_disposition.get("ARCHIVE_ONLY", 0) == report.totals.archive_only
        assert by_disposition.get("EXCLUDE", 0) == report.totals.exclude
        assert by_disposition.get("UNSUPPORTED", 0) == report.totals.unsupported

        # Sum equals total objects
        assert sum(by_disposition.values()) == report.corpus_total_objects


class TestSealedCorpusCompilation:
    """The production catalog is derived from the sealed physical manifest."""

    def test_preserves_physical_objects_content_identity_and_all_placements(
        self, tmp_path: Path
    ) -> None:
        manifest, placements, config = _write_sealed_fixture(tmp_path)

        catalog = compile_sealed_catalog(
            manifest,
            placements,
            config,
            rights_cleared_sha256={_sha("a")},
            pii_cleared_sha256={_sha("a")},
        )

        assert catalog.manifest_entries == 3
        assert catalog.physical_object_count == 4
        assert catalog.content_artifact_count == 3
        assert catalog.eduscol_unique_artifacts == 1
        assert catalog.eduscol_placement_count == 2
        assert catalog.eduscol_placements_classified == 2
        assert catalog.eduscol_placements_unclassified == 0
        assert catalog.multi_placement_artifacts == 1
        assert catalog.verification_passed is True

        content = catalog.artifacts[_sha("a")]
        assert len(content.physical_objects) == 2
        assert len(content.pedagogical_placements) == 2
        assert {placement.level for placement in content.pedagogical_placements} == {
            "seconde",
            "terminale",
        }
        serialized = catalog.to_dict()
        for item in serialized["physical_objects"]:
            assert item["provenance_status"] == "VERIFIED"
            assert item["attribution_metadata"]
            assert all(item["attribution_metadata"].values())
        eduscol = next(
            item
            for item in serialized["physical_objects"]
            if item["path"].startswith("01_EDUSCOL_OFFICIEL/")
        )
        assert eduscol["attribution_metadata"] == {
            "source": "EDUSCOL",
            "source_reference": "https://eduscol.education.gouv.fr/test",
            "source_url": "https://eduscol.education.gouv.fr/test",
            "source_urls": '["https://eduscol.education.gouv.fr/test"]',
        }

    def test_manifest_self_is_excluded_without_self_referential_entry(
        self, tmp_path: Path
    ) -> None:
        manifest, placements, config = _write_sealed_fixture(tmp_path)

        catalog = compile_sealed_catalog(manifest, placements, config)

        manifest_self = catalog.object_by_path("00_ADMIN/SHA256SUMS.txt")
        assert manifest_self is not None
        assert manifest_self.content_sha256 == hashlib.sha256(
            manifest.read_bytes()
        ).hexdigest()
        assert manifest_self.base_disposition == Disposition.EXCLUDE
        assert manifest_self.disposition == Disposition.EXCLUDE
        assert manifest_self.disposition_reason == "MANIFEST_SELF_OBJECT"
        assert all(
            obj.path != "00_ADMIN/SHA256SUMS.txt"
            for obj in catalog.physical_objects
            if not obj.is_manifest_self
        )

    def test_ingest_is_refused_until_every_mandatory_gate_passes(
        self, tmp_path: Path
    ) -> None:
        manifest, placements, config = _write_sealed_fixture(tmp_path)

        without_pii = compile_sealed_catalog(
            manifest,
            placements,
            config,
            rights_cleared_sha256={_sha("a")},
        )
        candidate = without_pii.object_by_path(
            "01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/10_ACTUEL_CONFIRME/MATHS/doc.pdf"
        )
        assert candidate is not None
        assert candidate.base_disposition == Disposition.INGEST
        assert candidate.disposition == Disposition.REVIEW_REQUIRED
        assert candidate.gate_statuses == {
            "rights": "PASS",
            "pii": "BLOCKED_NOT_CLEARED",
            "authority": "BLOCKED_NOT_CLEARED",
        }

        cleared_candidate = compile_sealed_catalog(
            manifest,
            placements,
            config,
            rights_cleared_sha256={_sha("a")},
            pii_cleared_sha256={_sha("a")},
        )
        eligible = cleared_candidate.object_by_path(candidate.path)
        assert eligible is not None
        assert eligible.disposition == Disposition.REVIEW_REQUIRED
        assert eligible.gate_statuses == {
            "rights": "PASS",
            "pii": "PASS",
            "authority": "BLOCKED_NOT_CLEARED",
        }

    def test_candidate_compiler_rejects_operator_authority_injection(
        self, tmp_path: Path
    ) -> None:
        manifest, placements, config = _write_sealed_fixture(tmp_path)

        with pytest.raises(TypeError, match="authority_cleared_sha256"):
            compile_sealed_catalog(
                manifest,
                placements,
                config,
                rights_cleared_sha256={_sha("a")},
                pii_cleared_sha256={_sha("a")},
                authority_cleared_sha256={_sha("a")},  # type: ignore[call-arg]
            )

    def test_ingest_is_refused_without_real_scope_authority(
        self, tmp_path: Path
    ) -> None:
        manifest, placements, config = _write_sealed_fixture(tmp_path)

        catalog = compile_sealed_catalog(
            manifest,
            placements,
            config,
            rights_cleared_sha256={_sha("a")},
            pii_cleared_sha256={_sha("a")},
        )

        candidate = catalog.object_by_path(
            "01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/10_ACTUEL_CONFIRME/MATHS/doc.pdf"
        )
        assert candidate is not None
        assert candidate.disposition == Disposition.REVIEW_REQUIRED
        assert candidate.gate_statuses == {
            "rights": "PASS",
            "pii": "PASS",
            "authority": "BLOCKED_NOT_CLEARED",
        }

    def test_rejects_manifest_digest_drift(self, tmp_path: Path) -> None:
        manifest, placements, config = _write_sealed_fixture(tmp_path)
        config["manifest_sha256"] = "0" * 64

        with pytest.raises(ValueError, match="manifest SHA256 mismatch"):
            compile_sealed_catalog(manifest, placements, config)

    def test_rejects_unknown_placement_content(self, tmp_path: Path) -> None:
        manifest, placements, config = _write_sealed_fixture(tmp_path)
        placement_text = placements.read_text(encoding="utf-8")
        unknown_row = placement_text.splitlines()[-1].replace(_sha("a"), _sha("c"))
        placements.write_text(
            placement_text + unknown_row + "\n",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="unknown Eduscol content SHA256"):
            compile_sealed_catalog(manifest, placements, config)

    @pytest.mark.parametrize(
        "unsafe_path",
        ("/absolute.pdf", "../escape.pdf", "zone/../../escape.pdf", ""),
    )
    def test_rejects_unsafe_manifest_paths(
        self, tmp_path: Path, unsafe_path: str
    ) -> None:
        manifest, placements, config = _write_sealed_fixture(tmp_path)
        manifest.write_text(
            f"{_sha('a')}  {unsafe_path}\n",
            encoding="utf-8",
        )
        config["manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()

        with pytest.raises(ValueError, match="unsafe manifest path"):
            compile_sealed_catalog(manifest, placements, config)

    def test_rejects_duplicate_physical_path(self, tmp_path: Path) -> None:
        manifest, placements, config = _write_sealed_fixture(tmp_path)
        manifest.write_text(
            f"{_sha('a')}  00_ADMIN/same.json\n"
            f"{_sha('b')}  00_ADMIN/same.json\n",
            encoding="utf-8",
        )
        config["manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()

        with pytest.raises(ValueError, match="duplicate manifest path"):
            compile_sealed_catalog(manifest, placements, config)


class TestGovernedSealedCorpusCompilation:
    def test_joins_manifest_bound_rights_and_pii_evidence(
        self, tmp_path: Path
    ) -> None:
        manifest, placements, config = _write_sealed_fixture(tmp_path)
        manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()

        catalog = compile_governed_sealed_catalog(
            manifest,
            placements,
            config,
            _rights_registry(manifest_sha256),
            _pii_evidence(manifest_sha256),
        )

        eligible = catalog.object_by_path(
            "01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/10_ACTUEL_CONFIRME/MATHS/doc.pdf"
        )
        assert eligible is not None
        assert eligible.disposition == Disposition.REVIEW_REQUIRED
        assert eligible.gate_statuses == {
            "rights": "PASS",
            "pii": "PASS",
            "authority": "BLOCKED_NOT_CLEARED",
        }
        assert sum(catalog.disposition_counts.values()) == 4

    def test_pii_signal_quarantines_current_ingest_candidate(
        self, tmp_path: Path
    ) -> None:
        manifest, placements, config = _write_sealed_fixture(tmp_path)
        manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()

        catalog = compile_governed_sealed_catalog(
            manifest,
            placements,
            config,
            _rights_registry(manifest_sha256),
            _pii_evidence(manifest_sha256, status="QUARANTINED_PII"),
        )

        candidate = catalog.object_by_path(
            "01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/10_ACTUEL_CONFIRME/MATHS/doc.pdf"
        )
        assert candidate is not None
        assert candidate.disposition == Disposition.QUARANTINE
        assert candidate.gate_statuses["pii"] == "BLOCKED_PII_DETECTED"

    def test_accepts_manifest_bound_initial_candidate_pii_scope(
        self, tmp_path: Path
    ) -> None:
        manifest, placements, config = _write_sealed_fixture(tmp_path)
        manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
        required_path = (
            "01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/10_ACTUEL_CONFIRME/"
            "MATHS/doc.pdf"
        )
        evidence = _pii_evidence(manifest_sha256)
        evidence["summary"].update(
            {
                "pii_scan_scope": "INITIAL_PRODUCTION_ELIGIBLE_PDFS",
                "pii_scan_required": 1,
                "pii_scan_exempt": 1,
            }
        )
        evidence["required_pdf_path_count"] = 1
        evidence["required_pdf_path_set_digest"] = hashlib.sha256(
            f"{required_path}\n".encode()
        ).hexdigest()
        evidence["results"][0]["physical_object_count"] = 1

        catalog = compile_governed_sealed_catalog(
            manifest,
            placements,
            config,
            _rights_registry(manifest_sha256),
            evidence,
        )

        candidate = catalog.object_by_path(required_path)
        assert candidate is not None
        assert candidate.gate_statuses["pii"] == "PASS"
        assert candidate.gate_statuses["authority"] == "BLOCKED_NOT_CLEARED"

    def test_rejects_pii_evidence_bound_to_another_manifest(
        self, tmp_path: Path
    ) -> None:
        manifest, placements, config = _write_sealed_fixture(tmp_path)
        manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
        evidence = _pii_evidence(manifest_sha256)
        evidence["corpus_manifest_sha256"] = "0" * 64

        with pytest.raises(ValueError, match="PII evidence manifest SHA256 mismatch"):
            compile_governed_sealed_catalog(
                manifest,
                placements,
                config,
                _rights_registry(manifest_sha256),
                evidence,
            )

    def test_rejects_rights_decision_bound_to_another_manifest(
        self, tmp_path: Path
    ) -> None:
        """P1 PRRT_kwDOTEIbbs6X3cnJ: Human decisions bound to a different manifest are rejected.

        The rights evidence gate validates scope_manifest_sha256 BEFORE the catalog
        compiler does its own check. When the decision's manifest doesn't match,
        the zone becomes UNRESOLVED, and gate_passed=False triggers this error.
        """
        manifest, placements, config = _write_sealed_fixture(tmp_path)
        manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
        registry = _rights_registry(manifest_sha256)
        registry["human_rights_decisions"]["eduscol"][
            "scope_manifest_sha256"
        ] = "0" * 64

        # P1: Decision validation now happens in rights_evidence_gate first
        with pytest.raises(ValueError, match="rights registry has unresolved"):
            compile_governed_sealed_catalog(
                manifest,
                placements,
                config,
                registry,
                _pii_evidence(manifest_sha256),
            )

    def test_rejects_pii_result_for_unknown_content_sha(
        self, tmp_path: Path
    ) -> None:
        manifest, placements, config = _write_sealed_fixture(tmp_path)
        manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
        evidence = _pii_evidence(manifest_sha256)
        evidence["results"][0]["content_sha256"] = "f" * 64

        with pytest.raises(ValueError, match="unknown content SHA256 in PII evidence"):
            compile_governed_sealed_catalog(
                manifest,
                placements,
                config,
                _rights_registry(manifest_sha256),
                evidence,
            )

    def test_rejects_nexus_decision_when_exact_sha_set_digest_drifts(
        self, tmp_path: Path
    ) -> None:
        manifest, placements, config = _write_sealed_fixture(tmp_path)
        manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
        registry = _rights_registry(manifest_sha256)
        registry["human_rights_decisions"]["nexus"] = {
            "decision_type": "HUMAN_ORGANIZATIONAL_RIGHTS_APPROVAL",
            "decision_maker": "Nexus Réussite",
            "decision_date": "2026-08-08",
            "scope_manifest_sha256": manifest_sha256,
            "scope_zones": ["02_NEXUS_DIAGNOSTICS/"],
            "artifact_count": 0,
            "content_sha256_set_digest": "0" * 64,
            "approved_for_production_rag": True,
            "generic_rights_blocker": False,
        }
        registry["source_evidence"]["nexus"] = {
            "zone": "02_NEXUS_DIAGNOSTICS/",
            "rights_status": "CLEARED_BY_HUMAN_DECISION",
            "rights_decision_ref": "nexus",
        }
        registry["summary"]["total_zones"] = 4
        config["rights_evidence_perimeter"].append("02_NEXUS_DIAGNOSTICS/")
        config["zone_rules"].append(
            {
                "zone_prefix": "02_NEXUS_DIAGNOSTICS/",
                "disposition": "REVIEW_REQUIRED",
                "reason": "nexus-test",
            }
        )

        with pytest.raises(ValueError, match="Nexus rights SHA set binding mismatch"):
            compile_governed_sealed_catalog(
                manifest,
                placements,
                config,
                registry,
                _pii_evidence(manifest_sha256),
            )


# ---------------------------------------------------------------------------
# Réconciliation TSV → GNU : le TSV n'est plus jamais une preuve scellée.
#
# Le défaut fermé ici : ``compile_catalog`` calculait un digest sur le TSV
# et le sérialisait sous la clé ``manifest_sha256`` — celle que le gate H2
# lit comme identité du corpus scellé. Un TSV et un GNU divergents
# produisaient donc deux identités sans que rien ne le signale.
# ---------------------------------------------------------------------------


class TestTsvIsNeverASealedManifest:
    def _inventory(self, tmp_path: Path) -> Path:
        path = tmp_path / "import_inventory.tsv"
        path.write_text(
            "sha256\tpath\ttaille_octets\n"
            f"{'a' * 64}\t01_EDUSCOL_OFFICIEL/x.pdf\t10\n",
            encoding="utf-8",
        )
        return path

    def _config(self) -> dict[str, object]:
        return {
            "config_id": "tsv-legacy-test",
            "corpus_total_objects": 1,
            "zone_rules": [
                {
                    "zone_prefix": "01_EDUSCOL_OFFICIEL/",
                    "disposition": "INGEST",
                    "currentness": "actuel",
                }
            ],
        }

    def test_the_report_never_exposes_a_sealed_manifest_digest(
        self, tmp_path: Path
    ) -> None:
        report = compile_catalog(self._inventory(tmp_path), self._config())
        assert not hasattr(report, "manifest_sha256")
        assert not hasattr(report, "manifest_path")
        assert report.import_inventory_sha256

    def test_the_report_declares_itself_non_authoritative(
        self, tmp_path: Path
    ) -> None:
        report = compile_catalog(self._inventory(tmp_path), self._config())
        assert report.legacy_input is True
        assert report.sealed_manifest_authority is False

    def test_the_json_never_carries_the_sealed_key(self, tmp_path: Path) -> None:
        """Un consommateur lit le JSON, pas la docstring : la clé
        ``manifest_sha256`` ne doit pas y apparaître depuis ce chemin."""
        from rag_pedago.imports.corpus_catalog_compiler import _report_to_json

        payload = _report_to_json(
            compile_catalog(self._inventory(tmp_path), self._config()),
            include_objects=False,
        )
        assert "manifest_sha256" not in payload
        assert "manifest_path" not in payload
        assert payload["sealed_manifest_authority"] is False
        assert payload["legacy_input"] is True

    def test_the_tsv_digest_is_not_the_gnu_digest(self, tmp_path: Path) -> None:
        """Preuve de mutation dirigée : si un jour le digest du TSV
        réalimentait ``manifest_sha256``, il désignerait des octets que
        personne n'a scellés."""
        import hashlib

        inventory = self._inventory(tmp_path)
        gnu = tmp_path / "SHA256SUMS.txt"
        gnu.write_text(f"{'a' * 64}  01_EDUSCOL_OFFICIEL/x.pdf\n", encoding="utf-8")

        report = compile_catalog(inventory, self._config())
        gnu_digest = hashlib.sha256(gnu.read_bytes()).hexdigest()
        assert report.import_inventory_sha256 != gnu_digest


class TestSealedPathRemainsGnuBound:
    """Preuves comportementales : on compile un vrai catalogue et on lit
    *quel* digest en ressort. Un test qui inspecterait le texte du code
    prouverait qu'un commentaire existe, pas qu'un mécanisme fonctionne."""

    def test_the_catalog_digest_is_the_digest_of_the_gnu_file_itself(
        self, tmp_path: Path
    ) -> None:
        """L'invariant central : ``catalog.manifest_sha256`` doit être le
        SHA-256 des octets du fichier GNU, et d'aucun autre objet."""
        import hashlib

        manifest, placements, config = _write_sealed_fixture(tmp_path)
        catalog = compile_sealed_catalog(manifest, placements, config)

        expected = hashlib.sha256(manifest.read_bytes()).hexdigest()
        assert catalog.manifest_sha256 == expected

    def test_the_catalog_digest_is_never_the_digest_of_a_tsv(
        self, tmp_path: Path
    ) -> None:
        """Le défaut fermé par ce lot : un TSV d'inventaire décrivant le
        *même* corpus produit un digest différent. Si celui-ci réalimentait
        ``manifest_sha256``, il désignerait des octets que personne n'a
        scellés."""
        import hashlib

        manifest, placements, config = _write_sealed_fixture(tmp_path)
        catalog = compile_sealed_catalog(manifest, placements, config)

        inventory = tmp_path / "import_inventory.tsv"
        inventory.write_text(
            "sha256\tpath\ttaille_octets\n"
            + "".join(
                f"{digest}\t{path}\t10\n"
                for digest, path in (
                    line.split("  ", 1)
                    for line in manifest.read_text().splitlines()
                )
            ),
            encoding="utf-8",
        )
        tsv_digest = hashlib.sha256(inventory.read_bytes()).hexdigest()

        assert catalog.manifest_sha256 != tsv_digest
        assert catalog.manifest_sha256 == hashlib.sha256(
            manifest.read_bytes()
        ).hexdigest()

    def test_a_single_space_manifest_is_refused(self, tmp_path: Path) -> None:
        """GNU ``sha256sum`` sépare par **deux** espaces. Un seul espace
        n'est pas une variante tolérable : c'est un format différent, donc
        un objet dont le parseur ne sait pas ce qu'il contient."""
        manifest, placements, config = _write_sealed_fixture(tmp_path)
        manifest.write_text(
            manifest.read_text().replace("  ", " "), encoding="utf-8"
        )
        config["manifest_sha256"] = compute_file_sha256(manifest)

        with pytest.raises(ValueError):
            compile_sealed_catalog(manifest, placements, config)

    def test_an_uppercase_digest_is_refused(self, tmp_path: Path) -> None:
        manifest, placements, config = _write_sealed_fixture(tmp_path)
        manifest.write_text(manifest.read_text().upper(), encoding="utf-8")
        config["manifest_sha256"] = compute_file_sha256(manifest)

        with pytest.raises(ValueError):
            compile_sealed_catalog(manifest, placements, config)

    def test_a_self_referential_manifest_is_refused(self, tmp_path: Path) -> None:
        """Un fichier ne peut pas contenir son propre digest : la ligne
        serait fausse dès son écriture."""
        manifest, placements, config = _write_sealed_fixture(tmp_path)
        manifest.write_text(
            manifest.read_text() + f"{_sha('c')}  00_ADMIN/SHA256SUMS.txt\n",
            encoding="utf-8",
        )
        config["manifest_sha256"] = compute_file_sha256(manifest)

        with pytest.raises(ValueError, match="must not contain its own path"):
            compile_sealed_catalog(manifest, placements, config)

    def test_a_manifest_modified_after_the_campaign_is_refused(
        self, tmp_path: Path
    ) -> None:
        """Le fichier réel a changé après que la campagne l'a épinglé."""
        manifest, placements, config = _write_sealed_fixture(tmp_path)
        manifest.write_text(
            manifest.read_text() + f"{_sha('d')}  04_COMPLEMENTS_PEDAGOGIQUES/x.pdf\n",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="manifest SHA256 mismatch"):
            compile_sealed_catalog(manifest, placements, config)

    def test_a_nominal_verified_tree_compiles(self, tmp_path: Path) -> None:
        """Réussite nominale : le chemin de production accepte un arbre
        vérifié et publie l'identité attendue."""
        manifest, placements, config = _write_sealed_fixture(tmp_path)
        catalog = compile_sealed_catalog(manifest, placements, config)

        assert catalog.verification_passed is True
        assert catalog.manifest_entries == 3
        assert catalog.manifest_sha256 == config["manifest_sha256"]

    def test_the_generator_and_the_compiler_agree_on_the_same_tree(
        self, tmp_path: Path
    ) -> None:
        """Preuve de bout en bout que les deux moitiés se rejoignent :
        ``generate_sealed_manifest`` écrit le fichier, ``compile_sealed_catalog``
        le relit, et les digests coïncident. C'est la seule façon de
        prouver qu'il n'existe pas deux formats en circulation."""
        from rag_pedago.governance.sealed_corpus import generate_sealed_manifest

        root = tmp_path / "corpus"
        (root / "01_EDUSCOL_OFFICIEL").mkdir(parents=True)
        (root / "01_EDUSCOL_OFFICIEL" / "doc.pdf").write_bytes(b"%PDF-1.4 test")

        generated = generate_sealed_manifest(root)
        manifest_file = tmp_path / "SHA256SUMS.txt"
        manifest_file.write_bytes(generated.content)

        assert compute_file_sha256(manifest_file) == generated.manifest_sha256
        parsed = _parse_sealed_manifest(manifest_file)
        assert [(d, p) for d, p in parsed] == list(generated.entries)
