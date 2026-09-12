"""Tests — dérivation d'evidence PII reviewable (Codex P1, PR #98)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rag_pedago.imports.pii_evidence_extract import (
    REVIEWABLE_EVIDENCE_PROTOCOL_VERSION,
    PiiEvidenceExtractionError,
    extract_reviewable_pii_evidence,
)

MANIFEST_SHA = "d" * 64
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _entry(sha: str, **overrides: object) -> dict[str, object]:
    base = {
        "content_sha256": sha,
        "status": "CLEARED",
        "pii_detected": False,
        "pages_scanned": 3,
        "characters_scanned": 1000,
        "signal_count": 0,
        "signal_classes": [],
        "error_code": None,
        # Champs volontairement absents du sous-ensemble projeté — présents
        # ici pour prouver qu'ils ne fuient jamais dans la sortie, pas parce
        # qu'ils contiennent de la vraie PII.
        "signals": [],
    }
    base.update(overrides)
    return base


def _write_source(tmp_path: Path, entries: list[dict[str, object]], **overrides: object) -> Path:
    document = {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "generated_at": "2026-08-10T00:00:00Z",
        "scanner_version": "pii_scanner_h2b_v2",
        "scanner_sha256": "1" * 64,
        "policy_version": "pii_gate_policy_h2b_v1",
        "policy_sha256": "2" * 64,
        "corpus_manifest_sha256": MANIFEST_SHA,
        "results": entries,
    }
    document.update(overrides)
    path = tmp_path / "source_evidence.json"
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestCorrectEvidenceProducesAReviewableExtract:
    def test_green_path(self, tmp_path: Path) -> None:
        source = _write_source(tmp_path, [_entry(SHA_A), _entry(SHA_B)])
        extracted = extract_reviewable_pii_evidence(
            source,
            expected_source_sha256=_sha256(source),
            expected_corpus_manifest_sha256=MANIFEST_SHA,
            required_content_sha256=(SHA_A, SHA_B),
        )
        assert extracted.document["evidence_protocol_version"] == (
            REVIEWABLE_EVIDENCE_PROTOCOL_VERSION
        )
        assert extracted.document["corpus_manifest_sha256"] == MANIFEST_SHA
        assert extracted.document["authorized_content_sha256"] == sorted([SHA_A, SHA_B])
        assert [r["content_sha256"] for r in extracted.document["results"]] == sorted(
            [SHA_A, SHA_B]
        )
        for result in extracted.document["results"]:
            assert set(result.keys()) == {
                "content_sha256",
                "status",
                "pii_detected",
                "pages_scanned",
                "characters_scanned",
                "signal_count",
                "signal_classes",
                "error_code",
            }
        assert extracted.digest == hashlib.sha256(extracted.canonical_bytes).hexdigest()

    def test_deterministic_across_runs(self, tmp_path: Path) -> None:
        source = _write_source(tmp_path, [_entry(SHA_A)])
        first = extract_reviewable_pii_evidence(
            source,
            expected_source_sha256=_sha256(source),
            expected_corpus_manifest_sha256=MANIFEST_SHA,
            required_content_sha256=(SHA_A,),
        )
        second = extract_reviewable_pii_evidence(
            source,
            expected_source_sha256=_sha256(source),
            expected_corpus_manifest_sha256=MANIFEST_SHA,
            required_content_sha256=(SHA_A,),
        )
        assert first.canonical_bytes == second.canonical_bytes
        assert first.digest == second.digest


class TestSensitivityCanaries:
    """Chaque cas prouve un vrai rouge — jamais un test qui ne passerait que
    sur une entrée déjà correcte."""

    def test_wrong_source_digest_is_refused(self, tmp_path: Path) -> None:
        source = _write_source(tmp_path, [_entry(SHA_A)])
        with pytest.raises(PiiEvidenceExtractionError, match="refusing to read"):
            extract_reviewable_pii_evidence(
                source,
                expected_source_sha256="0" * 64,
                expected_corpus_manifest_sha256=MANIFEST_SHA,
                required_content_sha256=(SHA_A,),
            )

    def test_missing_allowed_sha_is_refused(self, tmp_path: Path) -> None:
        source = _write_source(tmp_path, [_entry(SHA_A)])
        with pytest.raises(PiiEvidenceExtractionError, match="never covered"):
            extract_reviewable_pii_evidence(
                source,
                expected_source_sha256=_sha256(source),
                expected_corpus_manifest_sha256=MANIFEST_SHA,
                required_content_sha256=(SHA_A, SHA_B),
            )

    def test_quarantined_status_is_refused(self, tmp_path: Path) -> None:
        source = _write_source(tmp_path, [_entry(SHA_A, status="QUARANTINED_PII")])
        with pytest.raises(PiiEvidenceExtractionError, match="not cleared"):
            extract_reviewable_pii_evidence(
                source,
                expected_source_sha256=_sha256(source),
                expected_corpus_manifest_sha256=MANIFEST_SHA,
                required_content_sha256=(SHA_A,),
            )

    def test_review_required_status_is_refused(self, tmp_path: Path) -> None:
        source = _write_source(
            tmp_path, [_entry(SHA_A, status="REVIEW_REQUIRED_EXTRACTION_FAILED")]
        )
        with pytest.raises(PiiEvidenceExtractionError, match="not cleared"):
            extract_reviewable_pii_evidence(
                source,
                expected_source_sha256=_sha256(source),
                expected_corpus_manifest_sha256=MANIFEST_SHA,
                required_content_sha256=(SHA_A,),
            )

    def test_pii_detected_true_is_refused_even_if_status_says_cleared(
        self, tmp_path: Path
    ) -> None:
        source = _write_source(tmp_path, [_entry(SHA_A, pii_detected=True)])
        with pytest.raises(PiiEvidenceExtractionError, match="pii_detected"):
            extract_reviewable_pii_evidence(
                source,
                expected_source_sha256=_sha256(source),
                expected_corpus_manifest_sha256=MANIFEST_SHA,
                required_content_sha256=(SHA_A,),
            )

    def test_incomplete_scan_is_refused(self, tmp_path: Path) -> None:
        source = _write_source(
            tmp_path, [_entry(SHA_A, error_code="PDF_TEXT_EXTRACTION_EMPTY")]
        )
        with pytest.raises(PiiEvidenceExtractionError, match="incomplete scan"):
            extract_reviewable_pii_evidence(
                source,
                expected_source_sha256=_sha256(source),
                expected_corpus_manifest_sha256=MANIFEST_SHA,
                required_content_sha256=(SHA_A,),
            )

    def test_corpus_manifest_mismatch_is_refused(self, tmp_path: Path) -> None:
        source = _write_source(tmp_path, [_entry(SHA_A)], corpus_manifest_sha256="9" * 64)
        with pytest.raises(PiiEvidenceExtractionError, match="two different corpora"):
            extract_reviewable_pii_evidence(
                source,
                expected_source_sha256=_sha256(source),
                expected_corpus_manifest_sha256=MANIFEST_SHA,
                required_content_sha256=(SHA_A,),
            )

    def test_raw_pii_leak_in_source_never_reaches_output(self, tmp_path: Path) -> None:
        """Défense en profondeur : même si une source amont non conforme
        incluait un jour match_text/context à un niveau non projeté, le
        canari de balayage doit détecter toute clé interdite. Ce test le
        prouve en injectant volontairement une telle clé dans une position
        où un futur refactor pourrait accidentellement l'inclure."""
        entry = _entry(SHA_A)
        entry["match_text"] = "Jean Dupont, 06 12 34 56 78"  # donnée factice de test
        source = _write_source(tmp_path, [entry])
        # Le sous-ensemble projeté n'inclut pas match_text : succès attendu,
        # et on prouve explicitement son absence de la sortie.
        extracted = extract_reviewable_pii_evidence(
            source,
            expected_source_sha256=_sha256(source),
            expected_corpus_manifest_sha256=MANIFEST_SHA,
            required_content_sha256=(SHA_A,),
        )
        assert b"Jean Dupont" not in extracted.canonical_bytes
        assert b"match_text" not in extracted.canonical_bytes

    def test_duplicate_required_sha_is_refused(self, tmp_path: Path) -> None:
        source = _write_source(tmp_path, [_entry(SHA_A)])
        with pytest.raises(PiiEvidenceExtractionError, match="duplicates"):
            extract_reviewable_pii_evidence(
                source,
                expected_source_sha256=_sha256(source),
                expected_corpus_manifest_sha256=MANIFEST_SHA,
                required_content_sha256=(SHA_A, SHA_A),
            )

    def test_empty_required_set_is_refused(self, tmp_path: Path) -> None:
        source = _write_source(tmp_path, [_entry(SHA_A)])
        with pytest.raises(PiiEvidenceExtractionError, match="must not be empty"):
            extract_reviewable_pii_evidence(
                source,
                expected_source_sha256=_sha256(source),
                expected_corpus_manifest_sha256=MANIFEST_SHA,
                required_content_sha256=(),
            )


class TestRealEvidenceFileIntegration:
    """Exerce le module sur les cinq SHA réellement autorisés par PR #98,
    contre le vrai fichier d'evidence externe — pas seulement des fixtures
    synthétiques."""

    REAL_SOURCE = Path.home() / "Documents" / "NEXUS_RAG_H2_EVIDENCE" / (
        "h2f_pii_evidence_review6_20260810.json"
    )
    REAL_SOURCE_SHA256 = "3db37e916250300f0a0d538fd924802f222ce3a8880b595971f3cf4ab2b29b87"
    REAL_MANIFEST_SHA256 = "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
    REAL_FIVE_SHAS = (
        "03f268dc1f2628dbc76c58921ed868624437f06a15432ea055fff844f12aaf91",
        "846962c15217af5cfe7ba40b173e94cb225d2153ffd3131d23b2c60a2b5e9a17",
        "b5ed52b1a4754298f7ecdbc56cb886a438c580ebd04284be0ca878b82e7c62db",
        "e7cf3bdb7a1c3831ccc465d842d8ab0dacb688d565cb35510aee4eac4f2bf5f9",
        "f0dec90cafd512cb754fb71ed33dbf0a48f0e67a166be35b5b16a1daa6dd006d",
    )

    @pytest.mark.skipif(
        not REAL_SOURCE.is_file(),
        reason="real external H2-B PII evidence not present on this machine",
    )
    def test_the_five_authorized_documents_are_cleared_in_the_real_scan(self) -> None:
        extracted = extract_reviewable_pii_evidence(
            self.REAL_SOURCE,
            expected_source_sha256=self.REAL_SOURCE_SHA256,
            expected_corpus_manifest_sha256=self.REAL_MANIFEST_SHA256,
            required_content_sha256=self.REAL_FIVE_SHAS,
        )
        assert len(extracted.document["results"]) == 5
        assert all(r["status"] == "CLEARED" for r in extracted.document["results"])
        assert all(r["pii_detected"] is False for r in extracted.document["results"])
