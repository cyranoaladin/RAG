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
curl -sS --fail https://rag-api.nexusreussite.academy/health
curl -sS --fail -I https://rag-ui.nexusreussite.academy/
test -f .env
grep -q '^RAG_ENV=production$' .env
grep -q '^RAG_ENGINE_CONFIG_DIR=/app/configs$' .env
grep -q '^RAG_CONFIGS_HOST_DIR=./configs$' .env
grep -q '^ALLOW_UNAUTHENTICATED_ADMIN_DEV=false$' .env
test -f configs/rag_collections.yml
test -f configs/legacy_collection_mapping.yml
python3 - <<'PY'
import json
import subprocess

rendered = subprocess.run(
    ["docker", "compose", "config", "--format", "json"],
    check=True,
    stdout=subprocess.PIPE,
    text=True,
).stdout
config = json.loads(rendered)
volumes = config["services"]["ingestor"].get("volumes", [])
expected = {
    "type": "bind",
    "source": "/srv/nexusreussite/rag-ui/compose/configs",
    "target": "/app/configs",
    "read_only": True,
}
if not any(
    volume.get("type") == expected["type"]
    and volume.get("source") == expected["source"]
    and volume.get("target") == expected["target"]
    and volume.get("read_only") == expected["read_only"]
    for volume in volumes
):
    raise SystemExit("missing read-only ingestor configs bind mount")
PY
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
mkdir -p "$BACKUP/ingestor" "$BACKUP/ui" "$BACKUP/configs"
cp -a /srv/nexusreussite/rag-ui/compose/ingestor/api.py "$BACKUP/ingestor/api.py"
cp -a /srv/nexusreussite/rag-ui/compose/ingestor/admin_api.py "$BACKUP/ingestor/admin_api.py"
cp -a /srv/nexusreussite/rag-ui/compose/ui/app_v2.py "$BACKUP/ui/app_v2.py"
[ -f /srv/nexusreussite/rag-ui/compose/ingestor/collection_config.py ] && cp -a /srv/nexusreussite/rag-ui/compose/ingestor/collection_config.py "$BACKUP/ingestor/collection_config.py" || true
[ -f /srv/nexusreussite/rag-ui/compose/ingestor/retrieval_contract_adapter.py ] && cp -a /srv/nexusreussite/rag-ui/compose/ingestor/retrieval_contract_adapter.py "$BACKUP/ingestor/retrieval_contract_adapter.py" || true
[ -f /srv/nexusreussite/rag-ui/compose/configs/rag_collections.yml ] && cp -a /srv/nexusreussite/rag-ui/compose/configs/rag_collections.yml "$BACKUP/configs/rag_collections.yml" || true
[ -f /srv/nexusreussite/rag-ui/compose/configs/legacy_collection_mapping.yml ] && cp -a /srv/nexusreussite/rag-ui/compose/configs/legacy_collection_mapping.yml "$BACKUP/configs/legacy_collection_mapping.yml" || true
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
  services/rag-engine/src/ingestor/collection_config.py \
  services/rag-engine/src/ingestor/retrieval_contract_adapter.py \
  <serveur>:/srv/nexusreussite/rag-ui/compose/ingestor/

rsync -nci \
  services/rag-engine/configs/rag_collections.yml \
  services/rag-engine/configs/legacy_collection_mapping.yml \
  <serveur>:/srv/nexusreussite/rag-ui/compose/configs/

rsync -nci \
  services/rag-engine/src/ui/app_v2.py \
  <serveur>:/srv/nexusreussite/rag-ui/compose/ui/
```

La commande exacte doit etre ajustee a l'arborescence image/volume de prod. Ne pas utiliser `--delete`.

## 4. Deploiement cible

Copier uniquement les fichiers necessaires :

```bash
ssh <serveur> 'cd /srv/nexusreussite/rag-ui/compose && mkdir -p configs && grep -q "^RAG_ENV=production$" .env && grep -q "^RAG_ENGINE_CONFIG_DIR=/app/configs$" .env && grep -q "^RAG_CONFIGS_HOST_DIR=./configs$" .env && grep -q "^ALLOW_UNAUTHENTICATED_ADMIN_DEV=false$" .env'
ssh <serveur> 'cd /srv/nexusreussite/rag-ui/compose && python3 - <<'"'"'PY'"'"'
import json
import subprocess

rendered = subprocess.run(
    ["docker", "compose", "config", "--format", "json"],
    check=True,
    stdout=subprocess.PIPE,
    text=True,
).stdout
config = json.loads(rendered)
volumes = config["services"]["ingestor"].get("volumes", [])
expected = {
    "type": "bind",
    "source": "/srv/nexusreussite/rag-ui/compose/configs",
    "target": "/app/configs",
    "read_only": True,
}
if not any(
    volume.get("type") == expected["type"]
    and volume.get("source") == expected["source"]
    and volume.get("target") == expected["target"]
    and volume.get("read_only") == expected["read_only"]
    for volume in volumes
):
    raise SystemExit("missing read-only ingestor configs bind mount")
PY'

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

Note chemin configs :

- Layout repo versionne : le compose est execute depuis `services/rag-engine/infra`; la source hote attendue est `services/rag-engine/configs`; la syntaxe compose versionnee est `${RAG_CONFIGS_HOST_DIR:-../configs}:/app/configs:ro`, avec le defaut `../configs`.
- Layout prod historique : le compose est execute depuis `/srv/nexusreussite/rag-ui/compose`; la source hote attendue est `/srv/nexusreussite/rag-ui/compose/configs`; la syntaxe attendue dans `.env` est `RAG_CONFIGS_HOST_DIR=./configs`, rendue par Compose comme `/srv/nexusreussite/rag-ui/compose/configs`.
- Si `services/rag-engine/infra/docker-compose.prod.yml` est copie tel quel dans `/srv/nexusreussite/rag-ui/compose`, il ne doit pas etre utilise sans `RAG_CONFIGS_HOST_DIR=./configs`, sinon le defaut `../configs` pointerait vers `/srv/nexusreussite/rag-ui/configs`.

## 5. Post-check

```bash
curl -sS --fail https://rag-api.nexusreussite.academy/health
curl -sS --fail -I https://rag-ui.nexusreussite.academy/
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
mkdir -p configs
cp -a "$BACKUP/ingestor/api.py" ingestor/api.py
cp -a "$BACKUP/ingestor/admin_api.py" ingestor/admin_api.py
cp -a "$BACKUP/ui/app_v2.py" ui/app_v2.py
[ -f "$BACKUP/ingestor/collection_config.py" ] && cp -a "$BACKUP/ingestor/collection_config.py" ingestor/collection_config.py || rm -f ingestor/collection_config.py
[ -f "$BACKUP/ingestor/retrieval_contract_adapter.py" ] && cp -a "$BACKUP/ingestor/retrieval_contract_adapter.py" ingestor/retrieval_contract_adapter.py || rm -f ingestor/retrieval_contract_adapter.py
[ -f "$BACKUP/configs/rag_collections.yml" ] && cp -a "$BACKUP/configs/rag_collections.yml" configs/rag_collections.yml || rm -f configs/rag_collections.yml
[ -f "$BACKUP/configs/legacy_collection_mapping.yml" ] && cp -a "$BACKUP/configs/legacy_collection_mapping.yml" configs/legacy_collection_mapping.yml || rm -f configs/legacy_collection_mapping.yml
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
