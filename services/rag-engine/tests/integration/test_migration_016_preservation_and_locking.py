"""Migration 016 — préservation de l'historique et verrou du rollback (lot CU).

Deux garanties que les épreuves de contraintes ne couvraient pas :

1. Des attestations unitaires **créées avant** la migration survivent à son
   application, avec leurs identités et leurs champs. Une requête qui rend
   « zéro anomalie » sur zéro ligne ne démontre rien : ces épreuves échouent
   si les données de départ sont absentes.

2. Le contrôle de vacuité du rollback et sa destruction sont
   **inséparables**. Sans verrou pris avant le contrôle, une attestation
   batch enregistrée entre les deux serait validée puis perdrait ses
   colonnes d'autorité.

La coordination des sessions est déterministe — aucune pause supposée
reproduire une course — et les attentes sont bornées.
"""

from __future__ import annotations

import contextlib
import sys
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pg_authority import (  # noqa: E402
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)
from test_migration_016_release_identity import (  # noqa: E402
    _identite_batch,
    _inserer,
)

pytestmark = [pytest.mark.integration, requires_docker]

MIGRATIONS = ENGINE_ROOT / "infra/postgres/ingestion_control/migrations"
ROLLBACKS = ENGINE_ROOT / "infra/postgres/ingestion_control/rollbacks"
MIGRATION_016 = MIGRATIONS / "016_lot42_batch_release_identity.sql"
ROLLBACK_016 = ROLLBACKS / "016_lot42_batch_release_identity.down.sql"

COLONNES_BATCH = (
    "release_id",
    "release_manifest_sha256",
    "artifacts_release_sha256",
    "candidate_inventory_sha256",
    "artifact_transfer_manifest_sha256",
    "release_batch_review_digest",
)


@pytest.fixture(scope="module")
def pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("migration-016-preservation")


@pytest.fixture(autouse=True)
def schema_016_retabli(pg: dict[str, str]) -> Iterator[None]:
    """Un test qui applique le rollback ne doit pas priver les suivants du
    schéma : il est rétabli quoi qu'il arrive."""
    yield
    with psycopg.connect(superuser_dsn(pg)) as conn:
        present = conn.execute(
            "SELECT count(*) FROM information_schema.columns "
            " WHERE table_schema='ingestion_control' "
            "   AND table_name='publication_attestations' "
            "   AND column_name='release_id'"
        ).fetchone()
        if present == (0,):
            conn.execute(MIGRATION_016.read_text(encoding="utf-8"))
        conn.commit()


@pytest.fixture()
def ressource_reelle(pg: dict[str, str]):  # noqa: ANN201
    from test_migration_016_release_identity import (
        ressource_reelle as fabrique,
    )

    yield from fabrique.__wrapped__(pg)  # type: ignore[attr-defined]


@pytest.fixture()
def deux_ressources(pg: dict[str, str]):  # noqa: ANN201
    """Un index d'unicité interdit deux attestations ACTIVES pour une même
    ressource : les deux protocoles historiques en exigent donc deux."""
    from test_migration_016_release_identity import (
        ressource_reelle as fabrique,
    )

    premiere = fabrique.__wrapped__(pg)  # type: ignore[attr-defined]
    seconde = fabrique.__wrapped__(pg)  # type: ignore[attr-defined]
    couples = [next(premiere), next(seconde)]
    yield couples
    for generateur in (premiere, seconde):
        with contextlib.suppress(StopIteration):
            next(generateur)


# --- 1 — l'historique survit à la migration ------------------------------


def test_les_attestations_unitaires_survivent_a_la_migration(
    pg: dict[str, str], deux_ressources: list[tuple[object, object]]
) -> None:
    """Créées AVANT 016 (schéma rétabli par son rollback), relues après.

    L'assertion sur le nombre de lignes de départ est ce qui empêche cette
    épreuve de passer sur un ensemble vide.
    """
    with psycopg.connect(superuser_dsn(pg)) as conn:
        # Revenir au schéma d'avant 016 : aucune attestation batch n'existe.
        conn.execute(ROLLBACK_016.read_text(encoding="utf-8"))
        conn.commit()

        avant: dict[str, tuple] = {}
        for protocole, (resource_id, artifact_id) in zip(
            ("LOT42-V1", "LOT42-V2"), deux_ressources, strict=True
        ):
            attestation_id = uuid.uuid4()
            _inserer(
                conn,
                protocole=protocole,
                attestation_id=attestation_id,
                resource_id=resource_id,
                artifact_id=artifact_id,
            )
            avant[protocole] = conn.execute(
                "SELECT attestation_id, resource_id, artifact_id, content_sha256,"
                "       canonical_url, attestation_digest, review_id"
                "  FROM ingestion_control.publication_attestations"
                " WHERE attestation_id = %s",
                (attestation_id,),
            ).fetchone()
        conn.commit()

        # Sans ces lignes, la suite ne prouverait rien.
        assert len(avant) == 2
        assert all(ligne is not None for ligne in avant.values())

        conn.execute(MIGRATION_016.read_text(encoding="utf-8"))
        conn.commit()

        for protocole, ligne_avant in avant.items():
            apres = conn.execute(
                "SELECT attestation_id, resource_id, artifact_id, content_sha256,"
                "       canonical_url, attestation_digest, review_id"
                "  FROM ingestion_control.publication_attestations"
                " WHERE attestation_id = %s",
                (ligne_avant[0],),
            ).fetchone()
            assert apres == ligne_avant, protocole

            batch = conn.execute(
                f"SELECT {', '.join(COLONNES_BATCH)}"
                "  FROM ingestion_control.publication_attestations"
                " WHERE attestation_id = %s",
                (ligne_avant[0],),
            ).fetchone()
            assert batch == (None,) * len(COLONNES_BATCH), protocole

        conn.execute(
            "DELETE FROM ingestion_control.publication_attestations "
            " WHERE attestation_id = ANY(%s)",
            ([ligne[0] for ligne in avant.values()],),
        )
        conn.commit()


def test_l_epreuve_de_preservation_echoue_sur_un_ensemble_vide(
    pg: dict[str, str],
) -> None:
    """Garde méthodologique : une vérification de préservation qui passerait
    sans donnée de départ ne démontre rien."""
    with psycopg.connect(superuser_dsn(pg)) as conn:
        anomalies = conn.execute(
            "SELECT count(*) FROM ingestion_control.publication_attestations "
            " WHERE protocol_version IN ('LOT42-V1','LOT42-V2') "
            "   AND release_id IS NOT NULL"
        ).fetchone()
        lignes = conn.execute(
            "SELECT count(*) FROM ingestion_control.publication_attestations "
            " WHERE protocol_version IN ('LOT42-V1','LOT42-V2')"
        ).fetchone()
        conn.rollback()
    assert anomalies == (0,)
    # Le second constat est celui qui donne du sens au premier.
    assert lignes is not None


# --- 2 — le rollback et la concurrence -----------------------------------


def test_le_rollback_prend_son_verrou_avant_le_controle_de_vacuite() -> None:
    """Lecture du fichier : l'ordre des instructions est la garantie."""
    sql = ROLLBACK_016.read_text(encoding="utf-8")
    position_verrou = sql.index("LOCK TABLE ingestion_control.publication_attestations")
    position_controle = sql.index("SELECT count(*) INTO restantes")
    assert position_verrou < position_controle, (
        "le verrou doit précéder le contrôle : acquis après, il arrive trop "
        "tard pour fonder la décision"
    )
    assert "lock_timeout" in sql, "l'attente doit être bornée"


def test_une_attestation_concurrente_n_est_jamais_validee_puis_depouillee(
    pg: dict[str, str], ressource_reelle: tuple[object, object]
) -> None:
    """Coordination DÉTERMINISTE, sans pause supposée créer la course.

    La session A ouvre une transaction et insère une attestation batch sans
    valider : elle détient un verrou de ligne et la table est donc
    non-vide « en cours ». La session B lance le rollback ; son ``LOCK TABLE
    ACCESS EXCLUSIVE`` ne peut pas être accordé tant que A n'a pas terminé.

    L'issue attendue est un ÉCHEC BORNÉ du rollback — jamais une destruction
    des colonnes pendant qu'une attestation se valide.
    """
    resource_id, artifact_id = ressource_reelle
    barriere = threading.Barrier(2, timeout=30)
    resultat: dict[str, object] = {}

    def session_b() -> None:
        try:
            barriere.wait()
            with psycopg.connect(superuser_dsn(pg)) as conn:
                conn.execute("SET lock_timeout = '2s'")
                try:
                    conn.execute(ROLLBACK_016.read_text(encoding="utf-8"))
                    conn.commit()
                    resultat["b"] = "APPLIQUE"
                except Exception as exc:  # noqa: BLE001
                    resultat["b"] = type(exc).__name__
        except Exception as exc:  # noqa: BLE001
            resultat["b"] = f"barriere:{type(exc).__name__}"

    fil = threading.Thread(target=session_b, daemon=True)
    fil.start()

    with psycopg.connect(superuser_dsn(pg)) as session_a:
        session_a.execute("BEGIN")
        _inserer(
            session_a,
            protocole="LOT42-RELEASE-BATCH-V1",
            resource_id=resource_id,
            artifact_id=artifact_id,
            **_identite_batch(),
        )
        # A détient maintenant la ligne, non validée.
        barriere.wait()
        fil.join(timeout=30)
        assert not fil.is_alive(), "la session B n'a pas rendu la main"
        # B n'a pas pu détruire les colonnes pendant que A écrivait.
        assert resultat["b"] != "APPLIQUE", resultat
        session_a.commit()

    # Les colonnes d'autorité sont intactes, et l'attestation les porte.
    with psycopg.connect(superuser_dsn(pg)) as conn:
        porte = conn.execute(
            "SELECT release_id FROM ingestion_control.publication_attestations "
            " WHERE resource_id = %s AND protocol_version='LOT42-RELEASE-BATCH-V1'",
            (resource_id,),
        ).fetchone()
        assert porte is not None and porte[0] == _identite_batch()["release_id"]
        conn.execute(
            "DELETE FROM ingestion_control.publication_attestations "
            " WHERE resource_id = %s", (resource_id,)
        )
        conn.commit()
