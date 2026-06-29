# Lot 20 - Runbook rollback production `rag-ui`

Statut : runbook de preparation. Aucune commande n'a ete executee.

Ce document prepare un rollback pour une future fenetre de deploiement controlee. Il ne declenche aucun deploiement, aucune restauration et aucune migration.

## Preconditions

- Confirmation humaine explicite pour intervenir en production.
- Acces SSH valide avec host key connue.
- Incident ou validation rollback decidee par l'operateur.
- Backup horodate disponible et verifie.
- Aucun secret affiche dans terminal partage, rapport ou log copie.
- Aucune migration Chroma executee sauf lot futur explicitement approuve.

## Variables operateur

NE PAS EXECUTER SANS CONFIRMATION HUMAINE.

```bash
set -euo pipefail
COMPOSE_DIR="/srv/nexusreussite/rag-ui/compose"
BACKUP_ROOT="/srv/nexusreussite/backups"
TS="$(date -u +%Y%m%d_%H%M%S)"
BACKUP="$BACKUP_ROOT/rag-ui-lot20-$TS"
```

## Creation backup horodate

NE PAS EXECUTER SANS CONFIRMATION HUMAINE.

```bash
mkdir -p "$BACKUP"/{ingestor,ui,configs,data}
```

## Sauvegarde fichiers applicatifs

NE PAS EXECUTER SANS CONFIRMATION HUMAINE.

```bash
cp -a "$COMPOSE_DIR/ingestor/api.py" "$BACKUP/ingestor/api.py"
cp -a "$COMPOSE_DIR/ingestor/admin_api.py" "$BACKUP/ingestor/admin_api.py"
[ -f "$COMPOSE_DIR/ingestor/collection_config.py" ] && cp -a "$COMPOSE_DIR/ingestor/collection_config.py" "$BACKUP/ingestor/collection_config.py" || true
[ -f "$COMPOSE_DIR/ingestor/retrieval_contract_adapter.py" ] && cp -a "$COMPOSE_DIR/ingestor/retrieval_contract_adapter.py" "$BACKUP/ingestor/retrieval_contract_adapter.py" || true
cp -a "$COMPOSE_DIR/ui/app_v2.py" "$BACKUP/ui/app_v2.py"
```

## Sauvegarde configs

NE PAS EXECUTER SANS CONFIRMATION HUMAINE.

```bash
[ -f "$COMPOSE_DIR/configs/rag_collections.yml" ] && cp -a "$COMPOSE_DIR/configs/rag_collections.yml" "$BACKUP/configs/rag_collections.yml" || true
[ -f "$COMPOSE_DIR/configs/legacy_collection_mapping.yml" ] && cp -a "$COMPOSE_DIR/configs/legacy_collection_mapping.yml" "$BACKUP/configs/legacy_collection_mapping.yml" || true
```

`.env` et credentials doivent etre sauvegardes hors rapport, sans affichage de contenu, avec permissions restrictives.

## Sauvegarde `catalog.sqlite`

NE PAS EXECUTER SANS CONFIRMATION HUMAINE.

```bash
[ -f "$COMPOSE_DIR/data/catalog.sqlite" ] && cp -a "$COMPOSE_DIR/data/catalog.sqlite" "$BACKUP/data/catalog.sqlite" || true
```

## Sauvegarde volume Chroma en lecture seule

NE PAS EXECUTER SANS CONFIRMATION HUMAINE.

Adapter le nom exact du volume apres verification serveur.

```bash
docker run --rm \
  -v rag-ui_chroma:/chroma:ro \
  -v "$BACKUP":/backup \
  alpine tar czf /backup/chroma-volume.tgz -C /chroma .
```

## Verification backup

NE PAS EXECUTER SANS CONFIRMATION HUMAINE.

```bash
test -f "$BACKUP/ingestor/api.py"
test -f "$BACKUP/ingestor/admin_api.py"
test -f "$BACKUP/ui/app_v2.py"
find "$BACKUP" -maxdepth 3 -type f | sort
```

Ne pas afficher `.env`, credentials Google Drive, tokens ou contenus sensibles.

## Rollback fichiers applicatifs

NE PAS EXECUTER SANS CONFIRMATION HUMAINE.

```bash
cd "$COMPOSE_DIR"
docker compose stop ingestor ui
cp -a "$BACKUP/ingestor/api.py" ingestor/api.py
cp -a "$BACKUP/ingestor/admin_api.py" ingestor/admin_api.py
cp -a "$BACKUP/ui/app_v2.py" ui/app_v2.py
[ -f "$BACKUP/ingestor/collection_config.py" ] && cp -a "$BACKUP/ingestor/collection_config.py" ingestor/collection_config.py || rm -f ingestor/collection_config.py
[ -f "$BACKUP/ingestor/retrieval_contract_adapter.py" ] && cp -a "$BACKUP/ingestor/retrieval_contract_adapter.py" ingestor/retrieval_contract_adapter.py || rm -f ingestor/retrieval_contract_adapter.py
```

## Rollback configs

NE PAS EXECUTER SANS CONFIRMATION HUMAINE.

```bash
cd "$COMPOSE_DIR"
mkdir -p configs
[ -f "$BACKUP/configs/rag_collections.yml" ] && cp -a "$BACKUP/configs/rag_collections.yml" configs/rag_collections.yml || rm -f configs/rag_collections.yml
[ -f "$BACKUP/configs/legacy_collection_mapping.yml" ] && cp -a "$BACKUP/configs/legacy_collection_mapping.yml" configs/legacy_collection_mapping.yml || rm -f configs/legacy_collection_mapping.yml
```

## Rollback `catalog.sqlite`

NE PAS EXECUTER SANS CONFIRMATION HUMAINE.

```bash
[ -f "$BACKUP/data/catalog.sqlite" ] && cp -a "$BACKUP/data/catalog.sqlite" "$COMPOSE_DIR/data/catalog.sqlite"
```

## Rollback Chroma

NE PAS EXECUTER SANS CONFIRMATION HUMAINE.

Ce bloc est interdit pour Lot 20. Il ne devient applicable que si une migration Chroma future a ete explicitement approuvee et executee.

```bash
cd "$COMPOSE_DIR"
docker compose stop chroma
docker run --rm \
  -v rag-ui_chroma:/chroma \
  -v "$BACKUP":/backup \
  alpine sh -c 'rm -rf /chroma/* && tar xzf /backup/chroma-volume.tgz -C /chroma'
docker compose up -d chroma ingestor ui
```

## Redemarrage et post-check

NE PAS EXECUTER SANS CONFIRMATION HUMAINE.

```bash
cd "$COMPOSE_DIR"
docker compose up -d ingestor ui
curl -sS --fail https://rag-api.nexusreussite.academy/health
curl -sS --fail -I https://rag-ui.nexusreussite.academy/
curl -sS -i https://rag-api.nexusreussite.academy/collections | sed -n '1,20p'
```

Attendus :

- `/health` repond ;
- l'UI repond ;
- `/collections` sans token reste 401 ;
- logs sans secret ;
- aucune restauration Chroma sauf migration future explicitement approuvee.
