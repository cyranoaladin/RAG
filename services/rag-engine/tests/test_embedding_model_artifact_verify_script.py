"""Tests for verify-embedding-model-artifact.sh.

Validates that the verifier correctly distinguishes between legitimate tokenizer
vocabulary (economic, economica, economico) and actual forbidden Nomic 768d
embedding model references.

All tests use fake artifacts in tmp_path with SKIP_LOAD_TEST=1 — no model
download occurs.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "e2e" / "verify-embedding-model-artifact.sh"


def _make_fake_artifact(
    tmp_path: Path,
    *,
    model_id: str = "intfloat/multilingual-e5-large",
    canonical_dim: int = 1024,
    extra_json_files: dict[str, str] | None = None,
) -> Path:
    """Create a minimal fake artifact directory with manifest and checksums."""
    artifact = tmp_path / "artifact"
    artifact.mkdir()

    manifest = {
        "model_id": model_id,
        "canonical_dim": canonical_dim,
        "revision_requested": "abc123",
        "file_count": 1,
        "total_size_bytes": 100,
    }
    (artifact / "manifest.json").write_text(json.dumps(manifest))

    # Write extra JSON files (e.g. tokenizer.json with vocabulary)
    if extra_json_files:
        for name, content in extra_json_files.items():
            (artifact / name).write_text(content)

    # Generate SHA256SUMS for all files except manifest.json and SHA256SUMS
    checksums_lines = []
    for f in sorted(artifact.rglob("*")):
        if f.is_file() and f.name not in ("SHA256SUMS", "manifest.json"):
            h = hashlib.sha256(f.read_bytes()).hexdigest()
            rel = f.relative_to(artifact)
            checksums_lines.append(f"{h}  {rel}")
    (artifact / "SHA256SUMS").write_text("\n".join(checksums_lines) + "\n")

    return artifact


def _run_verify(artifact_dir: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "MODEL_ARTIFACT_DIR": str(artifact_dir),
        "SKIP_LOAD_TEST": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }
    return subprocess.run(
        ["bash", str(VERIFY_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
    )


class TestNomicFalsePositive:
    """Vocabulary words containing 'nomic' must not trigger failure."""

    @pytest.mark.parametrize(
        "word",
        ["economic", "economica", "economico", "onomic", "taxonomic"],
    )
    def test_vocabulary_word_does_not_trigger_failure(
        self, tmp_path: Path, word: str
    ) -> None:
        tokenizer_content = json.dumps(
            {"model": {"vocab": {f"▁{word}": 12345, word: 67890}}}
        )
        artifact = _make_fake_artifact(
            tmp_path,
            extra_json_files={"tokenizer.json": tokenizer_content},
        )
        result = _run_verify(artifact)
        assert result.returncode == 0, (
            f"Verification should pass with '{word}' in vocabulary.\n"
            f"stderr: {result.stderr}"
        )
        assert "Artifact verification passed" in result.stdout


class TestNomicTruePositive:
    """Explicit forbidden embedding references must trigger failure."""

    def test_nomic_embed_text_in_config(self, tmp_path: Path) -> None:
        config_content = json.dumps({"model_name": "nomic-embed-text:v1.5"})
        artifact = _make_fake_artifact(
            tmp_path,
            extra_json_files={"config.json": config_content},
        )
        result = _run_verify(artifact)
        assert result.returncode == 1
        assert "Forbidden embedding reference" in result.stderr

    def test_nomic_ai_reference(self, tmp_path: Path) -> None:
        config_content = json.dumps({"source": "nomic-ai/nomic"})
        artifact = _make_fake_artifact(
            tmp_path,
            extra_json_files={"modules.json": config_content},
        )
        result = _run_verify(artifact)
        assert result.returncode == 1
        assert "Forbidden embedding reference" in result.stderr

    def test_nomic_bert_hyphen_in_config(self, tmp_path: Path) -> None:
        config_content = json.dumps({"model_type": "nomic-bert"})
        artifact = _make_fake_artifact(
            tmp_path,
            extra_json_files={"config.json": config_content},
        )
        result = _run_verify(artifact)
        assert result.returncode == 1
        assert "Forbidden embedding reference" in result.stderr

    def test_nomic_bert_underscore_in_config(self, tmp_path: Path) -> None:
        config_content = json.dumps({"model_type": "nomic_bert"})
        artifact = _make_fake_artifact(
            tmp_path,
            extra_json_files={"config.json": config_content},
        )
        result = _run_verify(artifact)
        assert result.returncode == 1
        assert "Forbidden embedding reference" in result.stderr

    def test_nomic_bert_camelcase_in_config(self, tmp_path: Path) -> None:
        config_content = json.dumps({"auto_map": {"AutoModel": "NomicBertModel"}})
        artifact = _make_fake_artifact(
            tmp_path,
            extra_json_files={"config.json": config_content},
        )
        result = _run_verify(artifact)
        assert result.returncode == 1
        assert "Forbidden embedding reference" in result.stderr

    def test_wrong_model_id_in_manifest(self, tmp_path: Path) -> None:
        artifact = _make_fake_artifact(
            tmp_path,
            model_id="nomic-embed-text:v1.5",
        )
        result = _run_verify(artifact)
        assert result.returncode == 1
        assert "model_id" in result.stderr


class TestScriptStaticChecks:
    """Static checks on the verify script source."""

    def test_no_broad_nomic_grep(self) -> None:
        content = VERIFY_SCRIPT.read_text()
        assert 'grep -R "nomic"' not in content, (
            "Script must not use broad grep -R 'nomic'"
        )
        assert "grep -qi nomic" not in content, (
            "Script must not use grep -qi nomic"
        )

    def test_has_explicit_nomic_embed_pattern(self) -> None:
        content = VERIFY_SCRIPT.read_text()
        assert "nomic-embed" in content, (
            "Script must contain at least one explicit nomic-embed pattern"
        )

    def test_has_nomic_bert_patterns(self) -> None:
        content = VERIFY_SCRIPT.read_text()
        assert "nomic-bert" in content, "Script must block nomic-bert"
        assert "nomic_bert" in content, "Script must block nomic_bert"
        assert "NomicBert" in content, "Script must block NomicBert"

    def test_no_model_download(self) -> None:
        content = VERIFY_SCRIPT.read_text()
        assert "snapshot_download" not in content
        assert "hf_hub_download" not in content
