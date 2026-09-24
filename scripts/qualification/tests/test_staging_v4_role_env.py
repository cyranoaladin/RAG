"""DC — un fichier d'environnement par rôle, dérivé des secrets EXISTANTS.

Aucun nouveau secret, aucune valeur sur la sortie, écriture atomique en 0600
dans un répertoire 0700, jamais d'écrasement d'un contenu différent, et le
fichier global (``staging.env``, ``ingestion_control.env``) ne devient jamais
celui d'un worker.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[3]
SCRIPT = RACINE / "scripts/go_live/staging_v4_role_env.py"
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import staging_v4_role_env as role_env  # noqa: E402

BASE = "ragdb_profile_gate_v4"
SECRETS = {
    "INGESTION_CONTROL_APP_PASSWORD": "app-secret-AAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "INGESTION_CONTROL_ATTESTOR_PASSWORD": "attestor-secret-BBBBBBBBBBBBBBBBBBBBBBBB",
    "INGESTION_CONTROL_AUTHORITY_PASSWORD": "authority-secret-CCCCCCCCCCCCCCCCCCCCCC",
    "PGVECTOR_PUBLISHER_PASSWORD": "pub'li\\sher-DDDDDDDDDDDDDDDDDDDDDDDDDDD",
    "PGVECTOR_RETRIEVAL_PASSWORD": "reader-secret-EEEEEEEEEEEEEEEEEEEEEEEEEE",
}
#: présents dans les fichiers globaux, et qui ne doivent JAMAIS passer dans un fichier de rôle
AUTRES = {
    "PGVECTOR_PASSWORD": "superuser-secret-FFFFFFFFFFFFFFFFFFFFFFFF",
    "INGESTION_CONTROL_MIGRATOR_PASSWORD": "migrator-secret-GGGGGGGGGGGGGGGGGGGGG",
    "NEXUS_INTERNAL_TOKEN_SECRET": "token-secret-HHHHHHHHHHHHHHHHHHHHHHHHHHHHH",
}


def _environ(**surcharges: str) -> dict[str, str]:
    return {"PGVECTOR_PORT": "15435", **SECRETS, **AUTRES, **surcharges}


def _lancer(dossier: Path, environ: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"], **environ}
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--database", BASE, "--out-dir", str(dossier)],
        env=env, capture_output=True, text=True, check=False,
    )


def test_cinq_fichiers_un_par_role_sur_la_base_v4(tmp_path):
    dossier = tmp_path / "v4-roles"
    sortie = _lancer(dossier, _environ())
    assert sortie.returncode == 0, sortie.stderr
    assert sorted(p.name for p in dossier.iterdir()) == sorted(role_env.FICHIERS)
    for nom, (variable, role, source) in role_env.FICHIERS.items():
        texte = (dossier / nom).read_text()
        assert texte.startswith(f"{variable}=host=127.0.0.1 port=15435 dbname={BASE} user={role} password=")
        assert texte.count("\n") == 1
        assert texte.endswith(f"password={role_env._valeur_libpq(SECRETS[source])}\n")


def test_aucun_secret_sur_la_sortie_ni_dans_les_arguments(tmp_path):
    sortie = _lancer(tmp_path / "v4-roles", _environ())
    for secret in (*SECRETS.values(), *AUTRES.values()):
        assert secret not in sortie.stdout and secret not in sortie.stderr
    assert "ROLE_ENV_DONE count=5 dir_mode=0700" in sortie.stdout


def test_permissions_0600_dans_un_repertoire_0700(tmp_path):
    dossier = tmp_path / "v4-roles"
    assert _lancer(dossier, _environ()).returncode == 0
    assert stat.S_IMODE(dossier.stat().st_mode) == 0o700
    for fichier in dossier.iterdir():
        assert stat.S_IMODE(fichier.stat().st_mode) == 0o600, fichier.name
    assert not [p for p in dossier.iterdir() if p.name.startswith(".")], "fichier temporaire laissé"


def test_les_secrets_globaux_ne_passent_dans_aucun_fichier_de_role(tmp_path):
    dossier = tmp_path / "v4-roles"
    assert _lancer(dossier, _environ()).returncode == 0
    tout = "".join(p.read_text() for p in dossier.iterdir())
    for secret in AUTRES.values():
        assert secret not in tout
    assert "raguser" not in tout and "ingestion_control_migrator" not in tout


def test_chaque_fichier_ne_porte_que_le_mot_de_passe_de_son_role(tmp_path):
    dossier = tmp_path / "v4-roles"
    assert _lancer(dossier, _environ()).returncode == 0
    for nom, (_variable, _role, source) in role_env.FICHIERS.items():
        texte = (dossier / nom).read_text()
        for autre, secret in SECRETS.items():
            if autre != source and "'" not in secret and "\\" not in secret:
                assert secret not in texte, (nom, autre)


def test_le_mot_de_passe_est_echappe_pour_libpq():
    contenu = role_env.contenus(_environ(), database=BASE)["rag-publisher.env"]
    assert contenu.endswith("password='pub\\'li\\\\sher-DDDDDDDDDDDDDDDDDDDDDDDDDDD'\n")


def test_rejouer_a_l_identique_ne_change_rien(tmp_path):
    dossier = tmp_path / "v4-roles"
    assert _lancer(dossier, _environ()).returncode == 0
    avant = {p.name: p.read_text() for p in dossier.iterdir()}
    rejeu = _lancer(dossier, _environ())
    assert rejeu.returncode == 0
    assert rejeu.stdout.count(" UNCHANGED ") == 5
    assert {p.name: p.read_text() for p in dossier.iterdir()} == avant


def test_un_contenu_different_n_est_jamais_ecrase(tmp_path):
    dossier = tmp_path / "v4-roles"
    assert _lancer(dossier, _environ()).returncode == 0
    avant = {p.name: p.read_text() for p in dossier.iterdir()}
    refus = _lancer(dossier, _environ(INGESTION_CONTROL_APP_PASSWORD="autre-valeur-ZZZZZZZZZZZZZZZZZZZZZZZZZ"))
    assert refus.returncode == 2
    assert "rien n'est écrasé" in refus.stderr
    assert {p.name: p.read_text() for p in dossier.iterdir()} == avant


@pytest.mark.parametrize("absente", sorted(SECRETS) + ["PGVECTOR_PORT"])
def test_une_source_absente_refuse_sans_rien_ecrire(tmp_path, absente):
    dossier = tmp_path / "v4-roles"
    environ = _environ()
    environ.pop(absente)
    sortie = _lancer(dossier, environ)
    assert sortie.returncode == 2
    assert absente in sortie.stderr
    assert not dossier.exists() or not list(dossier.iterdir())


@pytest.mark.parametrize("base", ["ragdb", "RagDB", "ragdb;drop", ""])
def test_la_base_historique_ou_un_nom_invalide_est_refuse(base):
    with pytest.raises(role_env.DerivationRefusee):
        role_env.contenus(_environ(), database=base)


def test_un_repertoire_trop_ouvert_est_refuse(tmp_path):
    dossier = tmp_path / "v4-roles"
    dossier.mkdir(mode=0o755)
    os.chmod(dossier, 0o755)
    sortie = _lancer(dossier, _environ())
    assert sortie.returncode == 2 and "0700" in sortie.stderr
    assert not list(dossier.iterdir())


def test_aucun_fichier_de_role_ne_porte_le_nom_d_un_fichier_global():
    assert not {"staging.env", "ingestion_control.env", "credentials.env"} & set(role_env.FICHIERS)
