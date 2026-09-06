"""Le catalogue monté par le banc multi-niveaux et la release qu'il sert.

`/collections/v2` ne retient qu'une collection `instanciee: true` dont le
domaine est `retrievable: true`. Une release scellée qui sert une collection
dormante dans le catalogue monté est donc invisible du sélecteur, sans que
rien n'échoue : le banc reçoit une liste vide. Ces épreuves lient le catalogue
du banc à la release que le banc configure, et refusent l'activation d'une
collection que cette release ne sert pas.
"""

from __future__ import annotations

from pathlib import Path

from ingestor.collection_config import load_collection_config
from ingestor.release_readiness import load_release_registry
from ingestor.retrieval_v2_endpoint import _list_retrievable_collections

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SERVICE_ROOT.parents[1]
CANONICAL_CATALOGUE = SERVICE_ROOT / "configs" / "rag_collections.yml"
MULTILEVEL_CATALOGUE = (
    SERVICE_ROOT / "configs" / "staging" / "rag_collections_multilevel.yml"
)
MULTILEVEL_RELEASE = (
    REPOSITORY_ROOT
    / "services"
    / "rag-pedago"
    / "data"
    / "releases"
    / "prerentree_2026_2027"
    / "multilevel"
    / "multilevel.release.json"
)
MULTILEVEL_RELEASE_SHA256 = (
    "6ec1a4f8e0d644540214660c3568b2c169770b7789cd850186b6c3f1d6bd1c26"
)
E2E = SERVICE_ROOT / "tests" / "integration" / "test_multilevel_real_ingestion.py"


def _served_collections() -> set[str]:
    registry = load_release_registry(((MULTILEVEL_RELEASE, MULTILEVEL_RELEASE_SHA256),))
    return set(registry.collections)


def _instanciated(path: Path) -> set[str]:
    config = load_collection_config(path)
    return {
        name
        for name, definition in config["collections"].items()
        if definition.get("instanciee") is True
    }


def test_le_banc_designe_la_release_que_ces_epreuves_mesurent() -> None:
    """La release mesurée ici est celle que le banc épingle, pas une autre."""
    source = E2E.read_text(encoding="utf-8")
    assert f'RELEASE_SHA256 = "{MULTILEVEL_RELEASE_SHA256}"' in source


def test_le_banc_monte_le_catalogue_de_sa_propre_release() -> None:
    source = E2E.read_text(encoding="utf-8")
    assert '"staging" / "rag_collections_multilevel.yml"' in source
    assert '"configs" / "rag_collections.yml"' not in source


def test_le_catalogue_du_banc_rend_servable_chaque_collection_servie() -> None:
    served = _served_collections()
    servable = {
        item["name"]
        for item in _list_retrievable_collections(
            load_collection_config(MULTILEVEL_CATALOGUE)
        )["collections"]
    }
    assert served <= servable
    assert served - servable == set()


def test_le_catalogue_du_banc_n_active_rien_que_sa_release_ne_serve() -> None:
    served = _served_collections()
    base = _instanciated(CANONICAL_CATALOGUE)
    activated = _instanciated(MULTILEVEL_CATALOGUE) - base
    assert activated == served - base
    assert activated
