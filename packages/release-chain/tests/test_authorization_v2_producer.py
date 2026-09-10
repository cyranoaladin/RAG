"""Le producteur canonique d AuthorizationSetV2, eprouve par l adversaire.

Ce qui est protege ici n est pas le format du document : c est le fait que le
producteur DERIVE les contenus autorises des placements de la release, et
qu il refuse de rendre un set que le gate d egalite d ensemble rejetterait.

Aucun objet n est ecrit sous `governance/`. Aucune revue humaine reelle n est
revendiquee : les empreintes de revue sont synthetiques.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from nexus_contracts import (
    AuthorizationSetError,
    ReleaseScopePlacementEntryV1,
    ReleaseScopePlacementV2,
    scope_digest,
    verify_authorization_binding_set_v2,
)
from nexus_contracts.ingestion import ResourceScope
from nexus_release_chain.authorization_v2_producer import (
    AuthorizationFactsV1,
    AuthorizationV2ProducerError,
    produce_authorization_set_v2,
)

MAINTENANT = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
CONTENU_A = "1" * 64
CONTENU_B = "2" * 64
EMPREINTE_MANIFESTE = "d" * 64
CORPUS = "c" * 64


def _scope(*, collection: str, niveau: str = "premiere") -> ResourceScope:
    return ResourceScope.model_validate(
        {
            "tenant": "libre_" + niveau,
            "collection": collection,
            "niveau": niveau,
            "voie": "generale",
            "matiere": "hlp",
            "candidat": "libre",
            "audience": ["libre"],
            "visibility": "public",
            "school_year": "2026-2027",
            "programme_version": "2026",
        }
    )


def _entree(*, contenu: str, scope: ResourceScope) -> ReleaseScopePlacementEntryV1:
    return ReleaseScopePlacementEntryV1.model_validate(
        {
            "content_sha256": contenu,
            "profile_id": scope.collection,
            "profile_version": "v1",
            "profile_fingerprint": "c" * 64,
            "scope": scope,
        }
    )


def _faits(identifiant: str) -> AuthorizationFactsV1:
    return AuthorizationFactsV1(
        authorization_id=identifiant,
        authorization_digest=sha256(f"auth:{identifiant}".encode()).hexdigest(),
        review_binding_digest=sha256(f"binding:{identifiant}".encode()).hexdigest(),
        valid_from=MAINTENANT - timedelta(days=1),
        valid_until=MAINTENANT + timedelta(days=30),
    )


@pytest.fixture
def deux_scopes() -> tuple[ResourceScope, ResourceScope]:
    return (
        _scope(collection="hlp_premiere", niveau="premiere"),
        _scope(collection="hlp_terminale", niveau="terminale"),
    )


@pytest.fixture
def placement(deux_scopes) -> ReleaseScopePlacementV2:
    premiere, terminale = deux_scopes
    return ReleaseScopePlacementV2.build(
        placements=[
            _entree(contenu=CONTENU_A, scope=premiere),
            _entree(contenu=CONTENU_B, scope=premiere),
            _entree(contenu=CONTENU_A, scope=terminale),
        ],
        profile_manifest_digest=EMPREINTE_MANIFESTE,
    )


@pytest.fixture
def faits_complets(deux_scopes) -> dict[str, AuthorizationFactsV1]:
    premiere, terminale = deux_scopes
    return {
        scope_digest(premiere): _faits("hlp-premiere"),
        scope_digest(terminale): _faits("hlp-terminale"),
    }


# --- la propriete centrale --------------------------------------------


def test_le_set_produit_passe_le_gate_d_egalite_d_ensemble(placement, faits_complets):
    ensemble = produce_authorization_set_v2(
        release_scope_placement=placement,
        authorization_facts_by_scope_digest=faits_complets,
        corpus_manifest_sha256=CORPUS,
    )
    verify_authorization_binding_set_v2(ensemble, release_scope_placement=placement)
    assert ensemble.authorization_binding_count == 3
    assert ensemble.unique_content_count == 2


def test_les_contenus_viennent_de_la_release_pas_de_l_operateur(
    placement, faits_complets, deux_scopes
):
    """LE garde-fou du lot. L operateur ne fournit aucun contenu ; s il en
    fournissait, une liste ressaisie pourrait diverger de la release."""
    premiere, terminale = deux_scopes
    ensemble = produce_authorization_set_v2(
        release_scope_placement=placement,
        authorization_facts_by_scope_digest=faits_complets,
        corpus_manifest_sha256=CORPUS,
    )
    par_scope = {m.scope_digest: set(m.allowed_content_sha256) for m in ensemble.members}
    assert par_scope[scope_digest(premiere)] == {CONTENU_A, CONTENU_B}
    assert par_scope[scope_digest(terminale)] == {CONTENU_A}
    assert not any(
        hasattr(f, "allowed_content_sha256") for f in faits_complets.values()
    ), "les faits operateur ne doivent porter aucun contenu"


def test_un_meme_contenu_sous_deux_scopes_donne_deux_liaisons(placement, faits_complets):
    """C est la raison d etre de la V2 : le contenu seul ne suffit pas."""
    ensemble = produce_authorization_set_v2(
        release_scope_placement=placement,
        authorization_facts_by_scope_digest=faits_complets,
        corpus_manifest_sha256=CORPUS,
    )
    liaisons = {
        (contenu, m.scope_digest)
        for m in ensemble.members
        for contenu in m.allowed_content_sha256
    }
    assert (CONTENU_A, ensemble.members[0].scope_digest) in liaisons
    assert len({d for _, d in liaisons}) == 2


# --- les refus ---------------------------------------------------------


def test_un_scope_de_la_release_sans_autorisation_est_refuse(placement, faits_complets, deux_scopes):
    _premiere, terminale = deux_scopes
    partiels = {
        d: f for d, f in faits_complets.items() if d != scope_digest(terminale)
    }
    with pytest.raises(AuthorizationV2ProducerError, match="aucune autorisation ne couvre"):
        produce_authorization_set_v2(
            release_scope_placement=placement,
            authorization_facts_by_scope_digest=partiels,
            corpus_manifest_sha256=CORPUS,
        )


def test_une_autorisation_hors_release_est_refusee(placement, faits_complets):
    """Autoriser plus que ce que la release exige est une autorisation trop
    large, pas une precaution."""
    etranger = _scope(collection="maths_seconde", niveau="seconde")
    trop = dict(faits_complets)
    trop[scope_digest(etranger)] = _faits("maths-seconde")
    with pytest.raises(AuthorizationV2ProducerError, match="absents de la release"):
        produce_authorization_set_v2(
            release_scope_placement=placement,
            authorization_facts_by_scope_digest=trop,
            corpus_manifest_sha256=CORPUS,
        )


def test_un_refus_du_producteur_est_aussi_un_refus_de_contrat(placement, faits_complets):
    """Un appelant qui attrape deja AuthorizationSetError ne doit pas laisser
    passer un refus du producteur."""
    with pytest.raises(AuthorizationSetError):
        produce_authorization_set_v2(
            release_scope_placement=placement,
            authorization_facts_by_scope_digest={},
            corpus_manifest_sha256=CORPUS,
        )


def test_une_fenetre_de_validite_invalide_est_refusee(placement, faits_complets, deux_scopes):
    premiere, _terminale = deux_scopes
    casse = dict(faits_complets)
    faits = casse[scope_digest(premiere)]
    casse[scope_digest(premiere)] = replace(
        faits, valid_until=faits.valid_from - timedelta(days=1)
    )
    with pytest.raises(AuthorizationSetError):
        produce_authorization_set_v2(
            release_scope_placement=placement,
            authorization_facts_by_scope_digest=casse,
            corpus_manifest_sha256=CORPUS,
        )


def test_le_set_est_lie_a_la_release_qui_l_a_produit(placement, faits_complets, deux_scopes):
    """Un set produit pour une release ne doit pas passer le gate d une autre."""
    premiere, _terminale = deux_scopes
    ensemble = produce_authorization_set_v2(
        release_scope_placement=placement,
        authorization_facts_by_scope_digest=faits_complets,
        corpus_manifest_sha256=CORPUS,
    )
    autre = ReleaseScopePlacementV2.build(
        placements=[_entree(contenu=CONTENU_A, scope=premiere)],
        profile_manifest_digest=EMPREINTE_MANIFESTE,
    )
    with pytest.raises(AuthorizationSetError):
        verify_authorization_binding_set_v2(ensemble, release_scope_placement=autre)


def test_le_producteur_lie_l_empreinte_du_manifeste_de_profils(placement, faits_complets):
    ensemble = produce_authorization_set_v2(
        release_scope_placement=placement,
        authorization_facts_by_scope_digest=faits_complets,
        corpus_manifest_sha256=CORPUS,
    )
    assert ensemble.profile_manifest_digest == placement.profile_manifest_digest
    assert ensemble.release_scope_placement_digest == placement.digest()


# --- la defense en profondeur, prouvee ---------------------------------


def test_le_gate_tourne_DANS_le_producteur_avant_le_retour(
    placement, faits_complets, monkeypatch
):
    """Sans cette epreuve, retirer le gate du producteur ne casse rien.

    Les autres epreuves verifient le gate de l exterieur : elles passent donc
    aussi bien avec un producteur qui ne le tient pas. Or la promesse du
    producteur est qu un set faux n existe JAMAIS, pas meme le temps d un
    retour de fonction. Cette promesse ne se verifie qu ici.
    """
    from nexus_release_chain import authorization_v2_producer as module

    appels: list[tuple] = []
    vrai_gate = module.verify_authorization_binding_set_v2

    def espion(ensemble, *, release_scope_placement):
        appels.append((ensemble, release_scope_placement))
        return vrai_gate(ensemble, release_scope_placement=release_scope_placement)

    monkeypatch.setattr(module, "verify_authorization_binding_set_v2", espion)
    ensemble = produce_authorization_set_v2(
        release_scope_placement=placement,
        authorization_facts_by_scope_digest=faits_complets,
        corpus_manifest_sha256=CORPUS,
    )

    assert len(appels) == 1, "le producteur n a pas tenu le gate avant de rendre"
    rendu, contre = appels[0]
    assert rendu is ensemble
    assert contre is placement


def test_un_gate_qui_refuse_empeche_le_retour(placement, faits_complets, monkeypatch):
    """Si le gate refuse, le producteur ne doit rien rendre du tout."""
    from nexus_release_chain import authorization_v2_producer as module

    def refus(_ensemble, *, release_scope_placement):  # noqa: ARG001
        raise AuthorizationSetError("refus simule du gate")

    monkeypatch.setattr(module, "verify_authorization_binding_set_v2", refus)
    with pytest.raises(AuthorizationSetError, match="refus simule"):
        produce_authorization_set_v2(
            release_scope_placement=placement,
            authorization_facts_by_scope_digest=faits_complets,
            corpus_manifest_sha256=CORPUS,
        )
