"""La recette finale échoue sur les preuves absentes ou hors manifeste."""

from __future__ import annotations

import base64
import copy
import json
import sys
from pathlib import Path

import pytest
from nexus_contracts import Citation, RetrievalResponse, RetrievalResult

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "go_live"))
sys.path.insert(0, str(ROOT / "scripts"))

import final_retrieval_acceptance as acceptance  # noqa: E402
import rag_query  # noqa: E402


def _case_and_index():
    suite, index = acceptance.load_suite(ROOT)
    collection = "rag_nexus_dgemc_terminale_option"
    return suite, index, suite["collections"][collection]["positive"][0]


def _response(case, index, *, citation=True, collection=None, content=None, chunk=None):
    expected = case["expected_content_sha256"]
    artifact = index[case["collection"]][content or expected]
    chosen = chunk or next(iter(artifact["chunks"]))
    locator = artifact["chunks"][chosen]
    result = RetrievalResult(
        chunk_id=chosen,
        doc_id=content or expected,
        excerpt="Les règlements et directives de l'Union européenne sont des normes juridiques.",
        score=0.9,
        metadata={
            "collection": collection or case["collection"],
            "artifact_id": content or expected,
            "content_sha256": content or expected,
            "placement_id": next(iter(artifact["placements"])),
            "review_status": "reviewed",
        },
        citation=Citation(
            source_label=artifact["title"],
            source_uri=artifact["source_url"],
            page=locator["page_start"],
            rights="officiel_public",
        ) if citation else None,
    )
    return RetrievalResponse(results=[result])


def test_dataset_is_bound_to_exact_mixed_registry_and_11_subjects():
    suite, index, case = _case_and_index()
    assert suite["mixed_registry_sha256"] == "59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6"
    assert len(index) == 11
    assert sum(len(value["positive"]) for value in suite["collections"].values()) == 33
    assert case["expected_content_sha256"] in index[case["collection"]]
    assert suite["expected_population"] == {
        "collections": 11, "artifacts": 315, "placements": 479, "chunks": 8268
    }


def test_population_mismatch_refused():
    suite, _index, _case = _case_and_index()
    bad = copy.deepcopy(suite)
    bad["expected_population"]["chunks"] = 1
    with pytest.raises(acceptance.AcceptanceFailure, match="population"):
        acceptance.validate_suite(ROOT, bad)


def test_missing_collection_refused():
    suite, _index, _case = _case_and_index()
    bad = copy.deepcopy(suite)
    bad["collections"].pop("rag_nexus_dgemc_terminale_option")
    with pytest.raises(acceptance.AcceptanceFailure, match="11 collections"):
        acceptance.validate_suite(ROOT, bad)


def test_expected_content_outside_manifest_refused():
    suite, _index, _case = _case_and_index()
    bad = copy.deepcopy(suite)
    bad["collections"]["rag_nexus_dgemc_terminale_option"]["positive"][0]["expected_content_sha256"] = "0" * 64
    with pytest.raises(acceptance.AcceptanceFailure, match="hors manifeste"):
        acceptance.validate_suite(ROOT, bad)


def test_no_accent_case_cannot_silently_regain_accents():
    suite, _index, _case = _case_and_index()
    bad = copy.deepcopy(suite)
    cases = bad["collections"]["rag_nexus_dgemc_terminale_option"]["positive"]
    next(case for case in cases if case["id"] == "no_accent")["query"] = "règlement européen"
    with pytest.raises(acceptance.AcceptanceFailure, match="sans accents"):
        acceptance.validate_suite(ROOT, bad)


def test_citation_and_content_identity_pass_against_manifest():
    _suite, index, case = _case_and_index()
    assert acceptance.check_positive(case, _response(case, index), index) is True


def test_missing_citation_refused_even_when_expected_source_found():
    _suite, index, case = _case_and_index()
    with pytest.raises(acceptance.AcceptanceFailure, match="citation"):
        acceptance.check_positive(case, _response(case, index, citation=False), index)


def test_out_of_scope_result_refused():
    _suite, index, case = _case_and_index()
    with pytest.raises(acceptance.AcceptanceFailure, match="hors scope"):
        acceptance.check_positive(case, _response(case, index, collection="rag_nexus_svt_terminale_specialite"), index)


def test_empty_positive_and_nonempty_zero_result_both_fail():
    _suite, index, case = _case_and_index()
    with pytest.raises(acceptance.AcceptanceFailure, match="aucun résultat"):
        acceptance.check_positive(case, RetrievalResponse(results=[]), index)
    with pytest.raises(acceptance.AcceptanceFailure, match="zéro résultat"):
        acceptance.check_zero_result(_response(case, index))


def test_manifest_binding_refuses_tampered_digest():
    suite, _index, _case = _case_and_index()
    bad = copy.deepcopy(suite)
    bad["mixed_registry_sha256"] = "0" * 64
    with pytest.raises(acceptance.AcceptanceFailure, match="registre mixte"):
        acceptance.validate_suite(ROOT, bad)


def test_operator_issues_student_identity_for_negative_http_case():
    config = rag_query.ClientConfig(
        api_url="https://staging.example",
        bff_token="b" * 32,
        internal_secret="s" * 32,
        internal_issuer="nexus-test",
        internal_audience="engine-test",
        identity_issuer="sso-test",
        identity_audience="cockpit-test",
    )
    token, _artifact = rag_query.issue_scope_identity(
        "prod_nsi_terminale_specialite_v1", config=config, role="student"
    )
    body = token.split(".")[1]
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    assert payload["identity"]["role"] == "student"
    with pytest.raises(rag_query.RagQueryClientError, match="rôle"):
        rag_query.issue_scope_identity(
            "prod_nsi_terminale_specialite_v1", config=config, role="admin"
        )


def test_dense_probe_requires_all_chunks_and_reports_tie_overflow():
    suite, index, _case = _case_and_index()
    chunks = {
        name: len({chunk for artifact in selected.values() for chunk in artifact["chunks"]})
        for name, selected in index.items()
    }
    probe = {
        "release_id": "mixed-v4-hggsp",
        "collections": {
            name: {"chunks": count, "rappel_a_1": count - 1,
                   "rappel_a_5": count - 1,
                   "manques": 0, "refus_egalite": 1, "lexicaux": 1,
                   "student": "refuse"}
            for name, count in chunks.items()
        },
        "totaux": {"chunks": 12316, "rappel_a_1": 12305,
                   "rappel_a_5": 12305, "manques": 0, "refus_egalite": 11},
    }
    assert acceptance.check_dense_probe(probe, suite) == 11
    probe["totaux"]["chunks"] = 12315
    with pytest.raises(acceptance.AcceptanceFailure, match="dense"):
        acceptance.check_dense_probe(probe, suite)


@pytest.mark.parametrize("missing_first", [False, True])
@pytest.mark.parametrize("key_name", ["RAG_API_KEY", "COCKPIT_STAGING_API_KEY"])
def test_http_runner_covers_33_positives_and_refusals(monkeypatch, missing_first, key_name):
    import rag_query_external

    suite, index, _case = _case_and_index()
    monkeypatch.delenv("RAG_API_KEY", raising=False)
    monkeypatch.delenv("COCKPIT_STAGING_API_KEY", raising=False)
    for key, value in {
        "RAG_BFF_SERVICE_TOKEN": "b" * 32,
        key_name: "a" * 32,
        "NEXUS_INTERNAL_TOKEN_SECRET": "s" * 32,
        "NEXUS_INTERNAL_TOKEN_ISSUER": "nexus-test",
        "NEXUS_INTERNAL_TOKEN_AUDIENCE": "engine-test",
        "NEXUS_SSO_ISSUER": "sso-test",
        "NEXUS_SSO_AUDIENCE": "cockpit-test",
    }.items():
        monkeypatch.setenv(key, value)
    names = sorted(suite["collections"])
    seen: list[str] = []

    def fake_search(payload, *, config):
        call = len(seen)
        collection = names[call // 6]
        phase = call % 6
        seen.append(payload.need.query)
        if phase < 3:
            case = suite["collections"][collection]["positive"][phase]
            assert payload.need.query == case["query"]
            return _response(case, index, citation=not (missing_first and call == 0))
        if phase == 3:
            assert payload.need.query == suite["collections"][collection]["zero_result_query"]
            return RetrievalResponse(results=[])
        raise rag_query_external.RagQueryExternalClientError("API HTTP 403")

    monkeypatch.setattr(rag_query_external, "post_search", fake_search)
    report = acceptance.run_http(ROOT, suite, index, api_url="https://staging.example")
    assert report["verdict"] == ("fail" if missing_first else "pass")
    assert report["totals"]["positive_nonempty"] == 33
    assert report["totals"]["expected_source_hits"] == (32 if missing_first else 33)
    assert report["totals"]["missing_citations"] == int(missing_first)
    assert report["totals"]["zero_result_pass"] == 11
    assert report["totals"]["student_refusals"] == 11
    assert report["totals"]["scope_mismatch_refusals"] == 11
    assert len(seen) == 66


def test_checkout_sha_is_explicit_in_runtime_image_without_git(monkeypatch):
    sha = "e" * 40
    monkeypatch.setenv("NEXUS_ACCEPTANCE_CHECKOUT_SHA", sha)
    monkeypatch.setenv("PATH", "")
    assert acceptance._git_head(ROOT) == sha
