"""Test hermétique de la preuve SYNC_INCREMENTALE (sans Docker ni réseau)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "scripts/qualification"))

PREUVE = RACINE / "docs/reports/evidence/incremental_sync_proof.json"
EMPREINTE = RACINE / "docs/reports/evidence/incremental_sync_proof.sha256"


def test_verdict_derive_du_statut_scelle() -> None:
    import verify_incremental_sync as scelleur

    statut = json.loads(PREUVE.read_text(encoding="utf-8"))["verification_status"]
    assert scelleur.verifier_seulement() == (0 if statut == "VERIFIED" else 1)


def test_empreinte_scellee() -> None:
    octets = PREUVE.read_bytes()
    assert EMPREINTE.read_text(encoding="utf-8").split()[0] == hashlib.sha256(octets).hexdigest()


def test_observations_reelles_et_residus_comptes_apres_pytest() -> None:
    preuve = json.loads(PREUVE.read_text(encoding="utf-8"))
    assert preuve["observations"]["real_engine"]["mock_detected"] is False
    assert preuve["teardown"]["measured_after_pytest_exit"] is True
    assert preuve["governance_counters_before"] == preuve["governance_counters_after"]


def test_aucun_secret_dans_la_preuve() -> None:
    texte = PREUVE.read_text(encoding="utf-8").lower()
    for motif in ("password=", "bearer ", "token_sha256", "secret"):
        assert motif not in texte, motif
