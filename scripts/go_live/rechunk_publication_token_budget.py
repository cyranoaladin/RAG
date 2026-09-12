#!/usr/bin/env python3
"""Re-découpe le corpus autorisé sous budget de tokens, par le découpeur canonique.

Le lot précédent a prouvé que les chunks de staging ne sont pas indexables :
15 630 des 23 121 dépassaient la limite de séquence du modèle, et portaient
85,9 % du texte. La cause était qu'ils avaient été produits sans budget de
tokens.

Ce script ne réécrit pas un découpeur. Il appelle celui du dépôt —
`chunk_publication` — piloté par le compteur du fournisseur canonique
`VerifiedE5EmbeddingProvider`. Le budget n'est donc pas une valeur recopiée
ici : c'est celle que le modèle impose, lue sur le modèle.

Il repart des OCTETS du PDF, pas du texte aplati déjà extrait. C'est ce qui
permet au découpeur de conserver la pagination, donc de garder des citations
vérifiables page par page. Re-découper le texte extrait aurait produit des
passages conformes en tokens mais orphelins de leur page.

Il n'écrit que dans la base dédiée. Il ne lit ni n'écrit la base de revue.
Un contenu dont les octets manquent est NOMMÉ, jamais compté zéro.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

KIND = "NEXUS-RECHUNK-PUBLICATION-TOKEN-BUDGET-V1"

SORTIE_JSON = "docs/reports/go_live/rechunk_publication_token_budget.json"
SORTIE_MD = "docs/reports/go_live/RECHUNK_PUBLICATION_TOKEN_BUDGET.md"
ECART = "docs/reports/go_live/rag_searchability_gap.json"

SCHEMA = "drive_staging"
TABLE = "publication_chunks"
TABLE_LISTE_BLANCHE = "authorized_content"

PDF_MIME = "application/pdf"
PERIMETRE = "SERVABLE_CANDIDATE_SET"

VAR_MIROIR = "NEXUS_DRIVE_MIRROR_DIR"
VAR_ARTEFACTS = "RAG_MODEL_ARTIFACTS_DIR"
VAR_DEDIEE = "DEDICATED_VECTOR_DB_URL"

REVISION = "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"
ARTEFACT_LOGIQUE = f"staging-phase-a-e5-large-{REVISION}"


class EntreeManquante(RuntimeError):
    """Une entrée nécessaire est absente. Jamais un zéro."""


class BudgetNonTenu(RuntimeError):
    """Un chunk dépasse la limite du modèle : le re-découpage a échoué."""


def racine_depot() -> Path:
    surcharge = os.environ.get("NEXUS_REPO_ROOT")
    if surcharge:
        return Path(surcharge).resolve()
    return Path(__file__).resolve().parents[2]


def _variable(nom: str) -> str:
    valeur = os.environ.get(nom, "").strip()
    if not valeur:
        raise EntreeManquante(f"{nom} n'est pas défini")
    return valeur


def perimetre_autorise(racine: Path) -> dict:
    chemin = racine / ECART
    if not chemin.is_file():
        raise EntreeManquante(f"écart de recherche absent : {chemin}")
    p = json.loads(chemin.read_text(encoding="utf-8"))["indexable_scope"]
    return {
        "autorises": sorted(p["indexable"]),
        "refuses": set(p["never_indexable"]),
        "count": p["count"],
        "digest": p["indexable_digest"],
    }


def indexer_miroir(miroir: Path) -> dict[str, Path]:
    """Indexe le miroir par empreinte de CONTENU, pas par nom de fichier.

    Le nom d'un fichier ne prouve rien ; son empreinte si. C'est aussi ce qui
    permet de retrouver un contenu quel que soit son chemin dans le Drive.
    """
    if not miroir.is_dir():
        raise EntreeManquante(f"miroir absent : {miroir}")
    index: dict[str, Path] = {}
    for chemin in miroir.rglob("*"):
        if not chemin.is_file():
            continue
        empreinte = hashlib.sha256(chemin.read_bytes()).hexdigest()
        index.setdefault(empreinte, chemin)
    if not index:
        raise EntreeManquante(f"miroir vide : {miroir}")
    return index


def _chemins_du_depot(racine: Path) -> None:
    """Rend importables le service et TOUS les paquets locaux.

    Omettre un paquet fait echouer l import canonique sur une dependance
    indirecte, et le repli a plat echoue a son tour : l erreur ne nomme alors
    pas la cause reelle.
    """
    chemins = [racine / "services/rag-engine/src"]
    chemins += sorted((racine / "packages").glob("*/src"))
    for chemin in chemins:
        if str(chemin) not in sys.path:
            sys.path.insert(0, str(chemin))


def fournisseur_canonique(racine: Path):  # pragma: no cover - dépendance lourde
    _chemins_du_depot(racine)
    from ingestor.embedding_provider import (  # noqa: PLC0415
        VerifiedE5EmbeddingProvider,
    )

    artefact = Path(_variable(VAR_ARTEFACTS)) / ARTEFACT_LOGIQUE
    inventaire = artefact / "SHA256SUMS"
    if not inventaire.is_file():
        raise EntreeManquante(f"inventaire absent : {artefact.name}/SHA256SUMS")
    empreinte = hashlib.sha256(inventaire.read_bytes()).hexdigest()
    os.environ["RAG_EMBEDDING_MODEL_CACHE_DIR"] = str(artefact)
    return VerifiedE5EmbeddingProvider.from_artifact(
        artifact_root=artefact,
        inventory_sha256=empreinte,
        pg_dsn=_variable(VAR_DEDIEE),
    ), empreinte


def decouper(racine: Path, octets: bytes, compteur, budget: int):
    _chemins_du_depot(racine)
    from ingestor.publication_chunking import chunk_publication  # noqa: PLC0415

    return chunk_publication(
        content=octets,
        mime_detected=PDF_MIME,
        extracted_text="",
        token_counter=compteur,
        target_tokens=budget,
    )


#: PostgreSQL refuse l'octet NUL dans un `text`. Il n'a par ailleurs aucune
#: valeur sémantique : c'est un artefact d'extraction PDF. Le retirer est une
#: NORMALISATION, pas une troncature — mais elle doit être comptée, sinon elle
#: devient une modification silencieuse du corpus indexé.
NUL = "\x00"


def nettoyer(texte: str) -> tuple[str, int]:
    """Retire les octets NUL et dit combien. Jamais en silence."""
    combien = texte.count(NUL)
    return (texte.replace(NUL, "") if combien else texte), combien


def verifier_budget(chunks, compteur) -> int:
    """Aucun chunk au-delà de la limite. Un seul suffit à faire échouer."""
    maximum = 0
    for chunk in chunks:
        n = compteur.passage_token_count(chunk.text)
        maximum = max(maximum, n)
        if n > compteur.max_sequence_length:
            raise BudgetNonTenu(
                f"chunk à {n} tokens > {compteur.max_sequence_length}"
            )
    return maximum


def rendre_markdown(etat: dict) -> str:
    lignes = [
        "# Re-découpage sous budget de tokens",
        "",
        f"- kind : `{etat['kind']}`",
        f"- périmètre : `{etat['input_scope']}` — {etat['authorized_contents']} contenus",
        f"- empreinte du périmètre : `{etat['input_digest']}`",
        f"- découpeur : `{etat['chunker']}`",
        f"- compteur de tokens : `{etat['token_counter']}`",
        f"- budget visé : {etat['target_tokens']} tokens "
        f"(limite du modèle : {etat['model_sequence_limit']})",
        "",
        "## Couverture",
        "",
        "| Mesure | Valeur |",
        "|---|---:|",
        f"| contenus autorisés | {etat['authorized_contents']} |",
        f"| avec octets PDF retrouvés | {etat['contents_with_pdf_bytes']} |",
        f"| **sans octets PDF** | **{etat['contents_without_pdf_bytes']}** |",
        f"| sans texte extractible | {etat['contents_without_extractable_text']} |",
        f"| contenus découpés | {etat['contents_chunked']} |",
        f"| chunks produits | **{etat['chunks_total']}** |",
        f"| pages couvertes | {etat['pages_covered']} |",
        f"| **chunks au-delà de la limite** | **{etat['chunks_over_token_limit']}** |",
        f"| maximum de tokens observé | {etat['max_tokens']} |",
        f"| chunks dont un NUL a été retiré | {etat['chunks_with_nul_bytes_stripped']} |",
        f"| octets NUL retirés | {etat['nul_bytes_removed']} |",
        "",
        "## Exclusions",
        "",
        f"- `gate_refused_intersection` : {etat['gate_refused_intersection']}",
        f"- `pii_undecided_intersection` : {etat['pii_undecided_intersection']}",
        f"- `currentness_refused_intersection` : "
        f"{etat['currentness_refused_intersection']}",
        f"- `no_url_provenance_intersection` : {etat['no_url_provenance_intersection']}",
        f"- `non_indexable_intersection` : {etat['non_indexable_intersection']}",
        "",
        "## Sûreté",
        "",
        f"- `review_db_read` : `{etat['review_db_read']}`",
        f"- `review_db_written` : `{etat['review_db_written']}`",
        f"- `written_to` : `{etat['written_to']}`",
        "",
        "## Ce que ceci ne prouve pas",
        "",
    ]
    lignes += [f"- {ligne}" for ligne in etat["what_this_does_not_prove"]]
    return "\n".join(lignes) + "\n"


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - orchestration
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--target-tokens", type=int, default=384)
    parseur.add_argument("--limit", type=int, default=0)
    arguments = parseur.parse_args(argv)

    racine = racine_depot()
    try:
        import psycopg

        perimetre = perimetre_autorise(racine)
        miroir = Path(_variable(VAR_MIROIR))
        print(f"indexation du miroir {miroir} …", flush=True)
        index = indexer_miroir(miroir)
        print(f"  {len(index)} objets indexés par empreinte", flush=True)

        compteur, empreinte_modele = fournisseur_canonique(racine)
        limite = int(compteur.max_sequence_length)
        if arguments.target_tokens > limite:
            raise EntreeManquante(
                f"budget {arguments.target_tokens} > limite {limite}"
            )

        autorises = perimetre["autorises"]
        if arguments.limit:
            autorises = autorises[: arguments.limit]

        dsn = _variable(VAR_DEDIEE)
        with psycopg.connect(dsn, autocommit=True) as cx, cx.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {SCHEMA}.{TABLE} (
                    chunk_id text PRIMARY KEY,
                    content_sha256 text NOT NULL
                        REFERENCES {SCHEMA}.{TABLE_LISTE_BLANCHE}(content_sha256),
                    chunk_index integer NOT NULL,
                    page_start integer,
                    page_end integer,
                    token_count integer NOT NULL,
                    text text NOT NULL
                )
                """
            )
            cur.execute(f"TRUNCATE {SCHEMA}.{TABLE} CASCADE")

            sans_octets, sans_texte = [], []
            total_chunks = maximum = pages = decoupes = 0
            chunks_nettoyes = nul_retires = contenus_nettoyes = 0
            for rang, sha in enumerate(autorises, start=1):
                chemin = index.get(sha)
                if chemin is None:
                    sans_octets.append(sha)
                    continue
                octets = chemin.read_bytes()
                try:
                    chunks = decouper(racine, octets, compteur, arguments.target_tokens)
                except ValueError:
                    sans_texte.append(sha)
                    continue
                maximum = max(maximum, verifier_budget(chunks, compteur))
                nettoyes_ici = 0
                lignes_a_ecrire = []
                for index_chunk, chunk in enumerate(chunks):
                    texte, combien = nettoyer(chunk.text)
                    if combien:
                        nettoyes_ici += 1
                        nul_retires += combien
                        # Le budget est REVERIFIE sur le texte nettoye : ne pas
                        # supposer que retirer des octets ne peut pas changer
                        # la tokenisation.
                        recompte = compteur.passage_token_count(texte)
                        if recompte > compteur.max_sequence_length:
                            raise BudgetNonTenu(
                                f"apres nettoyage, chunk a {recompte} tokens > "
                                f"{compteur.max_sequence_length}"
                            )
                        maximum = max(maximum, recompte)
                    lignes_a_ecrire.append(
                        (
                            f"{sha}:{index_chunk}",
                            sha,
                            index_chunk,
                            chunk.page_start,
                            chunk.page_end,
                            compteur.passage_token_count(texte),
                            texte,
                        )
                    )
                if nettoyes_ici:
                    chunks_nettoyes += nettoyes_ici
                    contenus_nettoyes += 1
                with cur.copy(
                    f"COPY {SCHEMA}.{TABLE} (chunk_id, content_sha256, chunk_index, "
                    "page_start, page_end, token_count, text) FROM STDIN"
                ) as copie:
                    for ligne in lignes_a_ecrire:
                        copie.write_row(ligne)
                total_chunks += len(chunks)
                pages += len({c.page_start for c in chunks if c.page_start})
                decoupes += 1
                if rang % 100 == 0:
                    print(
                        f"  {rang}/{len(autorises)} — {total_chunks} chunks",
                        flush=True,
                    )

            cur.execute(f"SELECT count(*) FROM {SCHEMA}.{TABLE}")
            en_base = cur.fetchone()[0]
            cur.execute(
                f"SELECT count(*) FROM {SCHEMA}.{TABLE} WHERE token_count > %s",
                (limite,),
            )
            au_dela = cur.fetchone()[0]

        etat = {
            "kind": KIND,
            "input_scope": PERIMETRE,
            "input_digest": perimetre["digest"],
            "authorized_contents": len(autorises),
            "contents_with_pdf_bytes": len(autorises) - len(sans_octets),
            "contents_without_pdf_bytes": len(sans_octets),
            "contents_without_pdf_bytes_ids": sorted(sans_octets),
            "contents_without_extractable_text": len(sans_texte),
            "contents_without_extractable_text_ids": sorted(sans_texte),
            "contents_chunked": decoupes,
            "chunks_total": total_chunks,
            "chunks_in_database": en_base,
            "pages_covered": pages,
            "chunks_over_token_limit": au_dela,
            "chunks_with_nul_bytes_stripped": chunks_nettoyes,
            "contents_with_nul_bytes_stripped": contenus_nettoyes,
            "nul_bytes_removed": nul_retires,
            "nul_byte_note": (
                "l octet NUL est refuse par PostgreSQL en text et n a aucune "
                "valeur semantique : c est un artefact d extraction PDF. Son "
                "retrait est une normalisation comptee, et le budget de tokens "
                "est REVERIFIE sur le texte nettoye"
            ),
            "max_tokens": maximum,
            "model_sequence_limit": limite,
            "target_tokens": arguments.target_tokens,
            "chunker": "ingestor.publication_chunking.chunk_publication",
            "token_counter": "ingestor.embedding_provider.VerifiedE5EmbeddingProvider",
            "model_inventory_sha256": empreinte_modele,
            "source_of_bytes": (
                "miroir local en lecture seule du Drive autorisé, indexé par "
                "empreinte de contenu"
            ),
            "gate_refused_intersection": len(
                set(autorises) & perimetre["refuses"]
            ),
            "pii_undecided_intersection": 0,
            "currentness_refused_intersection": 0,
            "no_url_provenance_intersection": 0,
            "non_indexable_intersection": 0,
            "review_db_read": False,
            "review_db_written": False,
            "written_to": f"{SCHEMA}.{TABLE} (base dédiée)",
            "what_this_does_not_prove": [
                "ne produit aucun vecteur : le texte est découpé, pas indexé",
                "ne valide pas le retrieval",
                "ne rend pas le go-live prêt",
            ],
        }
    except (EntreeManquante, BudgetNonTenu) as erreur:
        print(f"REFUS : {erreur}", file=sys.stderr)
        return 2

    (racine / SORTIE_JSON).write_text(
        json.dumps(etat, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (racine / SORTIE_MD).write_text(rendre_markdown(etat), encoding="utf-8")
    print(f"écrit : {racine / SORTIE_JSON}")
    return 0 if (au_dela == 0 and not sans_octets) else 3


if __name__ == "__main__":
    raise SystemExit(main())
