#!/usr/bin/env python3
"""Préflight du reseal d'actualité. Il ne rescelle rien : il vérifie.

Un reseal se prépare avant de s'exécuter, parce que trois choses peuvent le
rendre faux et qu'aucune ne se voit au moment de l'écrire :

- **une identité déjà prise.** ADR-0050 interdit de resceller en place ; une
  identité réutilisée ferait mentir tout ce qui a été scellé sous elle. Le
  dépôt porte déjà plusieurs variantes autour de `v2`, y compris des
  répétitions et des candidats : supposer qu'un numéro est libre parce qu'il
  « sonne » suivant est le meilleur moyen d'en écraser un ;
- **un périmètre qui déborde.** Exclure un contenu de plus que les trois visés
  retirerait de la release quelque chose que personne n'a décidé de retirer ;
- **une collision avec la PII.** Les contenus en attente de décision
  personnelle ne doivent pas bouger dans un lot d'actualité.

Ce script établit les trois, et refuse si l'une manque.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

KIND = "NEXUS-CURRENTNESS-RESEAL-PREFLIGHT-V1"

MATRICE = "docs/reports/handoff/servability_matrix_v1.json"
CALCULATEUR_PROMU = "scripts/qualification/compute_promoted_content_set.py"

VERDICT_ARCHIVE = "BLOCKED_NOT_CURRENT_BY_SOURCE"
VERDICT_PII = "BLOCKED_PII_HUMAN_REVIEW"
VERDICT_CANDIDAT = "CANDIDATE_NO_BLOCKING_DIMENSION"

#: Toute chaîne de cette forme est une identité de release, quelle que soit sa
#: place : release effective, candidate, répétition. Les répétitions comptent —
#: une identité utilisée pour une répétition a été utilisée.
MOTIF_IDENTITE = re.compile(r"production-profile-gate-[0-9a-zA-Z.-]+")


class EntreeManquante(RuntimeError):
    """Une entrée nécessaire au préflight est absente ou inexploitable."""


def racine_depot() -> Path:
    surcharge = os.environ.get("NEXUS_REPO_ROOT")
    if surcharge:
        return Path(surcharge).resolve()
    return Path(__file__).resolve().parents[2]


#: Le rapport de préflight NOMME l'identité proposée. S'il était recensé, la
#: proposition se retrouverait « déjà utilisée » au passage suivant, et le
#: préflight s'invaliderait lui-même. On l'exclut, comme on exclut un contrôle
#: qui citerait ses propres motifs.
SORTIES_EXCLUES_DU_RECENSEMENT = (
    ":!docs/reports/go_live/currentness_reseal_preflight.json",
    ":!docs/reports/go_live/currentness_reseal_candidate_plan.json",
    ":!docs/reports/go_live/CURRENTNESS_RESEAL_CANDIDATE_PLAN.md",
)


def identites_existantes(racine: Path) -> set[str]:
    """Recense toute identité de release nommée quelque part dans le dépôt.

    Les rapports de préflight sont exclus : ils citent la proposition, et la
    compter reviendrait à refuser toute identité dès qu'on l'a proposée une
    fois.
    """
    execution = subprocess.run(
        ["git", "grep", "-rhoE", MOTIF_IDENTITE.pattern, "--", ".", *SORTIES_EXCLUES_DU_RECENSEMENT],
        cwd=str(racine),
        capture_output=True,
        text=True,
    )
    trouvees = {
        valeur.rstrip(".,);:\"'")
        for valeur in execution.stdout.split()
        if MOTIF_IDENTITE.fullmatch(valeur.rstrip(".,);:\"'"))
    }
    if not trouvees:
        raise EntreeManquante(
            "aucune identité de release trouvée : le recensement a échoué, et "
            "un recensement vide ne prouve pas qu'une identité est libre"
        )
    return trouvees


def ensemble_promu(racine: Path) -> set[str]:
    import tempfile

    chemin = racine / CALCULATEUR_PROMU
    if not chemin.is_file():
        raise EntreeManquante(f"calculateur canonique absent : {chemin}")
    with tempfile.TemporaryDirectory() as repertoire:
        sortie = Path(repertoire) / "promu.json"
        execution = subprocess.run(
            [sys.executable, str(chemin), "--output", str(sortie)],
            cwd=str(racine),
            capture_output=True,
            text=True,
        )
        if execution.returncode != 0 or not sortie.is_file():
            raise EntreeManquante(
                f"le calculateur canonique a échoué : {execution.stderr[:300]}"
            )
        return set(json.loads(sortie.read_text(encoding="utf-8"))["content_sha256"])


def preflight(racine: Path, identite_proposee: str) -> dict:
    chemin_matrice = racine / MATRICE
    if not chemin_matrice.is_file():
        raise EntreeManquante(f"matrice absente : {chemin_matrice}")
    lignes = json.loads(chemin_matrice.read_text(encoding="utf-8"))["rows"]
    par_contenu = {ligne["content_sha256"]: ligne for ligne in lignes}

    promus = ensemble_promu(racine)
    existantes = identites_existantes(racine)

    a_exclure = sorted(
        sha
        for sha in promus
        if par_contenu.get(sha, {}).get("verdict") == VERDICT_ARCHIVE
    )
    promus_pii = sorted(
        sha
        for sha in promus
        if par_contenu.get(sha, {}).get("verdict") == VERDICT_PII
    )
    refuses = sorted(
        sha
        for sha in promus
        if par_contenu.get(sha, {}).get("verdict", VERDICT_CANDIDAT) != VERDICT_CANDIDAT
    )

    pii_des_exclus = {par_contenu[sha]["pii"] for sha in a_exclure}
    tous_pii_clairs = pii_des_exclus == {"PII_CLEARED_OR_NOT_SCANNED"} if a_exclure else False
    aucun_pii_touche = not (set(a_exclure) & set(promus_pii))

    identite_libre = identite_proposee not in existantes

    return {
        "kind": KIND,
        "status": "PREFLIGHT_ONLY_NOT_APPLIED",
        "release_identity": {
            "proposed": identite_proposee,
            "is_free": identite_libre,
            "existing_identities": sorted(existantes),
            "existing_count": len(existantes),
            "why_it_matters": (
                "ADR-0050 interdit de resceller en place ; une identité réutilisée "
                "ferait mentir ce qui a été scellé sous elle. Les répétitions "
                "comptent comme des identités utilisées."
            ),
        },
        "contents_to_exclude": {
            "count": len(a_exclure),
            "content_sha256": a_exclure,
            "all_pii_cleared": tous_pii_clairs,
            "pii_statuses_observed": sorted(pii_des_exclus),
        },
        "pii_contents_untouched": {
            "count": len(promus_pii),
            "intersects_exclusion": not aucun_pii_touche,
        },
        "expected_impact": {
            "promoted_content_set_size": {
                "before": len(promus),
                "after": len(promus) - len(a_exclure),
            },
            "release_promoted_refused_contents": {
                "before": len(refuses),
                "after": len(refuses) - len(a_exclure),
            },
            "release_promoted_refused_by_currentness": {
                "before": len(a_exclure),
                "after": 0,
            },
            "pii_undecided_unchanged": True,
            "GO_LIVE_READY": {"before": False, "after": False},
            "assert_ready": {"before": 1, "after": 1},
            "why_still_false": (
                "PII, recherche, qualification et PR bloquantes persistent ; ce "
                "reseal ferme une raison sur six"
            ),
        },
        "preflight_passed": bool(
            identite_libre and a_exclure and tous_pii_clairs and aucun_pii_touche
        ),
        "blocking_findings": sorted(
            nom
            for nom, tenu in {
                "release_identity_already_used": not identite_libre,
                "no_content_to_exclude": not a_exclure,
                "excluded_content_has_undecided_pii": not tous_pii_clairs,
                "exclusion_touches_pii_contents": not aucun_pii_touche,
            }.items()
            if tenu
        ),
        "not_done_here": [
            "aucune release écrite",
            "aucun fichier data/releases/ modifié",
            "aucune identité réservée",
            "aucune décision PII",
        ],
        "requires_human_authorization": True,
    }


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--proposed-identity", required=True)
    analyseur.add_argument(
        "--output", default="docs/reports/go_live/currentness_reseal_preflight.json"
    )
    arguments = analyseur.parse_args(argv)

    racine = racine_depot()
    try:
        etat = preflight(racine, arguments.proposed_identity)
    except EntreeManquante as erreur:
        print(f"ENTREE_MANQUANTE: {erreur}", file=sys.stderr)
        return 2

    chemin = racine / arguments.output
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(etat, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"écrit : {chemin}")
    print(
        json.dumps(
            {
                "preflight_passed": etat["preflight_passed"],
                "identity_free": etat["release_identity"]["is_free"],
                "to_exclude": etat["contents_to_exclude"]["count"],
                "blocking_findings": etat["blocking_findings"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if etat["preflight_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
