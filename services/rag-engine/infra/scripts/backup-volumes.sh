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
#
# Remédiation revue PR#90 (Cubic P2, revue incrémentale) : ces noms sont
# les clés Compose déclarées dans docker-compose.v2.yml/docker-compose.
# ingestion.yml (ex. `rag_ingestion_artifacts_data`), jamais le nom RÉEL du
# volume Docker — `docker compose up` sans `-p`/`COMPOSE_PROJECT_NAME`
# explicite préfixe systématiquement chaque volume nommé du nom du projet
# (dérivé du répertoire du fichier Compose), donnant par exemple
# `infra_rag_ingestion_artifacts_data`, jamais le nom nu. Un
# `docker volume inspect "$vol"` sur le nom nu échouait alors
# silencieusement ("Skipping ... does not exist"), même quand le volume
# réel — sous un autre nom — contenait des données à sauvegarder : jamais
# une erreur bruyante, une sauvegarde qui semble réussir tout en omettant
# le volume réel.
#
# Résolution par étiquettes Compose (jamais un simple filtrage par nom) :
# `docker compose` étiquette systématiquement chaque volume qu'il crée avec
# `com.docker.compose.project=<projet>` et `com.docker.compose.volume=
# <clé>` — interroger ces deux étiquettes ensemble identifie le volume réel
# de CE projet, sans confusion possible avec un volume de même clé créé par
# un tout autre projet Compose sur le même hôte (constaté empiriquement sur
# cette machine partagée : plusieurs projets sans rapport y possèdent
# chacun un volume nommé différemment mais partageant la même clé Compose,
# ex. "rag_chroma_data" — un simple filtrage par sous-chaîne de nom aurait
# été soit ambigu, soit aurait pu sélectionner le volume d'un tout autre
# projet). Le nom de projet attendu reproduit la résolution par défaut de
# Compose, dans le même ordre de priorité que Compose lui-même :
# ``COMPOSE_PROJECT_NAME`` déjà présent dans l'environnement du shell
# (priorité la plus haute, ex. surchargé explicitement par un opérateur ou
# un test) ; sinon la même déclaration lue dans ``infra/.env`` — le même
# fichier que celui chargé par `make v2-up`/`make v2-ingestion-up` via
# ``--env-file`` ; sinon le nom du répertoire contenant les fichiers
# Compose, en minuscules. Repli explicite sur le nom nu (ancien
# comportement) uniquement si aucun volume étiqueté n'est trouvé, pour ne
# jamais casser un volume créé manuellement hors Compose.
compose_project_name="${COMPOSE_PROJECT_NAME:-}"
if [[ -z "$compose_project_name" && -f "infra/.env" ]]; then
  compose_project_name="$(grep -E '^COMPOSE_PROJECT_NAME=' infra/.env | tail -n1 | cut -d= -f2- || true)"
fi
if [[ -z "${compose_project_name:-}" ]]; then
  compose_project_name="$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9_-]//g')"
fi

volumes=(rag_chroma_data rag_ollama_data rag_n8n_data rag_pgvector_data rag_redis_data rag_admin_data rag_ingestion_artifacts_data)
for vol_key in "${volumes[@]}"; do
  real_volume_name="$(docker volume ls \
    --filter "label=com.docker.compose.project=${compose_project_name}" \
    --filter "label=com.docker.compose.volume=${vol_key}" \
    --format '{{.Name}}' | head -n1)"
  if [[ -z "$real_volume_name" ]] && docker volume inspect "$vol_key" >/dev/null 2>&1; then
    real_volume_name="$vol_key"
  fi
  if [[ -z "$real_volume_name" ]]; then
    echo "Skipping ${vol_key}: volume does not exist (never started)"
    continue
  fi
  archive="${backup_root}/${vol_key}-${timestamp}.tgz"
  echo "Creating archive ${archive} (volume: ${real_volume_name})"
  docker run --rm \
    -v "${real_volume_name}:/data:ro" \
    -v "${backup_root}:/backup" \
    busybox \
    sh -c "cd /data && tar czf \"/backup/$(basename "$archive")\" ."
  echo "Archive ready: ${archive}"
done

echo "Backup completed in ${backup_root}"
