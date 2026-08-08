"""Tests for PII scanner — H2-B."""
import json
from pathlib import Path

from rag_pedago.imports.pii_scanner import (
    DEFAULT_PII_PATTERNS,
    PIIMatch,
    PIIScanReport,
    PIIScanResult,
    extract_context,
    is_allowlisted,
    report_to_dict,
    result_to_dict,
    result_to_dict_sanitized,
    scan_pdf,
    scan_text_for_pii,
)


class TestPIIPatternMatching:
    """Test PII pattern detection."""

    def test_french_ssn_detected(self) -> None:
        """French social security numbers are detected."""
        text = "Le numero est 1 85 12 75 123 456 78 pour ce dossier."
        matches = scan_text_for_pii(text, DEFAULT_PII_PATTERNS)
        pattern_ids = [m.pattern_id for m in matches]
        assert "french_ssn" in pattern_ids

    def test_email_detected(self) -> None:
        """Email addresses are detected."""
        text = "Contactez-nous a jean.martin@gmail.com pour plus d'informations."
        matches = scan_text_for_pii(text, DEFAULT_PII_PATTERNS)
        pattern_ids = [m.pattern_id for m in matches]
        assert "email_address" in pattern_ids

    def test_french_phone_detected(self) -> None:
        """French phone numbers are detected."""
        text = "Appelez le 06 12 34 56 78 ou le +33 1 23 45 67 89."
        matches = scan_text_for_pii(text, DEFAULT_PII_PATTERNS)
        pattern_ids = [m.pattern_id for m in matches]
        assert "phone_french" in pattern_ids

    def test_iban_detected(self) -> None:
        """French IBAN numbers are detected."""
        text = "Virement sur FR76 1234 5678 9012 3456 7890 123."
        matches = scan_text_for_pii(text, DEFAULT_PII_PATTERNS)
        pattern_ids = [m.pattern_id for m in matches]
        assert "iban_french" in pattern_ids

    def test_student_name_pattern_detected(self) -> None:
        """Student name indicators are detected."""
        text = "Nom: Martin\nPrenom: Jean"
        matches = scan_text_for_pii(text, DEFAULT_PII_PATTERNS)
        pattern_ids = [m.pattern_id for m in matches]
        assert "student_name_pattern" in pattern_ids

    def test_date_of_birth_detected(self) -> None:
        """Date of birth with context is detected."""
        text = "Date de naissance: 15/03/1995"
        matches = scan_text_for_pii(text, DEFAULT_PII_PATTERNS)
        pattern_ids = [m.pattern_id for m in matches]
        assert "date_of_birth" in pattern_ids

    def test_clean_pedagogical_content(self) -> None:
        """Pedagogical content without PII returns empty."""
        text = """
        Programme de mathematiques - Terminale

        Chapitre 1: Les suites numeriques

        Une suite est une fonction de N vers R.
        Soit (un) une suite definie par:
        - u0 = 1
        - un+1 = 2*un + 3

        Exercice: Calculer u5.
        """
        matches = scan_text_for_pii(text, DEFAULT_PII_PATTERNS)
        assert len(matches) == 0


class TestAllowlist:
    """Test allowlist for pedagogical examples."""

    def test_example_email_allowlisted(self) -> None:
        """Example email addresses are allowlisted."""
        assert is_allowlisted("jean.dupont@example.com")
        assert is_allowlisted("exemple@education.fr")

    def test_fill_in_blank_allowlisted(self) -> None:
        """Fill-in-the-blank forms are allowlisted."""
        assert is_allowlisted("Nom: ...........")

    def test_real_email_not_allowlisted(self) -> None:
        """Real email addresses are not allowlisted."""
        assert not is_allowlisted("jean.martin@gmail.com")
        assert not is_allowlisted("professeur@lycee-victor-hugo.fr")


class TestContextExtraction:
    """Test context extraction around matches."""

    def test_context_extracted_correctly(self) -> None:
        """Context includes surrounding text."""
        text = "Avant le numero 06 12 34 56 78 et apres le texte."
        context = extract_context(text, 17, 31, context_chars=10)
        assert "06 12 34 56 78" in context
        assert len(context) < len(text)

    def test_context_handles_boundaries(self) -> None:
        """Context handles text boundaries gracefully."""
        text = "06 12 34 56 78"
        context = extract_context(text, 0, 14, context_chars=50)
        assert context == text


class TestPDFScanning:
    """Test PDF scanning functionality."""

    def test_scan_nonexistent_pdf_returns_error(self) -> None:
        """Scanning non-existent PDF returns extraction error."""
        result = scan_pdf(Path("/nonexistent/file.pdf"))
        assert result.extraction_error is not None
        assert result.pii_detected is False
        assert result.pages_scanned == 0


class TestMutationTests:
    """H2-B mutation tests — prove patterns are non-vacuous."""

    def test_mut_pii_01_ssn_pattern_not_vacuous(self) -> None:
        """MUT-H2B-PII-01: SSN pattern matches real SSN format."""
        # Real format: 1 85 12 75 123 456 78
        text = "Numero: 1 85 12 75 123 456 78"
        matches = scan_text_for_pii(text, DEFAULT_PII_PATTERNS)
        assert any(m.pattern_id == "french_ssn" for m in matches), \
            "SSN pattern must match valid SSN format"

    def test_mut_pii_02_email_pattern_not_vacuous(self) -> None:
        """MUT-H2B-PII-02: Email pattern matches real email format."""
        text = "Email: etudiant.dupont@education.gouv.fr"
        matches = scan_text_for_pii(text, DEFAULT_PII_PATTERNS)
        assert any(m.pattern_id == "email_address" for m in matches), \
            "Email pattern must match valid email format"

    def test_mut_pii_03_phone_pattern_not_vacuous(self) -> None:
        """MUT-H2B-PII-03: Phone pattern matches real phone format."""
        text = "Tel: 01 23 45 67 89"
        matches = scan_text_for_pii(text, DEFAULT_PII_PATTERNS)
        assert any(m.pattern_id == "phone_french" for m in matches), \
            "Phone pattern must match valid phone format"

    def test_mut_pii_04_allowlist_prevents_false_positives(self) -> None:
        """MUT-H2B-PII-04: Allowlist filters example emails."""
        text = "Exemple: jean.dupont@example.com"
        matches = scan_text_for_pii(text, DEFAULT_PII_PATTERNS)
        # Should NOT match because it's allowlisted
        assert not any(m.match_text == "jean.dupont@example.com" for m in matches), \
            "Allowlist must filter example emails"

    def test_mut_pii_05_clean_content_no_false_positives(self) -> None:
        """MUT-H2B-PII-05: Clean pedagogical content has no matches."""
        text = """
        Theoreme de Pythagore

        Dans un triangle rectangle, le carre de l'hypotenuse
        est egal a la somme des carres des deux autres cotes.

        Si ABC est un triangle rectangle en A, alors:
        BC^2 = AB^2 + AC^2
        """
        matches = scan_text_for_pii(text, DEFAULT_PII_PATTERNS)
        assert len(matches) == 0, \
            "Clean pedagogical content must not trigger false positives"

    def test_mut_pii_06_pattern_severity_assigned(self) -> None:
        """MUT-H2B-PII-06: Patterns have severity levels."""
        for pattern in DEFAULT_PII_PATTERNS:
            assert pattern.severity in ("critical", "high", "medium", "low"), \
                f"Pattern {pattern.pattern_id} must have valid severity"

    def test_mut_pii_07_ssn_pattern_rejects_partial(self) -> None:
        """MUT-H2B-PII-07: SSN pattern rejects partial matches."""
        # Partial SSN should not match
        text = "Code: 1 85 12"  # Only first part
        matches = scan_text_for_pii(text, DEFAULT_PII_PATTERNS)
        assert not any(m.pattern_id == "french_ssn" for m in matches), \
            "Partial SSN must not match"

    def test_mut_pii_08_context_includes_match(self) -> None:
        """MUT-H2B-PII-08: Context always includes the match itself."""
        text = "Le numero est 06 12 34 56 78 pour ce dossier important."
        matches = scan_text_for_pii(text, DEFAULT_PII_PATTERNS)
        for m in matches:
            assert m.match_text in m.context, \
                "Context must include the matched text"


class TestPIISanitization:
    """H2-B CRITICAL: Verify raw PII never appears in external evidence."""

    # Synthetic fake PII for testing - NOT real data
    FAKE_EMAIL = "fake.student.test@fakeuniversity.example.org"
    FAKE_PHONE = "06 98 76 54 32"
    FAKE_ADDRESS = "123 Rue Fictive, 75000 Fakeville"
    FAKE_SSN = "1 99 12 75 999 888 77"
    FAKE_STUDENT_ID = "INE123456789X"

    def _create_result_with_pii(self) -> PIIScanResult:
        """Create a scan result containing fake PII for testing."""
        return PIIScanResult(
            file_path="/test/document.pdf",
            sha256="abc123def456",
            pages_scanned=5,
            characters_scanned=10000,
            pii_detected=True,
            matches=[
                PIIMatch(
                    pattern_id="email_address",
                    description="Email addresses",
                    match_text=self.FAKE_EMAIL,
                    page_number=1,
                    char_offset=100,
                    context=f"Contact: {self.FAKE_EMAIL} for questions",
                ),
                PIIMatch(
                    pattern_id="phone_french",
                    description="French phone numbers",
                    match_text=self.FAKE_PHONE,
                    page_number=2,
                    char_offset=200,
                    context=f"Tel: {self.FAKE_PHONE}",
                ),
            ],
            extraction_error=None,
            scan_duration_ms=500,
        )

    def test_sanitized_result_excludes_match_text(self) -> None:
        """CRITICAL: Sanitized result must NOT contain match_text."""
        result = self._create_result_with_pii()
        sanitized = result_to_dict_sanitized(result)
        serialized = json.dumps(sanitized)

        assert self.FAKE_EMAIL not in serialized, \
            "Sanitized output must NOT contain fake email"
        assert self.FAKE_PHONE not in serialized, \
            "Sanitized output must NOT contain fake phone"

    def test_sanitized_result_excludes_context(self) -> None:
        """CRITICAL: Sanitized result must NOT contain context."""
        result = self._create_result_with_pii()
        sanitized = result_to_dict_sanitized(result)
        serialized = json.dumps(sanitized)

        assert "Contact:" not in serialized, \
            "Sanitized output must NOT contain context"
        assert "Tel:" not in serialized, \
            "Sanitized output must NOT contain context"

    def test_default_result_to_dict_is_sanitized(self) -> None:
        """Default result_to_dict() must use sanitization."""
        result = self._create_result_with_pii()
        output = result_to_dict(result)  # Default sanitize=True
        serialized = json.dumps(output)

        assert self.FAKE_EMAIL not in serialized
        assert self.FAKE_PHONE not in serialized
        assert "match_text" not in serialized
        assert "context" not in serialized

    def test_sanitized_report_excludes_all_pii(self) -> None:
        """CRITICAL: Full report must NOT contain any raw PII."""
        result = self._create_result_with_pii()
        report = PIIScanReport(
            report_id="test_report",
            generated_at="2026-08-08T00:00:00Z",
            policy_version="test_v1",
            total_files=1,
            files_scanned=1,
            files_with_errors=0,
            files_with_pii=1,
            files_clean=0,
            pii_absent_attested=False,
            total_matches=2,
            matches_by_pattern={"email_address": 1, "phone_french": 1},
            results=[result],
        )
        output = report_to_dict(report)  # Default sanitize=True
        serialized = json.dumps(output)

        assert self.FAKE_EMAIL not in serialized, \
            "Report must NOT contain fake email"
        assert self.FAKE_PHONE not in serialized, \
            "Report must NOT contain fake phone"

    def test_sanitized_output_contains_safe_metadata(self) -> None:
        """Sanitized output must still contain safe audit metadata."""
        result = self._create_result_with_pii()
        sanitized = result_to_dict_sanitized(result)

        # Safe metadata that SHOULD be present
        assert sanitized["sha256"] == "abc123def456"
        assert sanitized["pii_detected"] is True
        assert sanitized["signal_count"] == 2
        assert "email_address" in sanitized["signal_classes"]
        assert "phone_french" in sanitized["signal_classes"]
        assert len(sanitized["signals"]) == 2
        assert sanitized["signals"][0]["pattern_id"] == "email_address"
        assert sanitized["signals"][0]["match_length"] > 0

    def test_unsanitized_only_for_internal_use(self) -> None:
        """Unsanitized output is available but flagged for internal use only."""
        result = self._create_result_with_pii()
        # Explicit sanitize=False for internal debugging
        output = result_to_dict(result, sanitize=False)
        serialized = json.dumps(output)

        # This WOULD contain PII - for internal use only
        assert self.FAKE_EMAIL in serialized
        assert "match_text" in serialized
