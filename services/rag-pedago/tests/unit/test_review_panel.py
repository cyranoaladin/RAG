"""Tests unitaires du panel de revue agents (LOT 29 / ADR-0018)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agents.review_panel import ReviewPanel
from agents.reviewers import (
    Artefact,
    QualityExpertAgent,
    RightsExpertAgent,
    SubjectExpertAgent,
)

POLICY = {
    "policy_id": "agent_review_panel_v1",
    "consensus": "unanimous",
    "rights_map": {
        "eduscol.education.gouv.fr": "official_public_administrative",
        "fr.wikipedia.org": "cc_by_sa_4_0",
    },
    "unknown_rights_action": "quarantine",
    "subject_expert": {
        "catalogue": "../rag-engine/configs/rag_collections.yml",
        "taxonomy_root": "taxonomy",
        "min_notion_coverage": 0.05,
        "missing_taxonomy_action": "quarantine",
    },
    "quality_expert": {
        "min_words": 10,
        "max_words": 200000,
        "forbid_patterns": ["just a moment"],
        "require_manifest_fields": ["source_id", "url", "sha256", "collections_cibles"],
        "verify_sha256_integrity": True,
    },
}

EDUSCOL_TEXT = (
    "Suites numériques : modes de génération et variations. "
    "Second degré : forme canonique, équations, signe. "
    "Dérivation : nombre dérivé, fonction dérivée. "
    "Produit scalaire et applications. La loi binomiale. "
) * 10


def _make_artefact(tmp_path: Path, url: str, text: str, **overrides) -> Artefact:
    staging = tmp_path / "staging" / "art1"
    staging.mkdir(parents=True)
    (staging / "page.txt").write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    manifest = {
        "source_id": "test_source",
        "url": url,
        "sha256": digest,
        "matiere": "maths",
        "niveaux": ["premiere"],
        "collections_cibles": ["rag_nexus_maths_premiere_gen_specialite"],
        "rights_default": "official_public_administrative",
        "review_status": "pending",
        **overrides,
    }
    (staging / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return Artefact(staging_dir=staging, manifest=manifest, text=text)


class TestRightsExpertAgent:
    def test_known_provenance_approved(self, tmp_path):
        art = _make_artefact(tmp_path, "https://eduscol.education.gouv.fr/5817/x", EDUSCOL_TEXT)
        v = RightsExpertAgent(POLICY).review(art)
        assert v.status == "approved"
        assert v.signature

    def test_unknown_provenance_hard_quarantine(self, tmp_path):
        art = _make_artefact(tmp_path, "https://example-inconnu.fr/x", EDUSCOL_TEXT,
                             rights_default=None)
        v = RightsExpertAgent(POLICY).review(art)
        assert v.status == "quarantine"
        assert "unknown_rights_action:quarantine" in v.rules_fired

    def test_rights_mismatch_rejected(self, tmp_path):
        art = _make_artefact(tmp_path, "https://fr.wikipedia.org/wiki/X", EDUSCOL_TEXT,
                             rights_default="proprietary")
        v = RightsExpertAgent(POLICY).review(art)
        assert v.status == "rejected"


class TestSubjectExpertAgent:
    def test_coverage_above_threshold(self, tmp_path):
        art = _make_artefact(tmp_path, "https://eduscol.education.gouv.fr/5817/x", EDUSCOL_TEXT)
        v = SubjectExpertAgent(POLICY).review(art)
        # Le texte couvre plusieurs notions de la taxonomie maths 1re spé
        assert v.status in {"approved", "rejected"}
        assert any(r.startswith("notion_coverage:") for r in v.rules_fired)

    def test_off_program_content_rejected(self, tmp_path):
        art = _make_artefact(tmp_path, "https://eduscol.education.gouv.fr/5817/x",
                             "Recette de cuisine. " * 50)
        v = SubjectExpertAgent(POLICY).review(art)
        assert v.status == "rejected"
        assert "insufficient_notion_coverage" in v.rules_fired


class TestQualityExpertAgent:
    def test_integrity_violation_quarantine(self, tmp_path):
        art = _make_artefact(tmp_path, "https://eduscol.education.gouv.fr/5817/x", EDUSCOL_TEXT,
                             sha256="0" * 64)
        v = QualityExpertAgent(POLICY).review(art)
        assert v.status == "quarantine"
        assert "integrity_violation" in v.rules_fired

    def test_waf_challenge_page_quarantine(self, tmp_path):
        art = _make_artefact(tmp_path, "https://eduscol.education.gouv.fr/5817/x",
                             "Just a moment... " * 30)
        v = QualityExpertAgent(POLICY).review(art)
        assert v.status == "quarantine"


class TestPanelConsensus:
    def test_unanimous_approval(self, tmp_path):
        panel = ReviewPanel.__new__(ReviewPanel)
        panel.policy = POLICY
        panel.reviewers = [RightsExpertAgent(POLICY), QualityExpertAgent(POLICY)]
        art = _make_artefact(tmp_path, "https://eduscol.education.gouv.fr/5817/x", EDUSCOL_TEXT)
        payload = panel.decide(art)
        assert payload["decision"] == "approved"
        assert payload["panel_signature"]

    def test_disagreement_goes_quarantine(self, tmp_path):
        panel = ReviewPanel.__new__(ReviewPanel)
        panel.policy = POLICY
        panel.reviewers = [RightsExpertAgent(POLICY), QualityExpertAgent(POLICY)]
        art = _make_artefact(tmp_path, "https://example-inconnu.fr/x", EDUSCOL_TEXT,
                             rights_default=None)
        payload = panel.decide(art)
        assert payload["decision"] == "quarantine"

    def test_reviewer_error_fail_closed(self, tmp_path):
        panel = ReviewPanel.__new__(ReviewPanel)
        panel.policy = POLICY

        class BrokenReviewer(RightsExpertAgent):
            reviewer_id = "broken"
            def review(self, artefact):  # type: ignore[override]
                raise RuntimeError("boom")

        panel.reviewers = [BrokenReviewer(POLICY), QualityExpertAgent(POLICY)]
        art = _make_artefact(tmp_path, "https://eduscol.education.gouv.fr/5817/x", EDUSCOL_TEXT)
        payload = panel.decide(art)
        assert payload["decision"] == "quarantine"
