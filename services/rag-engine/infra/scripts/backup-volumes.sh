#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

backup_root=${BACKUP_DIR:-./backups}
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$backup_root"

# rag_ingestion_artifacts_data (LOT44f/ADR-0031) : volume du plan de
# contrôle d'ingestion gouvernée, strictement opt-in (docker-compose.
# ingestion.yml) — n'existe pas tant que ce plan n'a jamais été démarré. La
# vérification d'existence ci-dessous s'applique à tous les volumes pour
# éviter qu'un volume absent soit créé vide par effet de bord de `docker
# run -v` puis sauvegardé comme une archive vide silencieusement acceptée
# (revue PR#90).
volumes=(rag_chroma_data rag_ollama_data rag_n8n_data rag_pgvector_data rag_redis_data rag_admin_data rag_ingestion_artifacts_data)
for vol in "${volumes[@]}"; do
  if ! docker volume inspect "$vol" >/dev/null 2>&1; then
    echo "Skipping ${vol}: volume does not exist (never started)"
    continue
  fi
  archive="${backup_root}/${vol}-${timestamp}.tgz"
  echo "Creating archive ${archive}"
  docker run --rm \
    -v "${vol}:/data:ro" \
    -v "${backup_root}:/backup" \
    busybox \
    sh -c "cd /data && tar czf \"/backup/$(basename "$archive")\" ."
  echo "Archive ready: ${archive}"
done

echo "Backup completed in ${backup_root}"
