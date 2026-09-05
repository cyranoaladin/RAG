"""Acquisition depuis Google Drive — lecture seule, déterministe, fail-closed.

**Drive acquiert ; il ne fait pas autorité.** Un dossier Drive est
mutable : un fichier peut être remplacé, un identifiant réattribué, un
partage élargi, le tout sans que rien ne change dans le dépôt. Ce module
existe pour transformer, une fois, un contenu mutable en un contenu
adressé par son hachage — après quoi Drive n'est plus jamais consulté.
``corpus_source_resolver`` ne connaît que GHCR et un digest.

**Le manifeste livré n'est pas non plus une autorité.** La source porte
déjà ``00_ADMIN/SHA256SUMS.txt``. Il serait tentant de le croire sur
parole : il vient du même endroit que les octets qu'il décrit, donc un
corpus altéré arriverait avec un manifeste altéré assorti. On le traite
comme une *déclaration du producteur*, à recouper avec ce qu'on a
réellement téléchargé. Ce que ce recoupement attrape est étroit mais
réel : une corruption de transport, un téléchargement partiel, un fichier
modifié entre l'établissement du manifeste et la copie. Ce qu'il
n'attrape pas — une source hostile cohérente avec elle-même — relève de
l'approbation humaine du descripteur de campagne, pas d'ici.

L'autorité naît donc plus tard, et d'un humain : quand un relecteur
approuve un ``campaign.json`` versionné portant les digests *recalculés
localement*. Avant cette approbation, rien de ce qui sort d'ici ne peut
publier quoi que ce soit.

**Refus des fichiers sans octets stables.** Un Google Doc n'a pas de
contenu : il a des exports, et deux exports du même document à deux dates
peuvent différer. Sceller un export reviendrait à sceller une conversion,
et le digest cesserait d'identifier la source.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from rag_pedago.governance.sealed_corpus import (
    MANIFEST_SELF_PATH,
    MAX_FILES,
    MAX_PATH_BYTES,
    MAX_SINGLE_FILE_BYTES,
    MAX_TOTAL_BYTES,
    SealedManifest,
    generate_sealed_manifest,
)

#: Préfixe des types Drive natifs (Docs, Sheets, Slides, Forms…). Ces
#: objets n'ont pas d'octets : seulement des exports, qui ne sont pas
#: reproductibles dans le temps.
GOOGLE_NATIVE_MIME_PREFIX = "application/vnd.google-apps."

#: Type des dossiers, qui ne sont pas des objets à sceller.
GOOGLE_FOLDER_MIME = "application/vnd.google-apps.folder"

_GNU_LINE = re.compile(r"\A([0-9a-f]{64})  (.+)\Z")


class CorpusAcquisitionError(RuntimeError):
    """L'acquisition ne prouve pas ce qu'elle a téléchargé — refus.

    Aucun repli vers « ce qui a pu être récupéré » : un corpus partiel
    qui se scelle produit une campagne valide décrivant un contenu
    incomplet, et plus rien ensuite ne peut le détecter."""


@dataclass(frozen=True)
class DriveFile:
    """Un objet Drive tel qu'une énumération en lecture seule le décrit."""

    file_id: str
    relative_path: str
    mime_type: str
    size_bytes: int

    @property
    def is_folder(self) -> bool:
        return self.mime_type == GOOGLE_FOLDER_MIME

    @property
    def is_native(self) -> bool:
        return self.mime_type.startswith(GOOGLE_NATIVE_MIME_PREFIX)


#: Téléchargement d'un objet, par identifiant. Injecté pour que les tests
#: n'aient jamais besoin d'un compte de service — et pour qu'aucun
#: identifiant ne puisse être codé en dur dans ce module.
DriveDownload = Callable[[str], bytes]


@dataclass
class AcquisitionReport:
    """Ce qui a été acquis, et ce qui ne l'a pas été.

    Les exclusions sont énumérées, jamais résumées par un compteur : un
    fichier écarté sans que son chemin soit nommé est un fichier disparu
    en silence."""

    root: Path
    manifest: SealedManifest
    file_count: int
    total_bytes: int
    declared_manifest_present: bool
    declared_manifest_sha256: str | None
    skipped_native: list[str] = field(default_factory=list)
    skipped_folders: int = 0
    reconciliation_errors: list[str] = field(default_factory=list)
    #: La déclaration du producteur, telle qu'elle a été lue. Conservée
    #: pour qu'un recoupement de *périmètre* puisse comparer chemin par
    #: chemin ; sans elle, une tranche ne pourrait être recoupée qu'avec
    #: elle-même.
    declared_manifest: dict[str, str] = field(default_factory=dict)

    @property
    def reconciled(self) -> bool:
        """Le manifeste livré et les octets téléchargés concordent-ils ?"""
        return self.declared_manifest_present and not self.reconciliation_errors


def parse_declared_manifest(content: bytes) -> dict[str, str]:
    """Relit le ``SHA256SUMS.txt`` livré par la source.

    Le format GNU est exigé tel quel — deux espaces, hex minuscule. Une
    tolérance ici rendrait acceptables deux fichiers différents pour un
    même corpus, ce que tout le reste de la chaîne s'emploie à interdire.
    """
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorpusAcquisitionError(
            "the delivered manifest is not valid UTF-8"
        ) from exc

    declared: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        if not line:
            continue
        match = _GNU_LINE.match(line)
        if match is None:
            raise CorpusAcquisitionError(
                f"delivered manifest line {number} is not GNU sha256sum format "
                "(<64 lowercase hex><two spaces><path>)"
            )
        digest, path = match.group(1), unicodedata.normalize("NFC", match.group(2))
        if path in declared:
            raise CorpusAcquisitionError(
                f"delivered manifest declares {path!r} twice — which of the two "
                "digests describes the object cannot be decided"
            )
        declared[path] = digest
    if not declared:
        raise CorpusAcquisitionError(
            "the delivered manifest is empty — it would seal nothing while looking "
            "like a valid declaration"
        )
    return declared


def _safe_relative(path: str) -> str:
    normalised = unicodedata.normalize("NFC", path)
    if normalised.startswith("/"):
        raise CorpusAcquisitionError(f"{path!r} is an absolute path")
    if any(part in ("..", "") for part in normalised.split("/")):
        raise CorpusAcquisitionError(
            f"{path!r} escapes the acquisition root or contains an empty segment"
        )
    if len(normalised.encode("utf-8")) > MAX_PATH_BYTES:
        raise CorpusAcquisitionError(
            f"{path!r} exceeds the {MAX_PATH_BYTES}-byte governed path bound"
        )
    return normalised


def acquire_corpus(
    files: Iterable[DriveFile],
    *,
    destination: Path,
    download: DriveDownload,
) -> AcquisitionReport:
    """Matérialise l'arbre, puis le rehache intégralement.

    Le manifeste local est régénéré depuis les octets écrits, jamais
    recopié depuis la source : c'est ce recalcul qui fait passer le corpus
    d'un contenu déclaré à un contenu prouvé."""
    destination.mkdir(parents=True, exist_ok=True)
    destination.chmod(0o700)

    declared_manifest: dict[str, str] | None = None
    declared_manifest_sha256: str | None = None
    skipped_native: list[str] = []
    skipped_folders = 0
    written = 0
    total_bytes = 0
    seen: set[str] = set()

    # Ordre déterministe : deux acquisitions du même dossier doivent
    # écrire les mêmes octets et rapporter les mêmes exclusions.
    for item in sorted(files, key=lambda f: f.relative_path):
        if item.is_folder:
            skipped_folders += 1
            continue
        relative = _safe_relative(item.relative_path)
        if item.is_native:
            # Nommé, jamais compté en silence.
            skipped_native.append(relative)
            continue
        if relative in seen:
            raise CorpusAcquisitionError(
                f"{relative!r} is listed twice — the later download would silently "
                "overwrite the earlier one"
            )
        seen.add(relative)

        if item.size_bytes > MAX_SINGLE_FILE_BYTES:
            raise CorpusAcquisitionError(
                f"{relative!r} declares {item.size_bytes} bytes, above the "
                f"{MAX_SINGLE_FILE_BYTES}-byte bound"
            )

        payload = download(item.file_id)

        # Le producteur annonce une taille ; on vérifie ce qui est arrivé.
        # Un téléchargement tronqué se hacherait sans erreur.
        if len(payload) != item.size_bytes:
            raise CorpusAcquisitionError(
                f"{relative!r} was announced as {item.size_bytes} bytes but "
                f"{len(payload)} arrived — refusing a truncated download rather "
                "than sealing it"
            )

        total_bytes += len(payload)
        if total_bytes > MAX_TOTAL_BYTES:
            raise CorpusAcquisitionError(
                f"acquisition exceeds the {MAX_TOTAL_BYTES}-byte governed bound"
            )

        if relative == MANIFEST_SELF_PATH:
            declared_manifest = parse_declared_manifest(payload)
            declared_manifest_sha256 = hashlib.sha256(payload).hexdigest()
            # Le self-object n'est pas écrit dans l'arbre : le manifeste
            # régénéré ne se contient jamais.
            continue

        written += 1
        if written > MAX_FILES:
            raise CorpusAcquisitionError(
                f"acquisition exceeds {MAX_FILES} objects"
            )
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)

    if written == 0:
        raise CorpusAcquisitionError(
            "no regular object was acquired — an empty tree would seal nothing "
            "while looking like a valid campaign"
        )

    manifest = generate_sealed_manifest(destination)

    errors: list[str] = []
    if declared_manifest is None:
        errors.append(
            f"the source carries no {MANIFEST_SELF_PATH} — the acquisition cannot "
            "be cross-checked against what the producer claims to have sealed"
        )
    else:
        errors.extend(_reconcile(declared_manifest, manifest))

    return AcquisitionReport(
        root=destination,
        manifest=manifest,
        file_count=written,
        total_bytes=total_bytes,
        declared_manifest_present=declared_manifest is not None,
        declared_manifest_sha256=declared_manifest_sha256,
        skipped_native=skipped_native,
        skipped_folders=skipped_folders,
        reconciliation_errors=errors,
        declared_manifest=dict(declared_manifest or {}),
    )


def _reconcile(declared: dict[str, str], manifest: SealedManifest) -> list[str]:
    """Recoupe la déclaration du producteur avec les octets téléchargés.

    Les trois écarts sont distingués parce qu'ils ne signifient pas la
    même chose : un objet manquant est une acquisition incomplète, un
    objet en trop est une source qui a bougé, un digest différent est une
    altération."""
    actual = {path: digest for digest, path in manifest.entries}
    errors: list[str] = []

    for path in sorted(set(declared) - set(actual)):
        errors.append(
            f"declared but not acquired: {path!r} — the download is incomplete"
        )
    for path in sorted(set(actual) - set(declared)):
        errors.append(
            f"acquired but not declared: {path!r} — the source changed after its "
            "manifest was written"
        )
    for path in sorted(set(declared) & set(actual)):
        if declared[path] != actual[path]:
            errors.append(
                f"digest mismatch for {path!r}: declared {declared[path]}, "
                f"acquired {actual[path]}"
            )
    return errors


def require_reconciled(report: AcquisitionReport) -> AcquisitionReport:
    """Refuse une acquisition non recoupée.

    Point de passage obligé avant toute construction de campagne : sans
    lui, un appelant pourrait lire ``reconciliation_errors`` et décider de
    continuer."""
    if not report.declared_manifest_present:
        raise CorpusAcquisitionError(
            f"the source carries no {MANIFEST_SELF_PATH}; there is nothing to "
            "cross-check the acquisition against"
        )
    if report.reconciliation_errors:
        joined = "\n  - ".join(report.reconciliation_errors[:20])
        more = (
            f"\n  … and {len(report.reconciliation_errors) - 20} more"
            if len(report.reconciliation_errors) > 20
            else ""
        )
        raise CorpusAcquisitionError(
            "the acquired tree does not match the manifest the source delivered:\n"
            f"  - {joined}{more}"
        )
    return report


def require_scoped_reconciled(
    report: AcquisitionReport,
    *,
    requested: Collection[str],
) -> AcquisitionReport:
    """Recoupe une acquisition *partielle* sur le périmètre demandé.

    ``require_reconciled`` compare l'acquisition au corpus entier : c'est
    ce qu'il faut pour sceller une campagne, et c'est exactement ce qui
    rend toute tranche impossible. Une tranche a pourtant besoin d'être
    prouvée, sans quoi une ingestion incrémentale n'aurait plus qu'une
    auto-vérification à offrir : le digest recalculé comparé à lui-même.

    Le périmètre est donc une **entrée**, pas une déduction de ce qui est
    arrivé. C'est la différence entre « j'ai demandé ces objets, les
    voici, et le producteur les déclare ainsi » et « voici ce qui a fini
    par arriver, et ça se tient » — la seconde formulation accepte un
    téléchargement rétréci en silence.

    Quatre divergences sont refusées, chacune parce qu'elle signifie
    autre chose : un objet demandé que le producteur ne déclare pas n'est
    recoupable contre rien ; un objet demandé et non acquis est un
    téléchargement incomplet ; un objet acquis hors périmètre est une
    source qui a bougé ; un digest différent est une altération. Les
    objets déclarés *hors* périmètre, eux, sont attendus : c'est ce qui
    fait de ceci une tranche.
    """
    scope = {unicodedata.normalize("NFC", path) for path in requested}
    if not scope:
        raise CorpusAcquisitionError(
            "empty scope: a slice with no requested object would pass every "
            "check while proving nothing"
        )
    if not report.declared_manifest_present:
        raise CorpusAcquisitionError(
            f"the source carries no {MANIFEST_SELF_PATH}; there is nothing to "
            "cross-check the requested scope against"
        )

    declared = report.declared_manifest
    acquired = {path: digest for digest, path in report.manifest.entries}
    problems: list[str] = []

    for path in sorted(scope - set(declared)):
        problems.append(
            f"never declared: {path!r} was requested but the producer manifest "
            "does not describe it — its digest could only be compared to itself"
        )
    for path in sorted(scope - set(acquired)):
        problems.append(
            f"requested but not acquired: {path!r} — the download is incomplete"
        )
    for path in sorted(set(acquired) - scope):
        problems.append(
            f"acquired outside the requested scope: {path!r} — the source changed "
            "under the acquisition"
        )
    for path in sorted(scope & set(declared) & set(acquired)):
        if declared[path] != acquired[path]:
            problems.append(
                f"digest mismatch for {path!r}: declared {declared[path]}, "
                f"acquired {acquired[path]}"
            )

    if problems:
        joined = "\n  - ".join(problems[:20])
        more = f"\n  … and {len(problems) - 20} more" if len(problems) > 20 else ""
        raise CorpusAcquisitionError(
            "the acquired slice does not match the requested scope:\n"
            f"  - {joined}{more}"
        )
    return report


def verify_expected_inventory(
    report: AcquisitionReport,
    *,
    expected_counts: dict[str, int],
) -> None:
    """Compare l'acquisition à un inventaire attendu, zone par zone.

    Un total global qui tombe juste peut masquer deux erreurs opposées :
    trente PDF perdus dans une zone et trente gagnés dans une autre. La
    comparaison est donc par zone, et exhaustive dans les deux sens."""
    actual: dict[str, int] = {}
    for _digest, path in report.manifest.entries:
        zone = path.partition("/")[0]
        actual[zone] = actual.get(zone, 0) + 1

    problems: list[str] = []
    for zone in sorted(set(expected_counts) | set(actual)):
        want = expected_counts.get(zone)
        got = actual.get(zone, 0)
        if want is None:
            problems.append(f"{zone}: {got} objects acquired but none expected")
        elif want != got:
            problems.append(f"{zone}: expected {want}, acquired {got}")
    if problems:
        raise CorpusAcquisitionError(
            "acquired inventory diverges from the expected one:\n  - "
            + "\n  - ".join(problems)
        )


def zone_counts(manifest: SealedManifest) -> dict[str, int]:
    """Cardinalités par zone, pour alimenter un descripteur de campagne."""
    counts: dict[str, int] = {}
    for _digest, path in manifest.entries:
        zone = path.partition("/")[0]
        counts[zone] = counts.get(zone, 0) + 1
    return dict(sorted(counts.items()))


def summarise(report: AcquisitionReport) -> Sequence[str]:
    """Résumé lisible — les exclusions sont nommées, pas résumées."""
    lines = [
        f"objets acquis      : {report.file_count}",
        f"octets acquis      : {report.total_bytes}",
        f"manifeste livré    : "
        f"{report.declared_manifest_sha256 or 'ABSENT'}",
        f"manifeste recalculé: {report.manifest.manifest_sha256}",
        f"recoupement        : {'OK' if report.reconciled else 'ÉCHEC'}",
        f"dossiers ignorés   : {report.skipped_folders}",
    ]
    if report.skipped_native:
        lines.append(
            f"objets Drive natifs écartés ({len(report.skipped_native)}) — ils "
            "n'ont pas d'octets stables :"
        )
        lines.extend(f"  - {path}" for path in report.skipped_native)
    for zone, count in zone_counts(report.manifest).items():
        lines.append(f"zone {zone}: {count}")
    return lines


__all__ = [
    "GOOGLE_FOLDER_MIME",
    "GOOGLE_NATIVE_MIME_PREFIX",
    "AcquisitionReport",
    "CorpusAcquisitionError",
    "DriveDownload",
    "DriveFile",
    "acquire_corpus",
    "parse_declared_manifest",
    "require_reconciled",
    "require_scoped_reconciled",
    "summarise",
    "verify_expected_inventory",
    "zone_counts",
]
