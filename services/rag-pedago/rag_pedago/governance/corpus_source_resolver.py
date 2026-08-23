"""Résolveur de source de corpus — GHCR par digest, fail-closed.

**Où vit l'autorité.** Pas ici. Le client OCI n'est qu'une couche de
transport : il va chercher des octets là où le descripteur de campagne dit
qu'ils sont. C'est ``campaign.json``, versionné et approuvé exact-head,
qui porte l'identité. Ce module dérive donc lui-même la référence depuis
le descripteur ; aucun argument ne peut la remplacer, et la fonction ne
prend pas de paramètre « référence ».

**Les trois vérifications sont la preuve d'indépendance.** L'inégalité des
trois digests dans le descripteur n'est qu'un garde-fou précoce. Ce qui
rend les contrôles non redondants, ce sont trois recalculs sur trois
objets distincts :

``source_oci_digest``
    ce que le registre a effectivement renvoyé — prouve qu'on a tiré le
    bon objet ;
``source_archive_sha256``
    le SHA-256 du tar canonique **décompressé** — prouve que son contenu
    n'a pas changé en transit, indépendamment du compresseur ;
``source_tree_digest``
    le digest de l'arbre **après extraction** — prouve que ce qui a été
    matérialisé est bien ce qui a été scellé. Une extraction créative ou
    un packer défaillant ne peuvent pas passer ici, alors qu'ils
    passeraient une simple comparaison d'archives.

Les trois sont obligatoires et ordonnées. Une seule qui manque, et la
chaîne cesse de prouver ce qu'elle prétend.

**Aucun repli, jamais.** Objet absent, accès refusé, digest divergent :
chaque cas est un refus nommé. Chercher « une autre source » ou « le tag
correspondant » transformerait un problème de disponibilité en problème
d'authenticité — c'est exactement la confusion que la gouvernance par
digest existe pour supprimer.
"""
from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import tarfile
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from rag_pedago.governance.corpus_campaign import CorpusCampaignV1, CorpusCampaignV2
from rag_pedago.governance.sealed_corpus import (
    MANIFEST_SELF_PATH,
    MAX_COMPRESSION_RATIO,
    MAX_FILES,
    MAX_PATH_BYTES,
    MAX_SINGLE_FILE_BYTES,
    MAX_TOTAL_BYTES,
    SealedManifest,
    compute_tree_digest,
    generate_sealed_manifest,
)

#: Nom canonique de l'archive à l'intérieur de l'objet OCI. Une seule
#: entrée est attendue : plusieurs archives rendraient ambigu *ce* qui a
#: été scellé.
CANONICAL_ARCHIVE_MEMBER = "corpus.tar"


class CorpusSourceError(RuntimeError):
    """La source ne prouve pas l'identité déclarée — refus explicite.

    Jamais un repli : une source qui ne se vérifie pas n'est pas une
    source dégradée, c'est une source inconnue."""


class CorpusSourceUnavailable(CorpusSourceError):
    """Le registre n'a pas rendu l'objet.

    Distinguée de l'échec d'identité **délibérément** : la disponibilité
    et l'authenticité sont deux propriétés différentes, et confondre les
    deux invite à « réessayer ailleurs ». Ici, l'indisponibilité est un
    refus comme un autre — elle n'ouvre aucune alternative."""


@dataclass(frozen=True)
class ResolvedCorpus:
    """Arbre vérifié, prêt à être scellé."""

    root: Path
    manifest: SealedManifest
    tree_digest: str
    archive_sha256: str
    oci_digest: str


#: Signature d'un client OCI : reçoit la référence *dérivée du
#: descripteur*, rend (octets du blob, digest effectivement renvoyé par le
#: registre). Injectable pour que les tests n'aient jamais besoin de GHCR.
OciPull = Callable[[str], tuple[bytes, str]]


def _run(argv: Sequence[str], *, stdin: bytes | None = None) -> bytes:
    try:
        completed = subprocess.run(
            list(argv), input=stdin, capture_output=True, check=False, timeout=900
        )
    except FileNotFoundError as exc:
        raise CorpusSourceUnavailable(f"{argv[0]} is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise CorpusSourceUnavailable(f"{argv[0]} timed out") from exc
    if completed.returncode != 0:
        # Le stderr du registre peut contenir un jeton ; on ne le relaie pas.
        raise CorpusSourceUnavailable(
            f"{argv[0]} failed with exit code {completed.returncode}"
        )
    return completed.stdout


def decompress_transport_blob(blob: bytes) -> bytes:
    """Rend le tar canonique depuis son encodage de transport.

    Accepte un tar déjà nu — la compression est un détail de transport, et
    l'identité porte sur le tar décompressé (cf. ``sealed_corpus``)."""
    if blob[:4] != b"\x28\xb5\x2f\xfd":  # magic zstd
        return blob
    if shutil.which("zstd") is None:
        raise CorpusSourceUnavailable(
            "the blob is zstd-compressed but 'zstd' is not installed"
        )
    raw = _run(["zstd", "-d", "-c", "--stdout"], stdin=blob)
    if len(raw) > len(blob) * MAX_COMPRESSION_RATIO:
        raise CorpusSourceError(
            f"decompressed size exceeds {MAX_COMPRESSION_RATIO}x the transported "
            "blob — refusing a compression bomb"
        )
    if len(raw) > MAX_TOTAL_BYTES:
        raise CorpusSourceError(
            f"decompressed size exceeds the {MAX_TOTAL_BYTES}-byte bound"
        )
    return raw


def _safe_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    """Filtre fail-closed des entrées d'archive.

    Chaque refus nomme sa raison : une archive hostile doit se heurter à
    un message, pas à une extraction partielle."""
    members: list[tarfile.TarInfo] = []
    seen: set[str] = set()
    total = 0
    for member in archive.getmembers():
        name = member.name
        if name.startswith("/"):
            raise CorpusSourceError(f"archive entry {name!r} is an absolute path")
        normalised = unicodedata.normalize("NFC", name)
        if ".." in Path(normalised).parts:
            raise CorpusSourceError(
                f"archive entry {name!r} escapes the extraction root"
            )
        if len(normalised.encode("utf-8")) > MAX_PATH_BYTES:
            raise CorpusSourceError(f"archive entry path exceeds {MAX_PATH_BYTES} bytes")
        if member.issym() or member.islnk():
            raise CorpusSourceError(
                f"archive entry {name!r} is a link — a sealed corpus carries bytes, "
                "not references to bytes"
            )
        if member.ischr() or member.isblk() or member.isfifo():
            raise CorpusSourceError(
                f"archive entry {name!r} is a device or FIFO, which has no stable "
                "content to seal"
            )
        if member.isdir():
            continue
        if not member.isfile():
            raise CorpusSourceError(f"archive entry {name!r} is not a regular file")
        if normalised in seen:
            raise CorpusSourceError(
                f"archive declares {name!r} twice — the later entry would silently "
                "overwrite the earlier one, so what was sealed becomes ambiguous"
            )
        if member.size > MAX_SINGLE_FILE_BYTES:
            raise CorpusSourceError(
                f"archive entry {name!r} exceeds {MAX_SINGLE_FILE_BYTES} bytes"
            )
        total += member.size
        if total > MAX_TOTAL_BYTES:
            raise CorpusSourceError(
                f"archive exceeds the {MAX_TOTAL_BYTES}-byte bound"
            )
        seen.add(normalised)
        if len(seen) > MAX_FILES:
            raise CorpusSourceError(f"archive exceeds {MAX_FILES} entries")
        member.name = normalised
        members.append(member)
    if not members:
        raise CorpusSourceError("archive contains no regular file")
    return members


def extract_canonical_archive(tar_bytes: bytes, destination: Path) -> None:
    """Extrait le tar canonique dans un répertoire privé, après filtrage.

    Le filtrage précède l'écriture : rien n'est matérialisé avant que
    toutes les entrées aient été jugées acceptables."""
    destination.mkdir(parents=True, exist_ok=True)
    destination.chmod(0o700)
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as archive:
        members = _safe_members(archive)
        for member in members:
            member.mode = 0o644
        archive.extractall(destination, members=members, filter="data")


def resolve_corpus_source(
    campaign: CorpusCampaignV1 | CorpusCampaignV2,
    *,
    destination: Path,
    pull: OciPull,
) -> ResolvedCorpus:
    """Matérialise et vérifie le corpus décrit par ``campaign``.

    ``pull`` reçoit la référence **dérivée du descripteur** ; il n'existe
    aucun paramètre permettant d'en désigner une autre. Les huit étapes
    ci-dessous portent chacune leur propre refus."""
    # 1/8 — la référence vient du descripteur, jamais d'un appelant.
    reference = campaign.oci_reference()

    blob, returned_digest = pull(reference)

    # 2/8 — le registre a-t-il rendu l'objet demandé ?
    if returned_digest != campaign.source_oci_digest:
        raise CorpusSourceError(
            f"registry returned digest {returned_digest!r} for a reference pinned "
            f"to {campaign.source_oci_digest!r} — refusing rather than trusting "
            "what was actually served"
        )

    # 3/8 — transport : la compression n'appartient pas à l'identité.
    tar_bytes = decompress_transport_blob(blob)

    # 4/8 — identité des octets scellés.
    archive_sha256 = hashlib.sha256(tar_bytes).hexdigest()
    if archive_sha256 != campaign.source_archive_sha256:
        raise CorpusSourceError(
            "canonical archive digest does not match the approved campaign — the "
            "bytes served are not the bytes a human reviewed"
        )

    # 5/8 et 6/8 — filtrage puis matérialisation dans un répertoire privé.
    extract_canonical_archive(tar_bytes, destination)

    root = destination / campaign.source_root
    if not root.is_dir():
        raise CorpusSourceError(
            f"source_root {campaign.source_root!r} is absent from the extracted "
            "archive"
        )

    # 7/8 — l'arbre matérialisé est-il celui qui a été scellé ?
    manifest = generate_sealed_manifest(root)
    tree_digest = compute_tree_digest(manifest)
    if tree_digest != campaign.source_tree_digest:
        raise CorpusSourceError(
            "extracted tree digest does not match the approved campaign — the "
            "archive unpacked into something other than what was sealed"
        )

    # 8/8 — le manifeste régénéré est-il celui que la PR a approuvé ?
    if manifest.manifest_sha256 != campaign.expected_manifest_sha256:
        raise CorpusSourceError(
            "regenerated manifest digest does not match expected_manifest_sha256 — "
            "the corpus identity approved in the pull request is not the one "
            "produced here"
        )

    return ResolvedCorpus(
        root=root,
        manifest=manifest,
        tree_digest=tree_digest,
        archive_sha256=archive_sha256,
        oci_digest=returned_digest,
    )


__all__ = [
    "CANONICAL_ARCHIVE_MEMBER",
    "MANIFEST_SELF_PATH",
    "CorpusSourceError",
    "CorpusSourceUnavailable",
    "OciPull",
    "ResolvedCorpus",
    "decompress_transport_blob",
    "extract_canonical_archive",
    "resolve_corpus_source",
]
