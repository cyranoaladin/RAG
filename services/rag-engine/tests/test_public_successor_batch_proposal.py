"""LOT42 public: compare the exact sealed population before proposing a review."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from nexus_contracts.authority_artifacts import canonical_publication_review_path

from ingestor.ingestion_control.public_successor_batch_proposal import (
    build_public_successor_batch_projections,
    build_public_successor_batch_review_artifact,
    load_public_successor_batch_source,
    measure_public_successor_resource_scopes,
    require_public_successor_resource_scopes,
    require_reviewed_public_successor_batch,
)
from ingestor.ingestion_control.release_batch_attestation import (
    MeasuredReleaseBatchFacts,
    ReleaseBatchAttestationError,
    require_public_successor_batch_matches_release,
)

SHA = "a" * 64
COLLECTION = "rag_nexus_svt_premiere_specialite"
AUTHORIZATION = "lot41a-student-public-svt-premiere-v2"
ROOT = Path(__file__).resolve().parents[3]


def _facts() -> MeasuredReleaseBatchFacts:
    resource = uuid4()
    return MeasuredReleaseBatchFacts(
        release_id="student-public-successor-test",
        release_manifest_sha256="1" * 64,
        artifacts_release_sha256="2" * 64,
        candidate_inventory_sha256="3" * 64,
        artifact_transfer_manifest_sha256="4" * 64,
        collections=(COLLECTION,),
        scope_authorization_ids=(AUTHORIZATION,),
        subjects=1,
        unique_artifacts=1,
        placements=1,
        unique_chunks=2,
        provenance_source_url_count=1,
        resource_ids=(resource,),
        par_ressource={resource: (uuid4(), SHA, COLLECTION, AUTHORIZATION)},
        currentness="official_snapshot",
        placement_keys=((COLLECTION, SHA, "placement-1", AUTHORIZATION),),
        chunk_counts={SHA: 2},
    )


def _release() -> SimpleNamespace:
    return SimpleNamespace(
        release_id="student-public-successor-test",
        release_manifest_sha256="1" * 64,
        artifacts_release_sha256="2" * 64,
        candidate_inventory_sha256="3" * 64,
        artifact_transfer_manifest_sha256="4" * 64,
        expected_counts={
            "subjects": 1, "unique_artifacts": 1, "placements": 1,
            "unique_chunks": 2,
        },
        collections=(COLLECTION,),
        artifact_ids=frozenset({SHA}),
        artifact_media_types={SHA: "text/plain; charset=utf-8"},
        artifact_chunk_counts={SHA: 2},
        placements=(SimpleNamespace(
            collection=COLLECTION, artifact_id=SHA, placement_id="placement-1",
            review_status="reviewed", placement_status="active",
            currentness="official_snapshot",
            scope_dimensions={"visibility": "public"},
        ),),
    )


def test_public_batch_exact_population_passes() -> None:
    require_public_successor_batch_matches_release(
        _facts(), _release(), {COLLECTION: AUTHORIZATION}
    )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("placement_keys", ((COLLECTION, SHA, "substituted", AUTHORIZATION),), "placement"),
        ("unique_chunks", 3, "unique_chunks"),
        ("artifact_transfer_manifest_sha256", "5" * 64, "transfer"),
        ("scope_authorization_ids", ("old-internal",), "authorization"),
        ("chunk_counts", {SHA: 3}, "chunk_count"),
    ],
)
def test_public_batch_rejects_divergent_db_fact(
    field: str, value: object, reason: str
) -> None:
    with pytest.raises(ReleaseBatchAttestationError, match=reason):
        require_public_successor_batch_matches_release(
            replace(_facts(), **{field: value}), _release(),
            {COLLECTION: AUTHORIZATION},
        )


def test_public_batch_rejects_internal_placement() -> None:
    release = _release()
    release.placements[0].scope_dimensions["visibility"] = "internal"
    with pytest.raises(ReleaseBatchAttestationError, match="public"):
        require_public_successor_batch_matches_release(
            _facts(), release, {COLLECTION: AUTHORIZATION}
        )


def test_real_a2_source_loads_all_text_placements_without_db() -> None:
    anchor = ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261011.json"
    a2 = ROOT / "docs/reports/go_live/student_public_successor_temporal_continuity_a2_20261011_v2.json"
    release_root = ROOT / (
        "services/rag-pedago/data/releases/prerentree_2026_2027/"
        "profile_gate_student_public_successor_v1/release-40b956c6f5ec0c60"
    )
    source = load_public_successor_batch_source(
        release_root=release_root,
        anchor_path=anchor,
        anchor_sha256=sha256(anchor.read_bytes()).hexdigest(),
        a2_path=a2,
        transfer_manifest_sha256="4" * 64,
        now_utc=datetime(2026, 10, 12, 1, tzinfo=UTC),
    )
    assert source.release.expected_counts == {
        "subjects": 11, "unique_artifacts": 253,
        "placements": 377, "unique_chunks": 3975,
    }
    assert len(source.release.placements) == 377
    assert set(source.release.artifact_media_types.values()) == {"text/plain; charset=utf-8"}
    assert len(source.rights_by_sha) == len(source.pii_by_sha) == 253
    assert len(source.profiles_by_collection) == 11
    profile = source.profiles_by_collection["rag_nexus_dgemc_terminale_option"]
    assert profile.profile_version == "student-public-derivative-v1"
    assert profile.profile_fingerprint == (
        "75836923108abb72a729e2d521a3613fa69c0a117b8cc01816cfacf910a78bfe"
    )


def test_public_batch_refuses_db_scope_or_rights_category_substitution() -> None:
    facts = _facts()
    scope = {
        "tenant": "libre_premiere", "collection": COLLECTION,
        "niveau": "premiere", "voie": "generale", "matiere": "svt",
        "candidat": "libre", "audience": ["libre", "aefe"],
        "visibility": "public", "school_year": "2026-2027",
        "programme_version": "BOEN_SPECIAL_TEST",
    }
    profile = SimpleNamespace(
        profile_id=COLLECTION, profile_version="student-public-derivative-v1",
        profile_fingerprint="b" * 64,
        scope=SimpleNamespace(model_dump=lambda **_kwargs: scope),
    )
    source = SimpleNamespace(
        profiles_by_collection={COLLECTION: profile},
        profile_manifest_digest="c" * 64,
    )
    authority = SimpleNamespace(
        authorization_id=AUTHORIZATION,
        profile_id=COLLECTION, profile_version="student-public-derivative-v1",
        profile_fingerprint="b" * 64, manifest_digest="c" * 64,
        rights_categories=("public_allowed",), scope=profile.scope,
    )
    require_public_successor_resource_scopes(
        facts, source, {COLLECTION: authority}, {facts.resource_ids[0]: scope},
    )
    with pytest.raises(ReleaseBatchAttestationError, match="scope"):
        require_public_successor_resource_scopes(
            facts, source, {COLLECTION: authority},
            {facts.resource_ids[0]: {**scope, "visibility": "internal"}},
        )
    with pytest.raises(ReleaseBatchAttestationError, match="rights"):
        require_public_successor_resource_scopes(
            facts, source,
            {COLLECTION: SimpleNamespace(**{
                **vars(authority), "rights_categories": ("internal_only",),
            })},
            {facts.resource_ids[0]: scope},
        )
    with pytest.raises(ReleaseBatchAttestationError, match="profile"):
        require_public_successor_resource_scopes(
            facts, source,
            {COLLECTION: SimpleNamespace(**{
                **vars(authority), "profile_fingerprint": "d" * 64,
            })},
            {facts.resource_ids[0]: scope},
        )
    with pytest.raises(ReleaseBatchAttestationError, match="scope population"):
        require_public_successor_resource_scopes(
            facts, source, {COLLECTION: authority}, {},
        )


def test_public_batch_scope_measurement_rejects_missing_db_resource() -> None:
    facts = _facts()

    class EmptyScopeConnection:
        def execute(self, sql: str, params: object) -> EmptyScopeConnection:
            assert "visibility" in sql and "audience" in sql
            assert params == (list(facts.resource_ids),)
            return self

        def fetchall(self) -> list[object]:
            return []

    with pytest.raises(ReleaseBatchAttestationError, match="scope population"):
        measure_public_successor_resource_scopes(EmptyScopeConnection(), facts)


def test_attestor_can_read_pinned_postgres_system_identity() -> None:
    provisioning = (
        ROOT / "services/rag-engine/infra/scripts/provision_ingestion_control_roles.sh"
    ).read_text(encoding="utf-8")
    assert 'GRANT EXECUTE ON FUNCTION pg_catalog.pg_control_system() TO :"attestor_role"' in provisioning


def test_public_live_target_delegates_full_v2_replay_and_refuses_bad_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor.ingestion_worker import attest_publication_cli as cli
    from scripts.go_live import qualified_public_text_transfer as canonical

    gate = tmp_path / "release/profile_gate"
    gate.mkdir(parents=True)
    (gate / "candidate_inventory.json").write_bytes(b"inventory")
    (gate / "private_transfer_allowlist.json").write_bytes(b"allowlist")
    files = {}
    for name in ("plan", "v1", "pin", "v2"):
        path = tmp_path / name
        path.write_bytes(name.encode())
        files[name] = path
    args = SimpleNamespace(
        destination_root=tmp_path, release_root=tmp_path / "release",
        transfer_plan_path=files["plan"],
        transfer_v1_receipt_path=files["v1"],
        target_pin_path=files["pin"],
        transfer_v2_attestation_path=files["v2"],
        transfer_v2_sha256=sha256(b"v2").hexdigest(),
        target_pin_sha256="a" * 64,
        content_anchor_sha256="b" * 64,
    )
    content = SimpleNamespace(
        candidate_inventory_sha256="c" * 64, release_id="release-test",
        expected_counts={"unique_artifacts": 253},
    )
    observed: dict[str, object] = {}
    def verify(**kwargs: object) -> SimpleNamespace:
        observed.update(kwargs)
        return SimpleNamespace(file_count=253)
    monkeypatch.setattr(canonical, "verify_qualified_transfer_target", verify)
    monkeypatch.setattr(cli, "get_attestor_dsn", lambda: "isolated-attestor-dsn")
    cli._verify_public_live_target(args, content)
    assert observed["destination_root"] == tmp_path
    assert observed["database_dsn"] == "isolated-attestor-dsn"
    assert observed["candidate_inventory_raw"] == b"inventory"
    assert observed["allowlist_raw"] == b"allowlist"
    assert observed["attestation_raw"] == b"v2"
    args.transfer_v2_sha256 = "0" * 64
    with pytest.raises(ReleaseBatchAttestationError, match="V2 digest"):
        cli._verify_public_live_target(args, content)
    args.destination_root = Path("relative")
    with pytest.raises(ReleaseBatchAttestationError, match="absolute"):
        cli._verify_public_live_target(args, content)


def test_in_memory_projection_uses_exact_public_evidence() -> None:
    source = SimpleNamespace(
        release=_release(),
        rights_sha256="6" * 64,
        pii_sha256="7" * 64,
        currentness_sha256="8" * 64,
        artifacts_by_sha={SHA: {
            "content_sha256": SHA, "page_count": 1,
            "chunks": [
                {"chunk_id": "b" * 64, "chunk_sha256": "9" * 64,
                 "page_start": 1, "page_end": 1},
                {"chunk_id": "c" * 64, "chunk_sha256": "d" * 64,
                 "page_start": 1, "page_end": 1},
            ],
        }},
        rights_by_sha={SHA: {"rights_basis": "EDUSCOL_ETALAB_2_0_SITEWIDE"}},
        pii_by_sha={SHA: {"pii_gate_status": "PASS_BY_DERIVATIVE_FULL_TEXT_ADJUDICATION"}},
        currentness_by_sha={SHA: {
            "currentness_status": "PASS",
            "revocation_status": "PASS_CURRENT_OFFICIAL_PUBLICATION",
        }},
    )
    rows, digest = build_public_successor_batch_projections(
        source, _facts(), evaluator="automated:Codex/LOT42", now_utc=datetime(2026, 10, 12, tzinfo=UTC),
    )
    assert len(rows) == 1 and rows[0].gate_passed
    assert rows[0].droits.valeur == "public_allowed"
    assert rows[0].qualite.valeur is True
    assert len(digest) == 64


def test_in_memory_projection_refuses_missing_chunk_evidence() -> None:
    source = SimpleNamespace(
        release=_release(), rights_sha256="6" * 64, pii_sha256="7" * 64,
        currentness_sha256="8" * 64,
        artifacts_by_sha={SHA: {"page_count": 1, "chunks": []}},
        rights_by_sha={SHA: {"rights_basis": "EDUSCOL_ETALAB_2_0_SITEWIDE"}},
        pii_by_sha={SHA: {"pii_gate_status": "PASS_BY_DERIVATIVE_FULL_TEXT_ADJUDICATION"}},
        currentness_by_sha={SHA: {
            "currentness_status": "PASS", "revocation_status": "PASS_CURRENT_OFFICIAL_PUBLICATION",
        }},
    )
    with pytest.raises(ReleaseBatchAttestationError, match="quality"):
        build_public_successor_batch_projections(
            source, _facts(), evaluator="automated:Codex/LOT42",
            now_utc=datetime(2026, 10, 12, tzinfo=UTC),
        )


def test_public_batch_review_binds_a2_transfer_and_projection() -> None:
    facts = _facts()
    start = datetime(2026, 10, 12, tzinfo=UTC)
    expiry = datetime(2026, 10, 13, tzinfo=UTC)
    review = build_public_successor_batch_review_artifact(
        review_id="lot42-public-test", facts=facts,
        valid_from=start, valid_until=expiry,
        a2_sha256="a" * 64, transfer_sha256="4" * 64,
        target_pin_sha256="2" * 64, transfer_v2_sha256="3" * 64,
        projection_digest="f" * 64, evaluator="automated:Codex/LOT42",
    )
    require_reviewed_public_successor_batch(
        review, facts=facts, a2_sha256="a" * 64,
        a2_valid_until=expiry, transfer_sha256="4" * 64,
        target_pin_sha256="2" * 64, transfer_v2_sha256="3" * 64,
        projection_digest="f" * 64, evaluator="automated:Codex/LOT42",
        now_utc=start,
    )
    with pytest.raises(ReleaseBatchAttestationError, match="projection"):
        require_reviewed_public_successor_batch(
            review, facts=facts, a2_sha256="a" * 64,
            a2_valid_until=expiry, transfer_sha256="4" * 64,
            target_pin_sha256="2" * 64, transfer_v2_sha256="3" * 64,
            projection_digest="e" * 64, evaluator="automated:Codex/LOT42",
            now_utc=start,
        )


def test_public_batch_review_refuses_expired_a2_and_substitution() -> None:
    facts = _facts()
    start = datetime(2026, 10, 12, tzinfo=UTC)
    expiry = datetime(2026, 10, 13, tzinfo=UTC)
    review = build_public_successor_batch_review_artifact(
        review_id="lot42-public-test", facts=facts,
        valid_from=start, valid_until=expiry,
        a2_sha256="a" * 64, transfer_sha256="4" * 64,
        target_pin_sha256="2" * 64, transfer_v2_sha256="3" * 64,
        projection_digest="f" * 64, evaluator="automated:Codex/LOT42",
    )
    with pytest.raises(ReleaseBatchAttestationError, match="A2"):
        require_reviewed_public_successor_batch(
            review, facts=facts, a2_sha256="a" * 64,
            a2_valid_until=start, transfer_sha256="4" * 64,
            target_pin_sha256="2" * 64, transfer_v2_sha256="3" * 64,
            projection_digest="f" * 64, evaluator="automated:Codex/LOT42",
            now_utc=start,
        )
    with pytest.raises(ReleaseBatchAttestationError, match="A2"):
        require_reviewed_public_successor_batch(
            review, facts=facts, a2_sha256="b" * 64,
            a2_valid_until=expiry, transfer_sha256="4" * 64,
            target_pin_sha256="2" * 64, transfer_v2_sha256="3" * 64,
            projection_digest="f" * 64, evaluator="automated:Codex/LOT42",
            now_utc=start,
        )


class _RecordingConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.parameters: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self) -> _RecordingConnection:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, _params: object = None) -> _RecordingConnection:
        self.statements.append(sql)
        self.parameters.append(_params)
        return self

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[object]:
        return []

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_public_record_refuses_without_green_head_pinned_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor.ingestion_worker import attest_publication_cli as cli

    monkeypatch.setattr(cli, "_verified_approval", lambda _args: SimpleNamespace(
        head_pinned_status="failure",
    ))
    monkeypatch.setattr(cli.psycopg, "connect", lambda _dsn: pytest.fail(
        "no DB connection is allowed before a green required status",
    ))
    assert cli._cmd_record_release_batch_attestation(SimpleNamespace(
        command="record-public-successor-release-batch-attestation",
    )) == 1


def test_public_record_refuses_changed_projection_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor.ingestion_worker import attest_publication_cli as cli

    facts = _facts()
    now = datetime.now(UTC)
    review = build_public_successor_batch_review_artifact(
        review_id="lot42-public-test", facts=facts,
        valid_from=now.replace(year=now.year - 1),
        valid_until=now.replace(year=now.year + 1),
        a2_sha256="a" * 64, transfer_sha256="4" * 64,
        target_pin_sha256="2" * 64, transfer_v2_sha256="3" * 64,
        projection_digest="f" * 64, evaluator="automated:Codex/LOT42",
    )
    connection = _RecordingConnection()
    live = SimpleNamespace(
        repository="owner/repo", head_sha="b" * 40, head_pinned_status="success",
    )
    monkeypatch.setattr(cli, "_verified_approval", lambda _args: live)
    monkeypatch.setattr(cli, "get_attestor_dsn", lambda: "unused")
    monkeypatch.setattr(cli.psycopg, "connect", lambda _dsn: connection)
    monkeypatch.setattr(cli, "fetch_blob_at_ref", lambda **_kwargs: SimpleNamespace(
        content=review.canonical_bytes(), blob_sha="blob",
    ))
    monkeypatch.setattr(cli, "_prepare_public_successor_batch", lambda *_args: (
        SimpleNamespace(a2_sha256="a" * 64,
                        a2_valid_until=now.replace(year=now.year + 2)),
        facts, (), "e" * 64, "4" * 64, {},
    ))
    args = SimpleNamespace(
        command="record-public-successor-release-batch-attestation",
        release_id=facts.release_id, review_id=review.review_id,
        evaluator="automated:Codex/LOT42",
        target_pin_sha256="2" * 64, transfer_v2_sha256="3" * 64,
        review_artifact_path=canonical_publication_review_path(
            review_id=review.review_id, digest=review.digest(),
        ),
    )
    assert cli._cmd_record_release_batch_attestation(args) == 1
    assert connection.commits == 0
    assert connection.rollbacks >= 1
    assert not any("INSERT" in statement for statement in connection.statements)


def test_public_record_rolls_back_projection_on_attestation_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor.ingestion_control import sealed_release_projection as projection_module
    from ingestor.ingestion_worker import attest_publication_cli as cli

    facts = _facts()
    now = datetime.now(UTC)
    review = build_public_successor_batch_review_artifact(
        review_id="lot42-public-test", facts=facts,
        valid_from=now.replace(year=now.year - 1),
        valid_until=now.replace(year=now.year + 1),
        a2_sha256="a" * 64, transfer_sha256="4" * 64,
        target_pin_sha256="2" * 64, transfer_v2_sha256="3" * 64,
        projection_digest="f" * 64, evaluator="automated:Codex/LOT42",
    )

    class ConflictConnection(_RecordingConnection):
        def fetchone(self) -> tuple[str] | None:
            if "publication_attestations" in self.statements[-1]:
                return ("conflicting-digest",)
            return None

    connection = ConflictConnection()
    live = SimpleNamespace(
        repository="owner/repo", head_sha="b" * 40, head_pinned_status="success",
    )
    monkeypatch.setattr(cli, "_verified_approval", lambda _args: live)
    monkeypatch.setattr(cli, "get_attestor_dsn", lambda: "unused")
    monkeypatch.setattr(cli.psycopg, "connect", lambda _dsn: connection)
    monkeypatch.setattr(cli, "fetch_blob_at_ref", lambda **_kwargs: SimpleNamespace(
        content=review.canonical_bytes(), blob_sha="blob",
    ))
    monkeypatch.setattr(cli, "_prepare_public_successor_batch", lambda *_args: (
        SimpleNamespace(a2_sha256="a" * 64,
                        a2_valid_until=now.replace(year=now.year + 2)),
        facts, (SimpleNamespace(),), "f" * 64, "4" * 64, {},
    ))
    monkeypatch.setattr(projection_module, "persist_projection", lambda conn, **_kwargs: (
        conn.execute("INSERT PROJECTION"), (1, 0)
    )[1])
    monkeypatch.setattr(projection_module, "load_applicable_projection", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(projection_module, "require_projection_authorises", lambda *_args, **_kwargs: None)
    args = SimpleNamespace(
        command="record-public-successor-release-batch-attestation",
        release_id=facts.release_id, review_id=review.review_id,
        evaluator="automated:Codex/LOT42",
        target_pin_sha256="2" * 64, transfer_v2_sha256="3" * 64,
        review_artifact_path=canonical_publication_review_path(
            review_id=review.review_id, digest=review.digest(),
        ),
    )
    assert cli._cmd_record_release_batch_attestation(args) == 1
    assert any("INSERT PROJECTION" in statement for statement in connection.statements)
    assert connection.rollbacks >= 1
    assert connection.commits == 0


@pytest.mark.parametrize("review_changes", [False, True])
def test_public_record_binds_a2_profile_and_rechecks_review_before_commit(
    monkeypatch: pytest.MonkeyPatch, review_changes: bool,
) -> None:
    from ingestor.ingestion_control import sealed_release_projection as projection_module
    from ingestor.ingestion_worker import attest_publication_cli as cli

    facts = _facts()
    now = datetime.now(UTC)
    review = build_public_successor_batch_review_artifact(
        review_id="lot42-public-test", facts=facts,
        valid_from=now.replace(year=now.year - 1),
        valid_until=now.replace(year=now.year + 1),
        a2_sha256="a" * 64, transfer_sha256="4" * 64,
        target_pin_sha256="2" * 64, transfer_v2_sha256="3" * 64,
        projection_digest="f" * 64, evaluator="automated:Codex/LOT42",
    )
    connection = _RecordingConnection()
    live = SimpleNamespace(
        repository="owner/repo", pull_request=42, base_sha="a" * 40,
        head_sha="b" * 40, review_id=123, reviewer="human",
        submitted_at=now, challenge="challenge", head_pinned_status="success",
    )
    calls = 0

    def approval(_args: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        return SimpleNamespace(**{
            **vars(live),
            "head_pinned_status": "failure" if review_changes and calls == 2 else "success",
        })

    authority = SimpleNamespace(
        profile_id=COLLECTION, profile_version="student-public-derivative-v1",
        profile_fingerprint="b" * 64, manifest_digest="c" * 64,
    )
    monkeypatch.setattr(cli, "_verified_approval", approval)
    monkeypatch.setattr(cli, "get_attestor_dsn", lambda: "unused")
    monkeypatch.setattr(cli.psycopg, "connect", lambda _dsn: connection)
    monkeypatch.setattr(cli, "fetch_blob_at_ref", lambda **_kwargs: SimpleNamespace(
        content=review.canonical_bytes(), blob_sha="blob",
    ))
    monkeypatch.setattr(cli, "_prepare_public_successor_batch", lambda *_args: (
        SimpleNamespace(a2_sha256="a" * 64,
                        a2_valid_until=now.replace(year=now.year + 2)),
        facts, (SimpleNamespace(),), "f" * 64, "4" * 64,
        {COLLECTION: authority},
    ))
    monkeypatch.setattr(projection_module, "persist_projection", lambda conn, **_kwargs: (
        conn.execute("INSERT PROJECTION"), (1, 0)
    )[1])
    monkeypatch.setattr(projection_module, "load_applicable_projection", lambda *_args, **_kwargs: {
        "rights_status": "public_allowed", "gate_evaluated_at": now,
        "quality_passed": True, "quality_report_digest": "d" * 64,
        "gate_passed": True, "gate_name": "public-release",
    })
    monkeypatch.setattr(projection_module, "require_projection_authorises", lambda *_args, **_kwargs: None)
    args = SimpleNamespace(
        command="record-public-successor-release-batch-attestation",
        release_id=facts.release_id, review_id=review.review_id,
        evaluator="automated:Codex/LOT42",
        target_pin_sha256="2" * 64, transfer_v2_sha256="3" * 64,
        review_artifact_path=canonical_publication_review_path(
            review_id=review.review_id, digest=review.digest(),
        ),
    )
    result = cli._cmd_record_release_batch_attestation(args)
    assert calls == 2
    inserts = [params for sql, params in zip(connection.statements, connection.parameters, strict=False)
               if "INSERT INTO ingestion_control.publication_attestations" in sql]
    assert len(inserts) == 1
    assert inserts[0]["profile_id"] == COLLECTION
    assert inserts[0]["profile_version"] == "student-public-derivative-v1"
    assert inserts[0]["profile_fingerprint"] == "b" * 64
    assert inserts[0]["manifest_digest"] == "c" * 64
    if review_changes:
        assert result == 1 and connection.rollbacks == 1 and connection.commits == 0
    else:
        assert result == 0 and connection.rollbacks == 0 and connection.commits == 1
