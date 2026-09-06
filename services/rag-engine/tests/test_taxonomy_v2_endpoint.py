"""GET /taxonomy/v2 — une VUE des dimensions autorisées, pas une autorité.

Ce que l'endpoint doit prouver :

1. il n'annonce que ce que l'appelant a signé — jamais le catalogue entier ;
2. il n'invente aucune valeur : chaque dimension rendue est relue du
   catalogue ET du scope serveur dérivé, et les deux doivent coïncider ;
3. `specialite` n'y devient pas une nouvelle autorité. `statut_enseignement`
   n'est PAS l'une des dix dimensions de placement
   (`nexus_contracts.ingestion.ResourceScope`) : sa vérité canonique est le
   champ `statut` du catalogue `rag_collections.yml`, typé
   `StatutEnseignement`, et repris tel quel par `ServerRetrievalScope`.
   L'endpoint l'expose ; il ne le stocke ni ne le redéfinit.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from nexus_contracts import Rights
from nexus_contracts.document import StatutEnseignement
from nexus_contracts.ingestion import ResourceScope

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor.retrieval_scope_v2 import ServerRetrievalScope  # noqa: E402

CFG = {
    "version": 3,
    "domains": {"education": {"retrievable": True}, "quarantine": {"retrievable": False}},
    "collections": {
        "rag_nexus_nsi_terminale_specialite": {
            "matiere": "nsi",
            "niveau": "terminale",
            "voie": "gen",
            "statut": "specialite",
            "domain": "education",
            "instanciee": True,
        },
        "rag_nexus_maths_terminale_tc": {
            "matiere": "maths",
            "niveau": "terminale",
            "voie": "gen",
            "statut": "tronc_commun",
            "domain": "education",
            "instanciee": True,
        },
        "rag_nexus_quarantine": {
            "matiere": None,
            "niveau": None,
            "voie": None,
            "statut": None,
            "domain": "quarantine",
            "instanciee": True,
        },
    },
}


def _scope(collection: str, statut: str, matiere: str) -> ServerRetrievalScope:
    return ServerRetrievalScope(
        tenant="libre_terminale",
        niveau="terminale",
        voie="generale",
        matiere=matiere,
        statut_enseignement=statut,
        candidat="libre",
        audiences=("eleve",),
        rights=(Rights.officiel_public,),
        visibilities=("public",),
        school_year="2026-2027",
        collection=collection,
        programme_version="BOEN-2026",
        scope_id="scope-taxo",
        scope_digest="digest",
        source_sha256="0" * 64,
    )


SCOPES = {
    "rag_nexus_nsi_terminale_specialite": _scope(
        "rag_nexus_nsi_terminale_specialite", "specialite", "nsi"
    ),
    "rag_nexus_maths_terminale_tc": _scope(
        "rag_nexus_maths_terminale_tc", "tronc_commun", "maths"
    ),
}


@pytest.fixture
def endpoint(monkeypatch: pytest.MonkeyPatch):
    from ingestor import retrieval_v2_endpoint as module

    monkeypatch.setattr(module, "load_collection_config", lambda: CFG)
    monkeypatch.setattr(
        module, "_require_retrieval_identity", lambda *_a, **_k: SimpleNamespace()
    )
    monkeypatch.setattr(
        module, "_require_release_ready_if_governed", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        module,
        "build_server_retrieval_scope",
        lambda _verified, *, collection, collection_config: SCOPES[collection],
    )
    return module


def _allow(monkeypatch: pytest.MonkeyPatch, module, *collections: str) -> None:
    monkeypatch.setattr(
        module, "effective_signed_collections", lambda _verified: tuple(collections)
    )


def test_seules_les_collections_signees_sont_annoncees(
    endpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow(monkeypatch, endpoint, "rag_nexus_nsi_terminale_specialite")

    body = endpoint.get_taxonomy(SimpleNamespace()).model_dump(mode="json")

    assert [item["collection"] for item in body["collections"]] == [
        "rag_nexus_nsi_terminale_specialite"
    ]
    assert body["dimensions"]["matiere"] == ["nsi"]
    assert "maths" not in body["dimensions"]["matiere"]


def test_la_vue_est_versionnee_comme_le_reste_de_la_surface(
    endpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow(monkeypatch, endpoint, "rag_nexus_nsi_terminale_specialite")

    assert endpoint.get_taxonomy(SimpleNamespace()).version == 2


def test_une_collection_non_retrievable_n_est_jamais_annoncee(
    endpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Annoncer une dimension qu'on refusera de servir serait mentir."""
    _allow(monkeypatch, endpoint, "rag_nexus_quarantine")

    body = endpoint.get_taxonomy(SimpleNamespace()).model_dump(mode="json")

    assert body["collections"] == []
    assert body["dimensions"]["matiere"] == []


def test_specialite_est_expose_depuis_le_catalogue_sans_seconde_verite(
    endpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La valeur rendue est celle du catalogue, typée par le contrat."""
    _allow(
        monkeypatch,
        endpoint,
        "rag_nexus_nsi_terminale_specialite",
        "rag_nexus_maths_terminale_tc",
    )

    body = endpoint.get_taxonomy(SimpleNamespace()).model_dump(mode="json")

    par_collection = {item["collection"]: item for item in body["collections"]}
    assert par_collection["rag_nexus_nsi_terminale_specialite"][
        "statut_enseignement"
    ] == CFG["collections"]["rag_nexus_nsi_terminale_specialite"]["statut"]
    assert (
        par_collection["rag_nexus_maths_terminale_tc"]["statut_enseignement"]
        == "tronc_commun"
    )
    assert set(body["dimensions"]["statut_enseignement"]) == {
        "specialite",
        "tronc_commun",
    }
    # Toute valeur rendue est une valeur du contrat, jamais un texte libre.
    for value in body["dimensions"]["statut_enseignement"]:
        assert StatutEnseignement(value)


def test_statut_enseignement_n_est_pas_une_dimension_de_placement() -> None:
    """La propriété d'architecture, vérifiée contre le contrat lui-même.

    Si `statut_enseignement` entrait un jour dans `ResourceScope`, cette vue
    deviendrait une seconde vérité et devrait être repensée : l'épreuve le
    signalerait immédiatement."""
    assert "statut_enseignement" not in ResourceScope.model_fields
    assert set(ResourceScope.model_fields) == {
        "audience",
        "candidat",
        "collection",
        "matiere",
        "niveau",
        "programme_version",
        "school_year",
        "tenant",
        "visibility",
        "voie",
    }


def test_une_divergence_catalogue_scope_ferme_la_vue(
    endpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deux vérités qui divergent : on refuse, on n'en choisit pas une."""
    _allow(monkeypatch, endpoint, "rag_nexus_nsi_terminale_specialite")
    monkeypatch.setattr(
        endpoint,
        "build_server_retrieval_scope",
        lambda _verified, *, collection, collection_config: _scope(
            collection, "tronc_commun", "nsi"
        ),
    )

    with pytest.raises(HTTPException) as excinfo:
        endpoint.get_taxonomy(SimpleNamespace())

    assert excinfo.value.status_code == 403


def test_la_vue_n_expose_aucune_dimension_de_gouvernance(
    endpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ni empreinte de scope, ni identifiant d'artefact, ni droits internes."""
    _allow(monkeypatch, endpoint, "rag_nexus_nsi_terminale_specialite")

    body = endpoint.get_taxonomy(SimpleNamespace()).model_dump(mode="json")

    serialise = repr(body)
    for interdit in ("scope_digest", "source_sha256", "scope_id", "visibilit"):
        assert interdit not in serialise


def test_une_panne_d_autorite_remonte_au_lieu_de_rendre_une_taxonomie_vide(
    endpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail-closed n'est pas muet.

    Une taxonomie vide en 200 est indistinguable d'un compte légitimement
    vide : l'appelant croit que rien ne lui est servable, alors que
    l'autorité de release est en panne. Seul le 403 — une décision
    d'autorisation — peut être silencieux.
    """
    _allow(monkeypatch, endpoint, "rag_nexus_nsi_terminale_specialite")

    for status in (500, 503):
        monkeypatch.setattr(
            endpoint,
            "_check_retrievable",
            lambda *_a, _status=status, **_k: (_ for _ in ()).throw(
                HTTPException(status_code=_status, detail="release evidence unavailable")
            ),
        )
        with pytest.raises(HTTPException) as refus:
            endpoint.get_taxonomy(SimpleNamespace())
        assert refus.value.status_code == status


def test_une_collection_interdite_reste_omise_en_silence(
    endpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contrôle positif : sans lui, « tout remonte » passerait pour un progrès."""
    _allow(
        monkeypatch,
        endpoint,
        "rag_nexus_nsi_terminale_specialite",
        "rag_nexus_maths_terminale_tc",
    )
    reel = endpoint._check_retrievable

    def refuser_les_maths(collection, cfg, verified=None):
        if collection == "rag_nexus_maths_terminale_tc":
            raise HTTPException(status_code=403, detail="Forbidden")
        return reel(collection, cfg, verified)

    monkeypatch.setattr(endpoint, "_check_retrievable", refuser_les_maths)

    body = endpoint.get_taxonomy(SimpleNamespace()).model_dump(mode="json")

    assert [item["collection"] for item in body["collections"]] == [
        "rag_nexus_nsi_terminale_specialite"
    ]
