#!/usr/bin/env python3
"""Rescellement outillé des autorités de release — LOT 0.

Le rescellement était un acte manuel d'escalade : toute correction touchant une
des autorités liées par empreinte s'arrêtait, et la Phase 1 serait devenue une
file d'attente de demandes d'autorisation. Cet outil le rend routinier, tracé et
refusable.

    --check              n'écrit rien ; liste les autorités dont l'empreinte a dérivé
    --reseal --motif …   rescelle, en EXIGEANT un motif par autorité qui change

Ce qu'il refuse, et c'est le point :
  * une autorité qui dérive sans motif ;
  * un motif vide, trop court, ou générique ;
  * une autorité inconnue du jeu scellé ;
  * un chemin hors du dépôt.

Un outil de gouvernance qui ne peut pas refuser n'est pas une garde.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

#: `AGENTS.md` exige de dériver la racine de l'emplacement des fichiers, AVEC
#: override par variable d'environnement. La dérivation seule ne suffit pas :
#: l'outil vit dans un worktree dédié et doit pouvoir resceller la release d'un
#: autre plan de travail. Sans cet override il ne rescelle que sa propre copie.
RACINE = Path(
    os.environ.get("NEXUS_REPO_ROOT") or Path(__file__).resolve().parents[3]
).resolve()
GATE = RACINE / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate"
BINDINGS = GATE / "authority_bindings.json"
AGREGAT = GATE / "production-profile-gate.release.json"
SUJETS = GATE / "subjects"
REGISTRE = RACINE / "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json"
HISTOIRE = GATE / "reseal_history.jsonl"
#: Seconde chaîne de scellement, découverte en exécutant la première : la
#: provenance de production des placements suit 36 blobs d'entrée, et le registre
#: de release en fait partie. Les deux chaînes se référencent.
PROVENANCE = RACINE / "docs/reports/release_scope_placement_provenance_20260825.json"

#: Les NEUF chaînes d'attestation du dépôt. Une chaîne est un fichier qui enregistre
#: l'empreinte d'autres fichiers ET qui est vérifié par au moins un test — un fichier
#: d'empreintes que rien ne vérifie est de la documentation, pas une chaîne.
#:
#: 76 fichiers attestés, dont 34 par plusieurs chaînes. `ingestion_manifest.yml` en a
#: cinq. Sept arêtes chaîne→chaîne, aucun cycle : un ordre topologique existe.
#:
#: Un rescellement partiel a l'apparence d'un rescellement ; c'est ce qui le rend pire
#: que son absence. L'outil ÉNUMÈRE donc toutes les attestations d'un fichier avant
#: d'écrire, et refuse dès qu'une seule est hors de sa portée.
CHAINES = (
    "docs/reports/final_production_profile_matrix_20260825.json",
    "docs/reports/proposed_production_profile_matrix_20260823.json",
    "docs/reports/release_scope_placement_provenance_20260825.json",
    "docs/reports/production_profile_primary_evidence_20260825.json",
    "docs/reports/evidence-index/content_ledger_20260814.jsonl",
    "docs/reports/verified_production_profiles_20260825.json",
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/production-profile-gate.release.json",
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/authority_bindings.json",
    #: DIXIÈME chaîne, omise à la première rédaction : le registre épingle
    #: `expected_manifest_sha256` de l'agrégat. L'omettre faisait répondre
    #: « aucune chaîne ne porte ce fichier » pour l'agrégat, donc lever la garde
    #: qui refuse un rescellement hors portée. Sous-déclarer fait ÉCRIRE.
    "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json",
    "docs/reports/master_go_live_state_20260815.json",
)
#: Les chaînes que cet outil sait traiter — c'est-à-dire celles que `resceller`
#: réécrit lui-même. Toute autre le fait refuser. Ce jeu doit rester égal à ce que
#: le code écrit : une chaîne réécrite mais hors portée bloque tout, une chaîne
#: réécrite et absente des deux jeux passe en silence.
PORTEE = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/authority_bindings.json",
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/production-profile-gate.release.json",
    "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json",
)

#: Toute chaîne de caractères citée qui ressemble à un chemin de fichier suivi.
#: Volontairement large : le filtre est l'existence réelle du fichier sous la
#: racine, pas la forme du texte. Sur-déclarer fait consulter une chaîne de trop ;
#: sous-déclarer fait écrire sans consulter. Les deux erreurs ne se valent pas.
_CHEMIN = re.compile(
    r'"([A-Za-z0-9_][A-Za-z0-9_./-]*'
    r'\.(?:py|yml|yaml|json|jsonl|txt|md|sh|sql))"'
)


def _chemins_attestes(chaine: str, texte: str) -> set[str]:
    """Chemins cités par une chaîne, ramenés à la racine du dépôt.

    Une chaîne cite ses cibles soit relativement à la racine, soit relativement à
    son PROPRE répertoire — l'agrégat de release fait le second pour ses onze
    sujets. Ne reconnaître que la première forme faisait déclarer ces onze
    fichiers portés par personne.
    """
    base = (RACINE / chaine).parent
    trouves: set[str] = set()
    for brut in set(_CHEMIN.findall(texte)):
        rel = Path(brut)
        if rel.is_absolute() or ".." in rel.parts:
            continue
        for candidat in ((RACINE / rel), (base / rel)):
            resolu = candidat.resolve()
            if resolu.is_relative_to(RACINE) and resolu.is_file():
                trouves.add(str(resolu.relative_to(RACINE)))
    return trouves

#: Un motif générique n'explique rien et se lit comme une explication.
MOTIFS_REFUSES = re.compile(
    r"^\s*(?:fix|update|maj|correctif|wip|tmp|temp|divers|misc|rescellement|reseal|"
    r"mise\s+à\s+jour|changement|modification|\.+|-+)\s*$",
    re.IGNORECASE,
)
MOTIF_LONGUEUR_MIN = 25


class Refus(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"REFUS : {message}")


def _sha256(chemin: Path) -> str:
    h = hashlib.sha256()
    with chemin.open("rb") as fh:
        for bloc in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def _lire(chemin: Path) -> dict:
    if not chemin.is_file():
        raise Refus(f"fichier absent : {chemin.relative_to(RACINE)}")
    return json.loads(chemin.read_text(encoding="utf-8"))


def _ecrire(chemin: Path, donnees: dict) -> None:
    chemin.write_text(json.dumps(donnees, indent=2, ensure_ascii=False,
                                 sort_keys=True) + "\n", encoding="utf-8")


def deriver() -> dict[str, tuple[str, str, str]]:
    """Retourner {autorité: (chemin, empreinte_scellée, empreinte_réelle)} pour ce qui a dérivé."""
    liaisons = _lire(BINDINGS)["bindings"]
    derives: dict[str, tuple[str, str, str]] = {}
    for nom, liaison in sorted(liaisons.items()):
        rel = Path(liaison["path"])
        if rel.is_absolute():
            raise Refus(f"chemin absolu dans la liaison {nom}")
        cible = (RACINE / rel).resolve()
        if not cible.is_relative_to(RACINE):
            raise Refus(f"chemin hors du dépôt pour {nom}")
        if not cible.is_file():
            raise Refus(f"autorité introuvable : {rel}")
        reel = _sha256(cible)
        if reel != liaison["file_sha256"]:
            derives[nom] = (str(rel), liaison["file_sha256"], reel)
    return derives


def attestations_de(chemins: list[str]) -> dict[str, list[str]]:
    """Retourner {chemin: [chaînes qui l'attestent]} — R1 appliqué aux sceaux.

    Avant de toucher un fichier, on recense TOUTES les attestations qui parlent de lui.
    Ne pas le faire produit un rescellement partiel, qui a l'apparence d'un rescellement.
    """
    vises = set(chemins)
    porte: dict[str, list[str]] = {c: [] for c in vises}
    for chaine in CHAINES:
        f = RACINE / chaine
        if not f.is_file():
            continue
        try:
            txt = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for atteste in _chemins_attestes(chaine, txt):
            if atteste in vises and atteste != chaine:
                porte[atteste].append(chaine)
    return {k: sorted(v) for k, v in porte.items() if v}


def chaine_provenance_touchee(fichiers: list[str]) -> list[str]:
    """Retourner les blobs suivis par la provenance de placement que l'on s'apprête à réécrire.

    La provenance n'est pas un jeu d'empreintes que l'on rapièce : elle porte un
    `source_commit_sha` et un `release_scope_placement_digest`. La corriger à la main
    la falsifierait ; la régénérer est une ré-attestation de la production, décision
    de gouvernance. L'outil la DÉTECTE et refuse — il n'agit pas à sa place.
    """
    if not PROVENANCE.is_file():
        return []
    suivis = set(json.loads(PROVENANCE.read_text(encoding="utf-8")).get("input_blob_sha256", {}))
    return sorted(set(fichiers) & suivis)


def valider_motifs(derives: dict, motifs: dict[str, str]) -> None:
    inconnus = sorted(set(motifs) - set(derives))
    if inconnus:
        raise Refus(f"motif fourni pour une autorité qui n'a pas dérivé : {', '.join(inconnus)}")
    manquants = sorted(set(derives) - set(motifs))
    if manquants:
        raise Refus(
            "autorité(s) dérivée(s) sans motif : " + ", ".join(manquants)
            + "\n        Un rescellement sans motif écrit ne laisse aucune trace de sa raison."
        )
    for nom, texte in sorted(motifs.items()):
        t = (texte or "").strip()
        if not t:
            raise Refus(f"motif vide pour {nom}")
        if MOTIFS_REFUSES.match(t):
            raise Refus(f"motif générique pour {nom} : « {t} » n'explique rien")
        if len(t) < MOTIF_LONGUEUR_MIN:
            raise Refus(
                f"motif trop court pour {nom} ({len(t)} caractères, minimum {MOTIF_LONGUEUR_MIN})"
            )


def sauvegarder_avant_ecriture(cibles: list[Path]) -> tuple[Path, dict[str, str]]:
    """Copier chaque fichier qu'on s'apprête à réécrire, et rendre ses empreintes.

    Le 2026-08-30, cet outil a réécrit onze manifests de sujet qui n'étaient ni
    commités ni sauvegardés. Ils n'ont été retrouvés que parce qu'un instantané
    forensique pris pour une tout autre raison les portait. Une ligne de procédure
    dépend de qui l'exécute ; une copie faite par l'outil ne dépend de personne.

    Lève si la copie échoue : un rescellement dont la sauvegarde échoue n'a pas lieu.
    """
    moment = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    racine_copie = GATE / f"sauvegarde-{moment}"
    empreintes: dict[str, str] = {}
    for cible in cibles:
        if not cible.is_file():
            continue
        rel = cible.relative_to(RACINE)
        destination = racine_copie / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cible, destination)
        empreintes[str(rel)] = _sha256(cible)
    return racine_copie, empreintes


def resceller(derives: dict, motifs: dict[str, str], preuve: str | None) -> list[str]:
    touches: list[str] = []

    # Copier AVANT d'écrire. Si la copie échoue, rien ne s'écrit.
    a_reecrire = [BINDINGS, AGREGAT, REGISTRE, *sorted(SUJETS.glob("*.release.json"))]
    try:
        racine_copie, empreintes_avant = sauvegarder_avant_ecriture(a_reecrire)
    except OSError as exc:
        raise Refus(
            "la sauvegarde préalable a échoué, aucun octet n'a été écrit : "
            f"{exc}\n        Un rescellement qui ne peut pas copier ce qu'il "
            "va écraser n'a pas lieu."
        ) from exc

    # 1. les liaisons
    liaisons_doc = _lire(BINDINGS)
    for nom, (_, _, reel) in derives.items():
        liaison = liaisons_doc["bindings"][nom]
        liaison["file_sha256"] = reel
        if liaison.get("authority_kind") == "FILE_SHA256":
            liaison["authority_sha256"] = reel
    _ecrire(BINDINGS, liaisons_doc)
    touches.append(str(BINDINGS.relative_to(RACINE)))

    nouvelles = {n: liaisons_doc["bindings"][n]["authority_sha256"] for n in derives}

    # 2. les sujets, dont le bloc `authorities` doit égaler celui de l'agrégat
    for sujet in sorted(SUJETS.glob("*.release.json")):
        doc = _lire(sujet)
        if not isinstance(doc.get("authorities"), dict):
            continue
        doc["authorities"].update(nouvelles)
        _ecrire(sujet, doc)
        touches.append(str(sujet.relative_to(RACINE)))

    # 3. l'agrégat : ses autorités, puis les empreintes de ses sujets
    agg = _lire(AGREGAT)
    agg["authorities"].update(nouvelles)
    for entree in agg.get("subjects", []):
        chemin = GATE / entree["path"]
        if chemin.is_file():
            entree["sha256"] = _sha256(chemin)
    _ecrire(AGREGAT, agg)
    touches.append(str(AGREGAT.relative_to(RACINE)))

    # 4. le registre, qui épingle l'empreinte de l'agrégat
    reg = _lire(REGISTRE)
    empreinte_agg = _sha256(AGREGAT)
    for rel in reg.get("releases", []):
        if rel.get("manifest_path", "").endswith("production-profile-gate.release.json"):
            rel["expected_manifest_sha256"] = empreinte_agg
    _ecrire(REGISTRE, reg)
    touches.append(str(REGISTRE.relative_to(RACINE)))

    # 5. l'histoire — un rescellement sans trace est un rescellement qu'on refera sans le savoir
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=RACINE,
                                capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        commit = "(indéterminé)"
    entree = {
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": commit,
        "autorites": {n: {"chemin": derives[n][0], "avant": derives[n][1],
                          "apres": derives[n][2], "motif": motifs[n].strip()}
                      for n in sorted(derives)},
        "preuve": preuve,
        "manifeste_agrege_sha256": empreinte_agg,
        "fichiers_touches": sorted(set(touches)),
        # Une copie dont l'empreinte n'est pas journalisée ne prouve pas ce
        # qu'elle contient : c'est la leçon des poids répliqués sans contrôle
        # d'identité, appliquée aux fichiers que ce geste écrase.
        "sauvegarde": {
            "repertoire": str(racine_copie.relative_to(RACINE)),
            "empreintes_avant": empreintes_avant,
        },
    }
    with HISTOIRE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entree, ensure_ascii=False, sort_keys=True) + "\n")
    touches.append(str(HISTOIRE.relative_to(RACINE)))
    return sorted(set(touches))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--qui-atteste", metavar="CHEMIN", default=None,
                   help="lister les chaînes d'attestation qui portent ce fichier, "
                        "et sortir. À appeler AVANT toute modification.")
    p.add_argument("--check", action="store_true", help="n'écrit rien")
    p.add_argument("--reseal", action="store_true", help="rescelle")
    p.add_argument("--motif", action="append", default=[], metavar="AUTORITE=TEXTE",
                   help="motif pour une autorité qui a dérivé ; répétable")
    p.add_argument("--reattestation-autorisee", action="store_true",
                   help="lever le refus lié à la provenance de placement ; exige que la "
                        "régénération de la provenance soit prévue et tracée")
    p.add_argument("--preuve", default=None,
                   help="référence de la preuve : rapport, test, mesure")
    a = p.parse_args(argv)

    if a.qui_atteste:
        cible = a.qui_atteste
        porte = attestations_de([cible]).get(cible, [])
        if not porte:
            print(f"{cible}\n  aucune chaîne d'attestation ne porte ce fichier.")
            return 0
        print(f"{cible}\n  attesté par {len(porte)} chaîne(s) :")
        for c in porte:
            print(f"    {'[dans la portée de cet outil]' if c in PORTEE else '[HORS PORTÉE]':30s} {c}")
        return 0 if all(c in PORTEE for c in porte) else 1

    if a.check == a.reseal:
        raise Refus("choisissez --check OU --reseal")

    derives = deriver()
    if not derives:
        print("OK : les 19 autorités concordent avec leur empreinte scellée.")
        return 0

    print(f"{len(derives)} autorité(s) ont dérivé de leur empreinte scellée :\n")
    for nom, (chemin, avant, apres) in sorted(derives.items()):
        print(f"  {nom}")
        print(f"     {chemin}")
        print(f"     scellé {avant[:16]}…  →  réel {apres[:16]}…")
    print()

    if a.check:
        print("--check : rien n'a été écrit.")
        print("Pour resceller, fournissez un motif par autorité :")
        for nom in sorted(derives):
            print(f"  --motif '{nom}=…'")
        return 1

    motifs: dict[str, str] = {}
    for brut in a.motif:
        if "=" not in brut:
            raise Refus(f"motif mal formé : « {brut} » — attendu AUTORITE=TEXTE")
        nom, _, texte = brut.partition("=")
        motifs[nom.strip()] = texte
    valider_motifs(derives, motifs)

    # Avant d'écrire : la seconde chaîne serait-elle invalidée ?
    a_ecrire = [str(BINDINGS.relative_to(RACINE)), str(AGREGAT.relative_to(RACINE)),
                str(REGISTRE.relative_to(RACINE))] + \
               [str(s.relative_to(RACINE)) for s in sorted(SUJETS.glob("*.release.json"))]
    # R1 appliqué aux sceaux : recenser toutes les attestations avant d'écrire.
    porte = attestations_de(a_ecrire)
    hors_portee = {f: [c for c in ch if c not in PORTEE] for f, ch in porte.items()}
    hors_portee = {f: c for f, c in hors_portee.items() if c}
    if hors_portee and not a.reattestation_autorisee:
        lignes = []
        for f, chs in sorted(hors_portee.items()):
            lignes.append(f"          {f}")
            for c in chs:
                lignes.append(f"             attesté aussi par  {c}")
        raise Refus(
            "ce rescellement écrirait des fichiers attestés par des chaînes que cet\n"
            "        outil ne sait pas traiter :\n" + "\n".join(lignes) + "\n"
            "        Un rescellement partiel a l'apparence d'un rescellement. Refus.\n"
            "        Étendez la portée de l'outil, ou escaladez."
        )

    heurtes = chaine_provenance_touchee(a_ecrire)
    if heurtes and not a.reattestation_autorisee:
        raise Refus(
            "ce rescellement réécrirait " + str(len(heurtes)) + " blob(s) suivis par la\n"
            "        provenance de production des placements :\n"
            + "".join(f"          {h}\n" for h in heurtes)
            + "        Cette provenance porte un source_commit_sha et une empreinte de\n"
            "        production ; la rapiécer la falsifierait, et la régénérer est une\n"
            "        RÉ-ATTESTATION, décision de gouvernance.\n"
            "        Escaladez, ou relancez avec --reattestation-autorisee après avoir\n"
            "        prévu la régénération de la provenance."
        )

    touches = resceller(derives, motifs, a.preuve)
    print("RESCELLÉ.")
    for nom in sorted(derives):
        print(f"  {nom} : {motifs[nom].strip()}")
    print(f"\nfichiers touchés : {len(touches)}")
    for f in touches:
        print(f"  {f}")
    print(f"\nhistoire : {HISTOIRE.relative_to(RACINE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
