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


def _probe_provenance(suite):
    return {
        "checkout_sha": "e" * 40,
        "mixed_registry_sha256": suite["mixed_registry_sha256"],
        "release_manifest_sha256": suite["release_manifest_sha256"],
        "generated_at_utc": "2026-10-08T00:00:00Z",
        "db_fingerprint": {
            "database": "ragdb_profile_gate_v4", "database_oid": 1,
            "chunks": 8268, "artifacts": 315, "placements": 479,
            "max_chunk_indexed_at": "2026-10-08 00:00:00",
            "max_artifact_created_at": "2026-10-08 00:00:00",
            "max_placement_created_at": "2026-10-08 00:00:00",
        },
    }


def _response(case, index, *, citation=True, collection=None, content=None, chunk=None):
    expected = case["expected_content_sha256"]
    artifact = index[case["collection"]][content or expected]
    chosen = chunk or next(iter(artifact["chunks"]))
    locator = artifact["chunks"][chosen]
    result = RetrievalResult(
        chunk_id=chosen,
        doc_id=content or expected,
        title=artifact["title"],
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
    assert suite["thresholds"]["dense_misses"] == 0


def test_expected_sources_are_topic_resources_not_generic_programmes():
    suite, index, _case = _case_and_index()
    for collection, spec in suite["collections"].items():
        for case in spec["positive"]:
            title = index[collection][case["expected_content_sha256"]]["title"].lower()
            assert "programme de " not in title
            assert "bo spécial" not in title
            assert "bo special" not in title


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


def test_citation_label_must_match_result_title():
    _suite, index, case = _case_and_index()
    response = _response(case, index)
    response.results[0].title = "Autre source"
    with pytest.raises(acceptance.AcceptanceFailure, match="citation"):
        acceptance.check_positive(case, response, index)


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
            name: {"scope_id": suite["collections"][name]["scope_id"],
                   "programme_version": suite["collections"][name]["programme_version"],
                   "chunks": count, "rappel_a_1": count - 1,
                   "rappel_a_5": count - 1,
                   "manques": 0, "refus_egalite": 1, "lexicaux": 1,
                   "student": "refuse"}
            for name, count in chunks.items()
        },
        "totaux": {"chunks": 12316, "rappel_a_1": 12305,
                   "rappel_a_5": 12305, "manques": 0, "refus_egalite": 11},
    }
    with pytest.raises(acceptance.AcceptanceFailure, match="provenance"):
        acceptance.check_dense_probe(probe, suite, index)
    probe["provenance"] = _probe_provenance(suite)
    assert acceptance.check_dense_probe(probe, suite, index) == 11
    probe["totaux"]["chunks"] = 12315
    with pytest.raises(acceptance.AcceptanceFailure, match="dense"):
        acceptance.check_dense_probe(probe, suite, index)


def test_probe_database_fingerprint_records_target_and_publication_watermarks():
    import staging_retrieval_probe

    class FakeConnection:
        def execute(self, query):
            assert "current_database()" in query
            return self
        def fetchone(self):
            return ("ragdb_profile_gate_v4", 16438, 8268, 315, 479,
                    "2026-10-08 05:00:00", "2026-10-08 04:00:00", "2026-10-08 04:30:00")

    fingerprint = staging_retrieval_probe.db_fingerprint(FakeConnection())
    assert fingerprint == _probe_provenance(_case_and_index()[0])["db_fingerprint"] | {
        "database_oid": 16438,
        "max_chunk_indexed_at": "2026-10-08 05:00:00",
        "max_artifact_created_at": "2026-10-08 04:00:00",
        "max_placement_created_at": "2026-10-08 04:30:00",
    }


def test_dense_probe_rejects_wrong_scope_and_swapped_collection_counts():
    suite, index, _case = _case_and_index()
    counts = {name: len({chunk for artifact in selected.values() for chunk in artifact["chunks"]})
              for name, selected in index.items()}
    probe = {
        "release_id": "mixed-v4-hggsp",
        "provenance": _probe_provenance(suite),
        "collections": {
            name: {"scope_id": suite["collections"][name]["scope_id"],
                   "programme_version": suite["collections"][name]["programme_version"],
                   "chunks": count, "rappel_a_1": count, "rappel_a_5": count,
                   "manques": 0, "refus_egalite": 0, "student": "refuse"}
            for name, count in counts.items()
        },
        "totaux": {"chunks": 12316, "rappel_a_1": 12316, "rappel_a_5": 12316,
                   "manques": 0, "refus_egalite": 0},
    }
    wrong_scope = copy.deepcopy(probe)
    first, second = list(counts)[:2]
    wrong_scope["collections"][first]["scope_id"] = suite["collections"][second]["scope_id"]
    with pytest.raises(acceptance.AcceptanceFailure, match="scope"):
        acceptance.check_dense_probe(wrong_scope, suite, index)
    swapped = copy.deepcopy(probe)
    for field in ("chunks", "rappel_a_1", "rappel_a_5"):
        swapped["collections"][first][field], swapped["collections"][second][field] = (
            swapped["collections"][second][field], swapped["collections"][first][field]
        )
    with pytest.raises(acceptance.AcceptanceFailure, match="population"):
        acceptance.check_dense_probe(swapped, suite, index)


@pytest.mark.parametrize("field,value", [("rappel_a_1", -1), ("manques", 1)])
def test_dense_probe_rejects_negative_or_missing_recall(field, value):
    suite, index, _case = _case_and_index()
    counts = {name: len({chunk for artifact in selected.values() for chunk in artifact["chunks"]})
              for name, selected in index.items()}
    probe = {
        "release_id": "mixed-v4-hggsp",
        "provenance": _probe_provenance(suite),
        "collections": {
            name: {"scope_id": suite["collections"][name]["scope_id"],
                   "programme_version": suite["collections"][name]["programme_version"],
                   "chunks": count, "rappel_a_1": count, "rappel_a_5": count,
                   "manques": 0, "refus_egalite": 0, "student": "refuse"}
            for name, count in counts.items()
        },
        "totaux": {"chunks": 12316, "rappel_a_1": 12316, "rappel_a_5": 12316,
                   "manques": 0, "refus_egalite": 0},
    }
    name = next(iter(counts))
    probe["collections"][name][field] = value
    if field == "rappel_a_1":
        probe["totaux"]["rappel_a_1"] -= counts[name] + 1
    else:
        probe["collections"][name]["rappel_a_5"] -= 1
        probe["totaux"]["rappel_a_5"] -= 1
        probe["totaux"]["manques"] = 1
    with pytest.raises(acceptance.AcceptanceFailure, match="dense"):
        acceptance.check_dense_probe(probe, suite, index)


@pytest.mark.parametrize("missing_first", [False, True])
@pytest.mark.parametrize("key_name", ["RAG_API_KEY", "COCKPIT_STAGING_API_KEY"])
def test_http_runner_covers_33_positives_and_refusals(monkeypatch, missing_first, key_name):
    import rag_query_external

    suite, index, _case = _case_and_index()
    monkeypatch.setattr(acceptance, "_git_head", lambda _root: "e" * 40)
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
        from nexus_contracts import load_retrieval_scope_artifact
        from rag_query_external import build_request

        call = len(seen)
        collection = names[call // 6]
        phase = call % 6
        seen.append(payload.need.query)
        body = config.identity_token.split(".")[1]
        token = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        assert token["scope_id"] == suite["collections"][collection]["scope_id"]
        if phase < 3:
            assert token["identity"]["role"] == "teacher"
            case = suite["collections"][collection]["positive"][phase]
            assert payload.need.query == case["query"]
            return _response(case, index, citation=not (missing_first and call == 0))
        if phase == 3:
            assert token["identity"]["role"] == "teacher"
            assert payload.need.query == suite["collections"][collection]["zero_result_query"]
            return RetrievalResponse(results=[])
        if phase == 4:
            assert token["identity"]["role"] == "student"
            assert payload.need.query == suite["collections"][collection]["positive"][0]["query"]
        else:
            assert token["identity"]["role"] == "teacher"
            other = suite["collections"][names[(call // 6 + 1) % len(names)]]
            expected = build_request(
                "Quels thèmes sont étudiés ?", load_retrieval_scope_artifact(other["scope_id"])
            )
            assert payload == expected
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
    assert report["page_end_evidence"] == "manifest_only_db_check_required"
    assert report["http_path"] == "direct_api_v2"
    if not missing_first:
        first = report["cases"][0]["results"][0]
        assert first["chunk_id"] in index[report["cases"][0]["collection"]][first["content_sha256"]]["chunks"]
        assert first["page_end_manifest"] >= first["page_start"]
        assert first["source_uri"].startswith("https://")
        assert first["source_label"]
    assert len(seen) == 66


def test_checkout_sha_is_explicit_in_runtime_image_without_git(monkeypatch):
    sha = "e" * 40
    monkeypatch.setenv("NEXUS_ACCEPTANCE_CHECKOUT_SHA", sha)
    monkeypatch.setenv("NEXUS_ACCEPTANCE_CHECKOUT_CLEAN", "true")
    monkeypatch.setenv("PATH", "")
    assert acceptance._git_head(ROOT) == sha


def test_live_db_reconciles_each_returned_chunk_content_placement_and_pages():
    result = {
        "chunk_id": "chunk-1", "placement_id": "placement-1", "content_sha256": "a" * 64,
        "source_uri": "https://eduscol.example/source", "source_label": "Éduscol",
        "page_start": 2, "page_end_manifest": 3, "rights": "officiel_public",
    }
    report = {"cases": [{"collection": "collection-1", "results": [result]}]}
    db_row = (
        "chunk-1", "placement-1", "a" * 64, 2, 3, "collection-1",
        "active", "reviewed", "current", "internal", "officiel_public",
        "https://eduscol.example/source", "Éduscol",
    )
    assert acceptance.reconcile_db_rows(report, [db_row]) == 1
    assert result["page_start_db"] == 2
    assert result["page_end_db"] == 3
    for index, replacement in [(2, "b" * 64), (4, 4), (5, "other-collection"),
                               (8, "stale"), (11, "https://other.example")]:
        tampered = list(db_row)
        tampered[index] = replacement
        with pytest.raises(acceptance.AcceptanceFailure, match="DB"):
            acceptance.reconcile_db_rows(report, [tuple(tampered)])
    with pytest.raises(acceptance.AcceptanceFailure, match="DB"):
        acceptance.reconcile_db_rows(report, [])


def test_live_db_transport_opens_read_only_transaction(monkeypatch):
    import psycopg

    report = {"cases": []}
    commands = []
    class FakeConnection:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def execute(self, sql, args=None):
            commands.append((sql, args))
            return self
        def fetchall(self): return []
        def fetchone(self):
            return ("ragdb_profile_gate_v4", 16438, 8268, 315, 479,
                    "2026-10-08 05:00:00", "2026-10-08 04:00:00", "2026-10-08 04:30:00")
        def rollback(self): pass
    monkeypatch.setattr(psycopg, "connect", lambda _dsn: FakeConnection())
    assert acceptance.verify_db_evidence(report, "postgresql://reader@example/db") == 0
    assert commands[0][0] == "SET TRANSACTION READ ONLY"
    assert "current_database()" in commands[1][0]
    assert "rag_chunks" in commands[2][0]
    assert report["db_fingerprint"]["database"] == "ragdb_profile_gate_v4"


def test_runtime_without_git_refuses_missing_clean_checkout_attestation(monkeypatch):
    monkeypatch.setenv("NEXUS_ACCEPTANCE_CHECKOUT_SHA", "e" * 40)
    monkeypatch.delenv("NEXUS_ACCEPTANCE_CHECKOUT_CLEAN", raising=False)
    monkeypatch.setenv("PATH", "")
    with pytest.raises(acceptance.AcceptanceFailure, match="propre"):
        acceptance._git_head(ROOT)


def test_git_checkout_refuses_tracked_modifications(monkeypatch):
    import subprocess

    monkeypatch.delenv("NEXUS_ACCEPTANCE_CHECKOUT_SHA", raising=False)
    def fake_check_output(command, **kwargs):
        if "status" in command:
            return " M scripts/go_live/final_retrieval_acceptance.py\n"
        return "e" * 40
    monkeypatch.setattr(subprocess, "check_output", fake_check_output)
    with pytest.raises(acceptance.AcceptanceFailure, match="propre"):
        acceptance._git_head(ROOT)
