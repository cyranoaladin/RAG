"""Migration 017 — la projection append-only (lot CU).

`publication_attestations` exige des faits unitaires que l'ingestion de
release scellée n'écrit pas : aucun des 479 payloads acquis ne porte
``quality_passed``, ``rights_status`` ni ``gate_*``. La projection les
apporte **avec leur origine**, sans réécrire le passé.

Ces épreuves vérifient par INSERT réels : les quatre origines, l'invariant
« une dimension inconnue est listée », l'impossibilité de produire un objet
autorisant avec une condition inconnue, l'append-only et les rôles.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

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
from test_migration_016_release_identity import (  # noqa: E402
    AUTORISATION_DE_TEST,
    SHA,
)

pytestmark = [pytest.mark.integration, requires_docker]

VERSION = "SEALED-RELEASE-PROJECTION-V1"


@pytest.fixture(scope="module")
def pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("migration-017")


@pytest.fixture()
def ressource_reelle(pg: dict[str, str]):  # noqa: ANN201
    from test_migration_016_release_identity import ressource_reelle as fabrique

    yield from fabrique.__wrapped__(pg)  # type: ignore[attr-defined]


def _projection(
    *, resource_id: object, artifact_id: object, **surcharges: object
) -> dict[str, object]:
    ligne: dict[str, object] = {
        "projection_id": uuid.uuid4(),
        "projection_version": VERSION,
        "release_id": "production-profile-gate-2026-2027-v2",
        "release_manifest_sha256": "e" * 64,
        "artifacts_release_sha256": "4" * 64,
        "candidate_inventory_sha256": "d" * 64,
        "artifact_transfer_manifest_sha256": "1" * 64,
        "resource_id": resource_id,
        "artifact_id": artifact_id,
        "content_sha256": SHA,
        "collection": "rag_nexus_nsi_terminale_specialite",
        "scope_authorization_id": AUTORISATION_DE_TEST,
        "rights_status": "officiel_public",
        "rights_decision_id": "eduscol_generic_approval",
        "rights_registry_sha256": "c" * 64,
        "rights_origin": "DERIVATION",
        "quality_passed": True,
        "quality_report_digest": "9" * 64,
        "quality_predicate_version": "BATCH-TECHNICAL-QUALITY-V1",
        "quality_origin": "DERIVATION",
        "currentness": "current",
        "currentness_origin": "DERIVATION",
        "pii_status": "CLEARED",
        "pii_evidence_sha256": "f" * 64,
        "pii_origin": "DERIVATION",
        "gate_passed": True,
        "gate_name": "sealed_release_publication_gate",
        "gate_evaluator": "attest_publication_cli/propose-release-batch-review",
        "gate_evaluated_at": datetime.now(UTC),
        "unresolved_conditions": [],
        "projection_digest": "a" * 64,
    }
    ligne.update(surcharges)
    return ligne


def _inserer(conn: psycopg.Connection, ligne: dict[str, object]) -> None:
    noms = ", ".join(ligne)
    valeurs = ", ".join(f"%({nom})s" for nom in ligne)
    conn.execute(
        f"INSERT INTO ingestion_control.sealed_release_projections ({noms}) "
        f"VALUES ({valeurs})",
        ligne,
    )


def _contrainte(exc: psycopg.Error) -> str | None:
    """Diagnostic STRUCTURÉ, pas le texte du message."""
    return exc.diag.constraint_name


# --- 1 — cas nominal ------------------------------------------------------


def test_une_projection_complete_est_acceptee(
    pg: dict[str, str], ressource_reelle: tuple[object, object]
) -> None:
    resource_id, artifact_id = ressource_reelle
    with psycopg.connect(superuser_dsn(pg)) as conn:
        _inserer(conn, _projection(resource_id=resource_id, artifact_id=artifact_id))
        assert conn.execute(
            "SELECT count(*) FROM ingestion_control.sealed_release_projections "
            " WHERE resource_id = %s", (resource_id,)
        ).fetchone() == (1,)
        conn.rollback()


# --- 2 — une dimension inconnue doit être listée ET bloquer ---------------


@pytest.mark.parametrize(
    ("dimension", "condition"),
    [("rights", "rights"), ("quality", "quality"),
     ("currentness", "currentness"), ("pii", "pii")],
)
def test_une_dimension_non_etablie_doit_etre_listee(
    pg: dict[str, str], ressource_reelle: tuple[object, object],
    dimension: str, condition: str,
) -> None:
    """Sinon une projection se dirait sans blocage en portant un inconnu."""
    resource_id, artifact_id = ressource_reelle
    ligne = _projection(
        resource_id=resource_id, artifact_id=artifact_id,
        **{f"{dimension}_origin": "NON_ETABLI"},
        gate_passed=False, unresolved_conditions=[],
    )
    with psycopg.connect(superuser_dsn(pg)) as conn:
        with pytest.raises(psycopg.errors.CheckViolation) as erreur:
            _inserer(conn, ligne)
        assert _contrainte(erreur.value) == (
            "sealed_release_projections_unknowns_are_listed"
        )
        conn.rollback()


def test_une_dimension_non_etablie_et_listee_est_acceptee_mais_non_autorisante(
    pg: dict[str, str], ressource_reelle: tuple[object, object]
) -> None:
    """La projection reste CONSULTABLE : elle décrit un blocage, elle ne le
    masque pas."""
    resource_id, artifact_id = ressource_reelle
    with psycopg.connect(superuser_dsn(pg)) as conn:
        _inserer(conn, _projection(
            resource_id=resource_id, artifact_id=artifact_id,
            currentness_origin="NON_ETABLI",
            unresolved_conditions=["currentness"],
            gate_passed=False,
        ))
        ligne = conn.execute(
            "SELECT gate_passed, unresolved_conditions "
            "  FROM ingestion_control.sealed_release_projections "
            " WHERE resource_id = %s", (resource_id,)
        ).fetchone()
        assert ligne == (False, ["currentness"])
        conn.rollback()


def test_un_objet_autorisant_est_impossible_avec_une_condition_inconnue(
    pg: dict[str, str], ressource_reelle: tuple[object, object]
) -> None:
    """Le cœur de l'invariant : `gate_passed` ne peut pas être vrai tant
    qu'une condition reste inconnue."""
    resource_id, artifact_id = ressource_reelle
    with psycopg.connect(superuser_dsn(pg)) as conn:
        with pytest.raises(psycopg.errors.CheckViolation) as erreur:
            _inserer(conn, _projection(
                resource_id=resource_id, artifact_id=artifact_id,
                pii_origin="NON_ETABLI",
                unresolved_conditions=["pii"],
                gate_passed=True,
            ))
        assert _contrainte(erreur.value) == (
            "sealed_release_projections_gate_requires_no_unknown"
        )
        conn.rollback()


@pytest.mark.parametrize("dimension", ["rights", "quality", "currentness", "pii"])
def test_une_origine_inventee_est_refusee(
    pg: dict[str, str], ressource_reelle: tuple[object, object], dimension: str
) -> None:
    resource_id, artifact_id = ressource_reelle
    with psycopg.connect(superuser_dsn(pg)) as conn:
        with pytest.raises(psycopg.errors.CheckViolation) as erreur:
            _inserer(conn, _projection(
                resource_id=resource_id, artifact_id=artifact_id,
                **{f"{dimension}_origin": "EVIDENT"},
            ))
        assert _contrainte(erreur.value) == "sealed_release_projections_origins_named"
        conn.rollback()


# --- 3 — append-only et rejeu --------------------------------------------


def test_une_projection_ne_peut_pas_etre_modifiee(
    pg: dict[str, str], ressource_reelle: tuple[object, object]
) -> None:
    resource_id, artifact_id = ressource_reelle
    with psycopg.connect(superuser_dsn(pg)) as conn:
        _inserer(conn, _projection(resource_id=resource_id, artifact_id=artifact_id))
        conn.commit()
    try:
        with psycopg.connect(superuser_dsn(pg)) as conn:
            with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
                conn.execute(
                    "UPDATE ingestion_control.sealed_release_projections "
                    "   SET gate_passed = false WHERE resource_id = %s",
                    (resource_id,),
                )
            conn.rollback()
            with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
                conn.execute(
                    "DELETE FROM ingestion_control.sealed_release_projections "
                    " WHERE resource_id = %s", (resource_id,)
                )
            conn.rollback()
    finally:
        with psycopg.connect(superuser_dsn(pg)) as conn:
            conn.execute("ALTER TABLE ingestion_control.sealed_release_projections "
                         "DISABLE TRIGGER sealed_release_projections_no_update")
            conn.execute("DELETE FROM ingestion_control.sealed_release_projections "
                         " WHERE resource_id = %s", (resource_id,))
            conn.execute("ALTER TABLE ingestion_control.sealed_release_projections "
                         "ENABLE TRIGGER sealed_release_projections_no_update")
            conn.commit()


def test_une_identite_reutilisee_est_un_conflit_explicite(
    pg: dict[str, str], ressource_reelle: tuple[object, object]
) -> None:
    """Même (release, resource, artifact, version) avec d'autres données :
    conflit, jamais écrasement."""
    resource_id, artifact_id = ressource_reelle
    with psycopg.connect(superuser_dsn(pg)) as conn:
        _inserer(conn, _projection(resource_id=resource_id, artifact_id=artifact_id))
        with pytest.raises(psycopg.errors.UniqueViolation) as erreur:
            _inserer(conn, _projection(
                resource_id=resource_id, artifact_id=artifact_id,
                projection_digest="b" * 64,
            ))
        assert _contrainte(erreur.value) == (
            "sealed_release_projections_identity_uniq"
        )
        conn.rollback()


def test_une_nouvelle_version_de_projection_coexiste(
    pg: dict[str, str], ressource_reelle: tuple[object, object]
) -> None:
    """Une correction est une NOUVELLE version, pas une réécriture."""
    resource_id, artifact_id = ressource_reelle
    with psycopg.connect(superuser_dsn(pg)) as conn:
        _inserer(conn, _projection(resource_id=resource_id, artifact_id=artifact_id))
        _inserer(conn, _projection(
            resource_id=resource_id, artifact_id=artifact_id,
            projection_version="SEALED-RELEASE-PROJECTION-V2",
            projection_digest="b" * 64,
        ))
        assert conn.execute(
            "SELECT count(*) FROM ingestion_control.sealed_release_projections "
            " WHERE resource_id = %s", (resource_id,)
        ).fetchone() == (2,)
        conn.rollback()


# --- 4 — les rôles --------------------------------------------------------


def test_l_attestor_produit_la_projection(
    pg: dict[str, str], ressource_reelle: tuple[object, object]
) -> None:
    resource_id, artifact_id = ressource_reelle
    with psycopg.connect(attestor_dsn(pg)) as conn:
        _inserer(conn, _projection(resource_id=resource_id, artifact_id=artifact_id))
        conn.rollback()


def test_le_worker_lit_mais_n_ecrit_pas(
    pg: dict[str, str], ressource_reelle: tuple[object, object]
) -> None:
    """Projeter des faits est une opération d'attestation, pas de
    publication."""
    resource_id, artifact_id = ressource_reelle
    with psycopg.connect(app_dsn(pg)) as conn:
        conn.execute(
            "SELECT count(*) FROM ingestion_control.sealed_release_projections"
        ).fetchone()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            _inserer(conn, _projection(
                resource_id=resource_id, artifact_id=artifact_id
            ))
        conn.rollback()
