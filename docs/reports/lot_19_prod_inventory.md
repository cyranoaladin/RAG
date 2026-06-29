# Lot 19 - Inventaire production `rag-ui`

## Perimetre

Production visee : `https://rag-ui.nexusreussite.academy` et API publique `https://rag-api.nexusreussite.academy`.

## Acces live

SSH live non disponible dans ce contexte Codex.

Commande tentee en lecture seule :

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 rag-ui.nexusreussite.academy 'hostname; date; docker ps; ls -la /srv/nexusreussite/rag-ui; find /srv/nexusreussite/rag-ui -maxdepth 3 -type f | sort | sed -n "1,240p"'
```

Resultat : `Host key verification failed.`

Aucun contournement de verification d'host key n'a ete effectue.

## Probes publics non sensibles

```bash
curl -k -sS -I https://rag-ui.nexusreussite.academy/
```

Resultat observe le 29 juin 2026, heure Tunis :

```text
HTTP/2 200
server: nginx
content-type: text/html
cache-control: no-cache
x-content-type-options: nosniff
referrer-policy: no-referrer
x-frame-options: SAMEORIGIN
permissions-policy: geolocation=(), microphone=(), camera=()
strict-transport-security: max-age=63072000; includeSubDomains
```

```bash
curl -k -sS https://rag-api.nexusreussite.academy/health
```

```json
{"status":"healthy"}
```

```bash
curl -k -sS -i https://rag-api.nexusreussite.academy/collections
```

Resultat : `HTTP/2 401`, detail `Unauthorized`. Cela confirme que `/collections` est protege sans token public.

## Snapshot prod versionne

Source utilisee faute d'acces SSH live :

```text
services/rag-engine/rag-ui-nexusreussite-academy-tree-20260613_222121.txt
```

Elements presents dans le snapshot :

- racine `/srv/nexusreussite/rag-ui` ;
- `compose/docker-compose.yml` et `compose/docker-compose.yml.bak` ;
- code ingestor sous `compose/ingestor/` ;
- code UI sous `compose/ui/` ;
- fichiers `.bak` multiples pour `api.py`, `drive_sync.py`, `app_v2.py` ;
- dossiers `__pycache__` sous ingestor et UI ;
- dossier `creds/` et fichier Google Drive signale dans le snapshot, non lu et non expose ;
- dossier `data/uploads/` ;
- logs applicatifs.

## Services actifs

Non verifies live faute d'acces SSH. Les probes publics indiquent au minimum :

- reverse proxy Nginx actif ;
- UI HTTP accessible ;
- API health accessible ;
- endpoint collections protege.

`docker ps`, `docker compose ps` et logs `ingestor`/`ui` restent a collecter sur serveur.

## Fichiers prod differents du repo

Non verifiable live. Le snapshot montre des fichiers historiques et backups qui ne sont pas des sources propres du repo :

- `compose/ingestor/api.py.bak_*` ;
- `compose/ingestor/drive_sync.py.bak_*` ;
- `compose/ui/app_v2.py.bak_*` ;
- `compose/docker-compose.yml.bak` ;
- `__pycache__/`.

Un diff prod/repo doit etre execute avant deploiement.

## Collections Chroma

Collections historiques attendues selon code et cahier des charges :

- `rag_education` ;
- `rag_francais_premiere` ;
- `rag_maths_premiere` ;
- `rag_web3` ;
- `rag_divers`.

Non detectees live faute d'acces admin/SSH. Lot 19 ajoute un mapping versionne vers les collections Nexus et ne renomme aucune collection physique.

## Volumes et donnees

Non inspectes live. Volumes critiques a sauvegarder :

- volume Chroma ;
- `catalog.sqlite` ;
- uploads ;
- credentials Google Drive sans affichage ;
- `.env` sans affichage.

## Risques

| Risque | Niveau | Mitigation |
|---|---:|---|
| Confusion `rag-local` vs Nexus pgvector | Eleve | Docs Lot 19 + mapping explicite. |
| Collection arbitraire via client | Eleve | Refus serveur des collections inconnues. |
| Admin sans token en production | Eleve | `_admin_guard()` retourne 503 si token absent en `RAG_ENV=production`. |
| `/admin/reindex` sans auth | Eleve | Route protegee par `_admin_guard()`. |
| Backups et pycache en prod | Moyen | Inventaire et nettoyage separe apres backup. |
| Migration Chroma destructive | Eleve | Aucune migration physique dans Lot 19. |

## Plan rollback synthetique

1. Arreter uniquement `ingestor` et `ui`.
2. Restaurer les fichiers applicatifs backups :
   - `compose/ingestor/api.py` ;
   - `compose/ingestor/admin_api.py` ;
   - `compose/ui/app_v2.py`.
3. Restaurer `catalog.sqlite` si modifie.
4. Restaurer volume Chroma seulement si migration de donnees executee.
5. Redemarrer `ingestor` et `ui`.
6. Verifier `/health`, UI HTTP, logs sans secrets et recherche controlee.

Lot 19 ne deploie pas en production.
