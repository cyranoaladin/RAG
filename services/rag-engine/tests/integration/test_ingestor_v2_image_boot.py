"""L'image v2 réellement construite porte tout ce que son runtime importe.

Une ``allowlist`` de ``COPY`` tenue à la main ne se trompe jamais pendant le
développement : le module manquant s'importe depuis le checkout hôte, et
l'``ImportError`` n'apparaît qu'une fois l'image construite — c'est-à-dire au
démarrage en production. Une épreuve statique sur le Dockerfile ne le voit pas
non plus : elle lit le même texte que celui qu'on vient d'écrire.

Ces bancs construisent donc **l'image réelle**, depuis la racine du dépôt, et
la font démarrer. Aucun montage du checkout hôte : ce qui n'est pas dans
l'image n'existe pas.

Ils prouvent aussi la porte du registre de clients d'API sur l'image, là où
elle s'exercera : aucune source configurée, ou deux, doivent refuser le
démarrage ; exactement une doit passer cette porte.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ENGINE_ROOT.parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pg_authority import requires_docker  # noqa: E402

pytestmark = [pytest.mark.integration, requires_docker]

IMAGE_TAG = f"nexus-ingestor-v2-boot:{uuid.uuid4().hex[:10]}"

#: Un registre valide : une seule entrée, une empreinte, aucune valeur en clair.
_API_KEY = "cle-de-banc-du-registre-de-clients-0123456789"
_REGISTRY = json.dumps(
    [
        {
            "client_id": "banc-image",
            "token_sha256": hashlib.sha256(_API_KEY.encode("utf-8")).hexdigest(),
            "scopes": ["rag:search"],
        }
    ]
)


def _docker(*args: str, check: bool = True, timeout: int = 1800):
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=check, timeout=timeout
    )


@pytest.fixture(scope="module")
def image() -> Iterator[str]:
    _docker(
        "build",
        "-f",
        str(ENGINE_ROOT / "infra" / "Dockerfile.ingestor-v2"),
        "-t",
        IMAGE_TAG,
        str(REPOSITORY_ROOT),
    )
    try:
        yield IMAGE_TAG
    finally:
        _docker("image", "rm", "-f", IMAGE_TAG, check=False)


def test_l_application_v2_s_importe_dans_l_image_reelle(image: str) -> None:
    """La fermeture transitive des imports est dans l'image, ou elle n'y est pas.

    `import api_v2` charge tout le graphe du runtime servi : routes, portées
    d'API, métadonnées de retrieval, observabilité. Un module absent de
    l'``allowlist`` échoue ici, sans aucun montage hôte pour le sauver.
    """
    result = _docker(
        "run",
        "--rm",
        "--entrypoint",
        "python",
        image,
        "-c",
        "import api_v2; print('IMPORT_OK', flush=True)",
        check=False,
        timeout=300,
    )
    assert result.returncode == 0, (
        "le runtime v2 ne s'importe pas dans l'image réelle :\n"
        f"{result.stdout[-4000:]}\n{result.stderr[-4000:]}"
    )
    assert "IMPORT_OK" in result.stdout


def test_les_modules_de_ce_lot_sont_dans_l_image_et_non_sur_l_hote(image: str) -> None:
    """Nommément : les trois modules que la revue a vus manquer."""
    for module in ("api_scopes", "retrieval_metadata_v2", "retrieval_observability"):
        result = _docker(
            "run",
            "--rm",
            "--entrypoint",
            "python",
            image,
            "-c",
            f"import {module}, pathlib; "
            f"print(pathlib.Path({module}.__file__).parent, flush=True)",
            check=False,
            timeout=300,
        )
        assert result.returncode == 0, (module, result.stderr[-2000:])
        assert result.stdout.strip() == "/app", (module, result.stdout)


def _boot(image: str, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Démarrer uvicorn dans l'image et rendre ce que le démarrage a produit."""
    arguments = ["run", "--rm", "--network", "none"]
    for name, value in environment.items():
        arguments += ["-e", f"{name}={value}"]
    arguments += [image, "uvicorn", "api_v2:app", "--host", "127.0.0.1", "--port", "8001"]
    return _docker(*arguments, check=False, timeout=300)


_MINIMAL_ENVIRONMENT = {
    "RAG_ENV": "production",
    "RAG_BFF_SERVICE_TOKEN": "jeton-de-service-bff-de-banc-0123456789",
}


def test_aucun_registre_de_clients_refuse_le_demarrage(image: str) -> None:
    """Zéro autorité configurée : le service ne prend pas de trafic."""
    result = _boot(image, _MINIMAL_ENVIRONMENT)
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "no API client registry configured" in combined, combined[-4000:]
    assert "ModuleNotFoundError" not in combined
    assert "ImportError" not in combined


def test_deux_registres_de_clients_refusent_le_demarrage(image: str) -> None:
    """Deux autorités : laquelle gouverne ? Aucune — on refuse."""
    result = _boot(
        image,
        {
            **_MINIMAL_ENVIRONMENT,
            "RAG_API_CLIENTS": _REGISTRY,
            "RAG_API_CLIENTS_FILE": "/app/api-clients/api-clients.json",
        },
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "both API client sources are configured" in combined, combined[-4000:]


def test_exactement_un_registre_passe_la_porte_des_clients(image: str) -> None:
    """Contrôle positif : sans lui, un refus systématique passerait les deux autres.

    Le démarrage échoue plus loin — aucune base, aucun artefact de modèle
    dans ce banc — mais **plus jamais** sur le registre de clients. C'est
    exactement ce que cette porte doit prouver.
    """
    result = _boot(image, {**_MINIMAL_ENVIRONMENT, "RAG_API_CLIENTS": _REGISTRY})
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "API client registry" not in combined, combined[-4000:]
    assert "both API client sources are configured" not in combined
    assert "ModuleNotFoundError" not in combined
    assert "ImportError" not in combined
