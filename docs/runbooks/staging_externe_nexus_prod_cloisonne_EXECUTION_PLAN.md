# Plan d'exécution — Staging cloisonné sur `nexus-prod` (mode A)

> **Aucune commande de ce document n'est exécutée sans l'autorisation explicite de l'opérateur :**
> `SSH_STAGING_AUTHORIZED sur nexus-prod pour le commit <SHA>`.
> Sans elle : aucune connexion, pas même en lecture.

Complète `docs/runbooks/staging_externe.md` (secrets § 3, recette § 6, rollback § 8, preuve § 10) pour le cas
particulier où l'hôte de staging **est** la machine de production. Le cloisonnement y est donc la première exigence.

## 0. Principes de cloisonnement (non négociables)

| Règle | Comment elle est tenue |
|---|---|
| Aucun objet de production touché | projet Compose dédié `-p nexus-staging` ; Compose préfixe réseaux, conteneurs et volumes |
| Aucune base de production | service `pgvector` **propre au staging**, volume `nexus-staging_rag_pgvector_data` ; aucune DSN de production n'est lue ni connue |
| Aucune exposition publique | ports liés à `127.0.0.1` ; **Nginx n'est pas modifié**, aucun DNS, aucun certificat ; accès par tunnel SSH uniquement |
| Aucun current switch | aucun lien symbolique `current`, aucun fichier de release de production, aucun service systemd touché |
| Aucun secret partagé | secrets produits sur place par `prepare_staging_environment.py`, distincts de la production, `0600`, jamais affichés |
| Réversible | arrêt par `down` ; suppression explicite, décidée, du volume de staging en fin d'exercice |

Interdits pendant tout l'exercice : `docker compose down -v` hors projet `nexus-staging`, `--remove-orphans`,
`docker system prune`, `docker volume prune`, `systemctl restart|reload` de quoi que ce soit, édition de
`/etc/nginx`, lecture d'un `.env` de production, toute commande `docker` sans `-p nexus-staging` sauf lecture (`ps`, `ls`).

## 1. Ports, volumes, variables

Ports **proposés** (différents des défauts du Compose pour ne pas heurter la production ; à confirmer libres en phase 0) :

| Service | Variable | Proposé | Défaut du Compose | Liaison |
|---|---|---|---|---|
| API de retrieval | `INGESTOR_PORT` | 18003 | 8001 | `127.0.0.1` |
| PostgreSQL/pgvector | `PGVECTOR_PORT` | 15435 | 5435 | `127.0.0.1` |
| Prometheus | `PROMETHEUS_PORT` | 19191 | 19091 | `127.0.0.1` |

Volumes nommés créés par le projet : `nexus-staging_rag_pgvector_data`, `nexus-staging_rag_prometheus_data`.
Montages en lecture seule : configs du dépôt, registre de releases, corpus servables, `api-clients.json`, artefacts E5 et reranker.

Variables requises par le Compose (**noms seuls** ; la liste fait autorité dans
`docs/reports/evidence/external_staging_proof.json`, dérivée du Compose) :
`PGVECTOR_PASSWORD`, `PGVECTOR_RETRIEVAL_PASSWORD`, `PGVECTOR_REVIEW_PASSWORD`, `PGVECTOR_PUBLISHER_PASSWORD`,
`PG_RAG_DSN`, `PG_REVIEW_DSN`, `RAG_BFF_SERVICE_TOKEN`, `RAG_ACCESS_LOG_HMAC_SECRET`, `NEXUS_INTERNAL_TOKEN_SECRET`,
`NEXUS_INTERNAL_TOKEN_ISSUER`, `NEXUS_INTERNAL_TOKEN_AUDIENCE`, `NEXUS_SSO_ISSUER`, `NEXUS_SSO_AUDIENCE`,
`RAG_EMBEDDING_MODEL_INVENTORY_SHA256`, `RAG_RERANKER_MODEL_INVENTORY_SHA256`, `RAG_RELEASE_REGISTRY_SHA256`,
`RAG_SERVABLE_CORPUS_INDEX_SHA256`, `RAG_SERVABLE_CORPUS_HOST_DIR`, `RAG_API_CLIENTS_HOST_FILE`,
`RAG_EMBEDDING_MODEL_ARTIFACT_HOST_DIR`, `RAG_RERANKER_MODEL_ARTIFACT_HOST_DIR`.
Toutes sont écrites par le producteur de secrets dans `staging.env` ; aucune n'est saisie à la main ni affichée.

## 2. Faits que seul l'opérateur peut établir avant le jour J

1. **Source de l'index de staging** — à choisir, rien n'est inventé :
   (a) ingestion gouvernée de la release multilevel scellée (11 PDF, 353 chunks) par les workers, contre la base de staging ; ou
   (b) restauration d'un `pg_dump -Fc` de la base vectorielle de staging locale `nexus_vector_staging_a_…` (55 251 vecteurs), si elle est remise en service.
2. Le **répertoire de corpus servables** et l'empreinte de son index ; l'empreinte du **registre de releases**.
3. Le répertoire d'accueil (proposé : `/srv/nexus-staging`, propriétaire non-root) et la fenêtre horaire (hors heures d'usage : l'inférence E5 consomme 2 CPU et jusqu'à 8 Gio).

## 3. Phases, commandes et points d'arrêt

Chaque phase se termine par un **point d'arrêt** : je rapporte, l'opérateur dit de continuer.

### Phase 0 — Reconnaissance, lecture seule
```bash
ssh nexus-prod 'hostname; nproc; free -g; df -h / /srv /var/lib/docker 2>/dev/null; uptime'
ssh nexus-prod 'docker compose ls; docker ps --format "{{.Names}}\t{{.Ports}}\t{{.Status}}"'
ssh nexus-prod 'docker network ls --format "{{.Name}}"; docker volume ls --format "{{.Name}}" | grep -i nexus-staging || true'
ssh nexus-prod 'ss -ltn | grep -E ":(18003|15435|19191)\b" || echo PORTS_LIBRES'
```
```bash
install -d -m 0700 ~/nexus-staging-proof          # sur le poste de travail, hors dépôt
# Photographie AVANT : servira de preuve « zéro production touchée » et « zéro current switch » en phase 7
ssh nexus-prod 'docker ps --no-trunc --format "{{.ID}} {{.Names}} {{.Image}} {{.CreatedAt}}" | sort' > ~/nexus-staging-proof/prod_containers_before.txt
ssh nexus-prod 'find /srv /opt -maxdepth 4 -type l -name "current*" -printf "%p -> %l\n" 2>/dev/null | sort' > ~/nexus-staging-proof/current_links_before.txt
ssh nexus-prod 'sha256sum /etc/nginx/nginx.conf /etc/nginx/sites-enabled/* 2>/dev/null | sort' > ~/nexus-staging-proof/nginx_before.txt
```
**Sauvegarde préalable** : ce plan n'écrit rien en production, et ne lit aucune base de production (il n'en connaît pas
les identifiants, et ne doit pas les connaître). La garantie préalable est donc double : la photographie ci-dessus, et
votre confirmation qu'une sauvegarde de production récente existe selon `docs/runbooks/rollback.md`. **Sans cette
confirmation, arrêt.**

Aucun fichier d'environnement, aucun secret, aucune base n'est lu. **Arrêt** si : un port proposé est pris, un projet
`nexus-staging` existe déjà, < 12 Gio de RAM libre, < 25 Gio de disque libre, ou charge élevée.

### Phase 1 — Dépôt et artefacts, hors de tout chemin de production
```bash
ssh nexus-prod 'install -d -m 0700 /srv/nexus-staging && cd /srv/nexus-staging && git clone https://github.com/cyranoaladin/RAG.git repo && cd repo && git checkout --detach <SHA>'
rsync -a --chmod=D0700,F0600 <artefacts E5> <artefacts reranker> nexus-prod:/srv/nexus-staging/models/
ssh nexus-prod 'cd /srv/nexus-staging/models && sha256sum e5-large/SHA256SUMS ms-marco-reranker/SHA256SUMS'
```
Les deux empreintes doivent valoir `e2c7384b…` et `bdcedc4d…`. **Arrêt** sinon.

### Phase 2 — Matériel de secret, sur place, jamais affiché
```bash
ssh nexus-prod 'cd /srv/nexus-staging/repo/services/rag-engine && PYTHONPATH=src python3 scripts/prepare_staging_environment.py --destination /srv/nexus-staging/secrets <options du runbook staging_externe § 3>'
ssh nexus-prod 'stat -c "%a %n" /srv/nexus-staging/secrets/*'     # attendu : 600, trois fichiers
```
Les ports proposés sont ajoutés à `staging.env` (`INGESTOR_PORT`, `PGVECTOR_PORT`, `PROMETHEUS_PORT`). Le contenu des fichiers n'est jamais `cat`.

### Phase 3 — Base de staging seule, puis index
```bash
C='docker compose -p nexus-staging -f docker-compose.v2.yml --env-file /srv/nexus-staging/secrets/staging.env'
ssh nexus-prod "cd /srv/nexus-staging/repo/services/rag-engine/infra && $C config --quiet && $C up -d --wait pgvector"
ssh nexus-prod "docker ps --filter name=nexus-staging-pgvector --format '{{.Names}}'"                 # doit rendre exactement nexus-staging-pgvector-1
ssh nexus-prod "cd /srv/nexus-staging/repo/services/rag-engine/infra && PGVECTOR_CONTAINER=nexus-staging-pgvector-1 BACKUP_ROOT=/srv/nexus-staging/backups ./scripts/apply_pgvector_migrations.sh"
```
**Danger identifié** : `apply_pgvector_migrations.sh` vise un conteneur **par nom**, et son défaut est `rag_pgvector` — sur
cet hôte, possiblement la base de production. `PGVECTOR_CONTAINER=nexus-staging-pgvector-1` est donc **obligatoire**, et la
commande n'est lancée qu'après que la ligne précédente a rendu ce nom exact. Sans cette variable : ne pas exécuter.
Puis l'index selon le choix 2.1 (a) ou (b). Contrôle : `SELECT COUNT(*) FROM rag_chunks WHERE vector IS NOT NULL` > 0 sur la base de staging.

### Phase 4 — Image `ingestor` figée par digest, puis API
Le Compose **construit** `ingestor` (`build:`) : sans gel, deux `up` pourraient lancer deux images différentes.
```bash
ssh nexus-prod "cd …/infra && $C build ingestor"
ssh nexus-prod "docker inspect --format '{{.Id}}' nexus-staging-ingestor" | tee ~/nexus-staging-proof/ingestor_image_id.txt   # sha256:… — LE digest du staging
ssh nexus-prod "cd …/infra && $C up -d --wait --no-build ingestor"                     # --no-build : jamais de reconstruction implicite
ssh nexus-prod "docker inspect --format '{{.Image}}' nexus-staging-ingestor-1"         # doit égaler le digest consigné
```
Tout `up` ultérieur porte `--no-build`, et le digest du conteneur est recomparé après le rollback (phase 6). Un digest
différent = **arrêt**. Ce même digest est celui que le manifeste de production devra citer.

**Healthchecks**
```bash
ssh nexus-prod "cd …/infra && $C ps --format '{{.Service}} {{.Health}}'"               # pgvector healthy, ingestor healthy
ssh nexus-prod 'curl -fsS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18003/health'   # 200
```
`/health` valide les autorités de runtime, les artefacts de modèles, la réconciliation de base et la dimension
d'embedding ; il rend 503 sinon. Un 503 est un **arrêt**, pas un réessai.

### Phase 5 — Smoke tests depuis l'extérieur, par tunnel (aucune exposition)
```bash
ssh -N -L 18003:127.0.0.1:18003 nexus-prod &          # le poste de travail est hors de l'hôte et hors du conteneur
```
**API** — sans justificatifs puis avec :
```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:18003/search/v2 -d '{}'      # 401 attendu
curl -fsS http://127.0.0.1:18003/health                                                          # 200
```
**Retrieval** — la recette de l'agent extérieur, une portée par exécution (jetons lus de l'environnement, jamais en argument) :
```bash
RAG_API_URL=http://127.0.0.1:18003 python scripts/staging_external_acceptance.py --scope <portée>
# attendu : EXTERNAL_AGENT_E2E=PASS  RESULTS>0  CITATIONS=RESULTS (source, URI, page sur chaque résultat)
```
À jouer sur au moins trois portées (trois niveaux, trois matières), plus une requête **hors portée** → 403.

**Cockpit** — lancé **sur le poste de travail**, jamais sur `nexus-prod` :
```bash
cd services/cockpit && RAG_ENGINE_INTERNAL_URL=http://127.0.0.1:18003 npm run start    # secrets de staging dans l'environnement
```
Attendus : `/api/health` ok ; `POST /api/search` sans session → 401 ; collection hors portée → 403 ; recherche
authentifiée → résultats affichables avec citations (source, URI, page). Le banc `test_cockpit_e2e_retrieval.py` fixe déjà
ces attendus.

### Phase 6 — Rollback éprouvé
`staging_externe.md` § 8, sous `-p nexus-staging` : sauvegarde `pg_dump -Fc`, `down` (sans `-v`), `up -d --wait`,
`/health` à 200 **et** recette § 6 repassée. C'est ce second point qui vaut « éprouvé ».

### Phase 7 — Journaux et contrôle de non-atteinte de la production
```bash
ssh nexus-prod "cd …/infra && $C logs --no-color | grep -Eci 'password=|bearer [a-z0-9]|secret=' "     # attendu : 0
ssh nexus-prod 'docker compose ls; docker ps --format "{{.Names}}\t{{.Status}}"'                        # à comparer à la phase 0
```
```bash
ssh nexus-prod 'docker ps --no-trunc --format "{{.ID}} {{.Names}} {{.Image}} {{.CreatedAt}}" | sort | grep -v nexus-staging' | diff - <(grep -v nexus-staging ~/nexus-staging-proof/prod_containers_before.txt)   # vide = zéro production touchée
ssh nexus-prod 'find /srv /opt -maxdepth 4 -type l -name "current*" -printf "%p -> %l\n" 2>/dev/null | sort' | diff - ~/nexus-staging-proof/current_links_before.txt   # vide = zéro current switch
ssh nexus-prod 'sha256sum /etc/nginx/nginx.conf /etc/nginx/sites-enabled/* 2>/dev/null | sort' | diff - ~/nexus-staging-proof/nginx_before.txt                        # vide = Nginx intact
```
Les trois `diff` doivent être **vides** : mêmes identifiants de conteneurs de production (donc aucun redémarrage ni
recréation), mêmes liens `current`, même configuration Nginx. Ces trois sorties entrent dans la preuve.

### Phase 8 — État final, décidé par l'opérateur
Soit staging laissé arrêté (`$C down`, volume conservé), soit démantelé (`$C down -v` — **seule** occurrence admise de
`-v`, et uniquement sous `-p nexus-staging`), puis `rm -rf /srv/nexus-staging/secrets`. La preuve
`external_staging_proof.json` est alors rescellée en mode `A` / `production_cloisonnee`, sans nom d'hôte sensible ni secret.

## 4. Conditions d'arrêt immédiat

Je m'arrête, je ne corrige pas sur place, je rapporte — dès que l'un de ces faits survient :

1. un port proposé est pris, ou un projet / volume `nexus-staging` préexiste ;
2. ressources sous les seuils (RAM libre < 12 Gio, disque < 25 Gio) ou charge de la production élevée ;
3. une empreinte d'artefact de modèle, de registre ou d'index diffère de l'attendu ;
4. une commande exigerait un identifiant, un fichier ou une base de production ;
5. `docker ps` ne rend pas exactement `nexus-staging-pgvector-1` avant la migration ;
6. `/health` rend 503, ou le digest de l'image en service diffère du digest consigné ;
7. un `diff` de la phase 7 n'est pas vide, à n'importe quel moment où je le rejoue ;
8. un secret apparaît sur un terminal ou dans un journal ;
9. la production montre une dégradation (latence, erreurs) pendant l'exercice ;
10. toute situation que ce plan ne prévoit pas.

Dans tous les cas l'arrêt de sécurité est le même : `$C down` (sans `-v`), qui ne touche que le projet `nexus-staging`.

## 5. Risques

| Risque | Gravité | Parade |
|---|---|---|
| Contention CPU/RAM avec la production (inférence E5 + reranker) | élevée | fenêtre hors usage ; limites Compose `cpus: 2.0` / 8 Gio ; seuils d'arrêt phase 0 ; durée courte |
| Disque saturé (image ≈ 3 Gio, modèles ≈ 2,5 Gio, base) | moyenne | seuil 25 Gio libres ; démantèlement phase 8 |
| Collision de port ou de projet Compose | moyenne | ports dédiés vérifiés libres ; nom de projet unique ; arrêt si existant |
| Commande Docker hors projet touchant la production | élevée | toute commande d'écriture porte `-p nexus-staging` ; liste d'interdits § 0 ; comparaison phase 0 / phase 7 |
| Script d'exploitation à cible implicite (`apply_pgvector_migrations.sh` → `rag_pgvector` par défaut) visant la production | **critique** | `PGVECTOR_CONTAINER` explicite, vérification du nom avant exécution ; relire la cible de tout script avant de le lancer sur cet hôte |
| Fuite de secret (terminal, journaux, dépôt) | élevée | producteur qui n'affiche rien ; aucun `cat` ; recherche dans les journaux ; secrets détruits phase 8 |
| « Distinct de la production » contestable, puisque même machine | moyenne | c'est une limite **déclarée** du mode A : la preuve dira `production_cloisonnee`. Si vous exigez une séparation physique, c'est le mode B |
| Le test de charge (volet C) dégrade la production | élevée | voir le plan de mesure : séquentiel d'abord, charge complète seulement sur feu vert distinct |

## 6. Ce que ce plan ne fait pas

Ni déploiement de production, ni current switch, ni écriture dans une base de production, ni modification de Nginx,
de DNS ou de certificats, ni ingestion de production, ni révocation OAuth, ni reconfiguration rclone.
