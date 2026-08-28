#!/usr/bin/env python3
"""Classer le niveau d'un document par cascade de preuves citables.

═══ UN CLASSEMENT QUI DEVINE EST UNE INVENTION ════════════════════════════

Chaque affectation produite porte `classification_evidence` : le palier qui a
décidé, la source exacte, et l'extrait littéral qui l'a emporté. C'est
vérifiable a posteriori, comme une empreinte — et c'est ce qui distingue une
dérivation d'une devinette.

Un document qu'aucun palier ne résout reste **non classé** et sort du périmètre
en COVERAGE_GAP. On ne devine jamais pour combler.

═══ LA CASCADE, DU PLUS FORT AU PLUS FAIBLE ══════════════════════════════

P1  texte du document      — un programme énonce son niveau en première page
P2  url_source             — les URL Éduscol encodent niveau et matière
P3  référence B.O.         — un B.O. correspond à un programme, donc à un niveau
P4  canonical_destination  — LYCEE / COLLEGE
P5  titre

Les paliers ne s'excluent pas : ils se combinent. Plusieurs paliers concordants
renforcent la confiance ; un palier contredit par un autre marque le document
`CONFLIT`, qui est un examen requis et non une décision.

═══ MULTI-NIVEAUX N'EST PAS UN ÉCHEC ═════════════════════════════════════

Un document qui couvre réellement plusieurs niveaux reçoit PLUSIEURS niveaux,
et le modèle en fait plusieurs placements d'un même artefact. Le forcer sur un
niveau unique serait perdre ce qu'il dit de lui-même.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

NIVEAUX = ("sixieme", "cinquieme", "quatrieme", "troisieme",
           "cycle4", "seconde", "premiere", "terminale")


def sans_accent(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte)
                   if unicodedata.category(c) != "Mn").lower()


@dataclass
class Preuve:
    palier: str
    source: str
    extrait: str
    niveaux: set[str] = field(default_factory=set)


#: Motifs de niveau, appliqués à du texte désaccentué et normalisé en espaces.
#: Chaque motif doit être ancré sur une formulation que l'Éducation nationale
#: emploie réellement — jamais sur une abréviation ambiguë comme « 1re » seule.
_MOTIFS = (
    ("terminale", re.compile(
        r"(classe terminale|classes? de terminale|en terminale\b|"
        r"terminale generale|terminale technologique|cycle terminal[^e])")),
    ("premiere", re.compile(
        r"(classes? de premiere|en premiere\b|premiere generale|"
        r"premiere technologique)")),
    ("seconde", re.compile(
        r"(classes? de seconde|en seconde\b|seconde generale et technologique|"
        r"seconde professionnelle)")),
    ("cycle4", re.compile(
        r"(cycle 4|cycle des approfondissements|classes? de cinquieme[^)]*"
        r"quatrieme|5e-4e-3e)")),
    ("troisieme", re.compile(r"(classes? de troisieme|en troisieme\b|\b3e\b)")),
    ("quatrieme", re.compile(r"(classes? de quatrieme|en quatrieme\b|\b4e\b)")),
    ("cinquieme", re.compile(r"(classes? de cinquieme|en cinquieme\b|\b5e\b)")),
    ("sixieme", re.compile(r"(classes? de sixieme|en sixieme\b|\b6e\b|cycle 3)")),
)


#: Le programme de référence d'un élève de 5e, 4e ou 3e EST le programme de
#: cycle 4 : les programmes de collège sont publiés par cycle, jamais par année.
#: Un document qui dit « en 3e » ne contredit donc pas « cycle 4 » — il le
#: précise. Mesuré : 142 des 214 désaccords de la première passe étaient
#: exactement cela, et c'étaient de faux désaccords.
_ANNEE_VERS_CYCLE = {"troisieme": "cycle4", "quatrieme": "cycle4",
                     "cinquieme": "cycle4"}


def _niveaux_du_texte(texte: str) -> list[tuple[str, str, int]]:
    """Retourner (niveau, extrait, occurrences) pour chaque motif rencontré.

    Le nombre d'occurrences importe : un document de première qui cite « la
    notion de marché étudiée en classe de seconde » mentionne `seconde` une
    fois et `premiere` plusieurs. Prendre la première correspondance dans un
    ordre figé faisait gagner le niveau cité en prérequis.
    """
    plat = " ".join(sans_accent(texte).split())
    trouves: list[tuple[str, str, int]] = []
    for niveau, motif in _MOTIFS:
        occurrences = list(motif.finditer(plat))
        if occurrences:
            m = occurrences[0]
            debut = max(0, m.start() - 45)
            trouves.append((_ANNEE_VERS_CYCLE.get(niveau, niveau),
                            plat[debut:m.end() + 45], len(occurrences)))
    # Fusionner les niveaux repliés sur le même cycle.
    fusionne: dict[str, tuple[str, int]] = {}
    for niveau, extrait, n in trouves:
        if niveau in fusionne:
            fusionne[niveau] = (fusionne[niveau][0], fusionne[niveau][1] + n)
        else:
            fusionne[niveau] = (extrait, n)
    return [(niv, ext, n) for niv, (ext, n) in fusionne.items()]


def _dominants(trouves: list[tuple[str, str, int]]) -> set[str]:
    """Ne garder que les niveaux dominants — un prérequis cité une fois cède."""
    if not trouves:
        return set()
    maxi = max(n for _, _, n in trouves)
    seuil = max(1, maxi // 3)
    return {niv for niv, _, n in trouves if n >= seuil}


#: Un document ne se lit pas comme un sac de mots. Il DÉCLARE son niveau — dans
#: son titre, son intitulé de programme, sa phrase d'ouverture — et il en
#: MENTIONNE d'autres, en prérequis, en rappel, en renvoi au cycle précédent.
#:
#: L'appariement de motifs confond les deux, et c'est exactement ce que le
#: diagnostic avait montré : « la notion de marché étudiée en classe de seconde »
#: dans un document de première faisait gagner `seconde`. 81,8 % n'était pas la
#: précision d'une lecture, c'était celle d'une expression régulière.
#:
#: Ces deux grilles encodent la distinction. Un contexte de RENVOI annule le
#: niveau qu'il cite ; un contexte de DÉCLARATION le renforce.

#: Ce qui précède un niveau et en fait un simple renvoi.
_RENVOI = re.compile(
    r"(vu[e]?s? en|etudie[e]?s? en|abord[e]?[e]?s? en|acquis (de|du)|"
    r"prerequis|rappel|reinvestir|consolider|deja (vu|etudie|rencontre)|"
    r"au cycle precedent|des la|depuis la|en amont|anterieur|"
    r"comme en|ainsi qu[e'] en|de meme qu[e'] en|par rapport a la|"
    r"contrairement a la|apres la|avant la|issu[e]?s? de|venant de|"
    r"a l[a'] issue de|preparation a|vers la)\s*$")

#: Ce qui précède un niveau et en fait une déclaration de portée.
_DECLARATION = re.compile(
    r"(programme[s]? (de |d[e']|pour )?(l[a']?)?(enseignement)?[^.]{0,40}|"
    r"specialite[^.]{0,40}|option[^.]{0,40}|enseignement[^.]{0,40}|"
    r"attendus de fin d[e']annee[^.]{0,30}|reperes[^.]{0,30}|"
    r"ressources? d[e']accompagnement[^.]{0,40}|"
    r"a destination des (eleves|professeurs)[^.]{0,30}|"
    r"en classe de|classe de|au niveau|niveau)\s*$")


def p1_lecture_du_document(chemin: Path | None) -> Preuve | None:
    """Palier 1 — LIRE la première page : ce que le document est, non ce qu'il cite.

    Chaque mention de niveau est pesée par son contexte immédiat et sa position.
    Une mention en tête de page, précédée d'un mot de portée (« programme de »,
    « spécialité »), déclare. Une mention précédée d'un mot de renvoi
    (« vu en », « prérequis ») ne déclare rien et se voit annulée.

    Un document dont AUCUNE mention n'est déclarative ne reçoit pas de décision :
    il n'a pas dit de quel niveau il est, et on ne le devine pas.
    """
    if chemin is None or not chemin.is_file():
        return None
    try:
        from pypdf import PdfReader
        pages = PdfReader(str(chemin)).pages[:2]
        texte = "\n".join((p.extract_text() or "") for p in pages)
    except Exception:                                        # noqa: BLE001
        return None

    plat = " ".join(sans_accent(texte).split())
    if not plat:
        return None

    scores: dict[str, float] = {}
    extraits: dict[str, str] = {}
    for niveau_brut, motif in _MOTIFS:
        niveau = _ANNEE_VERS_CYCLE.get(niveau_brut, niveau_brut)
        for m in motif.finditer(plat):
            avant = plat[max(0, m.start() - 60):m.start()]
            if _RENVOI.search(avant):
                continue                    # citation, pas déclaration
            # Le poids décroît avec la distance au début : un document se
            # présente en tête, il cite plus loin.
            position = m.start()
            poids = 3.0 if position < 300 else (1.5 if position < 1200 else 0.6)
            if _DECLARATION.search(avant):
                poids *= 2.0
            scores[niveau] = scores.get(niveau, 0.0) + poids
            extraits.setdefault(
                niveau, plat[max(0, position - 70):m.end() + 70])

    if not scores:
        return None
    maxi = max(scores.values())
    # Un niveau retenu doit peser au moins la moitié du dominant : un document
    # réellement multi-niveaux en garde plusieurs, un document qui cite une fois
    # un autre niveau n'en garde qu'un.
    retenus = {niv for niv, s in scores.items() if s >= maxi * 0.5}
    dominant = max(scores, key=lambda k: scores[k])
    return Preuve("P1_lecture_document",
                  f"{chemin.name} (pages 1-2, lecture pondérée)",
                  extraits[dominant], retenus)


def p1_texte_du_document(chemin: Path | None) -> Preuve | None:
    """Palier 1 — ce que le document dit de lui-même, en première page."""
    if chemin is None or not chemin.is_file():
        return None
    try:
        from pypdf import PdfReader
        pages = PdfReader(str(chemin)).pages[:4]
        texte = "\n".join((p.extract_text() or "") for p in pages)
    except Exception:                                        # noqa: BLE001
        return None
    trouves = _niveaux_du_texte(texte)
    if not trouves:
        return None
    return Preuve("P1_texte_document", f"{chemin.name} (pages 1-4)",
                  trouves[0][1], _dominants(trouves))


def p2_url_source(url: str) -> Preuve | None:
    """Palier 2 — la structure de l'URL Éduscol."""
    if not url:
        return None
    trouves = _niveaux_du_texte(url.replace("-", " ").replace("/", " "))
    if not trouves:
        return None
    return Preuve("P2_url_source", url, trouves[0][1], _dominants(trouves))


def p3_reference_bo(titre: str, table_bo: dict[str, set[str]]) -> Preuve | None:
    """Palier 3 — la référence de B.O., via une table dérivée du corpus."""
    plat = sans_accent(titre)
    m = re.search(r"bo\s*(?:special\s*)?n\s*°?\s*(\d+)\s*du\s*(\d+)\s*"
                  r"([a-z]+)\s*(\d{4})", plat)
    if not m:
        return None
    cle = f"{m.group(1)}|{m.group(4)}"
    niveaux = table_bo.get(cle)
    if not niveaux:
        return None
    return Preuve("P3_reference_bo", f"B.O. n°{m.group(1)} de {m.group(4)}",
                  m.group(0), set(niveaux))


def p4_destination(chemin: str) -> Preuve | None:
    """Palier 4 — LYCEE / COLLEGE dans la destination canonique."""
    trouves = _niveaux_du_texte(chemin.replace("_", " ").replace("/", " "))
    if not trouves:
        return None
    return Preuve("P4_destination", chemin, trouves[0][1], _dominants(trouves))


def p5_titre(titre: str) -> Preuve | None:
    trouves = _niveaux_du_texte(titre)
    if not trouves:
        return None
    return Preuve("P5_titre", titre, trouves[0][1], _dominants(trouves))


def _table_bo(catalogue: list[dict[str, str]],
              niveaux_connus: dict[str, str]) -> dict[str, set[str]]:
    """Dériver « numéro de B.O. -> niveaux » du corpus lui-même.

    Ne retient une correspondance que si TOUS les documents citant ce B.O. et
    de niveau connu s'accordent. Un B.O. ambigu ne devient pas un palier.
    """
    brut: dict[str, set[str]] = {}
    for ligne in catalogue:
        niveau = niveaux_connus.get(ligne["sha256"])
        if not niveau:
            continue
        m = re.search(r"bo\s*(?:special\s*)?n\s*°?\s*(\d+)\s*du\s*\d+\s*"
                      r"[a-z]+\s*(\d{4})", sans_accent(ligne["titre"]))
        if m:
            brut.setdefault(f"{m.group(1)}|{m.group(2)}", set()).add(niveau)
    return {cle: v for cle, v in brut.items() if len(v) == 1}


def classer(ligne: dict[str, str], chemin: Path | None,
            table_bo: dict[str, set[str]], *,
            avec_p1: bool = True) -> dict[str, object]:
    """Appliquer la cascade et rendre la décision AVEC son évidence."""
    # L'ordre est MESURÉ, non supposé : sur les 1 505 niveaux connus, l'URL
    # source décidait juste à 88,5 % contre 76,7 % pour le texte du document.
    # Le texte d'une ressource pédagogique cite des niveaux de prérequis ;
    # l'URL Éduscol, elle, exprime le placement canonique.
    preuves: list[Preuve] = [
        p2_url_source(ligne.get("url_source", "")),
        p3_reference_bo(ligne.get("titre", ""), table_bo),
    ]
    if avec_p1:
        preuves.append(p1_lecture_du_document(chemin))
    preuves.extend((
        p4_destination(ligne.get("chemin_par_scope", "")),
        p5_titre(ligne.get("titre", "")),
    ))
    retenues = [p for p in preuves if p is not None]
    if not retenues:
        return {"niveaux": [], "statut": "NON_CLASSE", "evidence": []}

    # Le palier le plus fort décide ; les suivants confirment ou contredisent.
    decisive = retenues[0]
    concordants = [p for p in retenues[1:] if p.niveaux & decisive.niveaux]
    contradictoires = [p for p in retenues[1:] if not (p.niveaux & decisive.niveaux)]

    statut = "CLASSE"
    if contradictoires and not concordants:
        statut = "CONFLIT"
    elif len(decisive.niveaux) > 1:
        statut = "MULTI_NIVEAUX"

    return {
        "niveaux": sorted(decisive.niveaux),
        "statut": statut,
        "palier_decisif": decisive.palier,
        "confirmations": [p.palier for p in concordants],
        "contradictions": [
            {"palier": p.palier, "niveaux": sorted(p.niveaux), "extrait": p.extrait[:160]}
            for p in contradictoires],
        "evidence": [{"palier": p.palier, "source": p.source[:200],
                      "extrait": p.extrait[:200], "niveaux": sorted(p.niveaux)}
                     for p in retenues],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--sortie", type=Path, required=True)
    parser.add_argument("--mode", choices=["validation", "classement"], required=True,
                        help="validation : rejouer à l'aveugle sur les niveaux connus ; "
                             "classement : classer les documents non conformes")
    parser.add_argument("--sans-p1", action="store_true",
                        help="désactiver la lecture des PDF (mesure du gain de P1)")
    args = parser.parse_args(argv)

    racine = args.corpus_dir
    CORRESP = {"3e": "troisieme", "4e": "quatrieme", "5e": "cinquieme",
               "cycle-4": "cycle4", "seconde": "seconde",
               "premiere": "premiere", "terminale": "terminale"}
    with open(racine / "00_ADMIN/eduscol_affectations.tsv", encoding="utf-8") as flux:
        affectations = list(csv.DictReader(flux, delimiter="\t"))
    with open(racine / "00_INDEX_PROVENANCE/catalogue-par-scope.tsv",
              encoding="utf-8") as flux:
        catalogue = list(csv.DictReader(flux, delimiter="\t"))
    par_sha = {c["sha256"]: c for c in catalogue}

    niveaux_connus = {a["sha256"]: CORRESP[a["level"]]
                      for a in affectations if a["level"] in CORRESP}
    table_bo = _table_bo(catalogue, niveaux_connus)
    print(f"  table B.O. dérivée du corpus : {len(table_bo)} correspondances", flush=True)

    pdfs = {hashlib.sha256(p.read_bytes()).hexdigest(): p
            for p in (racine / "01_EDUSCOL_OFFICIEL").rglob("*.pdf")}

    if args.mode == "validation":
        cibles = sorted(niveaux_connus)
    else:
        cibles = sorted({a["sha256"] for a in affectations
                         if a["level"] not in CORRESP} - set(niveaux_connus))
    print(f"  documents à traiter : {len(cibles)}", flush=True)

    resultats = []
    for n, sha in enumerate(cibles, 1):
        ligne = par_sha.get(sha)
        if ligne is None:
            continue
        verdict = classer(ligne, pdfs.get(sha), table_bo, avec_p1=not args.sans_p1)
        verdict["sha256"] = sha
        verdict["titre"] = ligne["titre"][:120]
        if args.mode == "validation":
            verdict["niveau_reel"] = niveaux_connus[sha]
            verdict["accord"] = niveaux_connus[sha] in verdict["niveaux"]
        resultats.append(verdict)
        if n % 200 == 0:
            print(f"    {n}/{len(cibles)}", flush=True)

    args.sortie.write_text(
        json.dumps({"mode": args.mode, "count": len(resultats),
                    "documents": resultats}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    if args.mode == "validation":
        accords = [r for r in resultats if r["accord"]]
        print("\n  ── VALIDATION À L'AVEUGLE ──")
        print(f"  documents        : {len(resultats)}")
        print(f"  ACCORD           : {len(accords)} "
              f"({100 * len(accords) / max(1, len(resultats)):.1f} %)")
        par_palier: dict[str, list[bool]] = {}
        for r in resultats:
            par_palier.setdefault(r.get("palier_decisif", "AUCUN"), []).append(r["accord"])
        print("  ── par palier décisif ──")
        for palier in sorted(par_palier):
            v = par_palier[palier]
            print(f"    {palier:22} {len(v):5} docs   accord "
                  f"{100 * sum(v) / len(v):5.1f} %")
        non_classes = [r for r in resultats if r["statut"] == "NON_CLASSE"]
        print(f"  NON CLASSÉS      : {len(non_classes)}")
    else:
        statuts: dict[str, int] = {}
        for r in resultats:
            statuts[r["statut"]] = statuts.get(r["statut"], 0) + 1
        print("\n  ── CLASSEMENT ──")
        for s, c in sorted(statuts.items()):
            print(f"    {s:16} {c:5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
