"""Le checkout de la sonde DI est épinglé avant toute vérification distante."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/go_live/staging_v4_partial_recovery.sh"
PROBE = Path("scripts/go_live/staging_retrieval_probe.py")


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.fixture
def depots(tmp_path: Path) -> tuple[Path, Path, Path, str, str]:
    origin = tmp_path / "origin.git"
    operator = tmp_path / "operator"
    server = tmp_path / "server" / "repo"
    server.parent.mkdir()
    subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(origin), str(operator)], check=True, capture_output=True)
    (operator / PROBE).parent.mkdir(parents=True)
    (operator / PROBE).write_text("ancienne sonde\n")
    _git(operator, "add", str(PROBE))
    _git(operator, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "sonde initiale")
    _git(operator, "push", "-u", "origin", "main")
    ancien = _git(operator, "rev-parse", "HEAD")
    subprocess.run(["git", "clone", str(origin), str(server)], check=True, capture_output=True)
    (operator / PROBE).write_text("sonde corrigée\n")
    _git(operator, "add", str(PROBE))
    _git(operator, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "corriger la sonde")
    _git(operator, "push", "origin", "main")
    nouveau = _git(operator, "rev-parse", "HEAD")
    return operator, server, tmp_path, ancien, nouveau


def _pinner(operator: Path, server: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "NEXUS_REPO_ROOT": str(operator),
        "STATE_DIR": str(tmp_path / "state"),
        "V4_STATE_DIR": str(tmp_path / "v4"),
        "READINESS_LOCAL": str(tmp_path / "readiness"),
    }
    return subprocess.run(
        ["bash", "-c", f'source "{SCRIPT}"\nREMOTE="{server.parent}"\nremote() {{ bash -s; }}\npinner_sonde_di\n'],
        cwd=operator, env=env, capture_output=True, text=True, check=False,
    )


def test_checkout_distant_prend_exactement_la_nouvelle_sonde(depots) -> None:
    operator, server, tmp_path, ancien, nouveau = depots
    assert _git(server, "rev-parse", "HEAD") == ancien
    resultat = _pinner(operator, server, tmp_path)
    assert resultat.returncode == 0, resultat.stdout + resultat.stderr
    assert _git(server, "rev-parse", "HEAD") == nouveau
    assert (server / PROBE).read_bytes() == (operator / PROBE).read_bytes()


def test_checkout_local_perime_est_refuse_avant_le_serveur(depots) -> None:
    operator, server, tmp_path, ancien, _nouveau = depots
    _git(operator, "checkout", "--detach", ancien)
    resultat = _pinner(operator, server, tmp_path)
    assert resultat.returncode != 0
    assert _git(server, "rev-parse", "HEAD") == ancien


def test_checkout_local_sale_est_refuse_avant_le_serveur(depots) -> None:
    operator, server, tmp_path, ancien, _nouveau = depots
    (operator / PROBE).write_text("sonde altérée localement\n")
    resultat = _pinner(operator, server, tmp_path)
    assert resultat.returncode != 0
    assert _git(server, "rev-parse", "HEAD") == ancien


def test_checkout_distant_sale_est_refuse_sans_ecrasement(depots) -> None:
    operator, server, tmp_path, ancien, _nouveau = depots
    (server / PROBE).write_text("modification sur hôte\n")
    resultat = _pinner(operator, server, tmp_path)
    assert resultat.returncode != 0
    assert _git(server, "rev-parse", "HEAD") == ancien
    assert (server / PROBE).read_text() == "modification sur hôte\n"


def test_checkout_change_apres_pin_est_refuse_avant_la_sonde(depots) -> None:
    operator, server, tmp_path, ancien, nouveau = depots
    env = {
        **os.environ,
        "NEXUS_REPO_ROOT": str(operator),
        "STATE_DIR": str(tmp_path / "state"),
        "V4_STATE_DIR": str(tmp_path / "v4"),
        "READINESS_LOCAL": str(tmp_path / "readiness"),
    }
    commande = f'''source "{SCRIPT}"
REMOTE="{server.parent}"
appels=0
remote() {{
    appels=$((appels + 1))
    if [ "$appels" -eq 2 ]; then git -C "$REMOTE/repo" checkout -q --detach "{ancien}"; fi
    bash -s
}}
autoriser_di() {{ :; }}
cible_di_champ() {{ printf '%s\\n' 'rag_nexus_hlp_premiere_specialite'; }}
env_de_role() {{ :; }}
psql_ro() {{ printf '%s\\n' 'echo SQL_WOULD_RUN'; }}
tirer() {{ printf '%s\\n' ':'; }}
verifier_historique() {{ :; }}
etape_partial_independent_verification
'''
    resultat = subprocess.run(
        ["bash", "-c", commande], cwd=operator, env=env,
        capture_output=True, text=True, check=False,
    )
    assert resultat.returncode != 0
    assert _git(server, "rev-parse", "HEAD") == ancien
    assert _git(operator, "rev-parse", "HEAD") == nouveau
    assert "SQL_WOULD_RUN" not in resultat.stdout
    assert "SONDE_RETRIEVAL_V4" not in resultat.stdout
