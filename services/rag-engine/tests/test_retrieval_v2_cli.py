"""Contrat du consommateur CLI du retrieval hybride LOT40."""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from nexus_contracts import Rights

ENGINE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ENGINE_ROOT / "scripts" / "retrieval_v2.py"
sys.path.insert(0, str(ENGINE_ROOT / "scripts"))
sys.path.insert(0, str(ENGINE_ROOT / "src"))

import retrieval_v2 as cli  # noqa: E402

from ingestor.pg_pool import PoolConfigurationError, PoolSettings  # noqa: E402
from ingestor.retrieval_hybrid_v2 import (  # noqa: E402
    HybridHit,
    RetrievalCandidate,
    RetrievalPipelineError,
)
from ingestor.retrieval_scope_v2 import ServerRetrievalScope  # noqa: E402

COLLECTION = "rag_nexus_nsi_terminale_specialite"
SETTINGS = PoolSettings(
    dsn="postgresql://rag_user@127.0.0.1:5432/rag_db",
    min_size=1,
    max_size=2,
    timeout_s=1.0,
)
SCOPE = ServerRetrievalScope(
    tenant="libre_terminale",
    niveau="terminale",
    voie="generale",
    matiere="nsi",
    statut_enseignement="specialite",
    candidat="individuel",
    audiences=("libre", "tous"),
    rights=(Rights.officiel_public, Rights.public_allowed),
    visibilities=("public",),
    school_year="2026-2027",
    collection=COLLECTION,
    programme_version="BOEN_special_8_2019-07-25",
    scope_id="lot41_test_scope",
    scope_digest="a" * 64,
    source_sha256="b" * 64,
)


@pytest.fixture(autouse=True)
def verified_cli_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_load_verified_identity", lambda: object())
    monkeypatch.setattr(
        cli,
        "build_server_retrieval_scope",
        lambda *_args, **_kwargs: SCOPE,
    )


def _retrievable_config(*, retrievable: bool = True) -> dict[str, Any]:
    return {
        "collections": {
            COLLECTION: {
                "matiere": "nsi",
                "niveau": "terminale",
                "statut": "specialite",
                "domain": "education",
                "instanciee": True,
            }
        },
        "domains": {"education": {"retrievable": retrievable}},
    }


def _hit(*, lexical_score: float | None = None) -> HybridHit:
    return HybridHit(
        candidate=RetrievalCandidate(
            chunk_id="chunk-1",
            doc_id="doc-1",
            source_label="Libellé qui ne doit pas être imprimé",
            source_uri="https://example.edu/source",
            rights="official_public_administrative",
            type_doc="programme",
            text="CONTENU_SECRET_DU_CHUNK",
            page_start=3,
            vector=(1.0,) + (0.0,) * 1023,
            review_status="reviewed",
            dense_score=0.91,
            lexical_score=lexical_score,
        ),
        dense_rank=1,
        lexical_rank=None if lexical_score is None else 2,
        rrf_score=0.016,
        rerank_score=2.8,
        mmr_score=0.61,
        score_final=0.88,
    )


def _argv(*, query: str = "requête sensible", top_k: int = 5) -> list[str]:
    return [
        "--query",
        query,
        "--collection",
        COLLECTION,
        "--top-k",
        str(top_k),
    ]


def test_help_works_without_dsn_or_model_loading() -> None:
    environment = os.environ.copy()
    environment.pop("PG_RAG_DSN", None)
    environment.pop("DATABASE_URL_SYNC", None)

    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        cwd=ENGINE_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--top-k" in result.stdout
    assert result.stderr == ""


def test_help_returns_before_settings_factories_and_pool_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = MagicMock(side_effect=AssertionError("runtime resource touched"))
    monkeypatch.setattr(cli.PoolSettings, "from_env", forbidden)
    monkeypatch.setattr(cli, "_build_pg_store", forbidden)
    monkeypatch.setattr(cli, "_load_canonical_embedder", forbidden)
    monkeypatch.setattr(cli, "_load_canonical_reranker", forbidden)
    monkeypatch.setattr(cli, "close_pool", forbidden)

    with pytest.raises(SystemExit) as help_exit:
        cli.main(["--help"])

    assert help_exit.value.code == 0
    forbidden.assert_not_called()


def test_import_keeps_model_factories_lazy() -> None:
    code = (
        "import sys; "
        f"sys.path[:0] = [{str(ENGINE_ROOT / 'scripts')!r}, {str(ENGINE_ROOT / 'src')!r}]; "
        "import retrieval_v2; "
        "raise SystemExit(int('sentence_transformers' in sys.modules))"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ENGINE_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_search_defaults_are_named_lazy_factories() -> None:
    parameters = inspect.signature(cli.search).parameters

    assert parameters["store_factory"].default is cli._build_pg_store
    assert parameters["embedder_factory"].default is cli._load_canonical_embedder
    assert parameters["reranker_factory"].default is cli._load_canonical_reranker
    assert parameters["retrieve_fn"].default is cli.retrieve_hybrid


def test_build_pg_store_defers_pool_acquisition(monkeypatch: pytest.MonkeyPatch) -> None:
    acquire = MagicMock(side_effect=AssertionError("pool acquired eagerly"))
    monkeypatch.setattr(cli, "pool_connection", acquire)

    store = cli._build_pg_store(SETTINGS, SCOPE)

    assert store is not None
    acquire.assert_not_called()


def test_canonical_model_loaders_have_no_alternative_or_network_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedder = object()
    embedding_loader = MagicMock(return_value=embedder)
    reranker = object()
    cross_encoder = MagicMock(return_value=reranker)
    monkeypatch.setattr(cli, "load_embedding_model", embedding_loader)
    monkeypatch.setattr("sentence_transformers.CrossEncoder", cross_encoder)

    assert cli._load_canonical_embedder() is embedder
    assert cli._load_canonical_reranker() is reranker
    embedding_loader.assert_called_once_with()
    cross_encoder.assert_called_once_with(
        cli.RERANK_MODEL,
        max_length=512,
        local_files_only=True,
    )


@pytest.mark.parametrize("invalid_top_k", [0, 51, True])
def test_search_rejects_invalid_top_k_before_gate_or_factories(
    invalid_top_k: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_config = MagicMock(side_effect=AssertionError("gate config loaded"))
    factory = MagicMock(side_effect=AssertionError("factory called"))
    monkeypatch.setattr(cli, "load_collection_config", load_config)

    with pytest.raises(RetrievalPipelineError, match="invalid top_k"):
        cli.search(
            "question",
            COLLECTION,
            invalid_top_k,
            settings=SETTINGS,
            store_factory=factory,
            embedder_factory=factory,
            reranker_factory=factory,
        )

    load_config.assert_not_called()
    factory.assert_not_called()


def test_search_applies_retrievable_gate_before_all_factories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = MagicMock(side_effect=AssertionError("factory called before gate"))
    monkeypatch.setattr(
        cli,
        "load_collection_config",
        lambda: _retrievable_config(retrievable=False),
    )

    with pytest.raises(cli.CollectionNotRetrievableError):
        cli.search(
            "question",
            COLLECTION,
            5,
            settings=SETTINGS,
            store_factory=factory,
            embedder_factory=factory,
            reranker_factory=factory,
        )

    factory.assert_not_called()


def test_search_builds_factories_in_order_and_delegates_raw_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []
    store = object()
    embedder = object()
    reranker = object()
    expected = [_hit()]
    monkeypatch.setattr(cli, "load_collection_config", _retrievable_config)

    def build_store(settings: PoolSettings, scope: ServerRetrievalScope) -> object:
        events.append(("store", settings, scope))
        return store

    def build_embedder() -> object:
        events.append("embedder")
        return embedder

    def build_reranker() -> object:
        events.append("reranker")
        return reranker

    def retrieve(
        query: str,
        collection: str,
        top_k: int,
        **resources: object,
    ) -> list[HybridHit]:
        events.append(("retrieve", query, collection, top_k, resources))
        return expected

    actual = cli.search(
        "  Question brute ?  ",
        COLLECTION,
        7,
        settings=SETTINGS,
        store_factory=build_store,
        embedder_factory=build_embedder,
        reranker_factory=build_reranker,
        retrieve_fn=retrieve,
    )

    assert actual is expected
    assert events == [
        ("store", SETTINGS, SCOPE),
        "embedder",
        "reranker",
        (
            "retrieve",
            "  Question brute ?  ",
            COLLECTION,
            7,
            {"store": store, "embedder": embedder, "reranker": reranker},
        ),
    ]


def test_cli_top_k_bounds_are_argparse_errors_before_pool_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    close = MagicMock()
    monkeypatch.setattr(cli, "close_pool", close)

    with pytest.raises(SystemExit) as below:
        cli.main(_argv(top_k=0))
    assert below.value.code == 2
    assert "between 1 and 50" in capsys.readouterr().err

    with pytest.raises(SystemExit) as above:
        cli.main(_argv(top_k=51))
    assert above.value.code == 2
    assert "between 1 and 50" in capsys.readouterr().err
    close.assert_not_called()


def test_main_uses_primary_dsn_then_sync_fallback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: list[str] = []
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://primary@localhost/rag")
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql://fallback@localhost/rag")
    monkeypatch.setattr(cli, "search", lambda *_args, settings, **_kwargs: seen.append(settings.dsn) or [])
    monkeypatch.setattr(cli, "close_pool", MagicMock())

    assert cli.main(_argv()) == 0
    assert seen == ["postgresql://primary@localhost/rag"]
    assert capsys.readouterr().out == "results=0\n"

    seen.clear()
    monkeypatch.delenv("PG_RAG_DSN")
    assert cli.main(_argv()) == 0
    assert seen == ["postgresql://fallback@localhost/rag"]


def test_main_runs_gate_before_settings_and_search_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    config = _retrievable_config()

    def load_config() -> dict[str, Any]:
        events.append("config")
        return config

    def check_gate(collection: str, loaded: dict[str, Any]) -> dict[str, Any]:
        assert collection == COLLECTION
        assert loaded is config
        events.append("gate")
        return loaded["collections"][COLLECTION]

    def load_settings() -> PoolSettings:
        events.append("settings")
        return SETTINGS

    def run_search(*_args: object, **_kwargs: object) -> list[HybridHit]:
        events.append("search")
        return []

    def close() -> None:
        events.append("close")

    monkeypatch.setattr(cli, "load_collection_config", load_config)
    monkeypatch.setattr(cli, "_check_retrievable", check_gate)
    monkeypatch.setattr(cli.PoolSettings, "from_env", load_settings)
    monkeypatch.setattr(cli, "search", run_search)
    monkeypatch.setattr(cli, "close_pool", close)

    assert cli.main(_argv()) == 0
    assert events == ["settings", "search", "close"]


def test_missing_dsn_after_parse_is_generic_and_closes_pool(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("PG_RAG_DSN", raising=False)
    monkeypatch.delenv("DATABASE_URL_SYNC", raising=False)
    search = MagicMock(side_effect=AssertionError("search called without settings"))
    close = MagicMock()
    monkeypatch.setattr(cli, "search", search)
    monkeypatch.setattr(cli, "close_pool", close)

    assert cli.main(_argv(query="QUERY_ULTRA_SECRET")) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: hybrid retrieval unavailable\n"
    assert "QUERY_ULTRA_SECRET" not in captured.err
    search.assert_not_called()
    close.assert_called_once_with()


def test_success_output_contains_only_ids_and_labeled_scores(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://rag@localhost/rag")
    monkeypatch.setattr(cli, "search", MagicMock(return_value=[_hit()]))
    close = MagicMock()
    monkeypatch.setattr(cli, "close_pool", close)

    assert cli.main(_argv()) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == (
        "results=1\n"
        "chunk_id=chunk-1 dense=0.910000 lexical=none "
        "rrf=0.016000 rerank=2.800000 final=0.880000 mmr=0.610000\n"
    )
    assert "doc-1" not in captured.out
    assert "CONTENU_SECRET_DU_CHUNK" not in captured.out
    assert "Libellé qui ne doit pas être imprimé" not in captured.out
    assert "requête sensible" not in captured.out
    close.assert_called_once_with()


@pytest.mark.parametrize(
    ("failure", "patch_settings"),
    [
        (RetrievalPipelineError("pipeline query=ULTRA_SECRET"), False),
        (None, True),
    ],
)
def test_controlled_failures_are_generic_and_close_pool_once(
    failure: Exception | None,
    patch_settings: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_dsn = "postgresql://user@localhost/rag?application_name=DSN_ULTRA_SECRET"
    monkeypatch.setenv("PG_RAG_DSN", secret_dsn)
    close = MagicMock()
    monkeypatch.setattr(cli, "close_pool", close)
    if patch_settings:
        monkeypatch.setattr(
            cli.PoolSettings,
            "from_env",
            MagicMock(side_effect=PoolConfigurationError(f"bad {secret_dsn}")),
        )
    else:
        monkeypatch.setattr(cli, "search", MagicMock(side_effect=failure))

    assert cli.main(_argv(query="QUERY_ULTRA_SECRET")) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: hybrid retrieval unavailable\n"
    assert "QUERY_ULTRA_SECRET" not in captured.err
    assert "DSN_ULTRA_SECRET" not in captured.err
    close.assert_called_once_with()


def test_factory_failure_is_controlled_and_pool_is_closed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "load_collection_config", _retrievable_config)
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://rag@localhost/rag")
    monkeypatch.setattr(
        cli,
        "_build_pg_store",
        MagicMock(side_effect=cli.ModelLoadError("factory failed with secret")),
    )
    close = MagicMock()
    monkeypatch.setattr(cli, "close_pool", close)

    assert cli.main(_argv()) == 1
    assert capsys.readouterr().err == "Error: hybrid retrieval unavailable\n"
    close.assert_called_once_with()


def test_unexpected_body_exception_still_closes_pool_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://rag@localhost/rag")
    monkeypatch.setattr(cli, "search", MagicMock(side_effect=KeyboardInterrupt))
    close = MagicMock()
    monkeypatch.setattr(cli, "close_pool", close)

    with pytest.raises(KeyboardInterrupt):
        cli.main(_argv())

    close.assert_called_once_with()


def test_close_failure_is_generic_and_does_not_print_results(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://rag@localhost/rag")
    monkeypatch.setattr(cli, "search", MagicMock(return_value=[_hit(lexical_score=0.5)]))
    monkeypatch.setattr(
        cli,
        "close_pool",
        MagicMock(side_effect=PoolConfigurationError("close DSN_ULTRA_SECRET")),
    )

    assert cli.main(_argv()) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: hybrid retrieval unavailable\n"
    assert "DSN_ULTRA_SECRET" not in captured.err


@pytest.mark.parametrize("failure_phase", ["settings", "search", "close"])
def test_all_ordinary_runtime_failures_are_masked_and_close_once(
    failure_phase: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = "QUERY_DSN_SQL_ULTRA_SECRET"
    runtime_failure = RuntimeError(marker)
    config = _retrievable_config()
    load_config = MagicMock(return_value=config)
    gate = MagicMock(return_value=config["collections"][COLLECTION])
    load_settings = MagicMock(return_value=SETTINGS)
    run_search = MagicMock(return_value=[])
    close = MagicMock()
    phase_targets = {
        "config": load_config,
        "gate": gate,
        "settings": load_settings,
        "search": run_search,
        "close": close,
    }
    phase_targets[failure_phase].side_effect = runtime_failure
    monkeypatch.setattr(cli, "load_collection_config", load_config)
    monkeypatch.setattr(cli, "_check_retrievable", gate)
    monkeypatch.setattr(cli.PoolSettings, "from_env", load_settings)
    monkeypatch.setattr(cli, "search", run_search)
    monkeypatch.setattr(cli, "close_pool", close)

    assert cli.main(_argv(query=marker)) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: hybrid retrieval unavailable\n"
    assert marker not in captured.err
    close.assert_called_once_with()


def test_cli_contains_no_private_sql_or_hybrid_override() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "psycopg" not in source
    assert "SELECT " not in source
    assert "HYBRID_ENABLED" not in source
    assert "RERANK_SCORE_THRESHOLD" not in source
    assert "RERANK_CANDIDATES" not in source
    assert "EMBED_MODEL =" not in source
    assert "RERANK_MODEL =" not in source
