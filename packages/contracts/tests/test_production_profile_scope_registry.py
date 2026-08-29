"""Scopes V2 immuables de la release de profils production 2026-2027."""

from __future__ import annotations

from typing import NamedTuple

from nexus_contracts import RetrievalScopeArtifactV2, load_retrieval_scope_registry


class ScopeFacts(NamedTuple):
    collection: str
    source_sha256: str
    tenant: str
    niveau: str
    voie: str
    matiere: str
    statut: str
    programme_version: str


PRODUCTION_PROFILE_SCOPES = {
    "prod_dgemc_terminale_option_v1": ScopeFacts(
        "rag_nexus_dgemc_terminale_option", "02408bcf498ec56225852525758396152f2ed1c919c24528fd5f0fb59f54627f", "libre_terminale", "terminale", "generale", "dgemc", "option", "BOEN_special_8_2019-07-25_MENE1921266A_MENE2208320A"
    ),
    "prod_francais_premiere_tc_v1": ScopeFacts(
        "rag_nexus_francais_premiere_tc", "12d592364da6dfaf7934222195f908215e48c3f8a77dcb070990cd09055c12ad", "libre_premiere", "premiere", "generale", "francais", "tronc_commun", "BOEN_special_1_2019-01-22"
    ),
    "prod_francais_quatrieme_tc_v1": ScopeFacts(
        "rag_nexus_francais_quatrieme_tc", "836b02555dba0f4f8d9c16dc64c6f5964e86ba92d4b967eda3e2397b2fb58775", "libre_quatrieme", "quatrieme", "college", "francais", "tronc_commun", "BOEN_special_11_2018-07-26_aj_2020"
    ),
    "prod_francais_seconde_tc_v1": ScopeFacts(
        "rag_nexus_francais_seconde_tc", "975ff077553830fb2e4c0da24a6baa7f59f81e9fc6029102329feb662e7ea88d", "libre_seconde", "seconde", "generale", "francais", "tronc_commun", "BOEN_special_1_2019-01-22"
    ),
    "prod_hlp_premiere_specialite_v1": ScopeFacts(
        "rag_nexus_hlp_premiere_specialite", "5e5afe7badcb497af1044359d9961a9c41f58984630fd38bd41fefbdbe313c6c", "libre_premiere", "premiere", "generale", "hlp", "specialite", "BOEN_special_1_2019-01-22"
    ),
    "prod_maths_premiere_gen_specialite_v1": ScopeFacts(
        "rag_nexus_maths_premiere_gen_specialite", "309ca9d5f116b8e0217b9d12549bd945cc1a1868b93fb54bcf7574676cd668d4", "libre_premiere", "premiere", "generale", "maths", "specialite", "BOEN_14_2026-04-02_MENE2602917A"
    ),
    "prod_maths_quatrieme_tc_v1": ScopeFacts(
        "rag_nexus_maths_quatrieme_tc", "37975e4faf5aa976ff51493b18b56e3ed8d2787af3f1e15dcad0bcfc448b5da9", "libre_quatrieme", "quatrieme", "college", "maths", "tronc_commun", "BOEN_special_11_2018-07-26_aj_2020"
    ),
    "prod_maths_seconde_tc_v1": ScopeFacts(
        "rag_nexus_maths_seconde_tc", "715b78d9e1eb73ddbe4b69c363c0b1922697801cce0277673fe14d0d8c97c909", "libre_seconde", "seconde", "generale", "maths", "tronc_commun", "BOEN_14_2026-04-02_MENE2602914A"
    ),
    "prod_maths_terminale_gen_specialite_v1": ScopeFacts(
        "rag_nexus_maths_terminale_gen_specialite", "16e30edd3cf25e80447924a3a61d5a3323dccdf776c1e49a188b8d51de9be362", "libre_terminale", "terminale", "generale", "maths", "specialite", "BOEN_special_8_2019-07-25"
    ),
    "prod_nsi_premiere_specialite_v1": ScopeFacts(
        "rag_nexus_nsi_premiere_specialite", "af49291a8b5d5ffe50157f1b7d595b5c7466c36893df99c7c8293e57bde0fee7", "libre_premiere", "premiere", "generale", "nsi", "specialite", "BOEN_special_1_2019-01-22"
    ),
    "prod_nsi_terminale_specialite_v1": ScopeFacts(
        "rag_nexus_nsi_terminale_specialite", "27710247f2cf796b279bfa1ae05708af13519b517d28b72880527c90bd279595", "libre_terminale", "terminale", "generale", "nsi", "specialite", "BOEN_special_8_2019-07-25"
    ),
    "prod_pc_premiere_specialite_v1": ScopeFacts(
        "rag_nexus_pc_premiere_specialite", "9fb1dd7abe303dc9a9e930ce301edb94b546dc6f28b52257f788ff78c194a7ee", "libre_premiere", "premiere", "generale", "physique_chimie", "specialite", "BOEN_special_1_2019-01-22"
    ),
    "prod_pc_terminale_specialite_v1": ScopeFacts(
        "rag_nexus_pc_terminale_specialite", "fb8134a8fe88478b01c73f10136f027c1dc24158466b90ba7c752cf4d0db1462", "libre_terminale", "terminale", "generale", "physique_chimie", "specialite", "BOEN_special_8_2019-07-25"
    ),
    "prod_philo_terminale_tc_v1": ScopeFacts(
        "rag_nexus_philo_terminale_tc", "be4645b174e9b7e9be375708e4fa6949cc1866bb31c567fc8f5f533fb121079c", "libre_terminale", "terminale", "generale", "philosophie", "tronc_commun", "BOEN_special_8_2019-07-25"
    ),
    "prod_ses_premiere_specialite_v1": ScopeFacts(
        "rag_nexus_ses_premiere_specialite", "03014f387da2840c1590c9bda4a58073a1a270c5fa5be11ea1e61e613f0007f9", "libre_premiere", "premiere", "generale", "ses", "specialite", "BOEN_special_1_2019-01-22"
    ),
    "prod_ses_terminale_specialite_v1": ScopeFacts(
        "rag_nexus_ses_terminale_specialite", "6dedcd0a5060fa918cb4cb68f420cbe829c2f56bcf77239389c80a8cd1cde4df", "libre_terminale", "terminale", "generale", "ses", "specialite", "BOEN_special_8_2019-07-25"
    ),
    "prod_svt_premiere_specialite_v1": ScopeFacts(
        "rag_nexus_svt_premiere_specialite", "776178d0a077a137ee3b5db724d5071a01f3d22f3ae3543b035452374802a94d", "libre_premiere", "premiere", "generale", "svt", "specialite", "BOEN_special_1_2019-01-22"
    ),
    "prod_svt_terminale_specialite_v1": ScopeFacts(
        "rag_nexus_svt_terminale_specialite", "29bd5d9363e737e49b9fca9654a46c04f4a6e23224b306897c57f12d2e9f5d8d", "libre_terminale", "terminale", "generale", "svt", "specialite", "BOEN_special_8_2019-07-25"
    ),
}


#: Seconde émission des scopes de la release production.
#:
#: Le rescellement de `production-profile-gate-2026-2027-v1` a changé les
#: digests des 18 manifests-sujets sans changer l'identité de la release.
#: ADR-0045 interdisant de muter un `source_sha256` publié, ces `_v2` lient
#: les nouveaux digests et les `_v1` restent packagés intacts (ADR-0052).
RESEALED_PRODUCTION_PROFILE_SCOPES = {
    "prod_dgemc_terminale_option_v2": ScopeFacts(
        "rag_nexus_dgemc_terminale_option", "c8692efe6f0cbcd7a1a12976e88afd232f2f05732f78361564781776a05df892", "libre_terminale", "terminale", "generale", "dgemc", "option", "BOEN_special_8_2019-07-25_MENE1921266A_MENE2208320A"
    ),
    "prod_francais_premiere_tc_v2": ScopeFacts(
        "rag_nexus_francais_premiere_tc", "72d58dc201071ff6d525dd31be60751773ad2815ca81a32f0e0e5d00cf4fea71", "libre_premiere", "premiere", "generale", "francais", "tronc_commun", "BOEN_special_1_2019-01-22"
    ),
    "prod_francais_quatrieme_tc_v2": ScopeFacts(
        "rag_nexus_francais_quatrieme_tc", "9bc7e5b594db7fea1b365e2cc5cb61be9c38c35d59669fcfa88c1df784fa2ff7", "libre_quatrieme", "quatrieme", "college", "francais", "tronc_commun", "BOEN_special_11_2018-07-26_aj_2020"
    ),
    "prod_francais_seconde_tc_v2": ScopeFacts(
        "rag_nexus_francais_seconde_tc", "64b93629e92740e23efca7de6384844d015dc14c3a9677d18c8e720112d13cb9", "libre_seconde", "seconde", "generale", "francais", "tronc_commun", "BOEN_special_1_2019-01-22"
    ),
    "prod_hlp_premiere_specialite_v2": ScopeFacts(
        "rag_nexus_hlp_premiere_specialite", "51de4e36d5fcb86f9f844b5466fcc00d169ee6712d2935a91042773af75039af", "libre_premiere", "premiere", "generale", "hlp", "specialite", "BOEN_special_1_2019-01-22"
    ),
    "prod_maths_premiere_gen_specialite_v2": ScopeFacts(
        "rag_nexus_maths_premiere_gen_specialite", "1b92615e9d32f639797d6e41fc67c1dd8ee5625426ef4c4c26aa2cb1cac019b0", "libre_premiere", "premiere", "generale", "maths", "specialite", "BOEN_14_2026-04-02_MENE2602917A"
    ),
    "prod_maths_quatrieme_tc_v2": ScopeFacts(
        "rag_nexus_maths_quatrieme_tc", "871acdf6b0ee0375a1d2394778adb6ad2a42fff81a3909741a59bff66b4389ff", "libre_quatrieme", "quatrieme", "college", "maths", "tronc_commun", "BOEN_special_11_2018-07-26_aj_2020"
    ),
    "prod_maths_seconde_tc_v2": ScopeFacts(
        "rag_nexus_maths_seconde_tc", "036a28bfacfbd42b6e6264cb8af2225aed51e3c3453c42467833abb836a5bb48", "libre_seconde", "seconde", "generale", "maths", "tronc_commun", "BOEN_14_2026-04-02_MENE2602914A"
    ),
    "prod_maths_terminale_gen_specialite_v2": ScopeFacts(
        "rag_nexus_maths_terminale_gen_specialite", "9e5c0a8b069ae3b2ea0edacd79c87953714a0ec4fed87cf99819652e5c4a8921", "libre_terminale", "terminale", "generale", "maths", "specialite", "BOEN_special_8_2019-07-25"
    ),
    "prod_nsi_premiere_specialite_v2": ScopeFacts(
        "rag_nexus_nsi_premiere_specialite", "8e563dd782e05990f31b62b50178df333afe26ff714dafbfbe0b470cd09ada25", "libre_premiere", "premiere", "generale", "nsi", "specialite", "BOEN_special_1_2019-01-22"
    ),
    "prod_nsi_terminale_specialite_v2": ScopeFacts(
        "rag_nexus_nsi_terminale_specialite", "27dd2a9bb0bab918ab613d6f047c04aac4948915f34dc48e82eb573349a9d310", "libre_terminale", "terminale", "generale", "nsi", "specialite", "BOEN_special_8_2019-07-25"
    ),
    "prod_pc_premiere_specialite_v2": ScopeFacts(
        "rag_nexus_pc_premiere_specialite", "bed055dfef24eb39698e61dc95aabcac089be0c4ec6329a89451951f56cd7c1c", "libre_premiere", "premiere", "generale", "physique_chimie", "specialite", "BOEN_special_1_2019-01-22"
    ),
    "prod_pc_terminale_specialite_v2": ScopeFacts(
        "rag_nexus_pc_terminale_specialite", "5219cf45e0b5f0808072e4aac3cf792e4d31e5afaa0de3a31e8bf0fe4cbe98fa", "libre_terminale", "terminale", "generale", "physique_chimie", "specialite", "BOEN_special_8_2019-07-25"
    ),
    "prod_philo_terminale_tc_v2": ScopeFacts(
        "rag_nexus_philo_terminale_tc", "893a464de6548cbaa9449a4966b26b1b280894b7382bf1da11ed0e7cfd15dd62", "libre_terminale", "terminale", "generale", "philosophie", "tronc_commun", "BOEN_special_8_2019-07-25"
    ),
    "prod_ses_premiere_specialite_v2": ScopeFacts(
        "rag_nexus_ses_premiere_specialite", "17c8635e5a8ad500790fef63885f211621732d14d97118b2390251698ac33cfd", "libre_premiere", "premiere", "generale", "ses", "specialite", "BOEN_special_1_2019-01-22"
    ),
    "prod_ses_terminale_specialite_v2": ScopeFacts(
        "rag_nexus_ses_terminale_specialite", "ef90c996c19ce88fa57f8cb2e3d63ebd9c8f2b9908a1aae5d9369945e54b7061", "libre_terminale", "terminale", "generale", "ses", "specialite", "BOEN_special_8_2019-07-25"
    ),
    "prod_svt_premiere_specialite_v2": ScopeFacts(
        "rag_nexus_svt_premiere_specialite", "2da4020769000a66b4e77f54587930e397ecfdaaefda63cb9f5bbe65512220c0", "libre_premiere", "premiere", "generale", "svt", "specialite", "BOEN_special_1_2019-01-22"
    ),
    "prod_svt_terminale_specialite_v2": ScopeFacts(
        "rag_nexus_svt_terminale_specialite", "a81ef106251aa7e771c773b77b572ee18d4bae568b7c761eb9e7046b71b39796", "libre_terminale", "terminale", "generale", "svt", "specialite", "BOEN_special_8_2019-07-25"
    ),
}


def test_registry_contains_all_immutable_production_profile_scopes() -> None:
    registry = load_retrieval_scope_registry()

    assert set(PRODUCTION_PROFILE_SCOPES) <= set(registry)
    assert set(RESEALED_PRODUCTION_PROFILE_SCOPES) <= set(registry)
    assert len(registry) == 49


def test_production_profile_scopes_bind_exact_release_subjects() -> None:
    registry = load_retrieval_scope_registry()
    everything = {
        **PRODUCTION_PROFILE_SCOPES,
        **RESEALED_PRODUCTION_PROFILE_SCOPES,
    }
    for scope_id, expected in everything.items():
        artifact = registry[scope_id]
        assert isinstance(artifact, RetrievalScopeArtifactV2)
        assert artifact.source_sha256 == expected.source_sha256
        target = artifact.target_identity
        evidence = artifact.evidence_subject
        assert target.tenant == expected.tenant
        assert target.niveau.value == expected.niveau
        assert target.voie.value == expected.voie
        assert target.matiere == expected.matiere
        assert target.statut_enseignement.value == expected.statut
        assert target.audience == "libre"
        assert [candidate.value for candidate in target.candidates] == ["libre"]
        assert evidence.collection == expected.collection
        assert evidence.tenant == expected.tenant
        assert evidence.niveau.value == expected.niveau
        assert evidence.voie.value == expected.voie
        assert evidence.matiere == expected.matiere
        assert evidence.statut_enseignement.value == expected.statut
        assert evidence.candidat.value == "libre"
        assert evidence.audiences == ["libre", "tous"]
        assert evidence.visibility == "internal"
        assert [right.value for right in evidence.rights] == ["officiel_public"]
        assert evidence.school_year == "2026-2027"
        assert evidence.programme_version == expected.programme_version


def test_scope_collection_and_source_digest_pair_is_unique() -> None:
    """Le couple `(collection, source_sha256)` doit rester unique.

    ADR-0045 fixe la règle de sélection au démarrage : le moteur choisit un
    scope par le couple exact `(collection, subject_sha256)`, et **zéro comme
    plusieurs correspondances sont des refus**. Une collision ne se manifesterait
    donc pas par un mauvais scope servi, mais par un refus de démarrage —
    exactement le mode de panne dont la seconde émission nous fait sortir.

    Une même collection peut légitimement porter plusieurs scopes : c'est le cas
    des scopes historiques et de production, puis des `_v1` et `_v2` après
    rescellement. Ce qui doit rester unique est le couple, jamais la collection
    seule.
    """
    registry = load_retrieval_scope_registry()

    pairs: list[tuple[str, str]] = [
        (artifact.evidence_subject.collection, artifact.source_sha256)
        for artifact in registry.values()
        if isinstance(artifact, RetrievalScopeArtifactV2)
    ]
    duplicates = {pair for pair in pairs if pairs.count(pair) > 1}

    assert not duplicates, sorted(duplicates)
    assert len(pairs) == 48


def test_resealed_scopes_never_mutate_their_v1_counterpart() -> None:
    """Les `_v1` restent intacts : les enveloppes émises les référencent.

    ADR-0045 : « toute nouvelle version de subject exige un nouvel ID de scope et
    un nouveau digest, jamais une mutation silencieuse d'un scope existant ».
    Ce test échouerait si une ré-émission future réécrivait un `_v1` au lieu
    d'ajouter un `_v2`.
    """
    registry = load_retrieval_scope_registry()

    for scope_id, expected in RESEALED_PRODUCTION_PROFILE_SCOPES.items():
        ancestor_id = scope_id.removesuffix("_v2") + "_v1"
        ancestor = registry[ancestor_id]
        resealed = registry[scope_id]
        assert isinstance(ancestor, RetrievalScopeArtifactV2)
        assert isinstance(resealed, RetrievalScopeArtifactV2)

        assert ancestor.source_sha256 == PRODUCTION_PROFILE_SCOPES[
            ancestor_id
        ].source_sha256, "un scope _v1 publié ne doit jamais être réécrit"
        assert resealed.source_sha256 == expected.source_sha256
        assert resealed.source_sha256 != ancestor.source_sha256
        # Même sujet de preuve, même identité cible : seule l'attestation change.
        assert (
            resealed.evidence_subject.collection
            == ancestor.evidence_subject.collection
        )
        assert resealed.target_identity == ancestor.target_identity
