"""Contrat statique de la migration 019 — autorité de publication d'un successeur (ADR-0060).

Un placement adopté conserve l'autorisation qui a fondé son acquisition : elle
dit ce qui a été permis HIER. La publication par le successeur exige une
autorisation liée au contenu (LOT41A-V2). La migration 019 les tient séparées :
une liaison en ajout seul nomme, pour chaque placement adopté, l'autorisation
de PUBLICATION — sans toucher au payload acquis ni à l'adoption.
"""

from __future__ import annotations

import re
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ENGINE_ROOT / "infra/postgres/ingestion_control/migrations"
ROLLBACKS = ENGINE_ROOT / "infra/postgres/ingestion_control/rollbacks"
NOM = "019_sealed_release_publication_authorizations"
MIGRATION = MIGRATIONS / f"{NOM}.sql"
ROLLBACK = ROLLBACKS / f"{NOM}.down.sql"
ROLES = ENGINE_ROOT / "infra/scripts/provision_ingestion_control_roles.sh"
TABLE = "ingestion_control.sealed_release_publication_authorizations"


def _code(path: Path) -> str:
    return "\n".join(
        ligne
        for ligne in path.read_text(encoding="utf-8").splitlines()
        if not ligne.strip().startswith("--")
    )


def test_la_migration_019_est_la_tete_declaree_et_reversible() -> None:
    assert (MIGRATIONS / "HEAD").read_text(encoding="utf-8") == f"{NOM}\n"
    assert MIGRATION.is_file() and ROLLBACK.is_file()


def test_la_transaction_appartient_au_runner() -> None:
    for path in (MIGRATION, ROLLBACK):
        code = _code(path)
        assert not re.search(r"^\s*BEGIN\s*;", code, re.M), path.name
        assert not re.search(r"^\s*COMMIT\s*;", code, re.M), path.name


def test_la_liaison_est_en_ajout_seul() -> None:
    code = _code(MIGRATION)
    assert f"BEFORE UPDATE OR DELETE ON {TABLE}" in code
    assert "RAISE EXCEPTION" in code


def test_la_liaison_porte_sur_un_placement_adopte_et_une_autorisation_existante() -> None:
    code = _code(MIGRATION)
    assert re.search(
        r"FOREIGN KEY \(release_id, resource_id, artifact_id\)\s+REFERENCES "
        r"ingestion_control\.sealed_release_adoptions \(release_id, resource_id, artifact_id\)",
        code,
    )
    assert re.search(
        r"scope_authorization_id\s+TEXT NOT NULL\s+REFERENCES "
        r"ingestion_control\.scope_authorizations\(authorization_id\)",
        code,
    )


def test_l_autorite_d_acquisition_est_conservee_a_cote_et_distincte() -> None:
    code = _code(MIGRATION)
    assert re.search(r"^\s*acquisition_scope_authorization_id\s+TEXT NOT NULL", code, re.M)
    assert "CHECK (scope_authorization_id <> acquisition_scope_authorization_id)" in code


def test_un_placement_n_a_qu_une_autorite_de_publication_par_successeur() -> None:
    assert f"ON {TABLE} (release_id, resource_id, artifact_id)" in _code(MIGRATION)


def test_les_roles_attestor_ecrit_app_lit() -> None:
    roles = ROLES.read_text(encoding="utf-8")
    assert f"GRANT SELECT, INSERT ON {TABLE} TO :\"attestor_role\"" in roles
    assert f"GRANT SELECT ON {TABLE} TO :\"app_role\"" in roles
    assert re.search(rf"REVOKE UPDATE, DELETE, TRUNCATE\s+ON {re.escape(TABLE)} FROM :\"attestor_role\"", roles)


def test_le_rollback_refuse_de_detruire_des_liaisons() -> None:
    code = _code(ROLLBACK)
    assert "LOCK TABLE" in code and "RAISE EXCEPTION" in code
