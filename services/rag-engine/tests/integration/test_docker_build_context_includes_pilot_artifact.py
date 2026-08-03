"""LOT43 (suite) : le contexte de build Docker doit inclure l'artefact
pilote requis par ``identity_v2.load_identity_verifier_config``.

Bug réel trouvé lors de la validation Compose fraîche isolée : le
``.dockerignore`` racine dénie ``**/artifacts`` / ``**/artifacts/**`` pour
exclure les répertoires de build (dist/, artefacts CI, etc.), mais ce motif
générique masque aussi ``packages/contracts/src/nexus_contracts/artifacts/``
qui contient ``pilot-retrieval-scope-v1.json`` — une ressource *requise* au
runtime par ``identity_v2.py``, pas un artefact de build. Toute image Docker
construite depuis ce contexte plante donc en 500 sur toute route utilisant
``require_internal_identity`` (``/review/v2/*``, ``/search/v2``,
``/collections/v2``, ``/collections/readiness``) dès qu'un client envoie une
identité signée valide — confirmé en conditions réelles (conteneur jetable,
volume Postgres vierge, modèle d'embedding réel, jeton HS256 réellement
signé).

Ce test utilise Docker lui-même (le moteur réel d'évaluation des motifs
``.dockerignore``, pas une réimplémentation) sur un Dockerfile jetable minimal
qui ne fait que copier ``packages/contracts`` et vérifier la présence du
fichier — rapide (pas de pip install), fidèle au comportement réel.
"""
from __future__ import annotations

import shutil
import subprocess
import textwrap
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

_DOCKER_AVAILABLE = shutil.which("docker") is not None and (
    subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DOCKER_AVAILABLE, reason="Docker not available"),
]


def test_build_context_includes_pilot_retrieval_scope_artifact(tmp_path: Path) -> None:
    dockerfile = tmp_path / "Dockerfile.contextcheck"
    dockerfile.write_text(
        textwrap.dedent(
            """\
            FROM busybox
            COPY packages/contracts /x/nexus-contracts
            RUN test -f /x/nexus-contracts/src/nexus_contracts/artifacts/pilot-retrieval-scope-v1.json
            """
        ),
        encoding="utf-8",
    )
    tag = f"lot43-dockerignore-context-check-{uuid.uuid4().hex[:10]}"
    try:
        result = subprocess.run(
            ["docker", "build", "-f", str(dockerfile), "-t", tag, "."],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            "The pilot retrieval scope artifact is missing from the Docker "
            "build context (.dockerignore excludes it) — every route using "
            "require_internal_identity will 500 in any image built from "
            f"this repo.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    finally:
        subprocess.run(["docker", "rmi", "-f", tag], capture_output=True, check=False)
