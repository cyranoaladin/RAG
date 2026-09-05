"""Tranche verticale : Drive → acquisition prouvée → staging gouverné.

Ce module n'ajoute aucune autorité. Il enchaîne celles qui existent, dans
l'ordre où elles font foi :

1. ``DriveSourceAdapter`` énumère et résout — c'est la *frontière source*,
   pas une vérité ;
2. ``acquire_corpus`` matérialise et **rehache intégralement** — à partir
   d'ici on parle d'octets prouvés, plus de contenu déclaré ;
3. ``require_scoped_reconciled`` recoupe la tranche avec le manifeste du
   producteur, sur le périmètre *demandé* ;
4. la classification vient du **chemin gouverné**, jamais du nom de
   fichier — un slug de scraping porte un titre et un hash, pas un niveau
   ni une matière ;
5. le découpage lit les octets écrits par l'acquisition, pas ceux
   téléchargés — ainsi rien n'entre en staging qui n'ait traversé le
   rehachage.

**Le staging n'est pas servable.** Tout ce qui sort d'ici porte
``needs_review``. Le passage en retrieval exige la chaîne
``quality → gate → review`` et une attestation humaine, qui vivent en
aval et ne sont pas contournables depuis ici.

**Compteurs d'idempotence.** ``SliceReport`` distingue ce qui a été
*créé* de ce qui existait déjà. Un second passage sur le même instantané
Drive doit rendre ``new_artifacts == 0`` et ``new_chunks == 0`` : c'est la
seule preuve qu'une réexécution ne dédouble pas le corpus.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from rag_pedago.governance.corpus_acquisition import (
    MANIFEST_SELF_PATH,
    CorpusAcquisitionError,
    acquire_corpus,
    require_scoped_reconciled,
)
from rag_pedago.governance.drive_source import (
    CONTROL_PLANE_ZONES,
    SOURCE_KIND,
    DriveObject,
    DriveSourceAdapter,
)

#: Statut de revue à la sortie du staging. Constante, et jamais un
#: paramètre : un appelant capable de choisir « reviewed » ferait sauter
#: la revue humaine sans qu'aucun contrôle ne s'en aperçoive.
STAGING_REVIEW_STATUS = "needs_review"

#: Zones gouvernées de la racine. Une zone hors de cette liste n'est pas
#: un cas à traiter au mieux : c'est un chemin qu'on ne sait pas classer.
KNOWN_ZONES = frozenset(
    {
        "00_ADMIN",
        "00_INDEX_PROVENANCE",
        "01_EDUSCOL_OFFICIEL",
        "02_NEXUS_DIAGNOSTICS",
        "03_RESSOURCES_INTERACTIVES",
        "04_COMPLEMENTS_PEDAGOGIQUES",
    }
)

KNOWN_CYCLES = frozenset({"COLLEGE", "LYCEE"})

KNOWN_NIVEAUX = frozenset(
    {
        "SIXIEME",
        "CINQUIEME",
        "QUATRIEME",
        "TROISIEME",
        "CYCLE_3",
        "CYCLE_4",
        "CYCLE_4_TRANSVERSAL",
        "SECONDE",
        "PREMIERE",
        "TERMINALE",
        "TRANSVERSAL_MULTI_NIVEAUX",
    }
)

#: Un dossier de *nature* : deux chiffres, un souligné, un libellé.
_NATURE = re.compile(r"\A(\d{2})_([A-Z0-9_]+)\Z")

#: Un millésime : quatre chiffres, rien d'autre.
_MILLESIME = re.compile(r"\A\d{4}\Z")


class DriveClassificationError(RuntimeError):
    """Le chemin gouverné ne désigne pas un placement — refus.

    Classer « au mieux » un chemin ambigu produirait un placement
    plausible et faux, que rien en aval ne saurait distinguer d'un bon."""


@dataclass(frozen=True)
class Placement:
    """Où un artefact se range, tel que son chemin gouverné le dit."""

    zone: str
    cycle: str | None
    niveau: str | None
    matiere: str | None
    nature: str | None
    millesime: str | None

    @property
    def servable(self) -> bool:
        return self.zone not in CONTROL_PLANE_ZONES


@dataclass(frozen=True)
class PageText:
    """Une page et son texte, tels que l'extracteur les rend."""

    number: int
    text: str


@dataclass(frozen=True)
class StagedChunk:
    """Un chunk prêt pour la revue, avec de quoi le relire et le retrouver."""

    chunk_id: str
    artifact_id: str
    chunk_index: int
    chunk_sha256: str
    page_start: int
    page_end: int
    text: str


@dataclass(frozen=True)
class StagedArtifact:
    """Un artefact en staging : une identité de contenu, un placement."""

    artifact_id: str
    content_sha256: str
    source_kind: str
    mime_type: str
    size_bytes: int
    modified_time: str
    placement: Placement
    review_status: str = STAGING_REVIEW_STATUS


@dataclass(frozen=True)
class StagedProvenance:
    """Un chemin logique qui mène à un artefact. Plusieurs par artefact."""

    artifact_id: str
    source_id: str
    drive_file_id: str
    drive_path: str
    relative_path: str
    shortcut_id: str | None


@dataclass
class SliceReport:
    """Ce que la tranche a créé, et ce qu'elle a retrouvé.

    Les deux sont comptés séparément : un total ne dirait pas si une
    seconde exécution a dédoublé le corpus ou l'a laissé intact."""

    new_artifacts: int = 0
    duplicate_artifacts: int = 0
    new_provenances: int = 0
    duplicate_provenances: int = 0
    new_chunks: int = 0
    duplicate_chunks: int = 0
    acquired_bytes: int = 0
    manifest_sha256: str = ""
    artifact_ids: tuple[str, ...] = ()

    def lines(self) -> Sequence[str]:
        return (
            f"NEW_ARTIFACTS={self.new_artifacts}",
            f"DUPLICATE_ARTIFACTS={self.duplicate_artifacts}",
            f"NEW_PROVENANCES={self.new_provenances}",
            f"DUPLICATE_PROVENANCES={self.duplicate_provenances}",
            f"NEW_CHUNKS={self.new_chunks}",
            f"DUPLICATE_CHUNKS={self.duplicate_chunks}",
            f"ACQUIRED_BYTES={self.acquired_bytes}",
            f"MANIFEST_SHA256={self.manifest_sha256}",
        )


class StagingStore:
    """Le magasin de staging du plan de contrôle.

    Interface volontairement étroite : deux implémentations doivent
    pouvoir prouver la même idempotence, l'une en mémoire pour les tests,
    l'autre sur Postgres pour la tranche réelle."""

    def upsert_artifact(self, artifact: StagedArtifact) -> bool:
        """Rend ``True`` si l'artefact était nouveau."""
        raise NotImplementedError

    def upsert_provenance(self, provenance: StagedProvenance) -> bool:
        raise NotImplementedError

    def upsert_chunk(self, chunk: StagedChunk) -> bool:
        raise NotImplementedError


@dataclass
class InMemoryStagingStore(StagingStore):
    """Magasin de staging en mémoire — la charte de tests interdit une base."""

    artifacts: dict[str, StagedArtifact] = field(default_factory=dict)
    chunks: dict[str, StagedChunk] = field(default_factory=dict)
    _provenances: dict[tuple[str, str], StagedProvenance] = field(default_factory=dict)

    @property
    def provenances(self) -> dict[str, tuple[str, ...]]:
        grouped: dict[str, list[str]] = {}
        for (artifact_id, relative_path) in sorted(self._provenances):
            grouped.setdefault(artifact_id, []).append(relative_path)
        return {key: tuple(value) for key, value in grouped.items()}

    def upsert_artifact(self, artifact: StagedArtifact) -> bool:
        if artifact.artifact_id in self.artifacts:
            return False
        self.artifacts[artifact.artifact_id] = artifact
        return True

    def upsert_provenance(self, provenance: StagedProvenance) -> bool:
        key = (provenance.artifact_id, provenance.relative_path)
        if key in self._provenances:
            return False
        self._provenances[key] = provenance
        return True

    def upsert_chunk(self, chunk: StagedChunk) -> bool:
        if chunk.chunk_id in self.chunks:
            return False
        self.chunks[chunk.chunk_id] = chunk
        return True

    def query(
        self,
        *,
        matiere: str | None = None,
        niveau: str | None = None,
        motif: str | None = None,
    ) -> list[StagedChunk]:
        """Interroge le staging par placement et par motif textuel."""
        found: list[StagedChunk] = []
        for chunk in sorted(self.chunks.values(), key=lambda c: (c.artifact_id, c.chunk_index)):
            placement = self.artifacts[chunk.artifact_id].placement
            if matiere is not None and placement.matiere != matiere:
                continue
            if niveau is not None and placement.niveau != niveau:
                continue
            if motif is not None and motif.lower() not in chunk.text.lower():
                continue
            found.append(chunk)
        return found


def classify_from_hints(hints: Sequence[str]) -> Placement:
    """Classe un artefact d'après les dossiers traversés.

    Les segments sont reconnus par leur *forme*, pas par leur rang : une
    zone qui insère un dossier intermédiaire décalerait toute une
    classification positionnelle d'un cran, sans rien signaler.

    Deux ambiguïtés sont refusées plutôt qu'arbitrées : deux dossiers de
    nature (typiquement un bucket ``80_A_VERIFIER`` empilé sur une nature
    réelle) et deux segments libres. Dans les deux cas, la source dit
    elle-même qu'elle ne sait pas ; choisir à sa place fabriquerait une
    certitude."""
    if not hints:
        raise DriveClassificationError(
            "chemin vide : aucun dossier traversé ne porte de classification"
        )
    zone = hints[0]
    if zone not in KNOWN_ZONES:
        raise DriveClassificationError(
            f"zone inconnue {zone!r} — la racine gouvernée n'en déclare que "
            f"{sorted(KNOWN_ZONES)}"
        )

    cycles: list[str] = []
    niveaux: list[str] = []
    natures: list[str] = []
    millesimes: list[str] = []
    libres: list[str] = []

    for segment in hints[1:]:
        if segment in KNOWN_CYCLES:
            cycles.append(segment)
        elif segment in KNOWN_NIVEAUX:
            niveaux.append(segment)
        elif _MILLESIME.match(segment):
            millesimes.append(segment)
        elif (match := _NATURE.match(segment)) is not None:
            natures.append(match.group(2))
        else:
            libres.append(segment)

    for label, values in (
        ("cycle", cycles),
        ("niveau", niveaux),
        ("nature", natures),
        ("millésime", millesimes),
        ("matière", libres),
    ):
        if len(values) > 1:
            raise DriveClassificationError(
                f"chemin ambigu : {len(values)} segments de {label} "
                f"({values}) — arbitrer reviendrait à classer au hasard un "
                "document que la source elle-même dit incertain"
            )

    if zone not in CONTROL_PLANE_ZONES and not libres:
        raise DriveClassificationError(
            f"aucune matière dans {list(hints)} — un artefact servable sans "
            "discipline ne peut être placé"
        )

    return Placement(
        zone=zone,
        cycle=cycles[0].lower() if cycles else None,
        niveau=niveaux[0].lower() if niveaux else None,
        matiere=libres[0].lower() if libres else None,
        nature=natures[0].lower() if natures else None,
        millesime=millesimes[0] if millesimes else None,
    )


def make_chunks(artifact_id: str, pages: Iterable[PageText]) -> tuple[StagedChunk, ...]:
    """Un chunk par page, identifié par (artefact, rang, texte).

    Le rang est celui de la page, pas celui du chunk retenu : sauter une
    page vide en resserrant les rangs changerait toutes les identités
    suivantes, et deux découpages du même PDF ne coïncideraient plus."""
    chunks: list[StagedChunk] = []
    for index, page in enumerate(pages):
        text = page.text.strip()
        if not text:
            continue
        chunk_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        chunks.append(
            StagedChunk(
                chunk_id=hashlib.sha256(
                    f"{artifact_id}:{index}:{chunk_sha}".encode()
                ).hexdigest(),
                artifact_id=artifact_id,
                chunk_index=index,
                chunk_sha256=chunk_sha,
                page_start=page.number,
                page_end=page.number,
                text=text,
            )
        )
    if not chunks:
        raise CorpusAcquisitionError(
            f"l'artefact {artifact_id} ne rend aucun texte — le stager vide "
            "passerait pour un document ingéré alors qu'il n'enseigne rien"
        )
    return tuple(chunks)


#: Extraction des pages d'un document. Injectée : le runtime pypdf
#: canonique n'a pas à être importé pour tester le reste de la chaîne.
ExtractPages = Callable[[bytes], tuple[PageText, ...]]


def run_slice(
    adapter: DriveSourceAdapter,
    *,
    scope: Collection[str],
    destination: Path,
    store: StagingStore,
    extract_pages: ExtractPages,
) -> SliceReport:
    """Fait passer un périmètre Drive de bout en bout jusqu'au staging."""
    requested = set(scope)
    if not requested:
        raise CorpusAcquisitionError(
            "périmètre vide : la tranche ne prouverait rien"
        )

    discovered = adapter.discover()
    by_path = {obj.relative_path: obj for obj in discovered}
    missing = sorted(requested - set(by_path))
    if missing:
        raise CorpusAcquisitionError(
            "requested but not present in the source: "
            + ", ".join(repr(path) for path in missing)
        )
    manifest_object = by_path.get(MANIFEST_SELF_PATH)
    if manifest_object is None:
        raise CorpusAcquisitionError(
            f"la source ne porte pas {MANIFEST_SELF_PATH} — la tranche ne "
            "pourrait être recoupée qu'avec elle-même"
        )

    selected = [by_path[path] for path in sorted(requested)] + [manifest_object]
    report = acquire_corpus(
        adapter.to_drive_files(selected),
        destination=destination,
        download=adapter.download,
    )
    require_scoped_reconciled(report, requested=requested)

    artifacts = adapter.materialise([by_path[path] for path in sorted(requested)])
    slice_report = SliceReport(
        acquired_bytes=report.total_bytes,
        manifest_sha256=report.manifest.manifest_sha256,
        artifact_ids=tuple(artifact.artifact_id for artifact in artifacts),
    )

    for artifact in artifacts:
        placement = classify_from_hints(artifact.taxonomy_hints)
        created = store.upsert_artifact(
            StagedArtifact(
                artifact_id=artifact.artifact_id,
                content_sha256=artifact.content_sha256,
                source_kind=SOURCE_KIND,
                mime_type=artifact.mime_type,
                size_bytes=artifact.size,
                modified_time=artifact.modified_time,
                placement=placement,
            )
        )
        slice_report.new_artifacts += int(created)
        slice_report.duplicate_artifacts += int(not created)

        for relative_path in artifact.occurrences:
            occurrence: DriveObject = by_path[relative_path]
            fresh = store.upsert_provenance(
                StagedProvenance(
                    artifact_id=artifact.artifact_id,
                    source_id=occurrence.source_id,
                    drive_file_id=occurrence.drive_file_id,
                    drive_path=occurrence.drive_path,
                    relative_path=occurrence.relative_path,
                    shortcut_id=occurrence.shortcut_id,
                )
            )
            slice_report.new_provenances += int(fresh)
            slice_report.duplicate_provenances += int(not fresh)

        # Les octets lus sont ceux que l'acquisition a écrits puis
        # rehachés — jamais ceux que le téléchargement a rendus.
        proven = (report.root / artifact.occurrences[0]).read_bytes()
        for chunk in make_chunks(artifact.artifact_id, extract_pages(proven)):
            fresh_chunk = store.upsert_chunk(chunk)
            slice_report.new_chunks += int(fresh_chunk)
            slice_report.duplicate_chunks += int(not fresh_chunk)

    return slice_report


__all__ = [
    "KNOWN_CYCLES",
    "KNOWN_NIVEAUX",
    "KNOWN_ZONES",
    "STAGING_REVIEW_STATUS",
    "DriveClassificationError",
    "ExtractPages",
    "InMemoryStagingStore",
    "PageText",
    "Placement",
    "SliceReport",
    "StagedArtifact",
    "StagedChunk",
    "StagedProvenance",
    "StagingStore",
    "classify_from_hints",
    "make_chunks",
    "run_slice",
]
