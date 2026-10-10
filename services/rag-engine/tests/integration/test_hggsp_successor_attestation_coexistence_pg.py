"""Coexistence V4/V5 HGGSP sur le vrai schéma de contrôle PostgreSQL.

Les octets de release sont ceux du dépôt. Seuls la forge, les transferts de
banc et les lignes V4 initiales sont simulés. La chaîne V5 emprunte les vrais
CLI et les vrais rôles sur une instance PostgreSQL supprimée après le test.
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parents[1]
ROOT = ENGINE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ENGINE / "src"))
sys.path.insert(0, str(ROOT / "packages/contracts/src"))

from _banc_releases_reelles import (  # noqa: E402
    V4_DIR,
    V4_ID,
    acces_github,
    arguments_d_enregistrement,
    arguments_de_proposition,
    artefact_propose,
    enregistrer,
    run,
    sha,
    transfert_nomme,
)
from _local_github import VALID_TOKEN, LocalGitHub, local_github_server  # noqa: E402
from _pg_authority import (  # noqa: E402
    adopter_dsn,
    app_dsn,
    attestor_dsn,
    authority_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)

pytestmark = [pytest.mark.integration, requires_docker]

V5_DIR = ROOT / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_hggsp_v5/release-b34b11e678bf9559/profile_gate"
)
V5_ID = "production-profile-gate-2026-2027-v5-hggsp"
COLLECTIONS = (
    "rag_nexus_hggsp_premiere_specialite",
    "rag_nexus_hggsp_terminale_specialite",
)
CLI = "ingestor.ingestion_worker.attest_publication_cli"


def _facts(release_dir: Path, transfer: Path) -> Any:
    from ingestor.ingestion_worker.sealed_release_ingestion import load_sealed_release

    return load_sealed_release(
        release_dir,
        release_manifest_sha256=sha(release_dir / "production-profile-gate.release.json"),
        artifacts_release_sha256=sha(release_dir / "artifacts.release.json"),
        candidate_inventory_sha256=sha(release_dir / "candidate_inventory.json"),
        artifact_transfer_manifest_path=transfer,
        artifact_transfer_manifest_sha256=sha(transfer),
    )


def _r4_documents() -> tuple[dict[str, str], dict[str, str], list[tuple[str, bytes]]]:
    from nexus_contracts.authority_artifacts import ScopeAuthorizationArtifactV2

    sys.path.insert(0, str(ROOT / "scripts/go_live"))
    import build_lot41a_r4_authorizations as v4  # noqa: PLC0415

    old = v4.construire(ROOT)
    old_ids = {doc["scope"]["collection"]: key for key, doc in old.items()
               if doc["scope"]["collection"] in COLLECTIONS}
    # Autorités de BANC exclusivement : aucun artefact d'activation #270 n'est
    # importé par ce lot runtime. Le contenu autorisé et le scope sont ceux
    # des vraies releases ; seul l'identifiant de revue est local au test.
    new: dict[str, dict[str, Any]] = {}
    v5_manifest = json.loads((V5_DIR / "production-profile-gate.release.json").read_bytes())
    for key, source in old.items():
        if source["scope"]["collection"] not in COLLECTIONS:
            continue
        doc = deepcopy(source)
        new_id = key.replace("lot41a-staging-v4-", "lot41a-bench-hggsp-v5-")
        doc["authorization_id"] = new_id
        doc["manifest_digest"] = v5_manifest["authorities"]["profile_manifest_sha256"]
        doc["pii_absence_evidence"] = (
            f"{V5_DIR.relative_to(ROOT)}/pii_evidence.json@sha256:"
            f"{v5_manifest['authorities']['pii_evidence_sha256']}"
        )
        new[new_id] = doc
    new_ids = {doc["scope"]["collection"]: key for key, doc in new.items()}
    docs = [
        (key, ScopeAuthorizationArtifactV2.model_validate(doc).canonical_bytes())
        for source in (old, new)
        for key, doc in source.items()
        if doc["scope"]["collection"] in COLLECTIONS
    ]
    assert len(old_ids) == len(new_ids) == 2 and len(docs) == 4
    return old_ids, new_ids, docs


def _insert_old_attestation(
    conn: psycopg.Connection[Any], *, resource: uuid.UUID, artifact: uuid.UUID,
    sha256: str, collection: str, authorization_id: str, event: uuid.UUID,
    transfer: Path,
) -> uuid.UUID:
    """Représente les 74 attestations V4 déjà actives, sans les invalider."""
    attestation_id = uuid.uuid4()
    digest = hashlib.sha256(b"hggsp-v4-predecessor-review").hexdigest()
    review_id = "hggsp-v4-existing-bench"
    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "attestation_id": attestation_id,
        "resource_id": resource,
        "artifact_id": artifact,
        "content_sha256": sha256,
        "canonical_url": None,
        "collection": collection,
        "scope_authorization_id": authorization_id,
        "profile_id": collection,
        "profile_version": "v2-livraison-319",
        "profile_fingerprint": sha(V4_DIR / "artifacts.release.json"),
        "manifest_digest": sha(V4_DIR / "production-profile-gate.release.json"),
        "rights_status": "officiel_public",
        "rights_assessed_at": now,
        "quality_passed": True,
        "quality_report_digest": "a" * 64,
        "quality_assessed_at": now,
        "gate_passed": True,
        "gate_name": "hggsp-v4-existing-bench",
        "gate_evaluated_at": now,
        "evidence_event_ids": [event],
        "review_id": review_id,
        "review_artifact_path": f"governance/publication-reviews/{review_id}-{digest}.json",
        "review_artifact_blob_sha": "a" * 40,
        "attestation_digest": digest,
        "human_review_repository": "cyranoaladin/RAG",
        "human_review_pull_request": 262,
        "human_review_base_sha": "a" * 40,
        "human_review_head_sha": "b" * 40,
        "human_review_review_id": 9999,
        "human_review_reviewer": "bench-reviewer",
        "human_review_submitted_at": now,
        "human_review_challenge": "NEXUS-TRUSTED-REVIEW-V1:" + "c" * 64,
        "protocol_version": "LOT42-RELEASE-BATCH-V1",
        "attributed_facts_digest": None,
        "release_id": V4_ID,
        "release_manifest_sha256": sha(V4_DIR / "production-profile-gate.release.json"),
        "artifacts_release_sha256": sha(V4_DIR / "artifacts.release.json"),
        "candidate_inventory_sha256": sha(V4_DIR / "candidate_inventory.json"),
        "artifact_transfer_manifest_sha256": sha(transfer),
        "release_batch_review_digest": digest,
    }
    columns = sql.SQL(", ").join(sql.Identifier(name) for name in values)
    placeholders = sql.SQL(", ").join(sql.Placeholder(name) for name in values)
    conn.execute(
        sql.SQL("INSERT INTO ingestion_control.publication_attestations ({}) VALUES ({})")
        .format(columns, placeholders),
        values,
    )
    return attestation_id


def _seed_v4(
    pg: dict[str, str], *, facts: Any, transfer: Path,
    authorization_ids: dict[str, str], served: bool = True,
) -> None:
    """Les 74 lignes V4 HGGSP du plan de contrôle.

    ``served=True`` : jobs V4 terminés, ressources éligibles (contre-épreuve
    historique). ``served=False`` : décision B — jobs V4 en file, jamais
    exécutés, ressources NEEDS_REVIEW ; aucun placement produit HGGSP.
    """
    from ingestor.ingestion_control.artifact_attribution import (
        derive_sealed_release_artifact_attribution,
        persist_artifact_attribution,
    )
    from ingestor.ingestion_control.jobs import create_job
    from ingestor.ingestion_control.provisioning import (
        SEALED_RELEASE_PIPELINE,
        create_ingestion_run,
        create_resource,
        persist_sealed_release_artifact,
        persist_sealed_release_candidate,
    )
    from ingestor.ingestion_profiles.registry import load_profile_registry
    from ingestor.ingestion_worker.sealed_release_ingestion import sealed_placement_evidence

    profiles = {profile.scope.collection: profile for profile in
                load_profile_registry(ENGINE / "configs/ingestion_profiles/v3_livraison_315").values()}
    catalog = {
        a["content_sha256"]: a
        for a in json.loads((V4_DIR / "artifacts.release.json").read_bytes())["artifacts"]
    }
    hggsp = [placement for placement in facts.placements if placement.collection in COLLECTIONS]
    assert len(hggsp) == 74
    transitions = (
        ("DISCOVERED", "CANDIDATE"), ("CANDIDATE", "FETCHED"),
        ("FETCHED", "STORED"), ("STORED", "EXTRACTED"),
        ("EXTRACTED", "CLASSIFIED"), ("CLASSIFIED", "RIGHTS_CHECKED"),
        ("RIGHTS_CHECKED", "QUALITY_CHECKED"), ("QUALITY_CHECKED", "ROUTED"),
        ("ROUTED", "STAGED"), ("STAGED", "NEEDS_REVIEW"),
    )
    with psycopg.connect(superuser_dsn(pg)) as conn:
        runs = {
            c: create_ingestion_run(conn, scope=profiles[c].scope,
                                    profile_version=profiles[c].profile_version,
                                    trigger="manual")
            for c in COLLECTIONS
        }
        for placement in hggsp:
            collection, sha256 = placement.collection, placement.artifact_id
            entry = catalog[sha256]
            profile = profiles[collection]
            run_id = runs[collection]
            payload = {**sealed_placement_evidence(placement, facts),
                       "scope_authorization_id": authorization_ids[collection]}
            resource = create_resource(
                conn, run_id=run_id, scope=profile.scope, dedup_key=sha256,
                pipeline_kind=SEALED_RELEASE_PIPELINE,
            )
            persist_sealed_release_candidate(
                conn, resource_id=resource, run_id=run_id, dedup_key=sha256,
                source_url=placement.discovery_url, domain="eduscol.education.gouv.fr",
                proposed_type_doc=entry["type_doc"], payload=payload,
            )
            artifact = persist_sealed_release_artifact(
                conn, resource_id=resource, run_id=run_id, sha256=sha256,
                size_bytes=1, mime_declared="application/pdf", mime_detected="application/pdf",
                provenance_url=placement.provenance_url, payload=payload,
            )
            persist_artifact_attribution(
                conn,
                attribution=derive_sealed_release_artifact_attribution(
                    ingestion_artifact_id=artifact,
                    catalog_entry={"type_doc": entry["type_doc"],
                                   "source_url": placement.provenance_url},
                    profile=profile,
                ),
                run_id=run_id, actor="hggsp-coexistence-bench",
            )
            first_event: uuid.UUID | None = None
            for before, after in transitions:
                event = uuid.uuid4()
                first_event = first_event or event
                conn.execute(
                    "INSERT INTO ingestion_control.workflow_events "
                    "(event_id, run_id, resource_id, event_type, from_state, to_state, actor) "
                    "VALUES (%s, %s, %s, 'transition', %s, %s, 'hggsp-coexistence-bench')",
                    (event, run_id, resource, before, after),
                )
            conn.execute(
                "UPDATE ingestion_control.resources "
                "SET resource_state='NEEDS_REVIEW', state_version=10 WHERE resource_id=%s",
                (resource,),
            )
            assert first_event is not None
            old_attestation = _insert_old_attestation(
                conn, resource=resource, artifact=artifact, sha256=sha256,
                collection=collection, authorization_id=authorization_ids[collection],
                event=first_event, transfer=transfer,
            )
            job_id = create_job(
                conn, run_id=run_id, resource_id=resource,
                job_type="publication_resume",
                payload={"resource_id": str(resource), "run_id": str(run_id),
                         "expected_state_version": 10,
                         "publication_attestation_id": str(old_attestation),
                         "artifact_id": str(artifact)},
            )
            if not served:
                continue
            # L'état à reproduire est V4 déjà servie : le job historique est
            # terminal, la ressource est éligible. V5 doit malgré tout créer
            # SA ressource NEEDS_REVIEW et 74 jobs neufs.
            conn.execute(
                "UPDATE ingestion_control.jobs SET status='succeeded', attempt_count=1 "
                "WHERE job_id=%s", (job_id,),
            )
            conn.execute(
                "UPDATE ingestion_control.resources SET resource_state='RETRIEVAL_ELIGIBLE', "
                "state_version=11 WHERE resource_id=%s", (resource,),
            )
        conn.commit()


def _snapshot_v4(pg: dict[str, str]) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    with psycopg.connect(superuser_dsn(pg)) as conn:
        att = conn.execute(
            "SELECT attestation_id, resource_id, artifact_id, attestation_digest, "
            "invalidated_at FROM ingestion_control.publication_attestations "
            "WHERE release_id=%s ORDER BY resource_id", (V4_ID,),
        ).fetchall()
        jobs = conn.execute(
            "SELECT j.job_id, j.status, j.attempt_count, j.next_attempt_at, "
            "j.claimed_by, j.lease_token, j.lease_expires_at, j.last_error, j.payload "
            "FROM ingestion_control.jobs j "
            "JOIN ingestion_control.publication_attestations pa "
            "ON pa.attestation_id::text=j.payload->>'publication_attestation_id' "
            "WHERE pa.release_id=%s ORDER BY j.job_id", (V4_ID,),
        ).fetchall()
        conn.rollback()
    return att, jobs


def _snapshot_v4_control(pg: dict[str, str]) -> tuple[list[Any], list[Any]]:
    """Comparer toutes les colonnes des lignes V4, sans liste permissive."""
    with psycopg.connect(superuser_dsn(pg)) as conn:
        resources = conn.execute(
            "SELECT row_to_json(r) FROM ingestion_control.resources r "
            "JOIN ingestion_control.publication_attestations pa USING (resource_id) "
            "WHERE pa.release_id=%s ORDER BY r.resource_id", (V4_ID,),
        ).fetchall()
        artifacts = conn.execute(
            "SELECT row_to_json(a) FROM ingestion_control.artifacts a "
            "JOIN ingestion_control.publication_attestations pa USING (artifact_id) "
            "WHERE pa.release_id=%s ORDER BY a.artifact_id", (V4_ID,),
        ).fetchall()
        conn.rollback()
    return resources, artifacts


def _snapshot_v4_attestations_and_jobs(pg: dict[str, str]) -> tuple[list[Any], list[Any]]:
    """Toutes les colonnes, y compris les baux et métadonnées non présumées."""
    with psycopg.connect(superuser_dsn(pg)) as conn:
        attestations = conn.execute(
            "SELECT row_to_json(pa) FROM ingestion_control.publication_attestations pa "
            "WHERE pa.release_id=%s ORDER BY pa.attestation_id", (V4_ID,),
        ).fetchall()
        jobs = conn.execute(
            "SELECT row_to_json(j) FROM ingestion_control.jobs j "
            "JOIN ingestion_control.publication_attestations pa "
            "ON pa.attestation_id::text=j.payload->>'publication_attestation_id' "
            "WHERE pa.release_id=%s ORDER BY j.job_id", (V4_ID,),
        ).fetchall()
        conn.rollback()
    return attestations, jobs


@pytest.fixture(scope="module")
def control_pg() -> Any:
    yield from start_ingestion_control_postgres("hggsp-attestation-coexistence")


@pytest.fixture
def control_pg_v2() -> Any:
    yield from start_ingestion_control_postgres("hggsp-attestation-coexistence-v2")


def test_successor_v2_creates_distinct_control_resources_without_touching_v4(
    control_pg_v2: dict[str, str], tmp_path: Path,
) -> None:
    """Une vraie acquisition V4 active précède l'adoption V2 dans PostgreSQL."""
    transfer_v4 = transfert_nomme(tmp_path, V4_ID)
    transfer_v5 = transfert_nomme(tmp_path, V5_ID, release_dir=V5_DIR)
    v4 = _facts(V4_DIR, transfer_v4)
    old_auth, new_auth, docs = _r4_documents()
    github = LocalGitHub()
    token = tmp_path / "github-token-v2"
    token.write_text(VALID_TOKEN, encoding="utf-8")
    with local_github_server(github) as github_url:
        env = {
            "PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg_v2),
            "PG_INGESTION_CONTROL_ADOPTER_DSN": adopter_dsn(control_pg_v2),
            "PG_INGESTION_CONTROL_AUTHORITY_DSN": authority_dsn(control_pg_v2),
            **acces_github(github_url, token),
        }
        enregistrer(github=github, env=env, documents=docs,
                   numero=7903, graine="hggsp-coexistence-v2")
        _seed_v4(control_pg_v2, facts=v4, transfer=transfer_v4,
                 authorization_ids=old_auth)
        old_attestations, old_jobs = _snapshot_v4(control_pg_v2)
        old_control = _snapshot_v4_control(control_pg_v2)
        old_full = _snapshot_v4_attestations_and_jobs(control_pg_v2)
        assert len(old_attestations) == len(old_jobs) == 74
        adoption_args = [
            "adopt-predecessor-release", "--adoption-version", "SEALED-RELEASE-ADOPTION-V2",
            "--release-id", V5_ID, "--release-dir", str(V5_DIR),
            "--release-manifest-sha256", sha(V5_DIR / "production-profile-gate.release.json"),
            "--artifacts-release-sha256", sha(V5_DIR / "artifacts.release.json"),
            "--candidate-inventory-sha256", sha(V5_DIR / "candidate_inventory.json"),
            "--transfer-manifest-path", str(transfer_v5),
            "--transfer-manifest-sha256", sha(transfer_v5),
            "--predecessor-release-id", V4_ID,
            "--predecessor-release-manifest-sha256", sha(V4_DIR / "production-profile-gate.release.json"),
            "--adopted-by", "hggsp-coexistence-v2-bench",
        ]
        adopted = run(CLI, adoption_args, env)
        assert adopted.returncode == 0, adopted.stderr
        assert "created_successor_resources=74" in adopted.stdout
        assert "created_successor_artifacts=74" in adopted.stdout
        assert "created_adoptions=74" in adopted.stdout
        replayed = run(CLI, adoption_args, env)
        assert replayed.returncode == 0, replayed.stderr
        assert "created_successor_resources=0" in replayed.stdout
        assert "created_successor_artifacts=0" in replayed.stdout
        assert "created_adoptions=0" in replayed.stdout
        assert "already_present=74" in replayed.stdout
        bound = run(CLI, [
            "bind-publication-authorities", "--release-id", V5_ID,
            "--bound-by", "hggsp-coexistence-v2-bench",
            *[arg for collection in COLLECTIONS
              for arg in ("--scope-authorization", f"{collection}={new_auth[collection]}")],
        ], env)
        assert bound.returncode == 0, bound.stderr
        review_id = "hggsp-v5-coexistence-v2-bench"
        proposed = run(CLI, arguments_de_proposition(
            release_dir=V5_DIR, release_id=V5_ID,
            transfert=transfer_v5, revue=review_id,
        ), env)
        assert proposed.returncode == 0, proposed.stderr
        path, content = artefact_propose(proposed.stdout)
        head = hashlib.sha1(b"hggsp-v5-coexistence-v2-reviewed-head").hexdigest()
        github.add_approved_pr(number=7905, head_sha=head, base_sha="9" * 40,
                               review_id=7915)
        github.put_blob(path=path, ref=head, content=content)
        recorded = run(CLI, arguments_d_enregistrement(
            release_id=V5_ID, revue=review_id, pull_request=7905,
            tete=head, chemin=path,
        ), env)
        assert recorded.returncode == 0, recorded.stderr
        recorded_replay = run(CLI, arguments_d_enregistrement(
            release_id=V5_ID, revue=review_id, pull_request=7905,
            tete=head, chemin=path,
        ), env)
        assert recorded_replay.returncode == 0, recorded_replay.stderr
        enqueue_args = [
            "--release-id", V5_ID, "--expected-jobs", "74",
            *[arg for collection in COLLECTIONS for arg in ("--collection", collection)],
        ]
        enqueue_env = {**env, "PG_INGESTION_CONTROL_DSN": app_dsn(control_pg_v2)}
        enqueued = run("scripts.go_live.staging_v4_enqueue_publication",
                       enqueue_args, enqueue_env)
        assert enqueued.returncode == 0, enqueued.stderr
        assert "crees=74" in enqueued.stdout
        enqueued_replay = run("scripts.go_live.staging_v4_enqueue_publication",
                              enqueue_args, enqueue_env)
        assert enqueued_replay.returncode == 0, enqueued_replay.stderr
        assert "crees=0" in enqueued_replay.stdout
        assert "deja_en_file=74" in enqueued_replay.stdout
    assert _snapshot_v4(control_pg_v2) == (old_attestations, old_jobs)
    assert _snapshot_v4_control(control_pg_v2) == old_control
    assert _snapshot_v4_attestations_and_jobs(control_pg_v2) == old_full
    with psycopg.connect(superuser_dsn(control_pg_v2)) as conn:
        v4_ids = {row[1] for row in old_attestations}
        lineage = conn.execute(
            "SELECT resource_id, artifact_id, successor_resource_id, successor_artifact_id "
            "FROM ingestion_control.sealed_release_adoptions WHERE release_id=%s",
            (V5_ID,),
        ).fetchall()
    assert len(lineage) == 74
    assert {row[0] for row in lineage} == v4_ids
    assert {row[2] for row in lineage}.isdisjoint(v4_ids)
    assert all(row[1] != row[3] for row in lineage)
    with psycopg.connect(superuser_dsn(control_pg_v2)) as conn:
        counts = conn.execute(
            "SELECT release_id, count(*) FROM ingestion_control.publication_attestations "
            "WHERE invalidated_at IS NULL AND release_id IN (%s, %s) GROUP BY release_id",
            (V4_ID, V5_ID),
        ).fetchall()
        jobs = conn.execute(
            "SELECT pa.release_id, count(*) FROM ingestion_control.jobs j "
            "JOIN ingestion_control.publication_attestations pa "
            "ON pa.attestation_id::text = j.payload->>'publication_attestation_id' "
            "WHERE pa.release_id IN (%s, %s) GROUP BY pa.release_id",
            (V4_ID, V5_ID),
        ).fetchall()
        successor_links = conn.execute(
            "SELECT count(*) FROM ingestion_control.jobs j "
            "JOIN ingestion_control.publication_attestations pa "
            "  ON pa.attestation_id::text = j.payload->>'publication_attestation_id' "
            "JOIN ingestion_control.sealed_release_adoptions ad "
            "  ON ad.release_id = pa.release_id "
            " AND ad.successor_resource_id = j.resource_id "
            " AND ad.successor_artifact_id::text = j.payload->>'artifact_id' "
            " AND pa.resource_id = ad.successor_resource_id "
            " AND pa.artifact_id = ad.successor_artifact_id "
            "WHERE pa.release_id = %s", (V5_ID,),
        ).fetchone()[0]
        matching_physical_facts = conn.execute(
            "SELECT count(*) FROM ingestion_control.sealed_release_adoptions ad "
            "JOIN ingestion_control.artifacts predecessor "
            "  ON predecessor.artifact_id = ad.artifact_id "
            "JOIN ingestion_control.artifacts successor "
            "  ON successor.artifact_id = ad.successor_artifact_id "
            "WHERE ad.release_id = %s "
            "AND (predecessor.sha256, predecessor.size_bytes, "
            "     predecessor.mime_declared, predecessor.mime_detected, "
            "     predecessor.original_url, predecessor.final_url) "
            " IS NOT DISTINCT FROM "
            "    (successor.sha256, successor.size_bytes, "
            "     successor.mime_declared, successor.mime_detected, "
            "     successor.original_url, successor.final_url)", (V5_ID,),
        ).fetchone()[0]
        conn.rollback()
    assert dict(counts) == {V4_ID: 74, V5_ID: 74}
    assert dict(jobs) == {V4_ID: 74, V5_ID: 74}
    assert successor_links == matching_physical_facts == 74
    from ingestor.ingestion_control.jobs import claim_job  # noqa: PLC0415

    with psycopg.connect(app_dsn(control_pg_v2)) as conn:
        claimed_v5 = claim_job(
            conn, owner="hggsp-v5-bench", job_types=("publication_resume",),
            collections=COLLECTIONS, release_id=V5_ID,
            release_manifest_sha256=sha(V5_DIR / "production-profile-gate.release.json"),
        )
        assert claimed_v5 is not None
        assert claimed_v5.resource_id in {row[2] for row in lineage}
        conn.commit()
    assert _snapshot_v4(control_pg_v2) == (old_attestations, old_jobs)
    assert _snapshot_v4_attestations_and_jobs(control_pg_v2) == old_full
    with psycopg.connect(app_dsn(control_pg_v2)) as conn:
        claimed_v4 = claim_job(
            conn, owner="hggsp-v4-bench", job_types=("publication_resume",),
            collections=COLLECTIONS, release_id=V4_ID,
            release_manifest_sha256=sha(V4_DIR / "production-profile-gate.release.json"),
        )
        if claimed_v4 is not None:
            assert claimed_v4.resource_id in v4_ids
        conn.rollback()
    assert _snapshot_v4(control_pg_v2) == (old_attestations, old_jobs)
    assert _snapshot_v4_attestations_and_jobs(control_pg_v2) == old_full


def test_hggsp_old_adoption_hits_active_v4_attestation_conflict(
    control_pg: dict[str, str], tmp_path: Path,
) -> None:
    """Contre-épreuve P1 : le chemin actuel ne peut créer les attestations V5.

    Ce test démontre la collision sur la première des 74 ressources V4, avec
    une vraie proposition/revue batch V5 et le vrai record CLI. Il doit rester
    vert tant que l'ancien chemin existe ; le futur test positif de coexistence
    devra utiliser des resource_id V5 distincts.
    """
    transfer_v4 = transfert_nomme(tmp_path, V4_ID)
    transfer_v5 = transfert_nomme(tmp_path, V5_ID, release_dir=V5_DIR)
    v4 = _facts(V4_DIR, transfer_v4)
    v5 = _facts(V5_DIR, transfer_v5)
    assert len([p for p in v4.placements if p.collection in COLLECTIONS]) == 74
    assert len(v5.placements) == 74
    old_auth, new_auth, docs = _r4_documents()
    github = LocalGitHub()
    token = tmp_path / "github-token"
    token.write_text(VALID_TOKEN, encoding="utf-8")
    head = hashlib.sha1(b"hggsp-v5-coexistence-reviewed-head").hexdigest()
    github.add_approved_pr(number=7901, head_sha=head, base_sha="9" * 40,
                           review_id=7911)

    with local_github_server(github) as github_url:
        env = {
            "PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg),
            "PG_INGESTION_CONTROL_AUTHORITY_DSN": authority_dsn(control_pg),
            **acces_github(github_url, token),
        }
        enregistrer(github=github, env=env, documents=docs,
                   numero=7902, graine="hggsp-coexistence")
        _seed_v4(control_pg, facts=v4, transfer=transfer_v4,
                 authorization_ids=old_auth)
        old_attestations, old_jobs = _snapshot_v4(control_pg)
        old_full = _snapshot_v4_attestations_and_jobs(control_pg)
        assert len(old_attestations) == len(old_jobs) == 74
        assert all(row[4] is None for row in old_attestations)

        adopted = run(CLI, [
            "adopt-predecessor-release", "--release-id", V5_ID,
            "--release-dir", str(V5_DIR),
            "--release-manifest-sha256", sha(V5_DIR / "production-profile-gate.release.json"),
            "--artifacts-release-sha256", sha(V5_DIR / "artifacts.release.json"),
            "--candidate-inventory-sha256", sha(V5_DIR / "candidate_inventory.json"),
            "--transfer-manifest-path", str(transfer_v5),
            "--transfer-manifest-sha256", sha(transfer_v5),
            "--predecessor-release-id", V4_ID,
            "--predecessor-release-manifest-sha256", sha(V4_DIR / "production-profile-gate.release.json"),
            "--adopted-by", "hggsp-coexistence-bench",
        ], env)
        assert adopted.returncode == 0, adopted.stderr
        assert "placements=74 written=74" in adopted.stdout
        bound = run(CLI, [
            "bind-publication-authorities", "--release-id", V5_ID,
            "--bound-by", "hggsp-coexistence-bench",
            *[arg for collection in COLLECTIONS
              for arg in ("--scope-authorization", f"{collection}={new_auth[collection]}")],
        ], env)
        assert bound.returncode == 0, bound.stderr
        assert "written=74" in bound.stdout
        review_id = "hggsp-v5-coexistence-bench"
        proposed = run(CLI, arguments_de_proposition(
            release_dir=V5_DIR, release_id=V5_ID,
            transfert=transfer_v5, revue=review_id,
        ), env)
        assert proposed.returncode == 0, proposed.stderr
        path, content = artefact_propose(proposed.stdout)
        github.put_blob(path=path, ref=head, content=content)
        recorded = run(CLI, arguments_d_enregistrement(
            release_id=V5_ID, revue=review_id, pull_request=7901,
            tete=head, chemin=path,
        ), env)
        assert recorded.returncode == 1, recorded.stderr
        assert "ATTESTATION_CONFLICT" in recorded.stderr
        assert "no silent overwrite" in recorded.stderr

    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        successor = conn.execute(
            "SELECT attestation_id, resource_id, artifact_id, release_id, "
            "invalidated_at FROM ingestion_control.publication_attestations "
            "WHERE release_id=%s ORDER BY resource_id", (V5_ID,),
        ).fetchall()
        lineage = conn.execute(
            "SELECT resource_id, artifact_id FROM ingestion_control.sealed_release_adoptions "
            "WHERE release_id=%s ORDER BY resource_id", (V5_ID,),
        ).fetchall()
        conn.rollback()
    assert successor == []
    assert len(lineage) == 74
    assert {r[0] for r in lineage} == {r[1] for r in old_attestations}
    assert _snapshot_v4(control_pg) == (old_attestations, old_jobs)
    assert _snapshot_v4_attestations_and_jobs(control_pg) == old_full


@pytest.fixture
def control_pg_adversarial() -> Any:
    yield from start_ingestion_control_postgres("hggsp-adoption-v2-atomicity")


def test_v2_row_74_failure_rolls_back_and_concurrent_replay_is_unique(
    control_pg_adversarial: dict[str, str], tmp_path: Path,
) -> None:
    """Une erreur à la 74e ligne ne laisse aucun contrôle V5 partiel."""
    transfer_v4 = transfert_nomme(tmp_path, V4_ID)
    transfer_v5 = transfert_nomme(tmp_path, V5_ID, release_dir=V5_DIR)
    v4 = _facts(V4_DIR, transfer_v4)
    old_auth, _, docs = _r4_documents()
    github = LocalGitHub()
    token = tmp_path / "github-token-atomicity"
    token.write_text(VALID_TOKEN, encoding="utf-8")
    with local_github_server(github) as github_url:
        env = {
            "PG_INGESTION_CONTROL_ADOPTER_DSN": adopter_dsn(control_pg_adversarial),
            "PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg_adversarial),
            "PG_INGESTION_CONTROL_AUTHORITY_DSN": authority_dsn(control_pg_adversarial),
            **acces_github(github_url, token),
        }
        enregistrer(github=github, env=env, documents=docs,
                   numero=7950, graine="hggsp-v2-atomicity")
        _seed_v4(control_pg_adversarial, facts=v4, transfer=transfer_v4,
                 authorization_ids=old_auth)
        before = _snapshot_v4_attestations_and_jobs(control_pg_adversarial)
        before_control = _snapshot_v4_control(control_pg_adversarial)
        args = [
            "adopt-predecessor-release", "--adoption-version", "SEALED-RELEASE-ADOPTION-V2",
            "--release-id", V5_ID, "--release-dir", str(V5_DIR),
            "--release-manifest-sha256", sha(V5_DIR / "production-profile-gate.release.json"),
            "--artifacts-release-sha256", sha(V5_DIR / "artifacts.release.json"),
            "--candidate-inventory-sha256", sha(V5_DIR / "candidate_inventory.json"),
            "--transfer-manifest-path", str(transfer_v5),
            "--transfer-manifest-sha256", sha(transfer_v5),
            "--predecessor-release-id", V4_ID,
            "--predecessor-release-manifest-sha256", sha(V4_DIR / "production-profile-gate.release.json"),
            "--adopted-by", "hggsp-v2-atomicity-bench",
        ]
        with psycopg.connect(superuser_dsn(control_pg_adversarial)) as conn:
            conn.execute("""
                CREATE FUNCTION ingestion_control._bench_fail_v2_row_74()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.adoption_version = 'SEALED-RELEASE-ADOPTION-V2'
                       AND (SELECT count(*) FROM ingestion_control.sealed_release_adoptions
                            WHERE adoption_version = 'SEALED-RELEASE-ADOPTION-V2') >= 73
                    THEN RAISE EXCEPTION 'bench forced failure on V2 row 74';
                    END IF;
                    RETURN NEW;
                END $$
            """)
            conn.execute("""
                CREATE TRIGGER bench_fail_v2_row_74
                BEFORE INSERT ON ingestion_control.sealed_release_adoptions
                FOR EACH ROW EXECUTE FUNCTION ingestion_control._bench_fail_v2_row_74()
            """)
        failed = run(CLI, args, env)
        assert failed.returncode == 1
        assert "bench forced failure on V2 row 74" in failed.stderr
        with psycopg.connect(superuser_dsn(control_pg_adversarial)) as conn:
            assert conn.execute(
                "SELECT count(*) FROM ingestion_control.sealed_release_adoptions "
                "WHERE adoption_version='SEALED-RELEASE-ADOPTION-V2'"
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT count(*) FROM ingestion_control.resources "
                "WHERE dedup_key LIKE 'successor-control-v2:%'"
            ).fetchone()[0] == 0
            assert conn.execute(
                "SELECT count(*) FROM ingestion_control.artifacts "
                "WHERE payload->>'release_id'=%s", (V5_ID,),
            ).fetchone()[0] == 0
            conn.execute("DROP TRIGGER bench_fail_v2_row_74 "
                         "ON ingestion_control.sealed_release_adoptions")
            conn.execute("DROP FUNCTION ingestion_control._bench_fail_v2_row_74()")
        assert _snapshot_v4_attestations_and_jobs(control_pg_adversarial) == before
        assert _snapshot_v4_control(control_pg_adversarial) == before_control
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _index: run(CLI, args, env), range(2)))
        assert any(result.returncode == 0 for result in results)
        assert all(
            result.returncode == 0 or "ADOPTION_REFUSED" in result.stderr
            for result in results
        )
        replay = run(CLI, args, env)
        assert replay.returncode == 0, replay.stderr
        assert "created_adoptions=0" in replay.stdout
        assert "already_present=74" in replay.stdout
        with psycopg.connect(superuser_dsn(control_pg_adversarial)) as conn:
            assert conn.execute(
                "SELECT count(*) FROM ingestion_control.sealed_release_adoptions "
                "WHERE adoption_version='SEALED-RELEASE-ADOPTION-V2'"
            ).fetchone()[0] == 74
            assert conn.execute(
                "SELECT count(*) FROM ingestion_control.resources "
                "WHERE dedup_key LIKE 'successor-control-v2:%'"
            ).fetchone()[0] == 74
        assert _snapshot_v4_attestations_and_jobs(control_pg_adversarial) == before
        assert _snapshot_v4_control(control_pg_adversarial) == before_control
