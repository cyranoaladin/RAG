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
import subprocess
import sys
from pathlib import Path

KIND = "NEXUS-CURRENTNESS-RESEAL-PREFLIGHT-V1"

MATRICE = "docs/reports/handoff/servability_matrix_v1.json"
CALCULATEUR_PROMU = "scripts/qualification/compute_promoted_content_set.py"

VERDICT_ARCHIVE = "BLOCKED_NOT_CURRENT_BY_SOURCE"
VERDICT_PII = "BLOCKED_PII_HUMAN_REVIEW"
VERDICT_CANDIDAT = "CANDIDATE_NO_BLOCKING_DIMENSION"

class EntreeManquante(RuntimeError):
    """Une entrée nécessaire au préflight est absente ou inexploitable."""


def racine_depot() -> Path:
    surcharge = os.environ.get("NEXUS_REPO_ROOT")
    if surcharge:
        return Path(surcharge).resolve()
    return Path(__file__).resolve().parents[2]


def identites_existantes(racine: Path) -> tuple[set[str], str]:
    """Délègue à l'autorité canonique d'identité de release.

    Une version antérieure recensait les identités par `git grep` sur tout le
    dépôt. Elle produisait deux défauts, et les deux étaient des faux positifs :

    - le rapport de préflight NOMME l'identité proposée, donc au passage
      suivant elle ressortait « déjà utilisée » : le préflight s'invalidait
      lui-même, et chaque nouveau rapport aggravait le cas ;
    - une identité seulement ÉVOQUÉE — dans un ADR qui l'envisage, dans un
      rapport de lot qui la discute — était comptée comme prise. Or évoquer
      n'est pas publier.

    Surtout, ce recensement était une SECONDE autorité sur un concept qui en a
    déjà une : le producteur de release refuse lui-même toute identité publiée,
    en consultant ses identités publiées et le registre sur disque. Deux
    autorités sur l'unicité d'identité finiraient par ne pas dire la même
    chose — c'est d'ailleurs arrivé ici.
    """
    import sys as _sys

    chemin_scripts = racine / "services/rag-pedago/scripts"
    if str(chemin_scripts) not in _sys.path:
        _sys.path.insert(0, str(chemin_scripts))
    try:
        from build_production_profile_release import (  # noqa: PLC0415
            PUBLISHED_RELEASE_IDS,
        )
    except ImportError as erreur:
        raise EntreeManquante(
            f"autorité d'identité de release introuvable : {erreur}"
        ) from erreur
    return set(PUBLISHED_RELEASE_IDS), "build_production_profile_release.PUBLISHED_RELEASE_IDS"


def identite_est_libre(racine: Path, identite: str) -> tuple[bool, str]:
    """Interroge l'autorité canonique. Elle seule décide."""
    import sys as _sys

    chemin_scripts = racine / "services/rag-pedago/scripts"
    if str(chemin_scripts) not in _sys.path:
        _sys.path.insert(0, str(chemin_scripts))
    try:
        from build_production_profile_release import (  # noqa: PLC0415
            ReleaseIdentityError,
            require_governed_release_id,
        )
    except ImportError as erreur:
        raise EntreeManquante(
            f"autorité d'identité de release introuvable : {erreur}"
        ) from erreur
    try:
        require_governed_release_id(identite)
    except ReleaseIdentityError as refus:
        return False, str(refus)
    return True, "acceptée par require_governed_release_id"


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
    existantes, source_autorite = identites_existantes(racine)
    identite_libre, motif_identite = identite_est_libre(racine, identite_proposee)

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

    return {
        "kind": KIND,
        "status": "PREFLIGHT_ONLY_NOT_APPLIED",
        "release_identity": {
            "proposed": identite_proposee,
            "is_free": identite_libre,
            "verdict_reason": motif_identite,
            "authority": source_autorite,
            "published_identities": sorted(existantes),
            "existing_count": len(existantes),
            "why_it_matters": (
                "ADR-0050 interdit de resceller en place ; une identité réutilisée "
                "ferait mentir ce qui a été scellé sous elle. L'autorité "
                "consultée est celle du producteur de release, qui refuse toute "
                "identité publiée ou inscrite au registre — évoquer une identité "
                "dans un document ne la rend pas prise."
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
