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
import re
import sys
from pathlib import Path
from uuid import UUID

import psycopg
from nexus_contracts.ingestion import ResourceScope

try:
    from ingestor.ingestion_control.db import get_ingestion_control_dsn
    from ingestor.ingestion_control.jobs import find_or_create_job
    from ingestor.ingestion_control.provisioning import create_ingestion_run
    from ingestor.ingestion_profiles.readiness_gate import (
        ReadinessGateError,
        enforce_readiness_gate,
    )
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
    from ingestion_control.jobs import find_or_create_job
    from ingestion_control.provisioning import create_ingestion_run
    from ingestion_profiles.readiness_gate import (
        ReadinessGateError,
        enforce_readiness_gate,
    )
    from ingestion_profiles.registry import load_profile_registry, select_profile
    from ingestion_profiles.startup_gate import enforce_production_manifest_gate
    from ingestion_profiles.validation import validate_scope_against_profile

#: Même contrainte que ``nexus_contracts.identity.Sha256Digest`` — répétée
#: ici pour valider un ``--dedup-key`` fourni par l'opérateur sans tirer une
#: dépendance pydantic supplémentaire dans un script CLI (remédiation revue
#: PR#90 : avant ce correctif, une valeur arbitraire non-SHA-256 était
#: acceptée telle quelle, contournant silencieusement le contrat d'identité
#: canonique que Scout/``resources`` attendent).
_SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")


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
    parser.add_argument(
        "--scope-authorization-id",
        required=True,
        help=(
            "Identifiant de l'autorisation LOT41A sous laquelle ce job "
            "s'exécute (remédiation GATE H1, item C). Obligatoire et "
            "explicite : le worker ne déduit jamais « l'autorisation la plus "
            "récente couvrant ce scope » — plusieurs autorisations "
            "historiques peuvent coexister, et un job est lié à une seule, "
            "nommée ici."
        ),
    )
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--canonical-url", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--proposed-type-doc", required=True)
    parser.add_argument(
        "--dedup-key",
        default=None,
        help=(
            "Clé d'idempotence, 64 caractères hexadécimaux (SHA-256) — même "
            "format que celui que Scout calcule lui-même à partir de "
            "canonical_url, jamais un format différent. Par défaut : "
            "sha256(canonical_url) — déterministe, jamais aléatoire, calculé "
            "à partir de la même URL que Scout pour que la déduplication au "
            "niveau resources et celle au niveau job restent cohérentes "
            "(remédiation revue PR#90 : un défaut basé sur source_url "
            "aurait pu diverger de canonical_url et casser la contrainte "
            "resources_collection_dedup_key_unique en cas de redirection)."
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


def _default_dedup_key(canonical_url: str) -> str:
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    # ADR-0036 : la création d'un job est LA mutation qui compte. Le
    # manifeste de readiness est donc revalidé ici, et pas seulement au
    # démarrage du worker : un manifeste retiré ou remplacé après le
    # démarrage ne serait jamais vu par un contrôle qui ne s'exécuterait
    # qu'une fois. Ce contrôle précède le gate de manifest de profils, de
    # sorte qu'aucun job ne soit créé sans preuve de promotion gouvernée.
    try:
        enforce_readiness_gate()
    except ReadinessGateError as exc:
        print(str(exc), file=sys.stderr)
        return 1

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

    dedup_key = args.dedup_key or _default_dedup_key(args.canonical_url)
    if not _SHA256_HEX_PATTERN.match(dedup_key):
        print(
            f"INVALID_DEDUP_KEY: {dedup_key!r} is not 64 lowercase hexadecimal "
            "characters (SHA-256) — refusing to bypass the canonical identity "
            "contract",
            file=sys.stderr,
        )
        return 1

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
        # Remédiation revue PR#90 : find_or_create_job est atomique sous
        # concurrence (verrou advisory transactionnel) — deux invocations
        # concurrentes de cet outil avec le même dedup_key ne créent jamais
        # deux jobs actifs, contrairement à un create_job() nu précédé d'une
        # recherche séparée non protégée.
        job_id: UUID
        created: bool
        job_id, created = find_or_create_job(
            conn,
            run_id=run_id,
            collection=args.collection,
            job_type="resource_pipeline",
            dedup_key=dedup_key,
            resource_id=None,
            payload={
                "scope": scope_dict,
                "source_url": args.source_url,
                "canonical_url": args.canonical_url,
                "domain": args.domain,
                "proposed_type_doc": args.proposed_type_doc,
                "profile_version": args.profile_version,
                "scope_authorization_id": args.scope_authorization_id,
                "query": args.query,
            },
        )
        if not created:
            # Remédiation revue PR#90 (Cubic P2, revue incrémentale) :
            # create_ingestion_run ci-dessus a déjà inséré une ligne
            # ingestion_runs (status='planned') avant même de savoir si un
            # job actif existait déjà pour ce dedup_key — sur une
            # soumission dupliquée, cette ligne ne serait jamais référencée
            # par aucun job (celui retourné appartient à l'ancien run_id),
            # restant orpheline en 'planned' pour toujours (jamais reprise
            # par aucun worker, jamais visible comme "en cours" ni comme
            # "terminée"). Marquée 'cancelled' ici plutôt que supprimée :
            # le rôle runtime ingestion_control_app ne détient jamais
            # DELETE sur ingestion_runs (privilège volontairement absent,
            # cf. provision_ingestion_control_roles.sh — seuls SELECT/
            # INSERT/UPDATE lui sont accordés), et lui accorder DELETE
            # juste pour ce cas élargirait sa surface d'écriture au-delà du
            # strict nécessaire. 'cancelled' est une valeur légale de
            # ingestion_runs_status_valid (migration 001) qui documente
            # explicitement pourquoi ce run n'a jamais progressé, plutôt
            # que de le laisser silencieusement bloqué en 'planned'. run_id
            # est ensuite corrigé pour refléter le run réel auquel le job
            # réutilisé appartient, jamais le run superseded ci-dessus.
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ingestion_control.ingestion_runs SET status = 'cancelled' "
                    "WHERE run_id = %s", (run_id,)
                )
                cur.execute(
                    "SELECT run_id FROM ingestion_control.jobs WHERE job_id = %s", (job_id,)
                )
                existing_job_row = cur.fetchone()
                if existing_job_row is None:  # pragma: no cover - job_id vient de find_or_create_job
                    raise RuntimeError(f"job {job_id} not found immediately after find_or_create_job")
                (run_id,) = existing_job_row
        conn.commit()

    status = "JOB_CREATED" if created else "JOB_ALREADY_ACTIVE"
    print(f"{status} run_id={run_id} job_id={job_id} dedup_key={dedup_key}")
    return 0


if __name__ == "__main__":  # pragma: no cover - couvert par appel direct de main() dans les tests
    sys.exit(main())


__all__ = ["main"]
