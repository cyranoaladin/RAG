"""Câblage fail-closed des CLIs multi-collections."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from ingestor.ingestion_worker import (
    multilevel_cli,
    multilevel_publication_resume_cli,
    multilevel_runtime_authority,
)
from ingestor.ingestion_worker.runtime_authority import RuntimeAuthorityStartupError

SHA = "a" * 64


def _authority_args() -> list[str]:
    return [
        "--candidate-inventory-path",
        "/proof/inventory.json",
        "--candidate-inventory-sha256",
        SHA,
        "--currentness-evidence-path",
        "/proof/currentness.yml",
        "--currentness-evidence-sha256",
        SHA,
        "--levels-mapping-path",
        "/proof/levels.yml",
        "--levels-mapping-sha256",
        SHA,
        "--subjects-mapping-path",
        "/proof/subjects.yml",
        "--subjects-mapping-sha256",
        SHA,
        "--document-types-mapping-path",
        "/proof/document-types.yml",
        "--document-types-mapping-sha256",
        SHA,
        "--release-manifest-path",
        "/proof/multilevel.release.json",
        "--release-manifest-sha256",
        SHA,
        "--programme-registry-path",
        "/proof/programmes.yml",
        "--programme-registry-sha256",
        SHA,
        "--profile-manifest-path",
        "/proof/profiles.json",
        "--profile-manifest-sha256",
        SHA,
        "--collection-config-path",
        "/proof/collections.yml",
        "--collection-config-sha256",
        SHA,
        "--pii-evidence-path",
        "/proof/pii.json",
        "--pii-evidence-sha256",
        SHA,
        "--rights-evidence-path",
        "/proof/rights.yml",
        "--rights-evidence-sha256",
        SHA,
        "--corpus-manifest-sha256",
        SHA,
        "--repository-root",
        "/repo",
    ]


def _worker_a_args() -> list[str]:
    return [
        "--profiles-dir",
        "/proof/profiles",
        "--artifact-store-dir",
        "/artifacts",
        "--owner",
        "worker-a",
        "--expected-role",
        "ingestion_control_app",
        "--once",
        *_authority_args(),
    ]


def _worker_b_args() -> list[str]:
    return [
        "--profiles-dir",
        "/proof/profiles",
        "--artifact-store-dir",
        "/artifacts",
        "--owner",
        "worker-b",
        "--expected-role",
        "ingestion_control_app",
        "--embedding-artifact-root",
        "/models/e5",
        "--embedding-inventory-sha256",
        SHA,
        "--once",
        *_authority_args(),
    ]


def test_multilevel_runtime_parser_builds_every_digest_bound_input() -> None:
    parser = multilevel_cli._build_arg_parser()
    args = parser.parse_args(_worker_a_args())

    inputs = multilevel_runtime_authority.multilevel_runtime_authority_inputs_from_args(args)

    assert inputs.release_manifest_path == Path("/proof/multilevel.release.json")
    assert inputs.release_manifest_sha256 == SHA
    assert inputs.profile_manifest_sha256 == SHA
    assert inputs.programme_registry_sha256 == SHA
    assert inputs.repository_root == Path("/repo")


@pytest.mark.parametrize(
    "required_option",
    [
        "--release-manifest-sha256",
        "--profile-manifest-sha256",
        "--currentness-evidence-sha256",
        "--pii-evidence-sha256",
        "--rights-evidence-sha256",
        "--programme-registry-sha256",
    ],
)
@pytest.mark.parametrize("worker", ["a", "b"])
def test_cli_rejects_missing_authority_digest_before_runtime(
    required_option: str,
    worker: str,
) -> None:
    parser = (
        multilevel_cli._build_arg_parser()
        if worker == "a"
        else multilevel_publication_resume_cli._build_arg_parser()
    )
    args = _worker_a_args() if worker == "a" else _worker_b_args()
    index = args.index(required_option)
    del args[index : index + 2]

    with pytest.raises(SystemExit):
        parser.parse_args(args)


def test_worker_a_authority_drift_fails_before_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connected = False

    def connect(*_args: object, **_kwargs: object) -> None:
        nonlocal connected
        connected = True
        raise AssertionError("PostgreSQL must not be opened")

    monkeypatch.setattr(
        multilevel_cli,
        "enforce_readiness_gate",
        lambda: type("Readiness", (), {"environment": "rehearsal"})(),
    )
    monkeypatch.setattr(multilevel_cli, "load_profile_registry", lambda _path: {})
    monkeypatch.setattr(
        multilevel_cli,
        "load_multilevel_runtime_authorities",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeAuthorityStartupError("aggregate digest differs")
        ),
    )
    monkeypatch.setattr(multilevel_cli.psycopg, "connect", connect)

    assert multilevel_cli.main(_worker_a_args()) == 1
    assert connected is False


@pytest.mark.parametrize(
    ("module", "args"),
    [
        (multilevel_cli, _worker_a_args),
        (multilevel_publication_resume_cli, _worker_b_args),
    ],
)
def test_multilevel_cli_rejects_non_rehearsal_before_authority_and_postgres(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    args: Callable[[], list[str]],
) -> None:
    authority_loaded = False
    connected = False

    def load_authority(*_args: object, **_kwargs: object) -> None:
        nonlocal authority_loaded
        authority_loaded = True
        raise AssertionError("authority must not be loaded outside rehearsal")

    def connect(*_args: object, **_kwargs: object) -> None:
        nonlocal connected
        connected = True
        raise AssertionError("PostgreSQL must not be opened")

    monkeypatch.setattr(
        module,
        "enforce_readiness_gate",
        lambda: type("Readiness", (), {"environment": "production"})(),
    )
    monkeypatch.setattr(module, "load_multilevel_runtime_authorities", load_authority)
    monkeypatch.setattr(module.psycopg, "connect", connect)

    assert module.main(args()) == 1
    assert authority_loaded is False
    assert connected is False


def test_worker_b_model_drift_fails_before_model_load_and_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = type(
        "Resolver",
        (),
        {
            "release_embedding_model_id": "intfloat/multilingual-e5-large",
            "release_embedding_dimension": 1024,
            "release_embedding_inventory_sha256": "b" * 64,
        },
    )()
    authorities = type("Authorities", (), {"placement_resolver": resolver})()
    model_loaded = False
    connected = False

    def load_model(**_kwargs: object) -> None:
        nonlocal model_loaded
        model_loaded = True
        raise AssertionError("model must not be loaded")

    def connect(*_args: object, **_kwargs: object) -> None:
        nonlocal connected
        connected = True
        raise AssertionError("PostgreSQL must not be opened")

    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "enforce_readiness_gate",
        lambda: type("Readiness", (), {"environment": "rehearsal"})(),
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "load_profile_registry",
        lambda _path: {},
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "load_multilevel_runtime_authorities",
        lambda *_args, **_kwargs: authorities,
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli.VerifiedE5EmbeddingProvider,
        "from_artifact",
        load_model,
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli.psycopg,
        "connect",
        connect,
    )
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://unused")

    assert multilevel_publication_resume_cli.main(_worker_b_args()) == 1
    assert model_loaded is False
    assert connected is False


def test_multilevel_cli_modules_contain_no_content_sha_allowlist() -> None:
    modules = (
        multilevel_cli,
        multilevel_publication_resume_cli,
        multilevel_runtime_authority,
    )
    assert all(module.__file__ is not None for module in modules)
    sources = "\n".join(
        Path(str(module.__file__)).read_text(encoding="utf-8") for module in modules
    )

    assert "49ccdca4" not in sources
    assert "c8662b03" not in sources
    assert "d0edabd6" not in sources


@pytest.mark.parametrize(
    "module",
    [multilevel_cli, multilevel_publication_resume_cli],
)
def test_multilevel_cli_logs_staging_authority_without_human_claim(
    module: ModuleType,
) -> None:
    assert module.__file__ is not None
    source = Path(module.__file__).read_text(encoding="utf-8")

    assert "authority_mode=STAGING_LOCAL_GITHUB_ONLY" in source
    assert "production_approval=false" in source
    assert "approved_by" not in source
