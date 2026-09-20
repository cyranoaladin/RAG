"""Ingestion d'une release scellée sur un PostgreSQL réel, jusqu'à NEEDS_REVIEW.

Aucun mock de base : un conteneur ``pgvector:pg16`` jetable est migré par le
VRAI script de bootstrap (schema_head=14), puis le point d'entrée écrit ses
lignes. Ce qui est mesuré ici l'est par ``SELECT``, pas par le rapport que le
module rend de lui-même.

La seule chose simulée est la vérification d'autorisation LOT41A : elle exige
une revue GitHub vivante, donc du réseau. Elle est prouvée ailleurs
(``test_sealed_release_ingestion.py``) — ce fichier prouve les LIGNES.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[2]
INFRA_ROOT = ENGINE_ROOT / "infra"
BOOTSTRAP_SCRIPT = INFRA_ROOT / "scripts" / "bootstrap_ingestion_control_schema.sh"
REAL_PROFILES_DIR = ENGINE_ROOT / "configs/ingestion_profiles/v2_livraison_319"

sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pg_authority import (  # noqa: E402
    PG_SUPERUSER,
    PG_SUPERUSER_PASSWORD,
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)

from ingestor.ingestion_profiles.registry import load_profile_registry  # noqa: E402
from ingestor.ingestion_worker import sealed_release_ingestion as sri  # noqa: E402

pytestmark = [pytest.mark.integration, requires_docker]

COLLECTIONS = (
    "rag_nexus_hggsp_premiere_specialite",
    "rag_nexus_hlp_terminale_specialite",
)
#: Un artefact partagé par les deux collections, un artefact propre à la
#: seconde : 3 placements pour 2 artefacts. La même asymétrie que la vraie
#: release (479 placements, 315 artefacts), en petit.
PLACEMENTS = (
    (COLLECTIONS[0], "a", "spid-a-hggsp"),
    (COLLECTIONS[1], "a", "spid-a-hlp"),
    (COLLECTIONS[1], "b", "spid-b-hlp"),
)
CHUNKS = {"a": 2, "b": 3}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest_of(path: Path) -> str:
    return _sha256(path.read_bytes())


@pytest.fixture(scope="module")
def pg_container() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("sealed-release-ingestion")


@pytest.fixture(scope="module")
def migrated(pg_container: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PGHOST": pg_container["host"],
            "PGPORT": pg_container["port"],
            "PGUSER": PG_SUPERUSER,
            "PGPASSWORD": PG_SUPERUSER_PASSWORD,
            "PGDATABASE": pg_container["dbname"],
        }
    )
    resultat = subprocess.run(
        [str(BOOTSTRAP_SCRIPT)], cwd=ENGINE_ROOT, env=env,
        capture_output=True, text=True, check=False,
    )
    assert resultat.returncode == 0, resultat.stderr
    assert "SCHEMA_VERIFICATION=OK" in resultat.stdout
    return pg_container


def _profile_scope(collection: str) -> dict[str, Any]:
    document = yaml.safe_load((REAL_PROFILES_DIR / f"{collection}.yml").read_text("utf-8"))
    return dict(document["scope"])


def _build_release(root: Path) -> dict[str, Any]:
    release_dir = root / "release"
    (release_dir / "subjects").mkdir(parents=True)
    store = root / "store"
    store.mkdir()

    contenus = {"a": b"%PDF-1.4 partage\n", "b": b"%PDF-1.4 propre\n"}
    identifiants: dict[str, str] = {}
    artefacts: dict[str, dict[str, Any]] = {}
    for cle, octets in contenus.items():
        identifiant = _sha256(octets)
        identifiants[cle] = identifiant
        (store / f"{identifiant}.pdf").write_bytes(octets)
        artefacts[identifiant] = {
            "artifact_id": identifiant,
            "content_sha256": identifiant,
            "source_url": f"https://eduscol.education.gouv.fr/fichier-{cle}.pdf",
            "type_doc": "programme_officiel" if cle == "a" else "diaporama",
            "title": f"Artefact {cle}",
            "chunks": [
                {"chunk_id": f"{identifiant}-{i}", "chunk_index": i,
                 "chunk_sha256": _sha256(f"{identifiant}-{i}".encode()),
                 "page_start": 1, "page_end": 1}
                for i in range(CHUNKS[cle])
            ],
        }

    subjects: list[dict[str, Any]] = []
    inventaire: list[dict[str, Any]] = []
    for collection in COLLECTIONS:
        scope = _profile_scope(collection)
        siens = [entree for entree in PLACEMENTS if entree[0] == collection]
        subject = {
            "collection": collection,
            "release_id": f"scelle-{collection}",
            "release_kind": "MULTILEVEL_SUBJECT_RELEASE_V2",
            "school_year": scope["school_year"],
            "programme_version": scope["programme_version"],
            "profile": {"version": "profile-gate-v2", "fingerprint": "0" * 64,
                        "manifest_digest": "1" * 64},
            "expected_counts": {"placements": len(siens),
                                "unique_artifact_references": len(siens)},
            "placements": [
                {
                    "artifact_id": identifiants[cle],
                    "placement_id": f"pid-{cle}-{collection}",
                    "source_placement_id": spid,
                    "placement_status": "active",
                    "review_status": "reviewed",
                    "currentness": "current",
                    **{dimension: scope[dimension] for dimension in (
                        "tenant", "niveau", "voie", "matiere", "candidat",
                        "visibility", "school_year", "programme_version")},
                    "collection": collection,
                }
                for _, cle, spid in siens
            ],
        }
        chemin = f"subjects/{collection}.release.json"
        (release_dir / chemin).write_text(
            json.dumps(subject, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        subjects.append({"collection": collection, "path": chemin,
                         "sha256": _digest_of(release_dir / chemin)})
        inventaire.append({
            "collection": collection,
            "candidates": [
                {
                    "content_sha256": identifiants[cle],
                    "placements": [{
                        "source_placement_id": spid,
                        "external_document_type": "programme-officiel",
                        "source_url": (
                            f"https://eduscol.education.gouv.fr/page-{collection}"
                        ),
                        "title": f"Artefact {cle}",
                    }],
                }
                for _, cle, spid in siens
            ],
        })

    (release_dir / "artifacts.release.json").write_text(
        json.dumps({"release_id": "scelle", "artifacts": list(artefacts.values())},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (release_dir / "candidate_inventory.json").write_text(
        json.dumps({"inventory_kind": "MULTILEVEL_CANDIDATE_INVENTORY_V1",
                    "collections": inventaire}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    manifeste = {
        "release_id": "scelle",
        "release_kind": sri.SEALED_RELEASE_KIND,
        "promotion_status": "NOT_PROMOTABLE",
        "activation_status": "NO_PRODUCTION_ACTIVATION",
        "school_year": "2026-2027",
        "expected_counts": {
            "subjects": len(COLLECTIONS),
            "unique_artifacts": len(artefacts),
            "placements": len(PLACEMENTS),
            "unique_chunks": sum(CHUNKS.values()),
        },
        "artifact_registry": {
            "path": "artifacts.release.json",
            "sha256": _digest_of(release_dir / "artifacts.release.json"),
        },
        "authorities": {
            "candidate_inventory_sha256": _digest_of(
                release_dir / "candidate_inventory.json"
            ),
        },
        "subjects": subjects,
    }
    (release_dir / "production-profile-gate.release.json").write_text(
        json.dumps(manifeste, ensure_ascii=False, indent=2), encoding="utf-8")

    transfert = {
        "manifest_kind": "NEXUS-STAGING-ARTIFACT-TRANSFER-V1",
        "release_id": "scelle",
        "file_count": len(artefacts),
        "digest_missing": 0,
        "digest_mismatches": 0,
        "files": [{"file": f"{i}.pdf", "sha256_expected": i, "sha256_observed": i}
                  for i in sorted(artefacts)],
    }
    chemin_transfert = root / "transfer_manifest.json"
    chemin_transfert.write_text(
        json.dumps(transfert, ensure_ascii=False, indent=2), encoding="utf-8")

    profils = root / "profiles"
    profils.mkdir()
    for collection in COLLECTIONS:
        shutil.copy(REAL_PROFILES_DIR / f"{collection}.yml", profils / f"{collection}.yml")

    return {"release_dir": release_dir, "store": store, "profiles_dir": profils,
            "transfer_path": chemin_transfert, "identifiants": identifiants}


class _Autorisation:
    """Autorisation déjà revérifiée — seuls les champs lus ici sont portés."""

    def __init__(self, authorization_id: str) -> None:
        self.authorization_id = authorization_id
        self.authorization_digest = "d" * 64
        self.allowed_domains = ("eduscol.education.gouv.fr",)


@pytest.fixture(scope="module")
def ingeree(migrated: dict[str, str], tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    build = _build_release(tmp_path_factory.mktemp("release"))
    release_dir: Path = build["release_dir"]
    manifeste = json.loads(
        (release_dir / "production-profile-gate.release.json").read_text("utf-8")
    )
    facts = sri.load_sealed_release(
        release_dir,
        release_manifest_sha256=_digest_of(
            release_dir / "production-profile-gate.release.json"
        ),
        artifacts_release_sha256=manifeste["artifact_registry"]["sha256"],
        candidate_inventory_sha256=manifeste["authorities"]["candidate_inventory_sha256"],
        artifact_transfer_manifest_path=build["transfer_path"],
        artifact_transfer_manifest_sha256=_digest_of(build["transfer_path"]),
    )
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        rapport = sri.ingest_sealed_release(
            conn,
            facts=facts,
            artifact_store_dir=build["store"],
            profile_registry=load_profile_registry(build["profiles_dir"]),
            scope_authorization_ids={
                collection: f"lot41a-staging-v2-{collection}"
                for collection in COLLECTIONS
            },
            owner="operateur-staging",
            expected_collections=COLLECTIONS,
            verifier=lambda conn, *, authorization_id, scope: _Autorisation(
                authorization_id
            ),
        )
        conn.commit()
    return {"rapport": rapport, "facts": facts, **build}


def _scalaire(migrated: dict[str, str], sql: str) -> Any:
    with psycopg.connect(superuser_dsn(migrated)) as conn, conn.cursor() as cur:
        cur.execute(sql)
        ligne = cur.fetchone()
    assert ligne is not None
    return ligne[0]


def test_les_lignes_de_controle_sont_creees(
    migrated: dict[str, str], ingeree: dict[str, Any]
) -> None:
    assert _scalaire(migrated, "SELECT count(*) FROM ingestion_control.ingestion_runs") == 2
    assert _scalaire(migrated, "SELECT count(*) FROM ingestion_control.resources") == 3
    assert (
        _scalaire(migrated, "SELECT count(*) FROM ingestion_control.resource_candidates")
        == 3
    )
    assert _scalaire(migrated, "SELECT count(*) FROM ingestion_control.artifacts") == 3


def test_le_rapport_dit_la_verite_sur_les_lignes_ecrites(
    migrated: dict[str, str], ingeree: dict[str, Any]
) -> None:
    rapport = ingeree["rapport"]
    assert rapport.runs == 2
    assert rapport.resources == 3
    assert rapport.resource_candidates == 3
    assert rapport.artifacts == 3
    assert rapport.placements == 3
    assert rapport.unique_artifacts == 2
    assert rapport.chunks == 5


def test_15_canonical_url_reste_null_pour_sealed_release_pipeline(
    migrated: dict[str, str], ingeree: dict[str, Any]
) -> None:
    assert (
        _scalaire(
            migrated,
            "SELECT count(*) FROM ingestion_control.resource_candidates "
            "WHERE canonical_url IS NOT NULL",
        )
        == 0
    )
    assert (
        _scalaire(
            migrated,
            "SELECT count(DISTINCT pipeline_kind) FROM "
            "ingestion_control.resource_candidates",
        )
        == 1
    )
    assert (
        _scalaire(
            migrated,
            "SELECT pipeline_kind FROM ingestion_control.resource_candidates LIMIT 1",
        )
        == "sealed_release_pipeline"
    )


def test_15bis_la_base_refuse_une_canonical_url_fabriquee_apres_coup(
    migrated: dict[str, str], ingeree: dict[str, Any]
) -> None:
    """Le garde n'est pas seulement applicatif : PostgreSQL refuse aussi."""
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ingestion_control.resource_candidates "
                    "SET canonical_url = %s",
                    ("https://eduscol.education.gouv.fr/page-hggsp",),
                )
        conn.rollback()


def test_16_source_url_reste_une_provenance(
    migrated: dict[str, str], ingeree: dict[str, Any]
) -> None:
    urls = _scalaire(
        migrated,
        "SELECT array_agg(DISTINCT source_url) FROM "
        "ingestion_control.resource_candidates",
    )
    assert sorted(urls) == [
        f"https://eduscol.education.gouv.fr/page-{collection}"
        for collection in sorted(COLLECTIONS)
    ]
    origines = _scalaire(
        migrated,
        "SELECT count(*) FROM ingestion_control.artifacts "
        "WHERE original_url <> final_url",
    )
    assert origines == 0


def test_le_type_ecrit_est_le_type_nexus_de_la_release(
    migrated: dict[str, str], ingeree: dict[str, Any]
) -> None:
    """Trois placements, deux types distincts — jamais un type par job."""
    types = _scalaire(
        migrated,
        "SELECT array_agg(DISTINCT proposed_type_doc) FROM "
        "ingestion_control.resource_candidates",
    )
    assert sorted(types) == ["diaporama", "programme_officiel"]


def test_la_cle_de_deduplication_derive_du_contenu(
    migrated: dict[str, str], ingeree: dict[str, Any]
) -> None:
    cles = _scalaire(
        migrated, "SELECT array_agg(DISTINCT dedup_key) FROM ingestion_control.resources"
    )
    assert sorted(cles) == sorted(ingeree["identifiants"].values())


def test_19_letat_final_est_needs_review(
    migrated: dict[str, str], ingeree: dict[str, Any]
) -> None:
    etats = _scalaire(
        migrated,
        "SELECT array_agg(DISTINCT resource_state) FROM ingestion_control.resources",
    )
    assert etats == ["NEEDS_REVIEW"]


def test_19bis_chaque_etat_intermediaire_est_journalise(
    migrated: dict[str, str], ingeree: dict[str, Any]
) -> None:
    """Dix transitions par ressource, toutes tracées — aucun saut."""
    assert (
        _scalaire(migrated, "SELECT count(*) FROM ingestion_control.workflow_events")
        == 3 * len(sri.STATE_SEQUENCE)
    )
    etats = _scalaire(
        migrated,
        "SELECT array_agg(DISTINCT to_state ORDER BY to_state) FROM "
        "ingestion_control.workflow_events",
    )
    assert sorted(etats) == sorted(etat.value for etat in sri.STATE_SEQUENCE)


def test_17_aucune_ligne_publiee(migrated: dict[str, str], ingeree: dict[str, Any]) -> None:
    assert (
        _scalaire(
            migrated,
            "SELECT count(*) FROM ingestion_control.resources "
            "WHERE resource_state IN ('REVIEWED', 'RETRIEVAL_ELIGIBLE')",
        )
        == 0
    )
    assert ingeree["rapport"].published_rows == 0


def test_18_aucune_attestation_enregistree(
    migrated: dict[str, str], ingeree: dict[str, Any]
) -> None:
    assert (
        _scalaire(
            migrated, "SELECT count(*) FROM ingestion_control.publication_attestations"
        )
        == 0
    )
    assert ingeree["rapport"].attestations == 0


def test_les_lignes_portent_les_digests_de_la_release(
    migrated: dict[str, str], ingeree: dict[str, Any]
) -> None:
    payload = _scalaire(
        migrated, "SELECT payload FROM ingestion_control.resource_candidates LIMIT 1"
    )
    assert payload["protocol_version"] == sri.PROTOCOL_VERSION
    assert payload["release_manifest_sha256"] == ingeree["facts"].release_manifest_sha256
    assert "canonical_url" not in payload
    assert payload["provenance_discovery_url"].startswith("https://")


def test_21_le_resource_pipeline_reste_ecrivable_a_cote(
    migrated: dict[str, str], ingeree: dict[str, Any]
) -> None:
    """Les deux origines cohabitent : la migration 014 n'a rien retiré."""
    import uuid

    scope = _profile_scope(COLLECTIONS[0])
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        with conn.cursor() as cur:
            run_id = uuid.uuid4()
            cur.execute(
                """
                INSERT INTO ingestion_control.ingestion_runs (
                    run_id, tenant, collection, niveau, voie, matiere, candidat,
                    audience, visibility, school_year, programme_version,
                    profile_version, trigger)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        'profile-gate-v2', 'manual')
                """,
                (run_id, scope["tenant"], scope["collection"], scope["niveau"],
                 scope["voie"], scope["matiere"], scope["candidat"],
                 scope["audience"], scope["visibility"], scope["school_year"],
                 scope["programme_version"]),
            )
            resource_id = uuid.uuid4()
            cur.execute(
                """
                INSERT INTO ingestion_control.resources (
                    resource_id, run_id, dedup_key, tenant, collection, niveau,
                    voie, matiere, candidat, audience, visibility, school_year,
                    programme_version, resource_state, pipeline_kind)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        'DISCOVERED', 'resource_pipeline')
                """,
                (resource_id, run_id, uuid.uuid4().hex, scope["tenant"],
                 scope["collection"], scope["niveau"], scope["voie"],
                 scope["matiere"], scope["candidat"], scope["audience"],
                 scope["visibility"], scope["school_year"],
                 scope["programme_version"]),
            )
            cur.execute(
                """
                INSERT INTO ingestion_control.resource_candidates (
                    resource_id, run_id, dedup_key, source_url, canonical_url,
                    domain, proposed_type_doc, pipeline_kind)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'resource_pipeline')
                """,
                (resource_id, run_id, uuid.uuid4().hex,
                 "https://eduscol.education.gouv.fr/page",
                 "https://eduscol.education.gouv.fr/document.pdf",
                 "eduscol.education.gouv.fr", "ressource_officielle"),
            )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM ingestion_control.resource_candidates "
                "WHERE pipeline_kind = 'resource_pipeline'"
            )
            ligne = cur.fetchone()
        assert ligne is not None and ligne[0] == 1
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM ingestion_control.resource_candidates "
                "WHERE pipeline_kind = 'resource_pipeline'"
            )
            cur.execute(
                "DELETE FROM ingestion_control.resources "
                "WHERE pipeline_kind = 'resource_pipeline'"
            )
            cur.execute(
                "DELETE FROM ingestion_control.ingestion_runs WHERE run_id = %s",
                (run_id,),
            )
        conn.commit()
