"""Le vérificateur complet V2, éprouvé par l'adversaire.

Ce que ces épreuves protègent : la V2 doit tenir TOUTE la chaîne de preuves de
la V1 — matériau de release, ancre de confiance, revue humaine, révocations,
fenêtres de validité — et remplacer une seule chose, l'union par contenu, par
l'égalité d'ensemble exacte des liaisons contre le placement.

La différence qui compte tient en un cas : un contenu partagé entre deux
périmètres pédagogiques. La V1 le refusait comme un recouvrement ; la V2 doit
l'accepter, tout en continuant de refuser qu'une MÊME liaison soit couverte
deux fois.
"""
from __future__ import annotations

from datetime import timedelta
from hashlib import sha256

import pytest
from nexus_contracts import (
    AuthorizationSetError,
    AuthorizationSetV2,
    ReleaseScopePlacementV2,
    VerifiedAuthorizationSetV1,
    verify_authorization_set_v2,
)

from test_authorization_set_contract import (  # type: ignore[import-not-found]
    NOW,
    SHA_A,
    SHA_B,
    _binding_bytes,
    _member,
    _placement_entry,
    _profile_fact,
    _revocations,
    _scope,
    _trust_anchor,
    _authorization,
    canonical_authorization_path,
    canonical_review_binding_path,
)

MANIFESTE = "d" * 64


def _membre_et_materiel(
    *, authorization_id: str, scope, contents: tuple[str, ...], profile_id: str
):
    """Un membre reel, avec son artefact d autorisation et sa liaison de revue."""
    autorisation = _authorization(
        authorization_id=authorization_id,
        scope=scope,
        contents=contents,
        profile_id=profile_id,
    )
    autorisation_raw = autorisation.canonical_bytes()
    liaison_raw = _binding_bytes(autorisation)
    membre = _member(
        authorization_id=authorization_id,
        scope=scope,
        contents=contents,
        authorization_digest=sha256(autorisation_raw).hexdigest(),
        review_binding_digest=sha256(liaison_raw).hexdigest(),
    )
    materiel = {
        canonical_authorization_path(authorization_id): autorisation_raw,
        canonical_review_binding_path(authorization_id): liaison_raw,
    }
    return membre, materiel


def _monter(paires):
    """Construit (set V2, materiel, placement, profils) depuis des paires
    (identifiant, scope, contenus).

    Chaque scope recoit une identite de profil DISTINCTE : deux scopes ne
    peuvent pas legitimement partager le meme profil verifie, et le contrat
    le refuse — a juste titre.
    """
    membres = []
    materiel: dict[str, bytes] = {}
    entrees = []
    profils = []
    for identifiant, scope, contenus in paires:
        profil_id = f"profile-{scope.collection}"
        membre, part = _membre_et_materiel(
            authorization_id=identifiant,
            scope=scope,
            contents=contenus,
            profile_id=profil_id,
        )
        membres.append(membre)
        materiel.update(part)
        profils.append(_profile_fact(scope=scope, profile_id=profil_id))
        for contenu in contenus:
            entrees.append(
                _placement_entry(
                    content_sha256=contenu, scope=scope, profile_id=profil_id
                )
            )
    placement = ReleaseScopePlacementV2.build(
        placements=entrees, profile_manifest_digest=MANIFESTE
    )
    ensemble = AuthorizationSetV2.build(
        members=membres,
        corpus_manifest_sha256="c" * 64,
        profile_manifest_digest=MANIFESTE,
        release_scope_placement_digest=placement.digest(),
    )
    return ensemble, materiel, placement, tuple(profils)


def _verifier(ensemble, materiel, placement, profils, *, revoked=()):
    return verify_authorization_set_v2(
        ensemble,
        release_files=materiel,
        trust_anchor=_trust_anchor(),
        environment="test",
        now=NOW,
        expected_repository="cyranoaladin/RAG",
        accepted_reviewers=("abenrhouma",),
        release_scope_placement=placement,
        verified_profiles=profils,
        revocation_registry_raw=_revocations(*revoked),
    )


@pytest.fixture
def simple():
    return _monter([("auth-francais-v1", _scope(), (SHA_A,))])


# --- la chaîne complète tient -----------------------------------------


def test_la_verification_complete_rend_un_agregat_verifie(simple) -> None:
    resultat = _verifier(*simple)
    assert isinstance(resultat, VerifiedAuthorizationSetV1)
    assert resultat.authorization_ids == ("auth-francais-v1",)


def test_une_autorisation_revoquee_est_refusee(simple) -> None:
    with pytest.raises(AuthorizationSetError, match="revoked"):
        _verifier(*simple, revoked=("auth-francais-v1",))


def test_un_materiel_de_release_manquant_est_refuse(simple) -> None:
    ensemble, materiel, placement, profils = simple
    ampute = {k: v for k, v in materiel.items() if "review-binding" not in k}
    with pytest.raises(AuthorizationSetError):
        _verifier(ensemble, ampute, placement, profils)


def test_un_reviewer_non_accepte_est_refuse(simple) -> None:
    ensemble, materiel, placement, profils = simple
    with pytest.raises(AuthorizationSetError):
        verify_authorization_set_v2(
            ensemble,
            release_files=materiel,
            trust_anchor=_trust_anchor(),
            environment="test",
            now=NOW,
            expected_repository="cyranoaladin/RAG",
            accepted_reviewers=("quelqu-un-d-autre",),
            release_scope_placement=placement,
            verified_profiles=profils,
            revocation_registry_raw=_revocations(),
        )


def test_une_autorisation_expiree_est_refusee(simple) -> None:
    ensemble, materiel, placement, profils = simple
    with pytest.raises(AuthorizationSetError, match="expired"):
        verify_authorization_set_v2(
            ensemble,
            release_files=materiel,
            trust_anchor=_trust_anchor(),
            environment="test",
            now=NOW + timedelta(days=400),
            expected_repository="cyranoaladin/RAG",
            accepted_reviewers=("abenrhouma",),
            release_scope_placement=placement,
            verified_profiles=profils,
            revocation_registry_raw=_revocations(),
        )


# --- LA difference avec la V1 ------------------------------------------


def test_un_contenu_partage_entre_deux_scopes_est_ACCEPTE() -> None:
    """La V1 refusait ce cas comme un recouvrement. C est la raison d etre de
    la V2, et le cas reel des contenus multi-placement."""
    premiere = _scope(collection="hlp_premiere", matiere="hlp")
    terminale = _scope(collection="hlp_terminale", matiere="hlp")
    monte = _monter(
        [
            ("auth-hlp-premiere", premiere, (SHA_A,)),
            ("auth-hlp-terminale", terminale, (SHA_A,)),
        ]
    )
    resultat = _verifier(*monte)
    assert len(resultat.scope_authorization_ids) == 2
    assert {ident for _, ident in resultat.content_authorization_ids} == {
        "auth-hlp-premiere",
        "auth-hlp-terminale",
    }
    ensemble = monte[0]
    assert ensemble.unique_content_count == 1
    assert ensemble.authorization_binding_count == 2


def test_la_meme_liaison_couverte_deux_fois_reste_refusee() -> None:
    """Ce que la V2 continue d interdire : deux autorisations sur la MEME
    liaison (contenu, scope)."""
    scope = _scope()
    m1, _mat1 = _membre_et_materiel(
        authorization_id="auth-un",
        scope=scope,
        contents=(SHA_A,),
        profile_id="profile-francais-seconde",
    )
    m2, _mat2 = _membre_et_materiel(
        authorization_id="auth-deux",
        scope=scope,
        contents=(SHA_A,),
        profile_id="profile-francais-seconde",
    )
    placement = ReleaseScopePlacementV2.build(
        placements=[_placement_entry(content_sha256=SHA_A, scope=scope)],
        profile_manifest_digest=MANIFESTE,
    )
    with pytest.raises(AuthorizationSetError):
        AuthorizationSetV2.build(
            members=[m1, m2],
            corpus_manifest_sha256="c" * 64,
            profile_manifest_digest=MANIFESTE,
            release_scope_placement_digest=placement.digest(),
        )


# --- l egalite d ensemble exacte ---------------------------------------


def test_une_liaison_exigee_mais_non_autorisee_est_refusee(simple) -> None:
    ensemble, materiel, _placement, profils = simple
    scope = _scope()
    plus_large = ReleaseScopePlacementV2.build(
        placements=[
            _placement_entry(content_sha256=SHA_A, scope=scope),
            _placement_entry(content_sha256=SHA_B, scope=scope),
        ],
        profile_manifest_digest=MANIFESTE,
    )
    with pytest.raises(AuthorizationSetError):
        _verifier(ensemble, materiel, plus_large, profils)


def test_le_verificateur_ne_prend_aucune_liste_de_contenus() -> None:
    """La liste exigee est DERIVEE du placement. Une liste fournie par
    l appelant pouvait diverger de la release ; un placement, non."""
    import inspect

    parametres = set(inspect.signature(verify_authorization_set_v2).parameters)
    assert "authority_required_content_sha256" not in parametres
    assert "release_scope_placement" in parametres


# --- la defense en profondeur, prouvee ---------------------------------


def test_le_gate_d_egalite_d_ensemble_tourne_DANS_le_verificateur(
    simple, monkeypatch
) -> None:
    """Sans cette epreuve, retirer le gate du verificateur ne casse rien.

    Un controle amont refuse deja un placement qui ne correspond pas. Le gate
    est donc une defense en profondeur — et une defense qu aucune epreuve ne
    tient est une defense qu on retire sans s en apercevoir.
    """
    from nexus_contracts import authorization_set as module

    appels: list[tuple] = []
    vrai = module.verify_authorization_binding_set_v2

    def espion(ensemble, *, release_scope_placement):
        appels.append((ensemble, release_scope_placement))
        return vrai(ensemble, release_scope_placement=release_scope_placement)

    monkeypatch.setattr(module, "verify_authorization_binding_set_v2", espion)
    _verifier(*simple)
    assert len(appels) == 1, "le verificateur V2 n a pas tenu le gate d egalite"


def test_un_gate_qui_refuse_empeche_toute_verification(simple, monkeypatch) -> None:
    from nexus_contracts import authorization_set as module

    def refus(_ensemble, *, release_scope_placement):  # noqa: ARG001
        raise AuthorizationSetError("refus simule du gate")

    monkeypatch.setattr(module, "verify_authorization_binding_set_v2", refus)
    with pytest.raises(AuthorizationSetError, match="refus simule"):
        _verifier(*simple)
