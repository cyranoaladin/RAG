"""Tests du controle de derive vs la preuve versionnee (round 11 PR #74) :
un contenu modifie depuis la validation n'est pas stage sans revalidation."""
from __future__ import annotations

import hashlib

from agents.eduscol_agent import evidence_drift
from scrapers.text_extract import strip_html

HTML = ("<html><body><nav>Menu Navigation</nav><main>"
        "Annales du DNB, sujet de l'epreuve, duree deux heures."
        "</main></body></html>")
URL = "https://eduscol.education.gouv.fr/4536/diplome-national-du-brevet"


def _verdict(content_html: str = HTML, url: str = URL) -> dict:
    return {
        "source_id": "eduscol_dnb",
        "url": url,
        "content_sha256": hashlib.sha256(
            strip_html(content_html).encode("utf-8")).hexdigest(),
        "verdict": "verified_candidate",
    }


class TestEvidenceDrift:
    def test_unchanged_content_passes(self):
        verdicts = {"eduscol_dnb": _verdict()}
        assert evidence_drift("eduscol_dnb", URL, HTML, verdicts) is None

    def test_modified_content_blocked(self):
        verdicts = {"eduscol_dnb": _verdict()}
        modified = HTML.replace("duree deux heures", "duree trois heures")
        drift = evidence_drift("eduscol_dnb", URL, modified, verdicts)
        assert drift is not None
        assert "revalidation requise" in drift

    def test_url_mismatch_blocked(self):
        verdicts = {"eduscol_dnb": _verdict()}
        drift = evidence_drift(
            "eduscol_dnb", "https://eduscol.education.gouv.fr/9999/autre",
            HTML, verdicts)
        assert drift is not None
        assert "url configuree != url validee" in drift

    def test_untracked_source_not_blocked(self):
        """Une source legacy (absente de la preuve) n'est pas controlee."""
        assert evidence_drift("eduscol_maths_voie_gt", URL, HTML, {}) is None

    def test_chrome_changes_ignored(self):
        """Seul le contenu PRINCIPAL compte : un changement de navigation
        (chrome exclu par strip_html) ne declenche pas la derive."""
        verdicts = {"eduscol_dnb": _verdict()}
        chrome_changed = HTML.replace("Menu Navigation",
                                      "Menu Navigation Actualites Meteo")
        assert evidence_drift("eduscol_dnb", URL, chrome_changed, verdicts) is None
