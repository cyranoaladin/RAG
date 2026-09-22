"""Le migrateur reçoit-il TOUT ce que ses scripts exigent au démarrage ?

`docker-compose.ingestion.yml` monte les scripts du migrateur **un par un**,
en lecture seule — un choix délibéré, qui réduit la surface exposée au
conteneur. Sa contrepartie est un couplage invisible : ajouter un `source`
dans un script monté ne fait échouer aucun test unitaire, aucun lint, aucune
revue de diff du script lui-même. Le fichier sourcé n'arrive tout simplement
jamais dans le conteneur, et le migrateur meurt à la première ligne.

Mesuré sur ce dépôt le 22/09/2026 : l'ajout de
`scripts/lib/sql_transaction_control.sh` au bootstrap a fait sortir le
migrateur en 1. Le seul test qui l'a vu est une suite Compose complète, et
elle l'a signalé par « le migrateur devait réussir » — vrai, mais muet sur la
cause. Ce test-ci nomme la cause, sans Docker.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = ENGINE_ROOT / "infra" / "docker-compose.ingestion.yml"
MIGRATOR_SERVICE = "migrator-ingestion-control"

# `. "$X"` ou `source "$X"` où $X a été construit plus haut : on ne cherche
# donc pas la ligne `source`, mais tout chemin de la forme `lib/<nom>.sh`
# cité dans le script. Un faux positif coûte un montage de plus ; un faux
# négatif coûte un migrateur mort en production.
DEPENDANCE = re.compile(r"(?<![\w./-])(lib/[\w./-]+\.sh)")


def _montages() -> dict[str, str]:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    service = compose["services"][MIGRATOR_SERVICE]
    montages: dict[str, str] = {}
    for volume in service.get("volumes", []):
        hote, conteneur, *_ = str(volume).split(":")
        montages[conteneur] = hote
    return montages


def _scripts_montes(montages: dict[str, str]) -> dict[str, Path]:
    return {
        conteneur: (ENGINE_ROOT / "infra" / hote.lstrip("./")).resolve()
        for conteneur, hote in montages.items()
        if conteneur.endswith(".sh")
    }


def test_le_service_migrateur_existe_toujours_sous_ce_nom() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    assert MIGRATOR_SERVICE in compose["services"], (
        f"{MIGRATOR_SERVICE} a disparu de {COMPOSE_PATH.name} : ce test ne "
        "garde plus rien tant que son nom n'est pas corrigé"
    )


def test_tout_script_monte_existe_vraiment_dans_le_depot() -> None:
    for conteneur, hote in _scripts_montes(_montages()).items():
        assert hote.is_file(), (
            f"{COMPOSE_PATH.name} monte {hote} sur {conteneur}, mais ce "
            "fichier n'existe pas : Docker créerait un répertoire vide à sa "
            "place et le migrateur échouerait sans message utile"
        )


@pytest.mark.parametrize("conteneur", sorted(_scripts_montes(_montages())))
def test_chaque_fragment_source_est_lui_meme_monte(conteneur: str) -> None:
    montages = _montages()
    script = _scripts_montes(montages)[conteneur]
    racine_conteneur = conteneur.rsplit("/", 1)[0]

    for relatif in sorted(set(DEPENDANCE.findall(script.read_text(encoding="utf-8")))):
        attendu = f"{racine_conteneur}/{relatif}"
        assert attendu in montages, (
            f"{script.name} dépend de {relatif}, qui n'est monté nulle part "
            f"dans {MIGRATOR_SERVICE}. Ajouter dans ses volumes :\n"
            f"      - ./scripts/{relatif}:{attendu}:ro"
        )
        hote = (ENGINE_ROOT / "infra" / montages[attendu].lstrip("./")).resolve()
        assert hote.is_file(), f"{attendu} est monté depuis {hote}, absent du dépôt"
