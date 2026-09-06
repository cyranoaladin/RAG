"""L'ensemble des contenus promus est celui que la lignée ACTIVE sert.

Ce script part du registre canonique — l'autorité qui désigne les releases
actives — et non d'un manifeste historique nommé en dur : le corpus complet
produira une candidate bien plus large, et C1 ne doit pas être réécrit pour
autant.

Ce que ces épreuves refusent : qu'un maillon de la chaîne puisse être vide,
tronqué, déscellé ou hors périmètre sans que le gate le dise. Un ensemble
promu vide traverserait le contrôle de couverture en publiant « 0 manquant »,
puisqu'il ne manque alors jamais de rien.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compute_promoted_content_set import (  # noqa: E402
    PromotedContentSetError,
    collect_promoted_content_set,
    main,
)
from verify_corpus_cas import content_set_digest  # noqa: E402

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_SHARED = "c" * 64


def _sceau(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _gouverne(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Fait de `tmp_path` la racine gouvernée pour l'épreuve."""
    import compute_promoted_content_set as module

    monkeypatch.setattr(module, "GOVERNED_ROOT", tmp_path)


@pytest.fixture(autouse=True)
def _racine_gouvernee(request: pytest.FixtureRequest) -> None:
    """Sauf mention contraire, la racine gouvernée est le `tmp_path` du test."""
    if "tmp_path" not in request.fixturenames:
        return
    if request.node.get_closest_marker("racine_propre"):
        return
    _gouverne(request.getfixturevalue("monkeypatch"), request.getfixturevalue("tmp_path"))


def _seed(
    tmp_path: Path,
    *,
    occurrences: int | None = 4,
    sujets: list[str] | None = None,
    releases_vides: bool = False,
) -> Path:
    """Une chaîne d'autorité COMPLÈTE : registre, release scellée, sujets scellés."""
    base = tmp_path / "prerentree_2026_2027"
    noms = ["sujet-a", "sujet-b"] if sujets is None else sujets
    contenus = {"sujet-a": [SHA_A, SHA_SHARED], "sujet-b": [SHA_B, SHA_SHARED]}
    entrees = []
    for nom in noms:
        chemin = _write(
            base / "profile_gate" / "subjects" / f"{nom}.release.json",
            {
                "collection": nom,
                "expected_counts": {"artifacts": len(contenus[nom])},
                "artifacts": [{"content_sha256": s} for s in contenus[nom]],
            },
        )
        entrees.append(
            {
                "collection": nom,
                "path": f"subjects/{nom}.release.json",
                "sha256": _sceau(chemin),
            }
        )
    release = _write(
        base / "profile_gate" / "production.release.json",
        {
            "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V1",
            "expected_counts": {"artifacts": occurrences},
            "subjects": entrees,
        },
    )
    registre = _write(
        base / "release-registry.json",
        {
            "registry_version": "1",
            "school_year": "2026-2027",
            "releases": []
            if releases_vides
            else [
                {
                    "release_id": "epreuve-v1",
                    "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V1",
                    "collections": noms,
                    "manifest_path": "profile_gate/production.release.json",
                    "expected_manifest_sha256": _sceau(release),
                }
            ],
        },
    )
    return registre


# --- la chaîne nominale ------------------------------------------------


def test_collecte_les_contenus_de_toutes_les_releases_actives(tmp_path: Path) -> None:
    assert collect_promoted_content_set(_seed(tmp_path)) == {SHA_A, SHA_B, SHA_SHARED}


def test_un_contenu_partage_par_deux_sujets_n_est_pas_compte_deux_fois(
    tmp_path: Path,
) -> None:
    """Un contenu référencé par plusieurs sujets compte UNE fois.

    Deux sujets de deux artefacts chacun, dont un partagé : quatre occurrences
    pour trois contenus distincts. Les chiffres de production — 486 pour 319 —
    sont mesurés sur le corpus réel et consignés au rapport de lot ; c'est la
    PROPRIÉTÉ qui est éprouvée ici, pas leur valeur.
    """
    assert len(collect_promoted_content_set(_seed(tmp_path))) == 3


def test_main_ecrit_l_ensemble_et_la_meme_formule_d_empreinte_que_le_verificateur(
    tmp_path: Path,
) -> None:
    registre = _seed(tmp_path)
    sortie = tmp_path / "promoted.json"
    assert main(["--release-registry", str(registre), "--output", str(sortie)]) == 0
    rendu = json.loads(sortie.read_text(encoding="utf-8"))
    assert rendu["count"] == 3
    assert rendu["content_set_sha256"] == content_set_digest({SHA_A, SHA_B, SHA_SHARED})


# --- ce que chaque sceau doit démontrer --------------------------------


def test_un_manifeste_de_sujet_qui_a_derive_de_son_sceau_est_refuse(
    tmp_path: Path,
) -> None:
    registre = _seed(tmp_path)
    _write(
        registre.parent / "profile_gate" / "subjects" / "sujet-a.release.json",
        {"expected_counts": {"artifacts": 1}, "artifacts": [{"content_sha256": SHA_A}]},
    )
    with pytest.raises(PromotedContentSetError, match="l'autorité déclare"):
        collect_promoted_content_set(registre)


def test_un_manifeste_de_release_qui_a_derive_de_son_sceau_est_refuse(
    tmp_path: Path,
) -> None:
    """Le registre scelle la release : sans cette confrontation, une release
    réécrite changerait l'ensemble servi sans changer le registre qu'on lit."""
    registre = _seed(tmp_path)
    manifeste = registre.parent / "profile_gate" / "production.release.json"
    donnees = json.loads(manifeste.read_text(encoding="utf-8"))
    donnees["expected_counts"]["artifacts"] = 99
    _write(manifeste, donnees)
    with pytest.raises(PromotedContentSetError, match="l'autorité déclare"):
        collect_promoted_content_set(registre)


# --- le vide, à tous les étages ----------------------------------------


def test_un_registre_sans_release_active_est_refuse(tmp_path: Path) -> None:
    with pytest.raises(PromotedContentSetError, match="aucune release active"):
        collect_promoted_content_set(_seed(tmp_path, releases_vides=True))


def test_une_release_sans_sujet_est_refusee(tmp_path: Path) -> None:
    base = tmp_path / "prerentree_2026_2027"
    release = _write(
        base / "profile_gate" / "production.release.json",
        {"release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V1", "expected_counts": {"artifacts": 4}, "subjects": []},
    )
    registre = _write(
        base / "release-registry.json",
        {
            "releases": [
                {
                    "release_id": "vide",
                    "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V1",
                    "manifest_path": "profile_gate/production.release.json",
                    "expected_manifest_sha256": _sceau(release),
                }
            ]
        },
    )
    with pytest.raises(PromotedContentSetError, match="aucun sujet"):
        collect_promoted_content_set(registre)


def test_un_sujet_sans_artefact_est_refuse(tmp_path: Path) -> None:
    base = tmp_path / "prerentree_2026_2027"
    sujet = _write(
        base / "profile_gate" / "subjects" / "vide.release.json",
        {"expected_counts": {"artifacts": 1}, "artifacts": []},
    )
    release = _write(
        base / "profile_gate" / "production.release.json",
        {
            "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V1",
            "expected_counts": {"artifacts": 1},
            "subjects": [
                {"collection": "vide", "path": "subjects/vide.release.json", "sha256": _sceau(sujet)}
            ],
        },
    )
    registre = _write(
        base / "release-registry.json",
        {
            "releases": [
                {
                    "release_id": "r",
                    "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V1",
                    "collections": ["vide"],
                    "manifest_path": "profile_gate/production.release.json",
                    "expected_manifest_sha256": _sceau(release),
                }
            ]
        },
    )
    with pytest.raises(PromotedContentSetError, match="aucun artefact"):
        collect_promoted_content_set(registre)


# --- le compte déclaré est obligatoire ---------------------------------


def test_une_lecture_tronquee_est_visible_par_les_occurrences_declarees(
    tmp_path: Path,
) -> None:
    """Un ensemble DÉDUPLIQUÉ plus petit est indiscernable d'une lecture
    tronquée : seule la comparaison des OCCURRENCES la rend visible."""
    with pytest.raises(PromotedContentSetError, match="contre 9 déclarées"):
        collect_promoted_content_set(_seed(tmp_path, occurrences=9))


@pytest.mark.parametrize("valeur", [None, "4", 0, -1, True])
def test_un_compte_d_occurrences_absent_ou_illisible_est_refuse(
    tmp_path: Path, valeur: object
) -> None:
    """Le tolérer absent désactivait silencieusement le seul contrôle capable
    de distinguer une troncature d'une déduplication légitime."""
    registre = _seed(tmp_path)
    manifeste = registre.parent / "profile_gate" / "production.release.json"
    donnees = json.loads(manifeste.read_text(encoding="utf-8"))
    if valeur is None:
        donnees.pop("expected_counts")
    else:
        donnees["expected_counts"]["artifacts"] = valeur
    _write(manifeste, donnees)
    registre_donnees = json.loads(registre.read_text(encoding="utf-8"))
    registre_donnees["releases"][0]["expected_manifest_sha256"] = _sceau(manifeste)
    _write(registre, registre_donnees)
    with pytest.raises(PromotedContentSetError, match="expected_counts"):
        collect_promoted_content_set(registre)


# --- le périmètre gouverné ---------------------------------------------


@pytest.mark.racine_propre
def test_un_chemin_qui_sort_de_la_racine_gouvernee_est_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le SHA correct d'un fichier HORS périmètre ne prouve rien du corpus
    gouverné : il prouve qu'on a bien lu le fichier qu'on a désigné."""
    import compute_promoted_content_set as module

    racine = tmp_path / "gouverne"
    base = racine / "prerentree_2026_2027"
    base.mkdir(parents=True)
    monkeypatch.setattr(module, "GOVERNED_ROOT", racine)

    dehors = _write(tmp_path / "dehors" / "release.json", {"release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V1", "subjects": []})
    registre = _write(
        base / "release-registry.json",
        {
            "releases": [
                {
                    "release_id": "evade",
                    "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V1",
                    "manifest_path": "../../dehors/release.json",
                    "expected_manifest_sha256": _sceau(dehors),
                }
            ]
        },
    )
    with pytest.raises(PromotedContentSetError, match="hors de la racine gouvernée"):
        module.collect_promoted_content_set(registre)


# --- un manifeste malformé échoue proprement ---------------------------


def test_un_manifeste_illisible_rend_un_code_nomme_pas_une_trace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registre = tmp_path / "release-registry.json"
    registre.write_text("{ ceci n'est pas du JSON", encoding="utf-8")
    assert main(["--release-registry", str(registre), "--output", str(tmp_path / "o.json")]) == 2
    assert "PROMOTED_CONTENT_SET_INVALID" in capsys.readouterr().err


# --- l'autorité d'entrée est elle-même bornée --------------------------


@pytest.mark.racine_propre
def test_un_registre_hors_de_la_racine_gouvernee_est_refuse(tmp_path: Path) -> None:
    """Une autorité d'entrée extérieure au périmètre qu'elle prétend gouverner
    ne le gouverne pas. Un faux registre dont toutes les empreintes seraient
    cohérentes prouverait seulement qu'on a bien lu le fichier désigné."""
    registre = _seed(tmp_path)
    with pytest.raises(PromotedContentSetError, match="hors de la racine gouvernée"):
        collect_promoted_content_set(registre)


@pytest.mark.racine_propre
def test_un_composant_en_lien_symbolique_interne_est_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le garde symlink, éprouvé sur le cas qu'il est SEUL à attraper.

    Un lien vers l'extérieur est déjà refusé par la borne « le chemin résolu
    est dans la racine ». Un lien INTERNE ne l'est pas : la résolution reste
    à l'intérieur, et seule l'inspection de chaque composant le voit. Retirer
    cette inspection rend cette épreuve rouge — c'est ce qui en fait une
    épreuve du garde, et non de la borne voisine.
    """
    import compute_promoted_content_set as module

    racine = tmp_path / "gouverne"
    racine.mkdir()
    monkeypatch.setattr(module, "GOVERNED_ROOT", racine)

    reel = _seed(racine)
    assert module.collect_promoted_content_set(reel), "le chemin direct doit passer"

    # `gouverne/alias` → `gouverne/prerentree_2026_2027`. Tout reste DANS la
    # racine ; le sceau du fichier atteint est parfaitement correct.
    (racine / "alias").symlink_to(reel.parent, target_is_directory=True)
    par_le_lien = racine / "alias" / reel.name
    assert par_le_lien.resolve() == reel.resolve()

    with pytest.raises(PromotedContentSetError, match="lien symbolique"):
        module.collect_promoted_content_set(par_le_lien)


# --- JSON valide, type faux --------------------------------------------


@pytest.mark.parametrize("charge", ["[]", '"registry"', "42", "null"])
@pytest.mark.racine_propre
def test_un_registre_de_type_inattendu_est_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, charge: str
) -> None:
    """Un JSON parfaitement valide peut n'être pas un objet. Appeler `.get()`
    dessus rendrait une trace là où le gate doit nommer le défaut."""
    import compute_promoted_content_set as module

    racine = tmp_path / "gouverne"
    (racine / "prerentree_2026_2027").mkdir(parents=True)
    monkeypatch.setattr(module, "GOVERNED_ROOT", racine)
    registre = racine / "prerentree_2026_2027" / "release-registry.json"
    registre.write_text(charge, encoding="utf-8")

    with pytest.raises(PromotedContentSetError, match="pas un objet"):
        module.collect_promoted_content_set(registre)


@pytest.mark.parametrize("charge", ["[]", '"release"', "7"])
@pytest.mark.racine_propre
def test_un_manifeste_de_release_de_type_inattendu_est_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, charge: str
) -> None:
    import compute_promoted_content_set as module

    racine = tmp_path / "gouverne"
    base = racine / "prerentree_2026_2027"
    base.mkdir(parents=True)
    monkeypatch.setattr(module, "GOVERNED_ROOT", racine)
    manifeste = base / "release.json"
    manifeste.write_text(charge, encoding="utf-8")
    registre = _write(
        base / "release-registry.json",
        {
            "releases": [
                {
                    "release_id": "r",
                    "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V1",
                    "manifest_path": "release.json",
                    "expected_manifest_sha256": _sceau(manifeste),
                }
            ]
        },
    )
    with pytest.raises(PromotedContentSetError, match="pas un objet"):
        module.collect_promoted_content_set(registre)


@pytest.mark.parametrize("entree", ["[]", '"r"', "3"])
@pytest.mark.racine_propre
def test_une_entree_de_release_de_type_inattendu_est_refusee(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entree: str
) -> None:
    import compute_promoted_content_set as module
    import json as _json

    racine = tmp_path / "gouverne"
    base = racine / "prerentree_2026_2027"
    base.mkdir(parents=True)
    monkeypatch.setattr(module, "GOVERNED_ROOT", racine)
    registre = base / "release-registry.json"
    registre.write_text(
        _json.dumps({"releases": [_json.loads(entree)]}), encoding="utf-8"
    )
    with pytest.raises(PromotedContentSetError, match="pas un objet"):
        module.collect_promoted_content_set(registre)


@pytest.mark.parametrize(
    "empreinte", [None, 42, "", "pas-un-sha", "A" * 64, "g" * 64, "a" * 63]
)
def test_un_content_sha256_qui_n_en_est_pas_un_est_refuse(
    tmp_path: Path, empreinte: object
) -> None:
    """`str()` d'une valeur quelconque deviendrait un identifiant promu, que
    le store ne pourrait par construction jamais contenir : la couverture
    échouerait plus tard, sur un défaut dont l'origine serait perdue."""
    registre = _seed(tmp_path)
    sujet = registre.parent / "profile_gate" / "subjects" / "sujet-a.release.json"
    _write(
        sujet,
        {
            "expected_counts": {"artifacts": 2},
            "artifacts": [{"content_sha256": empreinte}, {"content_sha256": SHA_SHARED}],
        },
    )
    manifeste = registre.parent / "profile_gate" / "production.release.json"
    donnees = json.loads(manifeste.read_text(encoding="utf-8"))
    donnees["subjects"][0]["sha256"] = _sceau(sujet)
    _write(manifeste, donnees)
    reg = json.loads(registre.read_text(encoding="utf-8"))
    reg["releases"][0]["expected_manifest_sha256"] = _sceau(manifeste)
    _write(registre, reg)

    with pytest.raises(PromotedContentSetError, match="content_sha256 invalide"):
        collect_promoted_content_set(registre)


# --- les deux formes de release ----------------------------------------


def _sujets_v2(base: Path, sceau_registre: str) -> list[dict]:
    """Un sujet V2 place les artefacts que le registre porte."""
    sujet = _write(
        base / "profile_gate" / "subjects" / "sujet-v2.release.json",
        {
            "collection": "sujet-v2",
            "artifact_registry": {
                "path": "../artifacts.release.json",
                "sha256": sceau_registre,
            },
            "expected_counts": {"placements": 3, "unique_artifact_references": 3},
            "placements": [
                {"artifact_id": s} for s in (SHA_A, SHA_B, SHA_SHARED)
            ],
        },
    )
    return [
        {
            "collection": "sujet-v2",
            "path": "subjects/sujet-v2.release.json",
            "sha256": _sceau(sujet),
        }
    ]


def _seed_v2(
    tmp_path: Path, *, uniques: int | None = 3, propre: int | None = None
) -> Path:
    """Une lignée V2 : registre d'artefacts SCELLÉ, et sujets qui placent."""
    base = tmp_path / "prerentree_2026_2027"
    artefacts = _write(
        base / "profile_gate" / "artifacts.release.json",
        {
            "release_kind": "MULTILEVEL_ARTIFACT_REGISTRY_V2",
            "expected_counts": {"unique_artifacts": propre if propre is not None else 3},
            "artifacts": [{"content_sha256": s} for s in (SHA_A, SHA_B, SHA_SHARED)],
        },
    )
    release = _write(
        base / "profile_gate" / "production.release.json",
        {
            "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V2",
            "expected_counts": {
                "unique_artifacts": uniques,
                "subjects": 1,
                "placements": 3,
            },
            "artifact_registry": {
                "path": "artifacts.release.json",
                "sha256": _sceau(artefacts),
            },
            "subjects": _sujets_v2(base, _sceau(artefacts)),
        },
    )
    return _write(
        base / "release-registry.json",
        {
            "releases": [
                {
                    "release_id": "v2",
                    "collections": ["sujet-v2"],
                    "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V2",
                    "manifest_path": "profile_gate/production.release.json",
                    "expected_manifest_sha256": _sceau(release),
                }
            ]
        },
    )


def test_une_release_v2_est_lue_par_son_registre_d_artefacts(tmp_path: Path) -> None:
    """La candidate complète emploiera cette forme. N'en connaître qu'une
    obligerait à réécrire ce gate au moment précis où il doit servir."""
    assert collect_promoted_content_set(_seed_v2(tmp_path)) == {
        SHA_A,
        SHA_B,
        SHA_SHARED,
    }


def test_le_registre_d_artefacts_v2_est_confronte_a_son_sceau(tmp_path: Path) -> None:
    registre = _seed_v2(tmp_path)
    _write(
        registre.parent / "profile_gate" / "artifacts.release.json",
        {"expected_counts": {"artifacts": 1}, "artifacts": [{"content_sha256": SHA_A}]},
    )
    with pytest.raises(PromotedContentSetError, match="l'autorité déclare"):
        collect_promoted_content_set(registre)


def test_un_compte_v2_de_l_agregat_qui_ne_correspond_pas_est_refuse(
    tmp_path: Path,
) -> None:
    with pytest.raises(PromotedContentSetError, match="déclarés par l'agrégat"):
        collect_promoted_content_set(_seed_v2(tmp_path, uniques=9))


def test_le_registre_d_artefacts_v2_doit_tenir_son_PROPRE_compte(
    tmp_path: Path,
) -> None:
    """Ne confronter qu'au compte de l'agrégat laissait passer un registre
    tronqué dont on aurait rescellé l'agrégat : les deux comptes doivent
    tomber juste, faute de quoi l'un des deux ment."""
    with pytest.raises(PromotedContentSetError, match="qu'il déclare"):
        collect_promoted_content_set(_seed_v2(tmp_path, propre=9))


def test_une_nature_de_release_annoncee_et_dementie_est_refusee(
    tmp_path: Path,
) -> None:
    """Le registre DÉCLARE la nature de chaque release. Se fier au seul
    manifeste laisserait une lignée dont le registre annonce V1 et dont le
    fichier est V2 produire un ensemble que le runtime, lui, refusera."""
    registre = _seed_v2(tmp_path)
    donnees = json.loads(registre.read_text(encoding="utf-8"))
    donnees["releases"][0]["release_kind"] = "MULTILEVEL_AGGREGATE_RELEASE_V1"
    _write(registre, donnees)
    with pytest.raises(PromotedContentSetError, match="le registre annonce"):
        collect_promoted_content_set(registre)


def test_une_nature_de_manifeste_qui_dement_le_registre_est_refusee(
    tmp_path: Path,
) -> None:
    """Le registre déclare V2 et le manifeste porte autre chose : refus.

    Le lire d'office dans l'une des formes connues rendrait un ensemble faux
    au lieu d'un refus — et l'ensemble de couverture ainsi produit serait
    rejeté par le runtime, bien plus tard.
    """
    registre = _seed_v2(tmp_path)
    manifeste = registre.parent / "profile_gate" / "production.release.json"
    donnees = json.loads(manifeste.read_text(encoding="utf-8"))
    donnees["release_kind"] = "MULTILEVEL_AGGREGATE_RELEASE_V9"
    _write(manifeste, donnees)
    reg = json.loads(registre.read_text(encoding="utf-8"))
    reg["releases"][0]["expected_manifest_sha256"] = _sceau(manifeste)
    _write(registre, reg)
    with pytest.raises(PromotedContentSetError, match="le registre annonce"):
        collect_promoted_content_set(registre)


def test_le_dispatch_refuse_une_nature_inconnue_meme_appele_directement(
    tmp_path: Path,
) -> None:
    """Défense en profondeur : la garde du registre attrape ce cas en amont,
    mais le dispatch ne doit pas pour autant supposer son appelant."""
    import compute_promoted_content_set as module

    with pytest.raises(PromotedContentSetError, match="release_kind inconnu"):
        module._contenus_dune_release(
            {"release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V9"},
            tmp_path / "x.json",
            "essai",
        )


@pytest.mark.racine_propre
def test_chaque_lignee_reelle_du_depot_est_lisible_et_coherente() -> None:
    """Toutes les lignées versionnées sont lues, quelle que soit leur forme.

    Deux pièges évités. Nommer en dur le répertoire haché d'une répétition
    ferait taire l'épreuve à la répétition suivante — un `skip` silencieux est
    la manière dont une corroboration cesse d'exister sans que personne ne le
    voie. Et comparer la V1 promue à une candidate de répétition ferait échouer
    l'épreuve sur une divergence LÉGITIME de contenu, sans aucun défaut de
    code : ce sont deux jeux qui évoluent séparément.

    Ce qui est donc éprouvé est la propriété qui vaut pour toutes : chaque
    registre versionné se lit de bout en bout, ses sceaux tombent juste, ses
    comptes déclarés correspondent, et il rend un ensemble non vide.
    """
    racine = (
        Path(__file__).resolve().parents[3]
        / "services"
        / "rag-pedago"
        / "data"
        / "releases"
    )
    registres = sorted(racine.rglob("release-registry.json"))
    assert registres, "aucune lignée versionnée : la corroboration n'aurait pas lieu"

    for registre in registres:
        contenus = collect_promoted_content_set(registre)
        assert contenus, registre.as_posix()
        assert all(_est_un_sha256(sha) for sha in contenus), registre.as_posix()


def _est_un_sha256(valeur: str) -> bool:
    return len(valeur) == 64 and all(c in "0123456789abcdef" for c in valeur)


@pytest.mark.parametrize("annonce", [None, "", "MULTILEVEL_AGGREGATE_RELEASE_V9"])
def test_un_registre_sans_release_kind_connu_est_refuse(
    tmp_path: Path, annonce: object
) -> None:
    """La déclaration côté REGISTRE est obligatoire. La rendre facultative
    laissait le manifeste choisir seul son lecteur — et faisait disparaître le
    contrôle croisé précisément sur les registres tronqués ou malformés."""
    registre = _seed(tmp_path)
    donnees = json.loads(registre.read_text(encoding="utf-8"))
    if annonce is None:
        donnees["releases"][0].pop("release_kind")
    else:
        donnees["releases"][0]["release_kind"] = annonce
    _write(registre, donnees)
    with pytest.raises(PromotedContentSetError, match="release_kind connu"):
        collect_promoted_content_set(registre)


def test_deux_erreurs_de_sujet_qui_se_compensent_sont_refusees(tmp_path: Path) -> None:
    """Le total de l'agrégat ne suffit pas.

    Un sujet tronqué et un autre porteur d'un doublon rendent la MÊME somme.
    Ici sujet-a perd `SHA_A`, qui n'appartient qu'à lui : l'ensemble dédupliqué
    passe donc de trois contenus à deux, sur un total d'occurrences inchangé.
    La couverture CAS passerait alors sur un périmètre incomplet, et le seul
    compte de l'agrégat ne le verrait pas.
    """
    registre = _seed(tmp_path)
    profil = registre.parent / "profile_gate"
    # sujet-a perd un artefact, sujet-b en gagne un doublon : 4 occurrences
    # au total dans les deux cas.
    a = _write(
        profil / "subjects" / "sujet-a.release.json",
        # SHA_A n'appartient qu'à sujet-a : le perdre RÉTRÉCIT l'ensemble
        # dédupliqué, ce que le seul total d'occurrences ne voit pas.
        {
            "expected_counts": {"artifacts": 2},
            "artifacts": [{"content_sha256": SHA_SHARED}],
        },
    )
    b = _write(
        profil / "subjects" / "sujet-b.release.json",
        {
            "expected_counts": {"artifacts": 2},
            "artifacts": [
                {"content_sha256": SHA_B},
                {"content_sha256": SHA_SHARED},
                {"content_sha256": SHA_SHARED},
            ],
        },
    )
    manifeste = profil / "production.release.json"
    donnees = json.loads(manifeste.read_text(encoding="utf-8"))
    donnees["subjects"][0]["sha256"] = _sceau(a)
    donnees["subjects"][1]["sha256"] = _sceau(b)
    _write(manifeste, donnees)
    reg = json.loads(registre.read_text(encoding="utf-8"))
    reg["releases"][0]["expected_manifest_sha256"] = _sceau(manifeste)
    _write(registre, reg)

    with pytest.raises(PromotedContentSetError, match="qu'il déclare"):
        collect_promoted_content_set(registre)


# --- le registre est l'autorité du périmètre servi ---------------------


def test_une_release_amputee_d_un_sujet_est_refusee_par_les_collections(
    tmp_path: Path,
) -> None:
    """Comptes et sceaux refaits ne suffisent pas.

    Le registre déclare les collections que la release SERT. Sans cette
    confrontation, une release amputée d'un sujet était acceptée alors que
    l'autorité continue de déclarer la collection disparue active : l'ensemble
    promu rétrécissait sur un périmètre toujours servi.
    """
    registre = _seed(tmp_path)
    manifeste = registre.parent / "profile_gate" / "production.release.json"
    donnees = json.loads(manifeste.read_text(encoding="utf-8"))
    donnees["subjects"] = donnees["subjects"][:1]
    donnees["expected_counts"]["artifacts"] = 2
    _write(manifeste, donnees)
    reg = json.loads(registre.read_text(encoding="utf-8"))
    reg["releases"][0]["expected_manifest_sha256"] = _sceau(manifeste)
    _write(registre, reg)

    with pytest.raises(PromotedContentSetError, match="collection"):
        collect_promoted_content_set(registre)


def test_un_sujet_v2_qui_suppose_un_autre_registre_d_artefacts_est_refuse(
    tmp_path: Path,
) -> None:
    """Le registre d'artefacts et l'agrégat peuvent être rescellés ensemble
    sur un ensemble amputé ; les sujets, eux, continuent de déclarer l'ancien
    sceau. Ne pas les lire laissait passer un ensemble plus petit que le
    périmètre servi."""
    registre = _seed_v2(tmp_path)
    profil = registre.parent / "profile_gate"
    sujet = profil / "subjects" / "sujet-v2.release.json"
    donnees = json.loads(sujet.read_text(encoding="utf-8"))
    donnees["artifact_registry"]["sha256"] = "0" * 64
    _write(sujet, donnees)
    manifeste = profil / "production.release.json"
    agr = json.loads(manifeste.read_text(encoding="utf-8"))
    agr["subjects"][0]["sha256"] = _sceau(sujet)
    _write(manifeste, agr)
    reg = json.loads(registre.read_text(encoding="utf-8"))
    reg["releases"][0]["expected_manifest_sha256"] = _sceau(manifeste)
    _write(registre, reg)

    with pytest.raises(PromotedContentSetError, match="suppose le registre"):
        collect_promoted_content_set(registre)


def test_un_artefact_place_mais_absent_du_registre_v2_est_refuse(
    tmp_path: Path,
) -> None:
    """Un sujet qui place un artefact que le registre ne porte plus signale
    que l'un des deux a été amputé."""
    registre = _seed_v2(tmp_path)
    profil = registre.parent / "profile_gate"
    sujet = profil / "subjects" / "sujet-v2.release.json"
    donnees = json.loads(sujet.read_text(encoding="utf-8"))
    donnees["placements"].append({"artifact_id": "d" * 64})
    donnees["expected_counts"]["placements"] = 4
    donnees["expected_counts"]["unique_artifact_references"] = 4
    _write(sujet, donnees)
    manifeste = profil / "production.release.json"
    agr = json.loads(manifeste.read_text(encoding="utf-8"))
    agr["expected_counts"]["placements"] = 4
    agr["subjects"][0]["sha256"] = _sceau(sujet)
    _write(manifeste, agr)
    reg = json.loads(registre.read_text(encoding="utf-8"))
    reg["releases"][0]["expected_manifest_sha256"] = _sceau(manifeste)
    _write(registre, reg)

    with pytest.raises(PromotedContentSetError, match="absent"):
        collect_promoted_content_set(registre)


@pytest.mark.parametrize("declarees", [None, [], "rag_nexus", 7])
def test_un_registre_sans_collections_declarees_est_refuse(
    tmp_path: Path, declarees: object
) -> None:
    """Obligatoire, comme `release_kind`.

    Une déclaration facultative ne garde rien : elle disparaîtrait précisément
    sur le registre tronqué qu'elle doit attraper, et le périmètre servi ne
    serait alors confronté à rien.
    """
    registre = _seed(tmp_path)
    donnees = json.loads(registre.read_text(encoding="utf-8"))
    if declarees is None:
        donnees["releases"][0].pop("collections")
    else:
        donnees["releases"][0]["collections"] = declarees
    _write(registre, donnees)
    with pytest.raises(PromotedContentSetError, match="aucune collection"):
        collect_promoted_content_set(registre)


def test_le_total_de_placements_declare_par_l_agregat_v2_est_confronte(
    tmp_path: Path,
) -> None:
    """L'agrégat déclare le total de placements que la release sert, et c'est
    l'autorité que le producteur enregistre. Ne vérifier que les comptes
    locaux laissait ce total mentir sans conséquence."""
    registre = _seed_v2(tmp_path)
    manifeste = registre.parent / "profile_gate" / "production.release.json"
    donnees = json.loads(manifeste.read_text(encoding="utf-8"))
    donnees["expected_counts"]["placements"] = 999
    _write(manifeste, donnees)
    reg = json.loads(registre.read_text(encoding="utf-8"))
    reg["releases"][0]["expected_manifest_sha256"] = _sceau(manifeste)
    _write(registre, reg)
    with pytest.raises(PromotedContentSetError, match="déclarés par l'agrégat"):
        collect_promoted_content_set(registre)


def test_le_nombre_de_sujets_declare_par_l_agregat_v2_est_confronte(
    tmp_path: Path,
) -> None:
    registre = _seed_v2(tmp_path)
    manifeste = registre.parent / "profile_gate" / "production.release.json"
    donnees = json.loads(manifeste.read_text(encoding="utf-8"))
    donnees["expected_counts"]["subjects"] = 11
    _write(manifeste, donnees)
    reg = json.loads(registre.read_text(encoding="utf-8"))
    reg["releases"][0]["expected_manifest_sha256"] = _sceau(manifeste)
    _write(registre, reg)
    with pytest.raises(PromotedContentSetError, match="sujet\\(s\\) portés contre"):
        collect_promoted_content_set(registre)


def test_un_sujet_v2_qui_remplace_un_artefact_par_des_doublons_est_refuse(
    tmp_path: Path,
) -> None:
    """Le défaut que seul `unique_artifact_references` attrape.

    Retirer un artefact et remplacer ses placements par des doublons d'un
    autre préserve TOUS les totaux vérifiés — le compte local de placements
    comme celui de l'agrégat — et rétrécit pourtant l'ensemble promu.
    """
    registre = _seed_v2(tmp_path)
    profil = registre.parent / "profile_gate"
    sujet = profil / "subjects" / "sujet-v2.release.json"
    donnees = json.loads(sujet.read_text(encoding="utf-8"))
    # SHA_A disparaît, remplacé par un doublon de SHA_B : trois placements
    # toujours, mais deux artefacts distincts au lieu de trois.
    donnees["placements"] = [
        {"artifact_id": SHA_B},
        {"artifact_id": SHA_B},
        {"artifact_id": SHA_SHARED},
    ]
    _write(sujet, donnees)
    manifeste = profil / "production.release.json"
    agr = json.loads(manifeste.read_text(encoding="utf-8"))
    agr["subjects"][0]["sha256"] = _sceau(sujet)
    _write(manifeste, agr)
    reg = json.loads(registre.read_text(encoding="utf-8"))
    reg["releases"][0]["expected_manifest_sha256"] = _sceau(manifeste)
    _write(registre, reg)

    with pytest.raises(PromotedContentSetError, match="distinct\\(s\\) référencé"):
        collect_promoted_content_set(registre)


def test_un_sujet_v1_qui_reference_deux_fois_le_meme_contenu_est_refuse(
    tmp_path: Path,
) -> None:
    """Un sujet V1 ne déclare pas de compte de contenus DISTINCTS.

    Sans cette garde, remplacer un artefact unique par un doublon d'un autre
    préserve le compte du sujet ET celui de l'agrégat, tandis que l'ensemble
    promu rétrécit en silence. Vérifié sur la lignée réelle : aucun sujet ne
    porte de doublon interne, la garde ne rejette donc rien de légitime.
    """
    registre = _seed(tmp_path)
    profil = registre.parent / "profile_gate"
    sujet = _write(
        profil / "subjects" / "sujet-a.release.json",
        {
            "collection": "sujet-a",
            "expected_counts": {"artifacts": 2},
            "artifacts": [
                {"content_sha256": SHA_SHARED},
                {"content_sha256": SHA_SHARED},
            ],
        },
    )
    manifeste = profil / "production.release.json"
    donnees = json.loads(manifeste.read_text(encoding="utf-8"))
    donnees["subjects"][0]["sha256"] = _sceau(sujet)
    _write(manifeste, donnees)
    reg = json.loads(registre.read_text(encoding="utf-8"))
    reg["releases"][0]["expected_manifest_sha256"] = _sceau(manifeste)
    _write(registre, reg)

    with pytest.raises(PromotedContentSetError, match="contenu\\(s\\) distinct"):
        collect_promoted_content_set(registre)


def test_un_descripteur_qui_pointe_le_manifeste_d_une_autre_collection_est_refuse(
    tmp_path: Path,
) -> None:
    """Le descripteur annonce la collection ; le manifeste la déclare.

    Ne pas les lier laissait deux descripteurs pointer le MÊME manifeste :
    l'ensemble des collections restait complet en apparence, et un périmètre
    était servi deux fois pendant qu'un autre disparaissait.
    """
    registre = _seed(tmp_path)
    manifeste = registre.parent / "profile_gate" / "production.release.json"
    donnees = json.loads(manifeste.read_text(encoding="utf-8"))
    # sujet-b pointe désormais le manifeste de sujet-a.
    donnees["subjects"][1]["path"] = donnees["subjects"][0]["path"]
    donnees["subjects"][1]["sha256"] = donnees["subjects"][0]["sha256"]
    _write(manifeste, donnees)
    reg = json.loads(registre.read_text(encoding="utf-8"))
    reg["releases"][0]["expected_manifest_sha256"] = _sceau(manifeste)
    _write(registre, reg)

    with pytest.raises(PromotedContentSetError, match="le descripteur annonce"):
        collect_promoted_content_set(registre)
