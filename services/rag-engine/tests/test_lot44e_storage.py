"""LOT44e : stockage fichier local du worker (``ingestion_worker.storage``).

Périmètre strict : ``make_filesystem_artifact_store``/``make_filesystem_
artifact_reader`` — aucun PostgreSQL, filesystem réel via ``tmp_path``.
Ajouté en remédiation de la revue PR#90 (Cubic P2, protection contre la
lecture en dehors du magasin d'artefacts configuré).
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from ingestor.ingestion_worker.storage import (
    ArtifactPathEscapeError,
    make_filesystem_artifact_reader,
    make_filesystem_artifact_store,
)


class TestFilesystemArtifactStoreAndReader:
    def test_round_trip_store_then_read(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "artifacts"
        store = make_filesystem_artifact_store(base_dir)
        reader = make_filesystem_artifact_reader(base_dir)

        ref = store(artifact_id=uuid4(), content=b"contenu reel")
        assert reader(extracted_text_ref=ref) == b"contenu reel"


class TestFilesystemArtifactReaderPathEscape:
    def test_rejects_relative_traversal_outside_base_dir(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "artifacts"
        base_dir.mkdir()
        outside_secret = tmp_path / "secret.txt"
        outside_secret.write_bytes(b"not an artifact")

        reader = make_filesystem_artifact_reader(base_dir)
        traversal_ref = str(base_dir / ".." / "secret.txt")

        with pytest.raises(ArtifactPathEscapeError):
            reader(extracted_text_ref=traversal_ref)

    def test_rejects_absolute_path_outside_base_dir(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "artifacts"
        base_dir.mkdir()
        outside_secret = tmp_path / "outside" / "secret.txt"
        outside_secret.parent.mkdir()
        outside_secret.write_bytes(b"not an artifact")

        reader = make_filesystem_artifact_reader(base_dir)

        with pytest.raises(ArtifactPathEscapeError):
            reader(extracted_text_ref=str(outside_secret))

    def test_rejects_symlink_escaping_base_dir(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "artifacts"
        base_dir.mkdir()
        outside_secret = tmp_path / "outside_secret.txt"
        outside_secret.write_bytes(b"not an artifact")
        symlink_path = base_dir / "escape.bin"
        symlink_path.symlink_to(outside_secret)

        reader = make_filesystem_artifact_reader(base_dir)

        with pytest.raises(ArtifactPathEscapeError):
            reader(extracted_text_ref=str(symlink_path))

    def test_allows_legitimate_path_within_base_dir(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "artifacts"
        base_dir.mkdir()
        legit_path = base_dir / "artifact.bin"
        legit_path.write_bytes(b"real content")

        reader = make_filesystem_artifact_reader(base_dir)
        assert reader(extracted_text_ref=str(legit_path)) == b"real content"

    def test_allows_nested_subdirectory_within_base_dir(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "artifacts"
        nested = base_dir / "sub" / "dir"
        nested.mkdir(parents=True)
        legit_path = nested / "artifact.bin"
        legit_path.write_bytes(b"nested content")

        reader = make_filesystem_artifact_reader(base_dir)
        assert reader(extracted_text_ref=str(legit_path)) == b"nested content"
