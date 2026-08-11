"""A1 — les suites de gouvernance ne peuvent pas être vertes sans Docker.

**Le défaut fermé ici.** ``requires_docker`` est un ``skipif`` : sans
Docker, les 120 tests de gouvernance PostgreSQL étaient tous sautés et
pytest sortait ``0``. Le check requis « governance postgres » pouvait donc
passer au vert en n'ayant exécuté aucune assertion — un « vert non
démontré » au sens de la règle « Qualité des métriques » d'AGENTS.md.

**Comment ces tests prouvent le fail-closed sans casser la machine.**
Aucun daemon n'est arrêté, aucun binaire n'est supprimé. Deux mécanismes
non destructifs suffisent :

* pour « Docker introuvable » : un sous-processus dont le ``PATH`` ne
  contient qu'un répertoire temporaire vide. L'interpréteur est invoqué
  par chemin absolu, donc lui-même reste joignable ; seule la recherche de
  ``docker`` par ``shutil.which`` échoue, exactement comme sur un runner
  sans Docker ;
* pour « daemon injoignable » : un faux ``docker`` en tête de ``PATH`` qui
  répond en erreur à ``docker info``, ce qui reproduit un daemon arrêté
  sans y toucher.

Chaque test vérifie non seulement le code de sortie, mais qu'une assertion
volontairement fausse **n'a pas été masquée par un skip** — sans quoi on
mesurerait le message d'erreur plutôt que la propriété.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_DIR = ENGINE_ROOT / "tests" / "integration"
PREFLIGHT = ENGINE_ROOT / "infra" / "scripts" / "require_docker.sh"

#: Résolu AVANT toute réduction de ``PATH`` : c'est ``docker`` qu'on veut
#: rendre introuvable, pas l'interpréteur du script.
BASH = shutil.which("bash") or "/bin/bash"

#: Suite de gouvernance réelle, utilisée comme cible : c'est le
#: comportement de CES fichiers qui doit être fail-closed, pas celui d'un
#: module inventé pour le test.
GOVERNANCE_SUITE = "tests/integration/test_lot42_v2_migration_013.py"

#: Fichier sonde : une assertion fausse, dans un module qui importe la
#: VRAIE garde du dépôt. S'il est seulement « skipped », le fail-open est
#: encore là.
_PROBE = '''
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
import _pg_authority  # noqa: E402
import pytest  # noqa: E402

pytestmark = [pytest.mark.integration, _pg_authority.requires_docker]


def test_a_governance_assertion_that_must_not_be_hidden():
    assert False, "cette assertion doit soit s'exécuter, soit faire échouer le run"
'''


def _run_pytest(
    args: list[str], *, path_dir: Path, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Lance pytest dans un sous-processus au ``PATH`` maîtrisé.

    ``sys.executable`` est absolu : l'interpréteur reste joignable même
    avec un ``PATH`` réduit, ce qui permet d'isoler la seule variable qui
    nous intéresse — la découverte de ``docker``."""
    env = dict(os.environ)
    env["PATH"] = str(path_dir)
    env.pop("NEXUS_REQUIRE_DOCKER", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", *args],
        cwd=ENGINE_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )


@pytest.fixture
def empty_path(tmp_path: Path) -> Path:
    """``PATH`` sans aucun ``docker`` — équivalent d'un runner dépourvu."""
    directory = tmp_path / "no-docker-bin"
    directory.mkdir()
    return directory


@pytest.fixture
def failing_docker_path(tmp_path: Path) -> Path:
    """``docker`` présent mais dont le daemon répond en erreur."""
    directory = tmp_path / "broken-docker-bin"
    directory.mkdir()
    shim = directory / "docker"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'echo "Cannot connect to the Docker daemon" >&2\n'
        "exit 1\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return directory


class TestPreflightScript:
    """Barrière 1 — partagée par la cible Make et le job CI."""

    def test_the_preflight_script_is_executable_and_shared(self) -> None:
        assert PREFLIGHT.is_file()
        makefile = (ENGINE_ROOT / "Makefile").read_text(encoding="utf-8")
        workflow = (
            ENGINE_ROOT.parents[1] / ".github" / "workflows" / "ci.yml"
        ).read_text(encoding="utf-8")
        assert "infra/scripts/require_docker.sh" in makefile
        assert "infra/scripts/require_docker.sh" in workflow

    def test_it_refuses_when_docker_is_absent(self, empty_path: Path) -> None:
        env = dict(os.environ, PATH=str(empty_path))
        result = subprocess.run(
            [BASH, str(PREFLIGHT)], env=env, capture_output=True, text=True,
            check=False, timeout=60,
        )
        assert result.returncode != 0
        assert "GOVERNANCE_DOCKER_PREFLIGHT_FAILED" in result.stderr
        assert "introuvable" in result.stderr

    def test_it_refuses_when_the_daemon_is_unreachable(
        self, failing_docker_path: Path
    ) -> None:
        env = dict(os.environ, PATH=f"{failing_docker_path}:{os.environ['PATH']}")
        result = subprocess.run(
            [BASH, str(PREFLIGHT)], env=env, capture_output=True, text=True,
            check=False, timeout=60,
        )
        assert result.returncode != 0
        assert "injoignable" in result.stderr


class TestRequiredDockerMode:
    """Barrière 2 — dans pytest lui-même, pour l'invocation directe."""

    def test_a_missing_docker_fails_instead_of_skipping(
        self, empty_path: Path, tmp_path: Path
    ) -> None:
        probe = INTEGRATION_DIR / "test_zz_docker_policy_probe.py"
        probe.write_text(_PROBE, encoding="utf-8")
        try:
            result = _run_pytest(
                [str(probe.relative_to(ENGINE_ROOT))],
                path_dir=empty_path,
                extra_env={"NEXUS_REQUIRE_DOCKER": "1"},
            )
        finally:
            probe.unlink()
        combined = result.stdout + result.stderr
        assert result.returncode != 0, combined
        assert "GOVERNANCE_DOCKER_REQUIRED" in combined
        # La propriété qui compte : le run n'a pas « réussi en sautant ».
        assert "1 skipped" not in combined

    def test_an_unreachable_daemon_fails_in_required_mode(
        self, failing_docker_path: Path
    ) -> None:
        result = _run_pytest(
            [GOVERNANCE_SUITE, "--collect-only"],
            path_dir=failing_docker_path,
            extra_env={"NEXUS_REQUIRE_DOCKER": "1"},
        )
        combined = result.stdout + result.stderr
        assert result.returncode != 0, combined
        assert "GOVERNANCE_DOCKER_REQUIRED" in combined

    @pytest.mark.parametrize("value", ["yes", "true", "2", " ", "on"])
    def test_a_malformed_requirement_is_refused(
        self, value: str, empty_path: Path
    ) -> None:
        """Une configuration illisible ne doit jamais retomber sur le mode
        permissif : ce serait le défaut qu'on ferme, déguisé."""
        result = _run_pytest(
            [GOVERNANCE_SUITE, "--collect-only"],
            path_dir=empty_path,
            extra_env={"NEXUS_REQUIRE_DOCKER": value},
        )
        combined = result.stdout + result.stderr
        assert result.returncode != 0, combined
        assert "is not a recognised value" in combined

    def test_the_local_permissive_mode_is_preserved(
        self, empty_path: Path
    ) -> None:
        """Hors mode obligatoire, une suite générale lancée sans Docker
        continue de sauter ses tests Docker plutôt que d'échouer — sans
        quoi ce lot rendrait le dépôt inutilisable hors CI."""
        result = _run_pytest(
            [GOVERNANCE_SUITE, "--collect-only"], path_dir=empty_path
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined

    def test_the_make_target_imposes_the_required_mode_itself(self) -> None:
        """La recette ne doit pas dépendre de l'environnement hérité."""
        makefile = (ENGINE_ROOT / "Makefile").read_text(encoding="utf-8")
        recipe = makefile.split("test-governance-pg: install", 1)[1]
        recipe = recipe.split("\n\n", 1)[0]
        assert "NEXUS_REQUIRE_DOCKER=1" in recipe


class TestGovernanceSuiteIsNonVacuous:
    def test_zero_collected_tests_is_a_failure(self, empty_path: Path) -> None:
        """Un filtre qui ne sélectionnerait rien doit faire échouer le run,
        pas produire un succès silencieux."""
        result = _run_pytest(
            [GOVERNANCE_SUITE, "-k", "un_nom_qui_ne_correspond_a_rien"],
            path_dir=empty_path,
        )
        assert result.returncode != 0, result.stdout + result.stderr
