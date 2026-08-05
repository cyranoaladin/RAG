"""Point d'entrée CLI autonome du worker (LOT44e).

``python -m ingestor.ingestion_worker.cli [--once] [--max-iterations N]
[--poll-interval-s S]`` — jamais lancé automatiquement par ``api.py``
directement (aucune référence dans ce fichier), mais provisionné comme
service dédié par ``docker-compose.v2.yml`` depuis LOT44f (voir ADR-0029).
Boucle de scheduling volontairement simple (``time.sleep`` entre itérations
vides) : le déterminisme réel réside dans ``run_worker_iteration`` (LOT44e,
``runner.py``), pas dans cette boucle, qui n'est jamais testée comme une
boucle infinie — seul ``--once``/``--max-iterations`` est exercé par les
tests.

LOT44f/ADR-0029 : le gate de profils LOT44c (``enforce_production_manifest_
gate``) est appelé ici de façon inconditionnelle, avant toute connexion
PostgreSQL — ce processus n'a aucune raison d'exister sans plan de contrôle
d'ingestion gouvernée, contrairement à ``api.py`` qui sert aussi le
retrieval en lecture seule. Aucun moyen de le désactiver (pas de flag) —
même discipline fail-closed que le module ``startup_gate`` lui-même.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import psycopg

try:
    from ingestor.ingestion_control.db import get_ingestion_control_dsn
    from ingestor.ingestion_profiles.startup_gate import enforce_production_manifest_gate
except (ImportError, ValueError):
    # Image Docker aplatie (LOT44f, ADR-0029) : "ingestor" n'existe pas comme
    # paquet — ingestion_control/ingestion_profiles sont importables
    # directement au premier niveau. Même discipline que api.py.
    from ingestion_control.db import get_ingestion_control_dsn
    from ingestion_profiles.startup_gate import (
        enforce_production_manifest_gate,
    )

from .runner import WorkerDeps, run_worker_iteration
from .storage import make_filesystem_artifact_reader, make_filesystem_artifact_store

DEFAULT_POLL_INTERVAL_S = 5.0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Worker CLI LOT44e — traite un job à la fois.")
    parser.add_argument("--profiles-dir", required=True, type=Path)
    parser.add_argument("--manifest-path", required=True, type=Path)
    parser.add_argument("--artifact-store-dir", required=True, type=Path)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--once", action="store_true", help="Traite au plus un job puis quitte.")
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--poll-interval-s", type=float, default=DEFAULT_POLL_INTERVAL_S)
    parser.add_argument(
        "--heartbeat-file",
        type=Path,
        default=None,
        help=(
            "Optionnel (LOT44f) : fichier réécrit avec l'horodatage courant après "
            "chaque itération (réussie ou non) et une fois avant la première — "
            "sert uniquement de liveness check externe (ex. HEALTHCHECK Docker "
            "basé sur la fraîcheur du fichier). Aucune valeur par défaut : absent "
            "signifie pas de heartbeat écrit, comportement inchangé."
        ),
    )
    return parser


def _write_heartbeat(path: Path | None) -> None:
    if path is None:
        return
    path.write_text(str(time.time()), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    try:
        enforce_production_manifest_gate(args.profiles_dir, args.manifest_path)
    except Exception as exc:  # noqa: BLE001 - frontière CLI volontaire, jamais silencieuse
        print(f"WORKER_STARTUP_GATE_FAILED: {exc}", file=sys.stderr)
        return 1

    deps = WorkerDeps(
        owner=args.owner,
        profiles_dir=args.profiles_dir,
        artifact_store=make_filesystem_artifact_store(args.artifact_store_dir),
        artifact_reader=make_filesystem_artifact_reader(args.artifact_store_dir),
    )

    max_iterations = 1 if args.once else args.max_iterations
    iterations_done = 0

    with psycopg.connect(get_ingestion_control_dsn()) as conn:
        _write_heartbeat(args.heartbeat_file)
        while max_iterations is None or iterations_done < max_iterations:
            outcome = run_worker_iteration(conn, deps=deps)
            iterations_done += 1
            _write_heartbeat(args.heartbeat_file)
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
