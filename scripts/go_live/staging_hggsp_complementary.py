#!/usr/bin/env python3
"""Prévol en lecture seule du complément HGGSP, indépendant du Worker B.

La commande inspecte les deux releases dans la base dédiée et la revue V4
en direct. Elle ne contient aucune instruction SQL de mutation. L'orchestrateur
la rappelle avant chaque étape, y compris après une reprise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any


DATABASE = "ragdb_profile_gate_v4"
RELEASE = "production-profile-gate-2026-2027-v5-hggsp"
V4_RELEASE = "production-profile-gate-2026-2027-v4"
COLLECTIONS = (
    "rag_nexus_hggsp_premiere_specialite",
    "rag_nexus_hggsp_terminale_specialite",
)
REVIEW_HEAD = "079461659b60f8a8ce9458145a199599ad822bbc"
OLD_JOBS_SHA256 = "fef6d99df13b08c3ea02f79f29be94fa5f8d12a639ef7af85989bfcdaba6af31"
EXPECTED_V4 = {"collections": 9, "unique_artifacts": 263, "placements": 405, "unique_chunks": 5678}
EXPECTED_SUCCESSOR = {"collections": 2, "unique_artifacts": 52, "placements": 74, "unique_chunks": 2590}
EXPECTED_UNION = {"collections": 11, "unique_artifacts": 315, "placements": 479, "unique_chunks": 8268}
ZERO = {"collections": 0, "unique_artifacts": 0, "placements": 0, "unique_chunks": 0}
PHASES = frozenset({"prepare", "record_replay", "attested", "enqueue", "enqueue_replay", "publish", "verify"})
RELEASE_DIR = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_hggsp_v5/release-b34b11e678bf9559/profile_gate"
)
MANIFEST_SHA256 = "8286388002071e31a4d80d357feb19d802292c862055e6749d9371fc15441daf"
MIXED_REGISTRY = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "release-registry-v4-hggsp-complementary.json"
)
MIXED_REGISTRY_SHA256 = "59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6"


class HGGSPRefused(RuntimeError):
    """Un seul écart suffit à interdire l'étape."""


def _expect(actual: object, expected: object, label: str, errors: list[str]) -> None:
    if actual != expected:
        errors.append(f"{label}: {actual!r}, attendu {expected!r}")


def exiger_preflight(observed: Mapping[str, Any], *, phase: str) -> None:
    """Contrôle exhaustif des comptes, anciennes lignes et autorité live.

    ``publish`` admet un produit successeur partiel pour reprendre un arrêt 75 ;
    le périmètre est alors borné par les 74 jobs neufs et les deux collections.
    """
    if phase not in PHASES:
        raise HGGSPRefused(f"phase inconnue: {phase}")
    errors: list[str] = []
    _expect(observed.get("database"), DATABASE, "base", errors)
    _expect(observed.get("v4"), EXPECTED_V4, "produit V4", errors)
    _expect(observed.get("successor_collections"), list(COLLECTIONS), "collections successeur", errors)
    _expect(observed.get("old_v4_hggsp_jobs"), 74, "anciens jobs V4 HGGSP", errors)
    _expect(observed.get("old_v4_hggsp_jobs_sha256"), OLD_JOBS_SHA256, "empreinte anciens jobs", errors)
    _expect(observed.get("v4_active_attestations"), 479, "attestations V4 actives", errors)
    _expect(observed.get("v4_published_jobs"), 405, "jobs V4 publiés", errors)
    _expect(observed.get("legacy_unchanged"), True, "ragdb historique", errors)
    review = observed.get("review_262")
    if not isinstance(review, Mapping):
        errors.append("revue #262 absente")
    else:
        for key, expected in (
            ("state", "open"), ("draft", False), ("approved", True), ("head_sha", REVIEW_HEAD)
        ):
            _expect(review.get(key), expected, f"revue #262 {key}", errors)
    attestations = observed.get("successor_attestations")
    jobs = observed.get("successor_jobs")
    successor = observed.get("successor")
    if phase == "prepare":
        _expect(successor, ZERO, "produit successeur avant publication", errors)
        _expect(attestations, 0, "attestations successeur avant revue", errors)
        _expect(jobs, 0, "jobs successeur avant enqueue", errors)
    elif phase == "record_replay":
        _expect(successor, ZERO, "produit successeur avant revue enregistrée", errors)
        _expect(jobs, 0, "jobs successeur avant enqueue", errors)
        if attestations not in (0, 74):
            errors.append("attestations successeur : 0 ou 74 pour reprise d'enregistrement")
    elif phase == "attested":
        _expect(successor, ZERO, "produit successeur avant enqueue", errors)
        _expect(attestations, 74, "attestations successeur", errors)
        _expect(jobs, 0, "jobs successeur avant enqueue", errors)
    elif phase in ("enqueue", "enqueue_replay"):
        _expect(successor, ZERO, "produit successeur avant enqueue", errors)
        _expect(attestations, 74, "attestations successeur", errors)
        if phase == "enqueue":
            _expect(jobs, 0, "jobs successeur avant enqueue", errors)
        elif jobs not in (0, 74):
            errors.append("jobs successeur : 0 ou 74 pour reprise d'enqueue")
    elif phase == "publish":
        _expect(attestations, 74, "attestations successeur", errors)
        _expect(jobs, 74, "nouveaux jobs successeur", errors)
        if not isinstance(successor, Mapping) or any(
            type(successor.get(key)) is not int or not 0 <= successor[key] <= maximum
            for key, maximum in EXPECTED_SUCCESSOR.items()
        ):
            errors.append("produit successeur hors borne")
    else:
        _expect(attestations, 74, "attestations successeur", errors)
        _expect(jobs, 74, "nouveaux jobs successeur", errors)
        _expect(successor, EXPECTED_SUCCESSOR, "produit successeur", errors)
        _expect(observed.get("union"), EXPECTED_UNION, "union logique", errors)
        _expect(observed.get("successor_succeeded_jobs"), 74, "jobs successeur réussis", errors)
    if errors:
        raise HGGSPRefused("; ".join(errors))


def _rows(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor = conn.execute(sql, params)
    names = [column.name for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _instant(value: object) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def legacy_unchanged(baseline_sha256: str, current_sha256: str) -> bool:
    if any(re.fullmatch(r"[0-9a-f]{64}", value) is None
           for value in (baseline_sha256, current_sha256)):
        raise HGGSPRefused("empreinte de ragdb historique absente ou invalide")
    return baseline_sha256 == current_sha256


def old_job_fingerprint(jobs: Sequence[Mapping[str, Any]]) -> str:
    """Même projection canonique que le contrôle DI des 74 jobs exclus."""
    rows = sorted([
        str(job["job_id"]), str(job["attestation_id"]), str(job["status"]),
        int(job["attempt_count"]), int(job["max_attempts"]),
        _instant(job["next_attempt_at"]), str(job["last_error"] or ""), bool(job["leased"]),
    ] for job in jobs)
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def build_transfer_manifest(root: Path, store: Path) -> dict[str, Any]:
    """Rehache les 52 PDF de l'objet scellé, sans toucher au magasin."""
    manifest_path = root / RELEASE_DIR / "production-profile-gate.release.json"
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise HGGSPRefused("manifest SHA-256 inattendu")
    manifest = json.loads(raw)
    registry = manifest["artifact_registry"]
    registry_path = manifest_path.parent / registry["path"]
    registry_raw = registry_path.read_bytes()
    if hashlib.sha256(registry_raw).hexdigest() != registry["sha256"]:
        raise HGGSPRefused("registre d'artefacts altéré")
    artifacts = json.loads(registry_raw)["artifacts"]
    if len(artifacts) != 52 or len({a["artifact_id"] for a in artifacts}) != 52:
        raise HGGSPRefused("52 artefacts uniques attendus")
    files: list[dict[str, str]] = []
    for artifact in artifacts:
        digest = artifact["content_sha256"]
        if digest != artifact["artifact_id"]:
            raise HGGSPRefused("identité de contenu inattendue")
        path = store / f"{digest}.pdf"
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise HGGSPRefused(f"PDF absent ou divergent: {digest}")
        files.append({"file": path.name, "sha256_expected": digest, "sha256_observed": digest})
    return {
        "manifest_kind": "NEXUS-STAGING-ARTIFACT-TRANSFER-V1",
        "release_id": RELEASE,
        "transfer_method": "aucun transfert : 52 objets préexistants rehachés en lecture",
        "destination_path": "/srv/nexus-staging/artifact-store/",
        "file_count": 52,
        "files": sorted(files, key=lambda item: item["file"]),
        "digest_mismatches": 0,
        "digest_missing": 0,
        "production_db_reads": 0,
        "production_db_writes": 0,
        "production_paths_written": 0,
    }


def mixed_owners(root: Path) -> dict[str, str]:
    raw = (root / MIXED_REGISTRY).read_bytes()
    if hashlib.sha256(raw).hexdigest() != MIXED_REGISTRY_SHA256:
        raise HGGSPRefused("registre mixte v2 altéré")
    document = json.loads(raw)
    if document.get("registry_version") != "2" or len(document.get("releases", [])) != 2:
        raise HGGSPRefused("registre mixte v2 attendu")
    owners: dict[str, str] = {}
    for release in document["releases"]:
        release_id = release["release_id"]
        if release_id not in (V4_RELEASE, RELEASE):
            raise HGGSPRefused("troisième release dans le registre mixte")
        for collection in release["collections"]:
            if collection in owners:
                raise HGGSPRefused("deux propriétaires pour une collection")
            owners[collection] = release_id
    if len(owners) != 11 or {k for k, owner in owners.items() if owner == RELEASE} != set(COLLECTIONS):
        raise HGGSPRefused("autorité de collections mixte hors du périmètre 9+2")
    return owners


def _counts(product: Any, *, owners: Mapping[str, str]) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    artifacts_table = _rows(product, "SELECT artifact_id::text AS artifact_id FROM public.rag_artifacts ORDER BY artifact_id")
    placements = _rows(product, """
        SELECT collection, artifact_id::text AS artifact_id, placement_id::text AS placement_id
          FROM public.rag_artifact_placements ORDER BY collection, placement_id
    """)
    chunks = _rows(product, """
        SELECT artifact_id::text AS artifact_id, chunk_id::text AS chunk_id
          FROM public.rag_chunks ORDER BY artifact_id, chunk_id
    """)
    if len({p["placement_id"] for p in placements}) != len(placements):
        raise HGGSPRefused("placement produit dupliqué")
    artifact_ids = [item["artifact_id"] for item in artifacts_table]
    if len(set(artifact_ids)) != len(artifact_ids):
        raise HGGSPRefused("artefact produit dupliqué")
    if len({(c["artifact_id"], c["chunk_id"]) for c in chunks}) != len(chunks):
        raise HGGSPRefused("chunk produit dupliqué")
    def one(selected: list[dict[str, Any]]) -> dict[str, int]:
        artifacts = {p["artifact_id"] for p in selected}
        return {
            "collections": len({p["collection"] for p in selected}),
            "unique_artifacts": len(artifacts),
            "placements": len(selected),
            "unique_chunks": len({c["chunk_id"] for c in chunks if c["artifact_id"] in artifacts}),
        }
    if any(p["collection"] not in owners for p in placements):
        raise HGGSPRefused("placement dans une collection sans propriétaire mixte")
    successor = [p for p in placements if owners[p["collection"]] == RELEASE]
    v4 = [p for p in placements if owners[p["collection"]] == V4_RELEASE]
    if {p["artifact_id"] for p in successor} & {p["artifact_id"] for p in v4}:
        raise HGGSPRefused("artefact partagé entre V4 et successeur")
    placed_artifacts = {p["artifact_id"] for p in placements}
    if set(artifact_ids) != placed_artifacts or {c["artifact_id"] for c in chunks} != placed_artifacts:
        raise HGGSPRefused("artefact ou chunk hors placements, ou artefact sans chunks")
    return one(v4), one(successor), one(placements)


def inspect_database(
    control: Any, product: Any, *, review: Mapping[str, Any], owners: Mapping[str, str],
    historical_unchanged: bool,
) -> dict[str, Any]:
    """Deux transactions imposées en lecture seule, sans mutation ni cache."""
    control.execute("SET TRANSACTION READ ONLY")
    product.execute("SET TRANSACTION READ ONLY")
    try:
        database, role = control.execute("SELECT current_database(), current_user").fetchone()
        product_database, product_role = product.execute("SELECT current_database(), current_user").fetchone()
        if (database, role, product_database, product_role) != (
            DATABASE, "ingestion_control_app", DATABASE, "rag_reader"
        ):
            raise HGGSPRefused("base ou rôles de lecture inattendus")
        v4, successor, union = _counts(product, owners=owners)
        old_jobs = _rows(control, """
            SELECT j.job_id::text AS job_id, j.payload->>'publication_attestation_id' AS attestation_id,
                   j.status, j.attempt_count, j.max_attempts, j.next_attempt_at, j.last_error,
                   j.lease_token IS NOT NULL AS leased
              FROM ingestion_control.jobs j
              JOIN ingestion_control.publication_attestations pa
                ON pa.attestation_id::text = j.payload->>'publication_attestation_id'
             WHERE j.job_type = 'publication_resume' AND pa.release_id = %s
               AND pa.collection = ANY(%s) ORDER BY j.job_id
        """, (V4_RELEASE, list(COLLECTIONS)))
        successor_jobs = _rows(control, """
            SELECT j.job_id::text AS job_id, pa.collection,
                   j.payload->>'publication_attestation_id' AS attestation_id, j.status
              FROM ingestion_control.jobs j
              JOIN ingestion_control.publication_attestations pa
                ON pa.attestation_id::text = j.payload->>'publication_attestation_id'
             WHERE j.job_type = 'publication_resume' AND pa.release_id = %s ORDER BY j.job_id
        """, (RELEASE,))
        attestations = _rows(control, """
            SELECT attestation_id::text AS attestation_id, collection
              FROM ingestion_control.publication_attestations
             WHERE release_id = %s AND invalidated_at IS NULL ORDER BY attestation_id
        """, (RELEASE,))
        if any(j["collection"] not in COLLECTIONS for j in successor_jobs):
            raise HGGSPRefused("job successeur hors des deux collections")
        if any(a["collection"] not in COLLECTIONS for a in attestations):
            raise HGGSPRefused("attestation successeur hors des deux collections")
        if len({j["attestation_id"] for j in successor_jobs}) != len(successor_jobs):
            raise HGGSPRefused("plusieurs nouveaux jobs pour une attestation")
        if set(j["attestation_id"] for j in successor_jobs) - {a["attestation_id"] for a in attestations}:
            raise HGGSPRefused("job successeur réassigné ou sans attestation active")
        return {
            "database": database, "v4": v4, "successor": successor, "union": union,
            "old_v4_hggsp_jobs": len(old_jobs),
            "old_v4_hggsp_jobs_sha256": old_job_fingerprint(old_jobs),
            "successor_jobs": len(successor_jobs),
            "successor_succeeded_jobs": sum(j["status"] == "succeeded" for j in successor_jobs),
            "successor_attestations": len(attestations),
            "successor_collections": list(COLLECTIONS), "review_262": dict(review),
            "legacy_unchanged": historical_unchanged,
        }
    finally:
        control.rollback()
        product.rollback()


def enqueue_successor(conn: Any, *, create_job: Any = None) -> dict[str, int]:
    """74 jobs NEUFS depuis les adoptions successeur, en une transaction.

    Le V4 enqueue générique exige le release_id dans le payload ACQUIS ; les
    HGGSP hérités gardent V4 dans ce payload immuable. La table d'adoption
    fournit l'identité successeur sans réaffecter un job V4.
    """
    if create_job is None:
        from ingestor.ingestion_control.jobs import find_or_create_job  # noqa: PLC0415

        create_job = find_or_create_job
    database, role = conn.execute("SELECT current_database(), current_user").fetchone()
    if (database, role) != (DATABASE, "ingestion_control_app"):
        raise HGGSPRefused("enqueue : base ou rôle applicatif incorrect")
    old_jobs = _rows(conn, """
        SELECT j.job_id::text AS job_id, j.payload->>'publication_attestation_id' AS attestation_id,
               j.status, j.attempt_count, j.max_attempts, j.next_attempt_at, j.last_error,
               j.lease_token IS NOT NULL AS leased
          FROM ingestion_control.jobs j
          JOIN ingestion_control.publication_attestations pa
            ON pa.attestation_id::text = j.payload->>'publication_attestation_id'
         WHERE j.job_type = 'publication_resume' AND pa.release_id = %s
           AND pa.collection = ANY(%s) ORDER BY j.job_id
    """, (V4_RELEASE, list(COLLECTIONS)))
    if len(old_jobs) != 74 or old_job_fingerprint(old_jobs) != OLD_JOBS_SHA256:
        raise HGGSPRefused("enqueue : anciens jobs V4 HGGSP modifiés")
    rows = conn.execute("""
        SELECT pa.attestation_id, pa.resource_id, pa.artifact_id, pa.collection,
               r.run_id, r.state_version, r.resource_state
          FROM ingestion_control.publication_attestations pa
          JOIN ingestion_control.resources r ON r.resource_id = pa.resource_id
          JOIN ingestion_control.sealed_release_adoptions ad
            ON ad.release_id = pa.release_id AND ad.resource_id = pa.resource_id
           AND ad.artifact_id = pa.artifact_id
         WHERE pa.release_id = %s AND pa.invalidated_at IS NULL
         ORDER BY pa.collection, pa.resource_id FOR SHARE OF pa, r, ad
    """, (RELEASE,)).fetchall()
    if len(rows) != 74 or len({r[1] for r in rows}) != 74:
        raise HGGSPRefused(f"enqueue : {len(rows)} attestations adoptées, 74 attendues")
    if {r[3] for r in rows} != set(COLLECTIONS):
        raise HGGSPRefused("enqueue : les deux collections HGGSP sont obligatoires")
    successor_jobs_sql = """
        SELECT j.job_id::text AS job_id, pa.attestation_id::text AS attestation_id,
               j.status
          FROM ingestion_control.jobs j
          JOIN ingestion_control.publication_attestations pa
            ON pa.attestation_id::text = j.payload->>'publication_attestation_id'
         WHERE j.job_type = 'publication_resume' AND pa.release_id = %s
         ORDER BY j.job_id
    """
    existing = _rows(conn, successor_jobs_sql, (RELEASE,))
    if len(existing) not in (0, 74) or (
        existing and {j["attestation_id"] for j in existing} != {str(r[0]) for r in rows}
    ):
        raise HGGSPRefused("enqueue : anciens jobs successeur divergents")
    if existing:
        if len({j["attestation_id"] for j in existing}) != 74:
            raise HGGSPRefused("enqueue : attestations de jobs successeur dupliquées")
        if any(j["status"] not in {"queued", "running", "succeeded"} for j in existing):
            raise HGGSPRefused("enqueue : statut de job successeur non admissible au rejeu")
        return {"created": 0, "already_queued": 74}
    counts = {"created": 0, "already_queued": 0}
    for attestation, resource, artifact, collection, run, version, state in rows:
        if state != "NEEDS_REVIEW":
            raise HGGSPRefused(f"enqueue : ressource {resource} en {state}")
        _job, created = create_job(
            conn, run_id=run, collection=collection, job_type="publication_resume",
            dedup_key=f"publication:{attestation}", resource_id=resource,
            payload={
                "resource_id": str(resource), "run_id": str(run),
                "expected_state_version": int(version),
                "publication_attestation_id": str(attestation),
                "artifact_id": str(artifact),
            },
        )
        counts["created" if created else "already_queued"] += 1
    if sum(counts.values()) != 74:
        raise HGGSPRefused("enqueue : total de jobs successeur différent de 74")
    final_jobs = _rows(conn, successor_jobs_sql, (RELEASE,))
    if len(final_jobs) != 74 or {j["attestation_id"] for j in final_jobs} != {str(r[0]) for r in rows}:
        raise HGGSPRefused("enqueue : 74 nouveaux jobs relationnels non prouvés")
    return counts


def require_authority_for_write(root: Path, operation: str) -> None:
    """Aucun point d'entrée d'écriture ne contourne l'autorité fusionnée."""
    import check_staging_authorization as checker  # noqa: PLC0415

    target = checker.OPERATIONS_HGGSP[operation]["cible"]
    errors = checker.verifier_operation_hggsp_image(root, operation, target)
    if errors:
        raise HGGSPRefused("autorisation HGGSP non consommable : " + "; ".join(errors))


def worker_arguments(root: Path, *, transfer_sha256: str, embedding_root: str) -> list[str]:
    """Arguments Worker B dérivés des octets scellés de la release HGGSP."""
    from staging_v4_arguments import AUTORITES_WORKER_B, PROFILE_MANIFEST, PROFILS  # noqa: PLC0415

    manifest_path = root / RELEASE_DIR / "production-profile-gate.release.json"
    raw = manifest_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise HGGSPRefused("manifest HGGSP altéré")
    manifest = json.loads(raw)
    if manifest["release_id"] != RELEASE or {s["collection"] for s in manifest["subjects"]} != set(COLLECTIONS):
        raise HGGSPRefused("release hors des deux collections HGGSP")
    owners = mixed_owners(root)
    if {collection for collection, owner in owners.items() if owner == RELEASE} != set(COLLECTIONS):
        raise HGGSPRefused("propriété HGGSP du registre mixte divergente")
    auth = manifest["authorities"]
    bindings = json.loads((manifest_path.parent / "authority_bindings.json").read_bytes())
    if bindings["profile_manifest_fingerprint"] != auth["profile_manifest_sha256"]:
        raise HGGSPRefused("fingerprint de profils divergent")
    def checked(relative: str, digest: str) -> str:
        actual = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        if actual != digest:
            raise HGGSPRefused(f"octets divergents : {relative}")
        return "/repo/" + relative
    profile_path = checked(PROFILE_MANIFEST, bindings["profile_manifest_file_sha256"])
    args = [
        "--profiles-dir", "/repo/" + PROFILS,
        "--artifact-store-dir", "/store",
        "--owner", "staging-hggsp-successor-worker-b",
        "--expected-role", "ingestion_control_app",
        "--expected-product-role", "rag_publisher",
        "--release-manifest-path", "/repo/" + RELEASE_DIR + "/production-profile-gate.release.json",
        "--release-manifest-sha256", MANIFEST_SHA256,
        "--collection-config-path", checked("services/rag-engine/configs/rag_collections.yml",
                                             hashlib.sha256((root / "services/rag-engine/configs/rag_collections.yml").read_bytes()).hexdigest()),
        "--collection-config-sha256", hashlib.sha256((root / "services/rag-engine/configs/rag_collections.yml").read_bytes()).hexdigest(),
        "--corpus-manifest-sha256", auth["corpus_manifest_sha256"],
        "--repository-root", "/repo",
        "--pii-review-reviewers-sha256", hashlib.sha256((root / "scripts/github/trusted-reviewers.json").read_bytes()).hexdigest(),
        "--artifact-transfer-manifest-path", "/run-db/transfer_manifest_hggsp_successor.json",
        "--artifact-transfer-manifest-sha256", transfer_sha256,
        "--embedding-artifact-root", embedding_root,
        "--embedding-inventory-sha256", manifest["models"]["embedding"]["inventory_sha256"],
        "--profile-manifest-path", profile_path,
        "--profile-manifest-sha256", bindings["profile_manifest_file_sha256"],
        "--release-registry-path", checked(MIXED_REGISTRY, MIXED_REGISTRY_SHA256),
        "--release-registry-sha256", MIXED_REGISTRY_SHA256,
    ]
    for option, key, path, name in AUTORITES_WORKER_B:
        relative = path or f"{RELEASE_DIR}/{name}"
        if key == "subject_mapping_sha256":
            relative = "services/rag-engine/configs/mappings/eduscol_profile_gate_subjects_hggsp.yml"
        resolved = checked(relative, auth[key])
        args.extend((f"{option}-path", resolved, f"{option}-sha256", auth[key]))
    args += [
        "--collection", COLLECTIONS[0], "--collection", COLLECTIONS[1],
        "--min-job-interval-s", "60", "--rate-limit-max-wait-s", "900",
        "--max-consecutive-rate-limits", "3", "--max-idle-polls", "5",
        "--max-iterations", str(3 * 74 + 50),
    ]
    return args


def live_review() -> dict[str, Any]:
    from ingestor.ingestion_control.github_authority import verify_review  # noqa: PLC0415

    decision = verify_review(repository="cyranoaladin/RAG", pull_request=262, expected_head=REVIEW_HEAD)
    return {"state": "open" if decision.approved else str(decision.reason), "draft": False,
            "approved": bool(decision.approved), "head_sha": str(decision.head_sha)}


def complete_v4_observation(control: Any, root: Path, observation: dict[str, Any]) -> None:
    """Contrôle DI gouverné sur les lignes V4, commun au prévol et à l'enqueue."""
    from staging_v4_partial_recovery import charger_perimetre, controle_partiel  # noqa: PLC0415

    perimetre = charger_perimetre(root / "docs/reports/go_live/recovery/di_partial_v4_262.json")
    try:
        di = controle_partiel(control, perimetre, empreinte_exclus=OLD_JOBS_SHA256)
    except RuntimeError as exc:
        raise HGGSPRefused(f"V4 DI non intacte : {exc}") from exc
    observation["v4_active_attestations"] = perimetre.attendu["active_attestations"]
    observation["v4_published_jobs"] = di["published"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--phase", choices=sorted(PHASES))
    parser.add_argument("--build-transfer-manifest", action="store_true")
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--artifact-store", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker-args", action="store_true")
    parser.add_argument("--transfer-sha256")
    parser.add_argument("--embedding-root", default="/models/e5-large-prerentree-2026-2027-20260828-materialise")
    parser.add_argument("--legacy-baseline-sha256")
    parser.add_argument("--legacy-current-sha256")
    args = parser.parse_args(argv)
    if args.worker_args:
        if not args.transfer_sha256 or not args.transfer_sha256.isascii() or len(args.transfer_sha256) != 64:
            parser.error("--transfer-sha256 requis pour --worker-args")
        try:
            print("\n".join(worker_arguments(args.repository_root, transfer_sha256=args.transfer_sha256,
                                             embedding_root=args.embedding_root)))
        except (HGGSPRefused, OSError, KeyError, ValueError) as exc:
            print(f"HGGSP_REFUSED: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.build_transfer_manifest:
        if args.phase or not args.artifact_store or not args.output:
            parser.error("transfert : --artifact-store et --output requis, --phase interdite")
        try:
            require_authority_for_write(args.repository_root, "successor_sealed_ingestion_or_binding")
            document = build_transfer_manifest(args.repository_root, args.artifact_store)
            args.output.write_text(json.dumps(document, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
        except (HGGSPRefused, OSError, ValueError) as exc:
            print(f"HGGSP_REFUSED: {exc}", file=sys.stderr)
            return 1
        print(f"HGGSP_TRANSFER_OK sha256={hashlib.sha256(args.output.read_bytes()).hexdigest()}")
        return 0
    if not args.phase:
        parser.error("--phase requis")
    if not args.legacy_baseline_sha256 or not args.legacy_current_sha256:
        parser.error("les deux empreintes mesurées de ragdb historique sont requises")
    try:
        require_authority_for_write(args.repository_root, "successor_preflight")
    except (HGGSPRefused, OSError, ValueError, KeyError) as exc:
        print(f"HGGSP_REFUSED: {exc}", file=sys.stderr)
        return 1
    control_dsn = os.environ.get("PG_INGESTION_CONTROL_DSN")
    product_dsn = os.environ.get("PG_RAG_DSN")
    if not control_dsn or not product_dsn:
        print("HGGSP_REFUSED: DSN de lecture manquant", file=sys.stderr)
        return 2
    import psycopg  # noqa: PLC0415

    try:
        with psycopg.connect(control_dsn) as control, psycopg.connect(product_dsn) as product:
            observation = inspect_database(
                control, product, review=live_review(), owners=mixed_owners(args.repository_root),
                historical_unchanged=legacy_unchanged(
                    args.legacy_baseline_sha256, args.legacy_current_sha256
                ),
            )
            complete_v4_observation(control, args.repository_root, observation)
        exiger_preflight(observation, phase=args.phase)
    except (HGGSPRefused, psycopg.Error) as exc:
        print(f"HGGSP_REFUSED: {exc}", file=sys.stderr)
        return 1
    print("HGGSP_PREFLIGHT_OK " + json.dumps(observation, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
