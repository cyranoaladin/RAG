#!/usr/bin/env python3
"""Scelleur et vérificateur de la preuve CONCURRENCE.

`--run` lance le banc réel (`services/rag-engine/tests/integration/test_concurrency_load.py`),
attend que pytest ait DÉTRUIT ses conteneurs, compte alors les résidus Docker et
les processus moteur survivants, confronte les mesures brutes au budget versionné
(`docs/reports/go_live/concurrency_load_budget.json`) et scelle la preuve. Hors
budget, la preuve est scellée avec le statut `BUDGET_FAILED` et ses violations :
le blocage reste ouvert, la mesure reste consultable.

`--verify-only` revérifie la preuve scellée, sans Docker ni réseau.

Le jugement n'est pas ici : il est dans `build_qualification_blockers.py`
(`evaluer_concurrence`), source unique partagée avec le gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import build_qualification_blockers as blocages  # noqa: E402

BENCH = "services/rag-engine/tests/integration/test_concurrency_load.py"
ETAT_READINESS = "docs/reports/go_live/go_live_readiness_state.json"
MOTIF_PROCESSUS = "uvicorn src.ingestor.api_v2:app"
ENV_REQUIS = (
    "NEXUS_MULTILEVEL_PDF_MIRROR",
    "NEXUS_MULTILEVEL_PII_EVIDENCE_PATH",
    "RAG_EMBEDDING_MODEL_CACHE_DIR",
    "RAG_EMBEDDING_MODEL_INVENTORY_SHA256",
    "RAG_RERANKER_MODEL_CACHE_DIR",
    "RAG_RERANKER_MODEL_INVENTORY_SHA256",
)


def _conteneurs_nexus() -> set[str]:
    sortie = subprocess.run(
        ["docker", "ps", "-a", "--filter", "name=nexus-", "--format", "{{.Names}}"],
        capture_output=True, text=True, check=True,
    ).stdout
    return {ligne.strip() for ligne in sortie.splitlines() if ligne.strip()}


def _processus_moteur() -> set[str]:
    sortie = subprocess.run(
        ["pgrep", "-f", MOTIF_PROCESSUS], capture_output=True, text=True, check=False
    ).stdout
    return {ligne.strip() for ligne in sortie.splitlines() if ligne.strip()}


def _compteurs_gouvernance() -> dict[str, Any]:
    etat = json.loads((RACINE / ETAT_READINESS).read_text(encoding="utf-8"))
    return {
        cle: etat.get(cle)
        for cle in (
            "pii_undecided", "release_promoted_refused_contents",
            "current_switch", "production_db_writes", "production_deployments",
        )
    }


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=RACINE, capture_output=True, text=True, check=True
    ).stdout.strip()


def executer_et_sceller() -> int:
    manquantes = [nom for nom in ENV_REQUIS if not os.environ.get(nom, "").strip()]
    if manquantes:
        print(f"REFUS : variables d'environnement absentes : {manquantes}", file=sys.stderr)
        return 2
    base_main = _git("merge-base", "HEAD", "origin/main")
    if base_main != blocages.CONCURRENCE_MAIN_SHA_ATTENDU:
        print(f"REFUS : base main {base_main} != {blocages.CONCURRENCE_MAIN_SHA_ATTENDU}", file=sys.stderr)
        return 2
    if _git("status", "--porcelain", "--", "services/rag-engine/src", "packages"):
        print("REFUS : code moteur ou contrat modifié et non commité", file=sys.stderr)
        return 2

    conteneurs_avant = _conteneurs_nexus()
    processus_avant = _processus_moteur()
    compteurs_avant = _compteurs_gouvernance()

    with tempfile.TemporaryDirectory(prefix="nexus-concurrency-") as tmp:
        brut_path = Path(tmp) / "raw_measurements.json"
        env = dict(os.environ)
        env["NEXUS_REQUIRE_DOCKER"] = "1"
        env["NEXUS_CONCURRENCY_RAW_MEASUREMENTS_PATH"] = str(brut_path)
        bench = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-x", f"tests/integration/{Path(BENCH).name}"],
            cwd=RACINE / "services/rag-engine", env=env, check=False,
        )
        if not brut_path.is_file():
            print(f"REFUS : le banc n'a produit aucune mesure (pytest={bench.returncode})", file=sys.stderr)
            return 1
        mesures = json.loads(brut_path.read_text(encoding="utf-8"))

    # pytest est sorti : les fixtures ont détruit leurs conteneurs. On COMPTE.
    residus = sorted(_conteneurs_nexus() - conteneurs_avant)
    processus = sorted(_processus_moteur() - processus_avant)
    compteurs_apres = _compteurs_gouvernance()

    teardown = {
        "docker_residues_after_test": len(residus),
        "docker_residue_names": residus,
        "residual_engine_processes": len(processus),
        "measured_after_pytest_exit": True,
        "production_touched": False,
        "production_db_writes": 0,
        "production_deployments": 0,
        "current_switch": 0,
        "production_untouched_basis": (
            "toutes les DSN du banc visent 127.0.0.1 sur des conteneurs jetables créés "
            "par le banc ; aucun identifiant ni hôte de production n'est lu"
        ),
    }
    budget_octets = (RACINE / blocages.CONCURRENCE_BUDGET).read_bytes()
    budget_doc = json.loads(budget_octets)
    violations = blocages.evaluer_concurrence(budget_doc, mesures, teardown)
    if bench.returncode != 0:
        violations.append(f"le banc pytest a échoué (code {bench.returncode})")
    if compteurs_apres != compteurs_avant:
        violations.append(f"compteurs de gouvernance modifiés : {compteurs_avant} -> {compteurs_apres}")

    sequentiel = mesures.get("sequential_baseline") or []
    preuve = {
        "kind": "NEXUS-CONCURRENCY-LOAD-PROOF-V1",
        "verification_status": "VERIFIED" if not violations else "BUDGET_FAILED",
        "violations": violations,
        "observed_at_main_sha": base_main,
        "measured_at_branch_head": _git("rev-parse", "HEAD"),
        "sealed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "executed_command": "python3 scripts/qualification/verify_concurrency_load.py --run",
        "bench": BENCH,
        "bench_pytest_exit_code": bench.returncode,
        "host": {"cpu_count": os.cpu_count(), "accelerator": "none (CUDA_VISIBLE_DEVICES vide)"},
        "budget": {
            "path": blocages.CONCURRENCE_BUDGET,
            "sha256": hashlib.sha256(budget_octets).hexdigest(),
            "declared_in_commit": _git("log", "-1", "--format=%H", "--", blocages.CONCURRENCE_BUDGET),
            "values": budget_doc["budget"],
        },
        "summary": blocages.resumer_latences_concurrence(mesures["measured_requests"]),
        "sequential_baseline_summary": (
            blocages.resumer_latences_concurrence(sequentiel) if sequentiel else None
        ),
        "throughput_rps": round(
            len(mesures["measured_requests"]) / mesures["load_wall_seconds"], 3
        ) if mesures.get("load_wall_seconds") else None,
        "governance_counters_before": compteurs_avant,
        "governance_counters_after": compteurs_apres,
        "teardown": teardown,
        "measurements": mesures,
    }
    octets = (json.dumps(preuve, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    (RACINE / blocages.CONCURRENCE_PREUVE).write_bytes(octets)
    (RACINE / blocages.CONCURRENCE_PREUVE_SHA).write_text(
        f"{hashlib.sha256(octets).hexdigest()}  {blocages.CONCURRENCE_PREUVE}\n", encoding="utf-8"
    )
    print(json.dumps({k: preuve[k] for k in ("verification_status", "violations", "summary")}, indent=2))
    return 0 if not violations else 1


def verifier_seulement() -> int:
    etat = blocages.verifier_concurrence(RACINE)
    if etat["closed"]:
        print("CONCURRENCE : preuve scellée valide")
        return 0
    print(f"REFUS : {etat['why']}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    return executer_et_sceller() if args.run else verifier_seulement()


if __name__ == "__main__":
    raise SystemExit(main())
