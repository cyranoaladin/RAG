"""Worker B transmet-il réellement l'autorité de droits au lecteur ? (lot CU)

``find_latest_artifact`` refuse la branche scellée sans résolveur. Ce refus
ne vaut que si l'appelant **opérationnel** le fournit : un appel direct avec
un argument passé par un script de diagnostic ne prouve rien.

Ces épreuves entrent par ``resume_publication`` et observent ce qui parvient
au lecteur. Elles échouent si la transmission est retirée de
``publication_resume``.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from ingestor.ingestion_worker import publication_resume as module


def _source_de(nom: str) -> str:
    return inspect.getsource(getattr(module, nom))


def test_chaque_appel_au_lecteur_transmet_le_catalogue() -> None:
    """Si ``sealed_catalog=`` disparaît d'un appel, cette épreuve tombe.

    Protection structurelle : elle ne remplace pas l'essai d'intégration qui
    entre par le CLI, elle empêche seulement qu'une transmission soit
    supprimée sans qu'on s'en aperçoive.
    """
    source = _source_de("resume_publication")
    # Les appels au lecteur, hors mention dans un commentaire ou un message.
    appels = [
        ligne for ligne in source.splitlines()
        if ("find_authorised_artifact(" in ligne or "find_latest_artifact(" in ligne)
        and not ligne.strip().startswith("#")
    ]
    assert appels, "resume_publication doit lire l'artefact"
    transmissions = source.count("sealed_catalog=sealed_catalog")
    assert transmissions == len(appels), (
        f"{len(appels)} appel(s) au lecteur mais {transmissions} transmission(s) "
        f"du catalogue — appels observes : {appels!r}"
    )


def test_le_resolveur_transmis_vient_du_registre_gouverne() -> None:
    """Pas d'autorité fabriquée localement : c'est le registre des deps."""
    source = _source_de("resume_publication")
    assert "deps.build_sealed_catalog()" in source
    source_deps = inspect.getsource(module.PublicationResumeDeps.build_sealed_catalog)
    assert "self.rights_evidence_registry" in source_deps
    assert "_VerifiedSealedCatalog(" in source_deps
    # Le catalogue n'est construit qu'a UN endroit : une seconde fabrique
    # locale pourrait porter d'autres autorites sans qu'on s'en apercoive.
    assert source.count("build_sealed_catalog()") == 1


def test_l_adaptateur_delegue_au_registre_et_ne_decide_rien() -> None:
    source = inspect.getsource(module._VerifiedSealedCatalog)
    assert "self.registry.resolve_rights(" in source
    # Il ne doit y avoir aucune valeur de droits écrite en dur.
    for invente in ("officiel_public", "CLEARED", "return (\"", "rights ="):
        assert invente not in source, invente


class _RegistreQuiRefuse:
    def resolve_rights(self, **_: Any) -> Any:  # pragma: no cover - jamais atteint
        raise AssertionError("ne doit pas être appelé pour un contenu hors release")


def test_un_contenu_hors_release_est_refuse_avant_toute_resolution() -> None:
    """Le registre n'est même pas interrogé : le contenu n'appartient pas à
    l'ensemble scellé, donc ses droits n'ont pas de sens ici."""
    resolveur = module._VerifiedSealedCatalog(
        registry=_RegistreQuiRefuse(), sealed_artifacts={}, media_type_invariant="application/pdf"
    )
    with pytest.raises(module.PublicationResumeError, match="not part of the sealed"):
        resolveur.resolve_rights(content_sha256="a" * 64)


class _RegistreQuiObserve:
    def __init__(self) -> None:
        self.vu: dict[str, Any] = {}

    def resolve_rights(self, *, content_sha256: str, source_path: str) -> Any:
        self.vu = {"content_sha256": content_sha256, "source_path": source_path}

        class _Clearance:
            rights = type("R", (), {"value": "officiel_public"})()
            decision_id = "eduscol_generic_approval"
            registry_sha256 = "c" * 64

        return _Clearance()


def test_le_source_path_vient_de_l_ensemble_scelle() -> None:
    """Le ``source_path`` est la seule désignation qu'un opérateur ne choisit
    pas. Il doit venir de la release vérifiée, jamais d'une URL reconstruite."""
    registre = _RegistreQuiObserve()
    sha = "b" * 64
    resolveur = module._VerifiedSealedCatalog(
        registry=registre,
        sealed_artifacts={sha: {"source_path": "01_EDUSCOL_OFFICIEL/doc.pdf"}},
        media_type_invariant="application/pdf",
    )
    droits, decision, empreinte = resolveur.resolve_rights(content_sha256=sha)
    assert registre.vu == {
        "content_sha256": sha,
        "source_path": "01_EDUSCOL_OFFICIEL/doc.pdf",
    }
    assert (droits, decision, empreinte) == (
        "officiel_public", "eduscol_generic_approval", "c" * 64
    )


def test_les_deps_portent_l_ensemble_scelle() -> None:
    """Sans lui, l'adaptateur ne peut pas exister — et le lecteur refusera."""
    champs = module.PublicationResumeDeps.__dataclass_fields__
    assert "sealed_release_artifacts" in champs
    assert "sealed_media_type_invariant" in champs
    assert "rights_evidence_registry" in champs


# --- Le CLI de Worker B transporte le catalogue, il ne l'invente pas ------


def test_le_cli_de_worker_b_transmet_le_catalogue_scelle() -> None:
    """Sans cette transmission, ``build_sealed_catalog`` rend ``None`` et la
    branche scellée refuse — correctement, mais la chaîne s'arrête."""
    from ingestor.ingestion_worker import multilevel_publication_resume_cli as cli

    source = inspect.getsource(cli)
    assert "sealed_release_artifacts=" in source
    assert "sealed_media_type_invariant=" in source
    assert "authorities.sealed_release_catalog" in source


def test_le_cli_ne_construit_pas_son_propre_catalogue() -> None:
    """Le chargement appartient au démarrage des autorités. Un second
    chargeur local pourrait porter d'autres références sans qu'on le voie."""
    from ingestor.ingestion_worker import multilevel_publication_resume_cli as cli

    source = inspect.getsource(cli)
    assert "load_sealed_release_catalog" not in source
    assert "VerifiedSealedReleaseCatalog(" not in source


def test_les_autorites_portent_le_catalogue_optionnel() -> None:
    """Une release multi-niveaux classique n'en porte pas : ``None`` est un
    état légitime, et c'est la LECTURE d'un artefact scellé qui refusera."""
    from ingestor.ingestion_worker.runtime_authority import (
        GovernedRuntimeAuthorities,
    )

    champs = GovernedRuntimeAuthorities.__dataclass_fields__
    assert "sealed_release_catalog" in champs
    assert champs["sealed_release_catalog"].default is None


def test_le_chargeur_refuse_un_catalogue_nomme_mais_incoherent() -> None:
    """Un manifeste qui ne nomme aucun catalogue rend ``None``. Un manifeste
    qui en nomme un dont le contenu ne correspond pas est une ERREUR — la
    distinction est ce qui empêche un silence."""
    from ingestor.ingestion_worker import multilevel_runtime_authority as mod

    source = inspect.getsource(mod._charger_catalogue_scelle)
    assert "return None" in source
    assert "RuntimeAuthorityStartupError" in source
    assert "cannot be " in source and "established" in source
