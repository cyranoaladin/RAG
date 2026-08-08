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
    from ingestor.ingestion_control.attestation import (
        RoleAttestation,
        WorkerAttestationError,
        attest_runtime_role,
    )
    from ingestor.ingestion_control.db import get_ingestion_control_dsn
    from ingestor.ingestion_control.jobs import reap_expired_job_leases
    from ingestor.ingestion_control.lease_reaper import reap_expired_leases
    from ingestor.ingestion_profiles.startup_gate import enforce_production_manifest_gate
except (ImportError, ValueError):
    # Image Docker aplatie (LOT44f, ADR-0029) : "ingestor" n'existe pas comme
    # paquet — ingestion_control/ingestion_profiles sont importables
    # directement au premier niveau. Même discipline que api.py.
    from ingestion_control.attestation import (
        RoleAttestation,
        WorkerAttestationError,
        attest_runtime_role,
    )
    from ingestion_control.db import get_ingestion_control_dsn
    from ingestion_control.jobs import reap_expired_job_leases
    from ingestion_control.lease_reaper import reap_expired_leases
    from ingestion_profiles.startup_gate import (
        enforce_production_manifest_gate,
    )

from .runner import WorkerDeps, run_worker_iteration
from .storage import make_filesystem_artifact_reader, make_filesystem_artifact_store

DEFAULT_POLL_INTERVAL_S = 5.0


def _positive_int(raw: str) -> int:
    """Remédiation revue PR#90 (Cubic P2) : ``--max-iterations`` négatif ou
    nul produisait auparavant une boucle qui s'arrête immédiatement sans
    la moindre erreur (``iterations_done < max_iterations`` faux dès le
    départ) — silencieux, indiscernable d'une configuration correcte qui
    n'aurait simplement rien eu à faire. Un opérateur qui tape ``-1`` par
    erreur doit le savoir immédiatement."""
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {raw!r}")
    return value


def _finite_non_negative_float(raw: str) -> float:
    """Remédiation revue PR#90 (Cubic P2) : une valeur infinie/NaN/négative
    n'était rejetée qu'au premier passage dans ``time.sleep`` (erreur
    tardive, worker déjà démarré et sorti du service) — rejetée ici avant
    même de démarrer."""
    value = float(raw)
    if not (value >= 0) or value == float("inf"):
        raise argparse.ArgumentTypeError(
            f"must be a finite, non-negative number of seconds, got {raw!r}"
        )
    return value


def _non_blank_str(raw: str) -> str:
    if not raw.strip():
        raise argparse.ArgumentTypeError("must not be blank")
    return raw


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Worker CLI LOT44e — traite un job à la fois.")
    parser.add_argument("--profiles-dir", required=True, type=Path)
    parser.add_argument("--manifest-path", required=True, type=Path)
    parser.add_argument("--artifact-store-dir", required=True, type=Path)
    parser.add_argument("--owner", required=True, type=_non_blank_str)
    parser.add_argument(
        "--expected-role",
        required=True,
        type=_non_blank_str,
        help=(
            "Rôle PostgreSQL runtime attendu (LOT44f, item I) — vérifié contre "
            "current_user après connexion, indépendamment du DSN : le worker "
            "refuse de démarrer si la connexion réelle ne correspond pas, ou si "
            "le rôle porte un privilège excédant strictement le nécessaire "
            "(superutilisateur, CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS, "
            "propriété du schéma, appartenance à un autre rôle)."
        ),
    )
    parser.add_argument("--once", action="store_true", help="Traite au plus un job puis quitte.")
    parser.add_argument("--max-iterations", type=_positive_int, default=None)
    parser.add_argument(
        "--poll-interval-s", type=_finite_non_negative_float, default=DEFAULT_POLL_INTERVAL_S
    )
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


def _reap_expired_leases(conn: psycopg.Connection) -> None:
    """Libère les baux (jobs et ressources) expirés avant toute tentative de
    réclamation — remédiation revue PR#90 : sans cet appel, ``reap_expired_
    job_leases``/``reap_expired_leases`` n'étaient invoquées par aucun code
    non-test, un job/ressource dont le bail expire restait donc bloqué
    indéfiniment (``claim_job``/``claim_resource`` n'acceptent que
    ``status='queued'``/``resource_state`` éligible, jamais un ``'running'``
    au bail expiré) — y compris après un redémarrage de conteneur. Appelée à
    chaque itération (pas seulement au démarrage) : un bail détenu par un
    *autre* worker peut expirer pendant que celui-ci continue de tourner.
    Idempotent et non bloquant (``SKIP LOCKED``) — sûr à appeler à chaque
    itération, y compris quand rien n'a expiré."""
    reap_expired_job_leases(conn)
    reap_expired_leases(conn)
    conn.commit()


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    try:
        gate_result = enforce_production_manifest_gate(args.profiles_dir, args.manifest_path)
    except Exception as exc:  # noqa: BLE001 - frontière CLI volontaire, jamais silencieuse
        print(f"WORKER_STARTUP_GATE_FAILED: {exc}", file=sys.stderr)
        return 1

    # Traçabilité d'autorité (LOT44f, ADR-0031) : consigne, à chaque
    # démarrage, sous quelle autorité nommée et quelle empreinte de manifest
    # exacte ce worker opère — jamais un démarrage silencieux quant à
    # l'autorité effective.
    for (collection, profile_version), authority in gate_result.manifest.authorities.items():
        print(
            f"WORKER_STARTUP_AUTHORITY collection={collection} "
            f"profile_version={profile_version} approved_by={authority.approved_by} "
            f"approved_at={authority.approved_at} "
            f"manifest_fingerprint={gate_result.manifest.manifest_fingerprint}"
        )

    deps = WorkerDeps(
        owner=args.owner,
        # Remédiation revue PR#90 : le registre exact vérifié par le gate
        # ci-dessus, jamais un Path rechargé depuis le disque à chaque job
        # (cf. WorkerDeps.profile_registry).
        profile_registry=gate_result.registry,
        artifact_store=make_filesystem_artifact_store(args.artifact_store_dir),
        artifact_reader=make_filesystem_artifact_reader(args.artifact_store_dir),
        # LOT41A (item D) : l'empreinte du manifest réellement vérifié par
        # le gate ci-dessus, jamais recalculée ailleurs ni relue du disque.
        # Confrontée au manifest_digest de chaque autorisation : un worker
        # qui tourne sur un autre manifest que celui autorisé ne traite
        # plus aucun job de ce scope.
        manifest_digest=gate_result.manifest.manifest_fingerprint,
    )

    max_iterations = 1 if args.once else args.max_iterations
    iterations_done = 0

    with psycopg.connect(get_ingestion_control_dsn()) as conn:
        # Remédiation revue PR#90 (Cubic P1, revue incrémentale, item I) :
        # attestation obligatoire avant toute autre opération sur cette
        # connexion — un DSN mal configuré (ex. pointant vers le
        # superutilisateur du conteneur pgvector) ne doit jamais faire
        # tourner ce worker avec des privilèges non vérifiés, même une
        # seule itération.
        try:
            attestation: RoleAttestation = attest_runtime_role(conn, expected_role=args.expected_role)
        except WorkerAttestationError as exc:
            print(f"WORKER_ATTESTATION_FAILED: {exc}", file=sys.stderr)
            return 1
        print(f"WORKER_ATTESTATION_OK current_user={attestation.current_user}")

        _write_heartbeat(args.heartbeat_file)
        while max_iterations is None or iterations_done < max_iterations:
            _reap_expired_leases(conn)
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
