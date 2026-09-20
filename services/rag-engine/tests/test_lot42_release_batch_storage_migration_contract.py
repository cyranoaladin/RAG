"""Contrat statique de la migration 014 — stockage LOT42-RELEASE-BATCH-V1.

Ces épreuves lisent le SQL versionné, sans base. Elles prouvent ce qu'une
exécution ne montrerait pas aussi clairement : que la migration est
CONDITIONNELLE, et non permissive. La contre-partie sur PostgreSQL réel vit
dans `tests/integration/test_lot42_release_batch_migration_014.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ENGINE_ROOT / "infra/postgres/ingestion_control/migrations"
ROLLBACKS = ENGINE_ROOT / "infra/postgres/ingestion_control/rollbacks"
MIGRATION = MIGRATIONS / "014_lot42_release_batch_storage.sql"
ROLLBACK = ROLLBACKS / "014_lot42_release_batch_storage.down.sql"

SQL = MIGRATION.read_text(encoding="utf-8")
DOWN = ROLLBACK.read_text(encoding="utf-8")


def _sans_commentaires(sql: str) -> str:
    return "\n".join(
        ligne for ligne in sql.splitlines() if not ligne.strip().startswith("--")
    )


CODE = _sans_commentaires(SQL)


# --- 13 — la migration est déclarée, versionnée et réversible ------------


def test_la_migration_014_est_la_tete_declaree() -> None:
    assert (MIGRATIONS / "HEAD").read_text(encoding="utf-8") == (
        "014_lot42_release_batch_storage\n"
    )
    assert MIGRATION.is_file()
    assert ROLLBACK.is_file()


def test_la_migration_est_transactionnelle() -> None:
    """Une migration à moitié appliquée serait pire que pas de migration."""
    assert CODE.strip().startswith("BEGIN;")
    assert CODE.strip().endswith("COMMIT;")


# --- 1 / 2 / 3 — resource_pipeline et LOT42-V1 restent exigeants --------


def test_resource_pipeline_exige_toujours_une_canonical_url_non_vide() -> None:
    contrainte = _extrait(CODE, "resource_candidates_canonical_url_by_pipeline")
    assert "pipeline_kind = 'resource_pipeline'" in contrainte
    assert "canonical_url IS NOT NULL" in contrainte
    assert "btrim(canonical_url) <> ''" in contrainte


def test_lot42_v1_et_v2_exigent_toujours_une_canonical_url_non_vide() -> None:
    contrainte = _extrait(CODE, "publication_attestations_canonical_url_by_protocol")
    assert "'LOT42-V1', 'LOT42-V2'" in contrainte
    assert "canonical_url IS NOT NULL" in contrainte
    assert "btrim(canonical_url) <> ''" in contrainte


def test_aucune_colonne_n_est_rendue_nullable_sans_contrainte_conditionnelle() -> None:
    """`DROP NOT NULL` n'est acceptable que suivi d'un CHECK qui le remplace."""
    tables = re.findall(
        r"ALTER TABLE ingestion_control\.(\w+)\s*\n\s*ALTER COLUMN (\w+) DROP NOT NULL",
        CODE,
    )
    assert tables, "la migration doit expliciter les colonnes qu'elle ouvre"
    for table, colonne in tables:
        assert colonne == "canonical_url", (table, colonne)
        # Une contrainte conditionnelle doit exister pour cette table.
        assert re.search(rf"{table}_canonical_url_by_\w+", CODE), table


# --- 4 / 5 — la release scellée ne peut pas porter de canonical_url -----


def test_une_release_scellee_doit_avoir_canonical_url_null() -> None:
    """« doit », pas « peut » : une valeur fabriquée est refusée par la base."""
    for contrainte in (
        _extrait(CODE, "resource_candidates_canonical_url_by_pipeline"),
        _extrait(CODE, "publication_attestations_canonical_url_by_protocol"),
    ):
        assert "canonical_url IS NULL" in contrainte


def test_la_release_scellee_n_a_aucune_branche_permissive() -> None:
    """Aucun `OR canonical_url IS NOT NULL` pour l'origine scellée."""
    contrainte = _extrait(CODE, "resource_candidates_canonical_url_by_pipeline")
    scellee = contrainte.split("sealed_release_pipeline", 1)[1]
    assert "IS NOT NULL" not in scellee


# --- 7 / 9 — provenance et identité canonique ne se confondent pas ------


def test_la_migration_ne_touche_pas_artifacts() -> None:
    """`original_url` / `final_url` sont de la provenance : rien à changer."""
    assert "ingestion_control.artifacts" not in CODE


def test_source_url_n_est_jamais_ecrite_dans_canonical_url() -> None:
    assert "source_url" not in CODE
    assert "source_url" not in DOWN


# --- 8 / 10 — l'origine est une donnée déclarée -------------------------


def test_l_origine_est_une_colonne_contrainte_a_deux_valeurs() -> None:
    for table in ("resources", "resource_candidates"):
        contrainte = _extrait(CODE, f"{table}_pipeline_kind_valid")
        assert "'resource_pipeline'" in contrainte
        assert "'sealed_release_pipeline'" in contrainte


def test_le_defaut_preserve_tout_l_existant() -> None:
    """Les lignes déjà en base restent `resource_pipeline`, donc exigeantes."""
    ajouts = re.findall(
        r"ADD COLUMN IF NOT EXISTS pipeline_kind TEXT NOT NULL\s*\n\s*"
        r"DEFAULT '(\w+)'",
        CODE,
    )
    assert ajouts, "pipeline_kind doit avoir un défaut explicite"
    assert set(ajouts) == {"resource_pipeline"}


def test_le_troisieme_protocole_est_admis_partout_ou_il_doit_l_etre() -> None:
    for contrainte in (
        "publication_attestations_protocol_version_valid",
        "publication_commit_pins_publication_protocol_valid",
    ):
        assert "'LOT42-RELEASE-BATCH-V1'" in _extrait(CODE, contrainte)


def test_le_digest_d_attribution_reste_reserve_a_v2() -> None:
    """Une attestation de release ne doit pas pouvoir porter un digest V2."""
    contrainte = _extrait(CODE, "publication_attestations_attribution_digest_matches_protocol")
    assert "protocol_version = 'LOT42-V2' AND attributed_facts_digest IS NOT NULL" in contrainte
    assert "'LOT42-V1', 'LOT42-RELEASE-BATCH-V1'" in contrainte
    assert "attributed_facts_digest IS NULL" in contrainte


# --- 13 — le rollback est fail-closed ------------------------------------


def test_le_rollback_refuse_plutot_que_de_fabriquer_ou_de_detruire() -> None:
    assert "RAISE EXCEPTION" in DOWN
    assert "sealed_release_pipeline" in DOWN
    assert "LOT42-RELEASE-BATCH-V1" in DOWN
    # Le refus précède toute modification de contrainte.
    position_refus = DOWN.index("RAISE EXCEPTION")
    position_premier_alter = DOWN.index("DROP CONSTRAINT IF EXISTS")
    assert position_refus < position_premier_alter


def test_le_rollback_verrouille_avant_de_compter() -> None:
    """Sans verrou, une ligne pourrait apparaître entre le contrôle et la bascule."""
    for table in ("resource_candidates", "resources", "publication_attestations"):
        assert f"LOCK TABLE ingestion_control.{table} IN ACCESS EXCLUSIVE MODE" in DOWN
    assert DOWN.index("LOCK TABLE") < DOWN.index("RAISE EXCEPTION")


def test_le_rollback_restaure_exactement_les_contraintes_anterieures() -> None:
    assert "ALTER COLUMN canonical_url SET NOT NULL" in DOWN
    assert "publication_attestations_canonical_url_not_blank" in DOWN
    assert "resource_candidates_canonical_url_not_blank" in DOWN
    assert "CHECK (protocol_version IN ('LOT42-V1', 'LOT42-V2'))" in DOWN


def test_le_rollback_ne_supprime_aucune_ligne() -> None:
    assert not re.search(r"\bDELETE\s+FROM\b", DOWN)
    assert not re.search(r"\bTRUNCATE\b", DOWN)
    assert not re.search(r"\bDROP\s+TABLE\b", DOWN)


# --- 14 / 15 / 16 / 18 — périmètre du lot --------------------------------


def test_la_migration_ne_touche_que_le_schema_ingestion_control() -> None:
    tables = set(re.findall(r"ALTER TABLE (\S+)", CODE))
    assert tables, "la migration doit nommer les tables qu'elle modifie"
    for table in tables:
        assert table.startswith("ingestion_control."), table


def test_la_migration_ne_declenche_aucune_publication() -> None:
    for interdit in ("rag_chunks", "rag_artifacts", "rag_artifact_placements",
                     "rag_pgvector", "PG_RAG_DSN"):
        assert interdit not in CODE, interdit
        assert interdit not in DOWN, interdit


def test_la_migration_n_insere_aucune_attestation() -> None:
    assert not re.search(r"INSERT\s+INTO\s+ingestion_control\.publication_attestations", CODE)


def _extrait(sql: str, nom_contrainte: str) -> str:
    """Le texte de la contrainte nommée, jusqu'au point-virgule."""
    debut = sql.index(f"ADD CONSTRAINT {nom_contrainte}")
    return sql[debut : sql.index(";", debut)]
