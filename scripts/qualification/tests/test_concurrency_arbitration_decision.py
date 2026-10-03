"""L'arbitrage de concurrence fixe un protocole AVANT mesure ; il ne touche ni au budget ni au blocage."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

DECISION = RACINE / "docs/reports/go_live/concurrency_arbitration_decision.json"
EMPREINTE = RACINE / "docs/reports/go_live/concurrency_arbitration_decision.sha256"


def _decision() -> dict:
    return json.loads(DECISION.read_text(encoding="utf-8"))


def test_scellee():
    assert EMPREINTE.read_text(encoding="utf-8").split()[0] == hashlib.sha256(DECISION.read_bytes()).hexdigest()


def test_le_budget_versionne_est_inchange_et_lie():
    d = _decision()
    budget = RACINE / d["budget"]["path"]
    assert hashlib.sha256(budget.read_bytes()).hexdigest() == d["budget"]["sha256"]
    assert d["budget"]["changed_by_this_decision"] is False
    assert d["load_profile_changed_by_this_decision"] is False
    valeurs = json.loads(budget.read_text(encoding="utf-8"))
    assert valeurs["load_profile"]["concurrent_clients"] == 8
    assert valeurs["budget"]["p50_ms_max"] == 3000.0 and valeurs["budget"]["errors_max"] == 0


def test_ne_ferme_pas_concurrence():
    import build_qualification_blockers as blocages

    assert _decision()["closes_concurrence"] is False
    # L'arbitrage ne ferme rien : si CONCURRENCE est un jour fermé, ce ne peut être que par une preuve VERIFIED.
    etat = blocages.verifier_concurrence(RACINE)
    assert etat["closed"] is False or etat["proof"]["sha256_verified"] is True


def test_protocole_pre_enregistre_et_seuil_coherent_avec_le_budget():
    d = _decision()
    protocole = d["pre_registered_protocol"]
    assert protocole["fixed_before_any_new_measurement"] is True
    budget = json.loads((RACINE / d["budget"]["path"]).read_text(encoding="utf-8"))
    seuil = budget["budget"]["p50_ms_max"] / budget["load_profile"]["concurrent_clients"]
    assert d["measured_basis"]["required_service_ms_for_budget"] == seuil == 375
    assert [x["path"] for x in protocole["fallback_order"]] == ["B_RERANK_CAP", "C_LAUNCH_LOAD_PROFILE"]
    assert all("PR dédiée" in x["requires"] for x in protocole["fallback_order"])
    assert any("après lecture" in x for x in protocole["forbidden"])
