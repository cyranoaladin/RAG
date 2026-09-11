"""Épreuves du câblage de la politique d'actualité.

Ce que ces tests protègent : qu'on ne puisse pas rendre la politique
« appliquée » sans qu'elle change quoi que ce soit, ni la contourner en
effaçant un fichier. Le refus est la valeur par défaut partout.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[3]
SERVICE = RACINE / "services/rag-pedago"
if str(SERVICE) not in sys.path:
    sys.path.insert(0, str(SERVICE))

from rag_pedago.governance import currentness_disposition as cd  # noqa: E402
from rag_pedago.governance import servability_gate as sg  # noqa: E402

POLITIQUE = SERVICE / "configs/proposals/nexus_rag_currentness_policy_v1.yml"


def _politique(**surcharges) -> dict:
    document = yaml.safe_load(POLITIQUE.read_text(encoding="utf-8"))
    document.update(surcharges)
    return document


def _ecrire_politique(tmp_path: Path, document: dict) -> Path:
    chemin = tmp_path / "politique.yml"
    chemin.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    return chemin


def _cas(**surcharges) -> dict:
    base = {
        "official_provenance": True,
        "sha_provenance_match": True,
        "source_status": "CURRENT_DECLARED_BY_CATALOGUE",
        "superseding_conflict": False,
    }
    base.update(surcharges)
    return base


# --- le refus est la valeur par défaut ---------------------------------


def test_une_politique_absente_bloque(tmp_path: Path):
    """Un fichier effacé ne doit pas rendre tout le monde actuel en silence."""
    with pytest.raises(cd.PolitiqueNonAppliquee, match="absente"):
        cd.charger_politique(tmp_path / "nulle-part.yml")


def test_applied_false_bloque(tmp_path: Path):
    chemin = _ecrire_politique(tmp_path, _politique(applied=False))
    with pytest.raises(cd.PolitiqueNonAppliquee, match="pas appliquée"):
        cd.charger_politique(chemin)


def test_applied_absent_bloque(tmp_path: Path):
    document = _politique()
    document.pop("applied")
    chemin = _ecrire_politique(tmp_path, document)
    with pytest.raises(cd.PolitiqueNonAppliquee):
        cd.charger_politique(chemin)


def test_une_politique_illisible_bloque(tmp_path: Path):
    chemin = tmp_path / "p.yml"
    chemin.write_text("juste du texte", encoding="utf-8")
    with pytest.raises(cd.PolitiqueNonAppliquee, match="illisible"):
        cd.charger_politique(chemin)


# --- la politique ne s'arroge aucune décision étrangère -----------------


def test_une_condition_etrangere_dans_le_repli_est_refusee(tmp_path: Path):
    """Réintroduire PII_GATE_PASS ferait décider la PII à deux endroits."""
    document = _politique()
    document["fallback_rule"]["conditions_all_required"].append("PII_GATE_PASS")
    chemin = _ecrire_politique(tmp_path, document)
    with pytest.raises(cd.PolitiqueInvalide) as erreur:
        cd.charger_politique(chemin)
    assert "PII_GATE_PASS" in str(erreur.value)


def test_un_repli_qui_produirait_verified_current_est_refuse(tmp_path: Path):
    """Autoriser à servir n'est pas prouver l'actualité."""
    document = _politique()
    document["fallback_rule"]["disposition"] = cd.VERIFIED_CURRENT
    chemin = _ecrire_politique(tmp_path, document)
    with pytest.raises(cd.PolitiqueInvalide, match="VERIFIED_CURRENT"):
        cd.charger_politique(chemin)


# --- ce que la politique produit ---------------------------------------


def test_une_archive_declaree_n_est_jamais_ressuscitee():
    politique = cd.charger_politique()
    assert (
        cd.disposition_actualite(_cas(source_status="ARCHIVE"), politique)
        == cd.NOT_CURRENT_DECLARED_BY_SOURCE
    )


def test_un_403_ne_devient_jamais_current():
    """Un refus réseau laisse l'actualité indécidée ; il ne la nie pas, et il
    ne la prouve pas davantage."""
    politique = cd.charger_politique()
    disposition = cd.disposition_actualite(_cas(network_response=403), politique)
    assert disposition == cd.OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE
    assert disposition != cd.VERIFIED_CURRENT
    assert disposition != cd.NOT_CURRENT_DECLARED_BY_SOURCE


def test_une_preuve_absente_ne_devient_jamais_current():
    politique = cd.charger_politique()
    disposition = cd.disposition_actualite(
        _cas(official_provenance=False, sha_provenance_match=False), politique
    )
    assert disposition == cd.UNKNOWN
    assert disposition != cd.VERIFIED_CURRENT


def test_seule_une_identite_d_octets_prouve_l_actualite():
    politique = cd.charger_politique()
    assert (
        cd.disposition_actualite(_cas(content_identity_match=True), politique)
        == cd.VERIFIED_CURRENT
    )


# --- ce que le gate compose --------------------------------------------


def test_un_contenu_non_actuel_est_refuse_avant_toute_promotion():
    """Le refus que la matrice ne prononçait pas."""
    verdict, autorite = sg.composer(
        {"pii_gate": "PASS"}, cd.NOT_CURRENT_DECLARED_BY_SOURCE
    )
    assert verdict == sg.BLOCKED
    assert autorite == sg.AUTORITE_ACTUALITE


def test_une_actualite_inconnue_ne_passe_pas():
    verdict, autorite = sg.composer({"pii_gate": "PASS"}, cd.UNKNOWN)
    assert verdict == sg.BLOCKED
    assert autorite == sg.AUTORITE_ACTUALITE


def test_le_gate_ne_decide_aucune_dimension_etrangere():
    """Chaque refus nomme l'autorité qui l'a prononcé, jamais le gate."""
    for cas, attendue in (
        ({"pii_gate": "REJECTED"}, sg.AUTORITE_PII),
        ({"pii_gate": "PASS", "program": "INCOMPATIBLE"}, sg.AUTORITE_PROGRAMME),
        ({"pii_gate": "PASS", "indexable": False}, sg.AUTORITE_ROLE),
        ({"pii_gate": "PASS", "url_provenance": False}, sg.AUTORITE_PROVENANCE),
        ({"pii_gate": "PASS", "rights_gate": "FAIL"}, sg.AUTORITE_DROITS),
    ):
        verdict, autorite = sg.composer(
            cas, cd.OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE
        )
        assert verdict == sg.BLOCKED
        assert autorite == attendue
        assert autorite != sg.GATE


def test_une_disposition_inconnue_est_refusee():
    """Le gate n'invente pas une dimension qu'on ne lui donne pas."""
    with pytest.raises(sg.DimensionManquante):
        sg.composer({"pii_gate": "PASS"}, "PAS_UNE_DISPOSITION")


# --- le comportement est observable ------------------------------------


def test_la_matrice_refuse_de_se_construire_si_la_politique_ne_s_applique_pas(
    tmp_path: Path, monkeypatch
):
    """`applied=true` sans consommateur effectif ne peut pas exister ici.

    Si le drapeau redescend, la matrice ne se construit plus. Le drapeau et le
    comportement ne peuvent donc pas diverger — c'est ce qui rend l'application
    vérifiable autrement que par déclaration.
    """
    faux = tmp_path / "politique.yml"
    faux.write_text(
        yaml.safe_dump(_politique(applied=False), allow_unicode=True), encoding="utf-8"
    )
    monkeypatch.setattr(cd, "CHEMIN_POLITIQUE", faux)
    with pytest.raises(cd.PolitiqueNonAppliquee):
        cd.charger_politique()


def test_le_constructeur_de_matrice_charge_la_politique():
    """Le consommateur est relié : le code le montre, pas seulement le YAML."""
    source = (
        SERVICE / "scripts/construire_matrice_servabilite.py"
    ).read_text(encoding="utf-8")
    assert "charger_politique()" in source
    assert "from rag_pedago.governance.servability_gate import" in source
    # La matrice ne compose plus elle-même.
    assert 'row["verdict"] = _verdict(row, politique)' in source


def test_la_politique_declare_ses_consommateurs_et_ils_existent():
    document = yaml.safe_load(POLITIQUE.read_text(encoding="utf-8"))
    assert document["applied"] is True
    for relatif in document["consumed_by"]:
        assert (RACINE / relatif).is_file(), relatif
