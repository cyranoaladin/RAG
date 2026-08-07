"""LOT44e : stockage fichier local du worker (``ingestion_worker.storage``).

Périmètre strict : ``make_filesystem_artifact_store``/``make_filesystem_
artifact_reader`` — aucun PostgreSQL, filesystem réel via ``tmp_path``.
Ajouté en remédiation de la revue PR#90 (Cubic P2, protection contre la
lecture en dehors du magasin d'artefacts configuré).
"""
from __future__ import annotations

import os
import threading
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

    def test_symlink_swap_race_between_validation_and_read_never_leaks_secret(
        self, tmp_path: Path
    ) -> None:
        """Revue incrémentale PR#90 (Cubic P2) : preuve directe de la
        fenêtre de course TOCTOU explicitement signalée — un simple
        ``Path.resolve()`` (vérification) suivi de ``read_bytes()``
        (lecture) séparés est **insuffisant**, quelle que soit la rigueur
        de la vérification qui précède : entre les deux appels système, un
        attaquant (ou une corruption concurrente) peut remplacer le chemin
        cible par un lien symbolique pointant hors de ``base_dir``.

        Ce test fait réellement courir un thread qui bascule le chemin
        cible, en boucle, entre un fichier légitime et un lien symbolique
        vers un secret hors ``base_dir``, pendant qu'un second thread
        appelle ``reader`` en boucle sur ce même chemin — répété assez de
        fois pour exercer réellement la fenêtre de course. Sur
        l'implémentation ``resolve()`` + ``read_bytes()`` d'origine, ce
        test attrapait le secret dans un nombre significatif d'itérations
        (vérifié empiriquement en désactivant temporairement le correctif
        avant de valider ce test). Sur l'implémentation corrigée (ouverture
        atomique composant par composant, ``O_NOFOLLOW``), le secret ne
        doit **jamais** être renvoyé, quel que soit l'entrelacement réel
        des deux threads."""
        base_dir = tmp_path / "artifacts"
        base_dir.mkdir()
        target_path = base_dir / "artifact.bin"
        legit_path = base_dir / "legit_source.bin"
        legit_path.write_bytes(b"legitimate content")
        secret_path = tmp_path / "secret_outside.bin"
        secret_path.write_bytes(b"SECRET_MUST_NEVER_LEAK")

        reader = make_filesystem_artifact_reader(base_dir)
        stop = threading.Event()
        leaked: list[bytes] = []
        errors: list[BaseException] = []

        def _swap_loop() -> None:
            swap_target = tmp_path / "swap_tmp"
            toggle = False
            while not stop.is_set():
                if toggle:
                    if swap_target.is_symlink() or swap_target.exists():
                        swap_target.unlink()
                    swap_target.symlink_to(secret_path)
                else:
                    if swap_target.is_symlink() or swap_target.exists():
                        swap_target.unlink()
                    swap_target.write_bytes(b"legitimate content")
                os.replace(swap_target, target_path)
                toggle = not toggle

        def _read_loop() -> None:
            for _ in range(500):
                try:
                    content = reader(extracted_text_ref=str(target_path))
                except ArtifactPathEscapeError:
                    continue
                except FileNotFoundError:
                    continue
                if content == b"SECRET_MUST_NEVER_LEAK":
                    leaked.append(content)
                    stop.set()
                    return

        swap_thread = threading.Thread(target=_swap_loop)
        read_thread = threading.Thread(target=_read_loop)
        swap_thread.start()
        read_thread.start()
        read_thread.join(timeout=30)
        stop.set()
        swap_thread.join(timeout=5)

        assert not errors, f"unexpected errors: {errors}"
        assert leaked == [], (
            "the secret file outside base_dir was read despite the symlink-swap "
            "race — the TOCTOU window is not actually closed"
        )
