"""Contrat statique de la migration 015 — preuve de revue scellée.

Lecture du SQL versionné, sans base. La contrepartie sur PostgreSQL réel
vit dans `tests/integration/test_sealed_trusted_review_evidence_pg.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ENGINE_ROOT / "infra/postgres/ingestion_control/migrations"
ROLLBACKS = ENGINE_ROOT / "infra/postgres/ingestion_control/rollbacks"
MIGRATION = MIGRATIONS / "015_sealed_trusted_review_evidence.sql"
ROLLBACK = ROLLBACKS / "015_sealed_trusted_review_evidence.down.sql"

SQL = MIGRATION.read_text(encoding="utf-8")
DOWN = ROLLBACK.read_text(encoding="utf-8")


def _sans_commentaires(sql: str) -> str:
    return "\n".join(
        ligne for ligne in sql.splitlines() if not ligne.strip().startswith("--")
    )


CODE = _sans_commentaires(SQL)
CODE_DOWN = _sans_commentaires(DOWN)


def _extrait(sql: str, contrainte: str) -> str:
    """Le corps de l'ADD CONSTRAINT — pas celui du DROP qui le précède.

    Chaque contrainte est posée après un `DROP CONSTRAINT IF EXISTS`
    homonyme (idempotence) : chercher le nom tout court rendrait le
    DROP, et l'épreuve vérifierait une instruction vide."""
    debut = sql.index(f"ADD CONSTRAINT {contrainte}")
    return sql[debut : sql.index(";", debut)]


def test_la_migration_015_est_la_tete_declaree() -> None:
    assert (MIGRATIONS / "HEAD").read_text(encoding="utf-8") == (
        "017_sealed_release_projection\n"
    )
    assert MIGRATION.is_file()
    assert ROLLBACK.is_file()


def test_la_migration_n_ouvre_pas_sa_propre_transaction() -> None:
    for texte, etiquette in ((CODE, "migration"), (CODE_DOWN, "rollback")):
        assert not re.search(r"^\s*BEGIN;", texte, re.M), etiquette
        assert not re.search(r"^\s*COMMIT;", texte, re.M), etiquette


def test_la_migration_est_idempotente() -> None:
    ajouts = re.findall(r"ADD CONSTRAINT (\w+)", CODE)
    drops = set(re.findall(r"DROP CONSTRAINT IF EXISTS (\w+)", CODE))
    assert ajouts
    assert [a for a in ajouts if a not in drops] == []
    assert re.findall(r"ADD COLUMN(?! IF NOT EXISTS)", CODE) == []
    assert "CREATE TABLE IF NOT EXISTS" in CODE
    assert "CREATE INDEX IF NOT EXISTS" in CODE


def test_la_contrainte_d_appariement_neutralise_la_logique_ternaire() -> None:
    """Le piège qui a été trouvé sur base réelle, et qui ne doit pas revenir.

    Sans `IS NOT NULL` explicite, `NULL ~ '...'` vaut NULL, la branche vaut
    NULL, et un CHECK qui vaut NULL est ACCEPTÉ par PostgreSQL — seul FALSE
    rejette. Une preuve sans digest passait donc la contrainte. Le motif
    seul ne l'aurait jamais montré."""
    contrainte = _extrait(CODE, "scope_authorizations_review_evidence_paired")
    assert "review_evidence IS NOT NULL" in contrainte
    assert "review_evidence_digest IS NOT NULL" in contrainte
    assert "review_evidence_digest ~ '^[0-9a-f]{64}$'" in contrainte
    assert "review_evidence <> '{}'::jsonb" in contrainte
    # Chaque colonne comparée à un motif doit d'abord être exclue de NULL.
    for colonne in ("review_evidence_digest",):
        motif = contrainte.index(f"{colonne} ~")
        assert f"{colonne} IS NOT NULL" in contrainte[:motif], colonne


def test_le_protocole_de_la_preuve_est_contraint() -> None:
    contrainte = _extrait(CODE, "scope_authorizations_review_evidence_protocol")
    assert "NEXUS-SEALED-TRUSTED-REVIEW-EVIDENCE-V1" in contrainte
    # La branche NULL est explicite : une ligne sans preuve reste admise en
    # base, et c'est l'USAGE qui la refuse — pas la contrainte.
    assert "review_evidence IS NULL" in contrainte


def test_la_colonne_reste_nullable_et_c_est_deliberé() -> None:
    """Aucun backfill n'est possible : une revue ne se reconstitue pas."""
    assert "ADD COLUMN IF NOT EXISTS review_evidence JSONB" in CODE
    assert "review_evidence JSONB NOT NULL" not in CODE
    assert "aucun backfill" in SQL.lower() or "Aucun backfill" in SQL


def test_le_registre_de_revocation_porte_sa_propre_preuve() -> None:
    """Révoquer est une décision humaine, pas un geste administratif."""
    assert "CREATE TABLE IF NOT EXISTS ingestion_control.revoked_review_evidence" in CODE
    for colonne in (
        "revoked_by", "reason",
        "evidence_repository", "evidence_pull_request", "evidence_head_sha",
        "evidence_reviewer", "evidence_challenge",
    ):
        assert re.search(rf"^\s+{colonne}\s+", CODE, re.M), colonne


def test_le_rollback_refuse_de_detruire_une_preuve() -> None:
    assert "LOCK TABLE" in CODE_DOWN
    assert CODE_DOWN.index("LOCK TABLE") < CODE_DOWN.index("SELECT count(*)")
    assert "RAISE EXCEPTION" in CODE_DOWN
    assert "rollback 015 refusé" in DOWN


def test_le_rollback_refuse_aussi_de_perdre_les_revocations() -> None:
    """Les perdre ressusciterait des autorisations explicitement éteintes."""
    assert "revoked_review_evidence" in CODE_DOWN
    assert CODE_DOWN.count("RAISE EXCEPTION") >= 2
