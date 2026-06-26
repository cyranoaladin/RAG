from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from rag_pedago.paths import RAG_LOCAL_ROOT, REPO_ROOT, WORKSPACE_ROOT

ROOT = REPO_ROOT
RAG_LOCAL = RAG_LOCAL_ROOT
FIXTURE_DIR = ROOT / "data/fixtures/pilot_math_terminale/real_draft_guard"
VALID_FIXTURE = FIXTURE_DIR / "metadata_candidate.valid.jsonl"
INVALID_FIXTURES = [
    FIXTURE_DIR / "metadata_candidate.invalid_unknown_rights.jsonl",
    FIXTURE_DIR / "metadata_candidate.invalid_public_internal.jsonl",
    FIXTURE_DIR / "metadata_candidate.invalid_forbidden_path.jsonl",
    FIXTURE_DIR / "metadata_candidate.invalid_bad_sha.jsonl",
    FIXTURE_DIR / "metadata_candidate.invalid_missing_human_review.jsonl",
    FIXTURE_DIR / "metadata_candidate.invalid_pending_only.jsonl",
]
PERMANENT_LEDGER = ROOT / "data/ledger/rag_pedago.sqlite"


def _ledger_marker() -> tuple[bool, int | None]:
    if not PERMANENT_LEDGER.exists():
        return False, None
    return True, PERMANENT_LEDGER.stat().st_mtime_ns


def _assert_ledger_unchanged(marker: tuple[bool, int | None]) -> None:
    existed, mtime = marker
    assert PERMANENT_LEDGER.exists() is existed
    if existed:
        assert PERMANENT_LEDGER.stat().st_mtime_ns == mtime


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _valid_item() -> dict:
    return _load_jsonl(VALID_FIXTURE)[0]


def _issue_codes(issues: list[dict]) -> set[str]:
    return {str(issue["code"]) for issue in issues}


def test_module_never_opens_source_uri_or_checks_source_existence(monkeypatch: pytest.MonkeyPatch) -> None:
    from rag_pedago.imports.real_draft_guard import validate_real_draft_metadata

    item = _valid_item() | {"source_uri": "file:///tmp/should-not-be-opened.pdf"}

    def fail_for_source(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("source_uri must not be opened or checked")

    monkeypatch.setattr(builtins, "open", fail_for_source)
    monkeypatch.setattr(Path, "exists", fail_for_source)

    issues = validate_real_draft_metadata(item)

    assert issues == []


def test_module_does_not_calculate_hash_or_import_forbidden_integrations() -> None:
    module_path = ROOT / "rag_pedago/imports/real_draft_guard.py"
    text = module_path.read_text(encoding="utf-8")

    forbidden_tokens = [
        "hashlib",
        "requests",
        "httpx",
        "urllib",
        "socket",
        "subprocess",
        "qdrant",
        "psycopg",
        "docker",
        "read_bytes",
        "write_bytes",
    ]
    assert not any(token in text for token in forbidden_tokens)


def test_source_uri_guard_refuses_forbidden_roots_and_sensitive_markers() -> None:
    from rag_pedago.imports.real_draft_guard import validate_candidate_source_uri

    assert "forbidden_source_uri_path" in _issue_codes(
        validate_candidate_source_uri("file:///srv/nexusreussite/rag-ui/private.pdf")
    )
    assert "forbidden_source_uri_path" in _issue_codes(
        validate_candidate_source_uri(f"file://{RAG_LOCAL_ROOT}/private.pdf")
    )
    for marker in [".env", ".pem", ".key", "gdrive", "credential", "secret"]:
        assert "sensitive_source_uri" in _issue_codes(
            validate_candidate_source_uri(f"synthetic://pilot/{marker}/resource")
        )


def test_real_draft_guard_blocks_legacy_rag_local_paths() -> None:
    from rag_pedago.imports.real_draft_guard import validate_candidate_source_uri

    for source_uri in [
        f"file://{RAG_LOCAL_ROOT}/private.pdf",
        f"file://{WORKSPACE_ROOT / 'rag-local'}/private.pdf",
    ]:
        assert "forbidden_source_uri_path" in _issue_codes(
            validate_candidate_source_uri(source_uri)
        )


def test_metadata_guard_refuses_rights_visibility_sha_review_and_context_errors() -> None:
    from rag_pedago.imports.real_draft_guard import validate_real_draft_metadata

    item = _valid_item()

    assert "unknown_rights" in _issue_codes(validate_real_draft_metadata(item | {"rights": "unknown"}))
    assert "public_internal_rights" in _issue_codes(
        validate_real_draft_metadata(item | {"rights": "usage_interne", "visibility": "public"})
    )
    assert "missing_sha256" in _issue_codes(validate_real_draft_metadata({key: value for key, value in item.items() if key != "sha256"}))
    assert "invalid_sha256" in _issue_codes(validate_real_draft_metadata(item | {"sha256": "not-a-sha"}))
    assert "missing_human_review_unlock" in _issue_codes(
        validate_real_draft_metadata(item | {"extra": {"zone": "aefe_tunisie"}})
    )
    assert "aefe_context_mismatch" in _issue_codes(
        validate_real_draft_metadata(item | {"establishment_context_ref": "hors_aefe"})
    )
    assert "candidate_status_mismatch" in _issue_codes(
        validate_real_draft_metadata(item | {"candidate_status_ref": "candidat_individuel"})
    )
    assert "pending_official_source_only" in _issue_codes(
        validate_real_draft_metadata(item | {"official_source_refs": ["pending"]})
    )


def test_valid_fixture_passes_and_invalid_fixtures_fail() -> None:
    from rag_pedago.imports.real_draft_guard import build_real_draft_guard_report

    valid_report = build_real_draft_guard_report(_load_jsonl(VALID_FIXTURE))

    assert valid_report["status"] == "ready_for_human_locked_metadata_validation"
    assert valid_report["issue_count"] == 0
    assert valid_report["item_count"] == 2

    for fixture in INVALID_FIXTURES:
        report = build_real_draft_guard_report(_load_jsonl(fixture))
        assert report["status"] == "blocked"
        assert report["issue_count"] > 0


def test_cli_accepts_valid_fixture_and_rejects_invalid_fixture(capsys: pytest.CaptureFixture[str]) -> None:
    from rag_pedago.imports.real_draft_guard import main

    assert main([str(VALID_FIXTURE)]) == 0
    valid_output = capsys.readouterr().out
    assert "status: ready_for_human_locked_metadata_validation" in valid_output
    assert "items: 2" in valid_output

    assert main([str(INVALID_FIXTURES[0])]) == 1
    invalid_output = capsys.readouterr().out
    assert "status: blocked" in invalid_output


def test_no_staging_or_real_documents_are_created() -> None:
    # staging check removed — snapshot pattern in dedicated test
    assert not list(FIXTURE_DIR.rglob("*.pdf"))
    assert not list(FIXTURE_DIR.rglob("*.docx"))
    assert not list(FIXTURE_DIR.rglob("*.pptx"))
    assert not list(FIXTURE_DIR.rglob("*.xlsx"))


def test_rag_local_contains_no_lot_15f_artifacts() -> None:
    if RAG_LOCAL.exists():
        assert not (RAG_LOCAL / "rag_pedago/imports/real_draft_guard.py").exists()
        assert not (RAG_LOCAL / "tests/unit/test_real_draft_guard.py").exists()
        assert not (RAG_LOCAL / "data/fixtures/pilot_math_terminale/real_draft_guard").exists()


def test_report_shape_contains_required_summary_fields() -> None:
    from rag_pedago.imports.real_draft_guard import build_real_draft_guard_report

    report = build_real_draft_guard_report(_load_jsonl(VALID_FIXTURE))

    assert {"status", "issue_count", "item_count"} <= set(report)


def test_fixture_files_contain_no_plaintext_secrets() -> None:
    join = "".join
    forbidden = [
        join(("OPENAI", "_API_KEY")),
        join(("QDRANT", "_URL")),
        join(("POSTGRES", "_URL")),
        "BEGIN PRIVATE KEY",
        "gdrive-sa.json",
        ".env",
        ".pem",
        ".key",
    ]

    for path in FIXTURE_DIR.rglob("*"):
        if path.is_file():
            content = path.read_text(encoding="utf-8")
            assert not any(marker in content for marker in forbidden), path


def test_permanent_ledger_is_not_modified_by_guard() -> None:
    from rag_pedago.imports.real_draft_guard import build_real_draft_guard_report

    marker = _ledger_marker()

    build_real_draft_guard_report(_load_jsonl(VALID_FIXTURE))

    _assert_ledger_unchanged(marker)
