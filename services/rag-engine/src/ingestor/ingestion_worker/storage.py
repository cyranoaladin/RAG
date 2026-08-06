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


class ArtifactPathEscapeError(ValueError):
    """``extracted_text_ref`` résout en dehors de ``base_dir`` — rejet
    explicite, jamais une lecture en dehors du magasin d'artefacts
    configuré. Remédiation revue PR#90 : une reprise après crash relit
    ``extracted_text_ref`` depuis un ``ArtifactRecord`` persisté ; si cette
    référence est malformée ou altérée (chemin absolu externe, ``..``,
    symlink pointant hors de ``base_dir``), aucune vérification n'empêchait
    auparavant la lecture d'un fichier arbitraire du système de fichiers du
    worker."""


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
    jamais par reconstruction implicite d'un nom de fichier différent.

    Remédiation revue PR#90 : le chemin résolu (symlinks compris, via
    ``Path.resolve()``) doit rester sous ``base_dir`` résolu de la même
    façon — ``..``, chemins absolus externes et symlinks qui s'échappent
    sont rejetés avant toute lecture, jamais silencieusement suivis."""
    resolved_base_dir = base_dir.resolve()

    def read_artifact(*, extracted_text_ref: str) -> bytes:
        resolved_path = Path(extracted_text_ref).resolve()
        if not resolved_path.is_relative_to(resolved_base_dir):
            raise ArtifactPathEscapeError(
                f"extracted_text_ref {extracted_text_ref!r} resolves to "
                f"{resolved_path}, which is outside the configured artifact "
                f"store {resolved_base_dir} — refusing to read"
            )
        return resolved_path.read_bytes()

    return read_artifact


__all__ = [
    "ArtifactPathEscapeError",
    "make_filesystem_artifact_reader",
    "make_filesystem_artifact_store",
]
