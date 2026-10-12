"""Le contrôle public relit les révocations vivantes sans rescanner LOT42."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from nexus_contracts.authority_artifacts import canonical_publication_review_path, git_blob_sha1
from nexus_release_chain.public_successor_activation import verify_content_anchor

from ingestor import public_successor_db_guard as guard
from ingestor.public_successor_db_guard import (
    PublicSuccessorDBRefused,
    _sealed_review_blob_sha,
    require_public_successor_live_controls,
    require_public_successor_pinned_db,
    require_public_successor_startup_lot42,
)


class _PinnedIdentityConn:
    def __init__(self, database: str, system: str) -> None:
        self.database = database
        self.system = system
        self.queries: list[str] = []

    def execute(self, query: str) -> _PinnedIdentityConn:
        self.queries.append(query)
        return self

    def fetchone(self) -> tuple[str, str]:
        return self.database, self.system


def test_public_mutation_requires_exact_live_database_pin(tmp_path: Path) -> None:
    pin = tmp_path / "authorities/target-pin.json"
    pin.parent.mkdir()
    document = {
        "release_id": "release", "content_anchor_sha256": "a" * 64,
        "database_name": "ragdb_student_public_qual",
        "postgres_system_identifier": "7695463567278473254",
        "expires_at_utc": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    pin.write_text(json.dumps(document))
    digest = hashlib.sha256(pin.read_bytes()).hexdigest()
    verdict = SimpleNamespace(release_id="release", content_anchor_sha256="a" * 64)
    conn = _PinnedIdentityConn("ragdb_student_public_qual", "7695463567278473254")
    require_public_successor_pinned_db(conn, verdict, tmp_path, digest)
    assert conn.queries == ["SELECT current_database(), system_identifier FROM pg_control_system()"]
    for database, system in (("foreign", conn.system), (conn.database, "999")):
        with pytest.raises(PublicSuccessorDBRefused, match="target pin"):
            require_public_successor_pinned_db(
                _PinnedIdentityConn(database, system), verdict, tmp_path, digest,
            )
    with pytest.raises(PublicSuccessorDBRefused, match="target pin"):
        require_public_successor_pinned_db(conn, verdict, tmp_path, "b" * 64)
    document["expires_at_utc"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    pin.write_text(json.dumps(document))
    with pytest.raises(PublicSuccessorDBRefused, match="target pin"):
        require_public_successor_pinned_db(
            conn, verdict, tmp_path, hashlib.sha256(pin.read_bytes()).hexdigest(),
        )

_real_worker_transfer_sha_from_bundle = guard._worker_transfer_sha_from_bundle

AUTH_ID = "student-public-maths"
COLLECTION = "rag_nexus_maths_premiere_gen_specialite"
AUTH_SHA = "a" * 64
REVIEW_SHA = "b" * 64
MANIFEST_SHA = "c" * 64
ARTIFACT_SHA = "d" * 64
INVENTORY_SHA = "e" * 64
TRANSFER_SHA = "f" * 64
CONTENT_SHA = "1" * 64
FINGERPRINT = ARTIFACT_SHA
SOURCE_PLACEMENT = "3" * 64
PLACEMENT = "4" * 64
REVIEW_ID = "public-batch-review"
REVIEW_DIGEST = "5" * 64
REVIEW_BINDING = (
    "6" * 40, "7" * 40, "8" * 40, 123,
    "NEXUS-TRUSTED-REVIEW-V1:test", "reviewer-fixture",
)


@pytest.fixture(autouse=True)
def _unit_db_guard_transfer(monkeypatch: pytest.MonkeyPatch) -> None:
    """These DB-row unit fixtures use one synthetic transfer identity."""
    monkeypatch.setattr(guard, "_worker_transfer_sha_from_bundle", lambda *_: TRANSFER_SHA)


def test_startup_transfer_evidence_cannot_be_missing(tmp_path: Path) -> None:
    with pytest.raises(PublicSuccessorDBRefused, match="evidence missing"):
        _real_worker_transfer_sha_from_bundle(_verdict(), tmp_path)


def test_sealed_lot42_review_blob_is_derived_from_bytes_not_git_tree(tmp_path: Path) -> None:
    review = tmp_path / "authorities/publication_batch_review_receipt_sha256.bin"
    review.parent.mkdir()
    raw = b"exact reviewed LOT42 artifact"
    review.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    assert _sealed_review_blob_sha(tmp_path, digest) == git_blob_sha1(raw)
    assert _sealed_review_blob_sha(tmp_path, digest) != REVIEW_BINDING[2]
    with pytest.raises(PublicSuccessorDBRefused, match="digest differs"):
        _sealed_review_blob_sha(tmp_path, "0" * 64)


class _Cursor:
    def __init__(self, database: _Database) -> None:
        self.database = database
        self.query = ""

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.database.queries.append(query)
        if self.database.fail:
            raise OSError("DB unavailable")
        self.query = query
        self.database.params.append(params)

    def fetchall(self) -> list[tuple[object, ...]]:
        if "scope_authorizations" in self.query:
            return [] if self.database.missing else [(
                AUTH_ID, AUTH_SHA, REVIEW_SHA, self.database.authorization_revoked_at,
                self.database.valid_from, self.database.valid_until,
            )]
        if "revoked_review_evidence" in self.query:
            return [(REVIEW_SHA,)] if self.database.review_revoked else []
        if "JOIN ingestion_control.artifacts" in self.query:
            return self.database.sealed_rows
        if "FROM ingestion_control.publication_attestations" in self.query:
            return self.database.attestations
        raise AssertionError(self.query)

    def fetchone(self) -> tuple[bool]:
        if "publication_attestations" in self.query:
            return (self.database.lot42_invalidated,)
        if "sealed_release_adoptions" in self.query:
            return (False,)
        raise AssertionError(self.query)


class _Database:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.params: list[tuple[object, ...]] = []
        self.fail = False
        self.missing = False
        self.review_revoked = False
        self.lot42_invalidated = False
        self.authorization_revoked_at: datetime | None = None
        self.valid_from = datetime.now(UTC) - timedelta(minutes=1)
        self.valid_until = datetime.now(UTC) + timedelta(minutes=5)
        self.sealed_rows = [(
            "resource", "artifact", COLLECTION, CONTENT_SHA, {
                "release_manifest_sha256": MANIFEST_SHA,
                "artifacts_release_sha256": ARTIFACT_SHA,
                "candidate_inventory_sha256": INVENTORY_SHA,
                "artifact_transfer_manifest_sha256": TRANSFER_SHA,
                "source_placement_id": SOURCE_PLACEMENT,
                "placement_id": PLACEMENT,
                "currentness": "official_snapshot",
                "provenance_artifact_url": "https://example.test/source",
                "chunk_count": 1,
                "scope_authorization_id": AUTH_ID,
                "review_status": "reviewed",
                "placement_status": "active",
                "media_type": "text/plain; charset=utf-8",
            },
        )]
        self.attestations = [(
            "resource", "artifact", CONTENT_SHA, COLLECTION, AUTH_ID,
            "LOT42-RELEASE-BATCH-V1", MANIFEST_SHA, ARTIFACT_SHA,
            INVENTORY_SHA, TRANSFER_SHA, REVIEW_DIGEST, REVIEW_ID,
            canonical_publication_review_path(review_id=REVIEW_ID, digest=REVIEW_DIGEST),
            REVIEW_BINDING[2],
            FINGERPRINT, "public_allowed", datetime.now(UTC), True, "9" * 64,
            datetime.now(UTC), True, datetime.now(UTC), ["event"],
            "cyranoaladin/RAG", REVIEW_BINDING[0], REVIEW_BINDING[1],
            REVIEW_BINDING[3], REVIEW_BINDING[5], REVIEW_BINDING[4],
            None, "attestation", REVIEW_DIGEST,
        )]

    def cursor(self) -> _Cursor:
        return _Cursor(self)


def _verdict() -> SimpleNamespace:
    return SimpleNamespace(
        release_id="student-public-release-test",
        content_manifest_sha256=MANIFEST_SHA,
        content_anchor_sha256="6" * 64,
        artifact_registry_sha256=ARTIFACT_SHA,
        counts={"subjects": 1, "unique_artifacts": 1, "placements": 1, "unique_chunks": 1},
        authorization_review_evidence_by_id=((COLLECTION, AUTH_ID, AUTH_SHA, REVIEW_SHA),),
        transfer_manifest_sha256=TRANSFER_SHA,
        publication_batch_review_id=REVIEW_ID,
        publication_batch_review_digest=REVIEW_DIGEST,
        publication_batch_review_binding=REVIEW_BINDING,
        expires_at_utc=datetime.now(UTC) + timedelta(minutes=5),
    )


def test_live_controls_query_only_bound_authority_and_invalidations() -> None:
    database = _Database()
    require_public_successor_live_controls(database, _verdict())
    assert len(database.queries) == 3
    assert all("resources" not in query for query in database.queries)
    assert all("artifacts" not in query for query in database.queries)
    assert database.params[0] == ([AUTH_ID],)


@pytest.mark.parametrize("fault", [
    "missing", "review_revoked", "lot42_invalidated", "authorization_revoked_at", "fail",
])
def test_live_controls_fail_closed_after_startup(fault: str) -> None:
    database = _Database()
    setattr(database, fault, True if fault != "authorization_revoked_at" else datetime.now(UTC))
    with pytest.raises(PublicSuccessorDBRefused):
        require_public_successor_live_controls(database, _verdict())


def test_live_controls_refuse_unbound_expected_authority() -> None:
    database = _Database()
    verdict = _verdict()
    verdict.authorization_review_evidence_by_id = ()
    with pytest.raises(PublicSuccessorDBRefused):
        require_public_successor_live_controls(database, verdict)
    assert database.queries == []


def test_startup_replays_full_lot42_and_matches_expected_authorizations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor import public_successor_db_guard as guard

    monkeypatch.setattr(guard, "_sealed_review_blob_sha", lambda *_: REVIEW_BINDING[2])

    calls: list[str] = []
    monkeypatch.setattr(guard, "_expected_lot42_population", lambda *_: calls.append("A") or (
        {(COLLECTION, CONTENT_SHA, SOURCE_PLACEMENT): (
            PLACEMENT, "official_snapshot", FINGERPRINT, "https://example.test/source", 1,
        )}, INVENTORY_SHA,
    ))
    verdict = _verdict()
    database = _Database()
    observed = require_public_successor_startup_lot42(database, verdict, tmp_path)
    assert calls == ["A"]
    assert len(database.queries) == 3
    assert observed == 1


def test_startup_refuses_lot42_reviewer_different_from_c(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor import public_successor_db_guard as guard

    monkeypatch.setattr(guard, "_sealed_review_blob_sha", lambda *_: REVIEW_BINDING[2])

    monkeypatch.setattr(guard, "_expected_lot42_population", lambda *_: (
        {(COLLECTION, CONTENT_SHA, SOURCE_PLACEMENT): (
            PLACEMENT, "official_snapshot", FINGERPRINT, "https://example.test/source", 1,
        )}, INVENTORY_SHA,
    ))
    database = _Database()
    row = list(database.attestations[0])
    row[27] = "foreign-reviewer"
    database.attestations = [tuple(row)]
    with pytest.raises(PublicSuccessorDBRefused, match="LOT42 attestation differs"):
        require_public_successor_startup_lot42(database, _verdict(), tmp_path)


def test_startup_refuses_lot42_binding_without_reviewer(tmp_path: Path) -> None:
    verdict = _verdict()
    verdict.publication_batch_review_binding = (*REVIEW_BINDING[:5], "")
    database = _Database()
    with pytest.raises(PublicSuccessorDBRefused, match="signed review expectations"):
        require_public_successor_startup_lot42(database, verdict, tmp_path)
    assert database.queries == []


def test_startup_refuses_expired_c_before_query(tmp_path: Path) -> None:
    database = _Database()
    verdict = _verdict()
    verdict.expires_at_utc = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(PublicSuccessorDBRefused, match="C expired"):
        require_public_successor_startup_lot42(database, verdict, tmp_path)
    assert database.queries == []


def test_startup_refuses_lot42_foreign_authorization_before_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor import public_successor_db_guard as guard

    monkeypatch.setattr(guard, "_sealed_review_blob_sha", lambda *_: REVIEW_BINDING[2])

    monkeypatch.setattr(guard, "_expected_lot42_population", lambda *_: (
        {(COLLECTION, CONTENT_SHA, SOURCE_PLACEMENT): (
            PLACEMENT, "official_snapshot", FINGERPRINT, "https://example.test/source", 1,
        )}, INVENTORY_SHA,
    ))
    verdict = _verdict()
    database = _Database()
    database.sealed_rows[0][4]["scope_authorization_id"] = "foreign"
    with pytest.raises(PublicSuccessorDBRefused, match="LOT42 sealed row"):
        require_public_successor_startup_lot42(database, verdict, tmp_path)


@pytest.mark.parametrize("column", [
    "rights", "quality_digest", "events", "review_head", "review_blob",
    "attestation_digest",
])
def test_startup_refuses_lot42_attestation_without_substantive_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, column: str,
) -> None:
    from ingestor import public_successor_db_guard as guard

    monkeypatch.setattr(guard, "_sealed_review_blob_sha", lambda *_: REVIEW_BINDING[2])

    monkeypatch.setattr(guard, "_expected_lot42_population", lambda *_: (
        {(COLLECTION, CONTENT_SHA, SOURCE_PLACEMENT): (
            PLACEMENT, "official_snapshot", FINGERPRINT, "https://example.test/source", 1,
        )}, INVENTORY_SHA,
    ))
    database = _Database()
    positions = {"rights": 15, "quality_digest": 18, "events": 22,
                 "review_head": 25, "review_blob": 13,
                 "attestation_digest": 31}
    changed = list(database.attestations[0])
    changed[positions[column]] = {
        "rights": "usage_interne", "quality_digest": "", "events": [],
        "review_head": "f" * 40, "review_blob": "e" * 40,
        "attestation_digest": "0" * 64,
    }[column]
    database.attestations = [tuple(changed)]
    with pytest.raises(PublicSuccessorDBRefused, match="LOT42 attestation"):
        require_public_successor_startup_lot42(database, _verdict(), tmp_path)


def test_real_a_derives_exact_public_lot42_population(tmp_path: Path) -> None:
    from ingestor.public_successor_db_guard import _expected_lot42_population

    repository = Path(__file__).resolve().parents[3]
    anchor = repository / "docs/reports/go_live/student_public_successor_content_anchor_20261010.json"
    release = (
        repository / "services/rag-pedago/data/releases/prerentree_2026_2027"
        / "profile_gate_student_public_successor_v1/release-fcc84331e7700042"
    )
    shutil.copyfile(anchor, tmp_path / "content-anchor.json")
    (tmp_path / "release").symlink_to(release, target_is_directory=True)
    content = verify_content_anchor(anchor, hashlib.sha256(anchor.read_bytes()).hexdigest(), release)
    verdict = SimpleNamespace(
        content_anchor_sha256=content.content_anchor_sha256,
        release_id=content.release_id,
        content_manifest_sha256=content.content_manifest_sha256,
        artifact_registry_sha256=content.artifact_registry_sha256,
        counts=content.expected_counts,
    )
    placements, inventory_sha = _expected_lot42_population(verdict, tmp_path)
    assert len(placements) == 377
    assert len({key[1] for key in placements}) == 253
    assert len({key[0] for key in placements}) == 11
    assert inventory_sha == content.candidate_inventory_sha256
    assert {facts[2] for facts in placements.values()} == {
        content.artifact_registry_sha256,
    }
