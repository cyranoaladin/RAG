"""Contrat statique de la migration 018 — adoption par un successeur (ADR-0059 § 5).

Lecture du SQL versionné et du script des rôles, sans base. La contre-partie
sur PostgreSQL réel vit dans
``tests/integration/test_migration_018_sealed_release_adoption.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ENGINE_ROOT / "infra/postgres/ingestion_control/migrations"
ROLLBACKS = ENGINE_ROOT / "infra/postgres/ingestion_control/rollbacks"
MIGRATION = MIGRATIONS / "018_sealed_release_adoption.sql"
ROLLBACK = ROLLBACKS / "018_sealed_release_adoption.down.sql"
ROLES = ENGINE_ROOT / "infra/scripts/provision_ingestion_control_roles.sh"


def _code(path: Path) -> str:
    return "\n".join(
        ligne
        for ligne in path.read_text(encoding="utf-8").splitlines()
        if not ligne.strip().startswith("--")
    )


def test_la_migration_018_est_la_tete_declaree_et_reversible() -> None:
    assert (MIGRATIONS / "HEAD").read_text(encoding="utf-8") == (
        "018_sealed_release_adoption\n"
    )
    assert MIGRATION.is_file()
    assert ROLLBACK.is_file()


def test_la_transaction_appartient_au_runner() -> None:
    """Leçon du lot CU : un BEGIN/COMMIT interne défait `--single-transaction`."""
    for path in (MIGRATION, ROLLBACK):
        code = _code(path)
        assert not re.search(r"^\s*BEGIN\s*;", code, re.M), path.name
        assert not re.search(r"^\s*COMMIT\s*;", code, re.M), path.name


def test_l_adoption_est_en_ajout_seul_par_le_schema() -> None:
    code = _code(MIGRATION)
    assert "BEFORE UPDATE OR DELETE ON ingestion_control.sealed_release_adoptions" in code
    assert "RAISE EXCEPTION" in code


def test_seules_les_actualites_publiables_sont_adoptables() -> None:
    code = _code(MIGRATION)
    assert "CHECK (currentness IN ('current', 'official_snapshot'))" in code


def test_un_successeur_n_est_jamais_son_predecesseur() -> None:
    code = _code(MIGRATION)
    assert "CHECK (release_id <> predecessor_release_id)" in code
    assert (
        "CHECK (release_manifest_sha256 <> predecessor_release_manifest_sha256)" in code
    )


def test_l_adoption_nomme_les_preuves_qui_la_fondent() -> None:
    code = _code(MIGRATION)
    for colonne in (
        "currentness_evidence_sha256",
        "pii_evidence_sha256",
        "release_manifest_sha256",
        "candidate_inventory_sha256",
        "predecessor_release_manifest_sha256",
    ):
        assert re.search(rf"^\s*{colonne}\s+TEXT NOT NULL", code, re.M), colonne


def test_un_placement_n_est_adopte_qu_une_fois_par_successeur() -> None:
    assert (
        "ON ingestion_control.sealed_release_adoptions (release_id, resource_id, artifact_id)"
        in _code(MIGRATION)
    )


def test_le_rollback_refuse_de_detruire_une_adoption() -> None:
    code = _code(ROLLBACK)
    verrou = code.index("LOCK TABLE ingestion_control.sealed_release_adoptions")
    controle = code.index("rollback 018 refused")
    destruction = code.index("DROP TABLE IF EXISTS ingestion_control.sealed_release_adoptions")
    assert verrou < controle < destruction
    assert "SET LOCAL lock_timeout" in code


def test_l_attestor_ecrit_et_le_worker_lit_seulement() -> None:
    roles = ROLES.read_text(encoding="utf-8")
    assert (
        'GRANT SELECT, INSERT ON ingestion_control.sealed_release_adoptions TO :"attestor_role"'
        in roles
    )
    assert 'GRANT SELECT ON ingestion_control.sealed_release_adoptions TO :"app_role"' in roles
    assert re.search(
        r"REVOKE INSERT, UPDATE, DELETE, TRUNCATE\s+ON ingestion_control\.sealed_release_adoptions"
        r' FROM :"app_role"',
        roles,
    )
    assert re.search(
        r"REVOKE UPDATE, DELETE, TRUNCATE\s+ON ingestion_control\.sealed_release_adoptions"
        r' FROM :"attestor_role"',
        roles,
    )
