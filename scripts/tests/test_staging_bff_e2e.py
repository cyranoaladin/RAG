"""Contrôles du harnais BFF réel, sans staging ni secrets."""

from __future__ import annotations

import importlib.util
import json
from argparse import Namespace
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
    assert result["citation_count"] == 1
    assert result["citations"][0]["source_label"] == "Document officiel"
    assert result["content_sha256"] == ["b" * 64]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"citation": None}, "citation"),
        ({"citation": {"source_uri": "https://eduscol.education.fr/document.pdf", "source_label": "Document officiel", "rights": "official_public_administrative", "page": None}}, "citation"),
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


def test_pilot_scope_must_match_the_complete_sealed_release_population():
    harness = load_harness()
    with pytest.raises(ValueError, match="scope.*release"):
        harness.assert_scope_registry_parity(
            {"rag_nexus_maths_terminale_gen_specialite", "rag_nexus_nsi_terminale_specialite"},
            {"rag_nexus_nsi_terminale_specialite"},
        )


def test_final_scope_index_matches_all_sealed_collections_and_governed_artifacts(tmp_path):
    harness = load_harness()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    scopes = []
    collections = {"rag_nexus_nsi_terminale_specialite", "rag_nexus_hggsp_terminale_specialite"}
    for subject, collection in (("nsi", "rag_nexus_nsi_terminale_specialite"), ("hggsp", "rag_nexus_hggsp_terminale_specialite")):
        scope = {
            "artifact_version": "3",
            "scope_id": f"prod_{subject}_terminale_specialite_v3",
            "status": "eligible_for_promotion",
            "target_policy": {"tenant": "libre_terminale", "niveau": "terminale", "voie": "generale", "matiere": subject, "statut_enseignement": "specialite", "audiences": ["libre"], "candidates": ["libre"], "roles": ["student", "teacher"]},
            "evidence_subject": {"collection": collection, "school_year": "2026-2027", "visibility": "public"},
        }
        (artifacts / f"retrieval-scope-prod-{subject}-terminale-specialite-v3.json").write_text(json.dumps(scope))
        scopes.append(scope)
    generated = tmp_path / "final.json"
    generated.write_text(json.dumps(scopes))
    result = harness.load_final_scopes(generated, artifacts, collections)
    assert set(result) == collections
    assert result["rag_nexus_nsi_terminale_specialite"]["scope_id"] == "prod_nsi_terminale_specialite_v3"
    with pytest.raises(ValueError, match="scope.*release"):
        harness.load_final_scopes(generated, artifacts, {"rag_nexus_nsi_terminale_specialite"})
    scopes[0]["target_policy"]["tenant"] = "libre_autre"
    generated.write_text(json.dumps(scopes))
    with pytest.raises(ValueError, match="gouverné"):
        harness.load_final_scopes(generated, artifacts, collections)
    scopes[0]["target_policy"]["tenant"] = "libre_terminale"
    scopes[0]["artifact_version"] = "2"
    generated.write_text(json.dumps(scopes))
    (artifacts / "retrieval-scope-prod-nsi-terminale-specialite-v3.json").write_text(json.dumps(scopes[0]))
    with pytest.raises(ValueError, match="V3|public"):
        harness.load_final_scopes(generated, artifacts, collections)


def test_signed_claims_match_selected_final_scope_and_digest():
    harness = load_harness()
    scope = {"scope_id": "prod_nsi_terminale_specialite_v3", "evidence_subject": {"collection": "rag_nexus_nsi_terminale_specialite"}}
    claims = {"role": "teacher", "scope_id": scope["scope_id"], "scope_digest": harness.canonical_scope_digest(scope), "allowed_collections": [scope["evidence_subject"]["collection"]]}
    harness.assess_signed_claims(claims, "teacher", scope)
    with pytest.raises(ValueError, match="scope"):
        harness.assess_signed_claims({**claims, "scope_digest": "0" * 64}, "teacher", scope)


def test_v3_scope_source_digest_must_match_final_release_subject():
    harness = load_harness()
    collection = "rag_nexus_nsi_terminale_specialite"
    scope = {"source_sha256": "a" * 64, "evidence_subject": {"collection": collection}}
    harness.assert_scope_subject_binding(scope, collection, {collection: "a" * 64})
    with pytest.raises(ValueError, match="subject"):
        harness.assert_scope_subject_binding(scope, collection, {collection: "b" * 64})
    with pytest.raises(ValueError, match="subject"):
        harness.assert_scope_subject_binding(scope, collection, {})


def test_signed_identity_uses_exact_final_collection_profile():
    harness = load_harness()
    scope = {
        "target_policy": {"tenant": "libre_premiere", "niveau": "premiere", "voie": "generale", "matiere": "hggsp", "statut_enseignement": "specialite", "audiences": ["libre"], "candidates": ["libre"], "roles": ["student", "teacher"]},
        "evidence_subject": {"school_year": "2026-2027", "collection": "rag_nexus_hggsp_premiere_specialite"},
    }
    assert harness.identity_for_scope(scope, "teacher") == {
        "tenant": "libre_premiere", "niveau": "premiere", "voie": "generale", "matieres": ["hggsp"],
        "statut_enseignement": "specialite", "audience": "libre", "candidat": "libre",
        "school_year": "2026-2027", "role": "teacher",
    }


def test_unissued_teacher_role_is_refused_by_final_scope_policy():
    harness = load_harness()
    scope = {
        "target_policy": {"tenant": "libre_premiere", "niveau": "premiere", "voie": "generale", "matiere": "hggsp", "statut_enseignement": "specialite", "audiences": ["libre"], "candidates": ["libre"], "roles": ["student"]},
        "evidence_subject": {"school_year": "2026-2027", "collection": "rag_nexus_hggsp_premiere_specialite"},
    }
    with pytest.raises(ValueError, match="role"):
        harness.identity_for_scope(scope, "teacher")


@pytest.mark.parametrize(("roles", "student_mode"), [(["student"], "public"), (["student", "teacher"], "public"), (["student", "teacher"], "internal")])
def test_scope_roles_control_live_bff_probes(tmp_path, monkeypatch, roles, student_mode):
    harness = load_harness()
    root = tmp_path
    registry = root / "release-registry.json"
    manifest = root / "release.json"
    scope_index = root / "scopes.json"
    collections = [f"rag_nexus_nsi_collection_{index}" for index in range(11)]
    selected = collections[0]
    release = {"release_id": "student-public-successor-final", "release_mode": "production", "promotion_status": "PROMOTABLE", "activation_status": "PRODUCTION_ACTIVATION_ALLOWED", "review_status": "APPROVED", "subjects": [{"collection": collection, "sha256": "c" * 64} for collection in collections]}
    registry.write_text(json.dumps({"releases": [{"collections": collections, "manifest_path": "release.json", "expected_manifest_sha256": "a" * 64}]}))
    manifest.write_text(json.dumps(release))
    scope_index.write_text("[]")
    scopes = {collection: {"scope_id": f"prod_nsi_collection_{index}_v4", "source_sha256": "c" * 64, "target_policy": {"roles": roles}, "evidence_subject": {"collection": collection}} for index, collection in enumerate(collections)}
    head = "d" * 40
    def fake_git(_root, *args):
        if args == ("status", "--porcelain"):
            return ""
        if args == ("rev-parse", "HEAD^{tree}"):
            return "e" * 40
        return head
    monkeypatch.setattr(harness, "_git", fake_git)
    monkeypatch.setattr(harness, "_live_main_sha", lambda _root: head)
    monkeypatch.setattr(harness, "_sha256", lambda _path: "a" * 64)
    monkeypatch.setattr(harness, "load_final_scopes", lambda *_args: scopes)
    monkeypatch.setattr(harness, "_get_health", lambda _url: (200, {"status": "ok", "build_sha": head}))
    monkeypatch.setattr(harness, "load_release_evidence", lambda *_args: {"placement": {"content_sha256": "b" * 64}})
    minted = []
    def mint(_root, role, _scope):
        minted.append(role)
        if role == "teacher" and "teacher" not in roles:
            raise AssertionError("teacher ne doit pas être signé sur un scope student-only")
        return f"{role}-session", {}
    monkeypatch.setattr(harness, "_mint_session", mint)
    calls = []
    def post(_url, session, _query, collection):
        calls.append((session, collection))
        if session is None:
            return 401, {"error": "unauthorized"}
        if collection != selected:
            return 403, {"error": "forbidden_collection"}
        if session == "student-session" and student_mode == "internal":
            return 200, {"results": []}
        return 200, {"results": [{"citation": {"source_uri": "https://eduscol.education.gouv.fr"}}]}
    monkeypatch.setattr(harness, "_post_search", post)
    monkeypatch.setattr(harness, "assess_positive", lambda *_args, **_kwargs: {"results": 1, "citation_count": 1})
    args = Namespace(repository_root=root, operator_id="test", cockpit_url="http://127.0.0.1:18004", expected_sha=head, scope_index=scope_index, registry=registry, registry_sha256="a" * 64, collection=selected, query="test", student_mode=student_mode)
    report = harness.run(args)
    assert minted == (["student", "teacher"] if "teacher" in roles else ["student"])
    if "teacher" in roles:
        assert calls == [(None, selected), ("teacher-session", collections[1]), ("teacher-session", selected), ("student-session", selected)]
    else:
        assert calls == [(None, selected), ("student-session", collections[1]), ("student-session", selected)]
    assert report["student"] == ({"results": 1, "citation_count": 1} if student_mode == "public" else {"refusal": "empty"})
    assert report["teacher_status"] == (200 if "teacher" in roles else None)
    assert report["teacher_e2e_verified"] is ("teacher" in roles)
    assert report["teacher"] == ({"results": 1, "citation_count": 1} if "teacher" in roles else {"status": "NOT_RUN_SCOPE_ROLE_NOT_ISSUED"})
    assert report["cross_scope_role"] == ("teacher" if "teacher" in roles else "student")
    expected_status = "INTERNAL_STUDENT_REFUSAL_VERIFIED" if student_mode == "internal" else ("VERIFIED" if "teacher" in roles else "STUDENT_ONLY_VERIFIED")
    assert report["verification_status"] == expected_status


def test_rehearsal_and_candidate_releases_cannot_qualify_final_bff():
    harness = load_harness()
    candidate_path = ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_student_public_successor_v1/release-b1dda0c8503aa474/profile_gate/production-profile-gate.release.json"
    candidate = json.loads(candidate_path.read_text())
    rehearsal = {**candidate, "release_id": "profile-gate-v4", "release_mode": "rehearsal"}
    for release in (candidate, rehearsal):
        with pytest.raises(ValueError, match="release.*finale"):
            harness.assert_final_successor_release(release)
    approved = {**candidate, "release_id": "student-public-successor-final-20261010", "release_mode": "production", "promotion_status": "PROMOTABLE", "activation_status": "PRODUCTION_ACTIVATION_ALLOWED", "review_status": "APPROVED"}
    harness.assert_final_successor_release(approved)


def test_public_derivative_requires_exact_sealed_attribution_and_text_only():
    harness = load_harness()
    collection = "rag_nexus_nsi_terminale_specialite"
    candidate = hit(collection)
    candidate["metadata"]["placement_id"] = "placement-1"
    sealed_citation = {
        "source_uri": candidate["citation"]["source_uri"],
        "source_label": candidate["citation"]["source_label"],
        "licensor": "Direction générale de l'enseignement scolaire",
        "licence_id": "ETALAB-2.0",
        "source_updated_at": "2026-10-10T06:04:05Z",
        "derivative_notice": "Extrait textuel dérivé ; PDF non redistribué.",
    }
    sealed = {
        "placement-1": {
            "artifact_id": "b" * 64,
            "content_sha256": "b" * 64,
            "visibility": "public",
            "media_type": "text/plain; charset=utf-8",
            "citation": sealed_citation,
            "source_uri": sealed_citation["source_uri"],
            "source_label": sealed_citation["source_label"],
            "chunks": {"chunk-1": (3, 3)},
        }
    }
    with pytest.raises(ValueError, match="attribution"):
        harness.assess_positive(200, {"results": [candidate]}, collection, {"b" * 64}, sealed, require_public=True)
    candidate["citation"].update({key: sealed_citation[key] for key in ("licensor", "licence_id", "source_updated_at", "derivative_notice")})
    assert harness.assess_positive(200, {"results": [candidate]}, collection, {"b" * 64}, sealed, require_public=True)["results"] == 1
    candidate["citation"]["source_updated_at"] = "2026-10-09"
    with pytest.raises(ValueError, match="attribution"):
        harness.assess_positive(200, {"results": [candidate]}, collection, {"b" * 64}, sealed, require_public=True)
    candidate["citation"]["source_updated_at"] = sealed_citation["source_updated_at"]
    sealed["placement-1"]["media_type"] = "application/pdf"
    with pytest.raises(ValueError, match="textuel"):
        harness.assess_positive(200, {"results": [candidate]}, collection, {"b" * 64}, sealed, require_public=True)


def test_cockpit_url_accepts_only_local_origin_without_credentials_or_query():
    harness = load_harness()
    assert harness.safe_cockpit_url("http://127.0.0.1:18004") == "http://127.0.0.1:18004"
    for url in (
        "https://example.invalid",
        "http://localhost:18004",
        "http://user:secret@127.0.0.1:18004",
        "http://127.0.0.1:18004/?token=secret",
        "http://127.0.0.1:18004/path",
    ):
        with pytest.raises(ValueError, match="Cockpit URL"):
            harness.safe_cockpit_url(url)
    assert harness.RefuseRedirects().redirect_request(None, None, 302, "Found", {}, "https://elsewhere.invalid") is None


def test_deployed_cockpit_must_report_exact_build_sha():
    harness = load_harness()
    sha = "a" * 40
    assert harness.assess_runtime_identity(200, {"status": "ok", "build_sha": sha}, sha) == sha
    for payload in ({"status": "ok"}, {"status": "ok", "build_sha": "b" * 40}):
        with pytest.raises(ValueError, match="build"):
            harness.assess_runtime_identity(200, payload, sha)


def test_signed_claims_validator_requires_expected_role_and_scope():
    harness = load_harness()
    scope = {
        "scope_id": "prod_nsi_terminale_specialite_v3",
        "evidence_subject": {"collection": "rag_nexus_nsi_terminale_specialite"},
    }
    claims = {
        "role": "student",
        "scope_id": scope["scope_id"],
        "scope_digest": harness.canonical_scope_digest(scope),
        "allowed_collections": [scope["evidence_subject"]["collection"]],
    }
    harness.assess_signed_claims(claims, "student", scope)
    with pytest.raises(ValueError, match="role"):
        harness.assess_signed_claims(claims, "teacher", scope)
    with pytest.raises(ValueError, match="scope"):
        harness.assess_signed_claims({**claims, "scope_id": "unknown"}, "student", scope)


def test_release_index_is_bound_to_the_requested_collection():
    harness = load_harness()
    registry = ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json"
    contents = harness.load_release_contents(
        registry,
        "59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6",
        "rag_nexus_nsi_terminale_specialite",
    )
    assert len(contents) == 47


def test_real_release_placement_and_citation_are_checked_together():
    harness = load_harness()
    collection = "rag_nexus_nsi_terminale_specialite"
    registry = ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json"
    evidence = harness.load_release_evidence(
        registry,
        "59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6",
        collection,
    )
    placement_id, sealed = next(iter(evidence.items()))
    chunk_id, pages = next(iter(sealed["chunks"].items()))
    candidate = hit(collection)
    candidate["chunk_id"] = chunk_id
    candidate["doc_id"] = sealed["content_sha256"]
    candidate["metadata"].update({
        "artifact_id": sealed["artifact_id"],
        "content_sha256": sealed["content_sha256"],
        "placement_id": placement_id,
    })
    candidate["citation"].update({
        "source_uri": sealed["source_uri"],
        "source_label": sealed["source_label"],
        "page": pages[0],
    })
    allowed = {item["content_sha256"] for item in evidence.values()}
    assert harness.assess_positive(200, {"results": [candidate]}, collection, allowed, evidence)["results"] == 1
    candidate["metadata"]["placement_id"] = "0" * 64
    with pytest.raises(ValueError, match="placement"):
        harness.assess_positive(200, {"results": [candidate]}, collection, allowed, evidence)
    candidate["metadata"]["placement_id"] = placement_id
    with pytest.raises(ValueError, match="public"):
        harness.assess_positive(200, {"results": [candidate]}, collection, allowed, evidence, require_public=True)
    candidate["metadata"]["content_sha256"] = "c" * 64
    candidate["metadata"]["artifact_id"] = "c" * 64
    candidate["doc_id"] = "c" * 64
    with pytest.raises(ValueError, match="content"):
        harness.assess_positive(200, {"results": [candidate]}, collection, allowed, evidence)


def test_final_release_does_not_contain_the_other_pilot_collection():
    harness = load_harness()
    registry = ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json"
    with pytest.raises(ValueError, match="collection absente"):
        harness.load_release_contents(
            registry,
            "59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6",
            "rag_nexus_maths_terminale_gen_specialite",
        )
