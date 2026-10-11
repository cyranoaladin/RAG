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

ANCHOR = ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261011.json"
RELEASE = ROOT / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_student_public_successor_v1/release-40b956c6f5ec0c60"
)
ATTESTATION = ROOT / "docs/reports/go_live/student_derivative_source_currentness_20261011.json"
NOW = datetime(2026, 10, 11, 16, tzinfo=UTC)
ANCHOR_SHA256 = "1731e2a5690c4043dd21d02576d843f90dc90c7a2f7ec2cc736f7dd3563df7e0"
ATTESTATION_SHA256 = "76c68ea269f6031244d9f8824186abe0299f2810494e1d28b02e13cc4e2d912c"
EXPECTED_PROPOSAL_SHA256 = {
    "dgemc-terminale-option": "5f262cd9ece3a0d8a21e567ae5cc02d716d7c2505ee5da2de2d7684f7ce4ef45",
    "hggsp-premiere-specialite": "6d150e54f28b5ca954094c008cf9842e03d2b98af407c89fa2fbbe5fe2fca18c",
    "hggsp-terminale-specialite": "726c3484d63ff7de4b7c1b2edab6b9f56f0bdc931e7d8bb8164ab701835f6271",
    "hlp-premiere-specialite": "6ad6009102b8485877ea383e8c158cc9d2083200ff1093ce2668c371814a90d1",
    "hlp-terminale-specialite": "34ae3b8e740484a38f3ed3d90bada4a48b353446bc490ceb6f12502559ddb00e",
    "nsi-premiere-specialite": "50fa0b2ec42c2f8988a26a9577faad00bb5136a5c0f9e5bd179598ad2eca3158",
    "nsi-terminale-specialite": "56840efb09d102535ba87c34daeb9724f215b7833c932cdde6583c8f1ed6fd56",
    "ses-premiere-specialite": "5417b457f724593cc14de6ca099c84f1b7fbba5d44cd6bb64caa91511e882fc6",
    "ses-terminale-specialite": "cfd6865868d2ce44f0e32766fe2539b5f2b25256e6d298c8e9b86c6a614d85aa",
    "svt-premiere-specialite": "6e321483785b980a5e9bc7674898f3ba7f91f8a1d95cd85c3a42be99592cbf1f",
    "svt-terminale-specialite": "349186c4af739eb0daf16c22e1afddaa1f1e23724ab53a3696355b1e4d2ca731",
}


def _proposals() -> dict[str, bytes]:
    return build_proposals(
        anchor_path=ANCHOR,
        anchor_sha256=hashlib.sha256(ANCHOR.read_bytes()).hexdigest(),
        release_root=RELEASE,
        currentness_attestation_path=ATTESTATION,
        now_utc=NOW,
    )


def test_real_a_proposes_exact_eleven_public_lot41a_artifacts() -> None:
    assert hashlib.sha256(ANCHOR.read_bytes()).hexdigest() == ANCHOR_SHA256
    assert hashlib.sha256(ATTESTATION.read_bytes()).hexdigest() == ATTESTATION_SHA256
    proposals = _proposals()
    content = verify_content_anchor(
        ANCHOR, hashlib.sha256(ANCHOR.read_bytes()).hexdigest(), RELEASE
    )
    projection = derive_public_release_scope_placement(RELEASE, content)
    assert len(proposals) == 11
    assert {
        Path(path).name.removeprefix("lot41a-student-public-").removesuffix("-v1.json"):
        hashlib.sha256(raw).hexdigest()
        for path, raw in proposals.items()
    } == EXPECTED_PROPOSAL_SHA256
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
    assert all(row.valid_until == datetime(2026, 10, 12, 13, 58, 41, 752000, tzinfo=UTC) for row in parsed)
    assert all(b"review_id" not in raw and b"signature" not in raw for raw in proposals.values())


def test_expired_a_cannot_generate_new_proposals() -> None:
    with pytest.raises(ValueError, match="expired"):
        build_proposals(
            anchor_path=ANCHOR,
            anchor_sha256=hashlib.sha256(ANCHOR.read_bytes()).hexdigest(),
            release_root=RELEASE,
            currentness_attestation_path=ATTESTATION,
            now_utc=datetime(2026, 10, 13, tzinfo=UTC),
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
