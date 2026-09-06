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
    return {
        "url": f"https://exemple/direct/{sha[:8]}.pdf",
        "resolution": "RESOLUE",
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
        assert item["appui"].startswith("")
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


def test_un_artefact_sans_aucune_url_est_une_source_statique() -> None:
    registre = construire_registre(artefacts=[_artefact(SHA_A)], entrees_url=[])
    (item,) = registre["dispositions"]
    assert item["disposition"] == Disposition.NON_URL_STATIC_SOURCE.value
    assert registre["CURRENTNESS_UNACCOUNTED"] == 0


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
