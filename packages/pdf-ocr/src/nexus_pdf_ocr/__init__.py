"""Extraction de texte des PDF **sans couche textuelle**, sous runtime déclaré.

Trois documents du corpus gouverné ne rendent aucun texte. Mesuré page par
page, ils portent exactement une image et **zéro police** : ce sont des scans.
Les ranger « document vide » les ferait passer pour ingérés alors qu'ils
n'enseignent rien ; les ignorer perdrait leur contenu pédagogique.

**Ce module ne remplace pas l'extraction ordinaire.** Il n'intervient que
lorsque la couche textuelle est absente, et il le dit.

**Fail-closed, sans exception.** Un chemin d'extraction qui retombe
silencieusement quand sa dépendance manque produit des documents vides
« traités » — indiscernables d'un document réellement vide, et bien plus
dangereux, puisque rien ne signale la perte. Si l'OCR est nécessaire et
indisponible, ce module lève ``OcrRuntimeUnavailable``. Jamais un texte vide
de repli.

**Le runtime fait partie de la preuve.** Le texte rendu dépend du moteur, de
sa version, des données linguistiques et de la résolution de rastérisation.
Deux corpus océrisés sous des runtimes différents ne sont pas comparables :
``describe_runtime`` mesure ce qui est installé, ``require_runtime`` refuse
tout écart avec ce contre quoi une preuve a été produite. Épingler la seule
version Python ne suffirait pas — c'est le binaire et les ``traineddata`` qui
décident du texte.

**La partition des pages est un contrat.** La page physique *N* rend la page
*N*. Un décalage rendrait chaque citation fausse sans que rien ne le montre.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "OCR_CAPABILITY_ID",
    "DEFAULT_DPI",
    "DEFAULT_COLOR_MODE",
    "DEFAULT_OEM",
    "DEFAULT_PSM",
    "DEFAULT_LANGUAGES",
    "OcrError",
    "OcrRuntimeUnavailable",
    "OcrRuntime",
    "OcrPage",
    "describe_runtime",
    "require_runtime",
    "ocr_pdf_pages",
]

#: Identité versionnée de la capacité. Elle est nommée pour être attestée :
#: un texte océrisé n'est reproductible que sous le runtime qui l'a produit.
OCR_CAPABILITY_ID = "NEXUS-PDF-OCR-V1"

#: Résolution de rastérisation. Plus bas dégrade la reconnaissance ; plus haut
#: coûte sans gain mesuré. La valeur est FIXE parce qu'elle change le texte.
DEFAULT_DPI = 300

#: Le corpus est français, avec des citations anglaises. L'ordre compte pour
#: tesseract : il pondère la première langue.
DEFAULT_LANGUAGES = "fra+eng"

#: Mode couleur de la rastérisation. Explicite parce qu'un défaut implicite
#: peut changer avec une version future de poppler, et le texte avec lui.
DEFAULT_COLOR_MODE = "gray"

#: Moteur OCR de tesseract. 1 = LSTM seul — le moteur historique et le mode
#: « les deux » ne rendent pas le même texte.
DEFAULT_OEM = 1

#: Segmentation de page. 3 = page entière, segmentation automatique, sans
#: détection d'orientation : la détection ferait dépendre le texte d'une
#: heuristique non déclarée.
DEFAULT_PSM = 3

#: Locale imposée aux binaires. Sans elle, la locale de la machine peut
#: changer la mise en forme des nombres rendus par certains chemins de code.
FORCED_LOCALE = "C"

#: Un seul fil : tesseract paralléliser peut réordonner ses sorties.
FORCED_THREAD_LIMIT = "1"

_VERSION_TESSERACT = re.compile(r"^tesseract\s+(\S+)", re.MULTILINE)
_VERSION_LEPTONICA = re.compile(r"leptonica-(\S+)")
_VERSION_POPPLER = re.compile(r"pdftoppm\s+version\s+(\S+)")


class OcrError(RuntimeError):
    """L'océrisation n'a pas abouti — refus, jamais un texte vide de repli."""


class OcrRuntimeUnavailable(OcrError):
    """Le runtime déclaré est absent ou incomplet.

    Distinct d'``OcrError`` parce que la remédiation diffère : ici il manque
    une capacité à installer, pas un document à corriger."""


@dataclass(frozen=True)
class OcrRuntime:
    """Tout ce dont le texte rendu dépend, et rien d'autre."""

    capability_id: str
    engine: str
    engine_version: str
    leptonica_version: str
    rasterizer: str
    rasterizer_version: str
    languages: str
    traineddata_sha256: tuple[tuple[str, str], ...]
    dpi: int
    color_mode: str = DEFAULT_COLOR_MODE
    oem: int = DEFAULT_OEM
    psm: int = DEFAULT_PSM
    locale: str = FORCED_LOCALE
    thread_limit: str = FORCED_THREAD_LIMIT

    def identity_sha256(self) -> str:
        """Une empreinte unique du runtime, pour l'inscrire en provenance."""
        parts = [
            self.capability_id,
            self.engine,
            self.engine_version,
            self.leptonica_version,
            self.rasterizer,
            self.rasterizer_version,
            self.languages,
            str(self.dpi),
            self.color_mode,
            f"oem={self.oem}",
            f"psm={self.psm}",
            f"locale={self.locale}",
            f"threads={self.thread_limit}",
            *(f"{langue}:{digest}" for langue, digest in self.traineddata_sha256),
        ]
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OcrPage:
    """Une page physique et le texte que l'OCR en a tiré."""

    number: int
    text: str


def _environnement_fige(runtime: "OcrRuntime | None" = None) -> dict[str, str]:
    """L'environnement fait partie de la commande, donc de la preuve.

    Hériter de celui de l'appelant laisserait la locale et le nombre de fils
    décider du texte rendu, sans qu'aucune attestation ne le dise."""
    base = dict(os.environ)
    base["LC_ALL"] = runtime.locale if runtime else FORCED_LOCALE
    base["LANG"] = base["LC_ALL"]
    base["OMP_THREAD_LIMIT"] = (
        runtime.thread_limit if runtime else FORCED_THREAD_LIMIT
    )
    return base


def _run(
    commande: list[str],
    *,
    quoi: str,
    avec_stderr: bool = False,
    environnement: dict[str, str] | None = None,
) -> str:
    environnement = environnement or _environnement_fige()
    try:
        acheve = subprocess.run(  # noqa: S603
            commande,
            capture_output=True,
            check=False,
            timeout=600,
            env=environnement,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OcrRuntimeUnavailable(f"{quoi} : {type(exc).__name__}: {exc}") from exc
    if acheve.returncode != 0:
        raise OcrError(
            f"{quoi} : code {acheve.returncode} — "
            f"{acheve.stderr.decode('utf-8', 'replace')[:300]}"
        )
    sortie = acheve.stdout.decode("utf-8", "replace")
    if avec_stderr:
        # `pdftoppm -v` écrit sa version sur stderr. Ne lire que stdout la
        # rendait « inconnue » — un composant du runtime sans version ne peut
        # pas servir de preuve de reproductibilité.
        sortie += acheve.stderr.decode("utf-8", "replace")
    return sortie


def _binaire(nom: str) -> str:
    chemin = shutil.which(nom)
    if chemin is None:
        raise OcrRuntimeUnavailable(
            f"OCR_RUNTIME_UNAVAILABLE: {nom} est introuvable — un document "
            "scanné ne peut pas être rendu « traité » sans son texte"
        )
    return chemin


def _repertoire_tessdata(tesseract: str) -> Path:
    sortie = _run([tesseract, "--list-langs"], quoi="liste des langues")
    trouve = re.search(r'"([^"]+)"', sortie)
    if trouve is None:
        raise OcrRuntimeUnavailable(
            "OCR_RUNTIME_UNAVAILABLE: tesseract ne déclare aucun répertoire de "
            "données linguistiques"
        )
    return Path(trouve.group(1))


def describe_runtime(
    *, languages: str = DEFAULT_LANGUAGES, dpi: int = DEFAULT_DPI
) -> OcrRuntime:
    """Mesure le runtime INSTALLÉ. Ne suppose rien, ne devine rien."""
    tesseract = _binaire("tesseract")
    rasteriseur = _binaire("pdftoppm")

    version_brute = _run([tesseract, "--version"], quoi="version de tesseract")
    moteur = _VERSION_TESSERACT.search(version_brute)
    leptonica = _VERSION_LEPTONICA.search(version_brute)
    if moteur is None or leptonica is None:
        raise OcrRuntimeUnavailable(
            "OCR_RUNTIME_UNAVAILABLE: version de tesseract ou de leptonica "
            "illisible — le texte rendu en dépend"
        )

    poppler_brut = _run(
        [rasteriseur, "-v"], quoi="version de pdftoppm", avec_stderr=True
    )
    poppler = _VERSION_POPPLER.search(poppler_brut)
    if poppler is None:
        raise OcrRuntimeUnavailable(
            "OCR_RUNTIME_UNAVAILABLE: version de pdftoppm illisible — la "
            "rastérisation décide du texte, sa version fait partie de la preuve"
        )

    tessdata = _repertoire_tessdata(tesseract)
    empreintes: list[tuple[str, str]] = []
    for langue in languages.split("+"):
        fichier = tessdata / f"{langue}.traineddata"
        if not fichier.is_file():
            raise OcrRuntimeUnavailable(
                f"OCR_RUNTIME_UNAVAILABLE: données linguistiques absentes pour "
                f"{langue!r} ({fichier})"
            )
        empreintes.append(
            (langue, hashlib.sha256(fichier.read_bytes()).hexdigest())
        )

    return OcrRuntime(
        capability_id=OCR_CAPABILITY_ID,
        engine="tesseract",
        engine_version=moteur.group(1),
        leptonica_version=leptonica.group(1),
        rasterizer="pdftoppm",
        rasterizer_version=poppler.group(1),
        languages=languages,
        traineddata_sha256=tuple(empreintes),
        dpi=dpi,
    )


def require_runtime(expected_identity_sha256: str, **kwargs: object) -> OcrRuntime:
    """Refuse tout runtime différent de celui contre lequel la preuve existe."""
    mesure = describe_runtime(**kwargs)  # type: ignore[arg-type]
    obtenue = mesure.identity_sha256()
    if obtenue != expected_identity_sha256:
        raise OcrRuntimeUnavailable(
            f"OCR_RUNTIME_DRIFT: le runtime installé vaut {obtenue[:16]}… alors "
            f"que la preuve a été produite sous {expected_identity_sha256[:16]}… "
            "— deux corpus océrisés sous des runtimes différents ne sont pas "
            "comparables"
        )
    return mesure


def ocr_pdf_pages(content: bytes, *, runtime: OcrRuntime) -> tuple[OcrPage, ...]:
    """Rend une entrée par page PHYSIQUE, dans l'ordre du document.

    La rastérisation nomme ses sorties d'après le numéro de page, et le
    rapprochement se fait sur ce numéro — jamais sur l'ordre de listage d'un
    répertoire, qui trierait ``page-10`` avant ``page-2`` et décalerait toutes
    les citations sans que rien ne le montre.
    """
    tesseract = _binaire("tesseract")
    rasteriseur = _binaire("pdftoppm")
    env = _environnement_fige(runtime)

    with tempfile.TemporaryDirectory(prefix="nexus-ocr-") as brut:
        atelier = Path(brut)
        source = atelier / "source.pdf"
        source.write_bytes(content)

        _run(
            [
                rasteriseur,
                "-r",
                str(runtime.dpi),
                f"-{runtime.color_mode}",
                "-png",
                str(source),
                str(atelier / "page"),
            ],
            quoi="rastérisation",
            environnement=env,
        )

        images = sorted(
            atelier.glob("page-*.png"),
            key=lambda chemin: int(chemin.stem.rsplit("-", 1)[1]),
        )
        if not images:
            raise OcrError(
                "la rastérisation n'a produit aucune page — un document sans "
                "page ne peut pas être distingué d'une lecture qui a échoué"
            )

        pages: list[OcrPage] = []
        for image in images:
            numero = int(image.stem.rsplit("-", 1)[1])
            texte = _run(
                [
                    tesseract,
                    str(image),
                    "stdout",
                    "-l",
                    runtime.languages,
                    "--dpi",
                    str(runtime.dpi),
                    "--oem",
                    str(runtime.oem),
                    "--psm",
                    str(runtime.psm),
                ],
                quoi=f"océrisation de la page {numero}",
                environnement=env,
            )
            pages.append(OcrPage(number=numero, text=texte))

    numeros = [page.number for page in pages]
    if numeros != list(range(1, len(pages) + 1)):
        raise OcrError(
            f"partition de pages incomplète : {numeros[:8]}… — un décalage "
            "rendrait chaque citation fausse sans que rien ne le montre"
        )
    return tuple(pages)
