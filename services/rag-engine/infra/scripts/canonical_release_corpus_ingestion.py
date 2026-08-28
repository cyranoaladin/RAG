#!/usr/bin/env python3
"""Ingestion canonique de la FIRST_SERVABLE_RELEASE (P0-L1D).

Ce script exécute le pipeline gouverné réel de production :
1. Charge le registre de release et tous les 18 manifests-sujets scellés.
2. Pour chacun des 26 artefacts :
   - Récupère les octets canoniques du document officiel.
   - Vérifie le SHA-256 contre l'inventaire éligible scellé.
   - Découpe en chunks réels via `chunk_publication` avec le modèle e5-large.
   - Calcule les embeddings réels 1024-d normés via `SentenceTransformer`.
   - Écrit dans PostgreSQL les 26 artefacts, 26 placements et 730 chunks
     avec tous les attributs gouvernés requis (statuts, versions, modèles).
3. Exécute `validate_release_registry_readiness` pour prouver à 100% la réconciliation.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import urllib.request
from pathlib import Path
from typing import Any

import psycopg
from nexus_contracts.embedding_utils import format_passage
from sentence_transformers import SentenceTransformer

from ingestor.publication_chunking import PDF_MIME_TYPE, chunk_publication
from ingestor.release_readiness import (
    load_release_registry_file,
    validate_release_registry_readiness,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("release_ingestion")


class ModelTokenCounter:
    def __init__(self, model: SentenceTransformer) -> None:
        self.model = model
        self.max_sequence_length = 512

    def passage_token_count(self, text: str) -> int:
        return len(self.model.tokenizer.encode("passage: " + text, add_special_tokens=True))


def fetch_artifact_bytes(source_url: str, expected_sha256: str, cache_dir: Path) -> bytes:
    """Télécharge ou relit depuis le cache local le PDF vérifié par SHA256."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_file = cache_dir / f"{expected_sha256}.pdf"
    if cached_file.is_file():
        raw = cached_file.read_bytes()
        if hashlib.sha256(raw).hexdigest() == expected_sha256:
            return raw

    logger.info("Téléchargement de %s (SHA: %s...)", source_url, expected_sha256[:12])
    req = urllib.request.Request(source_url, headers={"User-Agent": "Mozilla/5.0 (NexusRAG/1.0)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()

    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != expected_sha256:
        raise ValueError(
            f"Empreinte SHA256 non conforme pour {source_url} : attendu={expected_sha256}, obtenu={actual_sha}"
        )

    cached_file.write_bytes(raw)
    return raw


def ingest_first_servable_release(
    *,
    review_status: str,
    db_dsn: str,
    registry_path: Path,
    registry_sha256: str,
    model_path: Path,
    cache_dir: Path,
) -> None:
    logger.info("Chargement du registre de release depuis %s...", registry_path)
    registry = load_release_registry_file(registry_path, registry_sha256)
    logger.info(
        "Registre chargé avec succès : %d collections, %d manifests",
        len(registry.collections),
        len(registry.manifests),
    )

    logger.info("Chargement du modèle d'embedding depuis %s...", model_path)
    model = SentenceTransformer(str(model_path), local_files_only=True)
    token_counter = ModelTokenCounter(model)

    # Récupérer l'ensemble des 26 artefacts uniques et leurs placements depuis tous les manifests
    artifacts_map: dict[str, Any] = {}
    for manifest_binding in registry.manifests:
        for artifact in manifest_binding.expectation.artifacts:
            if artifact.content_sha256 not in artifacts_map:
                artifacts_map[artifact.content_sha256] = artifact

    logger.info("Total des artefacts uniques à ingérer : %d", len(artifacts_map))

    total_chunks_written = 0
    total_placements_written = 0
    total_artifacts_written = 0

    with psycopg.connect(db_dsn) as conn:
        with conn.cursor() as cur:
            for art_idx, (content_sha, exp_artifact) in enumerate(artifacts_map.items(), 1):
                logger.info(
                    "[%02d/%02d] Traitement de l'artefact %s (%s)...",
                    art_idx,
                    len(artifacts_map),
                    content_sha[:12],
                    exp_artifact.title,
                )

                raw_bytes = fetch_artifact_bytes(
                    source_url=exp_artifact.source_url,
                    expected_sha256=content_sha,
                    cache_dir=cache_dir,
                )

                # 1. Insertion dans public.rag_artifacts
                import urllib.parse
                source_kind = urllib.parse.urlparse(exp_artifact.source_url).hostname or "eduscol.education.gouv.fr"
                cur.execute(
                    """
                    INSERT INTO public.rag_artifacts (
                        artifact_id, content_sha256, source_label, source_uri,
                        rights, official, source_kind, type_doc, ingestion_artifact_id
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, gen_random_uuid()
                    )
                    ON CONFLICT (artifact_id) DO NOTHING
                    """,
                    (
                        content_sha,
                        content_sha,
                        source_kind,
                        exp_artifact.source_url,
                        "officiel_public",
                        True,
                        source_kind,
                        exp_artifact.type_doc,
                    ),
                )
                total_artifacts_written += 1

                # 2. Chunking & Embeddings
                chunks = chunk_publication(
                    content=raw_bytes,
                    mime_detected=PDF_MIME_TYPE,
                    extracted_text="",
                    token_counter=token_counter,
                )

                if len(chunks) != len(exp_artifact.chunks):
                    raise ValueError(
                        f"Nombre de chunks générés ({len(chunks)}) != attendu ({len(exp_artifact.chunks)}) pour {content_sha}"
                    )

                passages = [format_passage(chunk.text) for chunk in chunks]
                embeddings = model.encode(passages, normalize_embeddings=True, show_progress_bar=False)

                # 3. Insertion dans public.rag_chunks
                for idx, (chunk, emb, exp_chunk) in enumerate(zip(chunks, embeddings, exp_artifact.chunks, strict=True)):
                    text = chunk.text
                    chunk_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    chunk_id = hashlib.sha256(f"{content_sha}:{idx}:{chunk_sha}".encode()).hexdigest()

                    if chunk_id != exp_chunk["chunk_id"]:
                        raise ValueError(f"Chunk ID mismatch at index {idx} pour {content_sha}")

                    vector_str = "[" + ",".join(f"{c:.8f}" for c in emb) + "]"

                    # Récupérer les données du premier placement pour les métadonnées de chunk
                    plc = exp_artifact.placements[0]
                    cur.execute(
                        """
                        INSERT INTO public.rag_chunks (
                            chunk_id, doc_id, chunk_sha256, vector,
                            collection, niveau, voie, audience, matiere,
                            statut_enseignement, domain, source_label, source_uri,
                            rights, type_doc, official, text, chunk_index,
                            page_start, page_end, review_status, model,
                            source_kind, tenant, candidat,
                            visibility, school_year, programme_version, artifact_id
                        ) VALUES (
                            %s, %s, %s, %s::vector,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s, %s
                        )
                        ON CONFLICT (chunk_id) DO NOTHING
                        """,
                        (
                            chunk_id,
                            content_sha,
                            chunk_sha,
                            vector_str,
                            exp_artifact.collection,
                            plc["niveau"],
                            plc["voie"],
                            ["tous"],
                            plc["matiere"],
                            plc["statut_enseignement"],
                            "lycee" if "terminale" in plc["niveau"] or "premiere" in plc["niveau"] or "seconde" in plc["niveau"] else "college",
                            source_kind,
                            exp_artifact.source_url,
                            "officiel_public",
                            exp_artifact.type_doc,
                            True,
                            text,
                            idx,
                            chunk.page_start,
                            chunk.page_end,
                            review_status,
                            exp_artifact.embedding_model,
                            source_kind,
                            plc["tenant"],
                            plc["candidat"],
                            plc["visibility"],
                            plc["school_year"],
                            plc["programme_version"],
                            content_sha,
                        ),
                    )
                    total_chunks_written += 1

                # 4. Insertion dans public.rag_artifact_placements
                for plc in exp_artifact.placements:
                    cur.execute(
                        """
                        INSERT INTO public.rag_artifact_placements (
                            placement_id, artifact_id, collection, tenant, niveau, voie,
                            audience, matiere, statut_enseignement, candidat, visibility,
                            school_year, programme_version, currentness, placement_status,
                            review_status, source_scope, source_placement_id, source_path,
                            source_uri, authorization_id, publication_attestation_id
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, gen_random_uuid()
                        )
                        ON CONFLICT (placement_id) DO NOTHING
                        """,
                        (
                            plc["placement_id"],
                            content_sha,
                            plc["collection"],
                            plc["tenant"],
                            plc["niveau"],
                            plc["voie"],
                            ["tous"],
                            plc["matiere"],
                            plc["statut_enseignement"],
                            plc["candidat"],
                            plc["visibility"],
                            plc["school_year"],
                            plc["programme_version"],
                            "current",
                            "active",
                            review_status,
                            plc["source_scope"],
                            plc["source_placement_id"],
                            exp_artifact.source_path,
                            exp_artifact.source_url,
                            f"prerentree-2026-2027-{plc['collection']}-v1",
                        ),
                    )
                    total_placements_written += 1

        conn.commit()

    logger.info("Ingestion PostgreSQL terminée.")
    logger.info("Artefacts: %d, Placements: %d, Chunks: %d", total_artifacts_written, total_placements_written, total_chunks_written)

    logger.info("Lancement de la réconciliation exacte du release database...")
    with psycopg.connect(db_dsn) as conn:
        reports = validate_release_registry_readiness(registry, conn)

    all_ready = True
    for col, rep in reports.items():
        if not rep.ready:
            all_ready = False
            logger.error("Échec de réconciliation pour la collection %s : %s", col, rep.blockers)
        else:
            logger.info("Collection %s : READY (PASS)", col)

    if not all_ready:
        raise RuntimeError("La réconciliation globale de release a échoué.")

    logger.info("RELEASE_DATABASE_RECONCILIATION=PASS")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingestion canonique de la FIRST_SERVABLE_RELEASE")
    parser.add_argument("--db-dsn", default=os.environ.get("PG_RAG_DSN", "host=127.0.0.1 port=5435 dbname=ragdb user=raguser password=ragpassword"))
    parser.add_argument("--registry-path", type=Path, default=Path("services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json"))
    # L'empreinte du registre est une ANCRE EXTERNE : elle vaut par le fait
    # qu'elle vient d'ailleurs que du fichier qu'elle atteste. Un littéral codé
    # en dur ici était un épinglage silencieux — périmé à la première
    # ré-émission de release, et invisible jusqu'au premier échec.
    #
    # Elle est désormais lue depuis la configuration de déploiement, où
    # `RAG_RELEASE_REGISTRY_SHA256` est déjà l'ancre du runtime : une seule
    # valeur, un seul endroit à mettre à jour (cf. docs/runbooks/release_reseal.md).
    parser.add_argument(
        "--registry-sha256",
        default=os.environ.get("RAG_RELEASE_REGISTRY_SHA256"),
        help=(
            "Empreinte attendue du registre de release. Défaut : variable "
            "RAG_RELEASE_REGISTRY_SHA256. Jamais dérivée du fichier lui-même."
        ),
    )
    # `review_status` était un littéral `"reviewed"` : le script AFFIRMAIT une
    # décision humaine pour tout contenu qu'il ingérerait jamais, y compris
    # celui que personne n'aurait examiné. Le contrat est explicite —
    # `REVIEWED` signifie « la décision humaine a été validée »
    # (`nexus_contracts.resource_state`), quand `RETRIEVAL_ELIGIBLE` est un
    # constat automatique. Affirmer l'un pour l'autre était le défaut de ce
    # dépôt appliqué à la revue : un contrôle qui affirme plus qu'il n'a vérifié.
    #
    # `needs_review` par défaut créerait un blocage circulaire :
    # `release_readiness` compte `wrong_review_status` comme bloqueur, la
    # release devient non prête, l'ingestor refuse de démarrer — et c'est lui
    # qui héberge `POST /review/decide`. Le service qui doit enregistrer la
    # décision ne démarrerait plus.
    #
    # Donc REQUIS et SANS DÉFAUT : chaque ingestion déclare explicitement ce
    # qu'elle affirme, et l'omission échoue au lieu d'hériter.
    parser.add_argument(
        "--review-status",
        required=True,
        choices=["needs_review", "reviewed"],
        help=(
            "Statut de revue inscrit en base. `reviewed` AFFIRME qu'une "
            "décision humaine a été prise sur ce contenu : ne le passer que "
            "si c'est vrai, et consigner la décision dans docs/reviews/."
        ),
    )
    # Troisième occurrence du même motif : un chemin de machine personnelle
    # figé comme défaut de code partagé, après `--cache-dir=/tmp/...` et
    # `NEXUS_SEALED_CORPUS_ROOT`. Un défaut est une décision : celui-ci
    # divulguait un nom d'utilisateur et ne fonctionnait que sur un poste.
    #
    # Correctif uniforme : lire la configuration, aucun défaut deviné, échec
    # explicite si non configuré.
    parser.add_argument(
        "--model-path",
        type=Path,
        default=(
            Path(os.environ["RAG_EMBEDDING_MODEL_ARTIFACT_DIR"])
            if os.environ.get("RAG_EMBEDDING_MODEL_ARTIFACT_DIR")
            else None
        ),
        help=(
            "Répertoire de l'artefact embedding. Défaut : variable "
            "RAG_EMBEDDING_MODEL_ARTIFACT_DIR. Aucun chemin n'est deviné."
        ),
    )
    # Le miroir PDF n'est PAS un cache de commodité : c'est une pièce d'archive.
    # Si Éduscol réédite un document, son empreinte ne correspondra plus à celle
    # scellée par la release, et ce miroir devient la seule source des octets
    # exacts sur lesquels l'index a été construit.
    #
    # Le défaut était `/tmp/nexus_corpus_pdf_cache`. `/tmp` a déjà emporté deux
    # fois des éléments dont dépendait la pile (surcharges Compose du projet
    # `infra`, puis ce miroir lui-même). Le défaut pointe désormais un
    # emplacement durable ; `NEXUS_CORPUS_PDF_MIRROR` reste prioritaire.
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(
            os.environ.get("NEXUS_CORPUS_PDF_MIRROR", "")
            or Path.home() / "sauvegardes-rag" / "corpus-pdf-mirror"
        ),
    )
    args = parser.parse_args()
    if not args.model_path:
        parser.error(
            "chemin de l'artefact embedding absent : passer --model-path ou "
            "définir RAG_EMBEDDING_MODEL_ARTIFACT_DIR. Deviner un chemin de "
            "machine ferait dépendre une ingestion gouvernée d'un poste précis."
        )
    if not args.registry_sha256:
        parser.error(
            "empreinte du registre absente : passer --registry-sha256 ou définir "
            "RAG_RELEASE_REGISTRY_SHA256. Une ingestion sans ancre externe ne "
            "prouve rien sur le registre qu'elle consomme."
        )

    ingest_first_servable_release(
        db_dsn=args.db_dsn,
        registry_path=args.registry_path,
        registry_sha256=args.registry_sha256,
        model_path=args.model_path,
        review_status=args.review_status,
        cache_dir=args.cache_dir,
    )


if __name__ == "__main__":
    main()
