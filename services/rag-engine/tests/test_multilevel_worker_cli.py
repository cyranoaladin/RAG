"""Câblage fail-closed des CLIs multi-collections."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from ingestor.ingestion_control.revocation_registry import RevocationRegistryError
from ingestor.ingestion_worker import (
    multilevel_cli,
    multilevel_publication_resume_cli,
    multilevel_runtime_authority,
)
from ingestor.ingestion_worker.runtime_authority import RuntimeAuthorityStartupError
from ingestor.release_readiness import ReleaseReadinessError

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


def test_worker_b_production_model_drift_fails_before_model_load_and_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same guarantee as the rehearsal test above, exercised in production:
    the embedding-model cross-check against the release manifest is
    unconditional (not gated by environment), so a drifted model still
    fails before Worker B ever loads it or opens PostgreSQL — even once
    all of the production-only evidence (release/revocation registries,
    product-role attestation) has already been satisfied."""
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
    connected_dsns: list[str] = []

    class _AttestOnlyConn:
        def __enter__(self) -> _AttestOnlyConn:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    def load_model(**_kwargs: object) -> None:
        nonlocal model_loaded
        model_loaded = True
        raise AssertionError("model must not be loaded")

    def connect(dsn: str, *_args: object, **_kwargs: object) -> _AttestOnlyConn:
        # The production evidence gate legitimately opens ONE connection —
        # to the product DSN, for role attestation — before authority/model
        # loading. What must never happen is a SECOND connection, to the
        # ingestion-control DSN, which only main()'s outer `with psycopg.
        # connect(...)` (reached after model loading) would open.
        connected_dsns.append(dsn)
        if dsn == "postgresql://ingestion-control":
            raise AssertionError("ingestion-control PostgreSQL must not be opened")
        return _AttestOnlyConn()

    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "enforce_readiness_gate",
        lambda: _production_readiness(),
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "load_release_registry_file",
        lambda *_a, **_k: object(),
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "load_revocation_registry",
        lambda *_a, **_k: object(),
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "require_revocation_registry_matches_manifest",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "get_ingestion_control_dsn",
        lambda: "postgresql://ingestion-control",
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "attest_runtime_role",
        lambda _conn, *, expected_role: None,
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli.psycopg,
        "connect",
        connect,
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
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://product")

    args = _worker_b_args() + [
        "--release-registry-path",
        "/proof/release-registry.json",
        "--release-registry-sha256",
        SHA,
        "--revocation-registry-path",
        "/proof/revocation-registry.json",
        "--revocation-registry-sha256",
        SHA,
        "--expected-product-role",
        "rag_publisher",
    ]

    assert multilevel_publication_resume_cli.main(args) == 1
    assert model_loaded is False
    assert connected_dsns == ["postgresql://product"]


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


# --- Production evidence gate (LOT H2-B remediation, finding P1-workers) ---


def _production_readiness(revocation_digest: str = SHA) -> object:
    manifest = type("Manifest", (), {"revocation_registry_digest": revocation_digest})()
    return type("Readiness", (), {"environment": "production", "manifest": manifest})()


def _production_args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "release_registry_path": Path("/proof/release-registry.json"),
        "release_registry_sha256": SHA,
        "revocation_registry_path": Path("/proof/revocation-registry.json"),
        "revocation_registry_sha256": SHA,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


@pytest.mark.parametrize("module", [multilevel_cli, multilevel_publication_resume_cli])
def test_enforce_production_evidence_requires_release_registry(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        module,
        "load_release_registry_file",
        lambda *_a, **_k: pytest.fail("release registry must not be loaded"),
    )
    args = _production_args(release_registry_path=None, release_registry_sha256=None)
    call = (
        (lambda: module._enforce_production_evidence(args, _production_readiness()))
        if module is multilevel_cli
        else (
            lambda: module._enforce_production_evidence(
                args, _production_readiness(), product_dsn="postgresql://product"
            )
        )
    )

    with pytest.raises(RuntimeAuthorityStartupError, match="release registry"):
        call()


@pytest.mark.parametrize("module", [multilevel_cli, multilevel_publication_resume_cli])
def test_enforce_production_evidence_refuses_release_registry_that_fails_to_load(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        module,
        "load_release_registry_file",
        lambda *_a, **_k: (_ for _ in ()).throw(
            ReleaseReadinessError("release registry digest mismatch")
        ),
    )
    args = _production_args()
    call = (
        (lambda: module._enforce_production_evidence(args, _production_readiness()))
        if module is multilevel_cli
        else (
            lambda: module._enforce_production_evidence(
                args, _production_readiness(), product_dsn="postgresql://product"
            )
        )
    )

    with pytest.raises(ReleaseReadinessError, match="digest mismatch"):
        call()


@pytest.mark.parametrize("module", [multilevel_cli, multilevel_publication_resume_cli])
def test_enforce_production_evidence_requires_revocation_registry(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "load_release_registry_file", lambda *_a, **_k: object())
    args = _production_args(revocation_registry_path=None, revocation_registry_sha256=None)
    call = (
        (lambda: module._enforce_production_evidence(args, _production_readiness()))
        if module is multilevel_cli
        else (
            lambda: module._enforce_production_evidence(
                args, _production_readiness(), product_dsn="postgresql://product"
            )
        )
    )

    with pytest.raises(RuntimeAuthorityStartupError, match="revocation registry"):
        call()


@pytest.mark.parametrize("module", [multilevel_cli, multilevel_publication_resume_cli])
def test_enforce_production_evidence_refuses_revocation_registry_digest_drift(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module, "load_release_registry_file", lambda *_a, **_k: object())
    monkeypatch.setattr(
        module,
        "load_revocation_registry",
        lambda *_a, **_k: object(),
    )
    # The registry's own digest ("expected" side) never matches the
    # manifest's pinned "b"*64 here — the real cross-check lives in
    # ``require_revocation_registry_matches_manifest`` (see
    # test_revocation_registry.py); this exercises the CLI wiring only.
    monkeypatch.setattr(
        module,
        "require_revocation_registry_matches_manifest",
        lambda *_a, **_k: (_ for _ in ()).throw(
            RevocationRegistryError("revocation registry digest does not match")
        ),
    )
    args = _production_args()
    call = (
        (lambda: module._enforce_production_evidence(args, _production_readiness()))
        if module is multilevel_cli
        else (
            lambda: module._enforce_production_evidence(
                args, _production_readiness(), product_dsn="postgresql://product"
            )
        )
    )

    with pytest.raises(RevocationRegistryError, match="does not match"):
        call()


def test_worker_b_enforce_production_evidence_requires_expected_product_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        multilevel_publication_resume_cli, "load_release_registry_file", lambda *_a, **_k: object()
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "load_revocation_registry",
        lambda *_a, **_k: object(),
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "require_revocation_registry_matches_manifest",
        lambda *_a, **_k: None,
    )
    args = _production_args(expected_product_role=None)

    with pytest.raises(RuntimeAuthorityStartupError, match="expected-product-role"):
        multilevel_publication_resume_cli._enforce_production_evidence(
            args, _production_readiness(), product_dsn="postgresql://product"
        )


def test_worker_b_enforce_production_evidence_refuses_shared_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        multilevel_publication_resume_cli, "load_release_registry_file", lambda *_a, **_k: object()
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "load_revocation_registry",
        lambda *_a, **_k: object(),
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "require_revocation_registry_matches_manifest",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "get_ingestion_control_dsn",
        lambda: "postgresql://shared",
    )
    args = _production_args(expected_product_role="rag_publisher")

    with pytest.raises(RuntimeAuthorityStartupError, match="distinct"):
        multilevel_publication_resume_cli._enforce_production_evidence(
            args, _production_readiness(), product_dsn="postgresql://shared"
        )


def test_worker_b_enforce_production_evidence_attests_the_product_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        multilevel_publication_resume_cli, "load_release_registry_file", lambda *_a, **_k: object()
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "load_revocation_registry",
        lambda *_a, **_k: object(),
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "require_revocation_registry_matches_manifest",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "get_ingestion_control_dsn",
        lambda: "postgresql://ingestion-control",
    )
    attested: list[str] = []

    class _Conn:
        def __enter__(self) -> _Conn:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(
        multilevel_publication_resume_cli.psycopg,
        "connect",
        lambda dsn: _Conn(),
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "attest_runtime_role",
        lambda _conn, *, expected_role: attested.append(expected_role),
    )
    args = _production_args(expected_product_role="rag_publisher")

    multilevel_publication_resume_cli._enforce_production_evidence(
        args, _production_readiness(), product_dsn="postgresql://product"
    )

    assert attested == ["rag_publisher"]


@pytest.mark.parametrize(
    ("module", "args_factory"),
    [
        (multilevel_cli, _worker_a_args),
        (multilevel_publication_resume_cli, _worker_b_args),
    ],
)
def test_production_without_registry_flags_fails_before_authority_and_postgres(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    args_factory: Callable[[], list[str]],
) -> None:
    """The gate itself already refuses production without a provisioned
    trust anchor (``PRODUCTION_TRUST_ANCHOR_PROVISIONED=false`` today), so
    this exercises the next layer down: even a caller that *did* clear the
    gate must still supply the release and revocation registries before
    either worker touches authority loading or PostgreSQL."""
    authority_loaded = False
    connected = False

    def load_authority(*_args: object, **_kwargs: object) -> None:
        nonlocal authority_loaded
        authority_loaded = True
        raise AssertionError("authority must not be loaded without production evidence")

    def connect(*_args: object, **_kwargs: object) -> None:
        nonlocal connected
        connected = True
        raise AssertionError("PostgreSQL must not be opened")

    monkeypatch.setattr(module, "enforce_readiness_gate", lambda: _production_readiness())
    monkeypatch.setattr(module, "load_multilevel_runtime_authorities", load_authority)
    monkeypatch.setattr(module.psycopg, "connect", connect)
    if module is multilevel_publication_resume_cli:
        monkeypatch.setenv("PG_RAG_DSN", "postgresql://product")

    assert module.main(args_factory()) == 1
    assert authority_loaded is False
    assert connected is False


def test_worker_a_production_with_full_evidence_reaches_postgres_connect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connected = False
    resolver = type("Resolver", (), {"release_profile_manifest_digest": SHA})()
    authorities = type(
        "Authorities",
        (),
        {
            "placement_resolver": resolver,
            "pii_evidence_registry": object(),
            "rights_evidence_registry": object(),
        },
    )()

    def connect(*_args: object, **_kwargs: object) -> None:
        nonlocal connected
        connected = True
        raise RuntimeAuthorityStartupError("test boundary: stop right after connect")

    monkeypatch.setattr(multilevel_cli, "enforce_readiness_gate", lambda: _production_readiness())
    monkeypatch.setattr(multilevel_cli, "load_release_registry_file", lambda *_a, **_k: object())
    monkeypatch.setattr(
        multilevel_cli, "load_revocation_registry", lambda *_a, **_k: object()
    )
    monkeypatch.setattr(
        multilevel_cli,
        "require_revocation_registry_matches_manifest",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(multilevel_cli, "load_profile_registry", lambda _path: {})
    monkeypatch.setattr(
        multilevel_cli,
        "load_multilevel_runtime_authorities",
        lambda *_args, **_kwargs: authorities,
    )
    monkeypatch.setattr(multilevel_cli.psycopg, "connect", connect)
    monkeypatch.setenv("PG_INGESTION_CONTROL_DSN", "postgresql://ingestion-control")

    args = _worker_a_args()
    index = args.index("--artifact-store-dir")
    args[index + 1] = str(tmp_path)
    args += [
        "--release-registry-path",
        "/proof/release-registry.json",
        "--release-registry-sha256",
        SHA,
        "--revocation-registry-path",
        "/proof/revocation-registry.json",
        "--revocation-registry-sha256",
        SHA,
    ]

    assert multilevel_cli.main(args) == 1
    assert connected is True


def test_worker_b_production_with_full_evidence_reaches_model_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_loaded = False

    def load_model(**_kwargs: object) -> None:
        nonlocal model_loaded
        model_loaded = True
        raise AssertionError("test boundary: stop right after model load is attempted")

    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "enforce_readiness_gate",
        lambda: _production_readiness(),
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "load_release_registry_file",
        lambda *_a, **_k: object(),
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "load_revocation_registry",
        lambda *_a, **_k: object(),
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "require_revocation_registry_matches_manifest",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "get_ingestion_control_dsn",
        lambda: "postgresql://ingestion-control",
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "attest_runtime_role",
        lambda _conn, *, expected_role: None,
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli.psycopg,
        "connect",
        lambda dsn: _NullConn(),
    )
    monkeypatch.setattr(
        multilevel_publication_resume_cli,
        "load_profile_registry",
        lambda _path: {},
    )
    resolver = type(
        "Resolver",
        (),
        {
            "release_embedding_model_id": "intfloat/multilingual-e5-large",
            "release_embedding_dimension": 1024,
            "release_embedding_inventory_sha256": SHA,
        },
    )()
    authorities = type("Authorities", (), {"placement_resolver": resolver})()
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
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://product")

    args = _worker_b_args() + [
        "--release-registry-path",
        "/proof/release-registry.json",
        "--release-registry-sha256",
        SHA,
        "--revocation-registry-path",
        "/proof/revocation-registry.json",
        "--revocation-registry-sha256",
        SHA,
        "--expected-product-role",
        "rag_publisher",
    ]

    assert multilevel_publication_resume_cli.main(args) == 1
    assert model_loaded is True


class _NullConn:
    def __enter__(self) -> _NullConn:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None
