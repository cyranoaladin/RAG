"""DC — l'orchestrateur V4 sur la base dédiée, sans serveur.

Essai à blanc hors ligne jusqu'au premier verrou humain, puis fonctions de
l'orchestrateur sourcées une à une : décision du pré-vol, intangibilité de
``ragdb``, fichiers d'environnement par rôle, expurgation du journal.
Aucune garde n'est desserrée pour que ces épreuves passent.
"""

from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[3]
SCRIPT = RACINE / "scripts/go_live/staging_v4_publication.sh"
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import check_staging_authorization as autorisation  # noqa: E402

BASE = "ragdb_profile_gate_v4"
ROLES = "/srv/nexus-staging/secrets/v4-roles"
MESURES_SAINES = """\
PSQL_ON_HOST=yes
PYTHON3_ON_HOST=yes
SUPERUSER=raguser
SOURCE_FILE /srv/nexus-staging/secrets/staging.env 600
SOURCE_FILE /srv/nexus-staging/secrets/ingestion_control.env 600
SOURCE_FILE /srv/nexus-staging/secrets/readiness.env 600
INFRA_DOTENV absent
LEGACY_PRODUCT_HEAD=4
LEGACY_CONTROL_HEAD=15
LEGACY_RESOURCES=479:3d907891df6158bbba28d0691a3d5e26
LEGACY_ARTIFACTS=479:3fb22f3bdb00a6b9e1c01016326460db
LEGACY_PLACEMENTS=26:92d3ff26b1536fc1e1eee9cff02e8863
LEGACY_CHUNKS=730:6db378881a1b6def6d8a000a7bc10d3d
LEGACY_SCOPE_AUTHORIZATIONS=22
TARGET_EXISTS=0
""" + "".join(
    f"ROLE_AUTH {r} OK\n" for r in (
        "raguser", "ingestion_control_migrator", "ingestion_control_app", "ingestion_control_attestor",
        "ingestion_control_authority", "rag_publisher", "rag_reader", "rag_reviewer",
    )
)


def _bash(script: str, etat: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Source l'orchestrateur (mode bibliothèque) puis exécute ``script``."""
    corps = f'source "{SCRIPT}" {" ".join(args)}\n{script}\n'
    return subprocess.run(
        ["bash", "-c", corps], capture_output=True, text=True, check=False,
        env={"PATH": os.environ["PATH"], "HOME": str(etat), "STATE_DIR": str(etat), **(env or {})},
    )


# ── essai à blanc complet, jusqu'au premier verrou humain ──────────────────

@pytest.fixture(scope="module")
def essai(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    racine = tmp_path_factory.mktemp("essai")
    etat, pret = racine / "etat", racine / "readiness"
    etat.mkdir(mode=0o700)
    pret.mkdir()
    (pret / "staging-readiness-v4.json").write_text("{}")
    # Le modèle E5 (1,3 Go) n'est pas sur la machine de CI : son étape est
    # marquée faite ; ses contrôles d'intégrité sont exercés sur le serveur.
    (etat / "model_artifact_install.done").write_text("hors essai\n")
    sortie = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run", "run"], capture_output=True, text=True, check=False,
        env={
            "PATH": os.environ["PATH"], "HOME": str(racine), "STATE_DIR": str(etat),
            "PYTHON": sys.executable, "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
            "READINESS_LOCAL": str(pret), "DRY_RUN_OFFLINE": "1",
            "BATCH_REVIEW_ID": "revue-essai", "EVALUATOR": "essai",
        },
    )
    return {"sortie": sortie, "texte": sortie.stdout + sortie.stderr, "etat": etat}


def test_l_essai_va_jusqu_a_la_revue_batch_et_s_y_arrete(essai):
    sortie, etat = essai["sortie"], essai["etat"]
    assert sortie.returncode == 0, essai["texte"][-2000:]
    faites = sorted(p.stem for p in etat.glob("*.done"))
    ordre = list(autorisation.ORDRE_V4)
    attendues = ordre[: ordre.index("batch_review_proposal") + 1]
    assert faites == sorted(attendues)
    assert "ATTENTE_HUMAINE" in essai["texte"]
    assert "ARRET" not in essai["texte"]


def test_la_base_dediee_est_creee_additivement_par_createdb(essai):
    texte = essai["texte"]
    assert f"createdb -U \"$POSTGRES_USER\" -T template0 -E UTF8 --locale=C {BASE}" in texte
    assert "BASE_DEJA_PRESENTE" in texte
    assert "dropdb" not in texte and "drop database" not in texte.lower()


def test_les_migrations_visent_la_base_dediee_par_les_runners_canoniques(essai):
    texte = essai["texte"]
    assert f"PGVECTOR_DB={BASE}" in texte and "./scripts/apply_pgvector_migrations.sh" in texte
    assert f"PGDATABASE={BASE}" in texte and "./scripts/provision_and_bootstrap_ingestion_control.sh" in texte
    assert "TETE_PRODUIT_INATTENDUE" in texte and "TETE_CONTROLE_INATTENDUE" in texte
    assert "PGVECTOR_RETRIEVAL_USER=rag_reader PGVECTOR_REVIEW_USER=rag_reviewer PGVECTOR_PUBLISHER_USER=rag_publisher" in texte


def test_ragdb_n_est_jamais_touchee_qu_en_lecture(essai):
    for ligne in essai["texte"].splitlines():
        if re.search(r"(-d\\? |dbname=)ragdb(?!_)", ligne):
            assert "default_transaction_read_only=on" in ligne or "pg_dump" in ligne, ligne


def test_ragdb_est_reverifiee_apres_chaque_etape_qui_ecrit(essai):
    texte = essai["texte"]
    for etape in ("database_creation", "product_migrations", "control_migrations",
                  "role_env_derivation", "scope_authorization_registration_r4",
                  "sealed_ingestion_v4", "batch_review_proposal"):
        bloc = texte.split(f"FAIT {etape}")[0].rsplit("non appelé", 1)[-1]
        assert "LEGACY_PLACEMENTS=" in bloc, etape


def test_les_conteneurs_ne_recoivent_que_des_fichiers_par_role(essai):
    fichiers = re.findall(r'--env-file "([^"]+)"', essai["texte"])
    assert fichiers
    for fichier in fichiers:
        assert fichier == "/srv/nexus-staging/secrets/readiness.env" or fichier.startswith(f"{ROLES}/"), fichier
        assert not fichier.endswith(("staging.env", "ingestion_control.env", "credentials.env"))


def test_l_ingestion_initiale_exige_une_base_dediee_vierge(essai):
    texte = essai["texte"]
    bloc = texte.split("sealed_release_ingestion_cli")[0].rsplit("FAIT scope_authorization_registration_r4", 1)[-1]
    assert "from ingestion_control.resources" in bloc.replace("\\ ", " ")
    assert f"-d\\ {BASE}" in bloc


def test_le_jeton_github_est_exige_sans_etre_lu(essai):
    texte = essai["texte"]
    assert "JETON_GITHUB_ABSENT" in texte and "JETON_GITHUB_MODE" in texte and "JETON_GITHUB_DIR_MODE" in texte
    assert "cat /srv/nexus-staging/secrets/github-read-token/token" not in texte


def test_aucune_valeur_de_secret_dans_le_journal(essai):
    texte = essai["texte"]
    assert "PGPASSWORD=***" in texte
    assert not re.search(r"password='[^*]", texte)


def test_la_derivation_embarque_le_script_verifie_et_controle_chaque_role(essai):
    texte = essai["texte"]
    assert f"python3 - --database {BASE} --out-dir {ROLES}" in texte
    for role in ("ingestion_control_app", "ingestion_control_attestor", "ingestion_control_authority",
                 "rag_publisher", "rag_reader"):
        assert f"= \"{role}|{BASE}\"" in texte, role


# ── fonctions, une à une ──────────────────────────────────────────────────

def test_l_ordre_du_script_est_celui_de_l_autorisation(tmp_path):
    sortie = _bash('printf "%s\\n" "${ORDRE[@]}"', tmp_path)
    assert sortie.stdout.split() == list(autorisation.ORDRE_V4)


def test_hors_ligne_n_a_aucun_effet_sans_dry_run(tmp_path):
    assert _bash('echo "$HORS_LIGNE"', tmp_path, env={"DRY_RUN_OFFLINE": "1"}).stdout.strip() == "0"
    assert _bash('echo "$HORS_LIGNE"', tmp_path, "--dry-run", env={"DRY_RUN_OFFLINE": "1"}).stdout.strip() == "1"


@pytest.mark.parametrize("fichier", [
    "/srv/nexus-staging/secrets/staging.env",
    "/srv/nexus-staging/secrets/ingestion_control.env",
    "/srv/nexus-staging/secrets/credentials.env",
    f"{ROLES}/../staging.env.bak",
])
def test_un_fichier_global_est_refuse_a_un_conteneur(tmp_path, fichier):
    sortie = _bash(f'env_de_role "{ROLES}/rag-reader.env" "{fichier}"', tmp_path)
    assert sortie.returncode == 3 and "hors des fichiers par rôle" in sortie.stderr


def test_un_fichier_par_role_est_accepte(tmp_path):
    assert _bash(f'env_de_role "{ROLES}/rag-reader.env" "{ROLES}/ingestion-control-app.env"', tmp_path).returncode == 0


def test_l_expurgation_masque_les_mots_de_passe_libpq(tmp_path):
    # Valeurs fictives tirées à l'exécution : aucune n'est écrite dans le dépôt.
    marque = "VALEUR" + secrets.token_hex(8)
    cle = "pass" + "word"
    ligne = (
        f"PG_RAG_DSN=host=127.0.0.1 port=15435 dbname=x user=rag_reader {cle}='a\\'b-{marque}' "
        f"et {cle}=c{marque} et PG{cle.upper()}=d{marque} postgresql://u:e{marque}@h/db"
    )
    redige = subprocess.run(
        ["bash", "-c", f'source "{SCRIPT}"; redact'], input=ligne + "\n", capture_output=True, text=True,
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), "STATE_DIR": str(tmp_path)},
    ).stdout
    assert marque not in redige, redige


def _decider(tmp_path: Path, mesures: str) -> subprocess.CompletedProcess[str]:
    fichier = tmp_path / "mesures.txt"
    fichier.write_text(mesures)
    return _bash(f'decision_prevol "$(cat "{fichier}")"; cat "$STATE_DIR/cible"', tmp_path)


def test_le_pre_vol_accepte_une_base_dediee_absente(tmp_path):
    sortie = _decider(tmp_path, MESURES_SAINES)
    assert sortie.returncode == 0, sortie.stderr
    assert sortie.stdout.strip() == "absente"
    assert (tmp_path / "legacy_baseline.txt").read_text().count("LEGACY_") == 7


def test_le_pre_vol_accepte_une_base_dediee_vierge(tmp_path):
    sortie = _decider(tmp_path, MESURES_SAINES.replace("TARGET_EXISTS=0", "TARGET_EXISTS=1\nTARGET_ROWS=0"))
    assert sortie.returncode == 0 and sortie.stdout.strip() == "vierge"


@pytest.mark.parametrize(
    ("remplacer", "par", "motif"),
    [
        ("TARGET_EXISTS=0", "TARGET_EXISTS=1\nTARGET_ROWS=12", "contenu inattendu"),
        ("TARGET_EXISTS=0", "TARGET_EXISTS=1", "contenu inattendu"),
        ("TARGET_EXISTS=0", "TARGET_EXISTS=", "illisible"),
        ("ROLE_AUTH rag_reader OK", "ROLE_AUTH rag_reader KO", "n'authentifie pas"),
        ("ROLE_AUTH rag_reviewer OK", "ROLE_AUTH rag_reviewer MISSING_SOURCE", "n'authentifie pas"),
        ("ROLE_AUTH raguser OK\n", "", "incomplètes"),
        ("INFRA_DOTENV absent", "INFRA_DOTENV overrides_target", "infra/.env"),
        ("SOURCE_FILE /srv/nexus-staging/secrets/staging.env 600",
         "SOURCE_FILE_MISSING /srv/nexus-staging/secrets/staging.env", "fichier source absent"),
        ("PSQL_ON_HOST=yes", "PSQL_ON_HOST=no", "psql absent"),
        ("PYTHON3_ON_HOST=yes", "PYTHON3_ON_HOST=no", "python3 absent"),
        ("LEGACY_CHUNKS=730:6db378881a1b6def6d8a000a7bc10d3d\n", "", "incomplète"),
    ],
)
def test_le_pre_vol_refuse(tmp_path, remplacer, par, motif):
    assert remplacer in MESURES_SAINES
    sortie = _decider(tmp_path, MESURES_SAINES.replace(remplacer, par))
    assert sortie.returncode == 3, sortie.stdout
    assert motif in sortie.stderr, sortie.stderr


def _historique(tmp_path: Path, apres: str) -> subprocess.CompletedProcess[str]:
    base = "".join(e + "\n" for e in MESURES_SAINES.splitlines() if e.startswith("LEGACY_"))
    (tmp_path / "legacy_baseline.txt").write_text(base)
    (tmp_path / "apres.txt").write_text(apres)
    # ``remote`` remplacé : il rend la mesure « après » au lieu d'appeler l'hôte.
    return _bash(f'remote() {{ cat >/dev/null; cat "{tmp_path}/apres.txt"; }}; verifier_historique', tmp_path)


def test_ragdb_inchangee_passe(tmp_path):
    base = "".join(e + "\n" for e in MESURES_SAINES.splitlines() if e.startswith("LEGACY_"))
    sortie = _historique(tmp_path, base)
    assert sortie.returncode == 0 and "RAGDB_INCHANGEE" in sortie.stderr


@pytest.mark.parametrize("ligne", [
    "LEGACY_PLACEMENTS=25:92d3ff26b1536fc1e1eee9cff02e8863",
    "LEGACY_RESOURCES=479:00000000000000000000000000000000",
    "LEGACY_PRODUCT_HEAD=5",
])
def test_la_moindre_variation_de_ragdb_arrete(tmp_path, ligne):
    cle = ligne.split("=")[0]
    base = [e for e in MESURES_SAINES.splitlines() if e.startswith("LEGACY_")]
    apres = "".join((ligne if e.startswith(cle + "=") else e) + "\n" for e in base)
    sortie = _historique(tmp_path, apres)
    assert sortie.returncode == 3 and "ragdb a changé" in sortie.stderr


# ── DD : les contrôles d'une base NEUVE ne nomment aucune table absente ─────

@pytest.mark.parametrize("appel", ["vide_cible", "tete_si_presente public", "tete_si_presente ingestion_control"])
def test_les_controles_de_base_neuve_ne_nomment_aucune_relation(tmp_path, appel):
    """PostgreSQL résout les noms à l'analyse, même dans une branche de CASE
    jamais exécutée : une base neuve n'a aucune table, et un contrôle qui en
    nomme une échoue (constaté le 2026-09-24 sur ragdb_profile_gate_v4). Les
    tables présentes doivent être trouvées dans pg_class, puis comptées par
    query_to_xml."""
    sql = _bash(appel, tmp_path).stdout
    assert "pg_class" in sql and "query_to_xml" in sql, sql
    assert "to_regclass" not in sql
    assert not re.search(r"\bfrom\s+(public|ingestion_control)\.", sql, re.IGNORECASE), sql


def test_les_tetes_avant_migration_passent_par_la_sonde_sans_relation(essai):
    texte = essai["texte"].replace("\\ ", " ")
    for garde in ("TETE_PRODUIT_INATTENDUE", "TETE_CONTROLE_INATTENDUE"):
        bloc = texte.split(garde)[0].rsplit("[dry-run]", 1)[-1]
        assert "query_to_xml" in bloc and "to_regclass" not in bloc, garde
