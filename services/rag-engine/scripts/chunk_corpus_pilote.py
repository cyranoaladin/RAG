#!/usr/bin/env python3
"""Chunk the pilot corpus (Terminale: Maths, NSI, Philosophie, Référentiel candidat libre).

Usage: python scripts/chunk_corpus_pilote.py
Output: services/rag-engine/data/chunks/terminale/*.jsonl
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor.pedagogical_chunker import (
    TaggingConfig,
    chunk_file,
    load_taxonomy_notion_map,
    write_jsonl,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS = REPO_ROOT / "corpus"
TAXONOMY = REPO_ROOT / "services/rag-pedago/taxonomy"
OUTPUT = Path(__file__).resolve().parents[1] / "data/chunks/terminale"


def main() -> None:
    # Load taxonomy notion maps
    maths_notions = load_taxonomy_notion_map(TAXONOMY / "maths/terminale_specialite.yml")
    nsi_notions = load_taxonomy_notion_map(TAXONOMY / "nsi/terminale.yml")

    configs = [
        (
            CORPUS / "Specialites/SPE_MATHEMATIQUES.md",
            TaggingConfig(
                doc_id="spe-mathematiques",
                matiere="mathematiques",
                audience=["tous"],
                type_doc_default="cours",
                source_label="Programme Maths Terminale — BO spécial n°1 du 22/01/2019",
                source_uri="https://eduscol.education.gouv.fr/maths-terminale",
                rights="officiel_public",
                official=True,
                notion_map=maths_notions,
            ),
            OUTPUT / "mathematiques.jsonl",
        ),
        (
            CORPUS / "Specialites/SPE_NSI.md",
            TaggingConfig(
                doc_id="spe-nsi",
                matiere="nsi",
                audience=["tous"],
                type_doc_default="cours",
                source_label="Programme NSI Terminale — BO spécial n°8 du 25/07/2019",
                source_uri="https://eduscol.education.gouv.fr/nsi-terminale",
                rights="officiel_public",
                official=True,
                notion_map=nsi_notions,
            ),
            OUTPUT / "nsi.jsonl",
        ),
        (
            CORPUS / "Tronc_commun/TRONC_PHILOSOPHIE.md",
            TaggingConfig(
                doc_id="tronc-philosophie",
                matiere="philosophie",
                audience=["tous"],
                type_doc_default="cours",
                source_label="Programme Philosophie Terminale — eduscol",
                source_uri="https://eduscol.education.gouv.fr/philosophie-terminale",
                rights="officiel_public",
                official=True,
                notion_map=None,  # No taxonomy for philo — notions derived from titles
            ),
            OUTPUT / "philosophie.jsonl",
        ),
        (
            CORPUS / "REFERENTIEL_CANDIDAT_LIBRE.md",
            TaggingConfig(
                doc_id="referentiel-candidat-libre",
                matiere="orientation",
                audience=["libre"],
                type_doc_default="referentiel",
                source_label="Référentiel candidat libre — eduscol/education.gouv.fr",
                source_uri="https://eduscol.education.gouv.fr/candidats-individuels",
                rights="officiel_public",
                official=True,
                notion_map=None,
            ),
            OUTPUT / "referentiel_candidat_libre.jsonl",
        ),
    ]

    for md_path, config, output_path in configs:
        print(f"Chunking {md_path.name} -> {output_path.name}")
        chunks = chunk_file(md_path, config)
        write_jsonl(chunks, output_path)
        print(f"  {len(chunks)} chunks written")

    print(f"\nOutput directory: {OUTPUT}")


if __name__ == "__main__":
    main()
