#!/usr/bin/env bash
# continuous-ingestion.sh — LOT 28 (ADR-0016)
# Point d'entree cron/systemd pour une passe d'ingestion continue.
# Aucun chemin absolu machine-local : la racine du depot est derivee de
# RAG_ROOT (defaut : deux niveaux au-dessus de ce script).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAG_ROOT="${RAG_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
PEDAGO_DIR="${RAG_ROOT}/services/rag-pedago"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LOG_DIR="${RAG_ROOT}/services/rag-pedago/data/reports"
mkdir -p "${LOG_DIR}"

cd "${PEDAGO_DIR}"
echo "[$(date -Is)] continuous-ingestion: run start" >> "${LOG_DIR}/continuous_ingestion.log"
PYTHONPATH="${PEDAGO_DIR}" "${PYTHON_BIN}" -m agents.continuous_orchestrator --run \
  >> "${LOG_DIR}/continuous_ingestion.log" 2>&1
echo "[$(date -Is)] continuous-ingestion: run end" >> "${LOG_DIR}/continuous_ingestion.log"
