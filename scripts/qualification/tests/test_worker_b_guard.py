"""Garde « aucun Worker B actif » : hermétique, ni Docker, ni SSH, ni orchestrateur."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GARDE = ROOT / "scripts/go_live/worker_b_guard.py"
SCRIPT = ROOT / "scripts/go_live/staging_hggsp_complementary.sh"
SPEC = importlib.util.spec_from_file_location("worker_b_guard", GARDE)
assert SPEC and SPEC.loader
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)

RUNTIME = "ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:" + "8" * 64
MODULE = ["-m", "ingestor.ingestion_worker.multilevel_publication_resume_cli", "--owner", "x"]


def conteneur(nom: str, image: str, entrypoint: list[str] | None, cmd: list[str] | None) -> dict:
    return {"Name": f"/{nom}", "Config": {"Image": image, "Entrypoint": entrypoint, "Cmd": cmd}}


# Les trois services réellement actifs sur le serveur de staging le jour du refus.
SANS_RAPPORT = [
    conteneur("rag_worker", "6c7417689bc5", None, ["celery", "-A", "tasks", "worker"]),
    conteneur("math-correction-worker-1", "134edf61c3f9", None, ["celery", "-A", "app.worker", "worker"]),
    conteneur("nexus-npc-worker-prod", "nexus-npc-worker:a533d452d", ["docker-entrypoint.sh"], ["node", "dist/worker.js"]),
]
WORKERS_B = [
    conteneur("nexus-v4-worker-b", RUNTIME, ["python"], MODULE),
    conteneur("nexus-v4-worker-b-dh", RUNTIME, ["python"], MODULE),
    conteneur("nexus-v4-worker-b-di-1", RUNTIME, ["python"], MODULE),
    conteneur("nexus-hggsp-successor-worker-b", RUNTIME, ["python"], MODULE),
    conteneur("nexus-hggsp-successor-worker-b-2", RUNTIME, ["python"], MODULE),
]


def evaluer(conteneurs: object) -> tuple[int, list[str]]:
    return guard.evaluer(json.dumps(conteneurs))


@pytest.mark.parametrize("service", SANS_RAPPORT, ids=lambda c: c["Name"])
def test_services_sans_rapport_ne_bloquent_pas(service: dict) -> None:
    assert evaluer([service]) == (0, [])


def test_les_trois_services_actifs_ensemble_ne_bloquent_pas() -> None:
    assert evaluer(SANS_RAPPORT) == (0, [])


@pytest.mark.parametrize("worker", WORKERS_B, ids=lambda c: c["Name"])
def test_worker_b_bloque(worker: dict) -> None:
    code, lignes = evaluer([worker])
    assert code == 4 and lignes and lignes[0].startswith("WORKER_ACTIF")
    assert worker["Name"].lstrip("/") in lignes[0]


def test_worker_b_bloque_parmi_des_services_sans_rapport() -> None:
    code, lignes = evaluer([*SANS_RAPPORT, WORKERS_B[0]])
    assert code == 4
    assert "rag_worker" not in lignes[0] and "nexus-v4-worker-b" in lignes[0]


def test_worker_b_renomme_est_identifie_par_son_image() -> None:
    renomme = conteneur("batch-publisher", RUNTIME, None, None)
    code, lignes = evaluer([renomme])
    assert code == 4 and "image du runtime de publication" in lignes[0]


def test_worker_b_renomme_et_reimage_est_identifie_par_son_module() -> None:
    renomme = conteneur("batch-publisher", "5f2d9c1e0a3b", ["python"], MODULE)
    code, lignes = evaluer([renomme])
    assert code == 4 and "module de publication lancé" in lignes[0]


def test_digest_ancien_du_runtime_bloque_aussi() -> None:
    ancien = conteneur("job", "ghcr.io/cyranoaladin/rag-multilevel-worker-production:v4", None, None)
    assert evaluer([ancien])[0] == 4


def test_un_nom_en_worker_b_chez_un_autre_projet_ne_bloque_pas() -> None:
    assert evaluer([conteneur("math-worker-b", "someimage:1", None, ["celery"])]) == (0, [])


@pytest.mark.parametrize(
    "brut",
    ["", "pas du json", "{}", "[]", "null", '"worker"', "[1]", '[{"Name": "/x"}]',
     '[{"Config": {"Image": "i"}}]', '[{"Name": "/x", "Config": {"Image": 3}}]',
     '[{"Name": "/x", "Config": {}}]'],
)
def test_inspection_ambigue_est_refusee(brut: str) -> None:
    code, lignes = guard.evaluer(brut)
    assert code == 5 and lignes[0].startswith("INSPECTION_AMBIGUE")


def test_un_conteneur_ambigu_ne_masque_pas_un_worker_b() -> None:
    code, lignes = evaluer([{"Name": "/x"}, WORKERS_B[0]])
    assert code == 4 and "WORKER_ACTIF" in lignes[0]


def test_un_conteneur_ambigu_parmi_des_services_sans_rapport_est_refuse() -> None:
    assert evaluer([*SANS_RAPPORT, {"Name": "/x"}])[0] == 5


def run(entree: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(GARDE)], input=entree, capture_output=True, text=True, check=False)


def test_cli_codes_de_sortie() -> None:
    assert run(json.dumps(SANS_RAPPORT)).returncode == 0
    refuse = run(json.dumps([WORKERS_B[0]]))
    assert refuse.returncode == 4 and "WORKER_ACTIF" in refuse.stderr
    assert run("").returncode == 5


def test_orchestrateur_n_utilise_plus_le_filtre_par_nom_et_garde_avant_la_sauvegarde() -> None:
    etape = SCRIPT.read_text(encoding="utf-8").split(
        "etape_successor_control_schema_020_and_adopter_role() {", 1)[1].split("\nexiger_revue_scopes", 1)[0]
    assert "name=worker" not in etape
    assert "docker inspect \\$ids | python3 $REMOTE/repo/scripts/go_live/worker_b_guard.py" in etape
    # refus par défaut : l'échec de `docker ps` comme celui de `docker inspect` arrêtent l'étape
    assert 'ids=\\$(docker ps -q) || { echo "INSPECTION_DOCKER_IMPOSSIBLE' in etape
    assert "set -euo pipefail" in etape
    assert etape.index("worker_b_guard.py") < etape.index("pg_dump") < etape.index("python3 $CONTROL020")
