#!/usr/bin/env python3
"""Première passe d'attribution de scope sur les citations transversales.

Rejoue ``NEXUS-CITATION-SCOPE-ATTRIBUTION-V1`` sur le texte canonique GELÉ :
les chunks de ``drive_staging.chunks`` pour les documents dédouanés, les
``canonical_text`` par page de l'entrée de revue canonique pour les autres.

Aucune ré-extraction, aucun OCR, aucun re-chunking, aucun re-scan PII : le
corpus texte est déjà figé et cette passe le LIT.

La sortie ne contient aucun contexte brut — seulement l'intitulé normalisé et
son empreinte.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag_pedago.governance.attribution_citation import (  # noqa: E402
    BASES_AUTORISEES,
    BASES_INTERDITES,
    CONTRACT_ID,
    DISPOSITIONS,
    UniteTexte,
    attribuer_document,
)


def unites_du_document(sha: str, chunks: dict, racine_canonique: Path) -> list[UniteTexte]:
    """Les unités de texte GELÉ d'un document, dans l'ordre."""
    if sha in chunks:
        return [
            UniteTexte(identifiant=f"chunk:{c['chunk_index']}", rang=c["chunk_index"],
                       texte=c["text"], page=c["page_start"])
            for c in chunks[sha]
        ]
    dossier = racine_canonique / sha
    manifeste = json.loads((dossier / "document.json").read_text(encoding="utf-8"))
    return [
        UniteTexte(
            identifiant=f"page:{numero}", rang=numero, debut_de_page=True, page=numero,
            texte=(dossier / "pages" / f"page-{numero:04d}.txt").read_bytes().decode("utf-8"),
        )
        for numero in range(1, manifeste["page_count"] + 1)
    ]


def main() -> int:
    parseur = argparse.ArgumentParser()
    parseur.add_argument("--inventaire", type=Path, required=True)
    parseur.add_argument("--entree-canonique", type=Path, required=True)
    parseur.add_argument("--sortie", type=Path, required=True)
    parseur.add_argument("--dsn", default=os.environ.get("DRIVE_STAGING_DSN"))
    arguments = parseur.parse_args()
    if not arguments.dsn:
        parseur.error("DSN de staging requis (--dsn ou DRIVE_STAGING_DSN)")

    inventaire = json.loads(arguments.inventaire.read_text(encoding="utf-8"))
    attendues: dict[str, list[str]] = defaultdict(list)
    for occurrence in inventaire["occurrences"]:
        attendues[occurrence["content_sha256"]].append(occurrence["official_reference"])
    total_attendu = sum(len(v) for v in attendues.values())

    chunks: dict[str, list[dict]] = defaultdict(list)
    with psycopg.connect(arguments.dsn) as connexion:
        for artefact, index, page, texte in connexion.execute(
            "select artifact_id, chunk_index, page_start, text from drive_staging.chunks"
            " where artifact_id = any(%s) order by artifact_id, chunk_index",
            (sorted(attendues),),
        ).fetchall():
            chunks[artefact].append({"chunk_index": index, "page_start": page, "text": texte})

    occurrences = []
    for sha in sorted(attendues):
        occurrences.extend(attribuer_document(
            sha, unites_du_document(sha, chunks, arguments.entree_canonique), attendues[sha]))

    comptes = Counter(o.disposition for o in occurrences)
    if sum(comptes.values()) != total_attendu:
        raise SystemExit(
            f"REFUS : {sum(comptes.values())} dispositions pour {total_attendu} occurrences")
    inconnues = {o.attribution_basis for o in occurrences} - set(BASES_AUTORISEES) - {None}
    if inconnues:
        raise SystemExit(f"REFUS : fondement hors enum fermée — {sorted(inconnues)}")

    rapport = {
        "kind": CONTRACT_ID,
        "applied": False,
        "attribution_basis_enum": list(BASES_AUTORISEES),
        "forbidden_bases": list(BASES_INTERDITES),
        "raw_context_excluded": True,
        "frozen_text_only": True,
        "TRANSVERSAL_OCCURRENCES_TOTAL": total_attendu,
        **{disposition: comptes[disposition] for disposition in DISPOSITIONS},
        "bases_used": dict(Counter(
            o.attribution_basis for o in occurrences if o.attribution_basis)),
        "occurrences": sorted(
            ({
                "reference_occurrence_id": o.reference_occurrence_id,
                "content_sha256": o.content_sha256,
                "normalized_reference": o.normalized_reference,
                "disposition": o.disposition,
                "attributed_scope_levels": o.attributed_scope_levels,
                "attribution_basis": o.attribution_basis,
                "heading_text_normalized": o.heading_text_normalized,
                "heading_digest": o.heading_digest,
                "section_unit": o.section_unit,
                "section_start": o.section_start,
                "section_end": o.section_end,
                "textual_instances": o.textual_instances,
                "instances_in_section": o.instances_in_section,
                "conflict_bases": o.conflict_bases,
            } for o in occurrences),
            key=lambda o: (o["content_sha256"], o["normalized_reference"]),
        ),
    }
    arguments.sortie.write_text(
        json.dumps(rapport, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    print(f"TRANSVERSAL_OCCURRENCES_TOTAL = {total_attendu}")
    for disposition in DISPOSITIONS:
        print(f"{disposition} = {comptes[disposition]}")
    print(f"somme = {sum(comptes.values())}")
    print(f"fondements employés = {rapport['bases_used']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
