"""Foyer unique du prédicat structurel « page PDF sans texte extractible ».

Pourquoi ce package existe. Deux services exécutaient chacun une copie du même
critère : le scanner PII de `rag-pedago` et l'extracteur de `rag-engine`. Deux
copies « maintenues synchronisées par tests » restent deux autorités ; la règle
cross-service interdit à un service d'importer l'autre. Le critère vit donc
ici, hors des deux services et hors du contrat de retrieval, et les deux
l'appellent. Voir ADR-0046.

Le critère (docs/reports/lot_1_2_critere_page_sans_texte.md), sans seuil :

    Une page sans texte extractible est IGNORABLE si et seulement si, sur son
    flux de contenu et récursivement dans tous les /Form XObjects effectivement
    invoqués, elle ne contient :
      1. aucun XObject /Image ni image en ligne       → sinon PAGE_IMAGE_NON_LISIBLE
      2. aucun opérateur d'affichage de texte          → sinon PAGE_TEXTE_NON_DECODABLE
      3. aucun opérateur de courbe (c, v, y)           → sinon PAGE_TRACE_VECTORIEL
      4. aucun opérateur de tracé libre (m, l)         → sinon PAGE_TRACE_VECTORIEL

    Toute construction restante est `re` seul : un rectangle n'est pas une lettre.

Ce package rend un VERDICT et ne décide rien d'autre : il ne lit aucun fichier
(il reçoit des octets ou des objets pypdf), n'écrit rien, ne connaît ni la PII,
ni le chunking, ni la release. Une panne de l'instrument n'est jamais un verdict :
elle lève `PageInspectionError` (R32), elle ne rend jamais « aucune image ».
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.generic import ContentStream

#: Identifiant versionné de la politique. Un futur critère porte un autre id ;
#: une preuve qui cite celui-ci cite exactement ce prédicat.
POLICY_ID = "NEXUS-PDF-PAGE-POLICY-V1"

#: Le runtime pypdf CANONIQUE de la plateforme — une seule autorité, partagée
#: par le producteur de release (verrou LOT 1b, D-41) et par le worker qui
#: extrait à l'ingestion. Mesuré le 2026-09-02 sur les 320 PDF de la production
#: visée : 4.2.0 et 6.14.2 rendent le même `page_count` et le même verdict de
#: pages vides, mais un texte différent sur 319 documents sur 320 — les chunks
#: en dépendent, donc la reproductibilité de la release aussi. La version
#: retenue est celle sous laquelle les chunks servis ont été produits.
CANONICAL_PYPDF_VERSION = "6.14.2"


class CanonicalRuntimeError(RuntimeError):
    """L'interpréteur n'est pas le runtime déclaré : on ne mesure pas, on refuse."""


def require_canonical_pypdf() -> str:
    """Refuser d'extraire, de sceller ou d'ingérer hors du runtime déclaré."""
    try:
        import pypdf as _pypdf
    except ImportError as exc:  # pragma: no cover - dépend de l'environnement
        raise CanonicalRuntimeError("pypdf est absent de cet interpréteur") from exc
    version = str(_pypdf.__version__)
    if version != CANONICAL_PYPDF_VERSION:
        raise CanonicalRuntimeError(
            f"pypdf {version} n'est pas le runtime déclaré ({CANONICAL_PYPDF_VERSION}) ; "
            "le découpage des chunks en dépend"
        )
    return version

PAGE_REFUS_IMAGE = "PAGE_IMAGE_NON_LISIBLE"
PAGE_REFUS_TEXTE = "PAGE_TEXTE_NON_DECODABLE"
PAGE_REFUS_TRACE = "PAGE_TRACE_VECTORIEL"
PAGE_INSPECTION_ECHOUEE = "PAGE_INSPECTION_FAILED"

#: Les seuls motifs de refus que ce prédicat prononce, par priorité décroissante.
MOTIFS_DE_REFUS: tuple[str, ...] = (PAGE_REFUS_IMAGE, PAGE_REFUS_TEXTE, PAGE_REFUS_TRACE)

#: Ce que chaque motif signifie, pour qui lit une preuve sans ce module sous la main.
SENS_DES_MOTIFS: dict[str, str] = {
    PAGE_REFUS_IMAGE: "page-image non lisible (candidat OCR)",
    PAGE_REFUS_TEXTE: "opérateurs de texte sans texte extractible (encodage non décodable)",
    PAGE_REFUS_TRACE: "tracé vectoriel pouvant porter un glyphe",
}

_OPS_TEXTE = {b"Tj", b"TJ", b"'", b'"'}
_OPS_COURBE = {b"c", b"v", b"y"}
_OPS_TRACE_LIBRE = {b"m", b"l"}


class PageInspectionError(RuntimeError):
    """L'inspection structurelle d'une page n'a pas pu s'effectuer.

    Ce n'est pas un verdict. Une panne d'instrument ne conclut jamais « aucune
    image » : elle refuse, et l'appelant refuse le document.
    """


def inspecter_structure(
    obj: Any,
    reader: Any,
    *,
    vus: set[int],
) -> tuple[int, bool, bool]:
    """Rend (nb_images, opérateur_de_texte, tracé_pouvant_porter_un_glyphe).

    Suit le FLUX DE CONTENU, pas l'inventaire des ressources : beaucoup de
    producteurs attachent le même dictionnaire /Resources à toutes les pages,
    et une image déclarée mais jamais peinte ne porte aucun glyphe. Descend
    récursivement dans les /Form XObjects effectivement invoqués par `Do`.
    Compte les images sans les décoder : aucune dépendance à pillow.

    Toute exception remonte à l'appelant : ce n'est pas ici qu'on décide ce
    qu'une panne signifie.
    """
    images = 0
    texte = False
    trace = False

    xobjects: Any = {}
    ressources = obj.get("/Resources")
    if ressources is not None:
        declares = ressources.get_object().get("/XObject")
        if declares is not None:
            xobjects = declares.get_object()

    # Une page porte son flux dans /Contents ; un /Form XObject EST son flux.
    source = obj.get_contents() if hasattr(obj, "get_contents") else obj
    if source is None:
        return images, texte, trace

    for operandes, operateur in ContentStream(source, reader).operations:
        if operateur in _OPS_TEXTE:
            texte = True
        elif operateur in _OPS_COURBE or operateur in _OPS_TRACE_LIBRE:
            trace = True
        elif operateur == b"INLINE IMAGE":
            images += 1
        elif operateur == b"Do" and operandes:
            reference = xobjects.get(operandes[0]) if xobjects else None
            if reference is None:
                # L'instrument ne peut pas dire ce qui est peint : il refuse.
                raise KeyError(f"XObject {operandes[0]!r} introuvable")
            identifiant = getattr(reference, "idnum", None)
            if identifiant is not None:
                if identifiant in vus:
                    continue
                vus.add(identifiant)
            enfant = reference.get_object()
            sous_type = enfant.get("/Subtype")
            if sous_type == "/Image":
                images += 1
            elif sous_type == "/Form":
                n, t, v = inspecter_structure(enfant, reader, vus=vus)
                images += n
                texte = texte or t
                trace = trace or v
    return images, texte, trace


def motif_de_refus_page(page: Any, reader: Any) -> str | None:
    """Verdict canonique d'UNE page sans texte extractible.

    Rend l'un des `MOTIFS_DE_REFUS`, ou `None` si la page est ignorable —
    structurellement incapable de porter un glyphe. Lève `PageInspectionError`
    si l'instrument ne peut pas s'exercer ; jamais de valeur de repli.
    """
    try:
        images, texte, trace = inspecter_structure(page, reader, vus=set())
    except Exception as exc:  # noqa: BLE001 - relevée, jamais convertie en verdict
        raise PageInspectionError(f"{type(exc).__name__}: {exc}") from exc
    if images:
        return PAGE_REFUS_IMAGE
    if texte:
        return PAGE_REFUS_TEXTE
    if trace:
        return PAGE_REFUS_TRACE
    return None


def classer_pages_sans_texte(
    pdf_content: bytes,
    numeros: Sequence[int],
) -> dict[int, str]:
    """Rend {numéro de page (1-indexé): motif de refus} pour les pages NON ignorables.

    Une page absente du résultat est ignorable. `numeros` désigne les pages
    dont l'appelant a déjà constaté qu'elles ne rendent aucun texte ; ce
    prédicat ne re-décide pas de l'extraction de texte, il qualifie l'absence.

    Lève `PageInspectionError` si le document ne se lit pas ou si une page ne
    peut pas être inspectée.
    """
    try:
        reader = PdfReader(BytesIO(pdf_content))
    except Exception as exc:  # noqa: BLE001 - relevée, jamais convertie en verdict
        raise PageInspectionError(
            f"lecture impossible: {type(exc).__name__}: {exc}"
        ) from exc
    refus: dict[int, str] = {}
    for numero in numeros:
        try:
            page = reader.pages[numero - 1]
        except Exception as exc:  # noqa: BLE001 - relevée, jamais convertie en verdict
            raise PageInspectionError(
                f"page {numero}: {type(exc).__name__}: {exc}"
            ) from exc
        try:
            motif = motif_de_refus_page(page, reader)
        except PageInspectionError as exc:
            raise PageInspectionError(f"page {numero}: {exc}") from exc
        if motif is not None:
            refus[numero] = motif
    return refus


def policy_source_sha256() -> str:
    """Empreinte SHA-256 des octets de ce module : la provenance exacte du verdict.

    Une preuve qui enregistre ce digest désigne le prédicat qui l'a rendue, sans
    réinterpréter rétrospectivement l'empreinte d'un scanner qui ne le porte plus.
    """
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


__all__ = [
    "CANONICAL_PYPDF_VERSION",
    "CanonicalRuntimeError",
    "MOTIFS_DE_REFUS",
    "PAGE_INSPECTION_ECHOUEE",
    "PAGE_REFUS_IMAGE",
    "PAGE_REFUS_TEXTE",
    "PAGE_REFUS_TRACE",
    "POLICY_ID",
    "SENS_DES_MOTIFS",
    "PageInspectionError",
    "classer_pages_sans_texte",
    "inspecter_structure",
    "motif_de_refus_page",
    "policy_source_sha256",
    "require_canonical_pypdf",
]
