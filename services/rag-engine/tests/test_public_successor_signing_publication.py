"""Le signer public ne lit aucune clé avant les autorités C et les replays live."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/rag-engine/scripts"))
sys.path.insert(0, str(ROOT / "scripts/go_live"))
sys.path.insert(0, str(ROOT / "packages/release-chain/src"))
sys.path.insert(0, str(ROOT / "packages/contracts/src"))
sys.path.insert(0, str(ROOT / "services/rag-engine/src"))

import historical_staging_target_pin_receipt as historical  # noqa: E402
import public_successor_signing_replay as replay  # noqa: E402
import sign_production_readiness_manifest_cli as production  # noqa: E402
import sign_staging_readiness_manifest_cli as staging  # noqa: E402
from nexus_release_chain.public_successor_activation import (  # noqa: E402
    PublicSuccessorActivationVerdict,
)

from tests.test_sign_production_readiness_manifest_cli import (  # noqa: E402
    APPLICATION_IMAGE_DIGESTS,
    PR_HEAD_SHA,
    PR_NUMBER,
    REPOSITORY,
    TEST_KEY_ID,
    TREE_SHA,
    UPSTREAM_IMAGE_REF,
    UPSTREAM_IMAGE_SERVICE,
    WORKFLOW_REF,
    _v2_material,
)

SHA = "a" * 64
SOURCE_ANCHOR = ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261010.json"
SOURCE_RELEASE = (
    ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027"
    / "profile_gate_student_public_successor_v1/release-fcc84331e7700042"
)


def _activation() -> PublicSuccessorActivationVerdict:
    return PublicSuccessorActivationVerdict(
        release_id="release-v2-test",
        content_anchor_sha256="b" * 64,
        content_manifest_sha256=hashlib.sha256(_v2_material().sealed_manifest_raw).hexdigest(),
        authority_envelope_sha256="c" * 64,
        artifact_registry_sha256="d" * 64,
        release_registry_sha256="e" * 64,
        scope_authority_sha256="f" * 64,
        subject_sha256_by_collection={},
        scope_sha256_by_id={},
        counts={"subjects": 11, "unique_artifacts": 253, "placements": 377, "unique_chunks": 3975},
        expires_at_utc=datetime.now(UTC) + timedelta(days=1),
    )


def test_staging_publication_replay_refusal_precedes_key_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = tmp_path / "release.json"
    release.write_text("{}\n", encoding="utf-8")
    output = tmp_path / "readiness.json"
    called: list[str] = []

    def refuse(*_args: object, **_kwargs: object) -> None:
        called.append("C")
        raise staging.SigningRefused("publication C replay refused")

    monkeypatch.setattr(staging, "_require_public_checkout_matches_merge", lambda *_: None)
    monkeypatch.setattr(staging, "_verify_public_successor_publication_replay", refuse)
    monkeypatch.setattr(staging, "_read_private_key", lambda *_: pytest.fail("key read before C"))
    result = staging.main([
        "--merge-sha", subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        ).strip(),
        "--worker-image", f"example/worker@sha256:{SHA}",
        "--allowed-release-id", "student-public-successor-test",
        "--release-manifest-file", str(release),
        "--key-id", "test", "--private-key-file", str(tmp_path / "absent.key"),
        "--trust-anchor-file", str(tmp_path / "anchor.json"),
        "--output", str(output),
        "--public-successor-phase", "PUBLICATION",
        "--public-successor-bundle-root", str(tmp_path / "bundle"),
    ])
    assert result == 1
    assert called == ["C"]
    assert not output.exists()


def test_production_v2_binds_only_typed_public_activation() -> None:
    material = _v2_material()
    verdict = _activation()
    manifest = production.assemble_and_sign_v2(
        material,
        repository=REPOSITORY,
        pr_number=PR_NUMBER,
        pr_head_sha=PR_HEAD_SHA,
        pr_head_tree_sha=TREE_SHA,
        application_image_digests=APPLICATION_IMAGE_DIGESTS,
        upstream_image_digests={UPSTREAM_IMAGE_SERVICE: UPSTREAM_IMAGE_REF},
        compose_digest=SHA,
        key_id=TEST_KEY_ID,
        workflow_ref=WORKFLOW_REF,
        public_successor_publication=replay.PublicationSigningReplayVerdict(
            activation=verdict, target_pin_sha256=SHA,
            expires_at_utc=datetime.now(UTC) + timedelta(hours=1),
        ),
    )
    assert manifest.public_successor_content_manifest_digest == verdict.content_manifest_sha256
    assert manifest.public_successor_content_anchor_digest == verdict.content_anchor_sha256
    assert manifest.public_successor_authority_envelope_digest == verdict.authority_envelope_sha256
    assert manifest.public_successor_target_pin_digest == SHA


def test_production_v2_refuses_public_activation_without_independent_pin() -> None:
    material = _v2_material()
    with pytest.raises((TypeError, ValueError, production.SigningToolError)):
        production.assemble_and_sign_v2(
            material, repository=REPOSITORY, pr_number=PR_NUMBER,
            pr_head_sha=PR_HEAD_SHA, pr_head_tree_sha=TREE_SHA,
            application_image_digests=APPLICATION_IMAGE_DIGESTS,
            upstream_image_digests={UPSTREAM_IMAGE_SERVICE: UPSTREAM_IMAGE_REF},
            compose_digest=SHA, key_id=TEST_KEY_ID, workflow_ref=WORKFLOW_REF,
            public_successor_activation=_activation(),
        )


def test_production_public_pin_expired_before_key_is_refused() -> None:
    replay_verdict = replay.PublicationSigningReplayVerdict(
        activation=_activation(), target_pin_sha256=SHA,
        expires_at_utc=datetime(2026, 10, 10, 12, tzinfo=UTC),
    )
    with pytest.raises(production.SigningToolError, match="expired before key"):
        production._require_public_publication_fresh_at_key(
            replay_verdict, datetime(2026, 10, 10, 12, tzinfo=UTC),
        )


def test_production_v2_parser_requires_explicit_successor_bundle() -> None:
    options = production._build_v2_arg_parser()._option_string_actions
    assert "--public-successor-bundle-root" in options
    assert "--public-successor-private-cas-root" in options
    assert "--public-successor-target-root" in options
    assert "--public-successor-target-pin-receipt-path" in options
    assert "--public-successor-target-pin-pull-request" in options


def test_verified_target_pin_uses_historical_authority_and_exact_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sys.path.insert(0, str(ROOT / "scripts/tests"))
    from test_historical_staging_target_pin_receipt import fixture  # noqa: PLC0415

    evidence = fixture(tmp_path)
    repository = tmp_path / "repo"
    pin_relative = Path(evidence["expected_pin_path"])
    pin_path = repository / pin_relative
    pin_path.parent.mkdir(parents=True)
    pin_path.write_bytes(evidence["pin_raw"])
    receipt_path = tmp_path / "historical-receipt.json"
    receipt_path.write_bytes(historical.canonical_receipt(evidence["receipt"]))
    called: list[tuple[Path, Path, Path, int, str, Path, str]] = []

    def check(*args: object) -> dict[str, object]:
        called.append(args)
        return historical.validate_historical_pin_receipt(**evidence)

    monkeypatch.setattr(historical, "check_historical_pin_receipt", check)
    digest, expiry = replay._verified_external_target_pin_sha256(
        repository_root=repository, target_pin_receipt_path=receipt_path,
        target_pin_path=pin_path, target_pin_pull_request=999,
        content_anchor_sha256=evidence["expected_content_anchor_sha256"],
        target_root=evidence["destination_root"], database_dsn="unused-secret",
        now_utc=evidence["now"],
    )
    assert digest == evidence["receipt"]["target_pin_sha256"]
    assert expiry > evidence["now"]
    assert called == [(
        repository, receipt_path, pin_relative, 999,
        evidence["expected_content_anchor_sha256"], evidence["destination_root"],
        "unused-secret",
    )]
    inputs = replay.PublicationSigningInputs(
        bundle_root=tmp_path / "bundle", repository_root=repository,
        content_anchor_path=tmp_path / "A.json",
        preissuance_receipt_path=tmp_path / "preissuance.json",
        private_cas_root=tmp_path / "cas", target_root=evidence["destination_root"],
        target_pin_path=pin_path, target_pin_receipt_path=receipt_path,
        target_pin_pull_request=999,
        observed_v1_receipt_path=tmp_path / "observed.json",
        database_dsn="unused-secret",
    )
    replay.recheck_publication_pin_before_key(
        inputs, expected_content_anchor_sha256=evidence["expected_content_anchor_sha256"],
        expected_pin_sha256=digest, evidence_expires_at_utc=expiry,
        now_utc=evidence["now"],
    )
    pin_path.write_bytes(b"substituted after first replay")
    with pytest.raises(replay.PublicationSigningReplayRefused):
        replay.recheck_publication_pin_before_key(
            inputs, expected_content_anchor_sha256=evidence["expected_content_anchor_sha256"],
            expected_pin_sha256=digest, evidence_expires_at_utc=expiry,
            now_utc=evidence["now"],
        )


@pytest.mark.parametrize("sabotage", [
    "pin_changed", "receipt_missing", "wrong_review", "wrong_base",
    "expired", "wrong_socket", "wrong_device_inode",
])
def test_verified_target_pin_rejects_historical_sabotage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sabotage: str,
) -> None:
    sys.path.insert(0, str(ROOT / "scripts/tests"))
    from test_historical_staging_target_pin_receipt import fixture  # noqa: PLC0415

    evidence = fixture(tmp_path)
    repository = tmp_path / "repo"
    pin_path = repository / evidence["expected_pin_path"]
    pin_path.parent.mkdir(parents=True)
    pin_path.write_bytes(evidence["pin_raw"])
    receipt_path = tmp_path / "historical-receipt.json"
    receipt_path.write_bytes(historical.canonical_receipt(evidence["receipt"]))
    if sabotage == "pin_changed":
        pin_path.write_bytes(b"substituted")
    elif sabotage == "receipt_missing":
        receipt_path.unlink()
    elif sabotage == "wrong_review":
        evidence["review_decision"]["approved"] = False
    elif sabotage == "wrong_base":
        evidence["merge_parent_sha"] = "0" * 40
    elif sabotage == "expired":
        evidence["now"] = evidence["now"] + timedelta(hours=3)
    elif sabotage == "wrong_socket":
        evidence["observation"] = replace(evidence["observation"], database_name="other_db")
    elif sabotage == "wrong_device_inode":
        evidence["observation"] = replace(evidence["observation"], destination_inode=1)

    monkeypatch.setattr(
        historical, "check_historical_pin_receipt",
        lambda *_: historical.validate_historical_pin_receipt(**evidence),
    )
    with pytest.raises(ValueError):
        replay._verified_external_target_pin_sha256(
            repository_root=repository, target_pin_receipt_path=receipt_path,
            target_pin_path=pin_path, target_pin_pull_request=999,
            content_anchor_sha256=evidence["expected_content_anchor_sha256"],
            target_root=evidence["destination_root"], database_dsn="unused-secret",
            now_utc=evidence["now"],
        )


def test_staging_signer_refuses_output_alias_to_private_key(tmp_path: Path) -> None:
    key = tmp_path / "operator.key"
    key.write_text("secret", encoding="utf-8")
    args = SimpleNamespace(output=key, private_key_file=key)
    with pytest.raises(staging.SigningRefused, match="output aliases"):
        staging._reject_output_aliasing_inputs(args)


def test_staging_public_signer_rejects_local_head_not_live_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def git(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(tmp_path), *args], text=True,
        ).strip()

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Test")
    (tmp_path / "tracked").write_text("a")
    git("add", "tracked")
    git("commit", "-qm", "a")
    monkeypatch.setattr(staging, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        production, "_require_live_main_head",
        lambda *_: (_ for _ in ()).throw(
            production.SigningToolError("live main differs")
        ),
    )
    with pytest.raises(staging.SigningRefused, match="live main"):
        staging._require_public_checkout_matches_merge(git("rev-parse", "HEAD"))


def test_staging_public_signer_rechecks_main_immediately_before_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = tmp_path / "release.json"
    release.write_text("{}\n")
    dsn_file = tmp_path / "database.dsn"
    dsn_file.write_text("postgresql://example.invalid/unused")
    calls: list[str] = []
    monkeypatch.setattr(
        staging, "_require_public_checkout_matches_merge",
        lambda *_: calls.append("main"),
    )
    monkeypatch.setattr(
        staging, "_verify_public_successor_publication_replay",
        lambda *_: ("a" * 64, "b" * 64, SHA, datetime.now(UTC) + timedelta(days=1)),
    )
    monkeypatch.setattr(
        replay, "recheck_publication_pin_before_key",
        lambda *_a, **_k: calls.append("pin"),
    )

    def key(*_args: object) -> str:
        assert calls == ["main", "main", "pin"]
        raise staging.SigningRefused("test stopped at key boundary")

    monkeypatch.setattr(staging, "_read_private_key", key)
    result = staging.main([
        "--merge-sha", subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        ).strip(),
        "--worker-image", f"example/worker@sha256:{SHA}",
        "--allowed-release-id", "student-public-successor-test",
        "--release-manifest-file", str(release),
        "--key-id", "test", "--private-key-file", str(tmp_path / "absent.key"),
        "--trust-anchor-file", str(tmp_path / "anchor.json"),
        "--output", str(tmp_path / "readiness.json"),
        "--public-successor-phase", "PUBLICATION",
        "--public-successor-database-dsn-file", str(dsn_file),
    ])
    assert result == 1


def test_staging_publication_manifest_receives_verified_pin_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = tmp_path / "release.json"
    release.write_text("{}\n")
    dsn_file = tmp_path / "database.dsn"
    dsn_file.write_text("postgresql://example.invalid/unused")
    monkeypatch.setattr(staging, "_require_public_checkout_matches_merge", lambda *_: None)
    monkeypatch.setattr(
        staging, "_verify_public_successor_publication_replay",
        lambda *_: ("a" * 64, "b" * 64, SHA, datetime.now(UTC) + timedelta(days=1)),
    )
    monkeypatch.setattr(staging, "_read_private_key", lambda *_: "dummy")
    monkeypatch.setattr(replay, "recheck_publication_pin_before_key", lambda *_a, **_k: None)

    seen: list[str] = []

    def capture(manifest: object, **_kwargs: object) -> object:
        seen.append("manifest")
        assert manifest.public_successor_target_pin_digest == SHA
        raise staging.SigningRefused("stopped after manifest assembly")

    monkeypatch.setattr(staging, "sign_staging_readiness_manifest", capture)
    result = staging.main([
        "--merge-sha", subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        ).strip(),
        "--worker-image", f"example/worker@sha256:{SHA}",
        "--allowed-release-id", "student-public-successor-test",
        "--release-manifest-file", str(release),
        "--key-id", "test", "--private-key-file", str(tmp_path / "absent.key"),
        "--trust-anchor-file", str(tmp_path / "anchor.json"),
        "--output", str(tmp_path / "readiness.json"),
        "--public-successor-phase", "PUBLICATION",
        "--public-successor-database-dsn-file", str(dsn_file),
    ])
    assert result == 1
    assert seen == ["manifest"]


def test_staging_atomic_write_preserves_external_hardlinked_evidence(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence.bin"
    evidence.write_bytes(b"sealed evidence")
    output = tmp_path / "readiness.json"
    os.link(evidence, output)
    staging._atomic_private_write(output, b"signed readiness")
    assert evidence.read_bytes() == b"sealed evidence"
    assert output.read_bytes() == b"signed readiness"
    assert not os.path.samefile(evidence, output)
    assert output.stat().st_mode & 0o777 == 0o600


def test_public_candidate_v2_without_c_bundle_refused_before_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = SimpleNamespace(
        public_candidate=True, public_successor_bundle_root=None,
        pr_head_sha="1" * 40, merge_sha="2" * 40,
    )
    monkeypatch.setattr(
        production, "_build_v2_arg_parser",
        lambda: SimpleNamespace(parse_args=lambda *_: args),
    )
    monkeypatch.setattr(production, "_reject_v2_output_aliasing_an_input", lambda *_: None)
    monkeypatch.setattr(
        production, "_hex",
        lambda *_: pytest.fail("production key path reached without C"),
    )
    assert production._main_v2([]) == 1


def test_publication_replay_keeps_real_c_red_before_any_live_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "content-anchor.json").write_bytes(SOURCE_ANCHOR.read_bytes())
    (bundle / "release").symlink_to(SOURCE_RELEASE, target_is_directory=True)
    (bundle / "authority-envelope.json").write_text(
        json.dumps({"authorities": {"public_scope_authority_sha256": SHA}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        replay.importlib, "import_module",
        lambda name: pytest.fail(f"live replay {name} reached before C"),
    )
    inputs = replay.PublicationSigningInputs(
        bundle_root=bundle,
        repository_root=ROOT,
        content_anchor_path=SOURCE_ANCHOR,
        preissuance_receipt_path=tmp_path / "absent-preissuance.json",
        private_cas_root=tmp_path / "cas",
        target_root=tmp_path,
        target_pin_path=Path("governance/staging_target_pins/absent-pin.json"),
        target_pin_receipt_path=tmp_path / "absent-pin-receipt.json",
        target_pin_pull_request=999,
        observed_v1_receipt_path=tmp_path / "absent-observed.json",
        database_dsn="postgresql://example.invalid/unused",
    )
    with pytest.raises(ValueError, match="publication evidence absent"):
        replay.replay_public_successor_publication(
            inputs,
            expected_release_id="student-public-successor-20261010-fcc84331e7700042",
            expected_manifest_sha256="b79246ff356b919aeb3dcb7f640a1a554e338899128a7c5acdcfaa9b7bcb1c78",
            now_utc=datetime(2026, 10, 10, 12, tzinfo=UTC),
        )


def test_publication_c_replay_receives_only_independently_verified_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "content-anchor.json").write_bytes(SOURCE_ANCHOR.read_bytes())
    (bundle / "release").symlink_to(SOURCE_RELEASE, target_is_directory=True)
    (bundle / "authority-envelope.json").write_text(
        json.dumps({"authorities": {"public_scope_authority_sha256": SHA}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        replay, "_verified_external_target_pin_sha256",
        lambda **_: (SHA, datetime.now(UTC) + timedelta(days=1)),
    )
    seen: list[str] = []

    def c_refuses(*_args: object, **kwargs: object) -> object:
        seen.append(kwargs["expected_target_pin_sha256"])
        raise replay.PublicationSigningReplayRefused("stopped at C")

    monkeypatch.setattr(replay, "verify_public_successor_activation", c_refuses)
    inputs = replay.PublicationSigningInputs(
        bundle_root=bundle, repository_root=ROOT, content_anchor_path=SOURCE_ANCHOR,
        preissuance_receipt_path=tmp_path / "receipt.json",
        private_cas_root=tmp_path / "cas", target_root=tmp_path,
        target_pin_path=tmp_path / "pin.json",
        target_pin_receipt_path=tmp_path / "pin-receipt.json",
        target_pin_pull_request=999,
        observed_v1_receipt_path=tmp_path / "observed.json",
        database_dsn="postgresql://example.invalid/unused",
    )
    with pytest.raises(replay.PublicationSigningReplayRefused, match="stopped at C"):
        replay.replay_public_successor_publication(
            inputs, expected_release_id="student-public-successor-20261010-fcc84331e7700042",
            expected_manifest_sha256="b79246ff356b919aeb3dcb7f640a1a554e338899128a7c5acdcfaa9b7bcb1c78",
            now_utc=datetime(2026, 10, 10, 12, tzinfo=UTC),
        )
    assert seen == [SHA]


def test_publication_refuses_self_declared_target_pin_before_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "content-anchor.json").write_bytes(SOURCE_ANCHOR.read_bytes())
    (bundle / "release").symlink_to(SOURCE_RELEASE, target_is_directory=True)
    envelope_raw = json.dumps({
        "authorities": {"public_scope_authority_sha256": SHA},
    }).encode()
    (bundle / "authority-envelope.json").write_bytes(envelope_raw)
    receipt = tmp_path / "preissuance.json"
    receipt.write_text("{}\n", encoding="utf-8")
    anchor_sha = hashlib.sha256(SOURCE_ANCHOR.read_bytes()).hexdigest()
    verdict = replace(
        _activation(),
        release_id="student-public-successor-20261010-fcc84331e7700042",
        content_anchor_sha256=anchor_sha,
        content_manifest_sha256="b79246ff356b919aeb3dcb7f640a1a554e338899128a7c5acdcfaa9b7bcb1c78",
        authority_envelope_sha256=hashlib.sha256(envelope_raw).hexdigest(),
        scope_authority_sha256=SHA,
    )
    monkeypatch.setattr(replay, "verify_public_successor_activation", lambda *_a, **_k: verdict)

    def importer(name: str) -> object:
        if name == "pr294_scope_review_receipt":
            return SimpleNamespace(check_pr294_scope_review_receipt=lambda *_: {
                "PR294_SCOPE_REVIEW_PASS": True,
                "PUBLIC_SCOPE_AUTHORITY_SHA256": SHA,
                "SCOPE_COUNT": 11,
            })
        if name == "check_public_successor_preissuance":
            return SimpleNamespace(verify_preissuance_authority=lambda *_: SimpleNamespace(
                preissuance_verified=True,
                publication_authorized=False,
                content_anchor_sha256=anchor_sha,
                expires_at_utc=datetime.now(UTC) + timedelta(days=1),
            ))
        pytest.fail(f"{name} reached with a self-declared target pin")

    monkeypatch.setattr(replay, "_checkout_module", importer)
    inputs = replay.PublicationSigningInputs(
        bundle_root=bundle, repository_root=ROOT, content_anchor_path=SOURCE_ANCHOR,
        preissuance_receipt_path=receipt, private_cas_root=tmp_path / "cas",
        target_root=tmp_path,
        target_pin_path=Path("governance/staging_target_pins/absent-pin.json"),
        target_pin_receipt_path=tmp_path / "pin-receipt.json",
        target_pin_pull_request=999,
        observed_v1_receipt_path=tmp_path / "observed.json",
        database_dsn="postgresql://example.invalid/unused",
    )
    with pytest.raises(ValueError, match="publication evidence absent"):
        replay.replay_public_successor_publication(
            inputs, expected_release_id=verdict.release_id,
            expected_manifest_sha256=verdict.content_manifest_sha256,
            now_utc=datetime(2026, 10, 10, 12, tzinfo=UTC),
        )


def test_publication_replay_rejects_checker_from_foreign_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    foreign = SimpleNamespace(__file__=str(tmp_path / "check_public_successor_preissuance.py"))
    monkeypatch.setattr(replay.importlib, "import_module", lambda *_: foreign)
    with pytest.raises(replay.PublicationSigningReplayRefused, match="current checkout"):
        replay._checkout_module("check_public_successor_preissuance")
