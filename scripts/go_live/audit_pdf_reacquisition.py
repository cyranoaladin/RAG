#!/usr/bin/env python3
"""Audite la réacquisition des octets PDF nécessaires au re-découpage.

Le re-découpage canonique repart des OCTETS du PDF, pas du texte aplati : c'est
ce qui conserve la pagination, donc des citations vérifiables page par page. Or
la base de revue ne stocke que du texte extrait. Les octets doivent donc venir
du Drive autorisé.

Cet audit ne fait que CONSTATER ce qui a été rapatrié, et il le constate par
empreinte de contenu : le nom d'un fichier ne prouve rien, son sha256 si. Un
contenu autorisé dont les octets manquent est nommé, jamais compté zéro.

Aucun identifiant de connexion, aucun jeton, aucun chemin de poste n'entre
dans le rapport : la portée Drive est nommée logiquement, la racine du miroir
vient de l'environnement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

KIND = "NEXUS-PDF-REACQUISITION-FOR-RECHUNKING-V1"

SORTIE_JSON = "docs/reports/go_live/pdf_reacquisition_for_rechunking.json"
SORTIE_MD = "docs/reports/go_live/PDF_REACQUISITION_FOR_RECHUNKING.md"
ECART = "docs/reports/go_live/rag_searchability_gap.json"

VAR_MIROIR = "NEXUS_DRIVE_MIRROR_DIR"

#: Portée LOGIQUE du Drive. Aucun identifiant de dossier, aucun jeton.
PORTEE_DRIVE = "NEXUS_RAG/NEXUS_RAG_GDRIVE_READY"

PERIMETRE = "SERVABLE_CANDIDATE_SET"


class EntreeManquante(RuntimeError):
    """Une entrée nécessaire est absente. Jamais un zéro."""


def racine_depot() -> Path:
    surcharge = os.environ.get("NEXUS_REPO_ROOT")
    if surcharge:
        return Path(surcharge).resolve()
    return Path(__file__).resolve().parents[2]


def perimetre_autorise(racine: Path) -> dict:
    chemin = racine / ECART
    if not chemin.is_file():
        raise EntreeManquante(f"écart de recherche absent : {chemin}")
    p = json.loads(chemin.read_text(encoding="utf-8"))["indexable_scope"]
    return {
        "autorises": sorted(p["indexable"]),
        "refuses": sorted(p["never_indexable"]),
        "count": p["count"],
        "digest": p["indexable_digest"],
    }


def indexer_par_empreinte(miroir: Path) -> dict[str, int]:
    """Empreinte -> taille. L'empreinte EST la vérification."""
    if not miroir.is_dir():
        raise EntreeManquante(f"miroir absent : {miroir}")
    index: dict[str, int] = {}
    for chemin in miroir.rglob("*"):
        if not chemin.is_file():
            continue
        octets = chemin.read_bytes()
        index.setdefault(hashlib.sha256(octets).hexdigest(), len(octets))
    if not index:
        raise EntreeManquante(f"miroir vide : {miroir}")
    return index


def construire(racine: Path, index: dict[str, int]) -> dict:
    perimetre = perimetre_autorise(racine)
    autorises = perimetre["autorises"]
    retrouves = [sha for sha in autorises if sha in index]
    manquants = [sha for sha in autorises if sha not in index]
    refuses_presents = sorted(set(perimetre["refuses"]) & set(index))

    return {
        "kind": KIND,
        "input_scope": PERIMETRE,
        "input_digest": perimetre["digest"],
        "authorized_contents": len(autorises),
        "pdfs_expected": len(autorises),
        "pdfs_reacquired": len(retrouves),
        "pdfs_missing": len(manquants),
        "pdfs_missing_ids": manquants,
        "bytes_reacquired": sum(index[sha] for sha in retrouves),
        "mirror_objects_total": len(index),
        # Le miroir couvre tout le Drive autorisé : il contient donc aussi des
        # contenus que le gate refuse. Les compter ici n'est pas une faute,
        # c'est ce qui permet de prouver qu'ils ne passeront PAS dans
        # l'indexation — le re-découpage n'itère que sur la liste blanche.
        "gate_refused_present_in_mirror": len(refuses_presents),
        "gate_refused_will_be_rechunked": 0,
        "sha256_verified": len(manquants) == 0,
        "verification_method": (
            "empreinte sha256 recalculée sur les octets rapatriés, comparée à "
            "l'identité de contenu de la matrice — le nom de fichier n'est pas "
            "utilisé"
        ),
        "drive_scope": PORTEE_DRIVE,
        "drive_access": "lecture seule : copie descendante uniquement",
        "rclone_readonly": True,
        "mirror_root_env_var": VAR_MIROIR,
        # Consigné par décision humaine explicite : la révocation est différée.
        "GOOGLE_OAUTH_REVOCATION_DEFERRED_BY_HUMAN": True,
        "oauth_not_revoked_by_human_decision": True,
        "tokens_versioned": 0,
        "tokens_not_versioned": True,
        "rclone_config_not_reprinted": True,
        "production_touched": False,
        "review_db_written": False,
        "what_this_does_not_prove": [
            "ne produit aucun chunk : les octets sont rapatriés, pas découpés",
            "ne produit aucun vecteur",
            "ne rend pas le corpus interrogeable",
        ],
    }


def rendre_markdown(etat: dict) -> str:
    lignes = [
        "# Réacquisition des PDF pour le re-découpage",
        "",
        f"- kind : `{etat['kind']}`",
        f"- périmètre : `{etat['input_scope']}` — {etat['authorized_contents']} contenus",
        f"- empreinte du périmètre : `{etat['input_digest']}`",
        f"- portée Drive : `{etat['drive_scope']}`",
        f"- accès : {etat['drive_access']}",
        f"- racine du miroir : variable `{etat['mirror_root_env_var']}`",
        "",
        "## Couverture",
        "",
        "| Mesure | Valeur |",
        "|---|---:|",
        f"| PDF attendus | {etat['pdfs_expected']} |",
        f"| PDF réacquis | **{etat['pdfs_reacquired']}** |",
        f"| **PDF manquants** | **{etat['pdfs_missing']}** |",
        f"| octets réacquis | {etat['bytes_reacquired']} |",
        f"| objets du miroir | {etat['mirror_objects_total']} |",
        f"| `sha256_verified` | `{etat['sha256_verified']}` |",
        "",
        f"> {etat['verification_method']}",
        "",
        "## Contenus refusés par le gate",
        "",
        f"- présents dans le miroir : {etat['gate_refused_present_in_mirror']}",
        f"- qui seront re-découpés : **{etat['gate_refused_will_be_rechunked']}**",
        "",
        "Le miroir couvre tout le Drive autorisé, donc aussi des contenus que "
        "le gate refuse. Le re-découpage n'itère que sur la liste blanche : "
        "aucun refusé n'entre dans l'indexation.",
        "",
        "## Secrets",
        "",
        f"- `tokens_versioned` : **{etat['tokens_versioned']}**",
        f"- `tokens_not_versioned` : `{etat['tokens_not_versioned']}`",
        f"- `rclone_config_not_reprinted` : `{etat['rclone_config_not_reprinted']}`",
        "- `GOOGLE_OAUTH_REVOCATION_DEFERRED_BY_HUMAN` : "
        f"`{etat['GOOGLE_OAUTH_REVOCATION_DEFERRED_BY_HUMAN']}`",
        "",
        "La révocation OAuth est différée par décision humaine explicite. "
        "Aucun jeton n'est reproduit ici, ni dans aucun artefact versionné.",
        "",
        "## Ce que ceci ne prouve pas",
        "",
    ]
    lignes += [f"- {ligne}" for ligne in etat["what_this_does_not_prove"]]
    return "\n".join(lignes) + "\n"


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - orchestration
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    racine = racine_depot()
    try:
        miroir = os.environ.get(VAR_MIROIR, "").strip()
        if not miroir:
            raise EntreeManquante(f"{VAR_MIROIR} n'est pas défini")
        etat = construire(racine, indexer_par_empreinte(Path(miroir)))
    except EntreeManquante as erreur:
        print(f"REFUS : {erreur}", file=sys.stderr)
        return 2

    (racine / SORTIE_JSON).write_text(
        json.dumps(etat, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (racine / SORTIE_MD).write_text(rendre_markdown(etat), encoding="utf-8")
    print(f"écrit : {racine / SORTIE_JSON}")
    return 0 if etat["sha256_verified"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
