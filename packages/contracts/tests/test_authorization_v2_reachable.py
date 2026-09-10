"""Une moitie de contrat qu on ne peut pas importer n existe pas.

`AuthorizationSetV2`, `ReleaseScopePlacementV2` et leurs fonctions etaient
implementes, declares dans les `__all__` de leurs modules, et **absents** de
`nexus_contracts/__init__.py`. Ils n avaient donc aucun appelant hors epreuves,
et la migration V2 semblait bloquee faute de producteur — alors qu elle etait
bloquee faute de chemin d import.

Ces epreuves tiennent la parite d atteignabilite entre V1 et V2. Elles ne
disent rien du comportement des deux protocoles : elles disent qu on peut les
atteindre par le meme chemin.
"""
from __future__ import annotations

import nexus_contracts
import pytest

#: Chaque nom V1 exporte, et son homologue V2 attendu.
PARITE = (
    ("AUTHORIZATION_SET_PROTOCOL_VERSION", "AUTHORIZATION_SET_PROTOCOL_VERSION_V2"),
    (
        "RELEASE_SCOPE_PLACEMENT_PROTOCOL_VERSION",
        "RELEASE_SCOPE_PLACEMENT_PROTOCOL_VERSION_V2",
    ),
    ("AuthorizationSetV1", "AuthorizationSetV2"),
    ("ReleaseScopePlacementV1", "ReleaseScopePlacementV2"),
    ("parse_authorization_set", "parse_authorization_set_v2"),
    ("parse_release_scope_placement", "parse_release_scope_placement_v2"),
    (
        "produce_release_scope_placement_from_blobs",
        "produce_release_scope_placement_v2_from_blobs",
    ),
    (
        "produce_release_scope_placement_from_git",
        "produce_release_scope_placement_v2_from_git",
    ),
)

#: Sans homologue V1 : la verification par egalite d ensemble n existe qu en V2.
PROPRES_A_V2 = ("verify_authorization_binding_set_v2",)


@pytest.mark.parametrize("nom_v1, nom_v2", PARITE)
def test_chaque_nom_v1_exporte_a_son_homologue_v2(nom_v1: str, nom_v2: str) -> None:
    assert hasattr(nexus_contracts, nom_v1), f"{nom_v1} n est plus atteignable"
    assert hasattr(nexus_contracts, nom_v2), (
        f"{nom_v2} n est pas atteignable depuis nexus_contracts alors que "
        f"{nom_v1} l est. Une moitie de contrat inatteignable est une moitie "
        "de contrat morte."
    )


@pytest.mark.parametrize("nom_v1, nom_v2", PARITE)
def test_chaque_homologue_v2_est_declare_dans_all(nom_v1: str, nom_v2: str) -> None:
    """Atteignable par hasard ne suffit pas : il faut etre declare."""
    assert nom_v1 in nexus_contracts.__all__
    assert nom_v2 in nexus_contracts.__all__, f"{nom_v2} absent de __all__"


@pytest.mark.parametrize("nom", PROPRES_A_V2)
def test_les_symboles_propres_a_v2_sont_atteignables(nom: str) -> None:
    assert hasattr(nexus_contracts, nom)
    assert nom in nexus_contracts.__all__


def test_les_deux_protocoles_sont_distincts() -> None:
    """Confondre les deux versions ferait passer un document V1 pour V2."""
    assert (
        nexus_contracts.AUTHORIZATION_SET_PROTOCOL_VERSION
        != nexus_contracts.AUTHORIZATION_SET_PROTOCOL_VERSION_V2
    )
    assert nexus_contracts.AUTHORIZATION_SET_PROTOCOL_VERSION_V2.endswith("-V2")
    assert (
        nexus_contracts.RELEASE_SCOPE_PLACEMENT_PROTOCOL_VERSION
        != nexus_contracts.RELEASE_SCOPE_PLACEMENT_PROTOCOL_VERSION_V2
    )


def test_le_module_et_le_paquet_exportent_la_meme_chose() -> None:
    """Deux listes d exports qui divergent, c est le defaut d origine."""
    from nexus_contracts import authorization_set

    v2_du_module = {
        nom for nom in authorization_set.__all__ if nom.endswith(("V2", "_v2"))
    }
    manquants = sorted(v2_du_module - set(nexus_contracts.__all__))
    assert manquants == [], (
        "declares par le module, absents du paquet : "
        f"{manquants}. C est ainsi que la V2 est devenue inatteignable."
    )
