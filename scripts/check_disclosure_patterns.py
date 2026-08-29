#!/usr/bin/env python3
"""Refuser la divulgation de données de machine ou de personne dans le dépôt.

═══ UN SCAN VERT NE SIGNIFIE PAS « RIEN À SIGNALER » ════════════════════════

Ce contrôle cherche des **motifs connus**. Un résultat vert établit qu'aucun
motif de sa grille n'a été détecté — jamais que le diff est exempt de
divulgation. Une grille de motifs est un **plancher**, pas une preuve.

Cette phrase n'est pas une précaution de style. Le 28/08/2026, un contrôle
anti-secret est passé vert sur une branche qui exposait cinq SSID Wi-Fi, une
adresse e-mail nominative et un identifiant Google Drive ouvrant le corpus en
écriture. Le contrôle avait raison sur son domaine — aucun secret — et ce domaine
n'était pas celui du risque.

Un contrôle qui affirme plus qu'il n'a vérifié est le défaut que ce dépôt a
rencontré à répétition : un sceau attestant une liste sans vérifier qu'elle
couvre ce que l'artefact déclare ; une release scellant l'empreinte d'un artefact
qui ne peut pas exister. Ce fichier refuse d'en être le prochain exemplaire.

═══ TROIS CATÉGORIES, PAS UNE ═══════════════════════════════════════════════

1. **Secrets** — clés privées, jetons, mots de passe. Catégorie classique.
2. **Donnée personnelle** — SSID, BSSID, adresses MAC, IP publiques et
   d'overlay, adresses e-mail, chemins nominatifs. Décrit *cette personne* ou
   *cette machine*, pas le système.
3. **Identifiants d'accès** — identifiant de dossier Drive, URL de partage,
   identifiant de bucket. Ni secret au sens classique ni donnée personnelle, et
   pourtant un accès : l'identifiant Drive versionné le 28/08 ouvrait le corpus
   complet en écriture à quiconque disposait du lien.

Un contrôle qui ne couvre que la première laisse passer les deux autres.

═══ RÈGLE ═══════════════════════════════════════════════════════════════════

Les rapports opérationnels et de diagnostic décrivent **une machine et une
personne**, pas un système. Sur un dépôt public, ils ne se versionnent pas
nommément. Un raisonnement ne perd rien à l'anonymisation : « cinq box grand
public sur 192.168.0.0/24 » porte exactement la force de « Tenda_E6CDE0 ».

═══ USAGE ═══════════════════════════════════════════════════════════════════

    python3 scripts/check_disclosure_patterns.py                  # diff vs base
    python3 scripts/check_disclosure_patterns.py --base origin/main
    python3 scripts/check_disclosure_patterns.py --all            # arbre entier
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Motif:
    categorie: str
    nom: str
    expression: re.Pattern[str]
    remede: str


#: Chemins dont la nature est d'illustrer un motif : ne pas s'auto-signaler.
FICHIERS_EXEMPTES = (
    "scripts/check_disclosure_patterns.py",
    "docs/runbooks/disclosure_policy.md",
)

MOTIFS: tuple[Motif, ...] = (
    # ── Catégorie 2 : donnée personnelle ─────────────────────────────────
    Motif(
        "donnée personnelle",
        "adresse MAC / BSSID",
        re.compile(r"\b(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\b"),
        "Un BSSID est indexé par les bases publiques de géolocalisation, avec "
        "une précision supérieure à celle d'un SSID. Retirer entièrement.",
    ),
    Motif(
        "donnée personnelle",
        "chemin de répertoire personnel",
        re.compile(r"/(?:home|Users)/(?!runner\b|user\b|<)[a-z][a-z0-9_-]{2,}"),
        "Lire la configuration, défaut neutre, échec explicite si non "
        "configuré. Cf. dette « chemins de machine personnelle ».",
    ),
    Motif(
        "donnée personnelle",
        "adresse e-mail nominative",
        re.compile(
            r"\b[A-Za-z0-9._%+-]+@(?!example\.|test\.|localhost)"
            r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        ),
        "Désigner le rôle — « le compte propriétaire du corpus » — jamais la "
        "personne.",
    ),
    Motif(
        "donnée personnelle",
        "adresse d'overlay Tailscale",
        re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
        "Une adresse d'overlay identifie un nœud nommé sur un réseau privé.",
    ),
    # ── Catégorie 3 : identifiants d'accès ───────────────────────────────
    Motif(
        "identifiant d'accès",
        "identifiant ou URL Google Drive",
        # Un identifiant Drive est du base64url : il porte des majuscules, un
        # `-` ou un `_`. Exiger cette marque distingue `1OEwXePZors4rl…` d'un
        # SHA-1 git ou d'un md5, qui sont hexadécimaux minuscules et
        # provoqueraient 22 faux positifs sur ce seul dépôt. Un contrôle qui
        # crie au loup se fait ignorer, et cesse alors de protéger.
        re.compile(
            r"(?:drive|docs)\.google\.com/[^\s\"')]+"
            r"|\b1(?=[A-Za-z0-9_-]{27,43}\b)"
            r"(?=[A-Za-z0-9_-]*[A-Z_-])[A-Za-z0-9_-]{27,43}\b"
        ),
        "Une provenance se documente sans handle d'accès : « dossier Drive du "
        "corpus, identifiant hors dépôt ».",
    ),
    # ── Catégorie 1 : secrets ────────────────────────────────────────────
    Motif(
        "secret",
        "clé privée",
        re.compile(r"BEGIN\s+(?:RSA|EC|OPENSSH|PGP|DSA)?\s*PRIVATE KEY"),
        "Ne jamais versionner. Révoquer la clé exposée.",
    ),
)

#: SSID : liste ouverte, donc motif structurel plutôt qu'énumération.
MOTIF_SSID = Motif(
    "donnée personnelle",
    "nom de réseau Wi-Fi",
    re.compile(
        r"\b(?:SSID|ssid)\s*[=:]\s*\S+"
        r"|\b(?:Tenda|Flybox|NetBox|Livebox|Freebox|SFR|Bbox|TP-Link|Linksys)"
        r"[-_][A-Za-z0-9]{4,}\b"
    ),
    "Anonymiser sans affaiblir : « cinq box grand public sur 192.168.0.0/24 » "
    "porte la même force d'argument que les noms.",
)


def _run(*args: str) -> str:
    return subprocess.run(
        args, cwd=REPOSITORY_ROOT, check=True, capture_output=True, text=True
    ).stdout


def _lignes_a_controler(base: str | None, tout: bool) -> list[tuple[str, int, str]]:
    """Retourner (fichier, numéro, contenu) des lignes à examiner."""
    lignes: list[tuple[str, int, str]] = []
    if tout:
        for entree in _run("git", "ls-files", "-z").split("\0"):
            if not entree or entree in FICHIERS_EXEMPTES:
                continue
            chemin = REPOSITORY_ROOT / entree
            try:
                texte = chemin.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for numero, ligne in enumerate(texte.splitlines(), 1):
                lignes.append((entree, numero, ligne))
        return lignes

    fichier = ""
    for ligne in _run("git", "diff", "-U0", base or "HEAD").splitlines():
        if ligne.startswith("+++ b/"):
            fichier = ligne[6:]
        elif ligne.startswith("+") and not ligne.startswith("+++"):
            if fichier not in FICHIERS_EXEMPTES:
                lignes.append((fichier, 0, ligne[1:]))
    return lignes


def controler(base: str | None, tout: bool) -> list[dict[str, object]]:
    constats: list[dict[str, object]] = []
    motifs = (*MOTIFS, MOTIF_SSID)
    for fichier, numero, ligne in _lignes_a_controler(base, tout):
        for motif in motifs:
            trouve = motif.expression.search(ligne)
            if trouve is None:
                continue
            constats.append(
                {
                    "categorie": motif.categorie,
                    "motif": motif.nom,
                    "fichier": fichier,
                    "ligne": numero,
                    "extrait": trouve.group(0)[:60],
                    "remede": motif.remede,
                }
            )
    return constats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=None)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)

    constats = controler(args.base, args.all)
    for constat in constats:
        emplacement = f"{constat['fichier']}"
        if constat["ligne"]:
            emplacement += f":{constat['ligne']}"
        print(f"[{constat['categorie']}] {constat['motif']}")
        print(f"  {emplacement}")
        print(f"  trouvé : {constat['extrait']}")
        print(f"  remède : {constat['remede']}")

    print(f"\nDISCLOSURE_FINDINGS={len(constats)}")
    print(
        "Un résultat vert signifie « aucun motif connu détecté », jamais "
        "« rien à signaler » :\nune grille de motifs est un plancher, pas une "
        "preuve. Relire ce qui décrit une\nmachine ou une personne plutôt qu'un "
        "système."
    )
    return 1 if constats else 0


if __name__ == "__main__":
    sys.exit(main())
