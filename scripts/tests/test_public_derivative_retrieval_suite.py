"""The public acceptance plan cannot pass on an unpromoted candidate."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from nexus_contracts import Citation, RetrievalResponse, RetrievalResult

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "go_live"))

from public_derivative_retrieval_suite import (  # noqa: E402
    SuiteFailure,
    check_dense_tie_probe,
    check_public_positive,
    load_draft_suite,
    reconcile_public_db_rows,
    require_final_binding,
    validate_draft_suite,
)


def _public_hit():
    sha = "a" * 64
    citation = {
        "source_uri": "https://eduscol.education.gouv.fr/example.pdf",
        "source_label": "Ressource officielle",
        "source_updated_at": "2026-10-10",
        "licensor": "Direction générale de l'enseignement scolaire",
        "licence_id": "ETALAB-2.0",
        "derivative_notice": "Extrait textuel dérivé ; PDF non redistribué.",
    }
    collection = "rag_nexus_nsi_terminale_specialite"
    index = {collection: {sha: {
        "content_sha256": sha,
        "source_pdf_sha256": "b" * 64,
        "media_type": "text/plain; charset=utf-8",
        "placements": {"placement-public"},
        "chunks": {"chunk-public": {"page_start": 3, "page_end": 3}},
        "citation": citation,
    }}}
    response = RetrievalResponse(results=[RetrievalResult(
        chunk_id="chunk-public", doc_id=sha, title=citation["source_label"],
        excerpt="Un passage officiel.", score=0.8,
        metadata={"collection": collection, "artifact_id": sha,
                  "content_sha256": sha, "placement_id": "placement-public",
                  "review_status": "reviewed"},
        citation=Citation(**citation, page=3, rights="officiel_public"),
    )])
    case = {"collection": collection, "expected_content_sha256": sha}
    spec = {"expected_citation": citation, "expected_source_pdf_sha256": "b" * 64}
    return case, spec, response, index, citation


def test_public_positive_checks_actual_derivative_and_complete_citation() -> None:
    case, spec, response, index, citation = _public_hit()
    hit, records = check_public_positive(case, spec, response, index)
    assert hit is True
    assert records == [{
        "collection": case["collection"], "content_sha256": case["expected_content_sha256"],
        "chunk_id": "chunk-public", "placement_id": "placement-public",
        "page_start": 3, "page_end": 3, "rights": "officiel_public", **citation,
    }]


@pytest.mark.parametrize("sabotage", [
    "empty", "foreign_scope", "pdf_identity", "foreign_chunk", "missing_attribution",
    "wrong_attribution", "unreviewed", "non_text", "oracle_citation",
    "oracle_pdf_identity", "invalid_index_citation",
])
def test_public_positive_refuses_unbound_or_invalid_http_hit(sabotage: str) -> None:
    case, spec, response, index, _ = _public_hit()
    hit = response.results[0]
    if sabotage == "empty":
        response.results.clear()
    elif sabotage == "foreign_scope":
        hit.metadata["collection"] = "rag_nexus_svt_terminale_specialite"
    elif sabotage == "pdf_identity":
        index[case["collection"]][case["expected_content_sha256"]]["source_pdf_sha256"] = case["expected_content_sha256"]
    elif sabotage == "foreign_chunk":
        hit.chunk_id = "unlisted-chunk"
    elif sabotage == "missing_attribution":
        hit.citation = None
    elif sabotage == "wrong_attribution":
        hit.citation = hit.citation.model_copy(update={"source_updated_at": "2025-01-01"})
    elif sabotage == "unreviewed":
        hit.metadata["review_status"] = "pending"
    elif sabotage == "non_text":
        index[case["collection"]][case["expected_content_sha256"]]["media_type"] = "application/pdf"
    elif sabotage == "oracle_citation":
        spec["expected_citation"]["source_uri"] = "https://example.com/forged.pdf"
    elif sabotage == "oracle_pdf_identity":
        spec["expected_source_pdf_sha256"] = "c" * 64
    elif sabotage == "invalid_index_citation":
        index[case["collection"]][case["expected_content_sha256"]]["citation"] = None
    with pytest.raises(SuiteFailure):
        check_public_positive(case, spec, response, index)


def test_public_positive_checks_pdf_lineage_of_every_result() -> None:
    case, spec, response, index, _ = _public_hit()
    collection = case["collection"]
    second_sha = "c" * 64
    second_artifact = copy.deepcopy(index[collection][case["expected_content_sha256"]])
    second_artifact["content_sha256"] = second_sha
    second_artifact["source_pdf_sha256"] = None
    index[collection][second_sha] = second_artifact
    second = response.results[0].model_copy(deep=True)
    second.doc_id = second_sha
    second.metadata["content_sha256"] = second_sha
    second.metadata["artifact_id"] = second_sha
    response.results.append(second)
    with pytest.raises(SuiteFailure, match="identity"):
        check_public_positive(case, spec, response, index)


def test_public_db_reconciliation_checks_visibility_page_and_attribution() -> None:
    case, spec, response, index, citation = _public_hit()
    _, records = check_public_positive(case, spec, response, index)
    row = {
        **records[0], "placement_status": "active", "review_status": "reviewed",
        "currentness": "official_snapshot", "visibility": "public",
        "is_text_derivative": True,
    }
    assert reconcile_public_db_rows(records, [row]) == 1
    for key, value in (("visibility", "internal"), ("page_end", 4),
                       ("licence_id", "NONE"), ("is_text_derivative", False),
                       ("source_uri", "https://example.com/other.pdf")):
        bad = {**row, key: value}
        with pytest.raises(SuiteFailure, match="DB"):
            reconcile_public_db_rows(records, [bad])
    with pytest.raises(SuiteFailure, match="DB"):
        reconcile_public_db_rows(records, [])
    with pytest.raises(SuiteFailure, match="DB"):
        reconcile_public_db_rows(records, [row, row])


def test_draft_covers_exact_candidate_and_fixed_cases() -> None:
    suite = load_draft_suite(ROOT)
    assert suite["status"] == "PREPARED_UNBOUND"
    assert len(suite["collections"]) == 11
    assert sum(len(row["positive"]) for row in suite["collections"].values()) == 33
    assert suite["thresholds"]["student_positive_nonempty"] == 33
    assert suite["thresholds"]["teacher_refusals"] == 11
    assert suite["thresholds"]["dense_misses"] == 0
    assert suite["preparation_manifest_sha256"] == (
        "b79246ff356b919aeb3dcb7f640a1a554e338899128a7c5acdcfaa9b7bcb1c78"
    )
    assert suite["preparation_index_sha256"] == (
        "bd1f714594ca17dbbe7d3cfdf255c8c270003c63bd4d267971a17b2afdb08ca4"
    )
    assert suite["expected_preparation_population"] == {
        "subjects": 11, "unique_artifacts": 253,
        "placements": 377, "unique_chunks": 3975,
    }


@pytest.mark.parametrize("sabotage", [
    "old_preparation", "index_digest", "manifest_digest", "chunk_budget",
    "foreign_collection_artifact",
])
def test_preparation_v2_binding_sabotage_rejected(sabotage: str) -> None:
    suite = copy.deepcopy(load_draft_suite(ROOT))
    if sabotage == "old_preparation":
        suite["preparation_manifest_path"] = (
            "services/rag-pedago/data/releases/prerentree_2026_2027/"
            "profile_gate_student_public_candidate_v1/production-profile-gate.release.json"
        )
    elif sabotage == "index_digest":
        suite["preparation_index_sha256"] = "0" * 64
    elif sabotage == "manifest_digest":
        suite["preparation_manifest_sha256"] = "0" * 64
    elif sabotage == "chunk_budget":
        suite["expected_preparation_population"]["unique_chunks"] = 2504
    else:
        dgemc = suite["collections"]["rag_nexus_dgemc_terminale_option"]
        hggsp = suite["collections"]["rag_nexus_hggsp_premiere_specialite"]
        dgemc["positive"][0]["expected_content_sha256"] = hggsp["positive"][0][
            "expected_content_sha256"
        ]
    with pytest.raises(SuiteFailure):
        validate_draft_suite(ROOT, suite)


@pytest.mark.parametrize("sabotage", ["index", "registry", "subject", "profile"])
def test_preparation_v2_file_sabotage_rejected(
    tmp_path: Path, sabotage: str
) -> None:
    suite = load_draft_suite(ROOT)
    candidate = tmp_path / suite["candidate_manifest_path"]
    candidate.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / suite["candidate_manifest_path"], candidate)
    package = Path(suite["preparation_index_path"]).parent
    shutil.copytree(ROOT / package, tmp_path / package)
    if sabotage == "index":
        target = tmp_path / suite["preparation_index_path"]
    elif sabotage == "registry":
        target = package / "profile_gate/artifacts.release.json"
        target = tmp_path / target
    elif sabotage == "subject":
        target = tmp_path / package / "profile_gate/subjects/rag_nexus_dgemc_terminale_option.release.json"
    else:
        target = tmp_path / package / "profile_gate/profiles/rag_nexus_dgemc_terminale_option.yml"
    target.write_bytes(target.read_bytes() + b"\n# tampered\n")
    with pytest.raises(SuiteFailure):
        validate_draft_suite(tmp_path, suite)


def test_final_quality_cannot_pass_without_successor_manifest_and_scope_registry() -> (
    None
):
    suite = load_draft_suite(ROOT)
    with pytest.raises(SuiteFailure, match="final.*binding"):
        require_final_binding(ROOT, suite)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: s["collections"].pop(next(iter(s["collections"]))),
        lambda s: s["collections"][next(iter(s["collections"]))]["positive"][0].update(
            expected_content_sha256="0" * 64
        ),
        lambda s: s["collections"][next(iter(s["collections"]))]["positive"][1].update(
            query="L'Union européenne dans l'enseignement"
        ),
        lambda s: s["collections"][next(iter(s["collections"]))].pop(
            "expected_citation"
        ),
        lambda s: s["thresholds"].update(student_positive_nonempty=0),
        lambda s: s["thresholds"].update(teacher_refusals=0),
        lambda s: s["collections"][next(iter(s["collections"]))].update(
            teacher_expected_http=200
        ),
        lambda s: s["thresholds"].update(dense_misses=1),
        lambda s: s.update(candidate_manifest_sha256="0" * 64),
    ],
)
def test_sabotage_rejected(mutation) -> None:
    suite = load_draft_suite(ROOT)
    altered = copy.deepcopy(suite)
    mutation(altered)
    with pytest.raises(SuiteFailure):
        validate_draft_suite(ROOT, altered)


def test_rehearsal_pdf_identity_cannot_replace_derivative_identity() -> None:
    suite = load_draft_suite(ROOT)
    altered = copy.deepcopy(suite)
    collection = next(iter(altered["collections"].values()))
    collection["positive"][0]["expected_content_sha256"] = collection[
        "expected_source_pdf_sha256"
    ]
    with pytest.raises(SuiteFailure, match="derivative"):
        validate_draft_suite(ROOT, altered)


def test_promoted_manifest_cannot_substitute_its_artifact_set(tmp_path: Path) -> None:
    suite = copy.deepcopy(load_draft_suite(ROOT))
    candidate = tmp_path / suite["candidate_manifest_path"]
    candidate.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / suite["candidate_manifest_path"], candidate)
    registry = tmp_path / "release" / "artifacts.release.json"
    registry.parent.mkdir()
    registry.write_text(json.dumps({"artifacts": [{"content_sha256": "0" * 64}]}))
    manifest = tmp_path / "release" / "production-profile-gate.release.json"
    manifest.write_text(
        json.dumps(
            {
                "release_mode": "production",
                "promotion_status": "PROMOTABLE",
                "activation_status": "PRODUCTION_ACTIVATION_ALLOWED",
                "review_status": "REVIEWED",
                "expected_counts": {
                    "subjects": 11,
                    "unique_artifacts": 253,
                    "placements": 377,
                },
                "artifact_registry": {
                    "path": "artifacts.release.json",
                    "sha256": hashlib.sha256(registry.read_bytes()).hexdigest(),
                },
            }
        )
    )
    scopes = tmp_path / "scopes.json"
    scopes.write_text("{}")
    suite.update(
        status="BOUND",
        final_release_manifest_path=str(manifest.relative_to(tmp_path)),
        final_release_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        final_scope_registry_path=str(scopes.relative_to(tmp_path)),
        final_scope_registry_sha256=hashlib.sha256(scopes.read_bytes()).hexdigest(),
        final_checkout_sha="a" * 40,
    )
    with pytest.raises(SuiteFailure, match="canonical release verifier required"):
        require_final_binding(tmp_path, suite)


def _write_json(path: Path, value: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "sabotage", ["empty_scopes", "cross_collection", "forged_checkout"]
)
def test_declarative_final_bindings_never_pass_without_canonical_evidence(
    tmp_path: Path,
    sabotage: str,
) -> None:
    suite = copy.deepcopy(load_draft_suite(ROOT))
    candidate_path = tmp_path / suite["candidate_manifest_path"]
    candidate_path.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / suite["candidate_manifest_path"], candidate_path)
    candidate = json.loads(candidate_path.read_text())
    artifacts = []
    placements: dict[str, list[dict]] = {name: [] for name in suite["collections"]}
    for entry in candidate["entries"]:
        sha = entry["derivative_content_sha256"]
        artifacts.append(
            {
                "artifact_id": sha,
                "content_sha256": sha,
                "source_pdf_sha256": entry["source_content_sha256"],
                "citation": entry["citation"],
                "chunks": [
                    {
                        "chunk_id": hashlib.sha256(sha.encode()).hexdigest(),
                        "page_start": 1,
                    }
                ],
            }
        )
        for collection in entry["collections"]:
            placements[collection].append(
                {
                    "placement_id": hashlib.sha256(
                        f"{collection}:{sha}".encode()
                    ).hexdigest(),
                    "artifact_id": sha,
                    "collection": collection,
                    "visibility": "public",
                    "placement_status": "active",
                    "review_status": "reviewed",
                }
            )
    assert sum(map(len, placements.values())) == 377
    if sabotage == "cross_collection":
        target = "rag_nexus_dgemc_terminale_option"
        foreign = next(
            entry["derivative_content_sha256"]
            for entry in candidate["entries"]
            if target not in entry["collections"]
        )
        placements[target][0]["artifact_id"] = foreign
    release = tmp_path / "release"
    registry_sha = _write_json(
        release / "artifacts.release.json", {"artifacts": artifacts}
    )
    refs = []
    for collection, rows in placements.items():
        relative = f"subjects/{collection}.json"
        sha = _write_json(
            release / relative, {"collection": collection, "placements": rows}
        )
        refs.append({"collection": collection, "path": relative, "sha256": sha})
    manifest_sha = _write_json(
        release / "promoted.json",
        {
            "release_mode": "production",
            "promotion_status": "PROMOTABLE",
            "activation_status": "PRODUCTION_ACTIVATION_ALLOWED",
            "review_status": "REVIEWED",
            "expected_counts": {
                "subjects": 11,
                "unique_artifacts": 253,
                "placements": 377,
                "unique_chunks": 253,
            },
            "artifact_registry": {
                "path": "artifacts.release.json",
                "sha256": registry_sha,
            },
            "subjects": refs,
        },
    )
    scopes = (
        {}
        if sabotage == "empty_scopes"
        else {
            "entries": [
                {"collection": name, "scope_id": f"public_{name}", "roles": ["student"]}
                for name in suite["collections"]
            ]
        }
    )
    scope_sha = _write_json(release / "scopes.json", scopes)
    suite.update(
        status="BOUND",
        final_release_manifest_path="release/promoted.json",
        final_release_manifest_sha256=manifest_sha,
        final_scope_registry_path="release/scopes.json",
        final_scope_registry_sha256=scope_sha,
        final_checkout_sha="f" * 40,
    )
    # The manifest is self-consistent enough to fool the former structural
    # checker, but none of these declarations is an authority receipt.
    with pytest.raises(SuiteFailure, match="canonical release verifier required"):
        require_final_binding(tmp_path, suite)


def test_dense_tie_overflow_is_recorded_and_not_counted_as_a_miss() -> None:
    suite = load_draft_suite(ROOT)
    counts = {name: 2 for name in suite["collections"]}
    probe = {
        "provenance": {
            "final_release_manifest_sha256": "a" * 64,
            "checkout_sha": "b" * 40,
            "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "collections": {
            name: {
                "chunks": 2,
                "rappel_a_1": 1,
                "rappel_a_5": 1,
                "manques": 0,
                "refus_egalite": 1,
            }
            for name in counts
        },
    }
    assert check_dense_tie_probe(suite, probe, counts, "a" * 64, "b" * 40) == 11
    bad = copy.deepcopy(probe)
    bad["collections"][next(iter(counts))]["refus_egalite"] = 0
    with pytest.raises(SuiteFailure, match="tie overflow"):
        check_dense_tie_probe(suite, bad, counts, "a" * 64, "b" * 40)
