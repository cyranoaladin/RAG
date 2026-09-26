"""Lot DI — incident HGGSP : un sujet de release que ses mappings scellés ne gouvernent pas.

La release V4 (``production-profile-gate-2026-2027-v4``) déclare deux
collections HGGSP (39 + 35 placements) mais scelle, sous
``authorities.subject_mapping_sha256``, un mapping de sujets sans ``hggsp``.
Worker B l'a découvert job par job (« external subject 'hggsp' is not
governed »), en consommant des tentatives.

Ces épreuves portent sur les VRAIS fichiers de la release V4, chargés par les
chargeurs canoniques et liés par les empreintes que le manifeste déclare :

A. la qualification refuse une release dont une collection ne se résout pas
   par le mapping scellé — exactement les deux collections HGGSP, et elles
   seules ;
B. l'autorité de sujets du successeur résout ``hggsp -> hggsp`` et les onze
   collections, sans rien retirer ni réinterpréter du mapping V4 ;
F. Worker B refuse de démarrer sur un périmètre qui contient HGGSP, et
   démarre sur les neuf autres collections : aucun job HGGSP n'est réclamé,
   donc aucun n'est consommé, avant que son autorité soit valide.

Rien n'est dérivé du nom de collection : un sujet absent du mapping reste
absent, et le mapping V4 scellé n'est jamais modifié.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from ingestor.multilevel_evidence import load_multilevel_candidate_inventory
from ingestor.multilevel_mapping import load_multilevel_mapping
from ingestor.multilevel_verified_placement import (
    MultilevelPlacementResolutionError,
    MultilevelVerifiedPedagogicalPlacementResolver,
    load_multilevel_release_eligibility,
    ungoverned_release_collections,
)

RACINE = Path(__file__).resolve().parents[3]
V4_DIR = (
    RACINE
    / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v4"
    / "release-024f8625ebfeb7ce/profile_gate"
)
V4_MANIFEST = V4_DIR / "production-profile-gate.release.json"
V4_MANIFEST_SHA256 = "bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be"
MAPPINGS = RACINE / "services/rag-engine/configs/mappings"
SUJETS_V4 = MAPPINGS / "eduscol_profile_gate_subjects.yml"
SUJETS_V4_SHA256 = "85a8efa17a9b04659800363ea3386208b46874ca673bdcb0889c6270bfc9c71c"
SUJETS_SUCCESSEUR = MAPPINGS / "eduscol_profile_gate_subjects_hggsp.yml"
SUJETS_SUCCESSEUR_SHA256 = "b909c1fb0a8b874b2bbe53cdb1973d5eadce97823c987f4e2b75fefd0d48bb6a"
NIVEAUX = MAPPINGS / "eduscol_multilevel_levels.yml"
TYPES = MAPPINGS / "eduscol_multilevel_document_types.yml"
COLLECTIONS = RACINE / "services/rag-engine/configs/rag_collections.yml"

HGGSP = frozenset({"rag_nexus_hggsp_premiere_specialite", "rag_nexus_hggsp_terminale_specialite"})
NON_HGGSP = frozenset({
    "rag_nexus_dgemc_terminale_option",
    "rag_nexus_hlp_premiere_specialite",
    "rag_nexus_hlp_terminale_specialite",
    "rag_nexus_nsi_premiere_specialite",
    "rag_nexus_nsi_terminale_specialite",
    "rag_nexus_ses_premiere_specialite",
    "rag_nexus_ses_terminale_specialite",
    "rag_nexus_svt_premiere_specialite",
    "rag_nexus_svt_terminale_specialite",
})
REFUS_HGGSP = "external subject 'hggsp' is not governed"


def _sha(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def autorites() -> dict[str, str]:
    assert _sha(V4_MANIFEST) == V4_MANIFEST_SHA256
    return dict(json.loads(V4_MANIFEST.read_text(encoding="utf-8"))["authorities"])


def _mapping(autorites: dict[str, str], *, sujets: Path, sujets_sha256: str):  # noqa: ANN202
    return load_multilevel_mapping(
        levels_path=NIVEAUX,
        expected_levels_sha256=autorites["level_mapping_sha256"],
        subjects_path=sujets,
        expected_subjects_sha256=sujets_sha256,
        document_types_path=TYPES,
        expected_document_types_sha256=autorites["document_type_mapping_sha256"],
    )


@pytest.fixture(scope="module")
def inventaire(autorites: dict[str, str]):  # noqa: ANN201
    return load_multilevel_candidate_inventory(
        V4_DIR / "candidate_inventory.json",
        expected_sha256=autorites["candidate_inventory_sha256"],
    )


@pytest.fixture(scope="module")
def configuration() -> dict[str, object]:
    return yaml.safe_load(COLLECTIONS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def eligibilite():  # noqa: ANN201
    return load_multilevel_release_eligibility(V4_MANIFEST, expected_sha256=V4_MANIFEST_SHA256)


def test_le_mapping_scelle_par_v4_est_intact_et_sans_hggsp(autorites: dict[str, str]) -> None:
    assert autorites["subject_mapping_sha256"] == SUJETS_V4_SHA256 == _sha(SUJETS_V4)
    sujets = yaml.safe_load(SUJETS_V4.read_text(encoding="utf-8"))["external_subjects"]
    assert "hggsp" not in sujets


def test_a_la_qualification_refuse_exactement_les_deux_collections_hggsp(
    autorites, inventaire, configuration, eligibilite
) -> None:
    mapping = _mapping(autorites, sujets=SUJETS_V4, sujets_sha256=autorites["subject_mapping_sha256"])
    assert {p.collection for p in eligibilite.placements} == HGGSP | NON_HGGSP
    refus = ungoverned_release_collections(
        placements=inventaire.placements, mapping=mapping, collection_config=configuration
    )
    assert refus == dict.fromkeys(HGGSP, REFUS_HGGSP)


def test_a_la_matiere_n_est_jamais_derivee_du_nom_de_collection(
    autorites, inventaire, configuration
) -> None:
    """Chaque collection HGGSP est bien configurée ``matiere: hggsp`` : si la
    règle se fiait au nom ou à la configuration, elle passerait. Elle refuse,
    parce que seule l'autorité scellée décide."""
    assert {configuration["collections"][c]["matiere"] for c in HGGSP} == {"hggsp"}
    mapping = _mapping(autorites, sujets=SUJETS_V4, sujets_sha256=autorites["subject_mapping_sha256"])
    assert set(ungoverned_release_collections(
        placements=inventaire.placements, mapping=mapping, collection_config=configuration
    )) == HGGSP


def test_b_l_autorite_du_successeur_resout_hggsp_sans_rien_retirer_de_v4(
    autorites, inventaire, configuration
) -> None:
    assert _sha(SUJETS_SUCCESSEUR) == SUJETS_SUCCESSEUR_SHA256
    v4 = yaml.safe_load(SUJETS_V4.read_text(encoding="utf-8"))
    successeur = yaml.safe_load(SUJETS_SUCCESSEUR.read_text(encoding="utf-8"))
    assert successeur["mapping_kind"] == v4["mapping_kind"]
    assert successeur["external_subjects"] == {**v4["external_subjects"], "hggsp": "hggsp"}
    mapping = _mapping(autorites, sujets=SUJETS_SUCCESSEUR, sujets_sha256=SUJETS_SUCCESSEUR_SHA256)
    hggsp = [p for p in inventaire.placements if p.collection in HGGSP]
    assert len(hggsp) == 74
    assert {
        mapping.resolve(
            external_level=p.external_level,
            external_subject=p.external_subject,
            external_document_type=p.external_document_type,
        ).matiere
        for p in hggsp
    } == {"hggsp"}
    assert ungoverned_release_collections(
        placements=inventaire.placements, mapping=mapping, collection_config=configuration
    ) == {}


def test_b_le_successeur_ne_peut_pas_remplacer_l_autorite_scellee_de_v4(
    autorites, eligibilite, inventaire, configuration
) -> None:
    """Le mapping successeur ne porte pas l'empreinte que V4 scelle : il ne
    peut pas être chargé à sa place (aucune réécriture de V4)."""
    with pytest.raises(Exception, match="digest differs"):
        _mapping(autorites, sujets=SUJETS_SUCCESSEUR, sujets_sha256=autorites["subject_mapping_sha256"])


@pytest.mark.parametrize(
    "alteration, attendu",
    [
        ({"hggsp": "histoire"}, "differs from configured subject 'hggsp'"),
        ({"ses": None}, "external subject 'ses' is not governed"),
    ],
)
def test_une_autorite_de_sujets_fausse_est_refusee(
    tmp_path, autorites, inventaire, configuration, alteration, attendu
) -> None:
    table = dict(yaml.safe_load(SUJETS_SUCCESSEUR.read_text(encoding="utf-8"))["external_subjects"])
    for cle, valeur in alteration.items():
        if valeur is None:
            table.pop(cle)
        else:
            table[cle] = valeur
    chemin = tmp_path / "sujets.yml"
    chemin.write_text(yaml.safe_dump(
        {"mapping_kind": "EDUSCOL_MULTILEVEL_SUBJECTS_V1", "external_subjects": table}
    ))
    mapping = _mapping(autorites, sujets=chemin, sujets_sha256=_sha(chemin))
    refus = ungoverned_release_collections(
        placements=inventaire.placements, mapping=mapping, collection_config=configuration
    )
    assert refus and all(attendu in raison for raison in refus.values())


def _resolveur(autorites, inventaire, configuration, eligibilite):  # noqa: ANN202
    """Seuls les champs que ``require_collections_governed`` lit sont réels ;
    les autres ne sont pas consultés par ce contrôle de démarrage."""
    mapping = _mapping(autorites, sujets=SUJETS_V4, sujets_sha256=autorites["subject_mapping_sha256"])
    inutilise = "0" * 64
    return MultilevelVerifiedPedagogicalPlacementResolver(
        release_manifest_sha256=V4_MANIFEST_SHA256,
        release_profile_manifest_digest=inutilise,
        catalog_sha256=inutilise,
        corpus_manifest_sha256=inutilise,
        placement_catalog_sha256=inutilise,
        currentness_evidence_sha256=inutilise,
        candidate_inventory_sha256=inventaire.sha256,
        programme_index_sha256=inutilise,
        currentness_school_year=inventaire.school_year,
        _candidate_inventory=inventaire,
        _currentness=None,  # type: ignore[arg-type]
        _mapping=mapping,
        _profiles={},
        _programme_registry=None,  # type: ignore[arg-type]
        _collection_config=configuration,
        _release_eligibility=eligibilite,
    )


def test_f_worker_b_refuse_de_demarrer_sur_toute_la_file_v4(
    autorites, inventaire, configuration, eligibilite
) -> None:
    resolveur = _resolveur(autorites, inventaire, configuration, eligibilite)
    for perimetre in (None, HGGSP, {"rag_nexus_hggsp_terminale_specialite", "rag_nexus_nsi_terminale_specialite"}):
        with pytest.raises(MultilevelPlacementResolutionError, match=REFUS_HGGSP):
            resolveur.require_collections_governed(perimetre)


def test_f_worker_b_demarre_sur_les_neuf_collections_gouvernees(
    autorites, inventaire, configuration, eligibilite
) -> None:
    _resolveur(autorites, inventaire, configuration, eligibilite).require_collections_governed(NON_HGGSP)


def test_f_une_selection_hors_release_est_refusee(
    autorites, inventaire, configuration, eligibilite
) -> None:
    with pytest.raises(MultilevelPlacementResolutionError, match="outside the release"):
        _resolveur(autorites, inventaire, configuration, eligibilite).require_collections_governed(
            {*NON_HGGSP, "rag_nexus_maths_terminale_specialite"}
        )


def test_l_identite_de_reprise_partielle_nomme_exactement_les_exclusions_derivees(tmp_path) -> None:
    """L'outil DI refuse une exclusion choisie à la main : l'identité
    versionnée doit égaler ce que les mappings SCELLÉS de V4 ne gouvernent pas."""
    import sys

    sys.path.insert(0, str(RACINE / "scripts/go_live"))
    import staging_v4_partial_recovery as di

    identite = RACINE / di.IDENTITE_PAR_DEFAUT
    di.verifier_exclusions(RACINE, identite)
    document = json.loads(identite.read_text(encoding="utf-8"))
    for exclues in (
        {"rag_nexus_hggsp_premiere_specialite": REFUS_HGGSP},
        {**document["excluded_collections"], "rag_nexus_nsi_terminale_specialite": "choix manuel"},
    ):
        altere = tmp_path / "identite.json"
        altere.write_text(json.dumps({**document, "excluded_collections": exclues}))
        with pytest.raises(di.RepriseRefusee, match="dérivées de l'autorité scellée"):
            di.verifier_exclusions(RACINE, altere)
