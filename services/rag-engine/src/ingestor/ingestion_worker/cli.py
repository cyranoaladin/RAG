"""Point d'entrée CLI autonome du worker (LOT44e).

``python -m ingestor.ingestion_worker.cli [--once] [--max-iterations N]
[--poll-interval-s S]`` — jamais lancé automatiquement par ``api.py`` ou
``docker-compose.v2.yml`` (aucune référence, vérifié). Boucle de scheduling
volontairement simple (``time.sleep`` entre itérations vides) : le
déterminisme réel réside dans ``run_worker_iteration`` (LOT44e,
``runner.py``), pas dans cette boucle, qui n'est jamais testée comme une
boucle infinie — seul ``--once``/``--max-iterations`` est exercé par les
tests.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import psycopg

from ingestor.ingestion_control.db import get_ingestion_control_dsn
from ingestor.ingestion_worker.runner import WorkerDeps, run_worker_iteration
from ingestor.ingestion_worker.storage import (
    make_filesystem_artifact_reader,
    make_filesystem_artifact_store,
)

DEFAULT_POLL_INTERVAL_S = 5.0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Worker CLI LOT44e — traite un job à la fois.")
    parser.add_argument("--profiles-dir", required=True, type=Path)
    parser.add_argument("--artifact-store-dir", required=True, type=Path)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--once", action="store_true", help="Traite au plus un job puis quitte.")
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--poll-interval-s", type=float, default=DEFAULT_POLL_INTERVAL_S)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    deps = WorkerDeps(
        owner=args.owner,
        profiles_dir=args.profiles_dir,
        artifact_store=make_filesystem_artifact_store(args.artifact_store_dir),
        artifact_reader=make_filesystem_artifact_reader(args.artifact_store_dir),
    )

    max_iterations = 1 if args.once else args.max_iterations
    iterations_done = 0

    with psycopg.connect(get_ingestion_control_dsn()) as conn:
        while max_iterations is None or iterations_done < max_iterations:
            outcome = run_worker_iteration(conn, deps=deps)
            iterations_done += 1
            if outcome.worked:
                print(f"WORKER_ITERATION job_id={outcome.job_id} status={outcome.status}")
                if outcome.error:
                    print(f"WORKER_ITERATION_ERROR job_id={outcome.job_id}: {outcome.error}", file=sys.stderr)
            elif args.once:
                print("WORKER_ITERATION no_job_available")
                break
            else:
                time.sleep(args.poll_interval_s)

    return 0


if __name__ == "__main__":  # pragma: no cover - couvert par appel direct de main() dans les tests
    sys.exit(main())


__all__ = ["main"]
