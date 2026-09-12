#!/usr/bin/env python3
"""Audite l'espace disque récupérable. Ne supprime rien, jamais.

Le gate de readiness exige 40 Gio libres. La machine est en dessous, et
`disk_policy_ok` bloque désormais le go-live. Ce blocage est réel : une base
vectorielle qu'on ne peut pas écrire ne sert personne.

Ce script existe pour que la sortie de ce blocage ne se fasse pas à coups de
`prune`. Un `docker system prune -a` libérerait l'espace en emportant, sans
les nommer, la base de revue PII, la base de vectorisation dédiée et les
artefacts de modèle épinglés. L'espace serait libre et le corpus
irrécupérable.

Il produit donc un inventaire CLASSÉ, et des commandes nommées une par une,
qu'un humain exécute ou non. Toute commande visant une ressource protégée est
refusée à la construction : la protection est dans le code, pas dans une
consigne.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

KIND = "NEXUS-DISK-RECOVERY-AUDIT-V1"

SORTIE_JSON = "docs/reports/go_live/disk_recovery_audit.json"
SORTIE_MD = "docs/reports/go_live/DISK_RECOVERY_AUDIT.md"

#: Le plancher du gate. Lu ici pour que les deux ne divergent pas en silence.
GATE = "scripts/go_live/check_go_live_readiness.py"

CATEGORIES = (
    "KEEP_CRITICAL",
    "KEEP_REVIEW_PII",
    "KEEP_VECTOR_DB",
    "KEEP_MODEL_ARTIFACT",
    "KEEP_BACKUP",
    "DELETE_CANDIDATE_SAFE",
    "DELETE_CANDIDATE_NEEDS_CONFIRMATION",
    "UNKNOWN_DO_NOT_TOUCH",
)

CATEGORIES_PROTEGEES = frozenset(
    {
        "KEEP_CRITICAL",
        "KEEP_REVIEW_PII",
        "KEEP_VECTOR_DB",
        "KEEP_MODEL_ARTIFACT",
        "KEEP_BACKUP",
        "UNKNOWN_DO_NOT_TOUCH",
    }
)

#: Motifs de ressources qu'aucune commande proposée ne doit jamais toucher.
#: Une correspondance suffit à refuser la commande.
MOTIFS_PROTEGES = (
    "nexus-drive-staging-v2",
    "drivestaging",
    "nexus_vector_staging_a_",
    "nexus-vector-staging-a-",
    "e4eb093913421bb0f5605c4effc2a0b527facbc66a55978986e6a8b883a6de62",
    "1f52e61ee77d4c1dfee011fe2276437716712176562e2ea77f8981302e2fe6d4",
    "/backup",
    "nexus-backups",
    "rag-model-artifacts",
    "huggingface",
    "multilingual-e5-large",
    "bge-reranker",
    "ms-marco-MiniLM",
)

#: Les prunes globaux. Ils ne nomment pas ce qu'ils emportent : c'est
#: exactement ce qui les rend inacceptables ici.
PRUNES_INTERDITS = (
    "docker system prune",
    "docker volume prune",
    "docker image prune",
    "docker container prune",
)


#: Ce qui a REELLEMENT été exécuté, avec les mesures prises de part et d'autre.
#: Une estimation qu'un fait a démentie ne doit pas rester seule dans un
#: artefact de preuve : elle y serait relue comme un fait.
OPERATIONS_EXECUTEES = (
    {
        "command": (
            "docker rmi 3d53b92c6c57 80c4e806c15e a8c65404dc7c e67cac305711 "
            "ccc96b0650e4 8838b3c6cc1c fa9d6bbdd381 a1c7447f7d46"
        ),
        "authorized_by": "décision humaine explicite, 8 identifiants nommés",
        "free_before_bytes": 32_622_968_832,
        "free_after_bytes": 32_620_871_680,
        "images_pool_before_bytes": 109_200_000_000,
        "images_pool_after_bytes": 108_200_000_000,
        "estimated_gain_bytes": 53_200_000_000,
        "measured_gain_bytes": -2_097_152,
        "verdict": "ESTIMATION_DEMENTIE_PAR_LA_MESURE",
        "why": (
            "`docker images` affiche une taille VIRTUELLE, couches partagées "
            "comprises. Ces huit images partageaient presque toutes leurs "
            "couches avec des images encore étiquetées (core-v2-auth-*, "
            "entitlement-*) : supprimer le manifeste n'a libéré aucune donnée. "
            "Le pool d'images n'a cédé qu'environ 1 Go, et l'espace libre rien "
            "du tout."
        ),
    },
    {
        "command": "docker buildx prune --force",
        "authorized_by": (
            "décision humaine explicite, sous condition d'absence de build actif"
        ),
        "active_build_check": (
            "cache identique à l'octet et en nombre d'entrées sur 75 s "
            "(139.2GB / 1907) ; images aria-p7b2-* vieilles de 2 h ; aucun "
            "processus docker build / buildx / buildkitd"
        ),
        "free_before_bytes": 32_540_786_688,
        "free_after_bytes": 108_489_826_304,
        "build_cache_before_bytes": 139_200_000_000,
        "build_cache_after_bytes": 68_710_000_000,
        "measured_gain_bytes": 75_949_039_616,
        "verdict": "PLANCHER_FRANCHI",
        "why": (
            "le cache de build ne porte aucune donnée : seul son temps de "
            "reconstruction est perdu. C'est la seule grande réserve dont la "
            "suppression ne coûte rien d'irremplaçable."
        ),
    },
)


class RessourceProtegee(RuntimeError):
    """Une commande proposée vise une ressource qui ne doit pas être touchée."""


class EntreeManquante(RuntimeError):
    """Une mesure nécessaire est absente. Jamais un zéro."""


def _libre_avant(libre_maintenant: int) -> int:
    """L'espace libre avant la première opération de la campagne.

    Sans opération exécutée, « avant » et « maintenant » se confondent.
    """
    if OPERATIONS_EXECUTEES:
        return OPERATIONS_EXECUTEES[0]["free_before_bytes"]
    return libre_maintenant


def racine_depot() -> Path:
    surcharge = os.environ.get("NEXUS_REPO_ROOT")
    if surcharge:
        return Path(surcharge).resolve()
    return Path(__file__).resolve().parents[2]


def plancher_du_gate(racine: Path) -> int:
    """Lit le plancher CHEZ le gate. Le recopier ici en ferait une 2e autorité."""
    source = (racine / GATE).read_text(encoding="utf-8")
    trouve = re.search(
        r"DISQUE_LIBRE_MINIMUM_OCTETS = (\d+) \* 1024\*\*3", source
    )
    if not trouve:
        raise EntreeManquante(
            "plancher disque introuvable dans le gate : il a changé de forme"
        )
    return int(trouve.group(1)) * 1024**3


def verifier_commande(commande: str, categorie: str) -> str:
    """Refuse toute commande protégée, et tout prune global.

    C'est le seul endroit où une commande de suppression prend forme. Elle y
    passe, ou elle n'existe pas.
    """
    if categorie in CATEGORIES_PROTEGEES:
        if commande:
            raise RessourceProtegee(
                f"une ressource {categorie} ne peut porter aucune commande de "
                f"suppression : {commande}"
            )
        return ""
    for prune in PRUNES_INTERDITS:
        if prune in commande:
            raise RessourceProtegee(
                f"prune global refusé : « {prune} » n'énumère pas ce qu'il "
                "emporte"
            )
    for motif in MOTIFS_PROTEGES:
        if motif in commande:
            raise RessourceProtegee(
                f"la commande vise une ressource protégée ({motif}) : {commande}"
            )
    return commande


def element(
    nom: str, taille_octets: int, categorie: str, raison: str, commande: str = ""
) -> dict:
    if categorie not in CATEGORIES:
        raise EntreeManquante(f"catégorie inconnue : {categorie}")
    return {
        "name": nom,
        "size_bytes": taille_octets,
        "size_human": humain(taille_octets),
        "category": categorie,
        "reason": raison,
        "proposed_command": verifier_commande(commande, categorie),
    }


def humain(octets: int) -> str:
    for unite in ("o", "Kio", "Mio", "Gio"):
        if abs(octets) < 1024 or unite == "Gio":
            return f"{octets:.1f} {unite}" if unite != "o" else f"{octets} o"
        octets /= 1024.0
    return f"{octets:.1f} Gio"


def _docker(*args: str) -> str:
    resultat = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=120
    )
    if resultat.returncode != 0:
        raise EntreeManquante(f"docker {' '.join(args)} : {resultat.stderr.strip()}")
    return resultat.stdout


def _octets(texte: str) -> int:
    """Convertit « 3.18GB », « 938MB », « 104.7kB » en octets décimaux."""
    trouve = re.match(r"\s*([\d.]+)\s*([kKMGT]?B)\s*$", texte)
    if not trouve:
        return 0
    facteurs = {"B": 1, "kB": 10**3, "MB": 10**6, "GB": 10**9, "TB": 10**12}
    return int(float(trouve.group(1)) * facteurs.get(trouve.group(2), 1))


def mesurer(racine: Path) -> dict:
    usage = shutil.disk_usage(racine)

    resume = _docker("system", "df", "--format", "{{.Type}}|{{.Size}}|{{.Reclaimable}}")
    pools = {}
    for ligne in resume.strip().splitlines():
        parties = ligne.split("|")
        if len(parties) != 3:
            continue
        pools[parties[0]] = {
            "size_bytes": _octets(parties[1]),
            "reclaimable_bytes": _octets(parties[2].split("(")[0]),
        }

    pendantes = []
    sortie = _docker(
        "images", "-f", "dangling=true", "--format", "{{.ID}}|{{.Size}}|{{.CreatedSince}}"
    )
    for ligne in sortie.strip().splitlines():
        if not ligne.strip():
            continue
        identifiant, taille, age = ligne.split("|")
        pendantes.append(
            {"id": identifiant, "size_bytes": _octets(taille), "age": age}
        )

    volumes = _docker("volume", "ls", "-q").strip().splitlines()

    return {
        "disk_total_bytes": usage.total,
        "disk_free_bytes": usage.free,
        "docker_pools": pools,
        "dangling_images": pendantes,
        "volumes_total": len(volumes),
    }


def construire(racine: Path, *, mesures=None) -> dict:
    mesures = mesures if mesures is not None else mesurer(racine)
    plancher = plancher_du_gate(racine)
    libre = mesures["disk_free_bytes"]
    manque = max(0, plancher - libre)

    pendantes = mesures["dangling_images"]
    somme_pendantes = sum(image["size_bytes"] for image in pendantes)

    elements = [
        element(
            "base de revue PII nexus-drive-staging-v2 (+ son volume)",
            0,
            "KEEP_REVIEW_PII",
            "seul support rendant rejouables 149 décisions PII, dont 23 promues",
        ),
        element(
            "base dédiée nexus_vector_staging_a_20260912T060731Z (+ son volume)",
            0,
            "KEEP_VECTOR_DB",
            "cible de la phase A ; porte la liste blanche des 2264 autorisés",
        ),
        element(
            "/backup/rag/non-pdf-reacquired",
            7_130_000,
            "KEEP_BACKUP",
            "store durable qui ferme non_pdf_servable_reacquired=37",
        ),
        element(
            "~/nexus-backups (sauvegarde de la base de revue)",
            131_000_000,
            "KEEP_BACKUP",
            "restauration prouvée du corpus de revue ; 125 Mo, gain nul",
        ),
        element(
            "~/rag-model-artifacts/intfloat-multilingual-e5-large-3d7cfbda…",
            9_700_000_000,
            "KEEP_MODEL_ARTIFACT",
            "révision EXACTE épinglée par le manifeste et vérifiée au préflight",
        ),
        element(
            "~/.cache/huggingface (E5, bge-reranker-v2-m3, bge-m3, MiniLM)",
            9_200_000_000,
            "KEEP_MODEL_ARTIFACT",
            "artefacts de modèle ; interdits de suppression par le mandat",
        ),
        element(
            f"{len(pendantes)} images Docker sans étiquette, non référencées",
            somme_pendantes,
            "DELETE_CANDIDATE_SAFE",
            "aucune n'est référencée par un conteneur ; restes de rebuilds "
            "Node/Playwright d'autres chantiers, dont 16 des 6 dernières heures",
            "docker rmi " + " ".join(image["id"] for image in pendantes[:8]),
        ),
        element(
            "cache de build Docker (buildx)",
            mesures["docker_pools"].get("Build Cache", {}).get("size_bytes", 0),
            "DELETE_CANDIDATE_NEEDS_CONFIRMATION",
            "cache pur, régénérable, aucune donnée ; mais la commande est un "
            "prune : elle n'énumère pas ce qu'elle emporte",
            "docker buildx prune --force",
        ),
        element(
            "~/.cache/uv et ~/.cache/pip",
            14_000_000_000,
            "DELETE_CANDIDATE_NEEDS_CONFIRMATION",
            "caches de paquets régénérables, hors de ce dépôt ; leur "
            "reconstruction coûte du réseau, pas des données",
            "uv cache clean; pip cache purge",
        ),
        element(
            "images E2E d'autres chantiers (agent-*, entitlement-*, core-v2-*)",
            0,
            "UNKNOWN_DO_NOT_TOUCH",
            "appartiennent à d'autres sessions ; leur cycle de vie ne se "
            "décide pas depuis ce dépôt",
        ),
        element(
            "~/nexus-claude-pr153-p2-20260908 (15 Gio)",
            16_100_000_000,
            "UNKNOWN_DO_NOT_TOUCH",
            "copie de travail d'un lot antérieur, non enregistrée comme "
            "worktree ; sa valeur d'archive n'est pas établie ici",
        ),
    ]

    candidats = [
        item
        for item in elements
        if item["category"].startswith("DELETE_CANDIDATE")
    ]
    proteges = [item for item in elements if item["category"] in CATEGORIES_PROTEGEES]
    sur_gain = sum(
        item["size_bytes"]
        for item in elements
        if item["category"] == "DELETE_CANDIDATE_SAFE"
    )

    return {
        "kind": KIND,
        # `*_before` désigne l'AVANT DE LA CAMPAGNE de nettoyage, pas l'instant
        # de ce calcul. Après coup, les deux diffèrent : laisser le présent
        # sous une étiquette « avant » ferait relire un état corrigé comme
        # l'état d'origine.
        "disk_free_before": _libre_avant(libre),
        "disk_free_before_human": humain(_libre_avant(libre)),
        "disk_free_after": libre,
        "disk_free_after_human": humain(libre),
        "disk_policy_ok_after": libre >= plancher,
        "disk_recovered_bytes": libre - _libre_avant(libre),
        "disk_recovered_human": humain(libre - _libre_avant(libre)),
        "disk_required_floor": plancher,
        "disk_required_floor_human": humain(plancher),
        "disk_shortfall_bytes": manque,
        "disk_shortfall_human": humain(manque),
        "disk_policy_ok_before": _libre_avant(libre) >= plancher,
        "unit_note": (
            "34,85 Gio et 37,42 Go sont la MÊME mesure : gibioctets contre "
            "gigaoctets décimaux. Il n'y a pas deux relevés qui divergent."
        ),
        "docker_images_reclaimable": mesures["docker_pools"]
        .get("Images", {})
        .get("reclaimable_bytes", 0),
        "docker_build_cache_reclaimable": mesures["docker_pools"]
        .get("Build Cache", {})
        .get("reclaimable_bytes", 0),
        "volumes_total": mesures["volumes_total"],
        "volumes_protected": [
            "e4eb093913421bb0f5605c4effc2a0b527facbc66a55978986e6a8b883a6de62",
            "1f52e61ee77d4c1dfee011fe2276437716712176562e2ea77f8981302e2fe6d4",
        ],
        "inventory": elements,
        "delete_candidates": candidats,
        "protected_resources": proteges,
        "commands_requiring_human_confirmation": [
            item["proposed_command"] for item in candidats if item["proposed_command"]
        ],
        "estimated_free_after": libre + sur_gain,
        "estimated_free_after_human": humain(libre + sur_gain),
        "estimated_free_after_note": (
            "borne HAUTE : les images sans étiquette partagent des couches, "
            "le gain réel est inférieur à leur somme. Le besoin n'est que de "
            f"{humain(manque)}."
        ),
        "measured_history": list(OPERATIONS_EXECUTEES),
        "deletions_executed": len(OPERATIONS_EXECUTEES),
        "vector_db_preserved": True,
        "review_db_preserved": True,
        "production_touched": False,
        "vectorization_executed": False,
        # Ce que CE CODE ne fait pas. A ne pas confondre avec ce qu un humain a
        # autorise et lance a la main : `measured_history` le dit, et les deux
        # ne doivent jamais se lire comme une seule affirmation.
        "what_this_script_never_does": [
            "il ne supprime rien : il n a aucun chemin d execution destructif",
            "il ne propose aucun prune global : ils n enumerent pas ce qu ils "
            "emportent, et une commande protegee est refusee a la construction",
            "il ne touche ni la base de revue, ni la base dediee, ni un volume, "
            "ni un artefact de modele",
        ],
        "what_this_does_not_prove": [
            "ne rend pas le corpus interrogeable : le blocage recherche reste "
            "ouvert et aucun vecteur n existe",
            "ne ferme aucun des six blocages de fond du go-live",
        ],
    }


def rendre_markdown(etat: dict) -> str:
    lignes = [
        "# Récupération d'espace disque — audit",
        "",
        f"- kind : `{etat['kind']}`",
        f"- libre avant nettoyage : **{etat['disk_free_before_human']}**",
        f"- libre après nettoyage : **{etat['disk_free_after_human']}**",
        f"- récupéré : **{etat['disk_recovered_human']}**",
        f"- plancher du gate : **{etat['disk_required_floor_human']}**",
        f"- manque : **{etat['disk_shortfall_human']}**",
        f"- `disk_policy_ok_before` : `{etat['disk_policy_ok_before']}`",
        f"- `disk_policy_ok_after` : `{etat['disk_policy_ok_after']}`",
        "",
        f"> {etat['unit_note']}",
        "",
        "## Inventaire classé",
        "",
        "| Élément | Taille | Catégorie | Raison | Commande proposée |",
        "|---|---:|---|---|---|",
    ]
    for item in etat["inventory"]:
        taille = item["size_human"] if item["size_bytes"] else "—"
        commande = f"`{item['proposed_command']}`" if item["proposed_command"] else "—"
        lignes.append(
            f"| {item['name']} | {taille} | `{item['category']}` | "
            f"{item['reason']} | {commande} |"
        )
    lignes += [
        "",
        "## Ce qui est protégé",
        "",
        f"- volumes protégés : {len(etat['volumes_protected'])} nommés",
        f"- `vector_db_preserved` : `{etat['vector_db_preserved']}`",
        f"- `review_db_preserved` : `{etat['review_db_preserved']}`",
        "",
        "## Récupérable selon Docker",
        "",
        f"- images : {humain(etat['docker_images_reclaimable'])}",
        f"- cache de build : {humain(etat['docker_build_cache_reclaimable'])}",
        f"- volumes au total : {etat['volumes_total']}",
        "",
        "## Ce qu'il resterait à récupérer",
        "",
        f"- borne haute sur les images sans étiquette : "
        f"{etat['estimated_free_after_human']}",
        f"- {etat['estimated_free_after_note']}",
        "",
    ]
    if etat["measured_history"]:
        lignes += [
            "## Ce qu'un humain a autorisé et exécuté, et ce que la mesure en a dit",
            "",
            "| Commande | Gain estimé | Gain mesuré | Verdict |",
            "|---|---:|---:|---|",
        ]
        for operation in etat["measured_history"]:
            estime = operation.get("estimated_gain_bytes")
            lignes.append(
                f"| `{operation['command'][:64]}` | "
                f"{humain(estime) if estime else '—'} | "
                f"**{humain(operation['measured_gain_bytes'])}** | "
                f"`{operation['verdict']}` |"
            )
        for operation in etat["measured_history"]:
            lignes += ["", f"> {operation['why']}"]
        lignes.append("")
    lignes += ["## Ce que ce script ne fait jamais", ""]
    lignes += [f"- {ligne}" for ligne in etat["what_this_script_never_does"]]
    lignes += ["", "## Ce que ce lot ne prouve pas", ""]
    lignes += [f"- {ligne}" for ligne in etat["what_this_does_not_prove"]]
    return "\n".join(lignes) + "\n"


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--check-only", action="store_true")
    arguments = parseur.parse_args(argv)

    racine = racine_depot()
    try:
        etat = construire(racine)
    except (EntreeManquante, RessourceProtegee) as erreur:
        print(f"REFUS : {erreur}", file=sys.stderr)
        return 2

    if arguments.check_only:
        print(json.dumps(etat, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    (racine / SORTIE_JSON).write_text(
        json.dumps(etat, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (racine / SORTIE_MD).write_text(rendre_markdown(etat), encoding="utf-8")
    print(f"écrit : {racine / SORTIE_JSON}")
    print(f"écrit : {racine / SORTIE_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
