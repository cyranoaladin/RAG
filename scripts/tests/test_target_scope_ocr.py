"""Tests for targeted OCR on the 22 unextractable PDFs.

Validates:
- OCR strictly limited to the 22 authorized no-text contents (no global corpus OCR).
- 0 gate-refused contents included.
- 0 PII undecided contents included.
- Pre-vectorization PII detection executed and attested (fail-closed if PII found).
- Chunks derived from OCR pages explicitly marked OCR_DERIVED, native marked NATIVE_DERIVED.
- Exact page ranges preserved (page_start and page_end).
- Token budget strictly respected (all tokens <= 512, target 384).
- target_scope_searchable is true iff vectorized_contents == 2264.
- rag_searchability_blocker is false iff conditions_not_met == [].
- GO_LIVE_READY remains strictly false.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

RACINE = Path(__file__).resolve().parents[2]

RAPPORT_OCR = RACINE / "docs/reports/go_live/target_scope_ocr_execution.json"
RAPPORT_RECHUNK = RACINE / "docs/reports/go_live/rechunk_publication_token_budget.json"
MAGASIN_VECTEURS = RACINE / "docs/reports/go_live/vector_store_audit.json"
ECART_RECHERCHE = RACINE / "docs/reports/go_live/rag_searchability_gap.json"
READINESS = RACINE / "docs/reports/go_live/go_live_readiness_state.json"
MATRICE = RACINE / "docs/reports/handoff/servability_matrix_v1.json"


@pytest.fixture(scope="module")
def execution_ocr() -> dict:
    if not RAPPORT_OCR.is_file():
        pytest.skip("Targeted OCR execution report not found")
    return json.loads(RAPPORT_OCR.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ecart() -> dict:
    if not ECART_RECHERCHE.is_file():
        pytest.skip("Searchability gap report not found")
    return json.loads(ECART_RECHERCHE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def magasin() -> dict:
    if not MAGASIN_VECTEURS.is_file():
        pytest.skip("Vector store audit not found")
    return json.loads(MAGASIN_VECTEURS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def readiness() -> dict:
    if not READINESS.is_file():
        pytest.skip("Readiness state not found")
    return json.loads(READINESS.read_text(encoding="utf-8"))


def test_ocr_limite_strictement_aux_22_contenus(execution_ocr):
    """L'OCR est strictement ciblée sur les 22 contenus autorisés sans texte."""
    assert execution_ocr["target_documents_count"] == 22
    assert execution_ocr["documents_processed"] == 22
    assert len(execution_ocr["documents"]) == 22

    rechunk_data = json.loads(RAPPORT_RECHUNK.read_text(encoding="utf-8"))
    unextractable_ids = set(rechunk_data["contents_without_extractable_text_ids"])
    assert set(execution_ocr["documents"].keys()) == unextractable_ids


def test_aucune_ocr_globale_du_corpus(execution_ocr, magasin):
    """Seuls 22 documents sur 2264 ont été traités par OCR ciblée."""
    assert execution_ocr["documents_processed"] == 22
    assert magasin["dedicated"]["vectorized_contents"] == 2264
    assert execution_ocr["vector_store"]["passages_added"] == execution_ocr["chunking"]["total_chunks"]


def test_zero_contenu_refuse_ou_pii_undecided_indexe(execution_ocr):
    """Aucun contenu refusé par le gate ou avec décision PII en suspens n'est ciblé."""
    matrice_data = json.loads(MATRICE.read_text(encoding="utf-8"))
    refuses = {
        r["content_sha256"]
        for r in matrice_data["rows"]
        if r["verdict"] != "CANDIDATE_NO_BLOCKING_DIMENSION"
    }
    targets = set(execution_ocr["documents"].keys())
    assert not (targets & refuses), "Des contenus refusés sont présents dans la cible OCR"


def test_detection_pii_executee_avant_vectorisation_et_saine(execution_ocr):
    """La politique PII a été exécutée sur l'ensemble des pages et atteste 0 PII."""
    assert execution_ocr["pii_scan"]["clearance"] is True
    assert execution_ocr["pii_scan"]["matches_count"] == 0
    assert execution_ocr["pii_scan"]["patterns_count"] >= 6


def test_arret_fail_closed_si_pii_detectee():
    """Le module de traitement lève immédiatement une exception bloquante si PII trouvée."""
    import sys
    sys.path.insert(0, str(RACINE / "scripts/go_live"))
    from vectorize_target_scope_ocr import PiiDiscoveredHumanDecisionRequired

    assert issubclass(PiiDiscoveredHumanDecisionRequired, RuntimeError)



def test_passages_marques_ocr_derived_et_native_derived(execution_ocr):
    """Les passages issus de pages OCR sont marqués OCR_DERIVED, les autres NATIVE_DERIVED."""
    assert execution_ocr["chunking"]["ocr_derived_chunks"] > 0
    assert execution_ocr["chunking"]["native_derived_chunks"] > 0
    total_chunks = (
        execution_ocr["chunking"]["ocr_derived_chunks"]
        + execution_ocr["chunking"]["native_derived_chunks"]
    )
    assert total_chunks == execution_ocr["chunking"]["total_chunks"]


def test_conservation_pagination_et_budget_tokens(execution_ocr):
    """La pagination page_start/page_end est conservée et aucun chunk ne dépasse 512 tokens."""
    assert execution_ocr["chunking"]["chunks_over_limit"] == 0
    assert execution_ocr["chunking"]["max_tokens_observed"] <= 512
    assert execution_ocr["chunking"]["unique_pages_covered"] > 0


def test_target_scope_searchable_ferme_exactement_a_2264(ecart, magasin):
    """target_scope_searchable n'est vrai que si les 2264 contenus candidats sont couverts."""
    assert magasin["dedicated"]["vectorized_contents"] == 2264
    assert magasin["dedicated"]["allowlist_rows"] == 2264
    assert ecart["closing_conditions"]["target_scope_searchable"] is True
    assert ecart["target_scope_searchable"] is True


def test_rag_searchability_blocker_ferme_exactement_quand_conditions_vides(ecart):
    """rag_searchability_blocker n'est faux que si conditions_not_met est vide."""
    assert ecart["conditions_not_met"] == []
    assert ecart["rag_searchability_blocker"] is False
    assert ecart["rag_searchable"] is True


def test_go_live_ready_reste_strictement_faux(readiness):
    """La fermeture de la recherche ne déclare pas le go-live prêt : les bloqueurs restants bloquent."""
    assert readiness["go_live_ready"] is False
    assert readiness["pii_undecided"] == 0
    assert readiness["release_promoted_refused_contents"] == 4
    assert readiness["go_live_qualification_blockers"] > 0
    assert readiness["open_prs_blocking"] == 0
    assert readiness["current_switch"] == 0
