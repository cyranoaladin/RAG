"""Opération ``successor_control_schema_020_and_adopter_role`` sur PostgreSQL réel.

État de départ = état attendu du staging : schéma de contrôle à 019 (runner
canonique de rollback), les QUATRE rôles historiques provisionnés par le
script canonique, aucun rôle adopter, des lignes V4 acquises par les vraies
primitives. Le conteneur journalise toutes les instructions
(``log_statement=all``) pour prouver qu'aucun secret n'y paraît.

Secrets synthétiques de banc uniquement. Opt-in : ``NEXUS_HGGSP_PG=1``.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

if os.environ.get("NEXUS_HGGSP_PG") != "1":
    pytest.skip("PostgreSQL jetable opt-in (NEXUS_HGGSP_PG=1)", allow_module_level=True)

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / "services/rag-engine"
for chemin in (ENGINE / "src", ENGINE / "tests/integration", ROOT / "scripts/go_live",
               ROOT / "packages/contracts/src"):
    sys.path.insert(0, str(chemin))

import hggsp_control_schema_020 as op  # noqa: E402
import psycopg  # noqa: E402
from _pg_authority import (  # noqa: E402
    APP_PASSWORD,
    ATTESTOR_PASSWORD,
    AUTHORITY_PASSWORD,
    MIGRATOR_PASSWORD,
    PG_IMAGE,
    PG_SUPERUSER,
    PG_SUPERUSER_PASSWORD,
    _wait_pg_isready,
    free_port,
)

DB = op.DATABASE
SCRIPTS = ENGINE / "infra/scripts"
HISTORIQUES = ("ingestion_control_migrator", "ingestion_control_app",
               "ingestion_control_authority", "ingestion_control_attestor")
CINQ = ("ingestion-control-app.env", "ingestion-control-attestor.env",
        "ingestion-control-authority.env", "rag-publisher.env", "rag-reader.env")


def _run(script: str, env: dict[str, str], **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SCRIPTS / script)], env={**env, **extra}, cwd=ENGINE,
                          capture_output=True, text=True, check=False)


def _sql(env: dict[str, str], requete: str) -> list[tuple[Any, ...]]:
    dsn = (f"host={env['PGHOST']} port={env['PGPORT']} dbname={DB} "
           f"user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}")
    with psycopg.connect(dsn, autocommit=True) as conn:
        cur = conn.execute(requete)
        return cur.fetchall() if cur.description else []


def _head(env: dict[str, str]) -> int:
    return int(_sql(env, "SELECT max(version) FROM ingestion_control.schema_migrations")[0][0])


@pytest.fixture()
def staging(tmp_path: Path) -> Iterator[dict[str, Any]]:
    nom = f"nexus-hggsp-control020-{uuid.uuid4().hex[:10]}"
    port = free_port()
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", nom,
         "-e", f"POSTGRES_USER={PG_SUPERUSER}", "-e", f"POSTGRES_PASSWORD={PG_SUPERUSER_PASSWORD}",
         "-e", f"POSTGRES_DB={DB}", "-p", f"127.0.0.1:{port}:5432", PG_IMAGE,
         "-c", "log_statement=all"],
        check=True, capture_output=True,
    )
    fixture = None
    try:
        _wait_pg_isready(port)
        env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"),
               "PGHOST": "127.0.0.1", "PGPORT": str(port), "PGUSER": PG_SUPERUSER,
               "PGPASSWORD": PG_SUPERUSER_PASSWORD, "PGDATABASE": DB}
        assert "BOOTSTRAP_COMPLETE" in _run("bootstrap_ingestion_control_schema.sh", env).stdout
        rollback = _run("rollback_ingestion_control_schema.sh", env, TARGET_VERSION="19")
        assert rollback.returncode == 0, rollback.stderr
        historique = _run(
            "provision_ingestion_control_roles.sh", env,
            INGESTION_CONTROL_MIGRATOR_PASSWORD=MIGRATOR_PASSWORD,
            INGESTION_CONTROL_APP_PASSWORD=APP_PASSWORD,
            INGESTION_CONTROL_AUTHORITY_PASSWORD=AUTHORITY_PASSWORD,
            INGESTION_CONTROL_ATTESTOR_PASSWORD=ATTESTOR_PASSWORD,
        )
        assert historique.returncode == 0, historique.stderr
        assert _head(env) == 19
        assert not _sql(env, f"SELECT 1 FROM pg_roles WHERE rolname = '{op.ADOPTER}'")
        from test_migration_018_sealed_release_adoption import lignes_acquises

        pg = {"host": "127.0.0.1", "port": str(port), "dbname": DB}
        fixture = lignes_acquises.__wrapped__(pg)  # type: ignore[attr-defined]
        contenus = next(fixture)
        secrets_dir = tmp_path / "secrets"
        secrets_dir.mkdir(mode=0o700)
        roles = tmp_path / "roles"
        roles.mkdir(mode=0o700)
        for nom_fichier in CINQ:  # les cinq fichiers historiques, à ne pas toucher
            (roles / nom_fichier).write_text(f"MARQUEUR={nom_fichier}\n")
            (roles / nom_fichier).chmod(0o600)
        sauvegarde = tmp_path / "backup" / f"{DB}.dump"
        sauvegarde.parent.mkdir(mode=0o700)
        with sauvegarde.open("wb") as flux:
            subprocess.run(["docker", "exec", nom, "pg_dump", "-Fc", "-U", PG_SUPERUSER, DB],
                           stdout=flux, check=True)
        sauvegarde.chmod(0o600)
        yield {"env": env, "pg": pg, "container": nom, "contents": contenus,
               "secret": secrets_dir / "ingestion_control_adopter.password",
               "roles": roles, "backup": sauvegarde}
    finally:
        if fixture is not None:
            fixture.close()
        subprocess.run(["docker", "rm", "-f", nom], capture_output=True, check=False)


def _apply(st: dict[str, Any], **env_extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/go_live/hggsp_control_schema_020.py"), "apply",
         "--repository-root", str(ROOT), "--secret-file", str(st["secret"]),
         "--roles-dir", str(st["roles"]), "--backup-file", str(st["backup"])],
        env={**st["env"], **env_extra}, capture_output=True, text=True, check=False,
    )


def _roles_historiques(env: dict[str, str]) -> list[tuple[Any, ...]]:
    return _sql(env, (
        "SELECT r.rolname, r.rolpassword, r.rolsuper, r.rolinherit, r.rolcreaterole, "
        "r.rolcreatedb, r.rolcanlogin, r.rolreplication, r.rolbypassrls, "
        "(SELECT array_agg(g.rolname ORDER BY g.rolname) FROM pg_auth_members m "
        " JOIN pg_roles g ON g.oid = m.roleid WHERE m.member = r.oid) "
        "FROM pg_authid r WHERE r.rolname = ANY(ARRAY" + str(list(HISTORIQUES)) + ") ORDER BY 1"))


def _mot_de_passe_adopter(env: dict[str, str]) -> str:
    return _sql(env, f"SELECT rolpassword FROM pg_authid WHERE rolname = '{op.ADOPTER}'")[0][0]


def _dsn(st: dict[str, Any]) -> str:
    ligne = (st["roles"] / op.FICHIER_DSN).read_text()
    variable, _, dsn = ligne.strip().partition("=")
    assert variable == "PG_INGESTION_CONTROL_ADOPTER_DSN"
    return dsn


def test_depuis_019_migration_role_secret_et_dsn_sans_toucher_l_historique(
    staging: dict[str, Any],
) -> None:
    env = staging["env"]
    historiques = _roles_historiques(env)
    cinq = {n: (staging["roles"] / n).read_bytes() for n in CINQ}
    avant = op.empreintes(env)
    sortie = _apply(staging)
    assert sortie.returncode == 0, sortie.stderr
    assert "HGGSP_CONTROL020_SECRET state=created mode=0600" in sortie.stdout
    assert "HGGSP_CONTROL020_MIGRATED from=19 to=20" in sortie.stdout
    assert "HGGSP_CONTROL020_OK head=20 adopter=ingestion_control_adopter v2=0 " in sortie.stdout
    assert _head(env) == 20
    # Rôles historiques : mots de passe, attributs et appartenances identiques.
    assert _roles_historiques(env) == historiques
    # Les cinq fichiers historiques ne sont ni relus comme cible ni réécrits.
    assert {n: (staging["roles"] / n).read_bytes() for n in CINQ} == cinq
    assert op.empreintes(env) == avant
    secret = op.lire_secret(staging["secret"])
    assert secret and stat.S_IMODE(staging["secret"].stat().st_mode) == 0o600
    assert stat.S_IMODE((staging["roles"] / op.FICHIER_DSN).stat().st_mode) == 0o600
    # Aucune fuite : ni la valeur ni le vérificateur, ni en sortie ni au serveur.
    journal = subprocess.run(["docker", "logs", staging["container"]],
                             capture_output=True, text=True, check=False)
    for texte in (sortie.stdout, sortie.stderr, journal.stdout, journal.stderr):
        assert secret not in texte
        assert "SCRAM-SHA-256$" not in texte
    # Connexion réelle avec le DSN dérivé, droits effectifs vérifiés.
    with psycopg.connect(_dsn(staging)) as conn:
        assert conn.execute("SELECT current_user, current_database()").fetchone() == (op.ADOPTER, DB)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE ingestion_control.resources SET last_error = 'interdit'")
    assert op.exiger_moindre_privilege(op.droits_effectifs(env)) == []


def test_rejeu_sans_rotation_ni_doublon(staging: dict[str, Any]) -> None:
    assert _apply(staging).returncode == 0
    empreinte = _mot_de_passe_adopter(staging["env"])
    dsn = (staging["roles"] / op.FICHIER_DSN).read_bytes()
    rejeu = _apply(staging)
    assert rejeu.returncode == 0, rejeu.stderr
    assert "state=reused_verified" in rejeu.stdout
    assert "HGGSP_CONTROL020_MIGRATED state=already_020" in rejeu.stdout
    assert f"file={op.FICHIER_DSN} state=UNCHANGED" in rejeu.stdout
    assert _mot_de_passe_adopter(staging["env"]) == empreinte
    assert (staging["roles"] / op.FICHIER_DSN).read_bytes() == dsn
    assert int(_sql(staging["env"], f"SELECT count(*) FROM pg_roles WHERE rolname = '{op.ADOPTER}'")[0][0]) == 1


def test_mauvaise_base_refusee_sans_ecriture(staging: dict[str, Any]) -> None:
    sortie = _apply(staging, PGDATABASE="postgres")
    assert sortie.returncode == 1 and "HGGSP_CONTROL020_OK" not in sortie.stdout
    assert not staging["secret"].exists()
    assert _head(staging["env"]) == 19


def test_role_sans_secret_ou_secret_incoherent_refuses_sans_reinitialisation(
    staging: dict[str, Any],
) -> None:
    assert _apply(staging).returncode == 0
    empreinte = _mot_de_passe_adopter(staging["env"])
    original = staging["secret"].read_text()
    staging["secret"].unlink()
    sans = _apply(staging)
    assert sans.returncode == 1 and "secret conservé introuvable" in sans.stderr
    staging["secret"].write_text(op.secrets.token_urlsafe(48) + "\n")
    staging["secret"].chmod(0o600)
    faux = _apply(staging)
    assert faux.returncode == 1 and "incohérents" in faux.stderr
    assert "HGGSP_CONTROL020_OK" not in sans.stdout + faux.stdout
    assert _mot_de_passe_adopter(staging["env"]) == empreinte
    # DSN divergent : jamais écrasé.
    staging["secret"].write_text(original)
    staging["secret"].chmod(0o600)
    (staging["roles"] / op.FICHIER_DSN).write_text("PG_INGESTION_CONTROL_ADOPTER_DSN=divergent\n")
    divergent = _apply(staging)
    assert divergent.returncode == 1 and "rien n'est écrasé" in divergent.stderr


def test_job_en_cours_refuse_avant_ecriture(staging: dict[str, Any]) -> None:
    from ingestor.ingestion_control.jobs import create_job

    env = staging["env"]
    run_id, resource_id = _sql(env, "SELECT run_id, resource_id FROM ingestion_control.resources LIMIT 1")[0]
    dsn = (f"host={env['PGHOST']} port={env['PGPORT']} dbname={DB} "
           f"user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}")
    with psycopg.connect(dsn) as conn:
        job = create_job(conn, run_id=run_id, resource_id=resource_id,
                         job_type="publication_resume", payload={"banc": "concurrence"})
        conn.execute("UPDATE ingestion_control.jobs SET status = 'running' WHERE job_id = %s", (job,))
        conn.commit()
    sortie = _apply(staging)
    assert sortie.returncode == 1 and "concurrence" in sortie.stderr
    assert not staging["secret"].exists() and _head(env) == 19


def test_reprises_apres_interruption(staging: dict[str, Any]) -> None:
    env = staging["env"]
    # (a) secret conservé, rôle et migration absents.
    op.creer_secret(staging["secret"])
    a = _apply(staging)
    assert a.returncode == 0 and "state=reused_before_role" in a.stdout
    # (b) rôle et secret présents, DSN perdu : dérivé à nouveau, sans rotation.
    empreinte = _mot_de_passe_adopter(env)
    (staging["roles"] / op.FICHIER_DSN).unlink()
    b = _apply(staging)
    assert b.returncode == 0 and "state=reused_verified" in b.stdout
    assert f"file={op.FICHIER_DSN} state=WRITTEN" in b.stdout
    assert _mot_de_passe_adopter(env) == empreinte


def test_migration_deja_faite_puis_role(staging: dict[str, Any]) -> None:
    """(c) interruption après la migration, avant le rôle."""
    env = staging["env"]
    op.creer_secret(staging["secret"])
    assert "BOOTSTRAP_COMPLETE" in _run("bootstrap_ingestion_control_schema.sh", env).stdout
    sortie = _apply(staging)
    assert sortie.returncode == 0, sortie.stderr
    assert "HGGSP_CONTROL020_MIGRATED state=already_020" in sortie.stdout


def test_rollback_permis_sans_v2_puis_refuse_apres_adoption_v2_reelle(
    staging: dict[str, Any],
) -> None:
    env = staging["env"]
    assert _apply(staging).returncode == 0
    # Sans V2 : rollback canonique permis ; rôle, secret et DSN restent en place.
    retour = _run("rollback_ingestion_control_schema.sh", env, TARGET_VERSION="19")
    assert retour.returncode == 0, retour.stderr
    assert _head(env) == 19
    assert _sql(env, f"SELECT 1 FROM pg_roles WHERE rolname = '{op.ADOPTER}'")
    assert staging["secret"].exists() and (staging["roles"] / op.FICHIER_DSN).exists()
    # Reprise : 020 réappliquée, rôle réutilisé.
    reprise = _apply(staging)
    assert reprise.returncode == 0 and "from=19 to=20" in reprise.stdout
    # Adoption V2 par les vraies primitives, sous le DSN dérivé.
    from test_migration_020_successor_control_identity import _attribute, _v5_plan

    from ingestor.ingestion_control.sealed_release_adoption import (
        persist_successor_control_adoption,
    )

    _attribute(staging["pg"], staging["contents"])
    with psycopg.connect(_dsn(staging)) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        lignes = _v5_plan(conn, staging["contents"])
        assert persist_successor_control_adoption(conn, lignes=lignes, adopted_by="banc")[2] == 2
    refus = _run("rollback_ingestion_control_schema.sh", env, TARGET_VERSION="19")
    assert refus.returncode != 0 and "rollback 020 refused" in refus.stderr
    assert _head(env) == 20
    # L'étape préparatoire rejouée constate la V2 existante sans la modifier.
    rejeu = _apply(staging)
    assert rejeu.returncode == 0 and " v2=2 " in rejeu.stdout


def test_parite_des_droits_avec_le_provisionneur_canonique(staging: dict[str, Any]) -> None:
    """Le provisionneur ciblé donne exactement les droits du bloc adopter canonique."""
    env = staging["env"]
    assert _apply(staging).returncode == 0
    cible = op.droits_effectifs(env)
    secret = op.lire_secret(staging["secret"])
    canonique = _run(
        "provision_ingestion_control_roles.sh", env,
        INGESTION_CONTROL_MIGRATOR_PASSWORD=MIGRATOR_PASSWORD,
        INGESTION_CONTROL_APP_PASSWORD=APP_PASSWORD,
        INGESTION_CONTROL_AUTHORITY_PASSWORD=AUTHORITY_PASSWORD,
        INGESTION_CONTROL_ATTESTOR_PASSWORD=ATTESTOR_PASSWORD,
        INGESTION_CONTROL_ADOPTER_PASSWORD=secret or "",
    )
    assert canonique.returncode == 0, canonique.stderr
    assert op.droits_effectifs(env) == cible


def test_verificateur_scram_accepte_par_postgresql(staging: dict[str, Any]) -> None:
    """Le vérificateur calculé côté hôte authentifie réellement le secret."""
    assert _apply(staging).returncode == 0
    assert op.connexion_adopter(staging["env"], op.lire_secret(staging["secret"]) or "")
    assert not op.connexion_adopter(staging["env"], op.secrets.token_urlsafe(48))


if shutil.which("psql") is None:  # pragma: no cover
    pytest.skip("psql client requis", allow_module_level=True)
