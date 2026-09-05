"""Exécute la tranche verticale Drive → staging sur la racine réelle.

Tout ce qui désigne une ressource — compte de service, racine gouvernée,
base de staging — vient de l'environnement. Aucun chemin machine-local
n'est écrit ici : une preuve doit pouvoir nommer ce qu'elle a lu, et un
défaut codé en dur ne se laisse pas nommer.

Usage :

    NEXUS_GDRIVE_SERVICE_ACCOUNT_FILE=… \\
    NEXUS_GDRIVE_ROOT_FOLDER_ID=… \\
    NEXUS_PEDAGO_STAGING_DSN=… \\
    python -m rag_pedago.governance.drive_slice_cli \\
        --path "01_EDUSCOL_OFFICIEL/…/programme.pdf" \\
        --destination /tmp/tranche
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from rag_pedago.governance.drive_extraction import extract_pdf_pages
from rag_pedago.governance.drive_slice import run_slice
from rag_pedago.governance.drive_source import DriveSourceAdapter
from rag_pedago.governance.drive_staging_pg import PostgresStagingStore, staging_dsn
from rag_pedago.governance.drive_transport import (
    GoogleDriveTransport,
    real_sleep,
    root_folder_id,
    root_name,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        action="append",
        required=True,
        metavar="CHEMIN_RELATIF",
        help="chemin relatif à la racine gouvernée, à acquérir et à stager",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        required=True,
        help="répertoire où l'acquisition matérialise puis rehache l'arbre",
    )
    parser.add_argument(
        "--query-matiere",
        default=None,
        help="matière à relire dans le staging après la tranche",
    )
    parser.add_argument(
        "--query-motif",
        default=None,
        help="motif textuel à retrouver dans les chunks stagés",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    import psycopg

    adapter = DriveSourceAdapter(
        GoogleDriveTransport.from_environment(),
        root_folder_id=root_folder_id(),
        root_name=root_name(),
        max_attempts=5,
        sleep=real_sleep,
    )

    with psycopg.connect(staging_dsn()) as connection:
        store = PostgresStagingStore(connection)
        store.create_schema()
        report = run_slice(
            adapter,
            scope=set(args.path),
            destination=args.destination,
            store=store,
            extract_pages=extract_pdf_pages,
        )
        connection.commit()

        for line in report.lines():
            print(line)
        for path, reason in adapter.exclusions:
            print(f"EXCLUSION {reason} {path}")
        for artifact_id in report.artifact_ids:
            print(f"ARTIFACT_ID {artifact_id}")

        if args.query_matiere or args.query_motif:
            print("--- interrogation du staging ---")
            for row in store.query(matiere=args.query_matiere, motif=args.query_motif):
                print(row)
    return 0


if __name__ == "__main__":  # pragma: no cover - point d'entrée
    sys.exit(main())
