"""Autorisation HGGSP successeur : garde pure et activation après fusion."""

from __future__ import annotations

import copy
import hashlib
import json
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/go_live"))

import check_staging_authorization as auth  # noqa: E402


def _document() -> dict:
    return json.loads((ROOT / auth.AUTORISATION_HGGSP).read_text(encoding="utf-8"))


def test_live_review_transport_uses_get_and_token_file_without_gh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    token_file = tmp_path / "github-token"
    token_file.write_text("test-token-only\n")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("NEXUS_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("NEXUS_GITHUB_TOKEN_FILE", str(token_file))
    commit = "c" * 40
    monkeypatch.setattr(auth, "commit_integration_hggsp", lambda _root: commit)
    monkeypatch.setattr(auth, "evaluer_revue_activation_hggsp", lambda *_a, **_kw: [])
    seen: list[str] = []

    def fake_get(request: object, *, timeout: int) -> object:
        assert timeout == 15
        assert request.get_method() == "GET"
        assert request.get_header("Authorization") == "Bearer test-token-only"
        assert request.get_header("X-github-api-version") == "2022-11-28"
        path = request.full_url
        seen.append(path)
        if path.endswith(f"/commits/{commit}/pulls"):
            response: object = [{"number": 300}]
        elif path.endswith("/pulls/300"):
            response = {"merge_commit_sha": commit, "head": {"sha": "a" * 40}}
        elif path.endswith("/permission"):
            response = {"permission": "write"}
        else:
            response = []

        class Reply:
            def __enter__(self) -> "Reply":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self, _limit: int) -> bytes:
                return json.dumps(response).encode()

        return Reply()

    monkeypatch.setattr(auth.urllib.request, "urlopen", fake_get)
    assert auth.verifier_revue_activation_hggsp(ROOT) == []
    assert len(seen) == 5


def test_image_guard_refuses_pr_branch_and_accepts_exact_merged_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    root = tmp_path / "checkout"
    for relative in auth.FICHIERS_FUSION_HGGSP:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    (root / ".git").mkdir()
    main_sha = "a" * 40
    (root / ".git/HEAD").write_text(main_sha + "\n")
    raw = (root / auth.AUTORISATION_HGGSP).read_bytes()
    blob_sha = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    monkeypatch.setattr(auth, "_jeton_hggsp", lambda: "test-only")
    monkeypatch.setattr(auth, "verifier_revue_activation_hggsp", lambda *_a, **_kw: [])

    def live(endpoint: str, _token: str) -> object:
        if endpoint.endswith("/git/ref/heads/main"):
            return {"object": {"sha": main_sha}}
        if "/contents/" in endpoint:
            return {"type": "file", "sha": blob_sha}
        if "/compare/" in endpoint:
            return {"status": "ahead"}
        if "/commits?" in endpoint:
            return [{"sha": "b" * 40}]
        raise AssertionError(endpoint)

    monkeypatch.setattr(auth, "_api_hggsp", live)
    operation = "successor_publication_job_enqueue"
    target = auth.OPERATIONS_HGGSP[operation]["cible"]
    assert auth.verifier_operation_hggsp_image(root, operation, target) == []
    (root / ".git/HEAD").write_text("c" * 40 + "\n")
    assert "checkout image différent" in str(auth.verifier_operation_hggsp_image(root, operation, target))
    (root / ".git/HEAD").write_text(main_sha + "\n")
    monkeypatch.setattr(auth, "_api_hggsp", lambda endpoint, token: (
        {"type": "file", "sha": "0" * 40} if "/contents/" in endpoint else live(endpoint, token)
    ))
    assert "absente ou divergente" in str(auth.verifier_operation_hggsp_image(root, operation, target))


def test_authority_is_single_and_all_operations_are_separate() -> None:
    assert (ROOT / auth.AUTORISATION_HGGSP).is_file()
    assert not (ROOT / auth.PROPOSITION_HGGSP).exists()
    assert not set(auth.OPERATIONS_HGGSP) & (
        set(auth.OPERATIONS_DI) | set(auth.OPERATIONS_DH) | set(auth.OPERATIONS_V4)
    )
    assert set(_document()["operations"]) == set(auth.OPERATIONS_HGGSP)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("runtime_image", "reference"), "ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:" + "0" * 64),
        (("retrieval_image", "reference"), "ghcr.io/cyranoaladin/rag-ingestor@sha256:" + "0" * 64),
        (("provenance", "run_id"), 1),
        (("provenance", "inventory_file_sha256"), "0" * 64),
        (("release", "manifest_sha256"), "0" * 64),
        (("collection_ownership_registry", "sha256"), "0" * 64),
        (("successor_scope_authority", "premiere"), {"path": "wrong", "sha256": "0" * 64}),
        (("r4_scope_authorizations", "terminale"), {"path": "wrong", "sha256": "0" * 64}),
        (("release", "collections"), ["rag_nexus_hggsp_premiere_specialite", "third"]),
        (("release", "expected_counts"), {"collections": 2, "unique_artifacts": 52, "placements": 73, "unique_chunks": 2590}),
        (("v4_preconditions", "published_counts"), {"collections": 9, "unique_artifacts": 263, "placements": 404, "unique_chunks": 5678}),
        (("v4_preconditions", "old_hggsp_jobs_sha256"), "0" * 64),
        (("v4_preconditions", "review_state"), "CLOSED"),
        (("v4_preconditions", "review_head_sha"), "0" * 40),
        (("v4_preconditions", "review_decision"), "CHANGES_REQUESTED"),
        (("v4_preconditions", "successor_jobs_after_enqueue"), 73),
        (("v4_preconditions", "successor_jobs_after_enqueue"), 75),
        (("targets", "database"), "ragdb"),
    ],
)
def test_tampering_is_refused(path: tuple[str, str], replacement: object) -> None:
    doc = copy.deepcopy(_document())
    doc[path[0]][path[1]] = replacement
    assert auth.evaluer_hggsp(ROOT, doc)


def test_readiness_and_worker_are_restricted_to_successor() -> None:
    doc = _document()
    assert doc["runtime_image"]["reference"].endswith(
        "@sha256:318ef58490e8de66a3f0bb0bea4d147cb1a700eaa6648a6b374c940e7b8fc222"
    )
    assert doc["retrieval_image"]["reference"].endswith(
        "@sha256:90cba4293be3a74ff333ea0a3e8c1c2dcc66d8e4ce4c8f8d35df1e887f172abb"
    )
    assert auth.OPERATIONS_HGGSP["successor_worker_b_publication"]["cible"]["claimed_collections"] == [
        "rag_nexus_hggsp_premiere_specialite", "rag_nexus_hggsp_terminale_specialite"
    ]
    assert "hggsp_job_claim" not in doc["operations"]
    for forbidden in ("v4_405_placement_adoption_or_republication", "v4_hggsp_job_claim_or_mutation", "manual_job_sql", "current_switch", "public_exposure", "production_image_rebuild_on_host"):
        assert forbidden in doc["forbidden"]


def test_provenance_is_the_new_build_from_merged_runtime() -> None:
    document = _document()
    proof = json.loads((ROOT / auth.PREUVE_HGGSP).read_text(encoding="utf-8"))
    assert document["base_commit_sha"] == proof["source_commit_sha"] == (
        "242d267046f1e9200b009e664410bc7b40816fae"
    )
    assert document["provenance"]["run_id"] == proof["workflow_run_id"] == 37063628014
    assert document["provenance"]["artifact_id"] == proof["artifact_id"] == 11251726187
    assert document["provenance"]["inventory_file_sha256"] == proof["inventory_file_sha256"] == (
        "fa8406bb589aec405ca75e2bacd4282469fadc7c1358159827c337e06a7cf84f"
    )
    assert document["provenance"]["artifact_zip_sha256"] == proof["artifact_zip_sha256"] == (
        "989fd82afa4b0f5dca2f170e9ebd899d33d2fe5b69155c819c490acc0bb88691"
    )
    assert auth.evaluer_hggsp(ROOT, document) == []


def _simulated_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, merged: bool) -> Path:
    root = tmp_path / "checkout"
    paths = auth.FICHIERS_FUSION_HGGSP
    for relative in paths:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    monkeypatch.setattr(auth, "verifier", lambda _root: [])

    def fake_git(_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if args[:1] == ("show",) and args[1].startswith("origin/main:"):
            relative = args[1].split(":", 1)[1]
            if merged:
                return subprocess.CompletedProcess(args, 0, (root / relative).read_text(), "")
            return subprocess.CompletedProcess(args, 128, "", "not on main")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(auth, "_git", fake_git)
    monkeypatch.setattr(auth, "verifier_revue_activation_hggsp", lambda _root: [])
    return root


def test_merged_pr_requires_exact_head_canonical_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    build_challenge = runpy.run_path(
        str(ROOT / "scripts/github/trusted_human_review.py")
    )["build_challenge"]

    head, base = "a" * 40, "b" * 40
    challenge = build_challenge({
        "repository": "cyranoaladin/RAG", "pull_request": 300,
        "base_ref": "main", "base_sha": base, "head_sha": head,
        "author": "author", "reviewer": "abenrhouma",
        "protocol": "NEXUS-TRUSTED-REVIEW-V1",
    })
    pr = {
        "number": 300, "merged": True, "state": "closed", "draft": False,
        "base": {"ref": "main", "sha": base},
        "head": {"sha": head, "repo": {"full_name": "cyranoaladin/RAG"}},
        "user": {"login": "author"}, "merge_commit_sha": "c" * 40,
        "merged_at": "2026-09-28T20:10:00Z",
    }
    review = {"id": 1, "state": "APPROVED", "body": challenge,
              "commit_id": head, "submitted_at": "2026-09-28T20:00:00Z",
              "user": {"login": "abenrhouma"}}
    statuses = [{"context": "trusted-human-review/head-pinned", "state": "success",
                 "creator": {"login": "github-actions[bot]"},
                 "created_at": "2026-09-28T20:05:00Z"}]
    permission = {"permission": "write", "role_name": "write"}
    assert auth.evaluer_revue_activation_hggsp(pr, [review], statuses, permission) == []
    assert auth.evaluer_revue_activation_hggsp(pr, [{**review, "commit_id": "d" * 40}], statuses, permission)
    assert auth.evaluer_revue_activation_hggsp(pr, [{**review, "body": "wrong"}], statuses, permission)
    assert auth.evaluer_revue_activation_hggsp({**pr, "merged": False}, [review], statuses, permission)
    assert auth.evaluer_revue_activation_hggsp(pr, [review], [{**statuses[0], "state": "failure"}], permission)
    assert auth.evaluer_revue_activation_hggsp(
        pr, [review], [{**statuses[0], "state": "failure", "created_at": "2026-09-28T20:20:00Z"}, *statuses], permission
    ) == [], "une réévaluation après fusion ne retire pas la preuve du statut vert avant fusion"


@pytest.mark.parametrize("strategy", ["squash", "merge_commit", "rename"])
def test_activation_commit_is_first_parent_integration(
    tmp_path: Path, strategy: str
) -> None:
    """Une fusion à deux parents ne doit pas donner le commit de la branche."""
    root = tmp_path / "disposable-git"
    root.mkdir()

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True, check=True
        )
        return result.stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (root / "base.txt").write_text("base\n")
    git("add", "base.txt")
    git("commit", "-q", "-m", "base")
    if strategy == "rename":
        proposed = root / auth.PROPOSITION_HGGSP
        proposed.parent.mkdir(parents=True)
        proposed.write_text("{}\n")
        git("add", auth.PROPOSITION_HGGSP)
        git("commit", "-q", "-m", "inactive proposal")
    git("checkout", "-q", "-b", "activation")
    target = root / auth.AUTORISATION_HGGSP
    target.parent.mkdir(parents=True, exist_ok=True)
    if strategy == "rename":
        git("mv", auth.PROPOSITION_HGGSP, auth.AUTORISATION_HGGSP)
    else:
        target.write_text("{}\n")
        git("add", auth.AUTORISATION_HGGSP)
    git("commit", "-q", "-m", "activate")
    feature_commit = git("rev-parse", "HEAD")
    git("checkout", "-q", "main")
    if strategy == "squash":
        git("merge", "--squash", "activation")
        git("commit", "-q", "-m", "squash activation")
    else:
        git("merge", "--no-ff", "-m", "merge activation", "activation")
    integration_commit = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/main", integration_commit)
    assert integration_commit != feature_commit
    assert auth.commit_integration_hggsp(root) == integration_commit


@pytest.mark.parametrize("operation", list(auth.OPERATIONS_HGGSP))
def test_each_operation_is_closed_before_merge_and_opens_on_exact_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    target = copy.deepcopy(auth.OPERATIONS_HGGSP[operation]["cible"])
    root = _simulated_checkout(tmp_path, monkeypatch, merged=False)
    assert any("origin/main" in error for error in auth.verifier_operation_hggsp(root, operation, target))
    root = _simulated_checkout(tmp_path, monkeypatch, merged=True)
    assert auth.verifier_operation_hggsp(root, operation, target) == []


def test_matching_files_on_main_do_not_authorize_a_different_local_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _simulated_checkout(tmp_path, monkeypatch, merged=True)
    original = auth._git

    def different_head(checkout: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if args == ("rev-parse", "HEAD"):
            return subprocess.CompletedProcess(args, 0, "a" * 40 + "\n", "")
        if args == ("rev-parse", "origin/main"):
            return subprocess.CompletedProcess(args, 0, "b" * 40 + "\n", "")
        return original(checkout, *args)

    monkeypatch.setattr(auth, "_git", different_head)
    operation = "successor_preflight"
    errors = auth.verifier_operation_hggsp(
        root, operation, auth.OPERATIONS_HGGSP[operation]["cible"]
    )
    assert "HGGSP : HEAD local différent de origin/main" in errors


def test_runtime_source_commit_must_be_in_main_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _simulated_checkout(tmp_path, monkeypatch, merged=True)
    original = auth._git

    def missing_source(checkout: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if args[:2] == ("merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(args, 1, "", "")
        return original(checkout, *args)

    monkeypatch.setattr(auth, "_git", missing_source)
    operation = "successor_preflight"
    errors = auth.verifier_operation_hggsp(
        root, operation, auth.OPERATIONS_HGGSP[operation]["cible"]
    )
    assert "HGGSP : commit source des images absent de origin/main" in errors


@pytest.mark.parametrize(
    ("operation", "key", "bad"),
    [
        ("successor_worker_b_publication", "claimed_collections", ["rag_nexus_svt_terminale_specialite"]),
        ("successor_worker_b_publication", "worker_image", "ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:" + "0" * 64),
        ("successor_independent_verification", "expected_successor_counts", {"collections": 2, "unique_artifacts": 52, "placements": 73, "unique_chunks": 2590}),
    ],
)
def test_exact_target_rejects_non_hggsp_claim_or_wrong_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, key: str, bad: object
) -> None:
    root = _simulated_checkout(tmp_path, monkeypatch, merged=True)
    target = copy.deepcopy(auth.OPERATIONS_HGGSP[operation]["cible"])
    target[key] = bad
    assert auth.verifier_operation_hggsp(root, operation, target)


@pytest.mark.parametrize(
    ("cle", "valeur"),
    [
        ("from_head", 18), ("to_head", 21), ("role", "ingestion_control_attestor"),
        ("database", "ragdb"),
        ("historical_roles", "realigned"),
    ],
)
def test_control_020_scope_tampering_is_refused(cle: str, valeur: object) -> None:
    doc = copy.deepcopy(_document())
    doc["control_schema_020"][cle] = valeur
    assert "HGGSP : périmètre de la migration 020 et du rôle adopter incorrect" in auth.evaluer_hggsp(ROOT, doc)


def test_control_020_binds_exact_bytes_of_migration_provisioner_and_operation() -> None:
    doc = _document()
    for binding in ("migration", "provisioner", "operation"):
        lien = doc["control_schema_020"][binding]
        assert hashlib.sha256((ROOT / lien["path"]).read_bytes()).hexdigest() == lien["sha256"]
        assert lien["path"] in auth.FICHIERS_FUSION_HGGSP
    assert auth.OPERATIONS_HGGSP["successor_control_schema_020_and_adopter_role"]["cible"]["to_head"] == 20
    for interdit in ("historical_role_password_rotation", "adopter_password_reset",
                     "control_schema_migration_beyond_020", "product_schema_migration"):
        assert interdit in doc["forbidden"]


# ── amendement du runtime après #279 : supersession bornée et cohérente ────────


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.pop("amendment"),
        lambda d: d["amendment"].update(triggered_by_pull_request=278),
        lambda d: d["amendment"]["superseded_runtime"].update(provenance_run_id=1),
        lambda d: d["amendment"]["superseded_runtime"]["readiness"].update(manifest_sha256="0" * 64),
        lambda d: d["amendment"]["superseded_runtime"]["readiness"].update(binding_sha256="0" * 64),
        lambda d: d["amendment"]["superseded_runtime"]["readiness"].pop("binding_sha256"),
        lambda d: d["amendment"]["superseded_runtime"].update(runtime_image="ghcr.io/x/y@sha256:" + "0" * 64),
        lambda d: d["amendment"].update(carried_over_operations=["successor_control_schema_020_and_adopter_role"]),
        lambda d: d["amendment"].update(renewed_operations=["successor_readiness_install"]),
        lambda d: d["amendment"]["carried_over_operations"].append("successor_attestations"),
        lambda d: d["amendment"].update(not_performed_operations=[]),
        lambda d: d["amendment"].update(extra="un champ non prévu"),
    ],
    ids=["absent", "pr", "run", "pin-manifeste", "pin-liaison", "pin-liaison-absent", "image", "report-020-seul",
         "renouvele-incomplet", "report-attestations", "non-effectue-vide", "champ-en-trop"],
)
def test_amendment_tampering_is_refused(mutation: object) -> None:
    doc = copy.deepcopy(_document())
    mutation(doc)  # type: ignore[operator]
    assert any("amendement" in ecart for ecart in auth.evaluer_hggsp(ROOT, doc))


def test_amendment_supersedes_exactly_the_previous_runtime_and_not_the_current_one() -> None:
    doc = _document()
    ancien = doc["amendment"]["superseded_runtime"]
    # La cible de la supersession est EXACTEMENT le runtime et la readiness installés par #270 (valeurs
    # figées ici : un autre run, une autre image ou une autre paire ne doit jamais devenir la cible).
    assert ancien == {
        "provenance_run_id": 36633288414,
        "source_commit_sha": "a9e3701965503d2862a248c46fd7e7e175058c8f",
        "runtime_image": "ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:"
                         "2228650e2245ea2fdc45d442a78363fd362781c2f80e2270618eedca0abf9bcf",
        "retrieval_image": "ghcr.io/cyranoaladin/rag-ingestor@sha256:"
                           "11aa98d58ebcd10ee09543d4791f63b67542b764ab0484f004cccc8d43e86caf",
        "readiness": {
            "manifest_sha256": "70fb399bf4fd005760bb141e5717e9a68329b0f7681c49f44eddeddd07c67c01",
            "binding_sha256": "ed8d08141f7b2ef5becda2760b692974b92940ea1382139dea828b1b64b7fb01",
        },
    }
    assert ancien["runtime_image"] != doc["runtime_image"]["reference"]
    assert ancien["retrieval_image"] != doc["retrieval_image"]["reference"]
    assert ancien["provenance_run_id"] != doc["provenance"]["run_id"]
    assert ancien["source_commit_sha"] != doc["base_commit_sha"]
    assert doc["amendment"]["amends_pull_request"] == 270 and doc["amendment"]["triggered_by_pull_request"] == 279


def test_amendment_partitions_operations_without_marking_unperformed_ones_done() -> None:
    doc = _document()
    amendement = doc["amendment"]
    groupes = [amendement["carried_over_operations"], amendement["renewed_operations"],
               amendement["not_performed_operations"]]
    tous = sum(groupes, [])
    # exactement les opérations, sauf la signature locale de la readiness (qui n'est dans aucun groupe)
    assert set(tous) == set(doc["operations"]) - {"successor_readiness_sign"}
    assert "successor_readiness_sign" not in tous
    assert len(tous) == len(set(tous))  # une opération dans un seul groupe
    # les faits persistants sont exactement la migration 020 et les r4 ; rien d'autre n'est reporté
    assert amendement["carried_over_operations"] == [
        "successor_control_schema_020_and_adopter_role", "successor_scope_authorization_registration_r4"]
    assert amendement["renewed_operations"] == ["successor_readiness_install", "successor_preflight"]
    for jamais_fait in ("successor_sealed_ingestion_or_binding", "successor_batch_review_proposal",
                        "successor_attestations", "successor_publication_job_enqueue",
                        "successor_worker_b_publication", "successor_independent_verification"):
        assert jamais_fait in amendement["not_performed_operations"]


def test_the_images_pinned_by_the_orchestrator_and_the_readiness_follow_the_authorization() -> None:
    doc = _document()
    runtime, retrieval = doc["runtime_image"]["reference"], doc["retrieval_image"]["reference"]
    orchestrateur = (ROOT / "scripts/go_live/staging_hggsp_complementary.sh").read_text(encoding="utf-8")
    readiness = (ROOT / "scripts/go_live/hggsp_successor_readiness.py").read_text(encoding="utf-8")
    plan = (ROOT / auth.PLAN_HGGSP).read_text(encoding="utf-8")
    for source in (orchestrateur, readiness, plan):
        assert runtime in source and retrieval in source
    assert f'SOURCE_COMMIT = "{doc["base_commit_sha"]}"' in readiness
    # aucune trace de l'ancien runtime comme runtime courant
    ancien = doc["amendment"]["superseded_runtime"]
    for source in (orchestrateur, readiness):
        assert ancien["runtime_image"] not in source and ancien["retrieval_image"] not in source
    assert str(doc["provenance"]["run_id"]) in plan and str(ancien["provenance_run_id"]) in plan
