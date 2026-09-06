"""L'ensemble promu est celui que le RUNTIME lit, jamais une seconde lecture.

Ce module ne décide plus rien de la structure des releases : natures
supportées, sceaux, comptes, autorités, partitions de pages et collisions
appartiennent à `nexus_release_chain.release_readiness`, que le runtime de
production consomme déjà. Le réimplémenter produisait un second runtime —
chaque règle omise devenait un faux vert, chaque règle ajoutée en amont
demandait d'être redécouverte ici.

Ces épreuves portent donc sur les deux seules choses qui restent propres à
C1 : le bornage de l'autorité d'entrée, et l'absence de divergence avec le
chargeur canonique.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compute_promoted_content_set import (  # noqa: E402
    GOVERNED_ROOT,
    PromotedContentSetError,
    collect_promoted_collections,
    collect_promoted_content_set,
    main,
)
from nexus_release_chain.release_readiness import (  # noqa: E402
    _REGISTRY_SUPPORTED_RELEASE_KINDS,
    load_release_registry_file,
)
from verify_corpus_cas import content_set_digest  # noqa: E402


def _registres_reels() -> list[Path]:
    """Toutes les lignées versionnées, découvertes par parcours.

    Nommer un répertoire en dur ferait taire la corroboration à la lignée
    suivante — un `skip` silencieux est la manière dont une épreuve cesse
    d'exister sans que personne ne le voie."""
    return sorted(GOVERNED_ROOT.rglob("release-registry.json"))


# --- l'autorité d'entrée est bornée ------------------------------------


def test_un_registre_hors_de_la_racine_gouvernee_est_refuse(tmp_path: Path) -> None:
    """Une autorité d'entrée extérieure au périmètre qu'elle prétend gouverner
    ne le gouverne pas. Un faux registre dont toutes les empreintes seraient
    cohérentes prouverait seulement qu'on a bien lu le fichier désigné."""
    faux = tmp_path / "release-registry.json"
    faux.write_text('{"registry_version": "1", "releases": []}', encoding="utf-8")
    with pytest.raises(PromotedContentSetError, match="hors de la racine gouvernée"):
        collect_promoted_content_set(faux)


def test_un_composant_en_lien_symbolique_interne_est_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le garde symlink, éprouvé sur le cas qu'il est SEUL à attraper.

    Un lien vers l'extérieur est déjà refusé par la borne « le chemin résolu
    est dans la racine ». Un lien INTERNE ne l'est pas : la résolution reste à
    l'intérieur, et le sceau du fichier atteint est correct."""
    import compute_promoted_content_set as module

    racine = tmp_path / "gouverne"
    vrai = racine / "lignee"
    vrai.mkdir(parents=True)
    (vrai / "release-registry.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module, "GOVERNED_ROOT", racine)
    (racine / "alias").symlink_to(vrai, target_is_directory=True)

    with pytest.raises(PromotedContentSetError, match="lien symbolique"):
        module.collect_promoted_content_set(racine / "alias" / "release-registry.json")


def test_un_registre_introuvable_est_refuse(tmp_path: Path) -> None:
    with pytest.raises(PromotedContentSetError, match="introuvable"):
        collect_promoted_content_set(GOVERNED_ROOT / "inexistant" / "release-registry.json")


# --- aucune divergence avec le chargeur du runtime ---------------------


def test_c1_lit_exactement_ce_que_le_chargeur_du_runtime_rend() -> None:
    """Le gate anti-divergence.

    Si le chargeur runtime gagne demain une nature de release, C1 doit la
    supporter PAR LUI — pas au prix d'une douzième ronde de revue. L'égalité
    est ici structurelle, et cette épreuve la maintient telle.
    """
    registres = _registres_reels()
    assert registres, "aucune lignée versionnée : la corroboration n'aurait pas lieu"

    for chemin in registres:
        empreinte = hashlib.sha256(chemin.read_bytes()).hexdigest()
        runtime = load_release_registry_file(chemin, empreinte)

        artefacts_runtime = {
            artefact.content_sha256
            for manifeste in runtime.manifests
            for artefact in manifeste.expectation.artifacts
        }
        assert collect_promoted_content_set(chemin) == artefacts_runtime, chemin.as_posix()
        assert collect_promoted_collections(chemin) == set(runtime.collections), (
            chemin.as_posix()
        )


def test_les_natures_supportees_sont_celles_du_runtime() -> None:
    """C1 ne connaît pas sa propre liste de natures : il n'en a plus.

    Un `if kind == …` dupliqué dans deux modules diverge le jour où l'un des
    deux gagne une nature. Wave0 est ainsi couvert sans que ce fichier n'ait
    jamais à le nommer.
    """
    assert "WAVE0_AGGREGATE_RELEASE_V1" in _REGISTRY_SUPPORTED_RELEASE_KINDS
    assert "MULTILEVEL_AGGREGATE_RELEASE_V1" in _REGISTRY_SUPPORTED_RELEASE_KINDS
    assert "MULTILEVEL_AGGREGATE_RELEASE_V2" in _REGISTRY_SUPPORTED_RELEASE_KINDS
    import compute_promoted_content_set as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for nature in _REGISTRY_SUPPORTED_RELEASE_KINDS:
        assert nature not in source, (
            f"{nature} est nommé dans C1 : la nature doit rester une décision "
            "du chargeur canonique, jamais une seconde table"
        )


# --- ce que le chargeur refuse, C1 le rend nommé -----------------------


def test_un_registre_illisible_rend_un_code_nomme_pas_une_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import compute_promoted_content_set as module

    racine = tmp_path / "gouverne"
    racine.mkdir()
    monkeypatch.setattr(module, "GOVERNED_ROOT", racine)
    registre = racine / "release-registry.json"
    registre.write_text("{ ceci n'est pas du JSON", encoding="utf-8")

    assert module.main(
        ["--release-registry", str(registre), "--output", str(tmp_path / "o.json")]
    ) == 2
    assert "PROMOTED_CONTENT_SET_INVALID" in capsys.readouterr().err


@pytest.mark.parametrize("charge", ["[]", '"registry"', "42", "null", '{"releases": 7}'])
def test_un_registre_de_forme_inattendue_est_refuse_proprement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, charge: str
) -> None:
    """Le chargeur canonique porte ces refus ; C1 doit les rendre NOMMÉS
    plutôt que de laisser remonter une trace."""
    import compute_promoted_content_set as module

    racine = tmp_path / "gouverne"
    racine.mkdir()
    monkeypatch.setattr(module, "GOVERNED_ROOT", racine)
    registre = racine / "release-registry.json"
    registre.write_text(charge, encoding="utf-8")

    with pytest.raises(PromotedContentSetError):
        module.collect_promoted_content_set(registre)


# --- la sortie ---------------------------------------------------------


def test_main_ecrit_l_ensemble_et_la_meme_formule_d_empreinte_que_le_verificateur(
    tmp_path: Path,
) -> None:
    import json

    sortie = tmp_path / "promoted.json"
    assert main(["--output", str(sortie)]) == 0
    rendu = json.loads(sortie.read_text(encoding="utf-8"))
    attendu = collect_promoted_content_set(module_registre())
    assert rendu["count"] == len(attendu)
    assert rendu["content_set_sha256"] == content_set_digest(attendu)


def module_registre() -> Path:
    import compute_promoted_content_set as module

    return module.DEFAULT_REGISTRY
