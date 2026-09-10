"""La sélection du mécanisme de release, énoncée une seule fois — les trois.

Le registre canonique n'est pas le seul mécanisme que le runtime reconnaît :
une liste explicite de manifests et le couple historique d'un manifest unique
désignent aussi ce qui est servi, et le runtime refuse qu'ils parlent à deux.
Cette sélection vivait dans le seul runtime ; le qualificateur C1 n'en
connaissait qu'un tiers, et divergeait (P2 ASTRA-PR153-P2-001).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from nexus_release_chain.deployment_binding import (
    MANIFEST_PATH_ENV,
    MANIFEST_SHA256_ENV,
    MANIFESTS_JSON_ENV,
    REGISTRY_PATH_ENV,
    REGISTRY_SHA256_ENV,
    RELEASE_AUTHORITY_LEGACY_MANIFEST,
    RELEASE_AUTHORITY_MANIFEST_LIST,
    RELEASE_AUTHORITY_REGISTRY_FILE,
    DeploymentBindingError,
    ReleaseAuthoritySelection,
    configured_release_manifest,
    load_selected_release_registry,
    parse_release_manifest_list,
    select_release_authority,
)
from nexus_release_chain.release_readiness import (
    ReleaseReadinessError,
    load_release_registry,
    load_release_registry_file,
)

SHA = "a" * 64
RELEASES = (
    Path(__file__).resolve().parents[3]
    / "services" / "rag-pedago" / "data" / "releases" / "prerentree_2026_2027"
)
REGISTRY = RELEASES / "release-registry.json"
WAVE0 = RELEASES / "wave0" / "wave0.release.json"
MULTILEVEL = RELEASES / "multilevel" / "multilevel.release.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _refus(environnement: dict[str, str]) -> str:
    with pytest.raises(DeploymentBindingError) as refus:
        select_release_authority(environnement)
    return str(refus.value)


# --- un mécanisme, ou aucun -------------------------------------------------


def test_aucune_variable_signifie_aucun_deploiement() -> None:
    assert select_release_authority({}) is None


def test_le_registre_est_selectionne_par_sa_paire() -> None:
    selection = select_release_authority({REGISTRY_PATH_ENV: "/app/r.json", REGISTRY_SHA256_ENV: SHA})
    assert selection == ReleaseAuthoritySelection(
        RELEASE_AUTHORITY_REGISTRY_FILE, ((Path("/app/r.json"), SHA),)
    )


def test_le_manifest_historique_est_selectionne_par_sa_paire() -> None:
    selection = select_release_authority({MANIFEST_PATH_ENV: "/app/w.json", MANIFEST_SHA256_ENV: SHA})
    assert selection == ReleaseAuthoritySelection(
        RELEASE_AUTHORITY_LEGACY_MANIFEST, ((Path("/app/w.json"), SHA),)
    )


def test_la_liste_explicite_est_selectionnee_dans_l_ordre_declare() -> None:
    selection = select_release_authority(
        {MANIFESTS_JSON_ENV: json.dumps([{"path": "/a.json", "sha256": SHA}, {"path": "/b.json", "sha256": "b" * 64}])}
    )
    assert selection == ReleaseAuthoritySelection(
        RELEASE_AUTHORITY_MANIFEST_LIST, ((Path("/a.json"), SHA), (Path("/b.json"), "b" * 64))
    )


# --- une paire incomplète est un refus, pour les deux paires ---------------


@pytest.mark.parametrize(
    "environnement",
    [
        {MANIFEST_PATH_ENV: "/app/w.json"},
        {MANIFEST_SHA256_ENV: SHA},
        {MANIFEST_PATH_ENV: "", MANIFEST_SHA256_ENV: SHA},
        {MANIFEST_PATH_ENV: "/app/w.json", MANIFEST_SHA256_ENV: ""},
        {MANIFEST_PATH_ENV: "", MANIFEST_SHA256_ENV: ""},
    ],
)
def test_un_couple_historique_incomplet_est_un_refus(environnement: dict[str, str]) -> None:
    with pytest.raises(DeploymentBindingError, match="release manifest configuration incomplete"):
        configured_release_manifest(environnement)
    assert "incomplete" in _refus(environnement)


@pytest.mark.parametrize(
    "environnement",
    [
        {REGISTRY_PATH_ENV: "/app/r.json"},
        {REGISTRY_SHA256_ENV: SHA},
        {REGISTRY_PATH_ENV: "", REGISTRY_SHA256_ENV: ""},
    ],
)
def test_une_paire_de_registre_incomplete_est_un_refus_par_la_selection(environnement: dict[str, str]) -> None:
    assert "incomplete" in _refus(environnement)


# --- deux mécanismes, c'est une ambiguïté -----------------------------------


@pytest.mark.parametrize(
    "environnement",
    [
        {REGISTRY_PATH_ENV: "/r", REGISTRY_SHA256_ENV: SHA, MANIFEST_PATH_ENV: "/w", MANIFEST_SHA256_ENV: SHA},
        {REGISTRY_PATH_ENV: "/r", REGISTRY_SHA256_ENV: SHA, MANIFESTS_JSON_ENV: "[]"},
        {MANIFEST_PATH_ENV: "/w", MANIFEST_SHA256_ENV: SHA, MANIFESTS_JSON_ENV: "[]"},
        {REGISTRY_PATH_ENV: "/r", REGISTRY_SHA256_ENV: SHA, MANIFEST_PATH_ENV: "/w", MANIFEST_SHA256_ENV: SHA, MANIFESTS_JSON_ENV: "[]"},
        # Une liste MALFORMÉE à côté d'un registre est d'abord une ambiguïté :
        # l'ordre des refus est celui que le runtime a toujours appliqué.
        {REGISTRY_PATH_ENV: "/r", REGISTRY_SHA256_ENV: SHA, MANIFESTS_JSON_ENV: "{nope"},
        {REGISTRY_PATH_ENV: "/r", REGISTRY_SHA256_ENV: SHA, MANIFESTS_JSON_ENV: ""},
    ],
    ids=["registre+legacy", "registre+liste", "legacy+liste", "les trois", "registre+liste malformée", "registre+liste vide"],
)
def test_deux_mecanismes_sont_refuses_comme_ambigus(environnement: dict[str, str]) -> None:
    assert _refus(environnement) == "release manifest configuration is ambiguous"


def test_une_paire_incomplete_est_refusee_avant_l_ambiguite() -> None:
    """La précédence du runtime, conservée : le registre incomplet parle en premier."""
    assert "incomplete" in _refus({REGISTRY_PATH_ENV: "/r", MANIFESTS_JSON_ENV: "[]"})
    assert "incomplete" in _refus({REGISTRY_PATH_ENV: "/r", REGISTRY_SHA256_ENV: SHA, MANIFEST_PATH_ENV: "/w"})


# --- la liste explicite est analysée strictement ---------------------------


@pytest.mark.parametrize(
    ("brut", "motif"),
    [
        ("", "not valid JSON"),
        ("{nope", "not valid JSON"),
        ("{}", "must be an array"),
        ('"x"', "must be an array"),
        (json.dumps([{"path": "/w.json"}]), "entry 0 is invalid"),
        (json.dumps([{"path": "/w.json", "sha256": SHA, "extra": 1}]), "entry 0 is invalid"),
        (json.dumps([{"path": "  ", "sha256": SHA}]), "entry 0 is invalid"),
        (json.dumps([{"path": "/w.json", "sha256": 1}]), "entry 0 is invalid"),
        (json.dumps([{"path": 1, "sha256": SHA}]), "entry 0 is invalid"),
        (json.dumps([{"path": "/a.json", "sha256": SHA}, "x"]), "entry 1 is invalid"),
    ],
)
def test_une_liste_malformee_est_un_refus_nomme(brut: str, motif: str) -> None:
    with pytest.raises(DeploymentBindingError, match=motif):
        parse_release_manifest_list(brut)
    with pytest.raises(DeploymentBindingError, match=motif):
        select_release_authority({MANIFESTS_JSON_ENV: brut})


def test_une_liste_vide_est_selectionnee_puis_refusee_au_chargement() -> None:
    """``[]`` est une liste valide qui ne désigne rien : c'est le chargeur qui
    refuse, avec son mot — exactement le comportement du runtime."""
    selection = select_release_authority({MANIFESTS_JSON_ENV: "[]"})
    assert selection == ReleaseAuthoritySelection(RELEASE_AUTHORITY_MANIFEST_LIST, ())
    with pytest.raises(ReleaseReadinessError, match="must not be empty"):
        load_selected_release_registry(selection)


# --- le chargement est celui des chargeurs existants, sur les vrais fichiers


def test_le_registre_selectionne_se_charge_comme_par_le_chargeur_de_registre() -> None:
    assert REGISTRY.is_file(), "le registre versionné doit exister : la corroboration n'aurait pas lieu"
    selection = select_release_authority({REGISTRY_PATH_ENV: str(REGISTRY), REGISTRY_SHA256_ENV: _sha(REGISTRY)})
    assert selection is not None
    charge = load_selected_release_registry(selection)
    attendu = load_release_registry_file(REGISTRY, _sha(REGISTRY))
    assert charge == attendu


@pytest.mark.parametrize(
    "environnement",
    [
        lambda: {MANIFEST_PATH_ENV: str(WAVE0), MANIFEST_SHA256_ENV: _sha(WAVE0)},
        lambda: {MANIFESTS_JSON_ENV: json.dumps([{"path": str(WAVE0), "sha256": _sha(WAVE0)}])},
    ],
    ids=["legacy", "liste"],
)
def test_le_manifest_wave0_selectionne_se_charge_comme_par_le_chargeur_de_manifests(environnement) -> None:
    assert WAVE0.is_file()
    selection = select_release_authority(environnement())
    assert selection is not None
    charge = load_selected_release_registry(selection)
    assert charge == load_release_registry(((WAVE0, _sha(WAVE0)),))
    contenus = {a.content_sha256 for m in charge.manifests for a in m.expectation.artifacts}
    registre = load_release_registry_file(REGISTRY, _sha(REGISTRY))
    contenus_registre = {a.content_sha256 for m in registre.manifests for a in m.expectation.artifacts}
    assert contenus != contenus_registre, (
        "Wave 0 et le registre ne servent pas le même ensemble : c'est tout le P2"
    )


def test_une_liste_de_deux_manifests_se_charge_dans_l_ordre_declare() -> None:
    selection = select_release_authority(
        {MANIFESTS_JSON_ENV: json.dumps([{"path": str(WAVE0), "sha256": _sha(WAVE0)}, {"path": str(MULTILEVEL), "sha256": _sha(MULTILEVEL)}])}
    )
    assert selection is not None
    charge = load_selected_release_registry(selection)
    assert charge == load_release_registry(((WAVE0, _sha(WAVE0)), (MULTILEVEL, _sha(MULTILEVEL))))
    assert [m.path for m in charge.manifests] == [WAVE0.resolve(), MULTILEVEL.resolve()]


def test_un_mecanisme_inconnu_ou_mal_forme_est_refuse_au_chargement() -> None:
    with pytest.raises(DeploymentBindingError, match="unsupported"):
        load_selected_release_registry(ReleaseAuthoritySelection("AUTRE", ((WAVE0, _sha(WAVE0)),)))
    with pytest.raises(DeploymentBindingError, match="exactly one file"):
        load_selected_release_registry(
            ReleaseAuthoritySelection(RELEASE_AUTHORITY_REGISTRY_FILE, ((REGISTRY, _sha(REGISTRY)), (REGISTRY, _sha(REGISTRY))))
        )
