# Lot 19 - Plan de mise a jour production `rag-ui`

Statut : plan seulement, non execute.

## Condition d'entree

Ne pas deployer sans :

- acces SSH verifie avec host key connue ;
- sauvegarde ;
- diff prod/repo ;
- plan rollback ;
- verification post-deploiement ;
- absence de secrets dans logs et rapports.

## 1. Preflight

```bash
git branch --show-current
git rev-parse HEAD
git status --short
bash scripts/ci-local.sh
cd services/rag-engine && make lint && make typecheck && make test
```

Sur serveur, en lecture seule :

```bash
hostname
date
cd /srv/nexusreussite/rag-ui/compose
docker compose ps
docker compose logs --tail 100 ingestor
docker compose logs --tail 100 ui
curl -k -sS https://rag-api.nexusreussite.academy/health
curl -k -sS -I https://rag-ui.nexusreussite.academy/
```

Ne jamais afficher `.env`, tokens, cles Google Drive ou secrets HMAC.

## 2. Backup

Creer un dossier horodate :

```bash
TS="$(date -u +%Y%m%d_%H%M%S)"
BACKUP="/srv/nexusreussite/backups/rag-ui-lot19-$TS"
mkdir -p "$BACKUP"
```

Fichiers applicatifs :

```bash
cp -a /srv/nexusreussite/rag-ui/compose/ingestor/api.py "$BACKUP/api.py"
cp -a /srv/nexusreussite/rag-ui/compose/ingestor/admin_api.py "$BACKUP/admin_api.py"
cp -a /srv/nexusreussite/rag-ui/compose/ui/app_v2.py "$BACKUP/app_v2.py"
```

Donnees :

```bash
cp -a /srv/nexusreussite/rag-ui/compose/data/catalog.sqlite "$BACKUP/catalog.sqlite"
rsync -a /srv/nexusreussite/rag-ui/compose/data/uploads/ "$BACKUP/uploads/"
```

Secrets :

- sauvegarder `.env` sans le copier vers un rapport ;
- sauvegarder credentials Google Drive sans affichage ;
- verifier permissions `600` si necessaire.

Chroma :

```bash
docker run --rm \
  -v rag-ui_chroma:/chroma:ro \
  -v "$BACKUP":/backup \
  alpine tar czf /backup/chroma-volume.tgz -C /chroma .
```

Adapter le nom exact du volume apres `docker volume ls`.

## 3. Diff prod/repo

Depuis un checkout local propre du commit a deployer :

```bash
rsync -nci \
  services/rag-engine/src/ingestor/api.py \
  services/rag-engine/src/ingestor/admin_api.py \
  services/rag-engine/src/ui/app_v2.py \
  services/rag-engine/src/ingestor/collection_config.py \
  services/rag-engine/src/ingestor/retrieval_contract_adapter.py \
  services/rag-engine/configs/rag_collections.yml \
  services/rag-engine/configs/legacy_collection_mapping.yml \
  <serveur>:/srv/nexusreussite/rag-ui/compose/
```

La commande exacte doit etre ajustee a l'arborescence image/volume de prod. Ne pas utiliser `--delete`.

## 4. Deploiement cible

Copier uniquement les fichiers necessaires :

```bash
rsync -av \
  services/rag-engine/src/ingestor/api.py \
  services/rag-engine/src/ingestor/admin_api.py \
  services/rag-engine/src/ingestor/collection_config.py \
  services/rag-engine/src/ingestor/retrieval_contract_adapter.py \
  <serveur>:/srv/nexusreussite/rag-ui/compose/ingestor/

rsync -av \
  services/rag-engine/src/ui/app_v2.py \
  <serveur>:/srv/nexusreussite/rag-ui/compose/ui/

rsync -av \
  services/rag-engine/configs/rag_collections.yml \
  services/rag-engine/configs/legacy_collection_mapping.yml \
  <serveur>:/srv/nexusreussite/rag-ui/compose/configs/
```

Rebuild cible :

```bash
cd /srv/nexusreussite/rag-ui/compose
docker compose build ingestor ui
docker compose up -d ingestor ui
```

Ne pas toucher a Chroma si aucune migration n'est executee.

## 5. Post-check

```bash
curl -k -sS https://rag-api.nexusreussite.academy/health
curl -k -sS -I https://rag-ui.nexusreussite.academy/
```

Checks fonctionnels :

- UI HTTP 200 ou BasicAuth attendu ;
- `/collections` retourne 401 sans token ;
- `/admin/reindex` retourne 401 sans auth si token configure ;
- upload markdown controle dans une collection education ;
- recherche filtree education ;
- recherche Web3 isolee ;
- `rag_divers`/quarantine non retrievable ;
- logs sans secret.

## 6. Rollback

```bash
cd /srv/nexusreussite/rag-ui/compose
docker compose stop ingestor ui
cp -a "$BACKUP/api.py" ingestor/api.py
cp -a "$BACKUP/admin_api.py" ingestor/admin_api.py
cp -a "$BACKUP/app_v2.py" ui/app_v2.py
cp -a "$BACKUP/catalog.sqlite" data/catalog.sqlite
rsync -a --delete "$BACKUP/uploads/" data/uploads/
docker compose up -d ingestor ui
```

Si Chroma a ete modifie pendant une future migration :

```bash
docker compose stop chroma
docker run --rm -v rag-ui_chroma:/chroma -v "$BACKUP":/backup alpine sh -c 'rm -rf /chroma/* && tar xzf /backup/chroma-volume.tgz -C /chroma'
docker compose up -d chroma ingestor ui
```

Verifier ensuite `/health`, UI, recherche controlee et logs.

## Statut Lot 19

Non deploye : acces SSH non valide (`Host key verification failed`), donc application du plan repoussee.
