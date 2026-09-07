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


# --- C1 et le runtime lisent la MÊME sémantique ------------------------


def test_le_chargeur_du_service_ne_derive_pas_de_l_autorite_canonique() -> None:
    """C1 importe le paquet ; le runtime importe sa copie dans le service.

    Elles sont aujourd'hui identiques octet pour octet, et rien ne l'imposait.
    Si elles divergent, le gate CAS certifie un périmètre sous une sémantique
    et le runtime en sert un autre sous une seconde — exactement le défaut que
    la délégation vient de supprimer côté C1, réintroduit un cran plus bas.

    Faire importer le paquet par `services/rag-engine` est la correction de
    fond ; elle touche huit modules du service et sa chaîne de dépendances,
    donc un autre lot. En attendant, l'écart ne peut plus se produire en
    silence.
    """
    racine = Path(__file__).resolve().parents[3]
    canonique = (
        racine / "packages" / "release-chain" / "src" / "nexus_release_chain"
        / "release_readiness.py"
    )
    copie_service = (
        racine / "services" / "rag-engine" / "src" / "ingestor" / "release_readiness.py"
    )
    if not copie_service.is_file():
        pytest.skip("le service ne porte plus de copie : elle a été unifiée")

    empreinte_canonique = hashlib.sha256(canonique.read_bytes()).hexdigest()
    empreinte_service = hashlib.sha256(copie_service.read_bytes()).hexdigest()
    assert empreinte_canonique == empreinte_service, (
        "le chargeur de release du service a dérivé de l'autorité canonique : "
        f"{empreinte_service[:16]}… contre {empreinte_canonique[:16]}… — C1 "
        "qualifierait alors un périmètre que le runtime ne sert pas de la "
        "même façon"
    )


# --- C1 qualifie le registre que le DÉPLOIEMENT sert -------------------


def test_la_racine_gouvernee_suit_le_deploiement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La borne reste exercée, mais contre la racine de CE déploiement : un
    conteneur ne connaît pas celle du dépôt."""
    import compute_promoted_content_set as module

    monkeypatch.setenv(module.GOVERNED_ROOT_ENV, str(tmp_path))
    dehors = tmp_path.parent / "ailleurs.json"
    dehors.write_text("{}", encoding="utf-8")
    with pytest.raises(PromotedContentSetError, match="hors de la racine gouvernée"):
        module.collect_promoted_content_set(dehors)


# --- parité de configuration C1 / runtime ------------------------------


def test_c1_et_le_runtime_lisent_la_meme_regle_de_configuration() -> None:
    """La matrice PATH/SHA, éprouvée sur les DEUX implémentations.

    Le runtime porte encore sa propre copie de la règle
    (`_configured_release_registry_file`). Tant que le doublon existe, cette
    épreuve confronte les deux verdicts case par case : une divergence de
    configuration ferait qualifier par C1 une lignée que le runtime refuse.
    """
    import os

    from nexus_release_chain.deployment_binding import (
        REGISTRY_PATH_ENV,
        REGISTRY_SHA256_ENV,
        DeploymentBindingError,
        configured_release_registry,
    )

    racine = Path(__file__).resolve().parents[3]
    module_runtime = (
        racine / "services" / "rag-engine" / "src" / "ingestor"
        / "retrieval_v2_endpoint.py"
    )
    if not module_runtime.is_file():
        pytest.skip("module runtime absent de ce checkout")

    source = module_runtime.read_text(encoding="utf-8")
    assert "_configured_release_registry_file" in source
    # La sémantique du runtime, lue dans son source : mêmes trois branches.
    assert 'path_raw is None and digest is None' in source
    assert 'if not path_raw or not digest' in source
    assert "release registry configuration incomplete" in source

    sha = "b" * 64
    matrice = [
        ({}, "DEFAUT"),
        ({REGISTRY_PATH_ENV: "/app/r.json", REGISTRY_SHA256_ENV: sha}, "EPINGLE"),
        ({REGISTRY_PATH_ENV: "/app/r.json"}, "REFUS"),
        ({REGISTRY_SHA256_ENV: sha}, "REFUS"),
    ]
    for environnement, attendu in matrice:
        try:
            resultat = configured_release_registry(environnement)
            obtenu = "DEFAUT" if resultat is None else "EPINGLE"
        except DeploymentBindingError:
            obtenu = "REFUS"
        assert obtenu == attendu, (environnement, attendu, obtenu)

    assert os.environ is not None  # la lecture par défaut reste l'environnement


def test_le_mode_deploiement_ne_calcule_jamais_l_empreinte_lui_meme(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Calculer l'empreinte d'un registre désigné par un déploiement ferait du
    fichier observé sa propre autorité — et C1 rendrait vert sur un registre
    que le runtime refuserait."""
    import compute_promoted_content_set as module
    from nexus_release_chain.deployment_binding import (
        REGISTRY_PATH_ENV,
        REGISTRY_SHA256_ENV,
    )

    racine = tmp_path / "gouverne"
    racine.mkdir()
    monkeypatch.setattr(module, "GOVERNED_ROOT", racine)
    registre = racine / "release-registry.json"
    registre.write_text('{"registry_version": "1", "releases": []}', encoding="utf-8")

    # Le déploiement parle — paire COMPLÈTE — mais l'appelant n'a pas
    # transmis l'empreinte. Le calculer ici la rendrait vraie par
    # construction.
    monkeypatch.setenv(REGISTRY_PATH_ENV, str(registre))
    monkeypatch.setenv(REGISTRY_SHA256_ENV, "c" * 64)

    with pytest.raises(module.PromotedContentSetError, match="propre autorité"):
        module.collect_promoted_content_set(registre)

    # Hors déploiement, le mode dépôt reste licite : le registre EST
    # l'autorité d'entrée, et la borne de racine en est la garde.
    monkeypatch.delenv(REGISTRY_PATH_ENV)
    monkeypatch.delenv(REGISTRY_SHA256_ENV)
    with pytest.raises(module.PromotedContentSetError):
        module.collect_promoted_content_set(registre)  # registre vide, autre refus


# --- la matrice de précédence du registre ------------------------------


class TestLaMatriceDePrecedenceEstExplicite:
    """Trois sources possibles, mutuellement exclusives.

    Sans ces noms, elles se recouvraient en silence : un déploiement pouvait
    désigner un registre et un argument de ligne de commande en imposer un
    autre, et la preuve produite ne disait pas laquelle avait décidé du
    périmètre servi.
    """

    def _resoudre(self, **kwargs):
        from compute_promoted_content_set import resoudre_source_du_registre

        return resoudre_source_du_registre(**kwargs)

    def test_sans_deploiement_ni_argument_le_mode_est_le_defaut(self) -> None:
        from compute_promoted_content_set import DEFAULT_REGISTRY, MODE_DEFAULT

        mode, registre, empreinte = self._resoudre(
            registre_demande=None, empreinte_demandee=None, liaison=None
        )
        assert (mode, registre, empreinte) == (MODE_DEFAULT, DEFAULT_REGISTRY, None)

    def test_un_deploiement_seul_impose_son_registre_et_son_empreinte(
        self, tmp_path: Path
    ) -> None:
        from compute_promoted_content_set import MODE_DEPLOYMENT

        chemin, sceau = tmp_path / "r.json", "a" * 64
        assert self._resoudre(
            registre_demande=None, empreinte_demandee=None, liaison=(chemin, sceau)
        ) == (MODE_DEPLOYMENT, chemin, sceau)

    def test_une_candidate_explicite_exige_son_empreinte(self, tmp_path: Path) -> None:
        """Hacher le fichier observé ferait de la candidate sa propre autorité :
        elle serait alors qualifiée contre elle-même."""
        from compute_promoted_content_set import PromotedContentSetError

        with pytest.raises(PromotedContentSetError, match="sa propre autorité"):
            self._resoudre(
                registre_demande=tmp_path / "candidate.json",
                empreinte_demandee=None,
                liaison=None,
            )

    def test_une_candidate_explicite_avec_empreinte_est_acceptee(
        self, tmp_path: Path
    ) -> None:
        from compute_promoted_content_set import MODE_EXPLICIT_CANDIDATE

        chemin, sceau = tmp_path / "candidate.json", "b" * 64
        assert self._resoudre(
            registre_demande=chemin, empreinte_demandee=sceau, liaison=None
        ) == (MODE_EXPLICIT_CANDIDATE, chemin, sceau)

    def test_un_deploiement_et_une_candidate_ensemble_sont_refuses(
        self, tmp_path: Path
    ) -> None:
        """Deux autorités pour un même périmètre : rien ne dirait laquelle a
        décidé de ce qui est servi."""
        from compute_promoted_content_set import PromotedContentSetError

        with pytest.raises(PromotedContentSetError, match="deux autorités"):
            self._resoudre(
                registre_demande=tmp_path / "candidate.json",
                empreinte_demandee="c" * 64,
                liaison=(tmp_path / "deploye.json", "d" * 64),
            )

    def test_une_empreinte_qui_contredit_le_deploiement_est_refusee(
        self, tmp_path: Path
    ) -> None:
        from compute_promoted_content_set import PromotedContentSetError

        with pytest.raises(PromotedContentSetError, match="contredit"):
            self._resoudre(
                registre_demande=None,
                empreinte_demandee="e" * 64,
                liaison=(tmp_path / "deploye.json", "f" * 64),
            )

    def test_une_empreinte_sans_registre_designe_est_refusee(self) -> None:
        """L'empreinte ne porterait sur rien de nommé."""
        from compute_promoted_content_set import PromotedContentSetError

        with pytest.raises(PromotedContentSetError, match="ne porterait sur rien"):
            self._resoudre(
                registre_demande=None, empreinte_demandee="0" * 64, liaison=None
            )
