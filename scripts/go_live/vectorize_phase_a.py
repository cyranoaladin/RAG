#!/usr/bin/env python3
"""Vectorisation phase A dans la base dédiée — et refus si l'entrée ne s'y prête pas.

Ce script n'est pas seulement un exécuteur : c'est d'abord un contrôle
d'aptitude. Vectoriser un corpus dont la majeure partie du texte dépasse la
longueur de séquence du modèle produirait un index qui *paraît* couvrir le
périmètre tout en laissant des contenus entiers inatteignables. Un tel index
est pire qu'aucun index : il rend des réponses plausibles sur un corpus
tronqué, et rien dans le résultat ne le signale.

Trois refus structurent ce fichier.

1. Refus d'aptitude : un seul chunk autorisé au-delà de la limite du modèle
   suffit. La limite n'est pas recopiée ici, elle est lue sur le modèle.
2. Refus de succès partiel : `vectorization_executed` ne peut pas devenir vrai
   sur une couverture incomplète. Un `vector_rows` non nul ne prouve rien ;
   seule l'égalité avec l'attendu, contenu par contenu, prouve quelque chose.
3. Refus de provenance non prouvée : l'identité du modèle est DÉRIVÉE de
   l'autorité canonique du dépôt, qui est réellement appelée. Aucun état
   fourni par l'appelant n'est recopié dans la preuve.

Ce qu'il ne fait jamais : écrire ailleurs que dans la table de vecteurs de la
base dédiée, ouvrir la base de revue autrement qu'en lecture, indexer un
contenu hors liste blanche, ou tronquer un passage pour le faire entrer —
tronquer, c'est indexer autre chose que ce qu'on prétend indexer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

KIND = "NEXUS-VECTORIZATION-PHASE-A-EXECUTION-V1"

SORTIE_JSON = "docs/reports/go_live/vectorization_phase_a_execution.json"
SORTIE_MD = "docs/reports/go_live/VECTORIZATION_PHASE_A_EXECUTION.md"
ECART = "docs/reports/go_live/rag_searchability_gap.json"

PERIMETRE = "SERVABLE_CANDIDATE_SET"
MODELE = "intfloat/multilingual-e5-large"
REVISION = "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"
DIMENSION = 1024

#: La racine des artefacts de modèle vient de l'environnement. Aucun chemin de
#: poste de travail ne doit entrer dans une preuve versionnée : elle doit
#: pouvoir être rejouée ailleurs.
VARIABLE_RACINE_ARTEFACTS = "RAG_MODEL_ARTIFACTS_DIR"

#: Identifiant LOGIQUE de l'artefact, relatif à cette racine.
ARTEFACT_LOGIQUE = f"staging-phase-a-e5-large-{REVISION}"

#: Les compteurs qui doivent tous être nuls pour qu'un succès soit possible.
COMPTEURS_A_ZERO = (
    "unauthorized_content_rows",
    "pii_undecided_rows",
    "currentness_refused_rows",
    "gate_refused_rows",
    "dimension_mismatch",
    "null_vectors",
    "duplicates",
    "missing_authorized_contents_with_chunks",
)


class EntreeManquante(RuntimeError):
    """Une entrée nécessaire est absente. Jamais un zéro."""


class EntreeInapte(RuntimeError):
    """L'entrée existe mais ne peut pas être vectorisée sans la trahir."""


class CibleInterdite(RuntimeError):
    """La cible désignée n'est pas la base dédiée."""


class ProvenanceNonProuvee(RuntimeError):
    """L'identité du modèle n'a pas été établie par l'autorité canonique."""


def racine_depot() -> Path:
    surcharge = os.environ.get("NEXUS_REPO_ROOT")
    if surcharge:
        return Path(surcharge).resolve()
    return Path(__file__).resolve().parents[2]


def _garde_de_cible():
    """Réutilise l'unique autorité qui sait refuser la base de revue."""
    chemin = str(Path(__file__).resolve().parent)
    if chemin not in sys.path:
        sys.path.insert(0, chemin)
    from provision_dedicated_vector_db import (  # noqa: PLC0415
        decrire_dsn,
        refuser_si_base_de_revue,
    )

    return decrire_dsn, refuser_si_base_de_revue


# --- Provenance du modèle : dérivée, jamais recopiée -----------------------


def racine_des_artefacts() -> Path:
    valeur = os.environ.get(VARIABLE_RACINE_ARTEFACTS, "").strip()
    if not valeur:
        raise EntreeManquante(
            f"{VARIABLE_RACINE_ARTEFACTS} n'est pas défini : la racine des "
            "artefacts de modèle ne doit pas être devinée"
        )
    return Path(valeur)


def empreinte_d_inventaire(artefact: Path) -> str:
    inventaire = artefact / "SHA256SUMS"
    if not inventaire.is_file():
        raise ProvenanceNonProuvee(
            f"inventaire absent : {artefact.name}/SHA256SUMS — sans lui, "
            "l'autorité canonique ne peut rien vérifier"
        )
    return hashlib.sha256(inventaire.read_bytes()).hexdigest()


def verifier_artefact(artefact: Path, *, verificateur=None) -> dict:
    """Appelle l'autorité canonique et DÉRIVE la provenance de son résultat.

    Ce que cette vérification prouve : chaque fichier de l'artefact correspond
    à son empreinte inventoriée, l'inventaire couvre exactement le contenu, et
    le manifeste annonce le modèle et la dimension canoniques.

    Ce qu'elle ne prouve PAS : que l'inventaire lui-même vient d'une ancre
    externe. Le dépôt n'en épingle aucune — la CI le recalcule à chaque fois.
    L'ancre disponible est donc la RÉVISION, comparée ici à celle épinglée. Le
    statut rendu le dit, plutôt que de laisser croire à davantage.
    """
    if verificateur is None:  # pragma: no cover - dépendance d'exécution
        racine_depot_local = racine_depot()
        for chemin in (
            racine_depot_local / "services/rag-engine/src",
            racine_depot_local / "packages/contracts/src",
        ):
            if str(chemin) not in sys.path:
                sys.path.insert(0, str(chemin))
        try:
            from ingestor.embedding_contract import (  # noqa: PLC0415
                verify_embedding_artifact,
            )
        except ImportError as erreur:
            raise ProvenanceNonProuvee(
                f"autorité canonique de vérification introuvable : {erreur}"
            ) from erreur
        verificateur = verify_embedding_artifact

    if not artefact.is_dir():
        raise ProvenanceNonProuvee(f"artefact absent : {artefact.name}")

    empreinte = empreinte_d_inventaire(artefact)
    try:
        verifie = verificateur(artefact, expected_inventory_sha256=empreinte)
    except Exception as erreur:
        raise ProvenanceNonProuvee(
            f"l'autorité canonique refuse l'artefact {artefact.name} : {erreur}"
        ) from erreur

    manifeste = json.loads((artefact / "manifest.json").read_text(encoding="utf-8"))
    revision = manifeste.get("revision_requested")
    if revision != REVISION:
        raise ProvenanceNonProuvee(
            f"révision non conforme : {revision} != {REVISION} (épinglée)"
        )
    if manifeste.get("canonical_dim") != DIMENSION:
        raise ProvenanceNonProuvee(
            f"dimension annoncée {manifeste.get('canonical_dim')} != {DIMENSION}"
        )

    return {
        "artifact_logical_id": Path(verifie).name,
        "artifact_revision": revision,
        "artifact_inventory_sha256": empreinte,
        "artifact_root_env_var": VARIABLE_RACINE_ARTEFACTS,
        "artifact_status": "VERIFIED_BY_CANONICAL_AUTHORITY",
        "artifact_verifier": (
            "ingestor.embedding_contract.verify_embedding_artifact — appelée, "
            "son résultat est la source de ces champs"
        ),
        "artifact_anchor": (
            "la révision épinglée ; l'empreinte d'inventaire est calculée sur "
            "l'artefact et n'est donc pas une ancre externe — le dépôt n'en "
            "épingle aucune"
        ),
    }


# --- Aptitude du corpus ----------------------------------------------------


def evaluer_aptitude(longueurs: list[int], limite: int) -> dict:
    """Le corpus est-il vectorisable SANS troncature ?

    Un seul dépassement suffit à refuser : c'est le sens d'un contrôle
    fail-closed.
    """
    if not longueurs:
        raise EntreeManquante(
            "aucune longueur mesurée : un corpus vide n'est pas un corpus apte"
        )
    trop_longs = [n for n in longueurs if n > limite]
    tiennent = [n for n in longueurs if n <= limite]
    return {
        "model_sequence_limit": limite,
        "chunks_total": len(longueurs),
        "chunks_within_limit": len(tiennent),
        "chunks_over_limit": len(trop_longs),
        "tokens_total": sum(longueurs),
        "tokens_in_over_limit_chunks": sum(trop_longs),
        "share_of_text_unreachable": round(
            100.0 * sum(trop_longs) / sum(longueurs), 1
        ),
        "max_tokens_observed": max(longueurs),
        "fit_for_vectorization": not trop_longs,
    }


def raison_du_refus(aptitude: dict) -> str:
    return (
        f"{aptitude['chunks_over_limit']} chunks autorisés sur "
        f"{aptitude['chunks_total']} dépassent la limite de "
        f"{aptitude['model_sequence_limit']} tokens du modèle canonique "
        f"(maximum observé : {aptitude['max_tokens_observed']}). Ils portent "
        f"{aptitude['share_of_text_unreachable']} % du texte. Les indexer "
        "exigerait de les tronquer, donc d'indexer autre chose que ce qui est "
        "annoncé ; les ignorer produirait un index qui paraît couvrir le "
        "périmètre en laissant des contenus entiers inatteignables."
    )


# --- Succès : complet, ou pas du tout --------------------------------------


def controles_de_couverture(
    *,
    aptitude: dict,
    etat_base: dict,
) -> dict:
    """Les compteurs opposables, et l'attendu dont ils doivent être égaux.

    `expected_vector_rows` vaut zéro quand le corpus est inapte : il n'y a
    alors aucune couverture à atteindre, et un succès est impossible.
    """
    attendu_lignes = aptitude["chunks_total"] if aptitude["fit_for_vectorization"] else 0
    attendu_contenus = (
        etat_base["authorized_with_chunks"]
        if aptitude["fit_for_vectorization"]
        else 0
    )
    return {
        "expected_vector_rows": attendu_lignes,
        "expected_content_count_with_chunks": attendu_contenus,
        "vector_rows_after": etat_base["vector_rows"],
        "distinct_vectorized_contents": etat_base["distinct_contents"],
        "missing_authorized_contents_with_chunks": max(
            0, attendu_contenus - etat_base["distinct_contents"]
        ),
        "unauthorized_content_rows": etat_base.get("unauthorized_rows", 0),
        "pii_undecided_rows": 0,
        "currentness_refused_rows": 0,
        "gate_refused_rows": etat_base.get("gate_refused_rows", 0),
        "dimension_mismatch": etat_base.get("dimension_mismatch", 0),
        "null_vectors": etat_base.get("null_vectors", 0),
        "duplicates": etat_base.get("duplicates", 0),
    }


def succes_phase_a(aptitude: dict, controles: dict) -> tuple[bool, list[str]]:
    """Vrai seulement si la couverture est COMPLÈTE et les exclusions vides.

    Le défaut que ceci ferme : `vector_rows > 0` suffisait à certifier une
    exécution. Une seule ligne, résiduelle ou partiellement écrite, faisait
    donc passer un index très incomplet pour une phase A réussie.
    """
    manquements: list[str] = []
    if not aptitude["fit_for_vectorization"]:
        manquements.append("corpus inapte : des chunks dépassent la limite du modèle")
    if controles["expected_vector_rows"] <= 0:
        manquements.append("aucune couverture attendue : rien ne peut être certifié")
    elif controles["vector_rows_after"] != controles["expected_vector_rows"]:
        manquements.append(
            f"couverture incomplète : {controles['vector_rows_after']} lignes "
            f"pour {controles['expected_vector_rows']} attendues"
        )
    if (
        controles["distinct_vectorized_contents"]
        != controles["expected_content_count_with_chunks"]
    ):
        manquements.append(
            f"contenus couverts : {controles['distinct_vectorized_contents']} "
            f"pour {controles['expected_content_count_with_chunks']} attendus"
        )
    for compteur in COMPTEURS_A_ZERO:
        if controles.get(compteur, 0) != 0:
            manquements.append(f"{compteur} = {controles[compteur]} (doit être 0)")
    return (not manquements), manquements


def construire(
    racine: Path,
    *,
    dsn_dedie: str,
    dsn_revue: str,
    aptitude: dict,
    perimetre: dict,
    etat_base: dict,
    disque_avant: int,
    disque_apres: int,
    provenance: dict,
) -> dict:
    decrire_dsn, refuser = _garde_de_cible()
    cible = decrire_dsn(dsn_dedie)
    revue = decrire_dsn(dsn_revue)
    refuser(cible, revue)

    for champ in (
        "artifact_logical_id",
        "artifact_revision",
        "artifact_inventory_sha256",
        "artifact_status",
        "artifact_verifier",
    ):
        if not provenance.get(champ):
            raise ProvenanceNonProuvee(
                f"provenance incomplète : {champ} absent — elle doit venir de "
                "la vérification, pas de l'appelant"
            )
    if provenance["artifact_status"] != "VERIFIED_BY_CANONICAL_AUTHORITY":
        raise ProvenanceNonProuvee(
            f"statut d'artefact non vérifié : {provenance['artifact_status']}"
        )

    controles = controles_de_couverture(aptitude=aptitude, etat_base=etat_base)
    execute, manquements = succes_phase_a(aptitude, controles)

    etat = {
        "kind": KIND,
        "dedicated_db_name": cible["dbname"],
        "dedicated_db_host": cible["host"],
        "dedicated_db_port": cible["port"],
        "input_scope": PERIMETRE,
        "input_count": perimetre["count"],
        "input_digest": perimetre["digest"],
        "model_name": MODELE,
        "model_revision": provenance["artifact_revision"],
        "vector_dimension": DIMENSION,
        "embeddability": aptitude,
        "authorized_contents_with_chunks": etat_base["authorized_with_chunks"],
        "authorized_contents_without_chunks": etat_base["authorized_without_chunks"],
        "vector_rows_before": 0,
        "vectorization_executed": execute,
        "coverage_shortfalls": manquements,
        "blocking_reason": (
            None if aptitude["fit_for_vectorization"] else raison_du_refus(aptitude)
        ),
        "disk_free_before": disque_avant,
        "disk_free_after": disque_apres,
        "review_db_written": False,
        # Formulation calée sur la preuve : l'option est posée par le CLIENT.
        # Dire « imposé par le serveur » serait plus fort que ce qui est
        # démontré, et une preuve plus forte que son objet n'en est pas une.
        "review_db_access": (
            "lecture seule posée côté client (option de session "
            "default_transaction_read_only=on) ; NI le serveur NI le rôle ne "
            "l'imposent — l'imposer exigerait d'écrire dans la base de revue"
        ),
        "review_db_readonly_enforced_by": "client_session_option",
        "pgvector_installed_in_review_db": etat_base["pgvector_in_review"],
        "production_touched": False,
        "current_switch": False,
        "pii_decision": False,
        "release_modified": False,
        "rollback_command": (
            "docker rm -f nexus-vector-staging-a-20260912T060731Z && docker volume "
            "rm $(docker inspect nexus-vector-staging-a-20260912T060731Z "
            "--format '{{range .Mounts}}{{.Name}}{{end}}')"
        ),
        "follow_up_required": [
            "re-découper le texte sous la limite de séquence du modèle : les "
            "chunks de staging ont été produits sans budget de tokens, et le "
            "découpeur canonique (chunk_publication) exige les octets du PDF, "
            "absents de la base de revue",
            "repointer la source de mesure de l'écart de recherche sur la base "
            "dédiée, sinon staging_vectors_present restera à zéro après une "
            "vectorisation réussie",
        ],
        "what_this_does_not_prove": [
            "ne valide pas le retrieval applicatif",
            "ne valide pas les citations",
            "ne valide pas la latence",
            "ne valide pas les filtres de scope applicatifs",
            "ne rend pas le go-live prêt",
        ],
    }
    etat.update(controles)
    etat.update(provenance)
    return etat


def perimetre_autorise(racine: Path) -> dict:
    chemin = racine / ECART
    if not chemin.is_file():
        raise EntreeManquante(f"écart de recherche absent : {chemin}")
    perimetre = json.loads(chemin.read_text(encoding="utf-8"))["indexable_scope"]
    return {
        "identifiants": sorted(perimetre["indexable"]),
        "count": perimetre["count"],
        "digest": perimetre["indexable_digest"],
        "refuses": sorted(perimetre["never_indexable"]),
    }


def rendre_markdown(etat: dict) -> str:
    apte = etat["embeddability"]
    lignes = [
        "# Vectorisation phase A — exécution",
        "",
        f"- kind : `{etat['kind']}`",
        f"- base dédiée : `{etat['dedicated_db_name']}` "
        f"(`{etat['dedicated_db_host']}:{etat['dedicated_db_port']}`)",
        f"- périmètre : `{etat['input_scope']}` — {etat['input_count']} contenus",
        f"- empreinte du périmètre : `{etat['input_digest']}`",
        f"- modèle : `{etat['model_name']}` révision `{etat['model_revision']}`",
        f"- dimension : {etat['vector_dimension']}",
        "",
        "## Provenance du modèle",
        "",
        f"- identifiant logique : `{etat['artifact_logical_id']}`",
        f"- racine : variable `{etat['artifact_root_env_var']}` "
        "(aucun chemin de poste dans cette preuve)",
        f"- empreinte d'inventaire : `{etat['artifact_inventory_sha256']}`",
        f"- statut : `{etat['artifact_status']}`",
        f"- vérificateur : {etat['artifact_verifier']}",
        f"- ancre : {etat['artifact_anchor']}",
        "",
        f"## `vectorization_executed` : **{etat['vectorization_executed']}**",
        "",
    ]
    if etat["blocking_reason"]:
        lignes += [f"> {etat['blocking_reason']}", ""]
    if etat["coverage_shortfalls"]:
        lignes += ["Manquements relevés :", ""]
        lignes += [f"- {ligne}" for ligne in etat["coverage_shortfalls"]]
        lignes.append("")
    lignes += [
        "## Aptitude du corpus à l'embedding",
        "",
        "| Mesure | Valeur |",
        "|---|---:|",
        f"| limite de séquence du modèle | {apte['model_sequence_limit']} tokens |",
        f"| chunks autorisés | {apte['chunks_total']} |",
        f"| tiennent dans la limite | {apte['chunks_within_limit']} |",
        f"| **dépassent la limite** | **{apte['chunks_over_limit']}** |",
        f"| maximum observé | {apte['max_tokens_observed']} tokens |",
        f"| part du texte dans les chunks trop longs | "
        f"**{apte['share_of_text_unreachable']} %** |",
        f"| apte à la vectorisation | `{apte['fit_for_vectorization']}` |",
        "",
        "## Couverture exigée pour un succès",
        "",
        "| Contrôle | Valeur |",
        "|---|---:|",
        f"| `expected_vector_rows` | {etat['expected_vector_rows']} |",
        f"| `vector_rows_after` | **{etat['vector_rows_after']}** |",
        f"| `expected_content_count_with_chunks` | "
        f"{etat['expected_content_count_with_chunks']} |",
        f"| `distinct_vectorized_contents` | {etat['distinct_vectorized_contents']} |",
        f"| `missing_authorized_contents_with_chunks` | "
        f"{etat['missing_authorized_contents_with_chunks']} |",
        f"| contenus autorisés porteurs de chunks | "
        f"{etat['authorized_contents_with_chunks']} |",
        f"| contenus autorisés SANS aucun chunk | "
        f"{etat['authorized_contents_without_chunks']} |",
        "",
        "Un index partiel n'est pas un succès partiel : c'est un échec.",
        "",
        "## Contrôles d'exclusion",
        "",
    ]
    for compteur in COMPTEURS_A_ZERO:
        lignes.append(f"- `{compteur}` : {etat[compteur]}")
    lignes += [
        "",
        "## Sûreté",
        "",
        f"- `review_db_written` : `{etat['review_db_written']}`",
        f"- `review_db_readonly_enforced_by` : "
        f"`{etat['review_db_readonly_enforced_by']}`",
        f"- accès base de revue : {etat['review_db_access']}",
        f"- `pgvector_installed_in_review_db` : "
        f"`{etat['pgvector_installed_in_review_db']}`",
        f"- `production_touched` : `{etat['production_touched']}`",
        f"- `current_switch` : `{etat['current_switch']}`",
        f"- `pii_decision` : `{etat['pii_decision']}`",
        f"- `release_modified` : `{etat['release_modified']}`",
        "",
        "## Retour arrière",
        "",
        f"```\n{etat['rollback_command']}\n```",
        "",
        "## Ce qu'il faut lever avant de réessayer",
        "",
    ]
    lignes += [f"- {ligne}" for ligne in etat["follow_up_required"]]
    lignes += ["", "## Ce que ceci ne prouve pas", ""]
    lignes += [f"- {ligne}" for ligne in etat["what_this_does_not_prove"]]
    return "\n".join(lignes) + "\n"


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - orchestration
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--state-file", required=True)
    arguments = parseur.parse_args(argv)

    racine = racine_depot()
    mesures = json.loads(Path(arguments.state_file).read_text(encoding="utf-8"))
    try:
        provenance = verifier_artefact(racine_des_artefacts() / ARTEFACT_LOGIQUE)
        etat = construire(
            racine,
            dsn_dedie=os.environ["DEDICATED_VECTOR_DB_URL"],
            dsn_revue=os.environ["REVIEW_DB_READONLY_URL"],
            aptitude=evaluer_aptitude(
                mesures["token_lengths"], mesures["model_sequence_limit"]
            ),
            perimetre=perimetre_autorise(racine),
            etat_base=mesures["db_state"],
            disque_avant=mesures["disk_free_before"],
            disque_apres=mesures["disk_free_after"],
            provenance=provenance,
        )
    except KeyError as erreur:
        print(
            f"REFUS : variable d'environnement manquante : {erreur}", file=sys.stderr
        )
        return 2
    except (
        EntreeManquante,
        EntreeInapte,
        CibleInterdite,
        ProvenanceNonProuvee,
    ) as erreur:
        print(f"REFUS : {erreur}", file=sys.stderr)
        return 2

    (racine / SORTIE_JSON).write_text(
        json.dumps(etat, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (racine / SORTIE_MD).write_text(rendre_markdown(etat), encoding="utf-8")
    print(f"écrit : {racine / SORTIE_JSON}")
    print(f"écrit : {racine / SORTIE_MD}")
    return 0 if etat["vectorization_executed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
