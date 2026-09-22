"""Stockage fichier local pour le worker CLI (LOT44e).

Implémentation réelle et minimale des protocoles ``ArtifactStore``/
``ArtifactReader`` (LOT44d, ``ingestion_agents.dependencies``) — LOT44d
n'en fournissait délibérément aucune (aucun client de stockage réutilisable
dans ce dépôt). Cette implémentation est locale au disque, réservée au
worker CLI de développement/test : elle n'est ni un profil, ni un manifest,
ni un fingerprint de production — un simple adaptateur de fichiers.
"""
from __future__ import annotations

import hashlib
import os
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


class SealedArtifactDigestError(ValueError):
    """Les octets lus sous le nom d'un artefact scellé ne sont pas les siens.

    Le magasin transféré nomme chaque objet par son empreinte. Cette
    convention n'est une preuve que si elle est RE-MESURÉE : sinon un
    fichier remplacé sous le bon nom traverserait toute la chaîne, et
    l'attestation qui nomme ce digest couvrirait d'autres octets qu'elle.
    """


def make_filesystem_artifact_store(base_dir: Path):
    """Retourne une fonction ``ArtifactStore`` qui écrit sous ``base_dir``."""
    base_dir.mkdir(parents=True, exist_ok=True)

    def store_artifact(*, artifact_id: UUID, content: bytes) -> str:
        path = base_dir / f"{artifact_id}.bin"
        path.write_bytes(content)
        return str(path)

    return store_artifact


def _open_beneath_no_symlinks(base_dir_fd: int, relative_parts: tuple[str, ...]) -> int:
    """Ouvre ``relative_parts`` composant par composant, chacun relatif au
    descripteur de fichier du précédent (jamais par résolution de chemin
    textuel), en refusant explicitement (``O_NOFOLLOW``) tout composant qui
    serait un lien symbolique — y compris les composants intermédiaires,
    pas seulement le dernier.

    Remédiation revue PR#90 (Cubic P2, revue incrémentale) : la version
    précédente faisait ``Path(...).resolve()`` (vérification) puis
    ``resolved_path.read_bytes()`` (lecture) séparément — deux appels
    système distincts, avec une fenêtre de temps entre les deux pendant
    laquelle un composant du chemin peut être remplacé par un lien
    symbolique pointant hors de ``base_dir`` (race TOCTOU explicitement
    signalée : un simple ``resolve()`` + ``read_bytes()`` est **insuffisant**
    par construction, quel que soit le soin apporté à la vérification qui
    précède la lecture). Ici, l'ouverture et la vérification ne font qu'un
    seul appel système par composant (``os.open(..., dir_fd=...,
    O_NOFOLLOW)``) : dès qu'un descripteur de fichier est obtenu, il
    référence un inode précis et immuable — aucune substitution ultérieure
    du chemin ne peut plus rien changer à ce qui sera effectivement lu."""
    current_fd = os.dup(base_dir_fd)
    try:
        last_index = len(relative_parts) - 1
        for index, part in enumerate(relative_parts):
            flags = os.O_RDONLY | os.O_NOFOLLOW
            if index != last_index:
                flags |= os.O_DIRECTORY
            new_fd = os.open(part, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = new_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def make_filesystem_artifact_reader(base_dir: Path):
    """Retourne une fonction ``ArtifactReader`` symétrique de
    ``make_filesystem_artifact_store`` — relit par référence de chemin,
    jamais par reconstruction implicite d'un nom de fichier différent.

    Remédiation revue PR#90 : le chemin résolu (symlinks compris, via
    ``Path.resolve()``) doit rester sous ``base_dir`` résolu de la même
    façon — ``..``, chemins absolus externes et symlinks qui s'échappent
    sont rejetés avant toute lecture, jamais silencieusement suivis.

    Remédiation revue PR#90 (Cubic P2, revue incrémentale) : la
    vérification de confinement ci-dessous reste une étape *lexicale*
    rapide (rejette d'emblée un ``..``/chemin absolu externe évident, sans
    toucher le système de fichiers) — la garantie de sécurité réelle contre
    une substitution de composant par un lien symbolique vient de
    ``_open_beneath_no_symlinks`` (ouverture atomique composant par
    composant, ``O_NOFOLLOW``), jamais de cette seule vérification
    lexicale."""
    resolved_base_dir = base_dir.resolve()
    base_dir_fd = os.open(str(resolved_base_dir), os.O_RDONLY | os.O_DIRECTORY)

    def read_artifact(*, extracted_text_ref: str) -> bytes:
        candidate_path = Path(extracted_text_ref)
        try:
            relative = candidate_path.relative_to(resolved_base_dir)
        except ValueError:
            # Chemin non préfixé lexicalement par base_dir (relatif,
            # absolu ailleurs, ou contenant un composant qui en sortirait
            # une fois normalisé) — rejeté avant tout accès disque.
            raise ArtifactPathEscapeError(
                f"extracted_text_ref {extracted_text_ref!r} does not resolve "
                f"under the configured artifact store {resolved_base_dir} — "
                "refusing to read"
            ) from None

        relative_parts = relative.parts
        if not relative_parts or ".." in relative_parts:
            raise ArtifactPathEscapeError(
                f"extracted_text_ref {extracted_text_ref!r} is not a valid "
                f"path strictly beneath {resolved_base_dir} — refusing to read"
            )

        try:
            fd = _open_beneath_no_symlinks(base_dir_fd, relative_parts)
        except OSError as exc:
            raise ArtifactPathEscapeError(
                f"extracted_text_ref {extracted_text_ref!r} could not be opened "
                f"safely beneath {resolved_base_dir} (symlink component or "
                f"missing path): {exc}"
            ) from exc

        try:
            with os.fdopen(fd, "rb") as handle:
                return handle.read()
        except BaseException:
            # os.fdopen n'a pas encore pris possession de fd si l'appel
            # lui-même échoue (rarissime) — évite une fuite de descripteur.
            try:
                os.close(fd)
            except OSError:
                pass
            raise

    return read_artifact


def make_sealed_release_artifact_reader(base_dir: Path):
    """Relit un artefact de release SCELLÉE par son empreinte.

    Une release scellée ne porte aucune référence de fichier : elle n'a
    jamais été téléchargée, et ``SealedReleaseArtifactRecord`` n'a donc ni
    ``extracted_text_ref`` ni ``mime_detected``. Le magasin transféré nomme
    chaque objet par son digest (``<sha256>.pdf``) — c'est ce que
    l'ingestion scellée exige déjà à l'entrée, et c'est la seule référence
    qui existe.

    Les octets sont relus sous la même protection que le chemin unitaire
    (ouverture composant par composant, ``O_NOFOLLOW``, confinement sous
    ``base_dir``), puis leur empreinte est RE-MESURÉE et confrontée. La
    publication ne lit donc jamais des octets dont elle n'a pas vérifié
    qu'ils sont ceux que l'attestation nomme.
    """
    resolved_base_dir = base_dir.resolve()
    read_artifact = make_filesystem_artifact_reader(base_dir)

    def read_sealed_artifact(*, content_sha256: str) -> bytes:
        content: bytes = read_artifact(
            extracted_text_ref=str(resolved_base_dir / f"{content_sha256}.pdf")
        )
        measured = hashlib.sha256(content).hexdigest()
        if measured != content_sha256:
            raise SealedArtifactDigestError(
                f"the artifact store holds bytes hashing to {measured} under the "
                f"name {content_sha256}.pdf — refusing to publish content the "
                "attestation does not name"
            )
        return content

    return read_sealed_artifact


__all__ = [
    "ArtifactPathEscapeError",
    "SealedArtifactDigestError",
    "make_filesystem_artifact_reader",
    "make_sealed_release_artifact_reader",
    "make_filesystem_artifact_store",
]
