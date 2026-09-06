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
            {"artifacts": [{"content_sha256": s} for s in contenus[nom]]},
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
        {"expected_counts": {"artifacts": occurrences}, "subjects": entrees},
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
    """486 occurrences pour 319 contenus distincts : la déduplication est ce
    que la PR #146 a légitimé."""
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
        {"artifacts": [{"content_sha256": SHA_A}]},
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
        {"expected_counts": {"artifacts": 4}, "subjects": []},
    )
    registre = _write(
        base / "release-registry.json",
        {
            "releases": [
                {
                    "release_id": "vide",
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
    sujet = _write(base / "profile_gate" / "subjects" / "vide.release.json", {"artifacts": []})
    release = _write(
        base / "profile_gate" / "production.release.json",
        {
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


def test_un_chemin_qui_sort_de_la_racine_gouvernee_est_refuse(tmp_path: Path) -> None:
    """Le SHA correct d'un fichier HORS périmètre ne prouve rien du corpus
    gouverné : il prouve qu'on a bien lu le fichier qu'on a désigné."""
    dehors = _write(tmp_path / "dehors" / "release.json", {"subjects": []})
    base = tmp_path / "prerentree_2026_2027"
    registre = _write(
        base / "release-registry.json",
        {
            "releases": [
                {
                    "release_id": "evade",
                    "manifest_path": "../dehors/release.json",
                    "expected_manifest_sha256": _sceau(dehors),
                }
            ]
        },
    )
    with pytest.raises(PromotedContentSetError, match="hors de la racine gouvernée"):
        collect_promoted_content_set(registre)


# --- un manifeste malformé échoue proprement ---------------------------


def test_un_manifeste_illisible_rend_un_code_nomme_pas_une_trace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registre = tmp_path / "release-registry.json"
    registre.write_text("{ ceci n'est pas du JSON", encoding="utf-8")
    assert main(["--release-registry", str(registre), "--output", str(tmp_path / "o.json")]) == 2
    assert "PROMOTED_CONTENT_SET_INVALID" in capsys.readouterr().err
