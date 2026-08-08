"""Tests for PII scanner — H2-B."""
from pathlib import Path

from rag_pedago.imports.pii_scanner import (
    DEFAULT_PII_PATTERNS,
    extract_context,
    is_allowlisted,
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
