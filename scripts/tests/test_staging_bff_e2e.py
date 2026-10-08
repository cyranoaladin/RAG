"""Contrôles du harnais BFF réel, sans staging ni secrets."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "go_live" / "staging_bff_e2e.py"
ROOT = Path(__file__).resolve().parents[2]


def load_harness():
    assert SCRIPT.is_file(), "harnais BFF réel absent"
    spec = importlib.util.spec_from_file_location("staging_bff_e2e", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hit(collection: str) -> dict:
    content = "b" * 64
    return {
        "chunk_id": "chunk-1",
        "doc_id": content,
        "citation": {
            "source_uri": "https://eduscol.education.fr/document.pdf",
            "source_label": "Document officiel",
            "rights": "official_public_administrative",
            "page": 3,
        },
        "metadata": {
            "collection": collection,
            "review_status": "reviewed",
            "artifact_id": content,
            "content_sha256": content,
        },
    }


def test_teacher_requires_real_cited_content_bound_to_final_manifest():
    harness = load_harness()
    collection = "rag_nexus_maths_terminale_gen_specialite"
    result = harness.assess_positive(200, {"results": [hit(collection)]}, collection, {"b" * 64})
    assert result["results"] == 1
    assert result["citations"] == 1
    assert result["content_sha256"] == ["b" * 64]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"citation": None}, "citation"),
        ({"citation": {"source_uri": "https://eduscol.education.fr/document.pdf", "source_label": "Document officiel", "rights": "officiel_public", "page": None}}, "citation"),
        ({"metadata": {"collection": "rag_nexus_maths_terminale_gen_specialite", "review_status": "reviewed", "content_sha256": None}}, "content"),
        ({"metadata": {"collection": "rag_nexus_maths_terminale_gen_specialite", "review_status": "reviewed", "content_sha256": "c" * 64}}, "content"),
        ({"doc_id": "d" * 64}, "content"),
        ({"metadata": {"collection": "hors_scope", "review_status": "reviewed"}}, "collection"),
        ({"metadata": {"collection": "rag_nexus_maths_terminale_gen_specialite", "review_status": "pending"}}, "review"),
    ],
)
def test_positive_fails_closed_on_missing_identity_scope_or_citation(mutation, reason):
    harness = load_harness()
    collection = "rag_nexus_maths_terminale_gen_specialite"
    candidate = hit(collection)
    candidate.update(mutation)
    with pytest.raises((ValueError, TypeError), match=reason):
        harness.assess_positive(200, {"results": [candidate]}, collection, {"b" * 64})


def test_positive_rejects_empty_or_non_200():
    harness = load_harness()
    collection = "rag_nexus_maths_terminale_gen_specialite"
    for status, payload in ((200, {"results": []}), (503, {"error": "launch_not_ready"})):
        with pytest.raises(ValueError):
            harness.assess_positive(status, payload, collection, {"b" * 64})


def test_student_internal_mode_accepts_only_empty_or_launch_refusal():
    harness = load_harness()
    collection = "rag_nexus_maths_terminale_gen_specialite"
    assert harness.assess_internal_student(503, {"error": "launch_not_ready"}) == "launch_not_ready"
    assert harness.assess_internal_student(200, {"results": []}) == "empty"
    with pytest.raises(ValueError, match="student"):
        harness.assess_internal_student(200, {"results": [hit(collection)]})
    with pytest.raises(ValueError, match="student"):
        harness.assess_internal_student(503, {"error": "service_unavailable"})


def test_cross_scope_must_be_bff_403():
    harness = load_harness()
    assert harness.assess_cross_scope(403, {"error": "forbidden_collection"}) is True
    with pytest.raises(ValueError, match="scope"):
        harness.assess_cross_scope(200, {"results": []})


def test_minted_session_must_have_expected_role_and_scope():
    harness = load_harness()
    claims = {
        "role": "student",
        "scope_id": "libre_terminale_maths_nsi_real_v1",
        "allowed_collections": [
            "rag_nexus_maths_terminale_gen_specialite",
            "rag_nexus_nsi_terminale_specialite",
        ],
    }
    harness.assess_signed_claims(claims, "student", claims["allowed_collections"])
    with pytest.raises(ValueError, match="role"):
        harness.assess_signed_claims(claims, "teacher", claims["allowed_collections"])
    with pytest.raises(ValueError, match="scope"):
        harness.assess_signed_claims({**claims, "scope_id": "unknown"}, "student", claims["allowed_collections"])


def test_release_index_is_bound_to_the_requested_collection():
    harness = load_harness()
    registry = ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json"
    contents = harness.load_release_contents(
        registry,
        "59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6",
        "rag_nexus_nsi_terminale_specialite",
    )
    assert len(contents) == 47


def test_final_release_does_not_contain_the_other_pilot_collection():
    harness = load_harness()
    registry = ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json"
    with pytest.raises(ValueError, match="collection absente"):
        harness.load_release_contents(
            registry,
            "59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6",
            "rag_nexus_maths_terminale_gen_specialite",
        )
