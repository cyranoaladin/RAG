#!/usr/bin/env python3
"""Mettre en file la publication d'une release attestée (lot DG).

Worker B ne publie que ce que des jobs ``publication_resume`` lui désignent ;
aucun outil canonique ne les créait pour une release scellée (le banc le
faisait par un utilitaire de test, en superutilisateur). Ce script comble ce
chaînon, et seulement lui :

* rôle ``ingestion_control_app`` (``PG_INGESTION_CONTROL_DSN``), qui a déjà
  ``SELECT, INSERT, UPDATE`` sur ``jobs`` — aucun droit nouveau ;
* un job par attestation batch ACTIVE de la release nommée, sur une ressource
  en ``NEEDS_REVIEW`` : le job nomme la ressource, son run, sa version d'état,
  l'attestation et l'artefact couverts — exactement ce que Worker B exige ;
* idempotent : un job actif pour la même attestation n'est pas recréé
  (``find_or_create_job``), une ressource déjà publiée n'est pas remise en file ;
* compte exigé : créés + déjà en file + déjà publiés = attendu, sinon refus
  et rien n'est validé (une seule transaction).

Exécuté depuis ``/repo`` dans l'image worker épinglée ; rien d'autre n'est lu
ni écrit. Aucune valeur de connexion n'est affichée.

    python staging_v4_enqueue_publication.py --release-id production-profile-gate-2026-2027-v4 \\
        --expected-jobs 479 [--collection rag_nexus_x ...]
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Any

JOB_TYPE = "publication_resume"
ETAT_ATTENDU = "NEEDS_REVIEW"
ETAT_PUBLIE = "RETRIEVAL_ELIGIBLE"

REQUETE = """
SELECT pa.attestation_id, pa.resource_id, pa.artifact_id, pa.collection,
       r.run_id, r.state_version, r.resource_state
  FROM ingestion_control.publication_attestations pa
  JOIN ingestion_control.resources r ON r.resource_id = pa.resource_id
  JOIN ingestion_control.artifacts a ON a.artifact_id = pa.artifact_id
 WHERE pa.release_id = %(release)s
   AND pa.invalidated_at IS NULL
   AND a.payload->>'release_id' = %(release)s
   AND r.collection = pa.collection
   AND (%(toutes)s OR pa.collection = ANY(%(collections)s))
 ORDER BY pa.collection, pa.resource_id
"""


class MiseEnFileRefusee(RuntimeError):
    """Le périmètre attesté n'est pas celui attendu ; rien n'est validé."""


def mettre_en_file(
    conn: Any,
    *,
    release_id: str,
    attendu: int,
    collections: Sequence[str] = (),
    find_or_create_job: Any = None,
) -> dict[str, int]:
    """Crée les jobs dans la transaction de ``conn`` ; l'appelant valide."""
    if find_or_create_job is None:
        from ingestor.ingestion_control.jobs import find_or_create_job  # noqa: PLC0415
    lignes = conn.execute(
        REQUETE,
        {"release": release_id, "toutes": not collections, "collections": list(collections)},
    ).fetchall()
    ressources = {ligne[1] for ligne in lignes}
    if len(ressources) != len(lignes):
        raise MiseEnFileRefusee("une ressource porte plusieurs attestations actives de cette release")
    bilan = {"crees": 0, "deja_en_file": 0, "deja_publies": 0}
    for attestation, ressource, artefact, collection, run, version, etat in lignes:
        if etat == ETAT_PUBLIE:
            bilan["deja_publies"] += 1
            continue
        if etat != ETAT_ATTENDU:
            raise MiseEnFileRefusee(f"ressource {ressource} en {etat}, attendu {ETAT_ATTENDU}")
        _job, cree = find_or_create_job(
            conn, run_id=run, collection=collection, job_type=JOB_TYPE,
            dedup_key=f"publication:{attestation}", resource_id=ressource,
            payload={
                "resource_id": str(ressource),
                "run_id": str(run),
                "expected_state_version": int(version),
                "publication_attestation_id": str(attestation),
                "artifact_id": str(artefact),
            },
        )
        bilan["crees" if cree else "deja_en_file"] += 1
    total = sum(bilan.values())
    if total != attendu:
        raise MiseEnFileRefusee(f"{total} placement(s) attesté(s) pour {release_id}, {attendu} attendu(s)")
    return bilan


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - exécution dans l'image
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--expected-jobs", required=True, type=int)
    parser.add_argument("--collection", action="append", default=[])
    args = parser.parse_args(argv)
    import psycopg

    dsn = os.environ.get("PG_INGESTION_CONTROL_DSN", "").strip()
    if not dsn:
        print("MISE_EN_FILE_REFUSEE: PG_INGESTION_CONTROL_DSN absent", file=sys.stderr)
        return 1
    with psycopg.connect(dsn) as conn:
        role = conn.execute("select current_user").fetchone()[0]
        if role != "ingestion_control_app":
            print(f"MISE_EN_FILE_REFUSEE: rôle {role}, attendu ingestion_control_app", file=sys.stderr)
            return 1
        try:
            bilan = mettre_en_file(
                conn, release_id=args.release_id, attendu=args.expected_jobs, collections=args.collection
            )
        except MiseEnFileRefusee as exc:
            conn.rollback()
            print(f"MISE_EN_FILE_REFUSEE: {exc}", file=sys.stderr)
            return 1
        conn.commit()
    print(
        f"PUBLICATION_JOBS_ENQUEUED release_id={args.release_id} crees={bilan['crees']} "
        f"deja_en_file={bilan['deja_en_file']} deja_publies={bilan['deja_publies']} "
        f"total={sum(bilan.values())}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
