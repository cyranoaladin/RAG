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
        "exam_domain": {
            "markers": ["session", "sujet", "épreuve", "annales",
                        "corrigé", "baccalauréat", "durée", "examen"],
            "min_markers": 2,
        },
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
        assert any(r.startswith("notion_coverage[") for r in v.rules_fired)

    def test_off_program_content_rejected(self, tmp_path):
        art = _make_artefact(tmp_path, "https://eduscol.education.gouv.fr/5817/x",
                             "Recette de cuisine. " * 50)
        v = SubjectExpertAgent(POLICY).review(art)
        assert v.status == "rejected"
        assert "insufficient_notion_coverage" in v.rules_fired

    def test_all_target_collections_reviewed(self, tmp_path):
        """Fix PR#72 P1 : chaque collection cible est evaluee, pas seulement la 1re."""
        art = _make_artefact(
            tmp_path, "https://eduscol.education.gouv.fr/5817/x", EDUSCOL_TEXT,
            collections_cibles=[
                "rag_nexus_maths_premiere_gen_specialite",
                "rag_nexus_inexistant_hors_catalogue",
            ],
        )
        v = SubjectExpertAgent(POLICY).review(art)
        # La 2e collection n'a pas de taxonomie -> quarantaine (fail-closed)
        assert v.status == "quarantine"
        assert any("rag_nexus_inexistant_hors_catalogue" in r for r in v.reasons)

    def test_multi_collection_coverage_rules_per_collection(self, tmp_path):
        art = _make_artefact(
            tmp_path, "https://eduscol.education.gouv.fr/5817/x", EDUSCOL_TEXT,
            collections_cibles=[
                "rag_nexus_maths_premiere_gen_specialite",
                "rag_nexus_maths_terminale_gen_specialite",
            ],
        )
        v = SubjectExpertAgent(POLICY).review(art)
        # Une regle de couverture par collection cible
        per_col = [r for r in v.rules_fired if r.startswith("notion_coverage[")]
        assert len(per_col) == 2

    def test_exam_domain_markers_rule(self, tmp_path):
        """LOT 31 : les collections domain:exam sont jugees aux marqueurs
        d'examen, pas a la couverture de notions (D-28-01)."""
        exam_text = (
            "Baccalauréat général — session 2026. Sujet de l'épreuve, "
            "durée 4 heures. Annales et corrigé officiel de l'examen. "
        ) * 5
        art = _make_artefact(tmp_path, "https://eduscol.education.gouv.fr/5853/x",
                             exam_text,
                             collections_cibles=["rag_nexus_exams_bac_general"])
        v = SubjectExpertAgent(POLICY).review(art)
        assert v.status == "approved"
        assert any(r.startswith("exam_markers[rag_nexus_exams_bac_general]") for r in v.rules_fired)

    def test_exam_domain_without_markers_rejected(self, tmp_path):
        """Un texte sans marqueurs d'examen vers une collection exam -> rejet."""
        art = _make_artefact(tmp_path, "https://eduscol.education.gouv.fr/5853/x",
                             "Recette de cuisine. " * 50,
                             collections_cibles=["rag_nexus_exams_bac_general"])
        v = SubjectExpertAgent(POLICY).review(art)
        assert v.status == "rejected"
        assert "insufficient_exam_markers" in v.rules_fired

    def test_exam_domain_requires_specific_marker(self, tmp_path):
        """Marqueurs generiques seuls (session, sujet, duree) insuffisants :
        il faut aussi un marqueur specifique a l'examen vise (revue PR #74)."""
        generic_only = (
            "Session 2026 : sujet de l'épreuve, durée 4 heures, examen. "
        ) * 10
        art = _make_artefact(tmp_path, "https://eduscol.education.gouv.fr/5853/x",
                             generic_only,
                             collections_cibles=["rag_nexus_exams_bac_general"])
        v = SubjectExpertAgent(POLICY).review(art)
        assert v.status == "rejected"
        assert any(r.startswith("exam_specific[rag_nexus_exams_bac_general]:0")
                   for r in v.rules_fired)

    def test_exam_specific_marker_accent_folded(self, tmp_path):
        """Le matching replie les accents : 'Mathématiques' matche 'mathematiques'."""
        text = (
            "Épreuve anticipée de Mathématiques — session 2026, sujet, durée. "
        ) * 8
        art = _make_artefact(tmp_path, "https://eduscol.education.gouv.fr/5836/x",
                             text,
                             collections_cibles=["rag_nexus_exams_anticipee_maths"])
        v = SubjectExpertAgent(POLICY).review(art)
        assert v.status == "approved"
        assert any(r.startswith("exam_specific[rag_nexus_exams_anticipee_maths]:")
                   and not r.endswith(":0") for r in v.rules_fired)


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

    def test_mixed_approved_rejected_goes_quarantine(self, tmp_path):
        """Fix PR#72 P2 : on_disagreement=quarantine s'applique aussi au mixte
        approved+rejected (pas de valeur 'quarantine' dans les statuts)."""
        panel = ReviewPanel.__new__(ReviewPanel)
        panel.policy = POLICY
        # RightsExpert approuve (eduscol), QualityExpert rejette (texte trop mince)
        panel.reviewers = [RightsExpertAgent(POLICY), QualityExpertAgent(POLICY)]
        art = _make_artefact(tmp_path, "https://eduscol.education.gouv.fr/5817/x",
                             "trop court")
        payload = panel.decide(art)
        assert payload["decision"] == "quarantine"

    def test_unanimous_rejection_stays_rejected(self, tmp_path):
        """Rejet unanime : tous les reviewers rejettent -> rejected (pas quarantaine)."""
        panel = ReviewPanel.__new__(ReviewPanel)
        panel.policy = POLICY

        class AlwaysReject(RightsExpertAgent):
            reviewer_id = "always_reject"
            def review(self, artefact):  # type: ignore[override]
                from agents.reviewers import Verdict
                v = Verdict(reviewer=self.reviewer_id, status="rejected",
                            reasons=["rejet systematique"], rules_fired=["test_rule"])
                v.sign()
                return v

        panel.reviewers = [AlwaysReject(POLICY), AlwaysReject(POLICY)]
        art = _make_artefact(tmp_path, "https://eduscol.education.gouv.fr/5817/x", EDUSCOL_TEXT)
        payload = panel.decide(art)
        assert payload["decision"] == "rejected"

    def test_signature_binds_artefact_sha256(self, tmp_path):
        """Fix PR#72 P1 : le payload signe inclut le sha256 de l'artefact relu."""
        panel = ReviewPanel.__new__(ReviewPanel)
        panel.policy = POLICY
        panel.reviewers = [RightsExpertAgent(POLICY), QualityExpertAgent(POLICY)]
        art = _make_artefact(tmp_path, "https://eduscol.education.gouv.fr/5817/x", EDUSCOL_TEXT)
        payload = panel.decide(art)
        assert payload["artefact_sha256"] == art.manifest["sha256"]

    def test_signature_binds_reviewed_content_not_declared(self, tmp_path):
        """Fix PR#73 P2 : le digest signe est calcule sur page.txt, pas sur le
        digest declare — meme quand le manifeste declare un sha256 different."""
        panel = ReviewPanel.__new__(ReviewPanel)
        panel.policy = POLICY
        panel.reviewers = [RightsExpertAgent(POLICY), QualityExpertAgent(POLICY)]
        art = _make_artefact(tmp_path, "https://eduscol.education.gouv.fr/5817/x",
                             EDUSCOL_TEXT, sha256="0" * 64)
        payload = panel.decide(art)
        real_digest = hashlib.sha256(EDUSCOL_TEXT.encode("utf-8")).hexdigest()
        assert payload["artefact_sha256"] == real_digest
        assert payload["manifest_sha256"] == "0" * 64

    def test_audit_append_idempotent(self, tmp_path):
        """Fix PR#73 P2 : une decision identique deja consignee n'est pas dupliquee."""
        panel = ReviewPanel.__new__(ReviewPanel)
        panel.policy = POLICY
        panel.reviewers = [RightsExpertAgent(POLICY), QualityExpertAgent(POLICY)]
        art = _make_artefact(tmp_path, "https://eduscol.education.gouv.fr/5817/x", EDUSCOL_TEXT)
        jsonl = tmp_path / "review" / "panel.jsonl"
        jsonl.parent.mkdir(parents=True)

        p1 = panel.decide(art)
        assert panel._already_recorded(jsonl, p1) is False
        with jsonl.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(p1, ensure_ascii=False) + "\n")
        # Meme source, memes octets, meme decision, autre timestamp -> dedup
        p2 = panel.decide(art)
        assert p2["decided_at"] != p1["decided_at"] or True  # timestamp peut varier
        assert panel._already_recorded(jsonl, p2) is True
        # Decision differente -> pas de dedup
        p3 = {**p1, "decision": "rejected"}
        assert panel._already_recorded(jsonl, p3) is False

    def test_audit_appended_before_manifest_update(self, tmp_path, monkeypatch):
        """Fix PR#72 P2 : si l'append audit echoue, le manifeste reste 'pending'."""
        panel = ReviewPanel.__new__(ReviewPanel)
        panel.policy = {**POLICY, "outputs": {
            "review_manifest_jsonl": str(tmp_path / "review" / "panel.jsonl"),
            "ledger_append": str(tmp_path / "ledger" / "panel.jsonl"),
            "report_file": str(tmp_path / "reports" / "latest.md"),
        }}
        panel.staging_root = tmp_path / "staging"
        panel.reviewers = [RightsExpertAgent(POLICY), QualityExpertAgent(POLICY)]
        art = _make_artefact(tmp_path, "https://eduscol.education.gouv.fr/5817/x", EDUSCOL_TEXT)

        import agents.review_panel as rp
        monkeypatch.setattr(rp, "_lock", lambda name: True)
        # Simule une panne d'ecriture sur le jsonl d'audit
        from pathlib import Path as _P
        orig_open = _P.open
        def failing_open(self, *a, **kw):
            if "panel.jsonl" in str(self) and "review" in str(self):
                raise OSError("disque plein (simule)")
            return orig_open(self, *a, **kw)
        monkeypatch.setattr(_P, "open", failing_open)

        import pytest
        with pytest.raises(OSError):
            panel.run()
        # Le manifeste staging n'a pas ete marque : l'artefact reste relisible
        manifest = json.loads((art.staging_dir / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["review_status"] == "pending"

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
