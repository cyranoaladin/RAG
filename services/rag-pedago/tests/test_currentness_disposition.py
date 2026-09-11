"""Le registre de dispositions : ce qu'il refuse de laisser passer.

`URL_UNACCOUNTED=0` répond d'une question — chaque URL a un état. Ce module en
pose une autre : chaque ARTEFACT gouverné a-t-il une disposition ? Un artefact
couvert par une URL comptée peut rester sans réponse ; ces épreuves refusent
ce silence, et refusent aussi qu'une disposition soit affirmée sans ce qui la
soutient.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from rag_pedago.governance.currentness_disposition import (
    Disposition,
    DispositionError,
    construire_registre,
    verifier_registre,
)
from rag_pedago.governance.url_source_registry import (
    RAISONS_IRRECUPERABILITE_CONNUES,
)

PEDAGO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = (
    PEDAGO_ROOT / "configs" / "prerentree_2026_2027" / "multilevel_currentness_evidence.yml"
)
REGISTRY = (
    PEDAGO_ROOT
    / "data"
    / "releases"
    / "prerentree_2026_2027"
    / "multilevel"
    / "url_source_registry.json"
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def _artefact(sha: str) -> dict[str, object]:
    return {"content_sha256": sha}


def _resolue(sha: str) -> dict[str, object]:
    url = f"https://exemple/direct/{sha[:8]}.pdf"
    return {
        "url": url,
        "source_role": "DOCUMENT_DIRECT",
        "resolution": "RESOLUE",
        "status": 200,
        "direct_url": url,
        "artefacts_perimetre": [sha],
        "content_sha256": sha,
        "empreinte_scellee": sha,
    }


def _irrecuperable(sha: str, *, preuve: object = "HTTP 403 le 2026-09-05, robots.txt lu") -> dict:
    return {
        "url": f"https://exemple/navigation/{sha[:8]}",
        "resolution": "IRRECUPERABLE",
        "artefacts_perimetre": [sha],
        "raison_irrecuperabilite": "PORTEUR_DE_RELATION_ABSENT",
        "preuve_irrecuperabilite": preuve,
    }


@pytest.fixture(scope="module")
def registre_reel() -> dict[str, object]:
    evidence = yaml.safe_load(EVIDENCE.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return construire_registre(
        artefacts=evidence["artifacts"], entrees_url=registry["entrees"]
    )


def test_chaque_artefact_scelle_recoit_une_disposition(registre_reel) -> None:
    """CURRENTNESS_ACCOUNTED=100% ou le registre est refusé — pas de moyenne."""
    assert registre_reel["artefacts"] == 150
    assert registre_reel["CURRENTNESS_ACCOUNTED"] == 150
    assert registre_reel["CURRENTNESS_UNACCOUNTED"] == 0
    assert verifier_registre(registre_reel) == registre_reel["comptes"]


def test_les_douze_verifies_sont_ceux_dont_l_empreinte_servie_est_identique(
    registre_reel,
) -> None:
    """« L'URL répond » n'est pas « le contenu n'a pas dérivé »."""
    verifies = [
        item
        for item in registre_reel["dispositions"]
        if item["disposition"] == Disposition.VERIFIED_CURRENT.value
    ]
    assert len(verifies) == 12
    for item in verifies:
        assert "identique à l'empreinte scellée" in item["appui"]


def test_les_irrecuperables_portent_tous_une_raison(registre_reel) -> None:
    irrecuperables = [
        item
        for item in registre_reel["dispositions"]
        if item["disposition"] == Disposition.UNRECOVERABLE_WITH_EVIDENCE.value
    ]
    assert len(irrecuperables) == 138
    for item in irrecuperables:
        # `startswith("")` était vrai de TOUTE chaîne : l'assertion passait
        # au vert sans rien exiger. On exige ce que la disposition promet —
        # une raison du vocabulaire fermé, nommée dans l'appui.
        assert any(
            raison in item["appui"] for raison in RAISONS_IRRECUPERABILITE_CONNUES
        ), item["appui"]
        assert "irrécupérable" in item["appui"]
        assert item["urls"]


def test_une_url_qui_repond_sans_empreinte_ne_verifie_rien() -> None:
    """Un 200 sans octets servis est un ping, pas une vérification."""
    entree = _resolue(SHA_A) | {"content_sha256": None}
    with pytest.raises(DispositionError) as refus:
        construire_registre(artefacts=[_artefact(SHA_A)], entrees_url=[entree])
    assert "aucune disposition ne s'applique" in str(refus.value)


def test_une_empreinte_servie_differente_ne_verifie_rien() -> None:
    """Le cas qui compte : l'URL répond, mais le contenu a dérivé."""
    entree = _resolue(SHA_A) | {"content_sha256": SHA_B}
    with pytest.raises(DispositionError):
        construire_registre(artefacts=[_artefact(SHA_A)], entrees_url=[entree])


def test_un_irrecuperable_sans_preuve_est_refuse() -> None:
    """Sans cette exigence, UNACCOUNTED=0 s'obtiendrait par déplacement."""
    with pytest.raises(DispositionError) as refus:
        construire_registre(
            artefacts=[_artefact(SHA_A)],
            entrees_url=[_irrecuperable(SHA_A, preuve=None)],
        )
    assert "sans preuve" in str(refus.value)


def test_un_artefact_declare_source_statique_sans_url_recoit_cette_disposition() -> None:
    artefact = {"content_sha256": SHA_A, "non_url_static_source": "DEPOT_GOUVERNE_SANS_URL"}
    registre = construire_registre(artefacts=[artefact], entrees_url=[])
    (item,) = registre["dispositions"]
    assert item["disposition"] == Disposition.NON_URL_STATIC_SOURCE.value
    assert registre["CURRENTNESS_UNACCOUNTED"] == 0


def test_un_artefact_sans_url_ni_declaration_de_source_statique_est_refuse() -> None:
    """Une régression du registre d'URL ne peut pas se faire passer pour une preuve."""
    with pytest.raises(DispositionError, match="non_url_static_source"):
        construire_registre(artefacts=[_artefact(SHA_A)], entrees_url=[])


def test_un_artefact_partiellement_resolu_n_est_pas_range_d_office() -> None:
    """Ni vérifié ni entièrement irrécupérable : le cas est nommé, pas classé."""
    entrees = [
        _irrecuperable(SHA_A),
        {
            "url": "https://exemple/en-attente",
            "resolution": "EN_ATTENTE",
            "artefacts_perimetre": [SHA_A],
            "motif_attente": "hors périmètre",
        },
    ]
    with pytest.raises(DispositionError) as refus:
        construire_registre(artefacts=[_artefact(SHA_A)], entrees_url=entrees)
    assert "aucune disposition ne s'applique" in str(refus.value)


def test_le_verificateur_refuse_un_compte_publie_faux() -> None:
    registre = construire_registre(
        artefacts=[_artefact(SHA_A)], entrees_url=[_resolue(SHA_A)]
    )
    registre["comptes"][Disposition.VERIFIED_CURRENT.value] = 99
    with pytest.raises(DispositionError) as refus:
        verifier_registre(registre)
    assert "divergent" in str(refus.value)


def test_le_verificateur_refuse_une_disposition_sans_appui() -> None:
    registre = construire_registre(
        artefacts=[_artefact(SHA_A)], entrees_url=[_resolue(SHA_A)]
    )
    registre["dispositions"][0]["appui"] = ""
    with pytest.raises(DispositionError) as refus:
        verifier_registre(registre)
    assert "sans appui" in str(refus.value)


def test_le_verificateur_refuse_un_artefact_dispositionne_deux_fois() -> None:
    registre = construire_registre(
        artefacts=[_artefact(SHA_A)], entrees_url=[_resolue(SHA_A)]
    )
    registre["dispositions"].append(dict(registre["dispositions"][0]))
    registre["artefacts"] = 2
    registre["comptes"][Disposition.VERIFIED_CURRENT.value] = 2
    with pytest.raises(DispositionError) as refus:
        verifier_registre(registre)
    assert "deux fois" in str(refus.value)


def test_un_perimetre_vide_est_refuse() -> None:
    """Zéro artefact rendrait UNACCOUNTED=0 trivialement vrai."""
    with pytest.raises(DispositionError):
        construire_registre(artefacts=[], entrees_url=[])


# --- exigences de fraîcheur vérifiée strictes ----------------------------


def test_une_resolution_qui_n_est_pas_un_document_direct_ne_verifie_rien() -> None:
    """RESOLUE + empreintes identiques ne suffit pas : il faut DOCUMENT_DIRECT."""
    entree = _resolue(SHA_A) | {"source_role": "NAVIGATION_PROVENANCE"}
    with pytest.raises(DispositionError):
        construire_registre(artefacts=[_artefact(SHA_A)], entrees_url=[entree])


def test_une_resolution_sans_statut_200_ne_verifie_rien() -> None:
    entree = _resolue(SHA_A) | {"status": 404}
    with pytest.raises(DispositionError):
        construire_registre(artefacts=[_artefact(SHA_A)], entrees_url=[entree])


def test_une_resolution_sans_url_directe_ne_verifie_rien() -> None:
    entree = _resolue(SHA_A) | {"direct_url": None}
    with pytest.raises(DispositionError):
        construire_registre(artefacts=[_artefact(SHA_A)], entrees_url=[entree])


# --- preuve persistée pour les dispositions irrécupérables ----------------


def test_l_appui_irrecuperable_porte_un_condensé_verifiable_de_la_preuve() -> None:
    registre = construire_registre(
        artefacts=[_artefact(SHA_A)], entrees_url=[_irrecuperable(SHA_A)]
    )
    (item,) = registre["dispositions"]
    import re

    assert re.search(r"preuve=[0-9a-f]{64}$", item["appui"])


@pytest.mark.parametrize("preuve_non_textuelle", [True, ["HTTP 403 le ...", "robots.txt lu"]])
def test_une_preuve_non_textuelle_est_refusee(preuve_non_textuelle: object) -> None:
    """`True` ou une liste seraient truthy, mais ne sont pas une preuve."""
    with pytest.raises(DispositionError, match="sans preuve"):
        construire_registre(
            artefacts=[_artefact(SHA_A)],
            entrees_url=[_irrecuperable(SHA_A, preuve=preuve_non_textuelle)],
        )


@pytest.mark.parametrize("appui_non_textuel", [123, ["preuve=" + "a" * 64]])
def test_le_verificateur_refuse_un_appui_irrecuperable_non_textuel(appui_non_textuel: object) -> None:
    """Un `appui` non textuel doit être un refus nommé, pas un TypeError."""
    registre = construire_registre(
        artefacts=[_artefact(SHA_A)], entrees_url=[_irrecuperable(SHA_A)]
    )
    registre["dispositions"][0]["appui"] = appui_non_textuel
    with pytest.raises(DispositionError, match="condensé de preuve"):
        verifier_registre(registre)


def test_le_verificateur_refuse_un_appui_irrecuperable_sans_condense_de_preuve() -> None:
    registre = construire_registre(
        artefacts=[_artefact(SHA_A)], entrees_url=[_irrecuperable(SHA_A)]
    )
    registre["dispositions"][0]["appui"] = "1 provenance(s) irrécupérable(s) : X"
    with pytest.raises(DispositionError, match="condensé de preuve"):
        verifier_registre(registre)


def test_sans_entrees_url_un_condense_falsifie_mais_bien_forme_passe() -> None:
    """La forme seule ne prouve rien : documenté, pas un défaut caché."""
    registre = construire_registre(
        artefacts=[_artefact(SHA_A)], entrees_url=[_irrecuperable(SHA_A)]
    )
    registre["dispositions"][0]["appui"] = (
        "1 provenance(s) irrécupérable(s) : AUTRE_RAISON ; preuve=" + "0" * 64
    )
    assert verifier_registre(registre) == registre["comptes"]


def test_avec_entrees_url_un_condense_falsifie_est_refuse() -> None:
    """La même falsification, recalculée depuis l'autorité, est refusée."""
    entrees = [_irrecuperable(SHA_A)]
    registre = construire_registre(artefacts=[_artefact(SHA_A)], entrees_url=entrees)
    registre["dispositions"][0]["appui"] = (
        "1 provenance(s) irrécupérable(s) : AUTRE_RAISON ; preuve=" + "0" * 64
    )
    with pytest.raises(DispositionError, match="ne correspond pas"):
        verifier_registre(registre, entrees_url=entrees)


def test_avec_entrees_url_le_condense_reel_est_accepte() -> None:
    entrees = [_irrecuperable(SHA_A)]
    registre = construire_registre(artefacts=[_artefact(SHA_A)], entrees_url=entrees)
    assert verifier_registre(registre, entrees_url=entrees) == registre["comptes"]


def test_le_registre_reel_se_verifie_condense_compris_contre_le_registre_d_url(
    registre_reel,
) -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert (
        verifier_registre(registre_reel, entrees_url=registry["entrees"])
        == registre_reel["comptes"]
    )


# --- ce dont la dérivation doit s'assurer AVANT de dériver -------------


def test_le_constructeur_refuse_un_artefact_hors_couverture_du_registre() -> None:
    """Le trou que le contrôle de dérive ne voit pas.

    Le contrôle de dérive attrape un grand livre PÉRIMÉ. Il n'attrape pas un
    registre d'URL vide, tronqué ou édité : à partir de lui, un grand livre
    tout neuf se régénère, et chaque artefact devenu introuvable serait pris
    pour une source statique. Moins on en saurait, plus le compte serait vert.
    """
    import importlib.util

    chemin = PEDAGO_ROOT / "scripts" / "build_currentness_disposition.py"
    spec = importlib.util.spec_from_file_location("build_cd", chemin)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    with pytest.raises(DispositionError) as refus:
        module._exiger_couverture(
            [{"content_sha256": SHA_A}],
            [{"url": "https://x", "artefacts_perimetre": [SHA_B]}],
        )
    assert "hors couverture du registre" in str(refus.value)


def test_un_artefact_declare_statique_est_admis_hors_couverture() -> None:
    """La déclaration explicite reste la seule porte de sortie."""
    import importlib.util

    chemin = PEDAGO_ROOT / "scripts" / "build_currentness_disposition.py"
    spec = importlib.util.spec_from_file_location("build_cd2", chemin)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    module._exiger_couverture(
        [{"content_sha256": SHA_A, "non_url_static_source": "corpus/referentiels"}],
        [],
    )
