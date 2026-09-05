"""Successeurs de scope de la release multi-niveaux régénérée (ADR-0048).

Ce module prouve trois choses, et rien d'autre :

  1. les trente scopes historiques restent packagés sous leurs identifiants et
     leurs digests d'origine — aucun octet, aucune empreinte n'a bougé ;
  2. les dix successeurs ne changent QUE la liaison de source : leur politique
     d'autorisation est celle, inchangée, du scope dont ils héritent ;
  3. la sémantique « diagnostic d'entrée en niveau N sur le contenu du niveau
     N−1 » est verrouillée, pour que personne ne la « corrige » par mégarde.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

import pytest
from nexus_contracts import (
    RetrievalScopeArtifactV2,
    load_retrieval_scope_artifact,
    load_retrieval_scope_registry,
)
from nexus_contracts.scope import RetrievalScopeArtifactV3

CONTRACTS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CONTRACTS_ROOT.parents[1]
MULTILEVEL_RELEASE = (
    REPO_ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/multilevel.release.json"
)

#: Digests gelés des TRENTE scopes V2 antérieurs à ce lot, plus le pilote V1.
#: Aucune ligne de cette table ne doit jamais changer de valeur : elle est la
#: preuve `OLD_SCOPE_DIGESTS_CHANGED=0` opposable en CI.
HISTORICAL_SCOPE_DIGESTS: Mapping[str, str] = {
    "libre_terminale_maths_nsi_real_v1": (
        "a1ed0fb1c7ec6344c17b155004d5bb61172b77f4b5bff6f5a250cc8b968fdd24"
    ),
    "entree_seconde_maths_v1": (
        "b6d8af23df88bd62c2ae601352a9591d2a97b16cca2a5723470679c2b547ce7b"
    ),
    "entree_seconde_francais_v1": (
        "1793ae29067f6f499f73e2d2dfdfc6b5bef5a7f809b75bc6165010165860b983"
    ),
    "entree_premiere_maths_v1": (
        "ea588c50397e720174f45d4ae85d851d49ad743e81899fc7b28a15cb8f890831"
    ),
    "entree_premiere_francais_v1": (
        "f983959892ec90ca68de8d6bf7649f76b76a52c449171cd59073305e2302cfb4"
    ),
    "entree_troisieme_maths_v1": (
        "f2bf84333a33cf4408e95901805066870a1e38cc361db0fd472943e5a4f3cbdf"
    ),
    "entree_troisieme_francais_v1": (
        "f2a483dfe490ea07bf13f30a907a54f05cf235a62fde05e832ffdbb708037b5f"
    ),
    "entree_terminale_maths_v1": (
        "17bb7b8accfc1c738dc3cf75a424808c39900100a771e71d29cb0bcb5fdceee1"
    ),
    "entree_terminale_nsi_v1": (
        "a5e311149bba4863125a9ca8c8e28b0400a27dc855b2cd37c329ebf56f104a93"
    ),
    "eaf_premiere_francais_v1": (
        "d674858bbe13c6c82a6b688a9444af8d7d1521b7fb5dd8763eb551a694fa2fb2"
    ),
    "terminale_maths_v1": (
        "3ea4cc2898f590bc0377f751b2e52a2a81f8878975eff0cb3b08382ec5bb3c63"
    ),
    "terminale_nsi_v1": (
        "22b4dd4be1e6c1eb52603a8f0f88a1e362b2b7c7ec2b291b34c5166d1175113b"
    ),
    "terminale_physique_chimie_v1": (
        "16ffcc4090f5e04531668ceaa66c19fad9eeb13e6d076b2793d607aefb9079f5"
    ),
    "prod_dgemc_terminale_option_v1": (
        "6d35cb6f39a22011fe7d07b1d573100c3123f4fcc149888161ba193c59ce4bfb"
    ),
    "prod_francais_premiere_tc_v1": (
        "14b534ae92d8b83a562781d5b1ab6872a45d55d37cc2db3a0e9bd5a96383aea9"
    ),
    "prod_francais_quatrieme_tc_v1": (
        "6d7e49d7748ac55a9ecebddf6501d694cb214f9b41e96fca825b35e0d94b9ef2"
    ),
    "prod_francais_seconde_tc_v1": (
        "fe18d7aed302ff44000c1d23e2bc5705362067a6be999b52e0696c6b01455e3d"
    ),
    "prod_hlp_premiere_specialite_v1": (
        "d27033c3c33b42f409444ffead785f5789b0e0668b7c4682c3124e956ec36e37"
    ),
    "prod_maths_premiere_gen_specialite_v1": (
        "6040ea2ad5e7c022814ce2da4f66f3726fe5f09654de944eaf744f5406dd4983"
    ),
    "prod_maths_quatrieme_tc_v1": (
        "e3bfdf325e7410d41023a2bbc73417fe5270691e4044ed4b6d3a3c49ab8b3454"
    ),
    "prod_maths_seconde_tc_v1": (
        "4cc04e1569c345d255be3743db92172273dca9febe0a0765ffc7c8480388a819"
    ),
    "prod_maths_terminale_gen_specialite_v1": (
        "55a70d1818bad95555be360cef0cf5f6d91c3c4ca27a474e564eb0a323cc1dfc"
    ),
    "prod_nsi_premiere_specialite_v1": (
        "c93c2149dabf8353fa8959ddaefcee0636c80f6963c8bcd6d25575b9aeab3837"
    ),
    "prod_nsi_terminale_specialite_v1": (
        "b6cb880fdfb0ec7c253e4571ce5683ec4452a6409997406240dde34127a69c7d"
    ),
    "prod_pc_premiere_specialite_v1": (
        "577c2213da3ff701f761b081769a50aecd35e472aeed1893e068c1de5cdd0e59"
    ),
    "prod_pc_terminale_specialite_v1": (
        "b152e78b06edc00680839041faf0726b5212ca16532ebd516a150b0b5f27fce5"
    ),
    "prod_philo_terminale_tc_v1": (
        "fe37f2b8ce27432471d84ae41038ade0881cc6267290cd6cf2881be856b618f1"
    ),
    "prod_ses_premiere_specialite_v1": (
        "e86731b299f9c95e7ddc0395da12b01e4884d9ed47b371805d7f5810ebdd8dfa"
    ),
    "prod_ses_terminale_specialite_v1": (
        "c906b75e7079b45104cf664b59f68f691f6240823d5813f87f46339c77ac4e66"
    ),
    "prod_svt_premiere_specialite_v1": (
        "d3bfefe5dd8edb486ed24e9d897ea8891e19d1c53950a46adc186f9bc3f5dfe9"
    ),
    "prod_svt_terminale_specialite_v1": (
        "92fc817fed20305f597299b911e188c65e12f5cbb54b8491fb91293b5dac1f9d"
    ),
}

#: Les dix successeurs émis par ADR-0048, avec la politique qu'ils reconduisent.
MULTILEVEL_SUCCESSORS: Mapping[str, str] = {
    "entree_premiere_maths_v2": "entree_premiere_maths_v1",
    "entree_premiere_francais_v2": "entree_premiere_francais_v1",
    "entree_troisieme_maths_v2": "entree_troisieme_maths_v1",
    "entree_troisieme_francais_v2": "entree_troisieme_francais_v1",
    "entree_terminale_maths_v2": "entree_terminale_maths_v1",
    "entree_terminale_nsi_v2": "entree_terminale_nsi_v1",
    "eaf_premiere_francais_v2": "eaf_premiere_francais_v1",
    "terminale_maths_v2": "terminale_maths_v1",
    "terminale_nsi_v2": "terminale_nsi_v1",
    "terminale_physique_chimie_v2": "terminale_physique_chimie_v1",
}

#: L'échelle des niveaux. Un diagnostic d'entrée en N porte sur le contenu N−1.
NIVEAU_LADDER: tuple[str, ...] = (
    "quatrieme",
    "troisieme",
    "seconde",
    "premiere",
    "terminale",
)


def _v2(scope_id: str) -> RetrievalScopeArtifactV2:
    artifact = load_retrieval_scope_artifact(scope_id)
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    return artifact


# --- 1. Immuabilité des scopes historiques -----------------------------------


def test_the_registry_holds_the_thirty_one_historical_scopes_and_the_ten_successors() -> None:
    """REGISTRY_BEFORE + NEW_SCOPES == REGISTRY_AFTER, mesuré."""
    registry = load_retrieval_scope_registry()

    assert set(HISTORICAL_SCOPE_DIGESTS) <= set(registry)
    assert set(MULTILEVEL_SUCCESSORS) <= set(registry)
    assert set(HISTORICAL_SCOPE_DIGESTS) & set(MULTILEVEL_SUCCESSORS) == set()
    assert len(HISTORICAL_SCOPE_DIGESTS) == 31
    assert len(MULTILEVEL_SUCCESSORS) == 10
    assert len(registry) == 41


@pytest.mark.parametrize(("scope_id", "digest"), HISTORICAL_SCOPE_DIGESTS.items())
def test_a_historical_scope_keeps_its_pinned_digest(scope_id: str, digest: str) -> None:
    """OLD_SCOPE_DIGESTS_CHANGED=0, y compris pour les dix-huit `prod_*`."""
    assert load_retrieval_scope_artifact(scope_id).sha256_digest() == digest


def test_no_artifact_of_this_perimeter_was_migrated_to_v3() -> None:
    """V3_ARTIFACTS=0 : rester en V2, aucune migration opportuniste."""
    registry = load_retrieval_scope_registry()

    assert not [
        scope_id
        for scope_id, artifact in registry.items()
        if isinstance(artifact, RetrievalScopeArtifactV3)
    ]


# --- 2. Le successeur ne change QUE la liaison de source ---------------------


@pytest.mark.parametrize(("successor", "source"), MULTILEVEL_SUCCESSORS.items())
def test_a_successor_reconducts_its_policy_without_widening_it(
    successor: str,
    source: str,
) -> None:
    """AUTHORIZATION_SEMANTIC_DIFF=0 sur les douze dimensions d'autorisation."""
    new = _v2(successor)
    old = _v2(source)

    assert new.target_identity == old.target_identity
    assert new.evidence_subject == old.evidence_subject
    assert new.status == old.status
    assert new.artifact_version == old.artifact_version == "2"
    # ADR-0045 : nouveau subject ⇒ nouvel identifiant ET nouveau digest.
    assert new.scope_id != old.scope_id
    assert new.source_sha256 != old.source_sha256
    assert new.sha256_digest() != old.sha256_digest()


def test_each_successor_binds_the_exact_subject_manifest_of_the_release() -> None:
    aggregate = json.loads(MULTILEVEL_RELEASE.read_text(encoding="utf-8"))
    sha_by_collection = {
        entry["collection"]: entry["sha256"] for entry in aggregate["subjects"]
    }

    bound = {
        str(_v2(successor).evidence_subject.collection): _v2(successor).source_sha256
        for successor in MULTILEVEL_SUCCESSORS
    }

    assert bound == sha_by_collection


def test_the_release_subjects_have_exactly_one_matching_scope_each() -> None:
    """ZERO_MATCHES=0, MULTIPLE_MATCHES=0, EXACT_MATCHES=SUBJECT_COUNT."""
    aggregate = json.loads(MULTILEVEL_RELEASE.read_text(encoding="utf-8"))
    assert hashlib.sha256(MULTILEVEL_RELEASE.read_bytes()).hexdigest() == (
        "6ec1a4f8e0d644540214660c3568b2c169770b7789cd850186b6c3f1d6bd1c26"
    )
    registry = load_retrieval_scope_registry()

    counts = []
    for entry in aggregate["subjects"]:
        counts.append(
            len(
                [
                    artifact
                    for artifact in registry.values()
                    if isinstance(artifact, RetrievalScopeArtifactV2)
                    and str(artifact.evidence_subject.collection) == entry["collection"]
                    and artifact.source_sha256 == entry["sha256"]
                ]
            )
        )

    assert counts.count(0) == 0
    assert [count for count in counts if count > 1] == []
    assert counts == [1] * len(aggregate["subjects"])


# --- 3. Verrou sémantique : entrée en N ⇒ contenu de N−1 ---------------------


@pytest.mark.parametrize(
    "scope_id",
    sorted(
        scope_id
        for scope_id in {*HISTORICAL_SCOPE_DIGESTS, *MULTILEVEL_SUCCESSORS}
        if scope_id.startswith("entree_")
    ),
)
def test_an_entry_diagnostic_targets_level_n_over_the_content_of_level_n_minus_one(
    scope_id: str,
) -> None:
    """Ce décalage est l'INTENTION métier du diagnostic, pas un défaut.

    Un élève qui entre en N est évalué sur ce qu'il devait maîtriser en N−1.
    Aligner les deux niveaux « pour corriger » détruirait le diagnostic : ce
    test le rend impossible sans le supprimer explicitement.
    """
    artifact = _v2(scope_id)
    target = artifact.target_identity.niveau.value
    evidence = artifact.evidence_subject.niveau.value

    assert target != evidence, "un diagnostic d'entrée n'interroge jamais son propre niveau"
    assert NIVEAU_LADDER.index(evidence) == NIVEAU_LADDER.index(target) - 1


@pytest.mark.parametrize(
    "scope_id",
    sorted(
        scope_id
        for scope_id in {*HISTORICAL_SCOPE_DIGESTS, *MULTILEVEL_SUCCESSORS}
        if scope_id.startswith(("eaf_", "terminale_", "prod_"))
    ),
)
def test_a_non_entry_scope_stays_on_its_own_level(scope_id: str) -> None:
    """Hors diagnostic d'entrée, la cible et la preuve partagent leur niveau."""
    artifact = _v2(scope_id)

    assert artifact.target_identity.niveau == artifact.evidence_subject.niveau
