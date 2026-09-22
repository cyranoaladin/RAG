"""Migration 018 — l'adoption par un successeur (lot CV, ADR-0059 § 5).

Épreuves sur PostgreSQL réel : les contraintes, l'ajout seul, les rôles, et
le chemin complet planification → persistance → faits batch sur des lignes
réellement acquises. La ligne acquise n'est jamais modifiée.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pg_authority import (  # noqa: E402
    app_dsn,
    attestor_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)

from ingestor.ingestion_control.release_batch_attestation import (  # noqa: E402
    ReleaseBatchAttestationError,
    measure_release_batch_facts,
)
from ingestor.ingestion_control.sealed_release_adoption import (  # noqa: E402
    SealedReleaseAdoptionError,
    SuccessorIdentity,
    artifact_belongs_to_release,
    load_acquired_rows,
    persist_adoption,
    plan_adoption,
)

pytestmark = [pytest.mark.integration, requires_docker]

PREDECESSEUR = "production-profile-gate-2026-2027-v2"
MANIFESTE_PREDECESSEUR = "e" * 64
SUCCESSEUR = SuccessorIdentity(
    release_id="production-profile-gate-2026-2027-v3",
    release_manifest_sha256="2" * 64,
    artifacts_release_sha256="3" * 64,
    candidate_inventory_sha256="4" * 64,
    artifact_transfer_manifest_sha256="5" * 64,
    currentness_evidence_sha256="6" * 64,
    pii_evidence_sha256="7" * 64,
)
COLLECTION = "rag_nexus_nsi_terminale_specialite"
AUTORISATION = "migration-018-scope-de-test"


@pytest.fixture(scope="module")
def pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("migration-018")


def _payload(sha: str, *, release_id: str, manifeste: str, currentness: str) -> dict[str, Any]:
    return {
        "protocol_version": "SEALED-RELEASE-INGESTION-V1",
        "pipeline_kind": "sealed_release_pipeline",
        "release_id": release_id,
        "release_manifest_sha256": manifeste,
        "artifacts_release_sha256": "8" * 64,
        "candidate_inventory_sha256": "9" * 64,
        "artifact_transfer_manifest_sha256": "0" * 64,
        "collection": COLLECTION,
        "content_sha256": sha,
        "placement_id": f"placement-{sha[:8]}",
        "source_placement_id": f"source-{sha[:8]}",
        "external_document_type": "diaporama",
        "type_doc": "ressource_officielle",
        "provenance_discovery_url": "https://eduscol.education.gouv.fr/5793/ressources",
        "provenance_artifact_url": "https://eduscol.education.gouv.fr/5793/ressources",
        "chunk_count": 23,
        "review_status": "reviewed",
        "placement_status": "active",
        "currentness": currentness,
        "scope_authorization_id": AUTORISATION,
        "scope_authorization_digest": "f" * 64,
    }


@pytest.fixture()
def lignes_acquises(pg: dict[str, str]) -> Iterator[list[str]]:
    """Deux placements réellement acquis sous le prédécesseur, via le chemin
    de provisionnement canonique."""
    from nexus_contracts.ingestion import ResourceScope
    from test_migration_016_release_identity import _valeur_de_test

    from ingestor.ingestion_control.provisioning import (
        SEALED_RELEASE_PIPELINE,
        create_ingestion_run,
        create_resource,
        persist_sealed_release_artifact,
    )

    scope = ResourceScope(
        tenant="libre_terminale", collection=COLLECTION, niveau="terminale",
        voie="generale", matiere="nsi", candidat="libre", audience=["aefe", "libre"],
        visibility="public", school_year="2026-2027",
        programme_version="EDUSCOL_CORPUS_20260808",
    )
    contenus = [uuid.uuid4().hex * 2, uuid.uuid4().hex * 2]
    with psycopg.connect(superuser_dsn(pg)) as conn:
        obligatoires = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            " WHERE table_schema='ingestion_control' AND table_name='scope_authorizations' "
            "   AND is_nullable='NO' AND column_default IS NULL ORDER BY ordinal_position"
        ).fetchall()
        autorisation = {nom: _valeur_de_test(nom, t) for nom, t in obligatoires}
        autorisation.update(
            {
                "authorization_id": AUTORISATION, "collection": COLLECTION,
                "protocol_version": "LOT41A-V1", "decision": "AUTHORIZE_INGESTION_SCOPE",
                "allowed_content_sha256": None,
            }
        )
        for champ in ("tenant", "niveau", "voie", "matiere", "candidat", "visibility",
                      "school_year", "programme_version"):
            if champ in autorisation:
                autorisation[champ] = getattr(scope, champ)
        if "audience" in autorisation:
            autorisation["audience"] = list(scope.audience)
        if "allowed_domains" in autorisation:
            autorisation["allowed_domains"] = ["eduscol.education.gouv.fr"]
        if "rights_categories" in autorisation:
            autorisation["rights_categories"] = ["officiel_public"]
        if "pii_absence_attested" in autorisation:
            autorisation["pii_absence_attested"] = True
        if "artifact_path" in autorisation:
            autorisation["artifact_path"] = f"governance/authorizations/{AUTORISATION}.json"
        noms = ", ".join(autorisation)
        valeurs = ", ".join(f"%({nom})s" for nom in autorisation)
        conn.execute(
            f"INSERT INTO ingestion_control.scope_authorizations ({noms}) "
            f"VALUES ({valeurs}) ON CONFLICT DO NOTHING",
            autorisation,
        )
        run_id = create_ingestion_run(
            conn, scope=scope, profile_version="v2-livraison-319", trigger="manual"
        )
        for sha in contenus:
            resource_id = create_resource(
                conn, run_id=run_id, scope=scope, dedup_key=sha,
                pipeline_kind=SEALED_RELEASE_PIPELINE,
            )
            persist_sealed_release_artifact(
                conn, resource_id=resource_id, run_id=run_id, sha256=sha,
                size_bytes=1000, mime_declared="application/pdf",
                mime_detected="application/pdf",
                provenance_url="https://eduscol.education.gouv.fr/5793/ressources",
                payload=_payload(
                    sha, release_id=PREDECESSEUR, manifeste=MANIFESTE_PREDECESSEUR,
                    currentness="current",
                ),
            )
        conn.commit()
    yield contenus


def _prescrits(contenus: list[str]) -> list[dict[str, Any]]:
    prescrits = []
    for sha in contenus:
        payload = _payload(
            sha, release_id=SUCCESSEUR.release_id,
            manifeste=SUCCESSEUR.release_manifest_sha256, currentness="official_snapshot",
        )
        payload.pop("scope_authorization_id")
        payload.pop("scope_authorization_digest")
        prescrits.append(payload)
    return prescrits


def _plan(conn: psycopg.Connection, contenus: list[str]) -> list[Any]:
    acquis = [
        row for row in load_acquired_rows(conn, release_id=PREDECESSEUR)
        if row.content_sha256 in contenus
    ]
    return plan_adoption(
        acquired=acquis, successor_placements=_prescrits(contenus), successor=SUCCESSEUR,
        predecessor_release_id=PREDECESSEUR,
        predecessor_release_manifest_sha256=MANIFESTE_PREDECESSEUR,
    )


def test_l_attestor_adopte_et_la_ligne_acquise_reste_intacte(
    pg: dict[str, str], lignes_acquises: list[str]
) -> None:
    with psycopg.connect(superuser_dsn(pg)) as conn:
        avant = conn.execute(
            "SELECT artifact_id, payload FROM ingestion_control.artifacts"
            " WHERE sha256 = ANY(%s) ORDER BY artifact_id", (lignes_acquises,)
        ).fetchall()
    with psycopg.connect(attestor_dsn(pg)) as conn:
        lignes = _plan(conn, lignes_acquises)
        assert persist_adoption(conn, lignes=lignes, adopted_by="banc") == (2, 0)
        conn.commit()
        # Un rejeu identique est reconnu, pas réécrit.
        assert persist_adoption(conn, lignes=lignes, adopted_by="banc") == (0, 2)
        conn.commit()
    with psycopg.connect(superuser_dsn(pg)) as conn:
        apres = conn.execute(
            "SELECT artifact_id, payload FROM ingestion_control.artifacts"
            " WHERE sha256 = ANY(%s) ORDER BY artifact_id", (lignes_acquises,)
        ).fetchall()
    assert apres == avant
    assert {row[1]["release_id"] for row in apres} == {PREDECESSEUR}
    assert {row[1]["currentness"] for row in apres} == {"current"}


def test_les_faits_batch_d_un_successeur_se_lisent_dans_ses_adoptions(
    pg: dict[str, str], lignes_acquises: list[str]
) -> None:
    with psycopg.connect(attestor_dsn(pg)) as conn:
        persist_adoption(conn, lignes=_plan(conn, lignes_acquises), adopted_by="banc")
        conn.commit()
        faits = measure_release_batch_facts(conn, release_id=SUCCESSEUR.release_id)
    assert faits.adopted is True
    assert faits.currentness == "official_snapshot"
    assert faits.release_manifest_sha256 == SUCCESSEUR.release_manifest_sha256
    assert faits.candidate_inventory_sha256 == SUCCESSEUR.candidate_inventory_sha256
    assert set(lignes_acquises) <= {sha for _, sha, _, _ in faits.par_ressource.values()}


def test_le_predecesseur_reste_mesure_depuis_ses_propres_lignes(
    pg: dict[str, str], lignes_acquises: list[str]
) -> None:
    with psycopg.connect(attestor_dsn(pg)) as conn:
        faits = measure_release_batch_facts(conn, release_id=PREDECESSEUR)
    assert faits.adopted is False
    assert faits.currentness == "current"
    assert faits.release_manifest_sha256 == MANIFESTE_PREDECESSEUR


def test_l_appartenance_d_un_artefact_se_lit_par_acquisition_ou_adoption(
    pg: dict[str, str], lignes_acquises: list[str]
) -> None:
    with psycopg.connect(attestor_dsn(pg)) as conn:
        lignes = _plan(conn, lignes_acquises)
        persist_adoption(conn, lignes=lignes, adopted_by="banc")
        conn.commit()
    with psycopg.connect(app_dsn(pg)) as conn:
        artefact = lignes[0].artifact_id
        assert artifact_belongs_to_release(conn, artifact_id=artefact, release_id=PREDECESSEUR)
        assert artifact_belongs_to_release(
            conn, artifact_id=artefact, release_id=SUCCESSEUR.release_id
        )
        assert not artifact_belongs_to_release(
            conn, artifact_id=artefact, release_id="une-autre-release"
        )


def test_l_adoption_est_en_ajout_seul(
    pg: dict[str, str], lignes_acquises: list[str]
) -> None:
    with psycopg.connect(attestor_dsn(pg)) as conn:
        persist_adoption(conn, lignes=_plan(conn, lignes_acquises), adopted_by="banc")
        conn.commit()
    with psycopg.connect(superuser_dsn(pg)) as conn:
        for requete in (
            "UPDATE ingestion_control.sealed_release_adoptions SET currentness = 'current'",
            "DELETE FROM ingestion_control.sealed_release_adoptions",
        ):
            with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
                conn.execute(requete)
            conn.rollback()


def test_le_worker_lit_l_adoption_mais_ne_l_ecrit_jamais(
    pg: dict[str, str], lignes_acquises: list[str]
) -> None:
    with psycopg.connect(attestor_dsn(pg)) as conn:
        lignes = _plan(conn, lignes_acquises)
    with psycopg.connect(app_dsn(pg)) as conn:
        conn.execute("SELECT count(*) FROM ingestion_control.sealed_release_adoptions")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            persist_adoption(conn, lignes=lignes, adopted_by="worker")


@pytest.mark.parametrize(
    ("colonne", "valeur", "contrainte"),
    [
        ("currentness", "archive", "sealed_release_adoptions_currentness_publishable"),
        ("release_id", PREDECESSEUR, "sealed_release_adoptions_is_a_successor"),
        (
            "release_manifest_sha256", MANIFESTE_PREDECESSEUR,
            "sealed_release_adoptions_manifest_differs",
        ),
        ("pii_evidence_sha256", "NOT-A-SHA", "sealed_release_adoptions_digests_valid"),
    ],
)
def test_le_schema_refuse_une_adoption_mal_formee(
    pg: dict[str, str], lignes_acquises: list[str], colonne: str, valeur: str,
    contrainte: str,
) -> None:
    with psycopg.connect(attestor_dsn(pg)) as conn:
        ligne = _plan(conn, lignes_acquises)[0]
    valeurs: dict[str, object] = {
        "adoption_id": uuid.uuid4(), "adoption_version": "SEALED-RELEASE-ADOPTION-V1",
        "release_id": SUCCESSEUR.release_id,
        "release_manifest_sha256": SUCCESSEUR.release_manifest_sha256,
        "artifacts_release_sha256": SUCCESSEUR.artifacts_release_sha256,
        "candidate_inventory_sha256": SUCCESSEUR.candidate_inventory_sha256,
        "artifact_transfer_manifest_sha256": SUCCESSEUR.artifact_transfer_manifest_sha256,
        "currentness_evidence_sha256": SUCCESSEUR.currentness_evidence_sha256,
        "pii_evidence_sha256": SUCCESSEUR.pii_evidence_sha256,
        "predecessor_release_id": PREDECESSEUR,
        "predecessor_release_manifest_sha256": MANIFESTE_PREDECESSEUR,
        "resource_id": ligne.resource_id, "artifact_id": ligne.artifact_id,
        "content_sha256": ligne.content_sha256, "collection": ligne.collection,
        "placement_id": ligne.placement_id, "currentness": "official_snapshot",
        "adopted_by": "banc", "adoption_digest": "a" * 64,
    }
    valeurs[colonne] = valeur
    noms = ", ".join(valeurs)
    marques = ", ".join(f"%({nom})s" for nom in valeurs)
    with psycopg.connect(superuser_dsn(pg)) as conn:
        with pytest.raises(psycopg.errors.CheckViolation) as exc:
            conn.execute(
                f"INSERT INTO ingestion_control.sealed_release_adoptions ({noms}) "
                f"VALUES ({marques})",
                valeurs,
            )
        assert exc.value.diag.constraint_name == contrainte


def test_une_adoption_divergente_est_refusee_sans_ecrasement(
    pg: dict[str, str], lignes_acquises: list[str]
) -> None:
    with psycopg.connect(attestor_dsn(pg)) as conn:
        persist_adoption(conn, lignes=_plan(conn, lignes_acquises), adopted_by="banc")
        conn.commit()
        autre = SuccessorIdentity(
            **{**SUCCESSEUR.__dict__, "currentness_evidence_sha256": "c" * 64}
        )
        acquis = [
            row for row in load_acquired_rows(conn, release_id=PREDECESSEUR)
            if row.content_sha256 in lignes_acquises
        ]
        divergentes = plan_adoption(
            acquired=acquis, successor_placements=_prescrits(lignes_acquises),
            successor=autre, predecessor_release_id=PREDECESSEUR,
            predecessor_release_manifest_sha256=MANIFESTE_PREDECESSEUR,
        )
        with pytest.raises(SealedReleaseAdoptionError, match="overwriting"):
            persist_adoption(conn, lignes=divergentes, adopted_by="banc")


def test_une_release_a_la_fois_acquise_et_adoptante_est_refusee(
    pg: dict[str, str], lignes_acquises: list[str]
) -> None:
    """Deux sources de faits pour une même release décrivent deux releases."""
    with psycopg.connect(attestor_dsn(pg)) as conn:
        persist_adoption(conn, lignes=_plan(conn, lignes_acquises), adopted_by="banc")
        conn.commit()
    with psycopg.connect(superuser_dsn(pg)) as conn:
        conn.execute(
            "UPDATE ingestion_control.artifacts SET payload = jsonb_set(payload,"
            " '{release_id}', to_jsonb(%s::text)) WHERE sha256 = %s",
            (SUCCESSEUR.release_id, lignes_acquises[0]),
        )
        try:
            with pytest.raises(ReleaseBatchAttestationError, match="mixture"):
                measure_release_batch_facts(conn, release_id=SUCCESSEUR.release_id)
        finally:
            conn.rollback()
