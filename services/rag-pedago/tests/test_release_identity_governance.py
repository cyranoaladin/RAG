"""ADR-0050 : le producteur n'invente jamais une identité de release.

Le défaut fermé ici : `release_id or RELEASE_ID`. Un appelant qui ne disait
rien obtenait l'identité de la release historique, et une chaîne scellée
nouvelle partait sous une identité déjà publiée. ADR-0050 §1 fait de V1 un
enregistrement immuable, §3 et §4 interdisent d'en réutiliser l'identifiant.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_production_profile_release import (  # noqa: E402
    HISTORICAL_RELEASE_ID,
    PUBLISHED_RELEASE_IDS,
    ReleaseIdentityError,
    require_governed_release_id,
)


def test_aucune_identite_fournie_est_un_refus() -> None:
    """Le silence de l'appelant ne vaut plus l'identité historique."""
    for absent in (None, "", "   "):
        with pytest.raises(ReleaseIdentityError, match="aucune identité"):
            require_governed_release_id(absent)


def test_l_identite_historique_est_refusee_pour_une_nouvelle_release() -> None:
    with pytest.raises(ReleaseIdentityError, match="déjà publiée"):
        require_governed_release_id(HISTORICAL_RELEASE_ID)


@pytest.mark.parametrize("identite", sorted(PUBLISHED_RELEASE_IDS))
def test_toute_identite_deja_publiee_est_refusee(identite: str) -> None:
    with pytest.raises(ReleaseIdentityError, match="déjà publiée"):
        require_governed_release_id(identite)


def test_le_registre_reel_sur_disque_est_interroge(tmp_path: Path) -> None:
    """Le plancher codé ne suffit pas : une identité entrée au registre après
    coup doit être refusée elle aussi."""
    registre = tmp_path / "release-registry.json"
    registre.write_text(
        json.dumps({"releases": [{"release_id": "une-identite-entree-plus-tard"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ReleaseIdentityError, match="déjà publiée"):
        require_governed_release_id("une-identite-entree-plus-tard", registry_path=registre)


@pytest.mark.parametrize(
    "malformee",
    [
        "court",
        "Avec-Majuscules-2026-2027",
        "espace dans identite 2026",
        "../remonte/hors/du/registre",
        "identite/avec/chemin/2026-2027",
        "é" * 20,
    ],
)
def test_une_identite_malformee_est_refusee(malformee: str) -> None:
    with pytest.raises(ReleaseIdentityError, match="malformée"):
        require_governed_release_id(malformee)


def test_une_identite_neuve_et_bien_formee_est_acceptee(tmp_path: Path) -> None:
    registre = tmp_path / "release-registry.json"
    registre.write_text(json.dumps({"releases": []}), encoding="utf-8")
    identite = "production-profile-gate-2026-2027-v2"
    assert require_governed_release_id(identite, registry_path=registre) == identite


def test_le_rejeu_de_la_release_historique_reste_possible_explicitement() -> None:
    """Reconstruire V1 pour l'éprouver doit rester faisable — mais jamais par
    défaut : il faut le demander."""
    assert (
        require_governed_release_id(HISTORICAL_RELEASE_ID, allow_historical=True)
        == HISTORICAL_RELEASE_ID
    )


def test_le_producteur_ne_porte_plus_aucun_repli_implicite() -> None:
    """Contrôle textuel : le motif du défaut ne doit pas renaître."""
    source = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "build_production_profile_release.py"
    ).read_text(encoding="utf-8")
    assert "or RELEASE_ID" not in source
    assert "release_id or HISTORICAL_RELEASE_ID" not in source
