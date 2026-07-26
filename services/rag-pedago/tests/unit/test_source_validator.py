"""Tests unitaires SourceValidator (LOT 31, correctifs PR #74).

Couvre les 4 points Codex :
1. fetch gouverne (browser_governed_fetch, jamais d'appel direct) ;
2. pertinence pedagogique reelle (SubjectExpert sur le contenu) ;
3. droits revalidés sur la provenance finale apres redirection ;
4. ledger append-only contenant chaque verdict signe.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import agents.source_validator as sv
from agents.source_validator import validate_source
from scrapers.fetch import FetchRefusal, FetchResult

EDUSCOL = "https://eduscol.education.gouv.fr/5817/x"

POLICY = {
    "rights_map": {"eduscol.education.gouv.fr": "official_public_administrative"},
    "unknown_rights_action": "quarantine",
    "subject_expert": {
        "catalogue": "../rag-engine/configs/rag_collections.yml",
        "taxonomy_root": "taxonomy",
        "min_notion_coverage": 0.05,
        "missing_taxonomy_action": "quarantine",
        "exam_domain": {"markers": ["session", "sujet", "épreuve"], "min_markers": 2},
    },
    "quality_expert": {"min_words": 200,
                       "forbid_patterns": ["just a moment", "enable javascript"]},
}

# Texte riche en notions de la taxonomie maths 1re spe (cf. test_review_panel)
MATHS_TEXT = (
    "Suites numériques : modes de génération et variations. "
    "Second degré : forme canonique, équations, signe. "
    "Dérivation : nombre dérivé, fonction dérivée. "
    "Produit scalaire et applications. La loi binomiale. "
) * 10

SOURCE = {
    "id": "eduscol_maths_voie_gt",
    "url": EDUSCOL,
    "status": "to_verify",
    "collections_cibles": ["rag_nexus_maths_premiere_gen_specialite"],
}


def _fetch_ok(final_url: str = EDUSCOL, text: str = MATHS_TEXT) -> FetchResult:
    return FetchResult(url=EDUSCOL, status_code=200, content_type="text/html",
                       text=f"<html><body>{text}</body></html>",
                       fetched_at=datetime.now(UTC), final_url=final_url)


class TestGovernedFetch:
    def test_uses_governed_fetcher(self, monkeypatch):
        """Le validateur passe par browser_governed_fetch (whitelist+robots)."""
        calls = []

        def fake_fetch(url):
            calls.append(url)
            return _fetch_ok()

        monkeypatch.setattr(sv, "browser_governed_fetch", fake_fetch)
        v = validate_source(SOURCE, POLICY)
        assert calls == [EDUSCOL]
        assert v["verdict"] == "verified_candidate"

    def test_fetch_refusal_stays_to_verify(self, monkeypatch):
        monkeypatch.setattr(
            sv, "browser_governed_fetch",
            lambda url: FetchRefusal(url=url, reason="blocked by robots.txt"))
        v = validate_source(SOURCE, POLICY)
        assert v["verdict"] == "stays_to_verify"
        assert "fetch_refused" in v["rules_fired"]


class TestRedirectRights:
    def test_redirect_to_unknown_host_fails_closed(self, monkeypatch):
        """Redirection vers une provenance hors rights_map -> stays_to_verify."""
        monkeypatch.setattr(
            sv, "browser_governed_fetch",
            lambda url: _fetch_ok(final_url="https://miroir-pirate.example/x"))
        v = validate_source(SOURCE, POLICY)
        assert v["verdict"] == "stays_to_verify"
        assert "redirect_rights_unresolved" in v["rules_fired"]

    def test_redirect_to_known_host_ok(self, monkeypatch):
        policy = {**POLICY, "rights_map": {
            **POLICY["rights_map"],
            "education.gouv.fr": "official_public_administrative"}}
        monkeypatch.setattr(
            sv, "browser_governed_fetch",
            lambda url: _fetch_ok(final_url="https://education.gouv.fr/x"))
        v = validate_source(SOURCE, policy)
        assert v["verdict"] == "verified_candidate"
        assert "redirect_rights_resolved" in v["rules_fired"]

    def test_redirect_with_different_rights_rejected(self, monkeypatch):
        """Droits differents apres redirection -> stays_to_verify (licence)."""
        policy = {**POLICY, "rights_map": {
            **POLICY["rights_map"],
            "fr.wikipedia.org": "cc_by_sa_4_0"}}
        monkeypatch.setattr(
            sv, "browser_governed_fetch",
            lambda url: _fetch_ok(final_url="https://fr.wikipedia.org/wiki/X"))
        v = validate_source(SOURCE, policy)
        assert v["verdict"] == "stays_to_verify"
        assert "redirect_rights_mismatch" in v["rules_fired"]


class TestPedagogicalRelevance:
    def test_irrelevant_content_rejected(self, monkeypatch):
        """200 mots de contenu hors programme ne suffisent pas."""
        monkeypatch.setattr(sv, "browser_governed_fetch",
                            lambda url: _fetch_ok(text="Recette de cuisine. " * 70))
        v = validate_source(SOURCE, POLICY)
        assert v["verdict"] == "stays_to_verify"
        assert any(r.startswith("subject_expert:") for r in v["rules_fired"])

    def test_relevant_content_approved(self, monkeypatch):
        monkeypatch.setattr(sv, "browser_governed_fetch", lambda url: _fetch_ok())
        v = validate_source(SOURCE, POLICY)
        assert v["verdict"] == "verified_candidate"
        assert "subject_expert:approved" in v["rules_fired"]
        assert v["signature"]


class TestSubstanceAndBinding:
    def test_chrome_words_do_not_count_as_substance(self, monkeypatch):
        """200 mots de navigation ne valident pas une source (chrome exclu)."""
        chrome = "Accueil Menu Rechercher Navigation Footer Mentions. " * 40
        main = "Suites numériques. " * 5  # < 200 mots de contenu principal
        html = f"<html><body><nav>{chrome}</nav><main>{main}</main></body></html>"
        result = FetchResult(url=EDUSCOL, status_code=200,
                             content_type="text/html", text=html,
                             fetched_at=datetime.now(UTC), final_url=EDUSCOL)
        monkeypatch.setattr(sv, "browser_governed_fetch", lambda url: result)
        v = validate_source(SOURCE, POLICY)
        assert v["verdict"] == "stays_to_verify"
        assert "too_thin" in v["rules_fired"]

    def test_payload_binds_content_and_final_url(self, monkeypatch):
        """Le verdict signe reference le digest du contenu et l'URL finale."""
        monkeypatch.setattr(sv, "browser_governed_fetch", lambda url: _fetch_ok())
        v = validate_source(SOURCE, POLICY)
        expected = hashlib.sha256(
            sv._strip_html(_fetch_ok().text).encode("utf-8")).hexdigest()
        assert v["content_sha256"] == expected
        assert v["final_url"] == EDUSCOL
        assert v["final_rights"] == "official_public_administrative"


class TestNetworkLock:
    def test_run_refused_when_network_locked(self, monkeypatch):
        """Kill-switch reseau : aucun fetch si network_allowed n'est pas leve."""
        called = []
        monkeypatch.setattr(sv, "browser_governed_fetch",
                            lambda url: called.append(url) or _fetch_ok())
        monkeypatch.setattr(sv, "_lock", lambda name: False)
        out = sv.run()
        assert out["status"] == "refused"
        assert out["exit_code"] == 1
        assert called == []  # aucune requete reseau emise

    def test_run_allowed_when_network_unlocked(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sv, "_lock", lambda name: True)
        monkeypatch.setattr(sv, "browser_governed_fetch", lambda url: _fetch_ok())
        monkeypatch.setattr(
            sv, "time",
            type("T", (), {"sleep": staticmethod(lambda seconds: None)}))
        src_file = tmp_path / "sources.yml"
        src_file.write_text("sources: []\n", encoding="utf-8")
        monkeypatch.setattr(sv, "SOURCES_PATH", src_file)
        monkeypatch.setattr(sv, "LEDGER_PATH", tmp_path / "l.jsonl")
        monkeypatch.setattr(sv, "REPORT_PATH", tmp_path / "r.md")
        out = sv.run()
        assert out["status"] == "ok"


class TestLedger:
    def test_ledger_contains_signed_verdicts(self, monkeypatch, tmp_path):
        """Chaque verdict signe est consigne dans le ledger append-only."""
        monkeypatch.setattr(sv, "_lock", lambda name: True)
        monkeypatch.setattr(sv, "browser_governed_fetch", lambda url: _fetch_ok())
        monkeypatch.setattr(
            sv, "time",
            type("T", (), {"sleep": staticmethod(lambda seconds: None)}))
        src_file = tmp_path / "sources.yml"
        src_file.write_text(
            "sources:\n  - id: eduscol_maths_voie_gt\n"
            f"    url: {EDUSCOL}\n    status: to_verify\n"
            "    collections_cibles: [rag_nexus_maths_premiere_gen_specialite]\n",
            encoding="utf-8")
        ledger = tmp_path / "ledger.jsonl"
        report = tmp_path / "report.md"
        monkeypatch.setattr(sv, "SOURCES_PATH", src_file)
        monkeypatch.setattr(sv, "LEDGER_PATH", ledger)
        monkeypatch.setattr(sv, "REPORT_PATH", report)
        out = sv.run()
        assert out["verified_candidates"] == ["eduscol_maths_voie_gt"]
        records = [
            json.loads(line)
            for line in ledger.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        verdicts = [r for r in records if r.get("source_id")]
        assert len(verdicts) == 1
        assert verdicts[0]["signature"]
        assert verdicts[0]["verdict"] == "verified_candidate"
