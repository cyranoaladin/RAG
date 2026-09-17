"""Test hermétique de la preuve CONCURRENCE (sans Docker ni réseau)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "scripts/qualification"))

PREUVE = RACINE / "docs/reports/evidence/concurrency_load_proof.json"
EMPREINTE = RACINE / "docs/reports/evidence/concurrency_load_proof.sha256"
BUDGET = RACINE / "docs/reports/go_live/concurrency_load_budget.json"


def test_module_de_scellement_importable_sans_dependance_externe() -> None:
    import verify_concurrency_load as scelleur

    statut = json.loads(PREUVE.read_text(encoding="utf-8"))["verification_status"]
    # Une mesure hors budget est un diagnostic : le vérificateur DOIT la refuser.
    assert scelleur.verifier_seulement() == (0 if statut == "VERIFIED" else 1)


def test_empreinte_scellee_et_budget_lie() -> None:
    octets = PREUVE.read_bytes()
    assert EMPREINTE.read_text(encoding="utf-8").split()[0] == hashlib.sha256(octets).hexdigest()
    preuve = json.loads(octets)
    budget_sha = hashlib.sha256(BUDGET.read_bytes()).hexdigest()
    assert preuve["budget"]["sha256"] == budget_sha
    assert preuve["measurements"]["budget_sha256"] == budget_sha


def test_mesures_brutes_completes_et_sans_mock() -> None:
    preuve = json.loads(PREUVE.read_text(encoding="utf-8"))
    profil = json.loads(BUDGET.read_text(encoding="utf-8"))["load_profile"]
    mesures = preuve["measurements"]
    assert len(mesures["measured_requests"]) == profil["measured_requests_total"]
    assert mesures["load_profile_executed"]["concurrent_clients"] == profil["concurrent_clients"]
    assert mesures["engine"]["mock_detected"] is False
    assert preuve["teardown"]["measured_after_pytest_exit"] is True
    assert preuve["governance_counters_before"] == preuve["governance_counters_after"]


def test_aucun_secret_dans_la_preuve() -> None:
    texte = PREUVE.read_text(encoding="utf-8").lower()
    for motif in ("password=", "bearer ", "token_sha256", "secret"):
        assert motif not in texte, motif
