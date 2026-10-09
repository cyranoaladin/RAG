"""Qualification locale et sans mutation des matériaux du candidat public."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import public_blue_green_preflight as preflight  # noqa: E402

SHA = "a" * 40
IMAGE = "ghcr.io/cyranoaladin/rag-ingestor@sha256:" + "b" * 64
TARGETS = {
    "/docker-entrypoint-initdb.d/00_init.sql": "postgres/init.sql",
    "/docker-entrypoint-initdb.d/01_003_profile_filtering.sql": "postgres/migrations/003_profile_filtering.sql",
    "/docker-entrypoint-initdb.d/02_004_artifact_placements.sql": "postgres/migrations/004_artifact_placements.sql",
    "/docker-entrypoint-initdb.d/03_005_official_snapshot_currentness.sql": "postgres/migrations/005_official_snapshot_currentness.sql",
    "/docker-entrypoint-initdb.d/04_register_bootstrap_migrations.sh": "postgres/register_bootstrap_migrations.sh",
    "/docker-entrypoint-initdb.d/05_provision_runtime_roles.sh": "postgres/provision_runtime_roles.sh",
    "/docker-entrypoint-migrations": "postgres/migrations",
    "/docker-entrypoint-healthcheck.sh": "postgres/healthcheck.sh",
    "/pgvector-migration-state.sh": "scripts/lib/pgvector_migration_state.sh",
    "/schema-head-005-fingerprints.env": "postgres/schema_head_005_fingerprints.env",
    "/schema-head-005-columns.tsv": "postgres/schema_head_005_columns.tsv",
    "/app/configs": "configs",
    "/app/release": "release",
    "/app/servable-corpus": "servable-corpus",
    "/models/e5-large": "models/e5-large",
    "/models/reranker": "models/reranker",
    "/etc/prometheus/prometheus.yml": "prometheus/prometheus.v2.yml",
    "/etc/prometheus/rules": "prometheus/rules",
}


def _fixture(tmp_path: Path) -> tuple[dict, Path, Path, Path]:
    repo = tmp_path / "checkout"
    repo.mkdir()
    root = tmp_path / "release-x"
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    secret = secret_root / "api-clients.json"
    secret.write_text("{}", encoding="utf-8")
    files: dict[str, str] = {}
    for relative in set(TARGETS.values()):
        path = root / relative
        if Path(relative).suffix:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative, encoding="utf-8")
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            path.mkdir(parents=True, exist_ok=True)
            child = path / "payload.bin"
            child.write_text(relative, encoding="utf-8")
            files[str(child.relative_to(root))] = hashlib.sha256(child.read_bytes()).hexdigest()
    manifest = {"protocol": "NEXUS-PUBLIC-MATERIAL-V1", "source_sha": SHA, "files": files}
    raw = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (root / "release-material-manifest.json").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()

    def bind(source: Path, target: str) -> dict:
        return {"type": "bind", "source": str(source), "target": target, "read_only": True}

    volumes = {
        "pgvector": [
            bind(root / relative, target)
            for target, relative in TARGETS.items()
            if target.startswith(("/docker-entrypoint-", "/pgvector-", "/schema-head-"))
        ],
        "ingestor": [
            *(
                bind(root / relative, target)
                for target, relative in TARGETS.items()
                if target.startswith(("/app/", "/models/"))
            ),
            bind(secret, "/app/api-clients/api-clients.json"),
        ],
        "prometheus": [
            bind(root / relative, target)
            for target, relative in TARGETS.items()
            if target.startswith("/etc/prometheus/")
        ],
    }
    config = {
        "name": "nexus-rag-blue",
        "services": {
            "pgvector": {
                "image": "pgvector/pgvector@sha256:" + "c" * 64,
                "environment": {"POSTGRES_DB": "ragdb"},
                "volumes": [*volumes["pgvector"], {"type": "volume", "source": "nexus-rag-blue_rag_pgvector_data", "target": "/var/lib/postgresql/data"}],
                "ports": [],
            },
            "ingestor": {
                "image": IMAGE,
                "environment": {
                    "PG_RAG_DSN": "postgresql://rag_reader:dummy@pgvector:5432/ragdb",
                    "PG_REVIEW_DSN": "postgresql://rag_reviewer:dummy@pgvector:5432/ragdb",
                },
                "volumes": volumes["ingestor"],
                "ports": [{"host_ip": "127.0.0.1", "published": "18101", "target": 8001}],
                "labels": {"nexus.release-material.sha256": digest},
            },
            "prometheus": {
                "image": "prom/prometheus@sha256:" + "d" * 64,
                "volumes": [*volumes["prometheus"], {"type": "volume", "source": "nexus-rag-blue_rag_prometheus_data", "target": "/prometheus"}],
                "ports": [{"host_ip": "127.0.0.1", "published": "19101", "target": 9090}],
            },
        },
    }
    return config, root, secret_root, repo


def _check(config: dict, root: Path, secrets: Path, repo: Path) -> dict:
    return preflight.require_public_candidate(
        resolved_compose=config,
        source_sha=SHA,
        color="blue",
        material_root=root,
        secrets_root=secrets,
        repo_root=repo,
        verified_application_images={"ingestor": IMAGE},
    )


def test_accepts_exact_public_candidate_material(tmp_path: Path) -> None:
    config, root, secrets, repo = _fixture(tmp_path)
    evidence = _check(config, root, secrets, repo)
    assert evidence["project"] == "nexus-rag-blue"
    assert evidence["material_files"] == 18
    assert evidence["api_image"] == IMAGE
    assert evidence["material_manifest_digest"] == config["services"]["ingestor"]["labels"]["nexus.release-material.sha256"]


def test_live_provenance_is_checked_for_exact_source_and_api_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, root, secrets, repo = _fixture(tmp_path)
    calls: list[dict] = []

    def verify(**kwargs: object) -> dict[str, str]:
        calls.append(kwargs)
        return {"ingestor": IMAGE}

    monkeypatch.setattr(preflight.dii, "verify_application_image_provenance", verify)
    evidence = preflight.require_candidate_with_live_provenance(
        resolved_compose=config,
        source_sha=SHA,
        source_tree_sha="f" * 40,
        color="blue",
        material_root=root,
        secrets_root=secrets,
        repo_root=repo,
        provenance_run_id=42,
        provenance_run_attempt=1,
        github_api_get=lambda path: {},
        download_artifact=lambda run, name, where: where,
        work_dir=tmp_path / "work",
    )
    assert evidence["api_image"] == IMAGE
    assert calls[0]["repository"] == "cyranoaladin/RAG"
    assert calls[0]["source_commit_sha"] == SHA
    assert calls[0]["source_tree_sha"] == "f" * 40
    config["services"]["ingestor"]["image"] = "ghcr.io/cyranoaladin/rag-ingestor@sha256:" + "0" * 64
    with pytest.raises(preflight.PublicCandidateError):
        preflight.require_candidate_with_live_provenance(
            resolved_compose=config,
            source_sha=SHA,
            source_tree_sha="f" * 40,
            color="blue",
            material_root=root,
            secrets_root=secrets,
            repo_root=repo,
            provenance_run_id=42,
            provenance_run_attempt=1,
            github_api_get=lambda path: {},
            download_artifact=lambda run, name, where: where,
            work_dir=tmp_path / "work",
        )


def test_refuses_mutable_root_alias_and_hardlinked_material(tmp_path: Path) -> None:
    config, root, secrets, repo = _fixture(tmp_path)
    alias = tmp_path / "current"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(preflight.PublicCandidateError, match="symlink"):
        _check(config, alias, secrets, repo)

    linked = tmp_path / "outside-copy"
    linked.hardlink_to(root / "postgres/init.sql")
    with pytest.raises(preflight.PublicCandidateError, match="hardlinked"):
        _check(config, root, secrets, repo)


def test_refuses_release_material_under_a_different_git_worktree(tmp_path: Path) -> None:
    config, root, secrets, repo = _fixture(tmp_path)
    sibling = tmp_path / "other-worktree"
    sibling.mkdir()
    (sibling / ".git").write_text("gitdir: ../.git/worktrees/other\n", encoding="utf-8")
    moved = sibling / root.name
    root.rename(moved)
    for service in config["services"].values():
        for volume in service["volumes"]:
            source = volume.get("source", "")
            if source.startswith(str(root) + "/"):
                volume["source"] = str(moved / Path(source).relative_to(root))
    with pytest.raises(preflight.PublicCandidateError, match="checkout"):
        _check(config, moved, secrets, repo)


@pytest.mark.parametrize("mutation", ["wrong_project", "wrong_image", "writer", "public_db", "external_db", "query_override", "checkout_bind", "writable_bind", "wrong_label", "missing_label", "changed_file", "extra_file", "symlink", "missing_bind", "unlisted_target", "foreign_volume", "missing_volume"])
def test_refuses_unsealed_or_unsafe_candidate(tmp_path: Path, mutation: str) -> None:
    config, root, secrets, repo = _fixture(tmp_path)
    services = config["services"]
    if mutation == "wrong_project":
        config["name"] = "infra"
    elif mutation == "wrong_image":
        services["ingestor"]["image"] = "ghcr.io/cyranoaladin/rag-ingestor@sha256:" + "e" * 64
    elif mutation == "writer":
        services["worker"] = {"image": IMAGE}
    elif mutation == "public_db":
        services["pgvector"]["ports"] = [{"host_ip": "0.0.0.0", "published": "5436", "target": 5432}]
    elif mutation == "external_db":
        services["ingestor"]["environment"]["PG_RAG_DSN"] = "postgresql://rag_reader:dummy@historic-db:5432/ragdb"
    elif mutation == "query_override":
        services["ingestor"]["environment"]["PG_RAG_DSN"] += "?host=historic-db"
    elif mutation == "checkout_bind":
        services["ingestor"]["volumes"][0]["source"] = str(repo)
    elif mutation == "writable_bind":
        services["ingestor"]["volumes"][0]["read_only"] = False
    elif mutation == "wrong_label":
        services["ingestor"]["labels"]["nexus.release-material.sha256"] = "0" * 64
    elif mutation == "missing_label":
        services["ingestor"].pop("labels")
    elif mutation == "changed_file":
        (root / "postgres/init.sql").write_text("tampered", encoding="utf-8")
    elif mutation == "extra_file":
        (root / "configs/extra").write_text("extra", encoding="utf-8")
    elif mutation == "missing_bind":
        services["ingestor"]["volumes"].pop(0)
    elif mutation == "unlisted_target":
        services["ingestor"]["volumes"].append({"type": "bind", "source": str(root / "configs"), "target": "/app/rogue", "read_only": True})
    elif mutation == "foreign_volume":
        services["pgvector"]["volumes"][-1]["source"] = "infra_rag_pgvector_data"
    elif mutation == "missing_volume":
        services["pgvector"]["volumes"].pop()
    else:
        target = root / "postgres/init.sql"
        target.unlink()
        target.symlink_to(repo)
    with pytest.raises(preflight.PublicCandidateError):
        _check(config, root, secrets, repo)
