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


def test_registry_contains_all_immutable_production_profile_scopes() -> None:
    registry = load_retrieval_scope_registry()

    assert set(PRODUCTION_PROFILE_SCOPES) <= set(registry)
    assert len(registry) == 31


def test_production_profile_scopes_bind_exact_release_subjects() -> None:
    registry = load_retrieval_scope_registry()
    for scope_id, expected in PRODUCTION_PROFILE_SCOPES.items():
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
