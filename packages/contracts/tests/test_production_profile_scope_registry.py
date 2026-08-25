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
        "rag_nexus_dgemc_terminale_option", "d336d22c53b01ee2cc73a80924c5282ebb59ef10edca335a6e958d77201b1dcf", "libre_terminale", "terminale", "generale", "dgemc", "option", "BOEN_special_8_2019-07-25_MENE1921266A_MENE2208320A"
    ),
    "prod_francais_premiere_tc_v1": ScopeFacts(
        "rag_nexus_francais_premiere_tc", "fce743e623671b4443da4aac919037a9017039c40fc6a1cf1d50c9384305c28b", "libre_premiere", "premiere", "generale", "francais", "tronc_commun", "BOEN_special_1_2019-01-22"
    ),
    "prod_francais_quatrieme_tc_v1": ScopeFacts(
        "rag_nexus_francais_quatrieme_tc", "28222d7b5a4e57717a26247a509906f4937155948cfc14b6ec0b8a397fb209d8", "libre_quatrieme", "quatrieme", "college", "francais", "tronc_commun", "BOEN_special_11_2018-07-26_aj_2020"
    ),
    "prod_francais_seconde_tc_v1": ScopeFacts(
        "rag_nexus_francais_seconde_tc", "bd5cf80b953266548e41b0733315883316b11a243db99250b956e4b4a2ee7da9", "libre_seconde", "seconde", "generale", "francais", "tronc_commun", "BOEN_special_1_2019-01-22"
    ),
    "prod_hlp_premiere_specialite_v1": ScopeFacts(
        "rag_nexus_hlp_premiere_specialite", "6462fde6f5fc2aca36ca6846d4d9d6eb6505f08552e4b064d49f389b568f3739", "libre_premiere", "premiere", "generale", "hlp", "specialite", "BOEN_special_1_2019-01-22"
    ),
    "prod_maths_premiere_gen_specialite_v1": ScopeFacts(
        "rag_nexus_maths_premiere_gen_specialite", "2b1aa2b47e5c5f9b010bdd9a7b6ba8b4c21cdc1afd00e3a9bcfd9469de96316b", "libre_premiere", "premiere", "generale", "maths", "specialite", "BOEN_14_2026-04-02_MENE2602917A"
    ),
    "prod_maths_quatrieme_tc_v1": ScopeFacts(
        "rag_nexus_maths_quatrieme_tc", "0a4974a3bee7e2dbf05412d47086da68ed6a9bf182c9bb14aa972325184c6772", "libre_quatrieme", "quatrieme", "college", "maths", "tronc_commun", "BOEN_special_11_2018-07-26_aj_2020"
    ),
    "prod_maths_seconde_tc_v1": ScopeFacts(
        "rag_nexus_maths_seconde_tc", "a5f1810dac14d08963f6c5b848a147ffa9505e44fd80723c477eac30d6a73aaf", "libre_seconde", "seconde", "generale", "maths", "tronc_commun", "BOEN_14_2026-04-02_MENE2602914A"
    ),
    "prod_maths_terminale_gen_specialite_v1": ScopeFacts(
        "rag_nexus_maths_terminale_gen_specialite", "c885ca363bad5901d87c0f29a6230129e8ccf958bb4b63980220c5749cc42382", "libre_terminale", "terminale", "generale", "maths", "specialite", "BOEN_special_8_2019-07-25"
    ),
    "prod_nsi_premiere_specialite_v1": ScopeFacts(
        "rag_nexus_nsi_premiere_specialite", "6e4ec07e59371e60c0562e284f8e42be1fc059e8aeadba7280aa44a29284fc71", "libre_premiere", "premiere", "generale", "nsi", "specialite", "BOEN_special_1_2019-01-22"
    ),
    "prod_nsi_terminale_specialite_v1": ScopeFacts(
        "rag_nexus_nsi_terminale_specialite", "8693b36b36ae142034cff1376cd55d01b3e731b6d127edfdf547746bbfc08444", "libre_terminale", "terminale", "generale", "nsi", "specialite", "BOEN_special_8_2019-07-25"
    ),
    "prod_pc_premiere_specialite_v1": ScopeFacts(
        "rag_nexus_pc_premiere_specialite", "e6940fc6f70b7aac6933b05987e053a9b2026a7ecea1d9974b60f873e501834f", "libre_premiere", "premiere", "generale", "physique_chimie", "specialite", "BOEN_special_1_2019-01-22"
    ),
    "prod_pc_terminale_specialite_v1": ScopeFacts(
        "rag_nexus_pc_terminale_specialite", "9244cf7e316968583e57b4af4be4eb0e162e62c0b4e84e16dfc0a1abc2fc8f2e", "libre_terminale", "terminale", "generale", "physique_chimie", "specialite", "BOEN_special_8_2019-07-25"
    ),
    "prod_philo_terminale_tc_v1": ScopeFacts(
        "rag_nexus_philo_terminale_tc", "55598466178cf6929e18f909fc835c4a54d26207554af7c84f9acecb9fb87b1b", "libre_terminale", "terminale", "generale", "philosophie", "tronc_commun", "BOEN_special_8_2019-07-25"
    ),
    "prod_ses_premiere_specialite_v1": ScopeFacts(
        "rag_nexus_ses_premiere_specialite", "dd6119bce6de846155cd9d68ffa88fe5cc0266c2e03b551a44b020dde5ffd9dc", "libre_premiere", "premiere", "generale", "ses", "specialite", "BOEN_special_1_2019-01-22"
    ),
    "prod_ses_terminale_specialite_v1": ScopeFacts(
        "rag_nexus_ses_terminale_specialite", "9b22795d9c17ac17c03d2b88c0774eb7a5e4c930face555626dc3b59ba1dde7e", "libre_terminale", "terminale", "generale", "ses", "specialite", "BOEN_special_8_2019-07-25"
    ),
    "prod_svt_premiere_specialite_v1": ScopeFacts(
        "rag_nexus_svt_premiere_specialite", "965a6df7066ddb3caec43c58f26e377ad97f18f4d86f38a21822a9208710ece4", "libre_premiere", "premiere", "generale", "svt", "specialite", "BOEN_special_1_2019-01-22"
    ),
    "prod_svt_terminale_specialite_v1": ScopeFacts(
        "rag_nexus_svt_terminale_specialite", "91c37631bac09e63eeb6734a0afe9814cd4eaea3baedcb7aafcf8f1bd02cca41", "libre_terminale", "terminale", "generale", "svt", "specialite", "BOEN_special_8_2019-07-25"
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
