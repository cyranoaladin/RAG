"""Stockage fichier local pour le worker CLI (LOT44e).

Implémentation réelle et minimale des protocoles ``ArtifactStore``/
``ArtifactReader`` (LOT44d, ``ingestion_agents.dependencies``) — LOT44d
n'en fournissait délibérément aucune (aucun client de stockage réutilisable
dans ce dépôt). Cette implémentation est locale au disque, réservée au
worker CLI de développement/test : elle n'est ni un profil, ni un manifest,
ni un fingerprint de production — un simple adaptateur de fichiers.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID


def make_filesystem_artifact_store(base_dir: Path):
    """Retourne une fonction ``ArtifactStore`` qui écrit sous ``base_dir``."""
    base_dir.mkdir(parents=True, exist_ok=True)

    def store_artifact(*, artifact_id: UUID, content: bytes) -> str:
        path = base_dir / f"{artifact_id}.bin"
        path.write_bytes(content)
        return str(path)

    return store_artifact


def make_filesystem_artifact_reader(base_dir: Path):
    """Retourne une fonction ``ArtifactReader`` symétrique de
    ``make_filesystem_artifact_store`` — relit par référence de chemin,
    jamais par reconstruction implicite d'un nom de fichier différent."""

    def read_artifact(*, extracted_text_ref: str) -> bytes:
        return Path(extracted_text_ref).read_bytes()

    return read_artifact


__all__ = ["make_filesystem_artifact_reader", "make_filesystem_artifact_store"]
