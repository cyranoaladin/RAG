"""Cibles unitaires étroites de la matrice de mutations H2-B."""
from __future__ import annotations

from pathlib import Path

from rag_pedago.imports.artifact_placement_model import (
    ContentArtifact,
    Disposition,
    PhysicalCorpusObject,
    SealedCorpusCatalog,
)
from rag_pedago.imports.corpus_catalog_compiler import (
    _apply_mandatory_ingest_gates,
    _determine_disposition,
    load_routing_config,
)
from rag_pedago.imports.currentness_gate import Currentness, classify_document

CONFIG = Path(__file__).resolve().parents[1] / "configs" / "corpus_zone_routing.yml"


def test_mut_h2b_01_rights_guard_blocks_uncleared_ingest() -> None:
    disposition, _reason, gates = _apply_mandatory_ingest_gates(
        Disposition.INGEST,
        "a" * 64,
        rights_cleared_sha256=set(),
        pii_cleared_sha256={"a" * 64},
        pii_quarantined_sha256=set(),
        authority_cleared_sha256={"a" * 64},
    )
    assert gates["rights"] == "BLOCKED_NOT_CLEARED", (
        "MUT-H2B-01 rights guard was neutralized"
    )
    assert disposition is Disposition.REVIEW_REQUIRED


def test_mut_h2b_02_pii_guard_quarantines_detected_signal() -> None:
    disposition, _reason, gates = _apply_mandatory_ingest_gates(
        Disposition.INGEST,
        "a" * 64,
        rights_cleared_sha256={"a" * 64},
        pii_cleared_sha256={"a" * 64},
        pii_quarantined_sha256={"a" * 64},
        authority_cleared_sha256={"a" * 64},
    )
    assert gates["pii"] == "BLOCKED_PII_DETECTED", (
        "MUT-H2B-02 PII guard was neutralized"
    )
    assert disposition is Disposition.QUARANTINE


def test_mut_h2b_03_currentness_guard_denies_non_current_ingest() -> None:
    import yaml

    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    result = classify_document(
        "a" * 64,
        "01_EDUSCOL_OFFICIEL/LYCEE/80_A_VERIFIER/document.pdf",
        config,
    )
    assert result.currentness is Currentness.A_VERIFIER
    assert result.ingest_eligible is False, (
        "MUT-H2B-03 currentness guard was neutralized"
    )


def test_mut_h2b_04_exclusion_guard_keeps_admin_out() -> None:
    disposition, *_ = _determine_disposition(
        "00_ADMIN/BUILD_INFO.json", load_routing_config(CONFIG)
    )
    assert disposition is Disposition.EXCLUDE, (
        "MUT-H2B-04 exclusion guard was neutralized"
    )


def test_mut_h2b_05_unsupported_guard_keeps_ggb_out() -> None:
    disposition, *_ = _determine_disposition(
        "03_RESSOURCES_INTERACTIVES/figure.ggb", load_routing_config(CONFIG)
    )
    assert disposition is Disposition.UNSUPPORTED, (
        "MUT-H2B-05 unsupported-format guard was neutralized"
    )


def test_mut_h2b_12_single_disposition_sum_guard_detects_corruption() -> None:
    class CorruptedCountsCatalog(SealedCorpusCatalog):
        @property
        def disposition_counts(self) -> dict[str, int]:
            return {item.value: 0 for item in Disposition}

    manifest_self = PhysicalCorpusObject(
        content_sha256="a" * 64,
        path="00_ADMIN/SHA256SUMS.txt",
        base_disposition=Disposition.EXCLUDE,
        disposition=Disposition.EXCLUDE,
        disposition_reason="MANIFEST_SELF_OBJECT",
        zone="00_ADMIN/",
        currentness=None,
        rights_category_candidate=None,
        is_manifest_self=True,
    )
    catalog = CorruptedCountsCatalog(
        config_id="mutation-target",
        manifest_path="SHA256SUMS.txt",
        manifest_sha256="a" * 64,
        placement_catalog_path="catalogue.tsv",
        placement_catalog_sha256="b" * 64,
        compiled_at="2026-08-09T00:00:00Z",
        manifest_entries=0,
        physical_objects=[manifest_self],
        artifacts={
            "a" * 64: ContentArtifact(
                sha256="a" * 64,
                physical_objects=[manifest_self],
            )
        },
    )

    catalog.verify()

    assert "disposition sum does not equal physical object count" in catalog.verification_errors, (
        "MUT-H2B-12 single-disposition sum guard was neutralized"
    )
