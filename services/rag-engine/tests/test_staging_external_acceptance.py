"""La recette externe : ce qu'elle refuse de déclarer PASS.

Un banc d'acceptation ne vaut que par ce qu'il refuse. Chaque refus est donc
éprouvé contre une réponse fabriquée qui a exactement le défaut visé — jamais
contre un service réel, que la CI n'a pas.

Le banc réutilise le client externe livré (`scripts/rag_query_external.py`) ;
ces épreuves vérifient aussi qu'il ne redéfinit ni le transport ni la forme du
contrat.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ENGINE_ROOT.parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
sys.path.insert(0, str(REPOSITORY_ROOT / "packages" / "contracts" / "src"))

import staging_external_acceptance as recette  # noqa: E402
from nexus_contracts import Citation, RetrievalResponse, RetrievalResult  # noqa: E402

CONFIG = SimpleNamespace(
    api_url="https://rag-staging.exemple",
    bff_token="jeton-de-service-bff-de-banc-0123456789",
    api_key="cle-de-client-de-banc",
    identity_token="identite.deja.emise",
)


def _result(*, collection: str, citation: Citation | None) -> RetrievalResult:
    return RetrievalResult(
        chunk_id="chunk-1",
        doc_id="d" * 64,
        excerpt="Les bases de données relationnelles et le langage SQL.",
        score=0.9,
        metadata={"collection": collection},
        citation=citation,
    )


def _citation(*, page: int | None = 4, source_uri: str = "https://eduscol/nsi.pdf") -> Citation:
    return Citation(
        source_label="Eduscol",
        source_uri=source_uri,
        page=page,
        rights="officiel_public",
    )


SCOPE = "prod_nsi_terminale_specialite_v1"


@pytest.fixture
def cas() -> recette.AcceptanceCase:
    return recette.build_case(SCOPE)


def _install(monkeypatch: pytest.MonkeyPatch, response: RetrievalResponse) -> None:
    monkeypatch.setattr(recette, "post_search", lambda _payload, *, config: response)


def _collection_of(cas: recette.AcceptanceCase) -> str:
    return cas.collection


def test_chaque_question_vise_une_collection_reelle() -> None:
    """Une question posée à une collection qui n'existe pas ne mesure rien."""
    from nexus_contracts import RetrievalScopeArtifactV2, load_retrieval_scope_registry

    servables = {
        str(artifact.evidence_subject.collection)
        for artifact in load_retrieval_scope_registry().values()
        if isinstance(artifact, RetrievalScopeArtifactV2)
    }
    assert recette.QUESTIONS_BY_COLLECTION
    inconnues = set(recette.QUESTIONS_BY_COLLECTION) - servables
    assert inconnues == set(), inconnues


def test_une_portee_sans_question_declaree_est_refusee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pas de question générique de repli : elle mesurerait autre chose."""
    monkeypatch.setattr(recette, "QUESTIONS_BY_COLLECTION", {})
    with pytest.raises(recette.AcceptanceError) as refus:
        recette.build_case(SCOPE)
    assert "aucune question pédagogique" in str(refus.value)


def test_le_cas_porte_la_collection_de_sa_portee() -> None:
    cas = recette.build_case(SCOPE)
    assert cas.collection == "rag_nexus_nsi_terminale_specialite"
    assert "SQL" in cas.query


def test_une_reponse_vide_n_est_jamais_un_succes(
    cas: recette.AcceptanceCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, RetrievalResponse(results=[], warnings=[], filters_applied={}))
    with pytest.raises(recette.AcceptanceError) as refus:
        recette.check_search(CONFIG, cas)
    assert "aucun résultat" in str(refus.value)


def test_un_resultat_sans_citation_est_refuse(
    cas: recette.AcceptanceCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sans citation, la réponse n'étaye rien : c'est une affirmation nue."""
    _install(
        monkeypatch,
        RetrievalResponse(
            results=[_result(collection=_collection_of(cas), citation=None)],
            warnings=[],
            filters_applied={},
        ),
    )
    with pytest.raises(recette.AcceptanceError) as refus:
        recette.check_search(CONFIG, cas)
    assert "sans citation" in str(refus.value)


def test_une_citation_sans_page_ni_source_est_refusee(
    cas: recette.AcceptanceCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(
        monkeypatch,
        RetrievalResponse(
            results=[
                _result(
                    collection=_collection_of(cas),
                    citation=_citation(page=None),
                )
            ],
            warnings=[],
            filters_applied={},
        ),
    )
    with pytest.raises(recette.AcceptanceError) as refus:
        recette.check_search(CONFIG, cas)
    assert "n'étaye rien" in str(refus.value)


def test_un_resultat_hors_portee_est_refuse(
    cas: recette.AcceptanceCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Servir hors de la portée signée serait le défaut le plus grave."""
    _install(
        monkeypatch,
        RetrievalResponse(
            results=[
                _result(collection="rag_nexus_une_autre_collection", citation=_citation())
            ],
            warnings=[],
            filters_applied={},
        ),
    )
    with pytest.raises(recette.AcceptanceError) as refus:
        recette.check_search(CONFIG, cas)
    assert "hors portée" in str(refus.value)


def test_un_cas_conforme_est_accepte(
    cas: recette.AcceptanceCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contrôle positif : sans lui, un refus systématique passerait pour rigueur."""
    _install(
        monkeypatch,
        RetrievalResponse(
            results=[_result(collection=_collection_of(cas), citation=_citation())],
            warnings=[],
            filters_applied={},
        ),
    )
    assert recette.check_search(CONFIG, cas) == (1, 1)


def test_une_taxonomie_qui_n_annonce_pas_la_collection_visee_est_refusee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interroger une collection non déclarée servable mesurerait autre chose."""
    monkeypatch.setattr(
        recette,
        "get_json",
        lambda _config, _route: {
            "version": 2,
            "collections": [{"collection": "rag_nexus_svt_terminale_specialite"}],
            "dimensions": {"matiere": ["svt"]},
        },
    )
    with pytest.raises(recette.AcceptanceError) as refus:
        recette.check_taxonomy(CONFIG, expected="rag_nexus_nsi_terminale_specialite")
    assert "n'annonce pas" in str(refus.value)


def test_une_taxonomie_vide_est_refusee(monkeypatch: pytest.MonkeyPatch) -> None:
    """Une taxonomie vide en 200 est indistinguable d'un compte vide légitime."""
    monkeypatch.setattr(
        recette,
        "get_json",
        lambda _config, _route: {"version": 2, "collections": [], "dimensions": {}},
    )
    with pytest.raises(recette.AcceptanceError) as refus:
        recette.check_taxonomy(CONFIG)
    assert "aucune collection" in str(refus.value)


def test_une_taxonomie_sans_dimension_est_refusee(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        recette,
        "get_json",
        lambda _config, _route: {
            "version": 2,
            "collections": [{"collection": "rag_nexus_nsi_terminale_specialite"}],
            "dimensions": {"matiere": []},
        },
    )
    with pytest.raises(recette.AcceptanceError):
        recette.check_taxonomy(CONFIG)


def test_une_taxonomie_typee_et_peuplee_est_acceptee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        recette,
        "get_json",
        lambda _config, _route: {
            "version": 2,
            "collections": [{"collection": "rag_nexus_nsi_terminale_specialite"}],
            "dimensions": {"matiere": ["nsi"]},
        },
    )
    assert recette.check_taxonomy(CONFIG) == 1


def test_la_recette_envoie_les_trois_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le service exige les trois sans repli : en envoyer deux mesurerait un 401."""
    observed: dict[str, str] = {}

    class _Response:
        status = 200

        def __enter__(self):  # noqa: D105
            return self

        def __exit__(self, *_args):  # noqa: D105
            return False

        def read(self, *_args):  # noqa: D102
            return b'{"version": 2, "collections": [1], "dimensions": {"matiere": ["nsi"]}}'

    def urlopen(request, timeout=None):  # noqa: ANN001, ARG001
        observed.update(request.headers)
        return _Response()

    monkeypatch.setattr(recette.urllib.request, "urlopen", urlopen)
    recette.get_json(CONFIG, "/taxonomy/v2")

    normalise = {name.lower(): value for name, value in observed.items()}
    assert normalise["authorization"] == f"Bearer {CONFIG.bff_token}"
    assert normalise["x-rag-api-key"] == CONFIG.api_key
    assert normalise["x-nexus-identity"] == CONFIG.identity_token


def test_la_recette_ne_redefinit_ni_le_transport_ni_le_contrat() -> None:
    """Deux vérités sur la forme d'appel finiraient par valider un simulacre."""
    source = Path(recette.__file__).read_text(encoding="utf-8")
    assert "from rag_query_external import" in source
    assert "post_search" in source
    assert "build_request" in source
    # Aucune requête POST fabriquée à la main : le POST vient du client livré.
    assert 'method="POST"' not in source


def test_l_echec_rend_un_verdict_explicite_et_un_code_non_nul(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ni « PASS » par défaut, ni code de sortie 0 sur un échec."""
    monkeypatch.setattr(recette, "load_external_client_config", lambda: CONFIG)
    monkeypatch.setattr(
        recette,
        "check_health",
        lambda _config: (_ for _ in ()).throw(recette.AcceptanceError("/health HTTP 503")),
    )
    assert recette.main(["--scope", SCOPE]) == 3
    sortie = capsys.readouterr().out
    assert "EXTERNAL_AGENT_E2E=FAIL" in sortie
    assert "503" in sortie
    assert "PASS" not in sortie


def test_le_verdict_reussi_ne_contient_aucun_secret(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(recette, "load_external_client_config", lambda: CONFIG)
    monkeypatch.setattr(recette, "check_health", lambda _config: None)
    monkeypatch.setattr(recette, "check_taxonomy", lambda _config, *, expected=None: 11)
    monkeypatch.setattr(recette, "check_search", lambda _config, _case: (8, 8))

    assert recette.main(["--scope", SCOPE]) == 0
    sortie = capsys.readouterr().out
    assert "EXTERNAL_AGENT_E2E=PASS" in sortie
    assert "SERVABLE_COLLECTIONS=11" in sortie
    assert "CITATIONS=8" in sortie
    for secret in (CONFIG.bff_token, CONFIG.api_key, CONFIG.identity_token):
        assert secret not in sortie
