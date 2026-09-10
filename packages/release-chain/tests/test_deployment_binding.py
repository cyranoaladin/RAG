"""La configuration de déploiement, énoncée une seule fois.

Cette règle vivait dans un seul consommateur. Le qualificateur C1 la
réimplémentait, et l'a d'abord réimplémentée FAUX — acceptant un chemin sans
empreinte que le runtime refuse. Une règle de configuration écrite deux fois
est une règle qui divergera.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nexus_release_chain.deployment_binding import (
    REGISTRY_PATH_ENV,
    REGISTRY_SHA256_ENV,
    DeploymentBindingError,
    configured_release_registry,
)

SHA = "a" * 64


def test_aucune_variable_signifie_aucun_deploiement() -> None:
    """L'appelant retombe alors sur sa politique par défaut."""
    assert configured_release_registry({}) is None


def test_la_paire_complete_epingle_la_lignee() -> None:
    binding = configured_release_registry(
        {REGISTRY_PATH_ENV: "/app/release/release-registry.json", REGISTRY_SHA256_ENV: SHA}
    )
    assert binding == (Path("/app/release/release-registry.json"), SHA)


@pytest.mark.parametrize(
    "environnement",
    [
        {REGISTRY_PATH_ENV: "/app/release/release-registry.json"},
        {REGISTRY_SHA256_ENV: SHA},
        {REGISTRY_PATH_ENV: "", REGISTRY_SHA256_ENV: SHA},
        {REGISTRY_PATH_ENV: "/app/r.json", REGISTRY_SHA256_ENV: ""},
    ],
)
def test_une_paire_incomplete_est_un_refus(environnement: dict[str, str]) -> None:
    """Un chemin sans empreinte transformerait le fichier observé en sa propre
    autorité ; une empreinte sans chemin ne désigne rien."""
    with pytest.raises(DeploymentBindingError, match="incomplete"):
        configured_release_registry(environnement)


def test_le_locator_n_est_pas_l_autorite() -> None:
    """Deux stacks peuvent monter des chemins différents et servir la même
    lignée : c'est l'empreinte qui décide, jamais le chemin hôte."""
    staging = configured_release_registry(
        {REGISTRY_PATH_ENV: "/app/release/r.json", REGISTRY_SHA256_ENV: SHA}
    )
    autre = configured_release_registry(
        {REGISTRY_PATH_ENV: "/srv/nexus/releases/r.json", REGISTRY_SHA256_ENV: SHA}
    )
    assert staging is not None and autre is not None
    assert staging[0] != autre[0]
    assert staging[1] == autre[1]
