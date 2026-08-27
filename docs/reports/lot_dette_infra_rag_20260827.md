# Lot — remédiation de schéma pgvector et refonte compose

**Date** : 27 août 2026
**Branche** : `lot/schema-remediation-compose-20260827` (depuis `integration/p0-convergence-20260827`)
**Périmètre** : `services/rag-engine/infra`, `services/rag-engine/eval`

---

## 0. Dette prioritaire — `COMPOSE_PROJECT_NAME` incohérent

> **C'est très probablement l'origine du dédoublement des piles.**

`services/rag-engine/infra/.env` déclare :

```
COMPOSE_PROJECT_NAME=nexusrag
```

alors que la pile réellement en service tourne sous le projet **`infra`**
(`infra-pgvector-1`, `infra-ingestor-1`, `infra-prometheus-1`, …). Conséquence
mécanique : selon qu'un opérateur lance `docker compose up` **avec** ou **sans**
`-p infra`, Docker Compose adresse **deux projets distincts**, donc deux jeux de
conteneurs, deux réseaux et — c'est le point grave — **deux volumes de données
différents** :

| Projet | Volume pgvector | État |
|---|---|---|
| `infra` | `infra_rag_pgvector_data` | base réelle, 24 chunks, remédiée par ce lot |
| `nexusrag` | `nexusrag_rag_pgvector_data` | pile parallèle `nexusrag-*`, contenu non audité |

Les deux existent bel et bien côte à côte (`docker volume ls`). Un opérateur qui
omet `-p infra` croit administrer la base de production et en administre une
autre. C'est exactement le mode de défaillance qui produit une base « bricolée »
dont les migrations n'ont jamais tourné.

**Résolution attendue** (hors périmètre de ce lot — touche la convention de
nommage de toute la pile) : trancher un nom de projet unique, l'aligner entre
`.env`, la documentation et les unités systemd, puis retirer ou migrer la pile
perdante. Décision opérateur requise : `infra` est le projet vivant,
`nexusrag` est le nom déclaré.

**Non traité ici**, conformément à la consigne : la pile `nexusrag-*` n'a été ni
arrêtée ni modifiée.

---

## 1. Ce qui a été fait

### 1.1 Sauvegarde (préalable à toute écriture)

`~/sauvegardes-rag/` (mode 700) :

| Fichier | Vérification |
|---|---|
| `ragdb_20260827_231012.dump` (custom, 165 Ko) | `pg_restore --list` **et** restauration réelle dans `ragdb_verif` |
| `ragdb_20260827_231012.sql.gz` (texte) | second filet |
| `MANIFEST.sha256` | empreintes des deux |

La restauration a été **exécutée**, pas seulement listée : 4 tables, 24 lignes,
empreinte md5 du contenu (identifiants + vecteurs 1024d + texte) identique à la
source — `1498d7032b3db296ce19284bc3510884`.

### 1.2 Remédiation du schéma

Six divergences traitées. **Trois n'étaient pas au diagnostic initial** :

| # | Divergence | Origine | Statut |
|---|---|---|---|
| 1 | `DEFAULT` absents sur `audience`, `statut_enseignement`, `source_kind` | `init.sql` antérieur | corrigé — **cause réelle** de l'erreur observée |
| 2 | Colonne `tsv` + `idx_rag_chunks_tsv` en doublon de `text_tsv` | hors migrations | supprimés |
| 3 | 4 contraintes `CHECK` hors contrat | hors migrations | supprimées (§2.1) |
| 4 | Migrations 003 et 004 jamais appliquées | volume existant jamais repassé par initdb | appliquées |
| 5 | `rag_schema_migrations` inexistante | idem | créée, versions 1→4 inscrites |
| 6 | Rôles runtime `rag_reader`/`rag_reviewer`/`rag_publisher` absents | idem | provisionnés |

Le diagnostic initial désignait la colonne `tsv` comme cause directe et la table
`schema_migrations` comme registre. Les deux étaient inexacts : `tsv` provoque le
contrôle *suivant*, et `schema_migrations` est une table héritée qu'aucun code du
contrat ne lit — le registre attendu est `rag_schema_migrations`, qui n'existait
pas du tout. `schema_migrations` a été laissée en place, vide et inerte.

**Méthode** : script versionné
`infra/scripts/remediate-pgvector-to-head-004.sh`, idempotent, transaction
unique, verrou consultatif partagé. Répété d'abord sur une copie restaurée
(`ragdb_verif`) et validé contre le healthcheck réel **avant** toute écriture sur
`ragdb`. Checksums calculés par la méthode exacte de
`register_bootstrap_migrations.sh`.

**Résultat** : `infra-pgvector-1` est **healthy**. Données intactes — empreinte
md5 inchangée après remédiation, 24 vecteurs 1024d préservés, aucun embedding
recalculé, volume jamais touché.

### 1.3 Correctif de code

`services/rag-engine/eval/run_eval.py` : `ts_rank_cd(tsv, …)` et `tsv @@ …`
→ `text_tsv`. Seule référence de production à la colonne supprimée ; sans ce
correctif, l'éval hors-ligne aurait cassé.

### 1.4 Réintégration des services orphelins — **pas dans `docker-compose.v2.yml`**

> **Écart assumé par rapport au point 7 du brief.** Le brief demandait de
> réintégrer les trois services « dans `docker-compose.v2.yml` ». C'est
> impossible sans lever un verrou de gouvernance ; ils ont été mis dans un
> fichier additif séparé. Justification ci-dessous.

`docker-compose.v2.yml` décrit une topologie **gouvernée** — lecture/revue plus
sa seule supervision — verrouillée par six tests :

```
tests/test_prod_compose_config_mount.py
  ::test_v2_compose_contains_only_the_read_review_stack
  ::test_v2_compose_has_no_writer_worker
tests/test_ui_runtime_dependency_lock.py
  ::test_ui_is_not_part_of_the_governed_v2_runtime
  ::test_historical_ui_is_not_referenced_by_v2_compose
tests/test_embedding_model_artifact_contract.py
  ::TestComposeModelMount::test_compose_has_no_embedding_writer_worker
tests/test_v2_runtime_surface.py
  ::test_env_example_documents_every_required_compose_variable
```

Le premier exige que le jeu de services soit **exactement**
`{pgvector, ingestor, prometheus, alertmanager}` et interdit nommément
`{chroma, ollama, ui, redis, worker, celery, nginx}`. L'invariant protégé, cité
dans le test : « qu'aucune capacité du moteur A ne réapparaisse ici ».

Une première version de ce lot a ajouté les trois services à
`docker-compose.v2.yml` : **six tests verts sont passés au rouge**, ce
qu'interdit le garde-fou CI d'`AGENTS.md`. Cette version a été annulée
(`git checkout`), le fichier gouverné est revenu à l'octet près à son état
d'origine, plage `10.30.0.0/24` comprise.

**Ce que cela révèle** : les trois orphelins ne « manquaient » pas au fichier
compose par accident. Ils en étaient exclus **délibérément**, et les surcharges
`/tmp` servaient à contourner ce verrou depuis l'extérieur du dépôt. Les
réintégrer dans le fichier gouverné aurait rendu ce contournement permanent et
officiel.

**Résolution** : `infra/docker-compose.legacy-async.yml`, fichier séparé et
strictement additif, chargé par un second `-f` explicite — exactement le motif
que le dépôt sanctionne déjà pour `docker-compose.ingestion.yml`
(cf. `test_v2_compose_ingestion_control_lives_in_a_separate_opt_in_file`). Le
`up` normal du runtime v2 ne le voit jamais.

```bash
docker compose -p infra \
    -f docker-compose.v2.yml \
    -f docker-compose.legacy-async.yml \
    up -d
```

L'objectif réel du brief est tenu : les trois services sont **versionnés**, sans
aucune dépendance à `/tmp`, et la pile est reproductible. Trois dettes purgées :

- le montage de modèles pointait `/tmp/rag-lot-v2-models` → remplacé par
  `RAG_EMBEDDING_MODEL_ARTIFACT_HOST_DIR` ;
- identifiants Redis et PostgreSQL en dur → variables `.env` ;
- **défaut latent corrigé** : le `DATABASE_URL` du worker portait
  un mot de passe hérité du moteur A, qui n'est plus celui de `raguser`. Le worker
  orphelin ne pouvait donc pas joindre la base. Les DSN sont maintenant dérivés
  de `PGVECTOR_USER`/`PGVECTOR_PASSWORD`.

`infra-redis-1` a été démarré depuis ce fichier et vérifié **healthy**,
réutilisant le volume `infra_rag_redis_data` existant (`appendonlydir` et
`dump.rdb` intacts). `worker` et `ui` sont décrits mais **non démarrés** :
`worker` dépend du Dockerfile restitué non revalidé (§2.2) et `ui` dépend de
`ingestor`, lui-même bloqué (§3.1).

### 1.5 Documentation

`infra/postgres/MIGRATIONS.md` : procédure reproductible couvrant le volume neuf
(chemin `initdb`) et le volume existant (chemin de rattrapage), les six dérives
connues, le piège de normalisation des `DEFAULT`, et la marche à suivre pour une
migration 005.

---

## 2. Décisions prises

### 2.1 Suppression de 4 contraintes `CHECK` — arbitrage opérateur

`validate_001_sql` énumère les contraintes autorisées sur `rag_chunks` et exige
**zéro** contrainte hors liste. Quatre `CHECK` présentes en base y échappaient,
et **aucune n'existe dans le dépôt** (0 référence sur l'ensemble des sources) :

| Contrainte | Perte réelle |
|---|---|
| `rag_chunks_vector_dims_1024` | **nulle** — le type `vector(1024)` refuse déjà toute autre dimension (`ERROR: expected 1024 dimensions, not 3`) |
| `rag_chunks_audience_non_empty` | garantie perdue |
| `rag_chunks_doc_id_not_chunk_id` | garantie perdue |
| `rag_chunks_review_status_allowed` | garantie perdue ; aucune validation d'énumération équivalente trouvée dans `rag-engine/src` |

Aucune ligne ne les violait : la suppression n'a modifié aucune donnée. Il
n'existait aucune alternative permettant de conserver ces contraintes **et**
d'atteindre le head 004. Suppression **nominative**, non dynamique, pour garder
le périmètre auditable.

> **Candidat ADR** : réintroduire les trois garanties utiles dans le contrat
> HEAD (migration 005 + extension des listes d'autorisation de
> `validate_001_sql`), plutôt que de les laisser en dette.

### 2.2 Dockerfile du worker — restitution, non invention

Le service `worker` était bâti par un Dockerfile absent du dépôt.
`Dockerfile.ingestion-worker` ne peut pas servir de substitut : il démarre
`python -m ingestor.ingestion_worker.cli` et n'embarque pas Celery, alors que le
worker orphelin exécutait `celery -A tasks worker` et dépend de
`requirements.v2.txt` (celery 5.4.0, redis 5.0.8).

`docker history --no-trunc infra-worker:latest` expose l'intégralité des
instructions de construction de l'image, toujours présente localement.
`infra/Dockerfile.celery-worker` en est la transcription fidèle — restitution
depuis une source vérifiable, non reconstitution de mémoire.

> ⚠️ **NON VALIDÉ PAR RECONSTRUCTION.** Le `compose build worker` (~5,7 Go de
> roues pip) n'a pas été joué. À faire avant tout usage en production.

---

## 3. Ce qui n'a pas pu être fait

### 3.1 `infra-ingestor-1` ne démarre pas — blocage de contenu, hors périmètre

**Le point 6 du brief n'est tenu qu'à moitié.** `pgvector` est healthy, mais
l'ingestor s'arrête au démarrage sur :

```
RuntimeError: release database reconciliation unavailable
  retrieval_v2_endpoint.validate_configured_release_database()
```

Cause qualifiée : le registre de release `prerentree_2026_2027` déclare
**18 collections** ; la base n'en contient **qu'une**
(`rag_nexus_nsi_terminale_specialite`, 24 chunks, tous `reviewed`).
`validate_release_registry_readiness` réconcilie chaque collection déclarée
contre le contenu ingéré et refuse le démarrage tant que les 17 autres sont
absentes.

Ce n'est **pas** une dérive de schéma : la connexion PostgreSQL fonctionne, les
rôles sont provisionnés, le contrat HEAD 004 est satisfait. C'est un déficit
d'**ingestion de corpus**. Le résoudre exigerait d'ingérer 17 collections, donc
de calculer des embeddings — ce que le brief interdit explicitement.

Aucun contournement n'a été tenté : ni réduction du registre, ni désactivation
du contrôle, ni assouplissement de `RAG_MIN_COLLECTION_SUBSTANCE_CHUNKS`. Ces
manœuvres auraient rendu la pile « verte » en dégradant une garantie de
gouvernance.

Le conteneur a été **arrêté** (`Exited`) plutôt que laissé en boucle de
redémarrage, pour ne pas laisser la pile dans un état bruyant. Ce blocage est
antérieur au lot : `infra-ingestor-1` était en état `Created` et n'avait jamais
démarré.

### 3.2 Surcharge `ingest-allowlist-local` — contenu irrécupérable

Le second fichier de surcharge perdu ne laisse aucune trace exploitable :
`infra-ingestor-1` a été recréé depuis `docker-compose.v2.yml` seul et ne porte
aucune variable d'allowlist ; `orphelins-rag.json` ne couvre que les trois
services orphelins. Les CIDR d'origine (`INGESTOR_IP_ALLOWLIST`,
`INGESTOR_TRUSTED_PROXY_CIDRS`) n'ont pas été devinés. **Dette ouverte** : à
redéfinir explicitement avec l'opérateur.

### 3.3 `OLLAMA_URL` — service inexistant

Le worker orphelin pointait `http://ollama:11434`, or **aucun service `ollama`
n'existe dans `docker-compose.v2.yml`**. La variable est transmise, vide par
défaut, sans qu'un service soit inventé. À trancher : soit le worker n'en a plus
besoin, soit un service Ollama doit être ajouté explicitement.

---

## 4. Dettes résiduelles

| # | Dette | Gravité |
|---|---|---|
| 1 | `COMPOSE_PROJECT_NAME=nexusrag` vs projet `infra` — deux volumes de données concurrents (§0) | **haute** |
| 2 | Ingestor bloqué par l'absence de 17 collections ingérées (§3.1) | haute |
| 3 | `Dockerfile.celery-worker` restitué, non validé par reconstruction (§2.2) | moyenne |
| 4 | 3 garanties `CHECK` perdues, candidates à une migration 005 (§2.1) | moyenne |
| 5 | Allowlist d'ingestion irrécupérable (§3.2) | moyenne |
| 6 | `REDIS_PASSWORD` — identifiant de développement faible hérité du moteur A (valeur en clair dans `.env`, non versionné), à faire tourner | moyenne |
| 7 | `OLLAMA_URL` sans service correspondant (§3.3) | basse |
| 8 | Volume `rag_v2_redis_data` orphelin (label compose divergent) — laissé intact, signalé par Docker | basse |

---

## 5. Qualité

Depuis `services/rag-engine` :

| Cible | Résultat |
|---|---|
| `make lint` (ruff) | ✅ `All checks passed!` |
| `make typecheck` (mypy) | ✅ `Success: no issues found in 125 source files` |
| `make test` (pytest, hors `integration`) | ✅ **3115 passés, 0 échec** (385 désélectionnés : `integration`) |

### 5.1 Suite de tests

`3115/3500` tests sélectionnés (`-m "not integration"`), **aucun échec**.

**Aucune régression** : la seule exécution rouge de ce lot a été provoquée par
la première version du §1.4 (6 tests de gouvernance compose), annulée. Sur le
commit parent comme sur `HEAD`, la suite est verte. Aucun échec préexistant à
tracer.

Les suites `integration` (385 tests) n'ont pas été exécutées : elles exigent une
pile PostgreSQL dédiée que ce lot n'a pas provisionnée. Non lancé, donc non
rapporté comme vert.

---

## 6. Contraintes respectées

- Volume `infra_rag_pgvector_data` : **jamais** supprimé ni recréé.
- Aucun embedding recalculé.
- Toute écriture en base : dans une transaction, après un dump vérifié par
  restauration réelle.
- Plage réseau `10.30.0.0/24` et ports 5437 / 19094 / 19095 : inchangés.
- Pile `nexusrag-*` : ni arrêtée ni modifiée, seulement documentée.
- Aucun secret versionné (`.env` est couvert par `infra/.gitignore`).
