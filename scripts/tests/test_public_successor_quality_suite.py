"""Contrat figé de la golden publique, avant toute mesure du staging final."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/go_live/public_successor_quality_suite.py"
SUITE_PATH = ROOT / "services/rag-engine/tests/fixtures/public_successor_quality_40b.json"


def _module():
    spec = importlib.util.spec_from_file_location("public_successor_quality_suite", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_suite_covers_exact_public_release_and_33_positive_cases() -> None:
    module = _module()
    suite = json.loads(SUITE_PATH.read_text(encoding="utf-8"))
    index = module.validate_suite(ROOT, suite)
    assert len(index) == 11
    assert sum(len(spec["positive"]) for spec in suite["collections"].values()) == 33
    assert all(
        row.get("expected_citation", {}).get("licence_id") == "ETALAB-2.0"
        for spec in suite["collections"].values() for row in spec["positive"]
    )
    assert all(len(spec.get("scope_digest", "")) == 64 for spec in suite["collections"].values())
    assert suite["expected_population"] == {
        "collections": 11, "artifacts": 253, "placements": 377, "chunks": 3975,
    }


@pytest.mark.parametrize("mutation", [
    lambda d: d["thresholds"].__setitem__("expected_source_hits_min", 0),
    lambda d: d["collections"].pop(next(iter(d["collections"]))),
    lambda d: d["collections"]["rag_nexus_nsi_terminale_specialite"]["positive"][0].__setitem__(
        "expected_content_sha256", "0" * 64
    ),
    lambda d: d["collections"]["rag_nexus_nsi_terminale_specialite"]["positive"][0].__setitem__(
        "expected_pages_any", [9999]
    ),
    lambda d: d["collections"]["rag_nexus_nsi_terminale_specialite"]["positive"][1].__setitem__(
        "query", "génétique"
    ),
    lambda d: d["collections"]["rag_nexus_nsi_terminale_specialite"]["positive"][0][
        "expected_citation"
    ].__setitem__("licence_id", "NONE"),
    lambda d: d.__setitem__("release_manifest_sha256", "0" * 64),
    lambda d: d["collections"]["rag_nexus_nsi_terminale_specialite"].__setitem__(
        "teacher_expected_http", 200
    ),
    lambda d: d["collections"]["rag_nexus_nsi_terminale_specialite"].__setitem__(
        "scope_digest", "b" * 64
    ),
    lambda d: d["collections"]["rag_nexus_nsi_terminale_specialite"]["positive"][0].__setitem__(
        "expected_text_anchor", "Représentation des arbres binaires de recherche"
    ),
    lambda d: d["collections"]["rag_nexus_nsi_terminale_specialite"]["positive"][0].__setitem__(
        "expected_chunk_ids", ["0" * 64]
    ),
])
def test_tampering_fails_closed(mutation) -> None:
    module = _module()
    suite = copy.deepcopy(json.loads(SUITE_PATH.read_text(encoding="utf-8")))
    mutation(suite)
    with pytest.raises(module.QualitySuiteError):
        module.validate_suite(ROOT, suite)


def test_positive_response_checks_identity_pages_scope_and_full_attribution() -> None:
    module = _module()
    suite = json.loads(SUITE_PATH.read_text(encoding="utf-8"))
    index = module.validate_suite(ROOT, suite)
    collection = "rag_nexus_nsi_terminale_specialite"
    case = suite["collections"][collection]["positive"][0]
    artifact = index[collection][case["expected_content_sha256"]]
    chunk = next(row for row in artifact["chunks"] if row["page_start"] in case["expected_pages_any"])
    result = {
        "chunk_id": chunk["chunk_id"],
        "doc_id": case["expected_content_sha256"],
        "title": case["expected_citation"]["source_label"],
        "excerpt": "Pour rechercher une clé dans un ABR, on parcourt les nœuds depuis la racine.",
        "score": 0.42,
        "metadata": {
            "collection": collection,
            "artifact_id": case["expected_content_sha256"],
            "content_sha256": case["expected_content_sha256"],
            "placement_id": next(iter(artifact["placement_ids"])),
            "review_status": "reviewed",
        },
        "citation": {
            **case["expected_citation"], "page": chunk["page_start"],
            "rights": "public_allowed",
        },
    }
    valid_response = {"results": [result], "filters_applied": {
        "collection": collection, "scope_digest": suite["collections"][collection]["scope_digest"],
    }}
    scope_digest = suite["collections"][collection]["scope_digest"]
    assert module.check_positive(case, valid_response, index, scope_digest=scope_digest)
    for corrupt in (
        lambda r: r["metadata"].__setitem__("collection", "rag_nexus_hggsp_premiere_specialite"),
        lambda r: r["metadata"].__setitem__("placement_id", "0" * 64),
        lambda r: r["citation"].__setitem__("licensor", ""),
        lambda r: r["citation"].__setitem__("page", 9999),
        lambda r: r["citation"].__setitem__("rights", "internal"),
        lambda r: r.__setitem__("title", None),
        lambda r: r.__setitem__("excerpt", ""),
        lambda r: r.__setitem__("score", float("nan")),
    ):
        changed = copy.deepcopy(result)
        corrupt(changed)
        with pytest.raises(module.QualitySuiteError):
            module.check_positive(case, {**valid_response, "results": [changed]}, index, scope_digest=scope_digest)
    with pytest.raises(module.QualitySuiteError):
        module.check_positive(case, {"results": [result], "filters_applied": {}}, index, scope_digest=scope_digest)
    with pytest.raises(module.QualitySuiteError):
        module.check_positive(case, {**valid_response, "filters_applied": {
            "collection": collection, "scope_digest": "b" * 64,
        }}, index, scope_digest=scope_digest)


def test_private_anchor_check_rejects_title_only_or_wrong_page(tmp_path: Path) -> None:
    module = _module()
    body = (
        "NEXUS-STUDENT-TEXT-DERIVATIVE-V2\n{}\n\n"
        "[PAGE 1 BLOCK 1]\n{}\nTitre sur la recherche binaire\n\n"
        "[PAGE 3 BLOCK 2]\n{}\nPour rechercher une clé particulière dans un arbre, "
        "on parcourt les nœuds depuis la racine en comparant les valeurs.\n"
    ).encode()
    sha = hashlib.sha256(body).hexdigest()
    (tmp_path / f"{sha}.txt").write_bytes(body)
    case = {"expected_content_sha256": sha, "expected_pages_any": [3],
            "expected_text_anchor": "Pour rechercher une clé particulière dans un arbre, on parcourt les nœuds depuis la racine en comparant les valeurs.",
            "id": "factual"}
    suite = {"collections": {"collection": {"positive": [case]}}}
    assert module.verify_text_anchors(suite, tmp_path) == 1
    case["expected_text_anchor"] = "Titre sur la recherche binaire"
    with pytest.raises(module.QualitySuiteError):
        module.verify_text_anchors(suite, tmp_path)
    case["expected_text_anchor"] = (
        "Pour rechercher une clé particulière dans un arbre, "
        "on parcourt les nœuds depuis la racine en comparant les valeurs."
    )
    case["expected_pages_any"] = [1]
    with pytest.raises(module.QualitySuiteError):
        module.verify_text_anchors(suite, tmp_path)
