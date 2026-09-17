"""Test hermétique de la preuve STAGING_EXTERNE (sans Docker ni réseau)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "scripts/qualification"))

PREUVE = RACINE / "docs/reports/evidence/external_staging_proof.json"
EMPREINTE = RACINE / "docs/reports/evidence/external_staging_proof.sha256"


def test_empreinte_scellee() -> None:
    octets = PREUVE.read_bytes()
    assert EMPREINTE.read_text(encoding="utf-8").split()[0] == hashlib.sha256(octets).hexdigest()


def test_un_runbook_ne_ferme_jamais_le_blocage() -> None:
    import verify_external_staging as scelleur

    preuve = json.loads(PREUVE.read_text(encoding="utf-8"))
    if preuve["host_kind"] == "runbook_only":
        assert preuve["environment_started"] is False
        assert preuve["closes_blocker"] is False
        assert scelleur.verifier_seulement() == 1


def test_rien_n_est_pretendu_qui_n_a_pas_ete_fait() -> None:
    preuve = json.loads(PREUVE.read_text(encoding="utf-8"))
    if preuve["environment_started"] is False:
        assert preuve["retrieval_smoke"]["executed"] is False
        assert preuve["cockpit_smoke"]["executed"] is False
        assert preuve["rollback"]["exercised"] is False
        assert preuve["local_checks_really_done"]["containers_started"] == 0


def test_noms_de_variables_sans_valeurs_ni_secret() -> None:
    preuve = json.loads(PREUVE.read_text(encoding="utf-8"))
    texte = PREUVE.read_text(encoding="utf-8")
    assert preuve["secret_exposed"] is False and preuve["secret_values_in_proof"] == 0
    assert all("=" not in nom for nom in preuve["variables_required_names_only"])
    for motif in ("rehearsal-placeholder", "PASSWORD=", "Bearer "):
        assert motif not in texte
    for cle in ("production_db_writes", "production_deployments", "current_switch"):
        assert preuve[cle] == 0
