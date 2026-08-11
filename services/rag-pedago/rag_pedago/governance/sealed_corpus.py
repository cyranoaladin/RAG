"""Générateur canonique du manifeste scellé et de l'archive de transport.

**Un seul manifeste fait autorité.** Le dépôt en portait deux : le gate
H2 lit du GNU ``sha256sum`` (``<hex>␠␠<chemin>``), tandis que le compiler
de catalogue lit un TSV d'inventaire et scelle *ce TSV* dans
``catalog.manifest_sha256``. Deux formats, deux digests, aucun lien : une
divergence entre eux passait inaperçue. Ici, le GNU est le seul format
scellé ; le TSV n'est plus qu'un inventaire d'import, explicitement non
autoritaire.

**Aucun hash auto-référentiel.** Le manifeste ne se contient jamais — un
fichier ne peut pas contenir son propre digest. La liaison passe par le
catalogue, en quatre passes :

1. énumérer et hacher les objets du corpus, self-object exclu ;
2. écrire ``SHA256SUMS.txt`` sous forme canonique ;
3. ``manifest_sha256 = sha256(octets du fichier)`` ;
4. le catalogue porte une entrée ``00_ADMIN/SHA256SUMS.txt`` dont le
   ``content_sha256`` est ce digest, et ``catalog.manifest_sha256`` la
   même valeur.

Le gate prouve ensuite présence *et* unicité du self-object, prouve son
digest, puis l'exclut de la comparaison manifeste ↔ catalogue.

**Déterminisme.** Deux exécutions sur les mêmes octets doivent produire le
même fichier et le même digest, quel que soit l'ordre du système de
fichiers, l'horloge, l'utilisateur ou la machine. Tout ce qui varie d'un
runner à l'autre est donc normalisé ou exclu.
"""
from __future__ import annotations

import hashlib
import io
import tarfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

#: Nom du self-object, tel que le gate l'attend dans le catalogue.
MANIFEST_SELF_PATH = "00_ADMIN/SHA256SUMS.txt"

#: Bornes de sécurité. Explicites et testées aux limites : une archive
#: hostile doit se heurter à un refus nommé, pas à un OOM.
MAX_FILES = 50_000
MAX_TOTAL_BYTES = 8 * 1024**3          # 8 GiB décompressés
MAX_SINGLE_FILE_BYTES = 512 * 1024**2  # 512 MiB par objet
MAX_COMPRESSION_RATIO = 200            # décompressé / compressé
MAX_PATH_BYTES = 1024

#: Taille de lecture pour le hachage — bornée pour ne jamais charger un
#: fichier entier en mémoire.
_CHUNK = 1024 * 1024


class SealedCorpusError(ValueError):
    """Le corpus ne peut pas être scellé tel quel — fail-closed.

    Aucune entrée douteuse n'est « ignorée » : un objet qu'on ne sait pas
    hacher de façon reproductible est un objet dont l'identité ne peut pas
    être approuvée."""


@dataclass(frozen=True)
class SealedManifest:
    """Le manifeste et son identité, produits ensemble."""

    content: bytes
    manifest_sha256: str
    entries: tuple[tuple[str, str], ...]  # (sha256, chemin POSIX relatif)

    @property
    def object_count(self) -> int:
        return len(self.entries)


def normalise_relative_path(root: Path, path: Path) -> str:
    """Chemin POSIX relatif, normalisé NFC, ou refus explicite.

    La normalisation Unicode n'est pas cosmétique : deux écritures NFC/NFD
    du même nom produisent des octets différents, donc deux lignes de
    manifeste pour un seul fichier. Refuser la divergence plutôt que la
    normaliser silencieusement serait pire — le corpus deviendrait
    inutilisable — mais normaliser *sans le dire* laisserait deux chemins
    distincts se confondre. On normalise, puis on refuse les collisions
    résultantes en amont (cf. ``generate_sealed_manifest``).
    """
    relative = path.relative_to(root)
    if any(part == ".." for part in relative.parts):
        raise SealedCorpusError(f"path {relative.as_posix()!r} escapes the corpus root")
    posix = unicodedata.normalize("NFC", relative.as_posix())
    if posix.startswith("/"):
        raise SealedCorpusError(f"path {posix!r} must be relative")
    if len(posix.encode("utf-8")) > MAX_PATH_BYTES:
        raise SealedCorpusError(
            f"path exceeds the {MAX_PATH_BYTES}-byte governed bound"
        )
    return posix


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            size += len(chunk)
            if size > MAX_SINGLE_FILE_BYTES:
                raise SealedCorpusError(
                    f"{path.name} exceeds the {MAX_SINGLE_FILE_BYTES}-byte bound"
                )
            digest.update(chunk)
    return digest.hexdigest(), size


def _refuse_unsupported(path: Path, posix: str) -> None:
    """Refuse tout ce dont l'identité n'est pas celle d'octets réguliers.

    Un lien symbolique désigne un contenu qui vit ailleurs ; un device ou
    un FIFO n'a pas de contenu stable. Les sceller reviendrait à sceller
    une promesse plutôt qu'un fait."""
    if path.is_symlink():
        raise SealedCorpusError(
            f"{posix!r} is a symlink — a sealed corpus contains bytes, not "
            "references to bytes that live elsewhere"
        )
    if not path.is_file():
        raise SealedCorpusError(
            f"{posix!r} is not a regular file (device, FIFO, socket or directory "
            "entry with no stable content)"
        )
    if path.stat().st_nlink > 1:
        raise SealedCorpusError(
            f"{posix!r} is a hard link — the same bytes reachable under two "
            "paths make the manifest ambiguous about what was sealed"
        )


def generate_sealed_manifest(root: Path) -> SealedManifest:
    """Produit ``SHA256SUMS.txt`` canonique pour le corpus enraciné en ``root``.

    Format, imposé par ``h2b_coverage_report._parse_manifest`` :
    ``<64 hex minuscules><deux espaces><chemin POSIX><LF>``.
    """
    if not root.is_dir():
        raise SealedCorpusError(f"corpus root {root} is not a directory")

    collected: dict[str, tuple[str, Path]] = {}
    total_bytes = 0

    # ``sorted`` sur les chemins matérialisés : l'ordre de ``rglob`` suit le
    # système de fichiers et varie d'une machine à l'autre.
    for candidate in sorted(root.rglob("*"), key=lambda p: p.as_posix()):
        if candidate.is_dir() and not candidate.is_symlink():
            continue
        posix = normalise_relative_path(root, candidate)
        if posix == MANIFEST_SELF_PATH:
            # Le manifeste ne se contient jamais.
            continue
        _refuse_unsupported(candidate, posix)

        if posix in collected:
            raise SealedCorpusError(
                f"path {posix!r} appears twice after Unicode NFC normalisation — "
                "two different byte spellings of one name would produce two "
                "manifest lines for a single object"
            )
        digest, size = _sha256_file(candidate)
        total_bytes += size
        if len(collected) + 1 > MAX_FILES:
            raise SealedCorpusError(f"corpus exceeds {MAX_FILES} objects")
        if total_bytes > MAX_TOTAL_BYTES:
            raise SealedCorpusError(
                f"corpus exceeds the {MAX_TOTAL_BYTES}-byte governed bound"
            )
        collected[posix] = (digest, candidate)

    if not collected:
        raise SealedCorpusError(
            "corpus is empty — an empty manifest would seal nothing while "
            "looking like a valid campaign"
        )

    entries = tuple((collected[p][0], p) for p in sorted(collected))
    content = "".join(f"{digest}  {path}\n" for digest, path in entries).encode("utf-8")
    return SealedManifest(
        content=content,
        manifest_sha256=hashlib.sha256(content).hexdigest(),
        entries=entries,
    )


def compute_tree_digest(manifest: SealedManifest) -> str:
    """Digest de l'arbre extrait, indépendant du transport.

    Distinct du digest de l'archive : celui-ci prouve que le *contenu
    matérialisé* est celui attendu, quelle que soit la façon dont il a été
    empaqueté. Un packer défaillant ou une extraction créative sont donc
    détectés, alors qu'une simple comparaison d'archives ne les verrait
    pas."""
    digest = hashlib.sha256()
    digest.update(b"NEXUS-CORPUS-TREE-V1\n")
    for entry_digest, path in manifest.entries:
        line = f"{entry_digest}  {path}\n".encode()
        digest.update(len(line).to_bytes(4, "big"))
        digest.update(line)
    return digest.hexdigest()


def build_canonical_archive(root: Path, manifest: SealedManifest) -> bytes:
    """Archive tar déterministe des objets scellés (non compressée).

    Toute métadonnée qui varie d'une machine à l'autre est écrasée :
    ``mtime``, ``uid``, ``gid``, noms d'utilisateur et de groupe, et les
    modes sont normalisés. Sans cela, deux exécutions sur les mêmes octets
    produiraient deux archives différentes, et le digest cesserait d'être
    une identité de contenu pour devenir une identité de build.

    La compression zstd est appliquée séparément par l'outil de
    publication, avec des paramètres explicites : mélanger les deux ici
    rendrait le déterminisme dépendant de la version de la bibliothèque de
    compression installée.
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for _digest, posix in manifest.entries:
            source = root / posix
            info = tarfile.TarInfo(name=posix)
            info.size = source.stat().st_size
            info.mtime = 0
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mode = 0o644
            info.type = tarfile.REGTYPE
            with source.open("rb") as handle:
                archive.addfile(info, handle)
    return buffer.getvalue()


def catalog_self_object(manifest: SealedManifest) -> dict[str, str]:
    """Entrée de catalogue du self-object — la seule liaison légitime.

    C'est ici, et nulle part ailleurs, que le digest du manifeste entre
    dans le catalogue."""
    return {
        "path": MANIFEST_SELF_PATH,
        "content_sha256": manifest.manifest_sha256,
    }


__all__ = [
    "MANIFEST_SELF_PATH",
    "MAX_COMPRESSION_RATIO",
    "MAX_FILES",
    "MAX_PATH_BYTES",
    "MAX_SINGLE_FILE_BYTES",
    "MAX_TOTAL_BYTES",
    "SealedCorpusError",
    "SealedManifest",
    "build_canonical_archive",
    "catalog_self_object",
    "compute_tree_digest",
    "generate_sealed_manifest",
    "normalise_relative_path",
]
