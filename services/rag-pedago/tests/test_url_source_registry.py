"""Registre des URL sources — ce qu'il refuse de laisser passer.

Aucun test n'ouvre de connexion : les sondes réseau sont des relevés
injectés. Ce qui est éprouvé ici, ce n'est pas la moisson, c'est la
**comptabilité** : qu'aucune URL découverte ne puisse disparaître entre
la découverte et le décompte, et qu'un « irrécupérable » sans preuve
soit un refus, pas une case cochée.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rag_pedago.governance.url_source_registry import (
    AutoriteSource,
    EntreeUrl,
    RegistreUrlSource,
    RegistreUrlSourceError,
    Resolution,
    RoleSource,
    charger_registre,
    compter,
    verifier_registre,
)

EMPREINTE_A = "a" * 64
EMPREINTE_B = "b" * 64
RETRIEVED_AT_NAVIGATION = "2026-09-05T18:00:10+00:00"


def _entree_directe(
    url: str = "https://eduscol.education.gouv.fr/sites/default/files/document/x-1.pdf",
    *,
    servie: str | None = EMPREINTE_A,
    scellee: str | None = EMPREINTE_A,
    status: int | None = 200,
) -> EntreeUrl:
    return EntreeUrl(
        url=url,
        source_role=RoleSource.DOCUMENT_DIRECT,
        resolution=Resolution.RESOLUE,
        navigation_url="https://eduscol.education.gouv.fr/5817/programmes",
        direct_url=url,
        resolved_url=url,
        status=status,
        content_type="application/pdf",
        etag='"abc"',
        last_modified="Mon, 04 Aug 2026 00:00:00 GMT",
        retrieved_at="2026-09-05T18:00:00+00:00",
        content_sha256=servie,
        artifact_id=scellee,
        empreinte_scellee=scellee,
    )


def _entree_navigation(
    url: str = "https://eduscol.education.gouv.fr/5817/programmes",
    *,
    resolution: Resolution = Resolution.IRRECUPERABLE,
    raison: str | None = "NAVIGATION_PROTEGEE_403",
    preuve: str | None = (
        f"HTTP 403 sur la page de navigation le {RETRIEVED_AT_NAVIGATION} ; "
        "robots.txt (User-agent: *) ne l'exclut pas — fermeture applicative du "
        "fournisseur, non contournée."
    ),
) -> EntreeUrl:
    return EntreeUrl(
        url=url,
        source_role=RoleSource.NAVIGATION_PROVENANCE,
        resolution=resolution,
        navigation_url=url,
        direct_url=None,
        resolved_url=None,
        status=403,
        content_type="text/html; charset=UTF-8",
        etag=None,
        last_modified=None,
        retrieved_at=RETRIEVED_AT_NAVIGATION,
        content_sha256=None,
        artifact_id=None,
        raison_irrecuperabilite=raison,
        preuve_irrecuperabilite=preuve,
    )


def _registre(*entrees: EntreeUrl) -> RegistreUrlSource:
    return RegistreUrlSource(
        registry_kind="URL_SOURCE_REGISTRY_V1",
        perimetre="prerentree_2026_2027/multilevel",
        autorites=[
            AutoriteSource(nom="catalogue-complet.tsv", emplacement="gdrive:x", sha256="c" * 64),
            AutoriteSource(nom="evidence.yml", emplacement="services/x", sha256="e" * 64),
        ],
        entrees=list(entrees),
    )


# --- comptage ---------------------------------------------------------


def test_compte_les_six_compteurs_sur_un_registre_mixte() -> None:
    registre = _registre(_entree_directe(), _entree_navigation())
    compteurs = compter(registre)
    assert compteurs["URL_DISCOVERED"] == 2
    assert compteurs["URL_DIRECT_RESOLVED"] == 1
    assert compteurs["URL_DIRECT_UNRESOLVED"] == 1
    assert compteurs["URL_UNRECOVERABLE"] == 1
    assert compteurs["URL_FETCHED"] == 1
    assert compteurs["URL_ERRORS"] == 1
    assert compteurs["URL_UNACCOUNTED"] == 0


def test_compte_la_fraicheur_verifiee_et_la_derive() -> None:
    conforme = _entree_directe(url="https://h/a.pdf", servie=EMPREINTE_A, scellee=EMPREINTE_A)
    derivee = _entree_directe(url="https://h/b.pdf", servie=EMPREINTE_B, scellee=EMPREINTE_A)
    compteurs = compter(_registre(conforme, derivee))
    assert compteurs["CURRENTNESS_VERIFIED"] == 1
    assert compteurs["CURRENTNESS_DRIFTED"] == 1


def test_une_entree_non_classee_tombe_en_unaccounted() -> None:
    orpheline = _entree_navigation(resolution=Resolution.NON_CLASSEE, raison=None, preuve=None)
    assert compter(_registre(orpheline))["URL_UNACCOUNTED"] == 1


# --- gardes -----------------------------------------------------------


def test_refuse_un_registre_qui_laisse_une_url_non_comptee() -> None:
    orpheline = _entree_navigation(resolution=Resolution.NON_CLASSEE, raison=None, preuve=None)
    with pytest.raises(RegistreUrlSourceError, match="URL_UNACCOUNTED"):
        verifier_registre(_registre(orpheline))


def test_refuse_un_irrecuperable_sans_preuve() -> None:
    sans_preuve = _entree_navigation(preuve=None)
    with pytest.raises(RegistreUrlSourceError, match="PREUVE_IRRECUPERABILITE_ABSENTE"):
        verifier_registre(_registre(sans_preuve))


def test_refuse_un_irrecuperable_sans_raison_nommee() -> None:
    sans_raison = _entree_navigation(raison=None)
    with pytest.raises(RegistreUrlSourceError, match="RAISON_IRRECUPERABILITE_ABSENTE"):
        verifier_registre(_registre(sans_raison))


def test_refuse_une_resolution_annoncee_sans_url_directe() -> None:
    menteuse = _entree_navigation(resolution=Resolution.RESOLUE, raison=None, preuve=None)
    with pytest.raises(RegistreUrlSourceError, match="RESOLUTION_SANS_URL_DIRECTE"):
        verifier_registre(_registre(menteuse))


def test_refuse_une_url_jamais_sondee() -> None:
    jamais_sondee = _entree_directe(status=None)
    with pytest.raises(RegistreUrlSourceError, match="SONDE_RESEAU_ABSENTE"):
        verifier_registre(_registre(jamais_sondee))


def test_refuse_un_document_direct_servi_sans_empreinte_servie() -> None:
    """Un 200 sans empreinte ne prouve rien : il ne peut pas passer pour vérifié."""
    muette = _entree_directe(servie=None)
    with pytest.raises(RegistreUrlSourceError, match="EMPREINTE_SERVIE_ABSENTE"):
        verifier_registre(_registre(muette))


def test_refuse_un_document_direct_sans_empreinte_scellee() -> None:
    sans_scelle = _entree_directe(scellee=None)
    with pytest.raises(RegistreUrlSourceError, match="EMPREINTE_SCELLEE_ABSENTE"):
        verifier_registre(_registre(sans_scelle))


def test_refuse_deux_entrees_pour_la_meme_url() -> None:
    with pytest.raises(RegistreUrlSourceError, match="URL_EN_DOUBLE"):
        verifier_registre(_registre(_entree_directe(), _entree_directe()))


def test_accepte_un_registre_complet() -> None:
    verifier_registre(_registre(_entree_directe(), _entree_navigation()))


def test_refuse_une_raison_irrecuperabilite_hors_liste_connue() -> None:
    """Une raison inventée serait invérifiable — équivalente à son absence."""
    raison_inventee = _entree_navigation(raison="LE_CHIEN_A_MANGE_LE_REGISTRE")
    with pytest.raises(RegistreUrlSourceError, match="RAISON_IRRECUPERABILITE_INCONNUE"):
        verifier_registre(_registre(raison_inventee))


def test_refuse_une_preuve_irrecuperabilite_trop_courte_pour_etre_structuree() -> None:
    """`raison="x"`, `preuve="x"` : la fraude minimale que la garde doit arrêter."""
    preuve_triviale = _entree_navigation(preuve="x")
    with pytest.raises(RegistreUrlSourceError, match="PREUVE_IRRECUPERABILITE_NON_STRUCTUREE"):
        verifier_registre(_registre(preuve_triviale))


def test_refuse_une_preuve_irrecuperabilite_sans_politique_robots() -> None:
    sans_robots = _entree_navigation(
        preuve=(
            f"HTTP 403 le {RETRIEVED_AT_NAVIGATION} sur la page de navigation, "
            "aucune autre vérification menée."
        )
    )
    with pytest.raises(
        RegistreUrlSourceError, match="PREUVE_IRRECUPERABILITE_SANS_POLITIQUE_ROBOTS"
    ):
        verifier_registre(_registre(sans_robots))


def test_refuse_une_preuve_irrecuperabilite_qui_ne_cite_pas_l_horodatage_de_la_sonde() -> None:
    """La preuve doit être ancrée sur LA sonde qu'elle prétend documenter."""
    horodatage_invente = _entree_navigation(
        preuve=(
            "HTTP 403 le 1999-01-01T00:00:00+00:00 sur la page de navigation ; "
            "robots.txt ne l'exclut pas."
        )
    )
    with pytest.raises(
        RegistreUrlSourceError, match="PREUVE_IRRECUPERABILITE_SANS_HORODATAGE_SONDE"
    ):
        verifier_registre(_registre(horodatage_invente))


def test_refuse_un_registre_sans_autorites() -> None:
    registre = RegistreUrlSource(
        registry_kind="URL_SOURCE_REGISTRY_V1",
        perimetre="prerentree_2026_2027/multilevel",
        autorites=[],
        entrees=[_entree_directe(), _entree_navigation()],
    )
    with pytest.raises(RegistreUrlSourceError, match="AUTORITES_INCOMPLETES"):
        verifier_registre(registre)


def test_refuse_une_autorite_non_scellee() -> None:
    registre = RegistreUrlSource(
        registry_kind="URL_SOURCE_REGISTRY_V1",
        perimetre="prerentree_2026_2027/multilevel",
        autorites=[
            AutoriteSource(nom="catalogue-complet.tsv", emplacement="gdrive:x", sha256=None),
            AutoriteSource(nom="evidence.yml", emplacement="services/x", sha256="e" * 64),
        ],
        entrees=[_entree_directe(), _entree_navigation()],
    )
    with pytest.raises(RegistreUrlSourceError, match="AUTORITE_NON_SCELLEE"):
        verifier_registre(registre)


# --- registre versionné ----------------------------------------------


def _chemin_registre() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "data"
        / "releases"
        / "prerentree_2026_2027"
        / "multilevel"
        / "url_source_registry.json"
    )


def test_le_registre_versionne_est_verifiable_et_sans_url_non_comptee() -> None:
    registre = charger_registre(_chemin_registre())
    verifier_registre(registre)
    compteurs = compter(registre)
    assert compteurs["URL_UNACCOUNTED"] == 0
    assert compteurs["URL_FETCHED"] + compteurs["URL_ERRORS"] == compteurs["URL_DISCOVERED"]


def test_le_registre_versionne_publie_ses_compteurs_et_ils_sont_exacts() -> None:
    """Les compteurs publiés sont recalculés, jamais crus sur parole."""
    chemin = _chemin_registre()
    publies = json.loads(chemin.read_text(encoding="utf-8"))["compteurs"]
    assert publies == compter(charger_registre(chemin))


def test_le_registre_versionne_couvre_les_cent_cinquante_artefacts_du_perimetre() -> None:
    """Aucun artefact scellé ne peut rester sans URL de provenance."""
    registre = charger_registre(_chemin_registre())
    couverts = {
        artefact
        for entree in registre.entrees
        for artefact in entree.artefacts_perimetre
    }
    evidence = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "configs"
            / "prerentree_2026_2027"
            / "multilevel_currentness_evidence.yml"
        ).read_text(encoding="utf-8")
    )["artifacts"]
    attendus = {artefact["content_sha256"] for artefact in evidence}
    assert attendus - couverts == set()
