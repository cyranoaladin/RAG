"""Extraction de texte PDF sous le runtime canonique.

Le découpage en chunks dépend du texte extrait, et le texte extrait
dépend de la version de ``pypdf`` : mesuré sur les 320 PDF de la
production visée, 4.2.0 et 6.14.2 rendent le même nombre de pages et le
même verdict de pages vides, mais un texte différent sur 319 documents
sur 320. Extraire hors du runtime déclaré produirait donc des chunks
reproductibles… d'une machine à l'autre seulement par hasard.

``nexus_pdf_page_policy`` porte ce verrou et le prédicat canonique qui
qualifie une page sans texte. On l'exige ici plutôt que de le
redécrire : deux définitions de « page vide » divergeraient en silence.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from io import BytesIO

from rag_pedago.governance.drive_slice import PageText
from rag_pedago.governance.drive_source import DriveSourceError

#: Identité VERSIONNÉE de la normalisation textuelle appliquée après
#: extraction. Elle est nommée pour pouvoir être attestée : deux corpus
#: découpés sous des normalisations différentes ne sont pas comparables, et
#: une normalisation muette rendrait le découpage irreproductible sans que
#: rien ne le dise.
TEXT_NORMALISATION_ID = "NEXUS-DRIVE-TEXT-NORMALISATION-V1"

#: U+0000 n'est pas du texte. `pypdf` l'émet lorsqu'un glyphe n'a aucune
#: correspondance Unicode dans la police du document — mesuré sur le corpus
#: gouverné, il s'agit systématiquement d'un appel de note de bas de page
#: (`\nN\x00<numéro>`). Le caractère ne porte donc aucune information, et
#: PostgreSQL refuse de le stocker en colonne `text`.
#:
#: On le RETIRE plutôt que de le remplacer : un U+FFFD injecterait un
#: artefact visible dans le texte servi et dans l'empreinte des chunks, là
#: où la suppression rend le texte que le document dit réellement.
#:
#: La normalisation ne touche QUE la représentation textuelle. Le fichier
#: source et son `content_sha256` restent intacts — c'est ce qui permet de
#: rejouer l'extraction et d'obtenir le même résultat.
_CARACTERES_RETIRES = ("\x00",)


def normalise_texte_page(texte: str) -> tuple[str, int]:
    """Rend le texte normalisé et le nombre de caractères retirés.

    Déterministe et sans état : deux exécutions sur les mêmes octets rendent
    le même texte. Le compte est rendu pour que l'appelant puisse l'attester
    plutôt que de le deviner."""
    retires = sum(texte.count(caractere) for caractere in _CARACTERES_RETIRES)
    if not retires:
        return texte, 0
    normalise = texte
    for caractere in _CARACTERES_RETIRES:
        normalise = normalise.replace(caractere, "")
    return normalise, retires


class PdfExtractionError(DriveSourceError):
    """Le document ne se lit pas — refus, jamais un texte vide de repli.

    Un PDF illisible rendu comme « zéro page de texte » serait ingéré
    comme un document sans contenu, indiscernable d'un document
    réellement vide."""


def extract_pdf_pages(content: bytes) -> tuple[PageText, ...]:
    """Rend une entrée par page, dans l'ordre du document."""
    from nexus_pdf_page_policy import require_canonical_pypdf
    from pypdf import PdfReader

    require_canonical_pypdf()

    try:
        reader = PdfReader(BytesIO(content))
    except Exception as exc:
        raise PdfExtractionError(
            f"document illisible : {type(exc).__name__}: {exc}"
        ) from exc

    pages: list[PageText] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            raise PdfExtractionError(
                f"page {number} illisible : {type(exc).__name__}: {exc}"
            ) from exc
        text, _retires = normalise_texte_page(text)
        pages.append(PageText(number=number, text=text))
    if not pages:
        raise PdfExtractionError(
            "document illisible : aucune page — un document sans page ne peut "
            "pas être distingué d'une lecture qui a échoué"
        )
    return tuple(pages)


def refused_pages(content: bytes, pages: tuple[PageText, ...]) -> dict[int, str]:
    """Qualifie les pages sans texte avec le prédicat canonique.

    Une page sans texte n'est pas forcément un problème : une page de
    séparation n'a rien à enseigner. Une page-image, elle, porte un
    contenu que l'ingestion perdrait sans le dire. Le prédicat gouverné
    tranche ; ce module ne le rejoue pas."""
    from nexus_pdf_page_policy import classer_pages_sans_texte

    empty = [page.number for page in pages if not page.text.strip()]
    if not empty:
        return {}
    return classer_pages_sans_texte(content, empty)


__all__ = [
    "DocumentExtraction",
    "EXTRACTION_POLICY_ID",
    "PageProvenance",
    "PdfExtractionError",
    "TextLayerAbsente",
    "extract_pdf_pages",
    "extraction_gouvernee",
    "extraire_document",
    "refused_pages",
]


#: Identité VERSIONNÉE de la politique d'extraction. V1 n'océrisait que le
#: document ENTIÈREMENT muet : un document qui portait une couche textuelle
#: et, parmi ses pages, une page-image, voyait cette page comptée vide. Le
#: scanner PII y lisait du vide, le découpage l'omettait, et rien ne le
#: disait. V2 décide PAGE PAR PAGE.
#:
#: La politique est nommée parce qu'elle change le texte : deux corpus
#: extraits sous V1 et V2 ne sont pas comparables, et un corpus qui ne
#: déclare pas sous laquelle il a été produit ne peut pas être requalifié.
EXTRACTION_POLICY_ID = "NEXUS-DRIVE-PDF-EXTRACTION-V2"

#: Règle de composition : le texte natif d'une page lisible n'est JAMAIS
#: remplacé. L'océrisation ne comble que les pages que la politique de page
#: refuse d'ignorer. Substituer une reconnaissance approximative à une
#: extraction exacte dégraderait le corpus sous couvert de le compléter.
PAGE_COMPOSITION_RULE = "NATIVE_TEXT_KEPT__OCR_FILLS_ONLY_NON_IGNORABLE_EMPTY"

#: Déclencheur de l'océrisation. Nommé pour que « pourquoi cette page a-t-elle
#: été océrisée » ait une réponse écrite plutôt que déduite du code.
OCR_FALLBACK_POLICY = "NON_IGNORABLE_EMPTY_PAGES_ONLY"

#: Voies d'extraction possibles, nommées. Le texte d'une page dépend de celle
#: qui l'a produite : les confondre rendrait deux pages incomparables sans
#: que rien ne le dise.
PATH_NATIVE_TEXT = "NATIVE_TEXT"
PATH_STRUCTURAL_EMPTY = "STRUCTURAL_EMPTY"
PATH_OCR_FALLBACK = "OCR_FALLBACK"
PATH_NOT_ASSESSABLE = "NOT_ASSESSABLE"

#: Conservées pour les appelants de V1. La voie « OCR » indistincte ne dit pas
#: si elle a comblé une page ou tout un document : les nouvelles la remplacent.
EXTRACTION_PATH_TEXT_LAYER = PATH_NATIVE_TEXT
EXTRACTION_PATH_OCR = PATH_OCR_FALLBACK


class TextLayerAbsente(PdfExtractionError):
    """Une page affiche du contenu et aucune capacité OCR n'est disponible.

    Distinct des autres échecs d'extraction : le document est parfaitement
    lisible, c'est le TEXTE qui manque. La remédiation n'est pas de corriger
    le fichier mais de fournir la voie océrisée. Sans elle, le refus est la
    seule réponse honnête : compter la page vide tairait ce qu'elle montre."""


def porte_une_couche_textuelle(pages: Sequence[PageText]) -> bool:
    """Vrai dès qu'UNE page rend du texte.

    Un document dont toutes les pages sont muettes n'est pas « vide » : c'est
    un document dont la couche textuelle est absente. Les confondre ferait
    passer un scan pour un document sans contenu."""
    return any(page.text.strip() for page in pages)


def _empreinte(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PageProvenance:
    """Ce qui a produit le texte d'UNE page, et ce qu'il vaut.

    Sans elle, « ce document a été océrisé » est la seule chose qu'on sache :
    on ne peut ni rejouer une page, ni distinguer une page blanche d'une page
    perdue, ni prouver que le texte soumis au scanner PII est celui qui a été
    découpé."""

    number: int
    extraction_path: str
    #: Ce que l'extracteur natif a rendu, normalisé — y compris la chaîne
    #: vide. C'est le témoin qui permet de rejouer la décision.
    native_text_sha256: str
    #: Le verdict de la politique de page, ou ``None`` si la page rendait du
    #: texte et n'a donc jamais été soumise à la politique.
    page_policy_verdict: str | None
    #: Le texte finalement retenu pour cette page — celui que le scanner PII
    #: lit et que le découpage utilise. Les deux doivent citer CETTE empreinte.
    canonical_page_text_sha256: str
    ocr_runtime_identity_sha256: str | None = None
    normalised_characters_removed: int = 0


@dataclass(frozen=True)
class DocumentExtraction:
    """Le texte canonique d'un document ET la preuve de sa fabrication."""

    policy_id: str
    pages: tuple[PageText, ...]
    provenance: tuple[PageProvenance, ...]
    page_policy_id: str
    page_policy_sha256: str
    pypdf_version: str
    text_normalisation_id: str
    ocr_fallback_policy: str
    page_composition_rule: str
    ocr_runtime_identity_sha256: str | None

    @property
    def pages_non_evaluables(self) -> tuple[int, ...]:
        """Les pages dont personne ne sait ce qu'elles portent.

        Non vide, le document ne peut pas être publié : un scanner PII qui
        n'a pas lu une page ne l'a pas déclarée saine, il ne l'a pas lue."""
        return tuple(
            p.number for p in self.provenance if p.extraction_path == PATH_NOT_ASSESSABLE
        )

    @property
    def assessable(self) -> bool:
        return not self.pages_non_evaluables

    @property
    def canonical_text(self) -> str:
        """LE texte du document — l'unique entrée du scanner PII et du
        découpage. Les faire lire deux compositions différentes rendrait
        « aucune PII » vrai sur un texte et faux sur l'autre."""
        return "\n".join(page.text for page in self.pages)

    def identity(self) -> dict[str, object]:
        """La politique effective, sous forme attestable."""
        return {
            "policy_id": self.policy_id,
            "native_extractor": "pypdf",
            "pypdf_version": self.pypdf_version,
            "page_policy_id": self.page_policy_id,
            "page_policy_sha256": self.page_policy_sha256,
            "text_normalisation_id": self.text_normalisation_id,
            "ocr_fallback_policy": self.ocr_fallback_policy,
            "page_composition_rule": self.page_composition_rule,
            "ocr_runtime_identity_sha256": self.ocr_runtime_identity_sha256,
        }

    def identity_sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(self.identity(), sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()


def _identite_politique_de_page() -> tuple[str, str, str]:
    """Le nom de la politique de page, l'empreinte de son MODULE, et la
    version de ``pypdf`` qu'elle impose.

    L'empreinte du module, pas seulement son nom : une politique dont le code
    change sans changer d'identifiant ferait deux corpus incomparables sous
    la même étiquette."""
    import inspect

    import nexus_pdf_page_policy as politique

    source = inspect.getsourcefile(politique)
    if source is None:  # pragma: no cover - un module sans source est anormal
        raise PdfExtractionError(
            "la politique de page n'expose pas son source : son empreinte ne "
            "peut pas être relevée, et une politique non attestée n'en est pas une"
        )
    empreinte = hashlib.sha256(pathlib.Path(source).read_bytes()).hexdigest()
    return politique.POLICY_ID, empreinte, politique.CANONICAL_PYPDF_VERSION


def extraire_document(
    content: bytes, *, ocr_runtime: object | None = None
) -> DocumentExtraction:
    """Extrait le texte canonique d'un PDF, page par page, avec sa provenance.

    L'ordre est le seul qui se prouve : extraire nativement, qualifier CHAQUE
    page muette par la politique gouvernée, puis n'océriser QUE les pages que
    cette politique refuse d'ignorer. Décider au niveau du document — ce que
    faisait V1 — laisse passer le cas majoritaire : un document qui porte du
    texte ET des pages-images.
    """
    from nexus_pdf_page_policy import classer_pages_sans_texte

    politique_id, politique_sha, version_pypdf = _identite_politique_de_page()
    natives = extract_pdf_pages(content)

    muettes = [page.number for page in natives if not page.text.strip()]
    # `classer_pages_sans_texte` n'est appelée que s'il y a matière : une
    # inspection sans page à inspecter n'aurait rien à dire, et son coût est
    # celui d'une relecture complète du document.
    verdicts: dict[int, str] = (
        classer_pages_sans_texte(content, muettes) if muettes else {}
    )

    a_ocreriser = sorted(verdicts)
    ocerisees: dict[int, str] = {}
    identite_ocr: str | None = None
    if a_ocreriser:
        if ocr_runtime is None:
            raise TextLayerAbsente(
                f"{len(a_ocreriser)} page(s) affichent du contenu que "
                "l'extraction native ne rend pas, et aucun runtime OCR n'est "
                "fourni : les compter vides tairait ce qu'elles montrent"
            )
        from nexus_pdf_ocr import ocr_pdf_pages

        identite_ocr = ocr_runtime.identity_sha256()  # type: ignore[attr-defined]
        # Seules les pages nécessaires : un document de 155 pages dont une
        # seule est illisible n'a pas à être océrisé en entier.
        for page in ocr_pdf_pages(content, runtime=ocr_runtime, pages=a_ocreriser):
            texte, _retires = normalise_texte_page(page.text)
            ocerisees[page.number] = texte
        if set(ocerisees) != set(a_ocreriser):
            raise PdfExtractionError(
                f"l'océrisation rend les pages {sorted(ocerisees)[:8]}… là où "
                f"{a_ocreriser[:8]}… étaient demandées — un décalage rendrait "
                "chaque citation fausse sans que rien ne le montre"
            )

    pages: list[PageText] = []
    provenance: list[PageProvenance] = []
    for page in natives:
        empreinte_native = _empreinte(page.text)
        verdict = verdicts.get(page.number)
        if page.text.strip():
            voie, texte = PATH_NATIVE_TEXT, page.text
        elif verdict is None:
            # Muette et ignorable par la politique — une page de séparation
            # n'a rien à enseigner. Distincte d'une page perdue : la nommer
            # évite qu'un compteur de pages vides mélange les deux.
            voie, texte = PATH_STRUCTURAL_EMPTY, page.text
        else:
            texte = ocerisees[page.number]
            if texte.strip():
                voie = PATH_OCR_FALLBACK
            else:
                # L'OCR a tourné et n'a rien rendu. Ce n'est PAS une page
                # vide : c'est une page dont personne ne sait ce qu'elle
                # porte. La déclarer vide reviendrait à faire dire au
                # scanner PII qu'il l'a lue.
                voie = PATH_NOT_ASSESSABLE
        pages.append(PageText(number=page.number, text=texte))
        provenance.append(
            PageProvenance(
                number=page.number,
                extraction_path=voie,
                native_text_sha256=empreinte_native,
                page_policy_verdict=verdict,
                canonical_page_text_sha256=_empreinte(texte),
                ocr_runtime_identity_sha256=(
                    identite_ocr if voie in (PATH_OCR_FALLBACK, PATH_NOT_ASSESSABLE) else None
                ),
            )
        )

    return DocumentExtraction(
        policy_id=EXTRACTION_POLICY_ID,
        pages=tuple(pages),
        provenance=tuple(provenance),
        page_policy_id=politique_id,
        page_policy_sha256=politique_sha,
        pypdf_version=version_pypdf,
        text_normalisation_id=TEXT_NORMALISATION_ID,
        ocr_fallback_policy=OCR_FALLBACK_POLICY,
        page_composition_rule=PAGE_COMPOSITION_RULE,
        ocr_runtime_identity_sha256=identite_ocr,
    )


def extraction_gouvernee(
    ocr_runtime: object | None = None,
) -> Callable[[bytes], tuple[PageText, ...]]:
    """Adaptateur pour les appelants qui n'attendent que des pages.

    La provenance reste disponible par ``extraire_document`` : un appelant qui
    persiste ou atteste doit l'employer, celui-ci ne rend que le texte.
    """

    def extraire(content: bytes) -> tuple[PageText, ...]:
        return extraire_document(content, ocr_runtime=ocr_runtime).pages

    return extraire
