"""Attribution d'une citation réglementaire à un scope pédagogique.

``NEXUS-CITATION-SCOPE-ATTRIBUTION-V1``.

Le problème qu'il résout. Un document de 300 pages cite le BO spécial n° 1 du
22 janvier 2019. Cette citation ne vaut pas pour le document entier : elle vaut
pour la SECTION où elle se trouve. Attribuer la référence à l'artefact entier
ferait relever de la Terminale un chapitre de Seconde, et l'écart entre les 148
liaisons trouvées et les 10 conservées vient exactement de là.

Ce que ce module s'interdit. Il ne lit ni le nom du fichier, ni le répertoire,
ni la ressemblance de vocabulaire, ni les mots qui entourent la citation. Un
« Première » qui passe par là dans une phrase n'attribue rien : il faut un
INTITULÉ, c'est-à-dire une ligne dont le texte entier délimite une section.
Aucun modèle n'est consulté ; la règle est rejouable caractère par caractère.

L'absence d'attribution est un résultat, pas un échec. Une occurrence
``UNATTRIBUTABLE`` reste ``UNKNOWN`` en aval — elle ne devient jamais un
``INCOMPATIBLE``, et jamais un placement d'autorisation : ce module produit un
scope pédagogique OBSERVÉ, et ``rag_artifact_placements`` reste seule autorité
d'accès.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .reference_programme import aplatir_avec_index, citations_localisees

CONTRACT_ID = "NEXUS-CITATION-SCOPE-ATTRIBUTION-V1"

#: Enum FERMÉE des fondements d'attribution admissibles. Une attribution dont
#: le fondement n'est pas l'un d'eux n'existe pas.
BASE_MANIFESTE = "GOVERNED_MANIFEST_PAGE_RANGE"
BASE_SECTION = "EXPLICIT_SECTION_HEADING"
BASE_PAGE = "EXPLICIT_PAGE_HEADING"
BASE_SOMMAIRE = "EXPLICIT_TABLE_OF_CONTENTS_RANGE"
BASE_METADONNEE = "EXPLICIT_SOURCE_METADATA"
BASE_MULTI = "MULTI_SCOPE_EXPLICIT_SECTION"
BASES_AUTORISEES = (
    BASE_MANIFESTE, BASE_SECTION, BASE_PAGE, BASE_SOMMAIRE, BASE_METADONNEE, BASE_MULTI,
)

#: Nommées pour être refusées explicitement. Chacune produirait une attribution
#: ayant la forme d'une preuve sans en être une, et un lecteur ne pourrait plus
#: distinguer un scope établi d'un scope deviné.
BASES_INTERDITES = (
    "SEMANTIC_SIMILARITY", "NEARBY_WORDS", "FILENAME_GUESS",
    "FOLDER_GUESS", "MODEL_INFERENCE",
)

ATTRIBUE = "CITATION_SCOPE_ATTRIBUTED"
MULTI_SCOPE = "CITATION_SCOPE_MULTI_SCOPE"
NON_ATTRIBUABLE = "CITATION_SCOPE_UNATTRIBUTABLE"
CONFLIT = "CITATION_SCOPE_CONFLICT"
DISPOSITIONS = (ATTRIBUE, MULTI_SCOPE, NON_ATTRIBUABLE, CONFLIT)

#: Les niveaux, sous leurs formes écrites admises. Enum fermée : « cycle 4 »
#: n'est pas un niveau, et « lycée » non plus.
_NIVEAUX = {
    "sixieme": "sixieme", "6e": "sixieme", "6eme": "sixieme",
    "cinquieme": "cinquieme", "5e": "cinquieme", "5eme": "cinquieme",
    "quatrieme": "quatrieme", "4e": "quatrieme", "4eme": "quatrieme",
    "troisieme": "troisieme", "3e": "troisieme", "3eme": "troisieme",
    "seconde": "seconde", "2de": "seconde", "2nde": "seconde",
    "premiere": "premiere", "1re": "premiere", "1ere": "premiere",
    "terminale": "terminale", "tle": "terminale",
}
_ALTERNATIVE_NIVEAU = "|".join(sorted(_NIVEAUX, key=len, reverse=True))

#: Un INTITULÉ, et non une mention. La ligne entière doit être l'intitulé :
#: elle commence en début de ligne, peut porter un préfixe (« classe de »,
#: « programme de », « niveau »), nomme un ou deux niveaux, peut porter un
#: qualificatif court après un tiret ou deux-points, et FINIT LÀ. Une phrase qui
#: contient « en première, les élèves… » n'en est pas une.
#: L'espace admis à l'INTÉRIEUR d'un intitulé est horizontal, jamais un saut de
#: ligne. Le défaut que cela empêche : dans un tableau extrait d'un PDF, les
#: cellules sont repliées, et « Classe de ⏎ terminale » commence en début de
#: ligne et finit en fin de ligne — un intitulé, en apparence. C'en est une
#: CELLULE. L'accepter faisait entrer la mise en page dans la structure, et
#: rattachait à une section une citation qui n'en relevait pas.
_INTITULE = re.compile(
    r"(?:^|\n)[ \t]*"
    r"(?P<intitule>"
    r"(?:classes?[ \t]+de[ \t]+|programmes?[ \t]+(?:de|d[ \t]*')[ \t]*"
    r"|niveaux?[ \t]+|en[ \t]+)?"
    rf"(?:{_ALTERNATIVE_NIVEAU})"
    rf"(?:[ \t]*(?:et|,|/|&)[ \t]*(?:classe[ \t]+de[ \t]+)?(?:{_ALTERNATIVE_NIVEAU}))?"
    r"(?:[ \t]*[-–—:][ \t]*[^\n]{3,60})?"
    r")[ \t]*(?=\n|$)",
    re.IGNORECASE,
)
_MENTION_NIVEAU = re.compile(rf"\b(?:{_ALTERNATIVE_NIVEAU})\b", re.IGNORECASE)

#: Le qualificatif d'un intitulé peut nommer un AUTRE niveau que la section
#: elle-même — « Classe de première : évaluation sur le programme de première »
#: est cohérent, mais « Classe de terminale : rappels de première » ne délimite
#: pas une section de première. Seuls les niveaux nommés AVANT le séparateur
#: délimitent ; le qualificatif est conservé pour la trace, jamais pour le
#: scope.
_SEPARATEUR_QUALIFICATIF = re.compile(r"\s*[-–—:]\s*")


def normaliser_intitule(intitule: str) -> str:
    """La forme normalisée d'un intitulé : minuscules, sans accents, compactée.

    C'est cette forme qui est publiée — jamais la ligne brute, et jamais le
    texte qui entoure la citation."""
    aplati, _ = aplatir_avec_index(intitule)
    return re.sub(r"[^a-z0-9]+", "_", aplati.lower()).strip("_")


def empreinte_intitule(intitule: str) -> str:
    return hashlib.sha256(normaliser_intitule(intitule).encode("utf-8")).hexdigest()


def niveaux_de_lintitule(intitule: str) -> list[str]:
    """Les niveaux que DÉLIMITE cet intitulé — ceux d'avant le qualificatif."""
    aplati, _ = aplatir_avec_index(intitule)
    tete = _SEPARATEUR_QUALIFICATIF.split(aplati, maxsplit=1)[0]
    trouves = [_NIVEAUX[m.group(0).lower()] for m in _MENTION_NIVEAU.finditer(tete)]
    return sorted(set(trouves))


@dataclass(frozen=True)
class Section:
    """Une section délimitée par un intitulé explicite, dans une unité de texte."""

    unite: str
    debut: int
    fin: int
    intitule_normalise: str
    empreinte: str
    niveaux: tuple[str, ...]
    base: str


_LIGNE_VIDE_AVANT = re.compile(r"\n[ \t]*\n[ \t]*\Z")


def _est_isole(aplati: str, debut: int) -> bool:
    """Cette ligne est-elle MISE À PART, ou une ligne parmi d'autres ?

    Un intitulé de section est isolé : une ligne vide le précède, ou il ouvre la
    page. Dans un tableau extrait d'un PDF, les cellules deviennent des lignes
    courtes et consécutives — « terminale » y occupe une ligne entière sans rien
    ouvrir du tout. La forme de la ligne ne les distingue pas ; son isolement,
    si. C'est un critère de mise en page, donc structurel et rejouable, et non
    un jugement sur le sens des mots.

    Le prix est assumé : un intitulé réel collé au paragraphe précédent est
    refusé. Une passe conservatrice préfère ne pas attribuer plutôt que
    d'attribuer à tort — une occurrence non attribuée reste ``UNKNOWN``, une
    occurrence mal attribuée devient une fausse preuve.
    """
    amont = aplati[:debut]
    if not amont.strip():
        # Début d'unité : pour une page, c'est la page qui l'isole ; pour un
        # chunk, c'est la coupe du découpeur gouverné, qui suit la structure de
        # publication. Dans les deux cas la frontière est structurelle, pas
        # typographique.
        return True
    # Une ligne « vide » du corpus porte presque toujours une espace : la
    # tester avec `endswith("\n\n")` la manquait, et le critère paraissait
    # alors vide de sens alors qu'il était seulement mal écrit.
    return _LIGNE_VIDE_AVANT.search(amont) is not None


def sections_explicites(texte: str, unite: str, debut_de_page: bool = False) -> list[Section]:
    """Les sections que délimitent les intitulés explicites de ce texte.

    Une section court de son intitulé jusqu'à l'intitulé suivant, ou jusqu'à la
    fin du texte. Un intitulé qui ne nomme aucun niveau ne délimite rien et est
    ignoré : il ne coupe pas la section précédente, sinon un sous-titre neutre
    priverait d'attribution tout ce qui le suit.
    """
    aplati, origine = aplatir_avec_index(texte)
    brutes: list[tuple[int, int, str]] = []
    for m in _INTITULE.finditer(aplati):
        intitule = m.group("intitule").strip()
        if not niveaux_de_lintitule(intitule):
            continue
        if not _est_isole(aplati, m.start("intitule")):
            continue
        brutes.append((origine[m.start("intitule")], origine[m.end("intitule") - 1] + 1, intitule))

    sections: list[Section] = []
    for indice, (debut, _fin_titre, intitule) in enumerate(brutes):
        fin = brutes[indice + 1][0] if indice + 1 < len(brutes) else len(texte)
        niveaux = tuple(niveaux_de_lintitule(intitule))
        if len(niveaux) > 1:
            base = BASE_MULTI
        elif debut_de_page and indice == 0 and not texte[:debut].strip():
            base = BASE_PAGE
        else:
            base = BASE_SECTION
        sections.append(Section(
            unite=unite, debut=debut, fin=fin,
            intitule_normalise=normaliser_intitule(intitule),
            empreinte=empreinte_intitule(intitule),
            niveaux=niveaux,
            base=base,
        ))
    return sections


@dataclass(frozen=True)
class UniteTexte:
    """Une unité du texte canonique GELÉ — un chunk, ou une page.

    ``rang`` ordonne les unités d'un même document. ``debut_de_page`` dit si
    l'unité commence une page : un intitulé en tête d'unité de page fonde un
    ``EXPLICIT_PAGE_HEADING``, pas un ``EXPLICIT_SECTION_HEADING``.
    """

    identifiant: str
    rang: int
    texte: str
    debut_de_page: bool = False
    page: int | None = None


@dataclass
class OccurrenceAttribuee:
    content_sha256: str
    normalized_reference: str
    disposition: str
    attributed_scope_levels: list[str] = field(default_factory=list)
    attribution_basis: str | None = None
    heading_text_normalized: str | None = None
    heading_digest: str | None = None
    section_unit: str | None = None
    section_start: int | None = None
    section_end: int | None = None
    textual_instances: int = 0
    instances_in_section: int = 0
    conflict_bases: list[str] = field(default_factory=list)

    @property
    def reference_occurrence_id(self) -> str:
        graine = f"{CONTRACT_ID}:{self.content_sha256}:{self.normalized_reference}"
        return hashlib.sha256(graine.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PlageManifeste:
    """Une plage de pages qu'un manifeste GOUVERNÉ attribue à des niveaux.

    Aucun des 112 artefacts transversaux n'en possède aujourd'hui — c'est
    précisément ce que mesure ``MANIFEST_PAGE_RANGE_CANDIDATE=0``. Le chemin
    existe quand même, et il est éprouvé : c'est lui qui rend un CONFLIT
    possible. Deux intitulés emboîtés ne se contredisent pas, ils se précisent ;
    un conflit exige deux mécanismes INDÉPENDANTS qui désignent des niveaux
    disjoints pour la même occurrence textuelle.
    """

    page_debut: int
    page_fin: int
    niveaux: tuple[str, ...]


@dataclass(frozen=True)
class _Instance:
    """Une occurrence TEXTUELLE et les preuves structurelles qui la couvrent."""

    section: Section | None
    preuves: tuple[tuple[str, tuple[str, ...]], ...]


def _preuves_de_linstance(
    section: Section | None,
    page: int | None,
    plages: Sequence[PlageManifeste],
) -> list[tuple[str, tuple[str, ...]]]:
    preuves: list[tuple[str, tuple[str, ...]]] = []
    if section is not None:
        preuves.append((section.base, section.niveaux))
    if page is not None:
        for plage in plages:
            if plage.page_debut <= page <= plage.page_fin:
                preuves.append((BASE_MANIFESTE, tuple(sorted(plage.niveaux))))
    return preuves


def attribuer_document(
    content_sha256: str,
    unites: Sequence[UniteTexte],
    references_attendues: Iterable[str],
    plages_manifeste: Sequence[PlageManifeste] = (),
) -> list[OccurrenceAttribuee]:
    """Attribue, pour un document, chacune de ses références attendues.

    Une section ouverte dans une unité reste ouverte dans les suivantes tant
    qu'aucun intitulé ne la referme : une unité de texte est un découpage
    technique, pas une frontière de section. Ne pas le faire priverait
    d'attribution toute citation qui tombe dans un chunk sans intitulé, alors
    que la structure du document la porte.
    """
    par_reference: dict[str, list[_Instance]] = {r: [] for r in references_attendues}
    section_courante: Section | None = None

    for unite in sorted(unites, key=lambda u: u.rang):
        sections = sections_explicites(unite.texte, unite.identifiant, unite.debut_de_page)
        for citation in citations_localisees(unite.texte):
            reference = citation["official_reference"]
            if reference not in par_reference:
                continue
            debut = citation["start"]
            englobantes = [s for s in sections if s.debut <= debut < s.fin]
            section = englobantes[-1] if englobantes else section_courante
            preuves = _preuves_de_linstance(section, unite.page, plages_manifeste)
            par_reference[reference].append(_Instance(section, tuple(preuves)))
        if sections:
            section_courante = sections[-1]

    resultats: list[OccurrenceAttribuee] = []
    for reference, instances in par_reference.items():
        situees = [i for i in instances if i.preuves]
        occurrence = OccurrenceAttribuee(
            content_sha256=content_sha256,
            normalized_reference=reference,
            disposition=NON_ATTRIBUABLE,
            textual_instances=len(instances),
            instances_in_section=len(situees),
        )
        if not situees:
            resultats.append(occurrence)
            continue

        # Un conflit est une contradiction DANS une même occurrence textuelle,
        # entre deux mécanismes différents. Deux sections successives qui
        # attribuent deux niveaux ne se contredisent pas : le document sert les
        # deux, et c'est un MULTI_SCOPE.
        conflits: set[str] = set()
        for instance in situees:
            for indice, (base_a, niveaux_a) in enumerate(instance.preuves):
                for base_b, niveaux_b in instance.preuves[indice + 1:]:
                    if base_a != base_b and not (set(niveaux_a) & set(niveaux_b)):
                        conflits.update((base_a, base_b))

        premiere = situees[0].section
        niveaux = sorted({n for i in situees for _b, ns in i.preuves for n in ns})
        occurrence.attributed_scope_levels = niveaux
        if premiere is not None:
            occurrence.heading_text_normalized = premiere.intitule_normalise
            occurrence.heading_digest = premiere.empreinte
            occurrence.section_unit = premiere.unite
            occurrence.section_start = premiere.debut
            occurrence.section_end = premiere.fin

        if conflits:
            occurrence.disposition = CONFLIT
            occurrence.conflict_bases = sorted(conflits)
            occurrence.attribution_basis = None
            occurrence.attributed_scope_levels = []
        elif len(niveaux) == 1:
            bases = sorted({b for i in situees for b, _ns in i.preuves})
            occurrence.disposition = ATTRIBUE
            occurrence.attribution_basis = bases[0] if len(bases) == 1 else BASE_SECTION
        else:
            occurrence.disposition = MULTI_SCOPE
            occurrence.attribution_basis = BASE_MULTI
        resultats.append(occurrence)
    return resultats


__all__ = [
    "ATTRIBUE", "BASES_AUTORISEES", "BASES_INTERDITES", "CONFLIT", "CONTRACT_ID",
    "DISPOSITIONS", "MULTI_SCOPE", "NON_ATTRIBUABLE", "OccurrenceAttribuee",
    "PlageManifeste", "Section", "UniteTexte", "attribuer_document", "empreinte_intitule",
    "niveaux_de_lintitule", "normaliser_intitule", "sections_explicites",
]
