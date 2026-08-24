from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_authorization_mapping import CONTENT_A, CONTENT_B, _scope, _set  # noqa: E402

from ingestor.ingestion_worker import create_job_cli  # noqa: E402
from ingestor.ingestion_worker.authorization_mapping import (  # noqa: E402
    build_authorization_mapping,
)
from ingestor.ingestion_worker.publication_resume import (  # noqa: E402
    PublicationResumeError,
    require_publication_authorization_mapping,
)
from ingestor.ingestion_worker.runner import (  # noqa: E402
    AuthorizationCheckpointError,
    require_postfetch_authorization_mapping,
    require_prefetch_authorization_mapping,
)


def _mapping():
    authorization_set = _set()
    return build_authorization_mapping(
        authorization_set_bytes=authorization_set.canonical_bytes(),
        expected_authorization_set_digest=authorization_set.digest(),
        authority_required_content_sha256=(CONTENT_A, CONTENT_B),
    )


def test_prefetch_selects_the_only_authorization_for_the_exact_scope() -> None:
    assert (
        require_prefetch_authorization_mapping(
            mapping=_mapping(),
            scope=_scope(collection="philo_terminale"),
            claimed_authorization_id="auth-a",
        )
        == "auth-a"
    )


def test_prefetch_refuses_a_caller_override_or_unknown_scope() -> None:
    with pytest.raises(AuthorizationCheckpointError, match="claims.*signed mapping"):
        require_prefetch_authorization_mapping(
            mapping=_mapping(),
            scope=_scope(collection="philo_terminale"),
            claimed_authorization_id="auth-b",
        )
    with pytest.raises(AuthorizationCheckpointError, match="unknown scope"):
        require_prefetch_authorization_mapping(
            mapping=_mapping(),
            scope=_scope(collection="unknown"),
            claimed_authorization_id="auth-a",
        )


def test_postfetch_requires_the_actual_bytes_to_belong_to_the_same_member() -> None:
    require_postfetch_authorization_mapping(
        mapping=_mapping(),
        content_sha256=CONTENT_A,
        authorization_id="auth-a",
    )
    with pytest.raises(AuthorizationCheckpointError, match="belongs to.*auth-b"):
        require_postfetch_authorization_mapping(
            mapping=_mapping(),
            content_sha256=CONTENT_B,
            authorization_id="auth-a",
        )


def test_publication_requires_the_durable_individual_authorization() -> None:
    require_publication_authorization_mapping(
        mapping=_mapping(),
        content_sha256=CONTENT_A,
        durable_authorization_id="auth-a",
    )
    with pytest.raises(PublicationResumeError, match="durable authorization"):
        require_publication_authorization_mapping(
            mapping=_mapping(),
            content_sha256=CONTENT_A,
            durable_authorization_id="auth-b",
        )


def test_create_job_refuses_free_form_authorization_before_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mapping = _mapping()
    monkeypatch.setattr(
        create_job_cli,
        "enforce_readiness_gate",
        lambda: SimpleNamespace(authorization_mapping=mapping),
    )
    monkeypatch.setattr(
        create_job_cli,
        "enforce_production_manifest_gate",
        lambda *_args: SimpleNamespace(
            manifest=SimpleNamespace(authorities={}, manifest_fingerprint="d" * 64)
        ),
    )
    monkeypatch.setattr(
        create_job_cli.psycopg,
        "connect",
        lambda *_args, **_kwargs: pytest.fail("database opened after mapping refusal"),
    )
    scope = _scope(collection="philo_terminale")
    argv = [
        "--profiles-dir", str(tmp_path),
        "--manifest-path", str(tmp_path / "manifest.yml"),
        "--tenant", scope.tenant,
        "--collection", scope.collection,
        "--niveau", scope.niveau,
        "--voie", scope.voie,
        "--matiere", scope.matiere,
        "--candidat", scope.candidat,
        "--audience", ",".join(scope.audience),
        "--visibility", scope.visibility,
        "--school-year", scope.school_year,
        "--programme-version", scope.programme_version,
        "--profile-version", "v1",
        "--scope-authorization-id", "auth-b",
        "--source-url", "https://example.test/a",
        "--canonical-url", "https://example.test/a",
        "--domain", "example.test",
        "--proposed-type-doc", "cours",
    ]

    assert create_job_cli.main(argv) == 1
    assert "JOB_AUTHORIZATION_MAPPING_FAILED" in capsys.readouterr().err
    with pytest.raises(AuthorizationCheckpointError, match="unknown content"):
        require_postfetch_authorization_mapping(
            mapping=_mapping(),
            content_sha256="f" * 64,
            authorization_id="auth-a",
        )
