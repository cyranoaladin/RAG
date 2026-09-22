"""Migration 016 — l'identité de release d'une attestation batch (lot CU).

Testée par des INSERT réellement permis ou refusés sur PostgreSQL, avec les
rôles prévus — pas par ``information_schema``.

Le piège gardé ici est la logique ternaire : une contrainte ``CHECK`` dont
l'expression vaut ``NULL`` est **acceptée** par PostgreSQL, seul ``FALSE``
rejette. Une branche écrite sans ``IS NOT NULL`` explicite accepterait donc
silencieusement une ligne batch sans identité de release.
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
    attestor_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)

pytestmark = [pytest.mark.integration, requires_docker]

SHA = "a" * 64
#: Identifiant d'autorisation du BANC, jamais une autorité réelle.
AUTORISATION_DE_TEST = "migration-016-scope-de-test"
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
    yield from start_ingestion_control_postgres("migration-016")


def _identite_batch() -> dict[str, str]:
    return {
        "release_id": "production-profile-gate-2026-2027-v2",
        "release_manifest_sha256": "e" * 64,
        "artifacts_release_sha256": "4" * 64,
        "candidate_inventory_sha256": "d" * 64,
        "artifact_transfer_manifest_sha256": "1" * 64,
        "release_batch_review_digest": "b" * 64,
    }


#: Formats exiges par les contraintes de la table, releves dans
#: 008_publication_attestations.sql. Une valeur qui ne les respecte pas ferait
#: lever la MAUVAISE contrainte, et une epreuve de refus passerait alors pour
#: une raison etrangere a ce qu'elle pretend demontrer.
_FORMATS: dict[str, object] = {
    "content_sha256": SHA,
    "profile_fingerprint": SHA,
    "manifest_digest": SHA,
    "quality_report_digest": SHA,
    "attestation_digest": SHA,
    "attributed_facts_digest": SHA,
    "review_id": "revue-de-test-016",
    "scope_authorization_id": AUTORISATION_DE_TEST,
    "review_artifact_blob_sha": "b" * 40,
    "human_review_base_sha": "c" * 40,
    "human_review_head_sha": "d" * 40,
    "human_review_challenge": f"NEXUS-TRUSTED-REVIEW-V1:{SHA}",
    "rights_status": "officiel_public",
    "quality_passed": True,
    "gate_passed": True,
    "canonical_url": "https://exemple.invalide/doc.pdf",
    # Chemin CANONIQUE, derive de review_id et attestation_digest : la
    # table impose l'egalite exacte (008:126-128).
    "review_artifact_path": (
        f"governance/publication-reviews/revue-de-test-016-{SHA}.json"
    ),
}


@pytest.fixture()
def ressource_reelle(pg: dict[str, str]) -> Iterator[tuple[object, object]]:
    """Une ressource et son artefact, réellement présents.

    Les épreuves de refus n'en avaient pas besoin : la contrainte ``CHECK``
    lève avant la clé étrangère. Le cas NOMINAL, lui, l'exige — c'est ce qui
    le rend probant.
    """
    from nexus_contracts.ingestion import ResourceScope

    from ingestor.ingestion_control.provisioning import (
        SEALED_RELEASE_PIPELINE,
        create_ingestion_run,
        create_resource,
        persist_sealed_release_artifact,
    )

    scope = ResourceScope(
        tenant="libre_terminale",
        collection="rag_nexus_nsi_terminale_specialite",
        niveau="terminale",
        voie="generale",
        matiere="nsi",
        candidat="libre",
        audience=["aefe", "libre"],
        visibility="public",
        school_year="2026-2027",
        programme_version="EDUSCOL_CORPUS_20260808",
    )
    with psycopg.connect(superuser_dsn(pg)) as conn:
        run_id = create_ingestion_run(
            conn, scope=scope, profile_version="v2-livraison-319",
            trigger="manual",
        )
        resource_id = create_resource(
            conn,
            run_id=run_id,
            scope=scope,
            dedup_key=f"migration-016-{uuid.uuid4().hex}",
            pipeline_kind=SEALED_RELEASE_PIPELINE,
        )
        # État initial : la clé étrangère `scope_authorization_id` exige une
        # ligne. Elle est écrite ici comme DONNÉE DE TEST du banc jetable,
        # avec les seules colonnes que le schéma impose. Elle n'autorise rien
        # et ne quitte jamais cette base.
        obligatoires = [
            (nom, type_sql)
            for nom, type_sql in conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                " WHERE table_schema='ingestion_control' "
                "   AND table_name='scope_authorizations' "
                "   AND is_nullable='NO' AND column_default IS NULL "
                " ORDER BY ordinal_position"
            ).fetchall()
        ]
        autorisation = {
            nom: _valeur_de_test(nom, type_sql) for nom, type_sql in obligatoires
        }
        autorisation["authorization_id"] = AUTORISATION_DE_TEST
        for champ, valeur in (
            ("collection", scope.collection), ("tenant", scope.tenant),
            ("niveau", scope.niveau), ("voie", scope.voie),
            ("matiere", scope.matiere), ("candidat", scope.candidat),
            ("visibility", scope.visibility), ("school_year", scope.school_year),
            ("programme_version", scope.programme_version),
        ):
            if champ in autorisation:
                autorisation[champ] = valeur
        if "audience" in autorisation:
            autorisation["audience"] = list(scope.audience)
        # Domaines et catégories : valeurs canoniques exigées par la 007.
        if "allowed_domains" in autorisation:
            autorisation["allowed_domains"] = ["eduscol.education.gouv.fr"]
        if "rights_categories" in autorisation:
            autorisation["rights_categories"] = ["officiel_public"]
        if "pii_absence_attested" in autorisation:
            autorisation["pii_absence_attested"] = True
        # Chemin CANONIQUE derive de l'identifiant (007:161-162).
        # LOT41A-V1 : aucune allowlist de contenu (009:56-59).
        autorisation["protocol_version"] = "LOT41A-V1"
        autorisation["decision"] = "AUTHORIZE_INGESTION_SCOPE"
        autorisation["allowed_content_sha256"] = None
        if "artifact_path" in autorisation:
            autorisation["artifact_path"] = (
                f"governance/authorizations/{AUTORISATION_DE_TEST}.json"
            )
        noms = ", ".join(autorisation)
        valeurs = ", ".join(f"%({nom})s" for nom in autorisation)
        conn.execute(
            f"INSERT INTO ingestion_control.scope_authorizations ({noms}) "
            f"VALUES ({valeurs}) ON CONFLICT DO NOTHING",
            autorisation,
        )
        artifact_id = persist_sealed_release_artifact(
            conn,
            resource_id=resource_id,
            run_id=run_id,
            sha256=SHA,
            size_bytes=242490,
            mime_declared="application/pdf",
            mime_detected="application/pdf",
            provenance_url="https://eduscol.education.gouv.fr/5793/ressources",
            payload={
                "content_sha256": SHA,
                "collection": scope.collection,
                "chunk_count": 23,
                "release_id": "production-profile-gate-2026-2027-v2",
                "release_manifest_sha256": "e" * 64,
                "provenance_artifact_url": (
                    "https://eduscol.education.gouv.fr/5793/ressources"
                ),
                "pipeline_kind": SEALED_RELEASE_PIPELINE,
            },
        )
        conn.commit()
        yield resource_id, artifact_id
        conn.execute(
            "DELETE FROM ingestion_control.publication_attestations "
            " WHERE resource_id = %s", (resource_id,))
        conn.commit()


def _valeur_de_test(nom: str, type_sql: str) -> object:
    """Valeur VALIDE pour une colonne obligatoire anterieure a cette migration.

    Ce test porte sur la regle AJOUTEE par la 016 : les colonnes des
    migrations precedentes doivent etre remplies avec des valeurs que leurs
    propres contraintes acceptent, faute de quoi le refus observe viendrait
    d'ailleurs.
    """
    if nom in _FORMATS:
        return _FORMATS[nom]
    if type_sql == "uuid":
        return uuid.uuid4()
    if type_sql.startswith("timestamp"):
        return datetime.now(UTC)
    if type_sql == "boolean":
        return True
    if type_sql == "ARRAY":
        return [uuid.uuid4()]
    if type_sql in ("integer", "bigint", "smallint"):
        return 1
    if type_sql in ("numeric", "double precision", "real"):
        return 1.0
    if nom.endswith(("_blob_sha", "_base_sha", "_head_sha")):
        # Un SHA git : 40 hexadecimaux, pas 64.
        return "b" * 40
    if nom.endswith("_challenge"):
        return f"NEXUS-TRUSTED-REVIEW-V1:{SHA}"
    if nom.endswith(("_sha256", "_digest")):
        return SHA
    if nom == "profile_version":
        return "1.0"
    return f"test-{nom}"


def _colonnes_obligatoires(conn: psycopg.Connection) -> list[tuple[str, str]]:
    return [
        (nom, type_sql)
        for nom, type_sql in conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            " WHERE table_schema='ingestion_control' "
            "   AND table_name='publication_attestations' "
            "   AND is_nullable='NO' AND column_default IS NULL "
            " ORDER BY ordinal_position"
        ).fetchall()
    ]


def _inserer(conn: psycopg.Connection, *, protocole: str, **identite: object) -> None:
    colonnes: dict[str, object] = {
        nom: _valeur_de_test(nom, type_sql)
        for nom, type_sql in _colonnes_obligatoires(conn)
    }
    colonnes["protocol_version"] = protocole
    if protocole == "LOT42-RELEASE-BATCH-V1":
        # Le batch n'a pas d'URL canonique : la 014 l'INTERDIT.
        colonnes["canonical_url"] = None
        colonnes["attributed_facts_digest"] = None
    else:
        colonnes["canonical_url"] = "https://exemple.invalide/doc.pdf"
        colonnes["attributed_facts_digest"] = SHA if protocole == "LOT42-V2" else None
    colonnes.update(identite)
    noms = ", ".join(colonnes)
    valeurs = ", ".join(f"%({nom})s" for nom in colonnes)
    conn.execute(
        f"INSERT INTO ingestion_control.publication_attestations ({noms}) "
        f"VALUES ({valeurs})",
        colonnes,
    )


def test_les_colonnes_existent_apres_la_migration(pg: dict[str, str]) -> None:
    with psycopg.connect(superuser_dsn(pg)) as conn:
        presentes = {
            ligne[0]
            for ligne in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='ingestion_control' "
                "  AND table_name='publication_attestations'"
            ).fetchall()
        }
        conn.rollback()
    assert set(COLONNES_BATCH) <= presentes


@pytest.mark.parametrize("manquante", COLONNES_BATCH)
def test_une_ligne_batch_sans_une_identite_est_refusee(
    pg: dict[str, str], manquante: str
) -> None:
    """Le piège de la logique ternaire : sans ``IS NOT NULL`` explicite,
    chacune de ces lignes passerait."""
    identite = _identite_batch()
    identite[manquante] = None  # type: ignore[assignment]
    with psycopg.connect(superuser_dsn(pg)) as conn:
        with pytest.raises(
            psycopg.errors.CheckViolation,
            match="publication_attestations_release_identity_by_protocol",
        ):
            _inserer(conn, protocole="LOT42-RELEASE-BATCH-V1", **identite)
        conn.rollback()


@pytest.mark.parametrize(
    "champ",
    ["release_manifest_sha256", "artifacts_release_sha256",
     "candidate_inventory_sha256", "artifact_transfer_manifest_sha256",
     "release_batch_review_digest"],
)
def test_un_digest_mal_forme_est_refuse(pg: dict[str, str], champ: str) -> None:
    identite = _identite_batch()
    identite[champ] = "PAS-UN-DIGEST"
    with psycopg.connect(superuser_dsn(pg)) as conn:
        with pytest.raises(
            psycopg.errors.CheckViolation,
            match="publication_attestations_release_identity_by_protocol",
        ):
            _inserer(conn, protocole="LOT42-RELEASE-BATCH-V1", **identite)
        conn.rollback()


def test_un_release_id_vide_est_refuse(pg: dict[str, str]) -> None:
    identite = _identite_batch()
    identite["release_id"] = "   "
    with psycopg.connect(superuser_dsn(pg)) as conn:
        with pytest.raises(
            psycopg.errors.CheckViolation,
            match="publication_attestations_release_identity_by_protocol",
        ):
            _inserer(conn, protocole="LOT42-RELEASE-BATCH-V1", **identite)
        conn.rollback()


@pytest.mark.parametrize("protocole", ["LOT42-V1", "LOT42-V2"])
@pytest.mark.parametrize("portee", COLONNES_BATCH)
def test_un_protocole_unitaire_ne_peut_pas_porter_une_identite_de_release(
    pg: dict[str, str], protocole: str, portee: str
) -> None:
    """Le batch ne contamine pas le chemin unitaire : une ligne V1/V2 qui
    porterait une identité de release serait une autorité fabriquée."""
    with psycopg.connect(superuser_dsn(pg)) as conn:
        with pytest.raises(
            psycopg.errors.CheckViolation,
            match="publication_attestations_release_identity_by_protocol",
        ):
            _inserer(conn, protocole=protocole, **{portee: _identite_batch()[portee]})
        conn.rollback()


def test_les_donnees_historiques_restent_valides(pg: dict[str, str]) -> None:
    """La migration s'applique à une base qui porte déjà des lignes : aucune
    ne doit être invalidée par la règle ajoutée."""
    with psycopg.connect(superuser_dsn(pg)) as conn:
        invalides = conn.execute(
            "SELECT count(*) FROM ingestion_control.publication_attestations "
            "WHERE protocol_version IN ('LOT42-V1','LOT42-V2') "
            "  AND release_id IS NOT NULL"
        ).fetchone()
        conn.rollback()
    assert invalides == (0,)


# --- Cas NOMINAL : une ligne batch valide doit pouvoir être enregistrée ----
#
# Les refus ci-dessus démontrent des protections. Ils ne démontrent pas
# qu'une attestation batch conforme peut exister : sans ce cas, une
# contrainte trop stricte passerait inaperçue.


def test_une_ligne_batch_complete_est_acceptee(
    pg: dict[str, str], ressource_reelle: tuple[object, object]
) -> None:
    resource_id, artifact_id = ressource_reelle
    with psycopg.connect(superuser_dsn(pg)) as conn:
        _inserer(
            conn, protocole="LOT42-RELEASE-BATCH-V1",
            resource_id=resource_id, artifact_id=artifact_id,
            **_identite_batch(),
        )
        ecrites = conn.execute(
            "SELECT count(*) FROM ingestion_control.publication_attestations "
            " WHERE protocol_version='LOT42-RELEASE-BATCH-V1' "
            "   AND release_id=%s",
            (_identite_batch()["release_id"],),
        ).fetchone()
        assert ecrites == (1,)
        conn.rollback()


@pytest.mark.parametrize("protocole", ["LOT42-V1", "LOT42-V2"])
def test_une_ligne_unitaire_reste_enregistrable(
    pg: dict[str, str], protocole: str, ressource_reelle: tuple[object, object]
) -> None:
    """La 016 ne doit invalider aucun chemin existant."""
    resource_id, artifact_id = ressource_reelle
    with psycopg.connect(superuser_dsn(pg)) as conn:
        _inserer(conn, protocole=protocole, resource_id=resource_id,
                 artifact_id=artifact_id)
        conn.rollback()


def test_le_role_attestor_peut_ecrire_une_attestation_batch(
    pg: dict[str, str], ressource_reelle: tuple[object, object]
) -> None:
    """Le rôle opérationnel, pas le propriétaire de la base.

    Une réussite avec le superutilisateur ne qualifierait pas le rôle qui
    écrira réellement les attestations.
    """
    resource_id, artifact_id = ressource_reelle
    with psycopg.connect(attestor_dsn(pg)) as conn:
        _inserer(
            conn, protocole="LOT42-RELEASE-BATCH-V1",
            resource_id=resource_id, artifact_id=artifact_id,
            **_identite_batch(),
        )
        conn.rollback()


# --- Le rollback : exécuté, pas seulement présent -------------------------


ROLLBACK = (
    Path(__file__).resolve().parents[2]
    / "infra/postgres/ingestion_control/rollbacks"
    / "016_lot42_batch_release_identity.down.sql"
)


def test_le_rollback_refuse_tant_qu_une_attestation_batch_existe(
    pg: dict[str, str], ressource_reelle: tuple[object, object]
) -> None:
    """Détruire l'identité de release rendrait les lignes INVÉRIFIABLES —
    pire qu'invalides. Le rollback refuse, et les données survivent."""
    resource_id, artifact_id = ressource_reelle
    with psycopg.connect(superuser_dsn(pg)) as conn:
        _inserer(
            conn, protocole="LOT42-RELEASE-BATCH-V1",
            resource_id=resource_id, artifact_id=artifact_id,
            **_identite_batch(),
        )
        conn.commit()
    try:
        with psycopg.connect(superuser_dsn(pg)) as conn:
            with pytest.raises(psycopg.errors.RaiseException, match="rollback 016 refused"):
                conn.execute(ROLLBACK.read_text(encoding="utf-8"))
            conn.rollback()
        # Les données sont intactes après le refus.
        with psycopg.connect(superuser_dsn(pg)) as conn:
            restantes = conn.execute(
                "SELECT count(*) FROM ingestion_control.publication_attestations "
                " WHERE protocol_version='LOT42-RELEASE-BATCH-V1'"
            ).fetchone()
            colonnes = conn.execute(
                "SELECT count(*) FROM information_schema.columns "
                " WHERE table_schema='ingestion_control' "
                "   AND table_name='publication_attestations' "
                "   AND column_name='release_id'"
            ).fetchone()
            conn.rollback()
        assert restantes == (1,)
        assert colonnes == (1,)
    finally:
        with psycopg.connect(superuser_dsn(pg)) as conn:
            conn.execute(
                "DELETE FROM ingestion_control.publication_attestations "
                " WHERE protocol_version='LOT42-RELEASE-BATCH-V1'"
            )
            conn.commit()


def test_le_rollback_s_applique_quand_aucune_attestation_batch_n_existe(
    pg: dict[str, str],
) -> None:
    """Puis la migration est réappliquée : le banc reste utilisable."""
    migration = (
        Path(__file__).resolve().parents[2]
        / "infra/postgres/ingestion_control/migrations"
        / "016_lot42_batch_release_identity.sql"
    )
    with psycopg.connect(superuser_dsn(pg)) as conn:
        conn.execute(ROLLBACK.read_text(encoding="utf-8"))
        conn.commit()
        absente = conn.execute(
            "SELECT count(*) FROM information_schema.columns "
            " WHERE table_schema='ingestion_control' "
            "   AND table_name='publication_attestations' "
            "   AND column_name='release_id'"
        ).fetchone()
        assert absente == (0,)
        conn.execute(migration.read_text(encoding="utf-8"))
        conn.commit()
        revenue = conn.execute(
            "SELECT count(*) FROM information_schema.columns "
            " WHERE table_schema='ingestion_control' "
            "   AND table_name='publication_attestations' "
            "   AND column_name='release_id'"
        ).fetchone()
        assert revenue == (1,)
