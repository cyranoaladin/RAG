from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import deploy_verified_release_cli as deploy  # noqa: E402

COMPOSE = Path(__file__).resolve().parents[1] / "infra/docker-compose.production-workers.yml"
CONTAINER_PATH = "/app/production/authorization-set.json"


def test_both_production_workers_mount_the_exact_authorization_set_read_only() -> None:
    document = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    for name in (
        "multilevel-worker-a-production",
        "multilevel-worker-b-production",
    ):
        service = document["services"][name]
        assert service["environment"]["NEXUS_AUTHORIZATION_SET_PATH"] == CONTAINER_PATH
        assert service["environment"]["NEXUS_EXPECTED_READINESS_PROTOCOL"] == (
            "NEXUS-PRODUCTION-READINESS-V2"
        )
        assert (
            "${PRODUCTION_AUTHORIZATION_SET_HOST_FILE:?"
            "PRODUCTION_AUTHORIZATION_SET_HOST_FILE requis}:"
            f"{CONTAINER_PATH}:ro"
        ) in service["volumes"]


def test_set_is_never_supplied_by_an_authority_directory_mount() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    assert "NEXUS_AUTHORIZATION_SET_PATH: /app/production/authority/" not in text
    assert "PRODUCTION_AUTHORIZATION_SET_HOST_DIR" not in text


def _effective(source: Path) -> dict[str, object]:
    volume = {
        "type": "bind",
        "source": str(source),
        "target": CONTAINER_PATH,
        "read_only": True,
    }
    return {
        "services": {
            "multilevel-worker-a-production": {"volumes": [volume]},
            "multilevel-worker-b-production": {"volumes": [volume]},
        }
    }


def test_effective_bind_is_rehashed_and_must_match_signed_set(tmp_path: Path) -> None:
    source = tmp_path / "authorization-set.json"
    source.write_bytes(b"signed set\n")
    source.chmod(0o600)
    digest = deploy._sha256_bytes(source.read_bytes())

    assert deploy.require_effective_authorization_set_bind(
        effective_compose=_effective(source), expected_digest=digest
    ) == source.resolve()

    source.write_bytes(b"substituted set\n")
    with pytest.raises(deploy.DeploymentWrapperError, match="effective authorization set"):
        deploy.require_effective_authorization_set_bind(
            effective_compose=_effective(source), expected_digest=digest
        )


def test_effective_bind_refuses_symlink_and_non_read_only_mount(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_bytes(b"set\n")
    real.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(real)
    digest = deploy._sha256_bytes(real.read_bytes())

    with pytest.raises(deploy.DeploymentWrapperError, match="symlink"):
        deploy.require_effective_authorization_set_bind(
            effective_compose=_effective(link), expected_digest=digest
        )
    effective = _effective(real)
    effective["services"]["multilevel-worker-a-production"]["volumes"][0][
        "read_only"
    ] = False
    with pytest.raises(deploy.DeploymentWrapperError, match="read-only"):
        deploy.require_effective_authorization_set_bind(
            effective_compose=effective, expected_digest=digest
        )


def test_effective_bind_refuses_world_writable_or_hardlinked_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "authorization-set.json"
    source.write_bytes(b"set\n")
    digest = deploy._sha256_bytes(source.read_bytes())
    source.chmod(0o666)
    with pytest.raises(deploy.DeploymentWrapperError, match="writable"):
        deploy.require_effective_authorization_set_bind(
            effective_compose=_effective(source), expected_digest=digest
        )
    source.chmod(0o600)
    (tmp_path / "second-name.json").hardlink_to(source)
    with pytest.raises(deploy.DeploymentWrapperError, match="hardlink|link count"):
        deploy.require_effective_authorization_set_bind(
            effective_compose=_effective(source), expected_digest=digest
        )


def test_effective_bind_refuses_inode_path_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "authorization-set.json"
    source.write_bytes(b"set\n")
    source.chmod(0o600)
    digest = deploy._sha256_bytes(source.read_bytes())
    real_stat = deploy.os.stat

    def substituted_stat(path, *, follow_symlinks=True):
        metadata = real_stat(path, follow_symlinks=follow_symlinks)
        if Path(path) == source and follow_symlinks is False:
            values = list(metadata)
            values[1] += 1
            return os.stat_result(values)
        return metadata

    monkeypatch.setattr(deploy.os, "stat", substituted_stat)
    with pytest.raises(deploy.DeploymentWrapperError, match="substituted"):
        deploy.require_effective_authorization_set_bind(
            effective_compose=_effective(source), expected_digest=digest
        )


def test_durable_generation_refuses_public_directory_or_non_unique_file(
    tmp_path: Path,
) -> None:
    raw = b"signed authorization set\n"
    digest = deploy._sha256_bytes(raw)
    bundle_digest = "a" * 64
    state_root = tmp_path / "deployment-state"
    state_root.mkdir(mode=0o755)

    with pytest.raises(deploy.DeploymentWrapperError, match="mode 0700"):
        deploy._materialize_authorization_set_generation(
            state_root=state_root,
            bundle_digest=bundle_digest,
            authorization_set_digest=digest,
            raw=raw,
        )

    state_root.chmod(0o700)
    generation = deploy._materialize_authorization_set_generation(
        state_root=state_root,
        bundle_digest=bundle_digest,
        authorization_set_digest=digest,
        raw=raw,
    )
    generation.path.chmod(0o600)
    (tmp_path / "authorization-set-hardlink.json").hardlink_to(generation.path)
    with pytest.raises(deploy.DeploymentWrapperError, match="hardlink|link count"):
        deploy._materialize_authorization_set_generation(
            state_root=state_root,
            bundle_digest=bundle_digest,
            authorization_set_digest=digest,
            raw=raw,
        )


def test_durable_generation_publishes_complete_bytes_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"signed authorization set\n"
    digest = deploy._sha256_bytes(raw)
    bundle_digest = "b" * 64
    state_root = tmp_path / "deployment-state"
    final_path = (
        state_root
        / "generations"
        / f"{bundle_digest}-{digest}"
        / "authorization-set.json"
    )
    real_write = deploy.os.write
    final_was_visible_during_write: list[bool] = []

    def observing_write(descriptor: int, data: bytes) -> int:
        final_was_visible_during_write.append(final_path.exists())
        return real_write(descriptor, data)

    monkeypatch.setattr(deploy.os, "write", observing_write)
    generation = deploy._materialize_authorization_set_generation(
        state_root=state_root,
        bundle_digest=bundle_digest,
        authorization_set_digest=digest,
        raw=raw,
    )

    assert final_was_visible_during_write
    assert not any(final_was_visible_during_write)
    assert generation.path.read_bytes() == raw


def test_durable_generation_refuses_writable_ancestor_or_untrusted_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"signed authorization set\n"
    digest = deploy._sha256_bytes(raw)
    bundle_digest = "c" * 64
    replaceable_parent = tmp_path / "replaceable-parent"
    replaceable_parent.mkdir(mode=0o777)
    replaceable_parent.chmod(0o777)

    with pytest.raises(deploy.DeploymentWrapperError, match="ancestor.*writable"):
        deploy._materialize_authorization_set_generation(
            state_root=replaceable_parent / "deployment-state",
            bundle_digest=bundle_digest,
            authorization_set_digest=digest,
            raw=raw,
        )

    trusted_parent = tmp_path / "trusted-parent"
    trusted_parent.mkdir(mode=0o700)
    state_root = trusted_parent / "deployment-state"
    state_root.mkdir(mode=0o700)
    state_metadata = state_root.stat()
    real_fstat = deploy.os.fstat
    untrusted_uid = next(uid for uid in (12345, 12346) if uid not in {0, os.geteuid()})

    def other_owner(descriptor: int) -> os.stat_result:
        metadata = real_fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) == (
            state_metadata.st_dev,
            state_metadata.st_ino,
        ):
            values = list(metadata)
            values[4] = untrusted_uid
            return os.stat_result(values)
        return metadata

    monkeypatch.setattr(deploy.os, "fstat", other_owner)
    with pytest.raises(deploy.DeploymentWrapperError, match="owner"):
        deploy._materialize_authorization_set_generation(
            state_root=state_root,
            bundle_digest=bundle_digest,
            authorization_set_digest=digest,
            raw=raw,
        )


def test_durable_generation_refuses_untrusted_file_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = b"signed authorization set\n"
    digest = deploy._sha256_bytes(raw)
    generation = deploy._materialize_authorization_set_generation(
        state_root=tmp_path / "deployment-state",
        bundle_digest="d" * 64,
        authorization_set_digest=digest,
        raw=raw,
    )
    file_metadata = generation.path.stat()
    real_fstat = deploy.os.fstat
    untrusted_uid = next(uid for uid in (12345, 12346) if uid not in {0, os.geteuid()})

    def other_owner(descriptor: int) -> os.stat_result:
        metadata = real_fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) == (
            file_metadata.st_dev,
            file_metadata.st_ino,
        ):
            values = list(metadata)
            values[4] = untrusted_uid
            return os.stat_result(values)
        return metadata

    monkeypatch.setattr(deploy.os, "fstat", other_owner)
    with pytest.raises(deploy.DeploymentWrapperError, match="owner"):
        deploy._materialize_authorization_set_generation(
            state_root=tmp_path / "deployment-state",
            bundle_digest="d" * 64,
            authorization_set_digest=digest,
            raw=raw,
        )
