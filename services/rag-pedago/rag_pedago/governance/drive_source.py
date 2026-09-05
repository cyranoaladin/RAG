"""Frontière source Google Drive — énumération, résolution, empreinte.

**Ce module n'est pas le foyer métier.** Le foyer reste
``corpus_acquisition.acquire_corpus`` : c'est lui qui matérialise l'arbre
puis le *rehache intégralement*, et c'est ce recalcul qui fait passer un
contenu déclaré à un contenu prouvé. Ici, on ne fait qu'une chose :
transformer une arborescence Drive — mutable, paginée, pleine de
raccourcis — en une liste d'objets nommés, ordonnée et reproductible,
que l'acquisition gouvernée saura consommer.

Quatre propriétés portent tout le reste, et chacune existe parce que son
absence produit une erreur *silencieuse* :

**Une occurrence logique n'est pas un artefact physique.** Drive laisse
le même fichier apparaître à plusieurs endroits via des raccourcis.
Compter les occurrences comme des artefacts gonflerait l'inventaire,
retéléchargerait les mêmes octets et créerait deux identités pour un même
contenu. L'identité d'un artefact est donc son empreinte de contenu, et
rien d'autre ; une occurrence supplémentaire est une *provenance*
supplémentaire.

**Une découverte doit être reprenable.** Une pagination sur des milliers
d'objets sera interrompue. Reprendre depuis le début redonnerait les
mêmes objets une seconde fois ; reprendre « à peu près » en perdrait.
L'état de découverte est donc explicite, immuable, et n'avance jamais sur
une page qui a échoué.

**Une réponse partielle est refusée, jamais complétée.** Une entrée sans
``mimeType`` ou sans ``size`` n'est pas un objet qu'on peut ignorer :
c'est une réponse qu'on ne sait pas interpréter. La compléter par un
défaut reviendrait à inventer la source.

**Les exclusions gouvernées sont nommées.** Un sous-arbre déclaré non
ingestible n'est pas une erreur : c'est une décision. Il est énuméré
comme exclusion, avec sa raison — jamais compté comme un échec, jamais
oublié en silence.
"""
from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from rag_pedago.governance.corpus_acquisition import (
    GOOGLE_FOLDER_MIME,
    GOOGLE_NATIVE_MIME_PREFIX,
    DriveFile,
)

#: Nature de la source, portée par chaque objet remis au pipeline.
SOURCE_KIND = "GOOGLE_DRIVE"

#: Un raccourci Drive : une occurrence, pas un contenu.
GOOGLE_SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

#: Zones de plan de contrôle. Elles sont découvertes — le manifeste livré
#: par le producteur vit dans ``00_ADMIN`` — mais jamais servies en
#: retrieval.
CONTROL_PLANE_ZONES = frozenset({"00_ADMIN", "00_INDEX_PROVENANCE"})

#: Sous-arbres déclarés non ingestibles par la gouvernance de la source.
#: Ils ne sont pas énumérés du tout : les descendre coûterait des milliers
#: d'appels pour produire des exclusions une par une.
NON_INGESTABLE_SUBTREES = frozenset(
    {
        "ARCHIVES_SOURCES_NON_INGESTABLES",
        "OUTILS_NEXUS_NON_INGESTABLES",
    }
)

#: Raisons d'exclusion. Nommées, parce qu'un compteur ne dit pas si un
#: objet manquant relève d'une décision ou d'une panne.
EXCLUSION_GOVERNED_SOURCE_CLASS = "EXCLUDED_BY_GOVERNED_SOURCE_CLASS"
EXCLUSION_UNSTABLE_EXPORT = "EXCLUDED_UNSTABLE_EXPORT"

#: Champs sans lesquels une entrée Drive n'est pas interprétable.
_REQUIRED_FIELDS = ("id", "name", "mimeType", "modifiedTime")

#: Champs à demander à ``files.list`` pour que ce module ait de quoi
#: travailler. Exporté pour que le transport réel et les tests parlent du
#: même contrat.
LIST_FIELDS = (
    "nextPageToken, files(id, name, mimeType, modifiedTime, size, "
    "md5Checksum, shortcutDetails(targetId, targetMimeType))"
)

#: Exports des formats Google natifs. Ces objets n'ont pas d'octets
#: stables : l'export existe pour le plan de contrôle, pas pour
#: l'acquisition scellée.
NATIVE_EXPORT_MIME = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}


class DriveSourceError(RuntimeError):
    """La source ne peut pas être énumérée telle quelle — refus explicite.

    Aucun repli vers « ce qui a pu être listé » : une découverte partielle
    qui se donne pour complète produit un inventaire crédible et faux."""


class DriveTransientError(DriveSourceError):
    """Panne réessayable (429, 5xx). Le transport la lève ; le retry la
    rattrape. Toute autre exception traverse sans être réessayée : une
    erreur de droits rejouée cinq fois reste une erreur de droits."""


@dataclass(frozen=True)
class DrivePage:
    """Une page de ``files.list``, telle que le transport la rend."""

    entries: tuple[Mapping[str, Any], ...]
    next_page_token: str | None


class DriveTransport(Protocol):
    """Le seul point de contact avec l'API Drive.

    Volontairement muet : il liste, il télécharge, il exporte. Toute la
    logique gouvernable — pagination, cycles, raccourcis, retries — vit
    au-dessus, donc reste testable sans compte de service."""

    def list_children(self, folder_id: str, *, page_token: str | None) -> DrivePage: ...

    def get_metadata(self, file_id: str) -> Mapping[str, Any]: ...

    def fetch(self, file_id: str) -> bytes: ...

    def export(self, file_id: str, *, mime_type: str) -> bytes: ...


@dataclass(frozen=True)
class DriveObject:
    """Une *occurrence* d'objet Drive, avec tout ce que le pipeline exige.

    ``source_id`` identifie l'occurrence (un chemin logique) ;
    ``drive_file_id`` identifie le fichier physique. Les deux diffèrent
    dès qu'un raccourci est en jeu, et c'est précisément la distinction
    qui empêche de compter deux fois le même contenu."""

    source_id: str
    drive_file_id: str
    drive_path: str
    relative_path: str
    mime_type: str
    modified_time: str
    size: int
    taxonomy_hints: tuple[str, ...]
    shortcut_id: str | None = None
    source_kind: str = SOURCE_KIND

    @property
    def zone(self) -> str:
        return self.relative_path.partition("/")[0] if "/" in self.relative_path else ""

    @property
    def servable(self) -> bool:
        """Un objet de plan de contrôle est acquis, jamais servi."""
        return self.zone not in CONTROL_PLANE_ZONES


@dataclass(frozen=True)
class MaterialisedArtifact:
    """Un artefact *physique*, identifié par ses octets.

    ``occurrences`` porte tous les chemins logiques qui y mènent : une
    identité, plusieurs provenances."""

    artifact_id: str
    content_sha256: str
    size: int
    mime_type: str
    modified_time: str
    occurrences: tuple[str, ...]
    drive_file_ids: tuple[str, ...]
    taxonomy_hints: tuple[str, ...]


@dataclass(frozen=True)
class _Frame:
    """Un dossier restant à énumérer, et où sa pagination en est."""

    folder_id: str
    path: str
    page_token: str | None


@dataclass(frozen=True)
class DiscoveryState:
    """L'état complet d'une découverte, sérialisable et immuable.

    Immuable pour une raison précise : une page qui échoue ne doit pas
    avoir avancé l'état. Le point de reprise est celui que l'appelant
    tient encore en main, pas un compteur interne à moitié incrémenté."""

    pending: tuple[_Frame, ...] = ()
    visited: frozenset[str] = frozenset()
    emitted: frozenset[str] = frozenset()
    consumed: frozenset[tuple[str, str]] = frozenset()
    exclusions: tuple[tuple[str, str], ...] = ()

    @property
    def exhausted(self) -> bool:
        return not self.pending


def taxonomy_hints_from_path(drive_path: str, *, root_name: str) -> tuple[str, ...]:
    """Indices de taxonomie tirés du chemin *parent*, jamais du nom.

    Le nom du fichier est un slug de scraping : il porte un titre, une
    taille et un hash, pas un niveau ni une matière. Ce sont les dossiers
    traversés qui portent la classification (zone, cycle, niveau,
    discipline, nature, millésime)."""
    parts = drive_path.split("/")
    if parts and parts[0] == root_name:
        parts = parts[1:]
    return tuple(parts[:-1])


def _normalise(name: str) -> str:
    """NFC, comme le manifeste livré et le manifeste recalculé.

    Deux écritures Unicode du même nom produiraient deux chemins et donc
    deux artefacts pour un seul fichier."""
    return unicodedata.normalize("NFC", name)


class DriveSourceAdapter:
    """Adaptateur de frontière : Drive → objets gouvernables.

    Il ne décide rien du destin d'un objet. Il énumère, résout, mesure et
    hache ; ``acquire_corpus`` juge."""

    def __init__(
        self,
        transport: DriveTransport,
        *,
        root_folder_id: str,
        root_name: str,
        max_attempts: int = 3,
        sleep: Callable[[float], None] | None = None,
        base_delay_s: float = 0.5,
        non_ingestable_subtrees: frozenset[str] = NON_INGESTABLE_SUBTREES,
    ) -> None:
        if max_attempts < 1:
            raise DriveSourceError("max_attempts doit valoir au moins 1")
        self._transport = transport
        self._root_folder_id = root_folder_id
        self._root_name = root_name
        self._max_attempts = max_attempts
        self._sleep = sleep if sleep is not None else _no_sleep
        self._base_delay_s = base_delay_s
        self._non_ingestable = non_ingestable_subtrees
        self._bytes: dict[str, bytes] = {}
        self._metadata: dict[str, Mapping[str, Any]] = {}
        self._last_state = DiscoveryState()

    # -- découverte ---------------------------------------------------
    @property
    def exclusions(self) -> tuple[tuple[str, str], ...]:
        """Exclusions de la dernière découverte : (chemin, raison)."""
        return self._last_state.exclusions

    def start(self) -> DiscoveryState:
        return DiscoveryState(
            pending=(_Frame(self._root_folder_id, self._root_name, None),),
            visited=frozenset({self._root_folder_id}),
        )

    def discover(self, *, resume: DiscoveryState | None = None) -> list[DriveObject]:
        """Énumère jusqu'à épuisement. Ordre déterministe."""
        state = resume if resume is not None else self.start()
        found: list[DriveObject] = []
        while not state.exhausted:
            batch, state = self.step(state)
            found.extend(batch)
        self._last_state = state
        return found

    def step(self, state: DiscoveryState) -> tuple[list[DriveObject], DiscoveryState]:
        """Consomme exactement une page.

        Rend l'état *après* la page. Si la page échoue, rien n'est rendu
        et l'appelant conserve l'état d'avant : c'est ce qui rend la
        reprise exacte plutôt qu'approximative."""
        if state.exhausted:
            return [], state
        frame, rest = state.pending[0], state.pending[1:]
        page = self._list(frame.folder_id, frame.page_token)

        objects: list[DriveObject] = []
        children: list[_Frame] = []
        visited = set(state.visited)
        emitted = set(state.emitted)
        exclusions = list(state.exclusions)

        for raw in page.entries:
            self._process(
                raw,
                frame=frame,
                objects=objects,
                children=children,
                visited=visited,
                emitted=emitted,
                exclusions=exclusions,
            )

        consumed = set(state.consumed)
        consumed.add((frame.folder_id, frame.page_token or ""))
        continuation: tuple[_Frame, ...] = ()
        if page.next_page_token is not None:
            key = (frame.folder_id, page.next_page_token)
            if key in consumed:
                raise DriveSourceError(
                    f"le dossier {frame.folder_id!r} renvoie un jeton de page déjà "
                    f"consommé ({page.next_page_token!r}) — poursuivre bouclerait "
                    "sur les mêmes objets au lieu d'avancer"
                )
            continuation = (_Frame(frame.folder_id, frame.path, page.next_page_token),)

        return objects, DiscoveryState(
            pending=continuation + tuple(children) + rest,
            visited=frozenset(visited),
            emitted=frozenset(emitted),
            consumed=frozenset(consumed),
            exclusions=tuple(exclusions),
        )

    # -- traitement d'une entrée --------------------------------------
    def _process(
        self,
        raw: Mapping[str, Any],
        *,
        frame: _Frame,
        objects: list[DriveObject],
        children: list[_Frame],
        visited: set[str],
        emitted: set[str],
        exclusions: list[tuple[str, str]],
    ) -> None:
        entry = self._validated(raw)
        name = _normalise(str(entry["name"]))
        path = f"{frame.path}/{name}"
        file_id = str(entry["id"])
        mime = str(entry["mimeType"])
        shortcut_id: str | None = None

        if mime == GOOGLE_SHORTCUT_MIME:
            details = entry.get("shortcutDetails")
            if not isinstance(details, Mapping) or not details.get("targetId"):
                raise DriveSourceError(
                    f"{path!r} est un raccourci sans shortcutDetails.targetId — "
                    "l'occurrence ne peut être rattachée à aucun contenu"
                )
            shortcut_id = file_id
            file_id = str(details["targetId"])
            mime = str(details.get("targetMimeType") or "")
            if not mime:
                raise DriveSourceError(
                    f"{path!r} est un raccourci sans targetMimeType — la nature "
                    "de la cible est indécidable"
                )
            if mime != GOOGLE_FOLDER_MIME:
                # Un dossier n'a ni taille ni octets : seul un raccourci
                # vers un *fichier* oblige à aller chercher la cible.
                entry = self._resolve_target(file_id, entry, path)

        if mime == GOOGLE_FOLDER_MIME:
            if name in self._non_ingestable:
                exclusions.append((path, EXCLUSION_GOVERNED_SOURCE_CLASS))
                return
            if file_id in visited:
                # Raccourci vers un dossier déjà planifié, ou cycle : le
                # descendre une seconde fois dupliquerait tout son contenu.
                return
            visited.add(file_id)
            children.append(_Frame(file_id, path, None))
            return

        if mime.startswith(GOOGLE_NATIVE_MIME_PREFIX):
            exclusions.append((path, EXCLUSION_UNSTABLE_EXPORT))
            return

        relative = path[len(self._root_name) + 1 :] if path.startswith(
            self._root_name + "/"
        ) else path
        if relative in emitted:
            raise DriveSourceError(
                f"{relative!r} serait émis deux fois — deux occurrences ne peuvent "
                "pas partager un même chemin logique"
            )
        emitted.add(relative)

        size_raw = entry.get("size")
        if size_raw is None:
            raise DriveSourceError(
                f"{path!r} est listé sans size — une taille inconnue rend "
                "indétectable un téléchargement tronqué"
            )
        objects.append(
            DriveObject(
                source_id=f"{SOURCE_KIND}:{path}",
                drive_file_id=file_id,
                drive_path=path,
                relative_path=relative,
                mime_type=mime,
                modified_time=str(entry["modifiedTime"]),
                size=int(size_raw),
                taxonomy_hints=taxonomy_hints_from_path(path, root_name=self._root_name),
                shortcut_id=shortcut_id,
            )
        )

    def _validated(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        for required in _REQUIRED_FIELDS:
            if not raw.get(required):
                raise DriveSourceError(
                    f"réponse partielle : une entrée sans {required} — la source "
                    "n'est pas interprétable, et la compléter reviendrait à "
                    f"l'inventer (entrée : {dict(raw)!r})"
                )
        return raw

    def _resolve_target(
        self, target_id: str, shortcut_entry: Mapping[str, Any], path: str
    ) -> Mapping[str, Any]:
        """Le raccourci ne porte ni taille ni date : elles sont à la cible."""
        cached = self._metadata.get(target_id)
        if cached is None:
            cached = self._retry(lambda: self._transport.get_metadata(target_id))
            self._metadata[target_id] = cached
        merged = dict(shortcut_entry)
        merged["modifiedTime"] = cached.get("modifiedTime") or shortcut_entry["modifiedTime"]
        if cached.get("size") is not None:
            merged["size"] = cached["size"]
        return merged

    # -- matérialisation ----------------------------------------------
    def materialise(self, objects: Iterable[DriveObject]) -> tuple[MaterialisedArtifact, ...]:
        """Ramène les occurrences à leurs artefacts physiques.

        Un fichier n'est téléchargé qu'une fois, quel que soit le nombre
        d'occurrences qui y mènent, et l'identité produite est l'empreinte
        de ses octets — pas son identifiant Drive, qui est réattribuable."""
        by_digest: dict[str, list[DriveObject]] = {}
        for obj in sorted(objects, key=lambda o: o.relative_path):
            payload = self.download(obj.drive_file_id)
            if len(payload) != obj.size:
                raise DriveSourceError(
                    f"{obj.relative_path!r} est annoncé à {obj.size} octets mais "
                    f"{len(payload)} sont arrivés — refus d'un téléchargement "
                    "tronqué plutôt que de le hacher"
                )
            digest = hashlib.sha256(payload).hexdigest()
            by_digest.setdefault(digest, []).append(obj)

        artifacts: list[MaterialisedArtifact] = []
        for digest in sorted(by_digest):
            group = by_digest[digest]
            first = group[0]
            artifacts.append(
                MaterialisedArtifact(
                    artifact_id=digest,
                    content_sha256=digest,
                    size=first.size,
                    mime_type=first.mime_type,
                    modified_time=min(o.modified_time for o in group),
                    occurrences=tuple(o.relative_path for o in group),
                    drive_file_ids=tuple(sorted({o.drive_file_id for o in group})),
                    taxonomy_hints=first.taxonomy_hints,
                )
            )
        return tuple(artifacts)

    # -- passage à l'acquisition gouvernée ----------------------------
    def to_drive_files(self, objects: Iterable[DriveObject]) -> list[DriveFile]:
        """Traduit vers le vocabulaire d'``acquire_corpus``."""
        return [
            DriveFile(
                file_id=obj.drive_file_id,
                relative_path=obj.relative_path,
                mime_type=obj.mime_type,
                size_bytes=obj.size,
            )
            for obj in sorted(objects, key=lambda o: o.relative_path)
        ]

    def download(self, file_id: str) -> bytes:
        """``DriveDownload`` pour ``acquire_corpus``, avec cache.

        Le cache n'est pas une optimisation : c'est ce qui garantit qu'une
        occurrence supplémentaire ne consomme pas un second
        téléchargement des mêmes octets."""
        cached = self._bytes.get(file_id)
        if cached is None:
            cached = self._retry(lambda: self._transport.fetch(file_id))
            self._bytes[file_id] = cached
        return cached

    def export(self, file_id: str, *, mime_type: str) -> bytes:
        """Export d'un format Google natif — hors acquisition scellée.

        Deux exports du même document à deux dates peuvent différer :
        sceller un export reviendrait à sceller une conversion."""
        return self._retry(lambda: self._transport.export(file_id, mime_type=mime_type))

    # -- transport borné ----------------------------------------------
    def _list(self, folder_id: str, page_token: str | None) -> DrivePage:
        return self._retry(
            lambda: self._transport.list_children(folder_id, page_token=page_token)
        )

    def _retry(self, call: Callable[[], Any]) -> Any:
        """Retries bornés, et *seulement* sur les pannes réessayables."""
        attempt = 0
        while True:
            try:
                return call()
            except DriveTransientError:
                attempt += 1
                if attempt >= self._max_attempts:
                    raise
                self._sleep(self._base_delay_s * (2 ** (attempt - 1)))


def _no_sleep(_seconds: float) -> None:
    """Attente par défaut : aucune.

    Une attente réelle codée en dur rendrait la suite de tests lente et
    l'appelant sans prise ; le vrai transport injecte ``time.sleep``."""
    return None


__all__ = [
    "CONTROL_PLANE_ZONES",
    "EXCLUSION_GOVERNED_SOURCE_CLASS",
    "EXCLUSION_UNSTABLE_EXPORT",
    "GOOGLE_SHORTCUT_MIME",
    "LIST_FIELDS",
    "NATIVE_EXPORT_MIME",
    "NON_INGESTABLE_SUBTREES",
    "SOURCE_KIND",
    "DiscoveryState",
    "DriveObject",
    "DrivePage",
    "DriveSourceAdapter",
    "DriveSourceError",
    "DriveTransientError",
    "DriveTransport",
    "MaterialisedArtifact",
    "taxonomy_hints_from_path",
]
