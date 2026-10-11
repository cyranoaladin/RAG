"""Les propositions LOT41A publiques dérivent des octets de A, sans review forgée."""

from __future__ import annotations

import hashlib
import copy
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from nexus_contracts.authority_artifacts import (
    ScopeAuthorizationArtifactV2,
    parse_scope_authorization_artifact,
)
from nexus_release_chain.public_successor_activation import (
    derive_public_release_scope_placement,
    verify_content_anchor,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/go_live"))

import build_public_lot41a_authorizations as generator  # noqa: E402
from build_public_lot41a_authorizations import build_proposals  # noqa: E402

ANCHOR = ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261010.json"
RELEASE = ROOT / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_student_public_successor_v1/release-fcc84331e7700042"
)
ATTESTATION = ROOT / "docs/reports/go_live/student_derivative_source_currentness_20261010.json"
NOW = datetime(2026, 10, 11, 7, tzinfo=UTC)


def _proposals() -> dict[str, bytes]:
    return build_proposals(
        anchor_path=ANCHOR,
        anchor_sha256=hashlib.sha256(ANCHOR.read_bytes()).hexdigest(),
        release_root=RELEASE,
        currentness_attestation_path=ATTESTATION,
        now_utc=NOW,
    )


def test_real_a_proposes_exact_eleven_public_lot41a_artifacts() -> None:
    proposals = _proposals()
    content = verify_content_anchor(
        ANCHOR, hashlib.sha256(ANCHOR.read_bytes()).hexdigest(), RELEASE
    )
    projection = derive_public_release_scope_placement(RELEASE, content)
    assert len(proposals) == 11
    parsed = [parse_scope_authorization_artifact(raw) for raw in proposals.values()]
    assert all(isinstance(row, ScopeAuthorizationArtifactV2) for row in parsed)
    assert set(proposals) == {row.canonical_path() for row in parsed}
    assert all(
        row.authorization_id == (
            "lot41a-student-public-"
            + str(row.scope.collection).removeprefix("rag_nexus_").replace("_", "-")
            + "-v1"
        )
        for row in parsed
    )
    assert all(row.decision == "AUTHORIZE_INGESTION_SCOPE" for row in parsed)
    assert all(row.scope.visibility == "public" for row in parsed)
    assert all(tuple(right.value for right in row.rights_categories) == ("public_allowed",) for row in parsed)
    assert all(row.allowed_domains == ("eduscol.education.gouv.fr",) for row in parsed)
    assert sum(len(row.allowed_content_sha256) for row in parsed) == 377
    assert len({sha for row in parsed for sha in row.allowed_content_sha256}) == 253
    assert {row.scope.collection for row in parsed} == {
        entry.scope.collection for entry in projection.placements
    }
    for row in parsed:
        expected = {
            entry.content_sha256
            for entry in projection.placements
            if entry.scope.collection == row.scope.collection
        }
        assert set(row.allowed_content_sha256) == expected
        source = next(
            entry for entry in projection.placements
            if entry.scope.collection == row.scope.collection
        )
        assert row.profile_id == source.profile_id
        assert row.profile_version == source.profile_version
        assert row.profile_fingerprint == source.profile_fingerprint
    assert all(
        row.pii_absence_evidence.startswith("profile_gate/public_pii_registry.json@sha256:")
        for row in parsed
    )
    assert all(row.valid_until == datetime(2026, 10, 11, 13, 39, 22, 520000, tzinfo=UTC) for row in parsed)
    assert all(b"review_id" not in raw and b"signature" not in raw for raw in proposals.values())


def test_expired_a_cannot_generate_new_proposals() -> None:
    with pytest.raises(ValueError, match="expired"):
        build_proposals(
            anchor_path=ANCHOR,
            anchor_sha256=hashlib.sha256(ANCHOR.read_bytes()).hexdigest(),
            release_root=RELEASE,
            currentness_attestation_path=ATTESTATION,
            now_utc=datetime(2026, 10, 12, tzinfo=UTC),
        )


def test_cli_requires_explicit_successor_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["build_public_lot41a_authorizations.py", "--write"])
    with pytest.raises(SystemExit) as error:
        generator.main()
    assert error.value.code == 2


def test_cli_uses_supplied_successor_without_old_a_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    anchor = tmp_path / "new-anchor.json"
    attestation = tmp_path / "new-attestation.json"
    release = tmp_path / "new-release"
    for path in (anchor, attestation):
        path.write_text("{}\n")
    release.mkdir()
    seen: dict = {}

    def proposed(**kwargs):
        seen.update(kwargs)
        return {"governance/authorizations/proposed.json": b"{}\n"}

    monkeypatch.setattr(generator, "ROOT", tmp_path)
    monkeypatch.setattr(generator, "build_proposals", proposed)
    monkeypatch.setattr(sys, "argv", [
        "build_public_lot41a_authorizations.py", "--write",
        "--anchor-path", str(anchor), "--anchor-sha256", "a" * 64,
        "--release-root", str(release),
        "--currentness-attestation-path", str(attestation),
    ])
    assert generator.main() == 0
    assert (tmp_path / "governance/authorizations/proposed.json").read_bytes() == b"{}\n"
    assert seen["anchor_path"] == anchor
    assert seen["anchor_sha256"] == "a" * 64
    assert seen["release_root"] == release
    assert seen["currentness_attestation_path"] == attestation


def test_attestation_digest_must_match_a(tmp_path: Path) -> None:
    changed = tmp_path / "attestation.json"
    changed.write_bytes(ATTESTATION.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="attestation"):
        build_proposals(
            anchor_path=ANCHOR,
            anchor_sha256=hashlib.sha256(ANCHOR.read_bytes()).hexdigest(),
            release_root=RELEASE,
            currentness_attestation_path=changed,
            now_utc=NOW,
        )


@pytest.mark.parametrize(
    ("filename", "field", "bad_value", "message"),
    [
        ("public_rights_registry.json", "rights_basis", "NONE", "rights"),
        ("public_pii_registry.json", "pii_gate_status", "PENDING", "PII"),
    ],
)
def test_one_negative_right_or_pii_fact_refuses_all_proposals(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    field: str,
    bad_value: str,
    message: str,
) -> None:
    original = generator._load_json

    def one_changed_fact(path: Path) -> dict:
        document = original(path)
        if path.name == filename:
            document = copy.deepcopy(document)
            document["entries"][0][field] = bad_value
        return document

    monkeypatch.setattr(generator, "_load_json", one_changed_fact)
    with pytest.raises(ValueError, match=message):
        _proposals()


@pytest.mark.parametrize(
    ("field", "bad_value", "message"),
    [
        ("profile_fingerprint", "0" * 64, "profile identity"),
        ("visibility", "internal", "public scope populations"),
    ],
)
def test_divergent_placement_or_internal_scope_refuses_all_proposals(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    bad_value: str,
    message: str,
) -> None:
    original = generator.derive_public_release_scope_placement

    def divergent_projection(release_root: Path, content):
        projection = original(release_root, content)
        entries = list(projection.placements)
        first = entries[0]
        if field == "visibility":
            entries[0] = first.model_copy(update={
                "scope": first.scope.model_copy(update={"visibility": bad_value})
            })
        else:
            entries[0] = first.model_copy(update={field: bad_value})
        return projection.model_copy(update={"placements": tuple(entries)})

    monkeypatch.setattr(generator, "derive_public_release_scope_placement", divergent_projection)
    with pytest.raises(ValueError, match=message):
        _proposals()
