"""Outil opérateur de création de job d'ingestion (LOT44f, ADR-0031).

Remplace le rôle que jouait ``ingest_v2_bridge.py``/``/ingest/v2`` dans le
prototype LOT44f initial : sur le runtime canonique (``api_v2.py``,
ADR-0024), il n'existe et ne doit exister aucun endpoint HTTP d'écriture
d'ingestion — un tel endpoint recréerait exactement le writer public que
ADR-0024 a fermé. La création de job passe donc par cet outil, invoqué
uniquement par un opérateur humain via ``docker exec`` sur le conteneur
``ingestion-worker`` (jamais par un processus réseau, jamais par api_v2.py).

Ne contourne jamais le moteur LOT44c : applique le même gate
(``enforce_production_manifest_gate``) que le worker lui-même avant de
créer quoi que ce soit, puis valide le scope contre le profil sélectionné
(``validate_scope_against_profile``) — un scope qui ne passerait pas cette
validation ne doit jamais atteindre la file d'attente (échec immédiat et
lisible pour l'opérateur, plutôt qu'un job qui finirait en ``dead_letter``
après un cycle de traitement complet par le worker).

N'invente aucune valeur : chaque dimension de scope, chaque champ candidat
et le ``profile_version`` sont des arguments explicites, jamais devinés.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from uuid import UUID

import psycopg
from nexus_contracts.ingestion import ResourceScope

try:
    from ingestor.ingestion_control.db import get_ingestion_control_dsn
    from ingestor.ingestion_control.jobs import create_job
    from ingestor.ingestion_control.provisioning import create_ingestion_run
    from ingestor.ingestion_profiles.registry import (
        load_profile_registry,
        select_profile,
    )
    from ingestor.ingestion_profiles.startup_gate import enforce_production_manifest_gate
    from ingestor.ingestion_profiles.validation import validate_scope_against_profile
except (ImportError, ValueError):
    # Image Docker aplatie (LOT44f, ADR-0029/ADR-0031) : même discipline que
    # cli.py et runner.py — "ingestor" n'existe pas comme paquet ici.
    from ingestion_control.db import get_ingestion_control_dsn
    from ingestion_control.jobs import create_job
    from ingestion_control.provisioning import create_ingestion_run
    from ingestion_profiles.registry import load_profile_registry, select_profile
    from ingestion_profiles.startup_gate import enforce_production_manifest_gate
    from ingestion_profiles.validation import validate_scope_against_profile


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Crée un run + un job d'ingestion gouvernée (job_type="
            "'resource_pipeline'). Outil opérateur uniquement : jamais un "
            "endpoint réseau."
        )
    )
    parser.add_argument("--profiles-dir", required=True, type=Path)
    parser.add_argument("--manifest-path", required=True, type=Path)

    scope = parser.add_argument_group("scope (dix dimensions, aucun défaut)")
    scope.add_argument("--tenant", required=True)
    scope.add_argument("--collection", required=True)
    scope.add_argument("--niveau", required=True)
    scope.add_argument("--voie", required=True)
    scope.add_argument("--matiere", required=True)
    scope.add_argument("--candidat", required=True)
    scope.add_argument(
        "--audience", required=True, help="Liste séparée par des virgules, ex. eleve,parent"
    )
    scope.add_argument("--visibility", required=True)
    scope.add_argument("--school-year", required=True)
    scope.add_argument("--programme-version", required=True)

    parser.add_argument("--profile-version", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--canonical-url", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--proposed-type-doc", required=True)
    parser.add_argument(
        "--dedup-key",
        default=None,
        help=(
            "Clé d'idempotence. Par défaut : sha256(source_url) — déterministe, "
            "jamais aléatoire, pour qu'une resoumission de la même URL soit "
            "reconnaissable comme telle par l'opérateur, pas pour bloquer "
            "une resoumission volontaire (aucune vérification de doublon "
            "n'est faite ici ; ``resources_collection_dedup_key_unique`` "
            "côté base est la seule barrière, avec un message d'erreur clair)."
        ),
    )
    parser.add_argument("--query", default="operator-submitted")
    parser.add_argument(
        "--trigger",
        default="manual",
        choices=["manual", "scheduled"],
        help="Doit correspondre à la contrainte SQL ingestion_runs_trigger_valid.",
    )
    return parser


def _default_dedup_key(source_url: str) -> str:
    return hashlib.sha256(source_url.encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    try:
        gate_result = enforce_production_manifest_gate(args.profiles_dir, args.manifest_path)
    except Exception as exc:  # noqa: BLE001 - frontière CLI volontaire, jamais silencieuse
        print(f"JOB_CREATION_GATE_FAILED: {exc}", file=sys.stderr)
        return 1

    # Traçabilité d'autorité (LOT44f, ADR-0031) : consigne sous quelle
    # autorité nommée ce job est créé, avant même de le créer — jamais une
    # création de job silencieuse quant à l'autorité effective. Absence de
    # correspondance ici n'est pas une erreur propre à cette étape : elle
    # sera de toute façon rejetée plus loin par select_profile.
    authority = gate_result.manifest.authorities.get((args.collection, args.profile_version))
    if authority is not None:
        print(
            f"JOB_CREATION_AUTHORITY collection={args.collection} "
            f"profile_version={args.profile_version} approved_by={authority.approved_by} "
            f"approved_at={authority.approved_at} "
            f"manifest_fingerprint={gate_result.manifest.manifest_fingerprint}"
        )

    scope_dict: dict[str, object] = {
        "tenant": args.tenant,
        "collection": args.collection,
        "niveau": args.niveau,
        "voie": args.voie,
        "matiere": args.matiere,
        "candidat": args.candidat,
        "audience": [a.strip() for a in args.audience.split(",") if a.strip()],
        "visibility": args.visibility,
        "school_year": args.school_year,
        "programme_version": args.programme_version,
    }

    dedup_key = args.dedup_key or _default_dedup_key(args.source_url)

    with psycopg.connect(get_ingestion_control_dsn()) as conn:
        registry = load_profile_registry(args.profiles_dir)
        try:
            select_profile(
                registry, collection=args.collection, profile_version=args.profile_version
            )
        except Exception as exc:  # noqa: BLE001 - frontière CLI volontaire
            print(f"PROFILE_SELECTION_FAILED: {exc}", file=sys.stderr)
            return 1

        validation_result = validate_scope_against_profile(
            raw_scope=scope_dict,
            registry=registry,
            collection=args.collection,
            profile_version=args.profile_version,
        )
        if validation_result.status != "passed":
            print(
                f"SCOPE_VALIDATION_FAILED status={validation_result.status} "
                f"issues={validation_result.issues}",
                file=sys.stderr,
            )
            return 1

        scope = ResourceScope.model_validate(scope_dict)
        run_id: UUID = create_ingestion_run(
            conn, scope=scope, profile_version=args.profile_version, trigger=args.trigger
        )
        job_id: UUID = create_job(
            conn,
            run_id=run_id,
            job_type="resource_pipeline",
            resource_id=None,
            payload={
                "scope": scope_dict,
                "dedup_key": dedup_key,
                "source_url": args.source_url,
                "canonical_url": args.canonical_url,
                "domain": args.domain,
                "proposed_type_doc": args.proposed_type_doc,
                "profile_version": args.profile_version,
                "query": args.query,
            },
        )
        conn.commit()

    print(f"JOB_CREATED run_id={run_id} job_id={job_id} dedup_key={dedup_key}")
    return 0


if __name__ == "__main__":  # pragma: no cover - couvert par appel direct de main() dans les tests
    sys.exit(main())


__all__ = ["main"]
