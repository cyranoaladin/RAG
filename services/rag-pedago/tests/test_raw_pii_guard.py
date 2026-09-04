"""Garde « aucune matière brute dans un artefact de gouvernance » (ADR-0047).

**Le piège que ce module doit éviter.** Un artefact de gouvernance est fait
d'empreintes : SHA-256 de contenu, de politique, de scanner, de paquet de
revue, SHA-1 de blob Git. Un digest hexadécimal contient, statistiquement,
des suites de chiffres — et une suite de dix chiffres se lit comme un numéro
de téléphone français. Scanner un tel artefact sans précaution produit des
faux positifs qui font croire à une fuite.

**Mais neutraliser trop est pire que ne pas neutraliser.** Si l'on efface
« tout ce qui ressemble à de l'hexadécimal », alors `0612345678` — dix
chiffres, donc dix caractères de l'alphabet hexadécimal — disparaît aussi, et
la garde devient un angle mort qui certifie l'absence de ce qu'elle a
elle-même effacé.

La règle tenue ici est donc étroite : on ne neutralise qu'un **token de digest
complet et bien délimité** (64 hex, ou 40 hex pour un blob Git), éventuellement
préfixé `sha256:`. Ni 63, ni 65, ni une courte chaîne hexadécimale.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rag_pedago.imports.raw_pii_guard import (
    find_raw_pii,
    neutralise_digest_tokens,
)

SHA_WITH_DIGIT_RUN = "b418fc211fa20174e72117826550375b0387715203d38cd8f99588ee8e10dc42"
SHA_WITH_DIGIT_RUN_2 = "c21dd6166d8fe164ed0622989644b38851809b23e9a0176f4c7d8e2b1a3f5069"
BLOB_SHA1 = "684e09d015ff7c53e1ee315977ffe0cb476bda37"


class TestNeutralisationIsNarrow:
    """Ce qui est neutralisé, et surtout ce qui ne l'est pas."""

    def test_full_sha256_token_is_neutralised(self) -> None:
        assert SHA_WITH_DIGIT_RUN not in neutralise_digest_tokens(SHA_WITH_DIGIT_RUN)

    def test_neutralisation_preserves_length(self) -> None:
        """Les offsets restent lisibles : un masque de même longueur."""
        text = f'"sha": "{SHA_WITH_DIGIT_RUN}",'
        assert len(neutralise_digest_tokens(text)) == len(text)

    def test_prefixed_sha256_token_is_neutralised(self) -> None:
        masked = neutralise_digest_tokens(f"sha256:{SHA_WITH_DIGIT_RUN}")
        assert SHA_WITH_DIGIT_RUN not in masked

    def test_git_blob_sha1_token_is_neutralised(self) -> None:
        assert BLOB_SHA1 not in neutralise_digest_tokens(BLOB_SHA1)

    @pytest.mark.parametrize("length", [39, 41, 63, 65])
    def test_near_miss_hex_runs_are_never_neutralised(self, length: int) -> None:
        """39, 41, 63, 65 : ce ne sont pas des digests, on n'y touche pas.

        Un masquage « à peu près » laisserait passer une matière brute
        adjacente à un digest tronqué."""
        run = "a1b2c3d4e5" * 10
        run = run[:length]
        assert neutralise_digest_tokens(run) == run

    @pytest.mark.parametrize("token", ["1234567890", "abcdef1234", "0612345678", "deadbeef"])
    def test_short_hex_alphabet_strings_are_never_neutralised(self, token: str) -> None:
        """Appartenir à l'alphabet hexadécimal n'est pas être un digest."""
        assert neutralise_digest_tokens(token) == token

    def test_a_digest_does_not_swallow_its_neighbours(self) -> None:
        text = f"contact: 0612345678 sha={SHA_WITH_DIGIT_RUN} fin"
        masked = neutralise_digest_tokens(text)
        assert "0612345678" in masked
        assert SHA_WITH_DIGIT_RUN not in masked


class TestFindRawPii:
    """Le verdict, sur du texte plutôt que sur des empreintes."""

    def test_digest_with_internal_digit_run_yields_no_finding(self) -> None:
        assert find_raw_pii(SHA_WITH_DIGIT_RUN) == []
        assert find_raw_pii(SHA_WITH_DIGIT_RUN_2) == []

    def test_isolated_phone_number_yields_a_finding(self) -> None:
        findings = find_raw_pii("0612345678")
        assert [f.pattern_id for f in findings] == ["phone_french"]

    def test_phone_number_in_a_sentence_yields_a_finding(self) -> None:
        findings = find_raw_pii("contact: 0612345678")
        assert any(f.pattern_id == "phone_french" for f in findings)

    def test_phone_number_next_to_a_digest_still_yields_a_finding(self) -> None:
        """Le cas qui aurait rendu la garde aveugle."""
        text = f'{{"sha": "{SHA_WITH_DIGIT_RUN}", "note": "appeler le 0612345678"}}'
        findings = find_raw_pii(text)
        assert [f.pattern_id for f in findings] == ["phone_french"]

    def test_email_address_yields_a_finding(self) -> None:
        findings = find_raw_pii("ecrire a jean.dupont@example.org")
        assert any(f.pattern_id == "email_address" for f in findings)

    def test_findings_never_carry_the_matched_material(self) -> None:
        """La garde ne recopie pas ce qu'elle dénonce : elle en rend
        l'empreinte, la classe et la position. Sinon son propre rapport
        deviendrait la fuite qu'elle cherchait."""
        findings = find_raw_pii("contact: 0612345678")
        assert findings
        for finding in findings:
            assert "0612345678" not in repr(finding)
            assert len(finding.match_sha256) == 64


class TestGovernanceArtifactsAreClean:
    """La mesure réelle, sur les artefacts scellés du candidat."""

    ROOT = Path(__file__).resolve().parents[3]

    @pytest.mark.parametrize(
        "relative",
        [
            "governance/pii-review-decisions/pii-review-2026-09-03-final.json",
            "governance/pii-review-bindings/pii-review-2026-09-03-final.json",
            "docs/reports/evidence-index/pii_review_index_20260903.json",
        ],
    )
    def test_sealed_artifact_carries_no_raw_pii(self, relative: str) -> None:
        findings = find_raw_pii((self.ROOT / relative).read_text(encoding="utf-8"))
        assert findings == [], f"{relative}: {[f.pattern_id for f in findings]}"
