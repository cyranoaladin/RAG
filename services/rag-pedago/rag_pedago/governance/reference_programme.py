"""Parseur FERMÉ d'identifiants de programme officiel.

Il reconnaît des formes explicitement définies, et rien d'autre. Une forme
inconnue rend zéro résultat : elle ne devient jamais un identifiant approximatif.

Pourquoi un parseur plutôt qu'une recherche. Une citation réglementaire
explicite dans un document — « Bulletin officiel spécial n° 1 du 22 janvier
2019 » — n'est pas une inférence sémantique : le document nomme le texte qu'il
met en œuvre. C'est une preuve. En revanche, la ressemblance de vocabulaire, le
nom du chapitre, le niveau supposé, l'année de publication, le slug ou le
répertoire n'en sont pas, et ce module n'en lit aucun.

Le défaut qu'il existe pour empêcher : ``2026-2027`` accepté comme version de
programme. Une année scolaire n'est pas une référence réglementaire, et la
compter avait failli déclarer 138 documents incompatibles avec le programme en
vigueur alors que rien n'établissait lequel ils servent.
"""

from __future__ import annotations

import re
import unicodedata

PARSER_ID = "NEXUS-OFFICIAL-PROGRAM-REFERENCE-PARSER-V1"

#: La forme CANONIQUE d'un identifiant, telle que les profils d'ingestion
#: l'emploient. La date complète est exigée : ``BOEN_special_1`` ne désigne
#: aucun texte, et ``BOEN_`` encore moins.
FORME_CANONIQUE = re.compile(
    r"\ABOEN(?:_special)?_\d{1,3}_\d{4}-\d{2}-\d{2}(?:_[A-Za-z0-9_]+)?\Z"
)

_MOIS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12,
}

#: « Bulletin officiel spécial n° 1 du 22 janvier 2019 », « BO spécial n°8 du
#: 25 juillet 2019 », « B.O. n° 14 du 2 avril 2026 ». Les variantes de
#: ponctuation et d'espacement sont absorbées ; la STRUCTURE ne l'est pas.
_CITATION = re.compile(
    r"\b(?:bulletin\s+officiel|b\.?\s*o\.?\s*e?\.?\s*n?\.?|bo)\b"
    r"(?P<special>\s+special)?"
    r"\s*n\s*[°ºo]?\s*(?P<numero>\d{1,3})"
    r"\s*du\s+(?P<jour>\d{1,2})\s*(?:er)?\s*"
    r"(?P<mois>janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)"
    r"\s+(?P<annee>\d{4})",
    re.IGNORECASE,
)

#: La même chose en date numérique : « BO spécial n° 1 du 22-1-2019 ».
_CITATION_NUMERIQUE = re.compile(
    r"\b(?:bulletin\s+officiel|b\.?\s*o\.?\s*e?\.?\s*n?\.?|bo)\b"
    r"(?P<special>\s+special)?"
    r"\s*n\s*[°ºo]?\s*(?P<numero>\d{1,3})"
    r"\s*du\s+(?P<jour>\d{1,2})[-/](?P<mois>\d{1,2})[-/](?P<annee>\d{4})",
    re.IGNORECASE,
)


def _sans_accents(texte: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn"
    )


def est_reference_canonique(valeur: object) -> bool:
    """Un identifiant canonique, ou non. Sans indulgence sur la forme."""
    return isinstance(valeur, str) and bool(FORME_CANONIQUE.match(valeur))


def references_canoniques(valeur: object) -> list[str]:
    """Les identifiants canoniques que porte cette valeur — zéro ou plusieurs.

    Une LISTE est une cardinalité, pas un autre type : chacun de ses éléments
    est validé indépendamment. Exiger une chaîne rejetait des liaisons
    parfaitement établies — un faux négatif, moins visible qu'un faux positif
    et tout aussi faux."""
    if isinstance(valeur, str):
        return [valeur] if est_reference_canonique(valeur) else []
    if isinstance(valeur, (list, tuple)):
        return [v for v in valeur if est_reference_canonique(v)]
    return []


def citations_officielles(texte: str) -> list[str]:
    """Les citations réglementaires EXPLICITES d'un texte, normalisées.

    Rend des identifiants canoniques, dédupliqués, dans l'ordre de première
    apparition. Une citation dont la structure n'est pas reconnue n'est pas
    devinée : elle est simplement absente du résultat.
    """
    aplati = _sans_accents(texte)
    trouvees: list[str] = []
    for motif, numerique in ((_CITATION, False), (_CITATION_NUMERIQUE, True)):
        for m in motif.finditer(aplati):
            mois = int(m.group("mois")) if numerique else _MOIS[m.group("mois").lower()]
            if not 1 <= mois <= 12:
                continue
            jour = int(m.group("jour"))
            if not 1 <= jour <= 31:
                continue
            prefixe = "BOEN_special" if m.group("special") else "BOEN"
            identifiant = (
                f"{prefixe}_{int(m.group('numero'))}_"
                f"{int(m.group('annee')):04d}-{mois:02d}-{jour:02d}"
            )
            if est_reference_canonique(identifiant) and identifiant not in trouvees:
                trouvees.append(identifiant)
    return trouvees


def resoudre(reference: str, autorites: set[str]) -> tuple[str, list[str]]:
    """Résout une citation vers UNE entrée de l'autorité de programme courant.

    Rend ``(verdict, candidats)`` où le verdict vaut ``RESOLVED``,
    ``AMBIGUOUS`` ou ``UNKNOWN``.

    L'ambiguïté est réelle : ``BOEN_special_8_2019-07-25`` est un préfixe de
    ``BOEN_special_8_2019-07-25_MENE1921266A_MENE2208320A``. Choisir le plus
    court ou le premier trouvé ferait décider au parseur ce qui relève de
    l'autorité — et une citation qui désigne deux textes n'en désigne aucun.
    """
    if reference in autorites:
        return "RESOLVED", [reference]
    candidats = sorted(a for a in autorites if a.startswith(reference + "_"))
    if len(candidats) == 1:
        return "RESOLVED", candidats
    if len(candidats) > 1:
        return "AMBIGUOUS", candidats
    return "UNKNOWN", []


__all__ = [
    "FORME_CANONIQUE",
    "PARSER_ID",
    "citations_officielles",
    "est_reference_canonique",
    "references_canoniques",
    "resoudre",
]
