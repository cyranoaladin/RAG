"""La propriete de `currentness_policy_impact.json`, et ce qu il n a pas le droit de devenir.

Ce rapport porte des compteurs PROGRAM_COMPATIBLE / INCOMPATIBLE / UNKNOWN. Ils
y sont des ENTREES de la decision d actualite, pas une logique programme : le
front actualite demande « ce document sert-il un programme en vigueur ? » et
recoit une reponse produite ailleurs.

PROGRAM_COUNTS_ROLE=INPUT_ONLY
PROGRAM_LOGIC_IMPLEMENTED=false

Ces deux proprietes ne sont PAS ecrites dans le rapport lui-meme : il est scelle
par empreinte (campaign freeze receipt), et y ajouter un champ le ferait deriver.
Elles sont donc tenues ici, par une epreuve qui echoue si de la logique
programme s y introduit un jour.
"""

from __future__ import annotations

import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
RAPPORT = RACINE / "docs/reports/handoff/currentness_policy_impact.json"
POLITIQUE = Path(__file__).resolve().parents[1] / "configs/proposals/nexus_rag_currentness_policy_v1.yml"

#: Marqueurs d une LOGIQUE programme — pas d une simple mention. Un compteur
#: nomme PROGRAM_UNKNOWN est une entree ; un identifiant de BO, une autorite ou
#: une base de liaison est une logique, et n a rien a faire ici.
MARQUEURS_DE_LOGIQUE_PROGRAMME = (
    "BOEN", "official_reference", "authority_id", "binding_basis",
    "attribution_basis", "program_authority", "NOR", "bulletin_number",
    "supersedes", "effective_from",
)

COMPTEURS_ADMIS = ("PROGRAM_COMPATIBLE", "PROGRAM_INCOMPATIBLE", "PROGRAM_UNKNOWN")


def test_le_rapport_ne_porte_que_des_compteurs_programme():
    texte = RAPPORT.read_text(encoding="utf-8")
    presents = [m for m in MARQUEURS_DE_LOGIQUE_PROGRAMME if m in texte]
    assert presents == [], (
        "logique programme introduite dans un rapport d actualite : "
        f"{presents}. Les compteurs programme y sont INPUT_ONLY."
    )


def test_les_compteurs_programme_sont_bien_presents_comme_entree():
    # L autre sens : si ces compteurs disparaissaient, la decision d actualite
    # perdrait son entree sans que rien ne le signale.
    donnees = json.loads(RAPPORT.read_text(encoding="utf-8"))
    for compteur in COMPTEURS_ADMIS:
        assert compteur in donnees, f"entree de decision disparue : {compteur}"


def test_la_politique_ne_porte_aucune_autorite_de_programme():
    texte = POLITIQUE.read_text(encoding="utf-8")
    presents = [m for m in MARQUEURS_DE_LOGIQUE_PROGRAMME if m in texte]
    assert presents == [], (
        f"la politique d actualite a cesse d etre INPUT_ONLY : {presents}"
    )
