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

## 3bis. Dette réseau — auto-allocation Docker et plages de box (DOCUMENTÉE, NON APPLIQUÉE)

`docker-compose.v2.yml` n'épingle plus de sous-réseau (ADR-0051 §6) : Docker
auto-alloue. C'est le bon choix pour ce fichier, mais l'auto-allocation par
défaut du démon est dangereuse **sur ce poste précis**.

### Le risque, mesuré

Sans `default-address-pools`, Docker puise dans `172.17.0.0/16` → `172.31.0.0/16`,
puis dans **`192.168.0.0/16` par tranches de /20**. Onze bridges occupent déjà
cette seconde zone :

| Bridge | Sous-réseau | Couvre |
|---|---|---|
| `bilan-foundation-main-baseline_default` | **192.168.0.0/20** | **192.168.0.0/24 et 192.168.1.0/24** |
| `nexus-bilans-p0d-release-quality_e2e-network` | 192.168.16.0/20 | 192.168.16–31 |
| `candidat-libre-diagnostic_default` | 192.168.32.0/20 | 192.168.32–47 |
| `candidat-libre-diagnostic_e2e-network` | 192.168.48.0/20 | 192.168.48–63 |
| `saisie-papier-email-differe_default` | 192.168.64.0/20 | 192.168.64–79 |
| `korrigo-local_default` | 192.168.80.0/20 | 192.168.80–95 |
| `deploy-main-142-53db37319_default` | 192.168.112.0/20 | 192.168.112–127 |
| `nexus-release-e32137e_default` | 192.168.128.0/20 | 192.168.128–143 |
| `nexus-project_v0_default` | 192.168.144.0/20 | 192.168.144–159 |
| `nexusrag_rag_net` | 192.168.160.0/20 | 192.168.160–175 |
| `t3a-headcount-workflow_default` | 192.168.176.0/20 | 192.168.176–191 |

Ce poste est **itinérant** : douze réseaux Wi-Fi enregistrés, dont cinq box
grand public de fournisseurs d'accès. Ces box servent typiquement
`192.168.0.1`, `192.168.1.1`, `192.168.8.1` ou
`192.168.100.1` comme passerelle.

**La première ligne du tableau est la collision effective** :
`bilan-foundation-main-baseline_default` occupe `192.168.0.0/20`, donc capture
`192.168.0.1` **et** `192.168.1.1`. Sur un réseau utilisant l'une de ces
passerelles, le poste ne joint plus sa box : le bridge Docker l'emporte, avec
une route locale plus spécifique. Symptôme observé côté utilisateur : « le Wi-Fi
est connecté mais rien ne passe ».

Le LAN courant (`192.168.100.0/24`) tombe dans `192.168.96.0/20`, tranche non
encore allouée. **La machine n'est indemne que par chance** : la prochaine
création de réseau Docker peut prendre cette tranche.

### Correctif — au niveau du démon, pas de Compose

Aucun fichier Compose ne peut corriger cela : l'auto-allocation est une propriété
du démon. Le réglage est `default-address-pools` dans `/etc/docker/daemon.json`
(actuellement `null`, donc défauts d'usine — vérifié par
`docker info --format '{{json .DefaultAddressPools}}'`).

```jsonc
// /etc/docker/daemon.json — fusionner avec le contenu existant, ne pas écraser
{
  "default-address-pools": [
    { "base": "10.200.0.0/13", "size": 24 }
  ]
}
```

`10.200.0.0/13` couvre `10.200.0.0` → `10.207.255.255`, soit 2048 réseaux /24.
Cette plage est hors du `10.0.3.0/24` de `lxcbr0` déjà présent, et hors de toute
plage de box grand public.

```bash
# 1. Sauvegarder la configuration existante.
sudo cp -a /etc/docker/daemon.json /etc/docker/daemon.json.bak_$(date +%Y%m%d_%H%M%S)

# 2. Éditer (fusionner la clé, ne pas remplacer le fichier).

# 3. Valider le JSON AVANT de redémarrer — un daemon.json invalide
#    empêche Docker de redémarrer du tout.
python3 -m json.tool /etc/docker/daemon.json >/dev/null && echo "JSON valide"

# 4. Redémarrer le démon.
sudo systemctl restart docker

# 5. Contrôler la prise en compte.
docker info --format '{{json .DefaultAddressPools}}'
```

### Conséquences, à assumer avant d'appliquer

- **`systemctl restart docker` arrête tous les conteneurs de la machine** — les
  quatre piles Nexus, `korrigo-local`, `workflow_correction`, et tout le reste.
  Ceux en `restart: unless-stopped` redémarrent ; les autres non.
- **Aucune renumérotation des réseaux existants.** Le réglage ne vaut que pour
  les réseaux *créés ensuite*. Les onze bridges du tableau — dont celui qui
  capture `192.168.0.0/20` — **restent en place**. Les renuméroter exige
  `docker network rm` sur chacun, donc l'arrêt des piles concernées.
- Traiter en priorité `bilan-foundation-main-baseline_default` : c'est le seul
  qui recouvre des passerelles réellement rencontrées.
- Un `daemon.json` syntaxiquement invalide empêche Docker de démarrer. L'étape 3
  n'est pas facultative.

**Non appliqué dans ce lot** : le redémarrage du démon dépasse le périmètre et
demande une fenêtre choisie par l'opérateur.

## 3ter. Gate opérateur — artefact embedding scellé mais incomplet

Constaté le 28/08/2026 en démarrant l'ingestor sur la base canonique.

**Le gate release est franchi.** `validate_configured_release_database()` passe
sans aucun contournement : ni registre réduit, ni contrôle désactivé, ni seuil
assoupli. Les 18 collections déclarées sont réconciliées contre les 730 chunks
ingérés. Zéro occurrence d'erreur de release dans les journaux.

Le démarrage échoue plus loin, sur `EMBEDDING_MODEL_UNAVAILABLE`.

### Nature exacte du défaut

L'artefact `~/rag-model-artifacts/e5-large-prerentree-2026-2027` **satisfait son
propre sceau** : `_initialize_model_artifacts()` et
`_validate_release_model_attestations()` passent, donc
`RAG_EMBEDDING_MODEL_INVENTORY_SHA256=e15ab71b…` correspond bien au contenu.

Mais `SHA256SUMS` ne scelle que dix fichiers plats, et `modules.json` — lui-même
scellé — déclare trois modules :

| idx | type | `path` | présent |
|---|---|---|---|
| 0 | `models.Transformer` | `""` (racine) | oui |
| 1 | `models.Pooling` | `1_Pooling` | **NON** |
| 2 | `models.Normalize` | `2_Normalize` | non |

L'artefact est donc **fidèlement scellé et intrinsèquement inutilisable** : le
sceau est cohérent avec un répertoire qui l'est pas. `sentence_transformers` lit
`modules.json`, ne trouve pas `1_Pooling` en local, retombe sur un
`snapshot_download` et échoue en `HFValidationError: Repo id must be in the form
'repo_name' or 'namespace/repo_name': '/models/e5-large'`.

Vérifié au code source de `sentence-transformers` 3.0.1 embarqué dans l'image :

```python
Pooling.load(input_path)    # open(os.path.join(input_path, "config.json")) -> REQUIS
Normalize.load(input_path)  # return Normalize()                            -> sans effet
```

Seul `1_Pooling/` manque réellement. L'absence de `2_Normalize/` est inoffensive,
et l'artefact d'ingestion du 26/08 ne le contenait pas davantage.

Le reranker n'a pas ce défaut : `ms-marco-MiniLM-L-6-v2-prerentree-2026-2027` est
un cross-encoder, sans `modules.json`.

### Correctif — action opérateur, non appliquée

Le fichier manquant est connu ; il est présent dans l'artefact d'ingestion
`intfloat-multilingual-e5-large-3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3` :

```json
{
    "word_embedding_dimension": 1024,
    "pooling_mode_cls_token": false,
    "pooling_mode_mean_tokens": true,
    "pooling_mode_max_tokens": false,
    "pooling_mode_mean_sqrt_len_tokens": false
}
```

La remise en état suppose de **resceller** l'artefact : ajouter
`1_Pooling/config.json`, régénérer `SHA256SUMS`, puis reporter la nouvelle
empreinte dans `RAG_EMBEDDING_MODEL_INVENTORY_SHA256`.

**Non appliqué délibérément.** `docker-compose.v2.yml` qualifie cette valeur
d'« empreinte SHA-256 **externe** de l'inventaire embedding » : elle est fournie
par la gouvernance, pas dérivée du contenu par le service. La recalculer
soi-même reviendrait à faire signer l'artefact par celui qui le modifie, ce qui
vide l'attestation de sa fonction. Le pooling `mean` retenu ci-dessus est de
surcroît une caractéristique du modèle, pas un détail d'emballage : il doit être
confirmé, pas déduit d'un autre répertoire.

C'est un gate opérateur au sens strict : la décision et la nouvelle empreinte
appartiennent à l'autorité qui a scellé l'artefact.

## 3quater. Dette du format de sceau — `SHA256SUMS` n'atteste pas la complétude

Cette dette **survivra au rescellement** de l'artefact du §3ter : elle est dans le
format, pas dans son application.

### Le défaut

`SHA256SUMS` scelle **une liste de fichiers** et garantit que chacun est intact.
Il ne vérifie jamais que cette liste **couvre ce que l'artefact déclare avoir
besoin**. `verify-embedding-model-artifact.sh` confirme la liste et l'empreinte
d'inventaire, sans jamais ouvrir `modules.json`.

Conséquence observée : un artefact amputé de `1_Pooling/` — donc incapable de se
charger — est déclaré **conforme** par l'attestation. Le contrôle a fonctionné
exactement comme spécifié, et a laissé passer un artefact inutilisable.

### La cause racine, identifiée

Deux producteurs coexistent, et un seul est récursif.

`scripts/e2e/prepare-embedding-model-artifact.sh` — script sanctionné :

```bash
find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum
```

`services/rag-pedago/scripts/build_production_profile_release.py::_model_inventory` :

```python
for path in sorted(snapshot.iterdir(), key=lambda item: item.name):
    if path.is_file():
        rows.append(f"{_file_sha256(path)}  {path.name}")
```

`Path.iterdir()` n'est **pas récursif**, et `if path.is_file()` écarte les
répertoires **sans erreur ni avertissement**. Tout sous-répertoire est
silencieusement absent du sceau — et, l'artefact étant construit sur ce même
inventaire, absent de l'artefact.

Vérifié par reproduction à l'octet près sur l'artefact du 27/08 : `manifest.json`
et `SHA256SUMS` sont reproduits exactement par `_model_inventory`, et
l'empreinte d'inventaire recalculée vaut `e15ab71b…`, la valeur de `.env`. Le
producteur est identifié sans ambiguïté.

Le seul garde-fou existant est indirect : `_model_inventory` lève
`"model inventory has no weights"` si `model.safetensors` manque. Le poids est
protégé ; la structure ne l'est pas.

### Correctif recommandé

**L'attestation doit vérifier que chaque chemin déclaré par `modules.json` existe
et est couvert par le sceau.** Concrètement, dans `verify-embedding-model-artifact.sh`
et dans `src/ingestor/model_artifact.py` :

1. lire `modules.json` (lui-même scellé, donc digne de confiance) ;
2. pour chaque module de `path` non vide, exiger que `<path>/config.json` soit
   présent **et** listé dans `SHA256SUMS` ;
3. échouer en `MODEL_ARTIFACT_INCOMPLETE` sinon, avec le chemin fautif.

`Normalize` est la seule exception légitime : `Normalize.load()` ne lit aucun
fichier (vérifié au source de `sentence-transformers` 3.0.1). La règle doit donc
porter sur les modules qui chargent un `config.json`, pas sur tous.

Rendre `_model_inventory` récursif est nécessaire mais **insuffisant** : cela
corrige un producteur, pas le format. Un sceau qui n'atteste pas sa propre
complétude reproduira ce défaut au prochain producteur ad hoc. C'est
précisément la classe de défaut qui a laissé passer un artefact inutilisable en
le déclarant conforme.

## 3quinquies. Régénération de l'artefact — gate hors ligne, 28/08/2026

Suite au §3ter et §3quater. Arbitrage opérateur : régénérer par le script
sanctionné (`prepare-embedding-model-artifact.sh`), **hors ligne d'abord**.

### Les deux correctifs de code sont appliqués

- `build_production_profile_release.py::_model_inventory` est **récursif**
  (`rglob`), aligné sur le `find . -type f` du script sanctionné. Deux tests de
  non-régression, vérifiés rouges sur l'implémentation d'origine.
- `model_artifact.py::_assert_declared_modules_are_sealed` exige que chaque
  module de `modules.json` à `path` non vide ait son `config.json` présent
  **et** scellé, en échouant sur `MODEL_ARTIFACT_INCOMPLETE: <chemin>`.
  `Normalize` reste exempté nominativement. Trois tests, dont un vérifié rouge
  sans le correctif (`DID NOT RAISE`).

`verify-embedding-model-artifact.sh` n'a pas eu à changer : il délègue déjà au
vérificateur du runtime. Confronté à l'artefact du 27/08 il rapporte désormais
`MODEL_ARTIFACT_INCOMPLETE: 1_Pooling/config.json` — auparavant il affichait
`OK: runtime artifact contract verified` et n'échouait que sur le test de
chargement, sans nommer la cause.

### Le gate : le script ne peut pas fonctionner hors ligne

`HF_HUB_OFFLINE=1` échoue en `LocalEntryNotFoundError`. La cause est
**structurelle, pas une affaire de configuration** :

```python
snapshot_download(repo_id=model_id, revision=revision, local_dir=target)
```

La docstring de `huggingface_hub` est explicite : avec `local_dir`, « the
`cache_dir` will not be used, and a `.cache/huggingface/` folder will be created
at the root of `local_dir` ». Le mode `local_dir` **contourne le cache hub par
conception**. Le répertoire cible étant neuf, il n'y a rien à résoudre.

Vérifié : **sans** `local_dir`, la révision épinglée se résout hors ligne
parfaitement, depuis
`~/.cache/huggingface/hub/models--intfloat--multilingual-e5-large/snapshots/3d7cfbda…`,
qui contient les 11 fichiers utiles — `1_Pooling/` compris — pour 2,2 Go.

Le script code `local_dir=target` en dur. L'écarter de ce comportement est une
modification du script, donc une sortie du périmètre délégué.

### Correction d'une analyse antérieure

Il avait été avancé que la voie B produirait un artefact plus léger que la voie A.
**C'est faux** : `snapshot_download` sans `allow_patterns` récupère l'intégralité
du dépôt. Un lancement **en ligne** produirait ~9,5 Go (`onnx/`, `openvino/`,
`pytorch_model.bin`, `.eval_results/`) — soit *plus* que les 2,2 Go du cache
local. La légèreté vient du cache, pas du script : elle plaide pour la voie hors
ligne, pas contre elle.

### La voie A est écartée, pour une raison nouvelle

L'artefact d'ingestion du 26/08 est complet et cohérent (134 fichiers, sceau
vérifié, `1_Pooling/` présent), mais il est **scellé au format obsolète** :
`manifest.json` n'y figure pas.

Preuve : il porte `repo_commit: ec4bb1cf…`, et l'historique montre que
`ec4bb1c` (17/07) scellait avec `find … ! -name manifest.json`, tandis que
`374b231` (03/08) a corrigé en scellant le manifeste — « The manifest carries the
canonical identity and must itself be authenticated ».

Or `verify_model_artifact` exige `"manifest.json" in checksums`. L'artefact
d'ingestion est donc **rejeté par l'attestation du runtime**
(`MODEL_ARTIFACT_INVALID`), indépendamment de la dette n°13. Le déclarer tel quel
est impossible.

### Preuve empirique de non-dérive du retrieval

Faite **sans attendre l'artefact scellé** : le cache hub porte les mêmes poids
(`model.safetensors` = `020afdeb…`, identique aux deux artefacts).

Protocole : charger le modèle depuis le cache hub hors ligne, ré-encoder le
texte de chunks existants avec la convention exacte de l'ingestion
(`format_passage` → préfixe `"passage: "`, `normalize_embeddings=True`), et
comparer au vecteur stocké en base. Trois chunks de trois collections
différentes, pour ne pas conclure sur un cas isolé.

| Collection | Similarité cosinus | Écart à 1 |
|---|---|---|
| `rag_nexus_dgemc_terminale_option` | 1,000000000075469 | 7,5·10⁻¹¹ |
| `rag_nexus_svt_terminale_specialite` | 1,000000001056675 | 1,1·10⁻⁹ |
| `rag_nexus_maths_seconde_tc` | 0,999999998755483 | 1,2·10⁻⁹ |

L'écart résiduel s'explique entièrement par la quantification au stockage :
`canonical_release_corpus_ingestion.py` sérialise les composantes en
`f"{c:.8f}"`, soit huit décimales. À cette précision, 10⁻⁹ est le plancher
atteignable — il n'y a aucune dérive de modèle.

Observation annexe confirmée empiriquement : le snapshot charge bien
`['Transformer', 'Pooling', 'Normalize']` alors que `2_Normalize/` est absent du
répertoire. L'exemption de `Normalize` dans le contrôle de complétude est donc
correcte, et non une commodité.

### Ce qui reste à trancher

1. Rendre le script capable de résoudre depuis le cache hub quand
   `HF_HUB_OFFLINE=1` — c'est-à-dire appeler `snapshot_download` sans
   `local_dir` puis recopier le snapshot résolu dans le répertoire d'artefact.
   Modification du script sanctionné, à valider explicitement.
2. Ou pré-alimenter le répertoire cible pour que le mode `local_dir` trouve ses
   métadonnées hors ligne — étape manuelle hors script, et qui produirait le
   jeu à 9 Go.
3. Ou autoriser un lancement **en ligne**, avec ~9,5 Go rapatriés.

L'option 1 est recommandée : elle conserve l'autorité de scellement au script,
n'exige aucun téléchargement, et produit l'artefact épuré qui contient
exactement ce dont `sentence-transformers` a besoin.

**Rien n'a été régénéré.** La délégation opérateur du report d'empreinte portait
sur une régénération *sans écart au script* ; l'écart étant nécessaire, elle est
caduque et la décision revient à l'opérateur.

## 3sexies. Gate opérateur — la release scelle l'artefact défectueux

Constaté le 28/08/2026 après rescellement de l'artefact embedding.

### Symptôme

Avec l'artefact rescellé (`…-20260828`, inventaire
`9788d8e5…`), le démarrage progresse d'un cran de plus qu'avant et échoue sur :

```
api_v2.py:380 _validate_release_model_attestations
RuntimeError: release model inventory mismatch
```

Progression : `validate_configured_release_database()` **passe** (gate release
franchi), `_initialize_model_artifacts()` **passe** (l'artefact rescellé est
valide, contrôle de complétude compris). L'échec est la comparaison entre
l'inventaire attesté et celui que **la release scelle**.

### Le fond

La release active — `release-registry.json` ne référence que
`profile_gate/production-profile-gate.release.json` — scelle
`embedding_inventory_sha256= e15ab71b…` dans son agrégat **et dans ses 18
manifests-sujets**.

`e15ab71b…` est l'empreinte de l'**artefact défectueux du 27/08**, celui qui est
amputé de `1_Pooling/` et incapable de se charger.

Autrement dit : **la release de production est scellée contre un artefact
embedding qui ne peut pas servir**. Ce n'est pas une conséquence du
rescellement — c'était vrai avant, et c'est ce qui rendait le blocage
inévitable quel que soit le chemin choisi.

### Chaîne causale

Les horodatages excluent l'hypothèse simple :

| Objet | Horodatage |
|---|---|
| `production-profile-gate.release.json` | 27/08 **08:08:15** |
| `SHA256SUMS` de l'artefact défectueux | 27/08 **20:02:10** |

La release **précède l'artefact de douze heures**. Elle n'a donc pas été scellée
*à partir* de ce répertoire : c'est `_model_inventory`, non récursif, qui a
produit `e15ab71b…` au moment du build de release à 08:08 ; le répertoire
d'artefact a été matérialisé plus tard, à 20:02, pour correspondre à cette
empreinte déjà scellée — donc nécessairement plat, donc nécessairement
inutilisable.

Un seul défaut (`snapshot.iterdir()` + `is_file()`), deux conséquences : un
artefact amputé **et** une release qui le sanctifie. Corriger le producteur —
fait — n'annule pas le sceau déjà émis.

### Anomalie dormante, signalée sans être traitée

Les manifests sous `multilevel/` déclarent une **troisième** empreinte,
`e2c7384b…`, qui ne correspond à **aucun artefact présent sur le disque**. Ces
manifests ne sont pas référencés par `release-registry.json` : ils sont
inertes aujourd'hui. Activer la release multilevel sans rescellement ferait
resurgir le même blocage.

### Ce qui est requis, et pourquoi je ne l'ai pas fait

Rendre le runtime démarrable exige de **resceller la release** avec l'inventaire
correct : rejouer `build_production_profile_release.py` — maintenant que
`_model_inventory` est récursif — pour régénérer l'agrégat, les 18
manifests-sujets et leurs liaisons d'autorité.

C'est la régénération d'une release scellée, avec sa chaîne de preuves et ses
`authority_bindings`. La délégation reçue portait sur *un artefact, une fois*, et
sur le report d'une empreinte dans `.env`. Rebâtir la release en sort
franchement. Aucun contournement n'a été tenté : ni édition des manifests, ni
assouplissement de `_validate_release_model_attestations`, ni retour à
l'artefact défectueux.

### État laissé

`.env` pointe l'artefact **correct** (`…-20260828`, `9788d8e5…`). Les deux états
échouent au démarrage — l'ancien sur `EMBEDDING_MODEL_UNAVAILABLE`, le nouveau
sur `release model inventory mismatch` — mais pointer l'artefact valide rend
l'action restante explicite. Le retour arrière tient en deux lignes de `.env`,
l'artefact du 27/08 étant intact.

## 3septies. Dette structurelle — dépendance de la pile à `/tmp`

**Deux incidents, pas un accident.** `/tmp` a déjà emporté deux fois des éléments
dont dépendait la pile.

| # | Élément perdu | Conséquence |
|---|---|---|
| 1 | `docker-compose.v2.network-hasfree.yml` et `…ingest-allowlist-local.yml` | trois services en orphelins, une plage réseau publique introuvable, une allowlist définitivement perdue (§1.4, §3.2) |
| 2 | `/tmp/nexus_corpus_pdf_cache` — **menacé, pas encore perdu** | seul exemplaire des 26 PDF scellés ; sans lui, aucune ré-émission de release n'est possible |

Le second n'a été découvert que parce qu'une recherche l'avait d'abord déclaré
absent à tort : le miroir était bien là, dans le seul répertoire que la recherche
ne couvrait pas.

### Cause traitée

`canonical_release_corpus_ingestion.py` définissait
`--cache-dir` avec pour défaut `/tmp/nexus_corpus_pdf_cache`. Le défaut pointe
désormais `~/sauvegardes-rag/corpus-pdf-mirror`, surchargeable par
`NEXUS_CORPUS_PDF_MIRROR`. Le miroir a été mis à l'abri sur **deux disques
physiques distincts** (`/dev/nvme0n1p3` et `/dev/nvme1n1p1`), 26/26 vérifiés par
empreinte contre l'autorité de la release.

### Ce qui reste ouvert — et grandira

Le miroir ne contient aujourd'hui que les **26** contenus scellés. Le corpus
source en compte **2451** (`docs/corpus/README_GDRIVE_IMPORT.md` §1 :
2451 PDF, 2451 SHA-256 uniques, 2956 affectations). Le jour où l'ingestion
couvrira le corpus complet, le miroir passera de 9,4 Mo à plusieurs gigaoctets.

**Un cache de plusieurs Go dans `/tmp` n'est pas tenable** : ni en place disque,
ni en durabilité, ni au regard du temps de reconstitution — 2451 téléchargements
Éduscol, dont chacun peut avoir été réédité depuis. À cette échelle, la perte du
miroir ne serait plus un contretemps mais une reconstruction non garantie.

**Décision requise** avant tout passage à l'échelle : choisir un emplacement
durable dimensionné (le second disque offre 202 Go libres), et l'inscrire dans la
configuration plutôt que dans un défaut de script.

### Portée générale

Aucun chemin de `/tmp` ne doit porter un élément dont dépend une pile ou une
preuve. `AGENTS.md` interdit déjà les chemins absolus machine-locaux dans le code
versionné ; la même règle doit s'étendre aux **emplacements volatils**, y compris
dans les valeurs par défaut. Un défaut est une décision : celui-ci a créé deux
incidents.

## 3octies. Dette de fond — deux producteurs d'inventaire sans autorité déclarée

C'est la cause dont l'artefact amputé n'était qu'un symptôme.

**Deux outils produisent l'inventaire du même artefact embedding, et ils ne
peuvent pas s'accorder** — non par un défaut d'implémentation, mais parce que
chacun écrit son propre `manifest.json`, qui est la première ligne de
l'inventaire :

| Producteur | `manifest.json` écrit | Empreinte obtenue |
|---|---|---|
| `build_production_profile_release.py::_model_inventory` | 3 clés : `model_id`, `revision`, `canonical_dim` | `58ad18db…` |
| `scripts/e2e/prepare-embedding-model-artifact.sh` | 10 clés : `revision_requested`, `file_count`, `generated_at`, `repo_commit`, versions… | `9788d8e5…` |

Mêmes onze fichiers, mêmes poids, deux empreintes irréconciliables. Aucun
document du dépôt n'établissait lequel fait autorité — et c'est **ce silence**
qui est le défaut.

### Répartition arrêtée le 28/08/2026

- **La release fait autorité.** L'inventaire scellé par
  `build_production_profile_release.py` est la référence ; l'artefact runtime en
  est une **matérialisation**, pas une source.
- `prepare-embedding-model-artifact.sh` fabrique un artefact **candidat** pour une
  release *future*. Il ne sert jamais une release déjà scellée.
- La matérialisation d'un artefact runtime depuis une release scellée est un
  **troisième métier**, distinct des deux précédents : elle ne calcule rien, elle
  copie (cf. `scripts/e2e/materialize-release-model-artifact.py` et
  `docs/runbooks/release_reseal.md` §4bis).

### Ce que le silence a coûté

L'artefact du 27/08 avait été matérialisé depuis la release — méthode correcte.
Il était amputé parce que l'inventaire de la release l'était (dette n°13, depuis
corrigée), pas parce que la méthode était mauvaise. Faute de documentation, la
correction a d'abord été tentée avec le mauvais outil : `prepare-…` a produit un
artefact valide et **inutilisable en l'état**, dont l'empreinte ne pouvait par
construction pas satisfaire la release.

## 3nonies. Troisième emplacement volatil — le cache HuggingFace

Après `/tmp` (surcharges Compose, miroir PDF — dette n°18), un **troisième**
emplacement volatil porte une dépendance gouvernée.

`E5TokenCounter` exige que le répertoire passé en `--embedding-snapshot` **porte
la révision pour nom** :

```python
if snapshot.name != self.model_revision or not snapshot.is_dir():
    raise ValueError("E5 tokenizer snapshot revision differs")
```

Seul `~/.cache/huggingface/hub/models--…/snapshots/<revision>/` satisfait cette
contrainte. **La reproductibilité de la release dépend donc de `~/.cache`**, que
tout nettoyage de cache — y compris automatique — peut effacer.

Ce répertoire n'est de surcroît fait que de liens vers `../../blobs` : une copie
naïve ne préserverait rien.

**Traité** : copie déréférencée (`cp -rL`) sur les deux disques, nom de
répertoire conservé égal à la révision, mise en lecture seule.
`~/sauvegardes-rag/hub-snapshots/e5-large/3d7cfbda…` et son homologue sur
`/dev/nvme1n1p1`, 2,2 Go chacune.

**Équivalence prouvée, pas supposée** : un rejeu à blanc depuis la copie produit
une release identique fichier pour fichier à celle produite depuis le cache, même
agrégat `c13a6205…`.

**Reste ouvert** : rien n'empêche un futur opérateur de repasser le chemin du
cache. Le runbook impose la copie ; un contrôle automatique refusant un
`--embedding-snapshot` sous `~/.cache` serait plus sûr.

## 3decies. Défaut de paquet — `nexus-contracts` porte cinq canonicalisations divergentes

À distinguer de la limite de l'outil de fermeture (dette n°23) : celle-ci est une
limite d'outillage, celle-là est un **défaut du paquet**.

`packages/contracts/src/nexus_contracts/` définit au moins **cinq formes
canoniques JSON distinctes**, chacune employée pour calculer des empreintes qui
font autorité :

| Module | Forme |
|---|---|
| `scope.py` | `separators=(",", ":")`, compact, sans saut de ligne final |
| `release_evidence.py` | `indent=2` **+ `"\n"` final** |
| `authorization_set.py` | `indent=2` + `"\n"` final |
| `h2_coverage_evidence.py` | `indent=_CANONICAL_INDENT` + `"\n"` |
| `production_readiness.py` | `indent=_CANONICAL_INDENT` + `"\n"` |

S'y ajoutent les empreintes calculées sur une **projection de champs** —
`review_binding.canonical_document()` énumère explicitement ses clés — et non sur
le modèle complet.

### Pourquoi c'est un défaut, et pas une commodité

Chaque forme est cohérente avec elle-même. Le défaut est qu'**aucun mécanisme ne
garantit que deux modules censés s'accorder sur une empreinte emploient la même
forme**. Deux composants peuvent calculer « l'empreinte du même document » et
obtenir deux valeurs, sans qu'aucun test, aucun type, aucune revue ne le signale :
la divergence ne se manifeste qu'au moment où l'un vérifie ce que l'autre a
scellé — c'est-à-dire trop tard, et dans un contexte où le symptôme (`digest
mismatch`) ne désigne pas la cause.

C'est **la même famille de défaut que le sceau qui n'attestait pas sa propre
complétude** (dette n°13) : un mécanisme correct dans son périmètre, muet sur ce
qu'il ne couvre pas. `SHA256SUMS` scellait fidèlement une liste sans vérifier
qu'elle couvrait `modules.json` ; ici, chaque canonicalisation est fidèle à
elle-même sans qu'aucune n'atteste être *la* canonicalisation du paquet.

### Correctif recommandé

Une seule fonction de canonicalisation exportée par `nexus_contracts`, employée
par tous les modèles, et un test qui refuse toute autre implémentation de
`json.dumps` dans le paquet — même motif que le contrôle de complétude ajouté à
`verify_model_artifact`. Les formes historiques déjà scellées doivent être
préservées explicitement, sous un nom qui dit qu'elles le sont
(`_LEGACY_CANONICAL_*`), plutôt que d'être reconduites par inadvertance.

Chantier de paquet, exigeant un ADR et un bump SemVer : hors de ce lot.

## 3undecies. Latence de retrieval — le budget est calibré sous le pire cas

Diagnostic conduit le 28/08/2026 après un 503 sur la première requête réelle.

### Ce qui n'est PAS en cause

`preload_runtime_models()` s'exécute dans le lifespan **avant le `yield`** :
l'application n'accepte aucun trafic tant que les modèles ne sont pas chargés.
`_get_embed_model()` met en cache dans un global, sous verrou, avec double
vérification. Le conteneur ne passe `healthy` qu'ensuite.

Mesuré sur un conteneur redémarré, cinq requêtes consécutives :

```
#1  4531 ms  200      #2  4746 ms  200      #3  4926 ms  200
#4  4798 ms  200      #5  4864 ms  200
```

**La première requête ne porte aucun surcoût.** Le healthcheck n'affirme donc pas
plus que ce qu'il a vérifié : ce n'est pas la famille de défaut du sceau attestant
un artefact inutilisable. L'hypothèse d'un préchargement qui ne réchaufferait pas
le chemin de requête est **infirmée par la mesure**.

### Ce qui est en cause

Décomposition du temps, mesurée dans le conteneur avec les modèles chauds :

| Étape | Coût |
|---|---|
| Encodage de la requête (e5-large, CPU) | 0,59 s |
| Rerank 10 paires | 1,11 s |
| Rerank 30 paires | 3,30 s |
| **Rerank 50 paires** (`CHANNEL_LIMIT`) | **5,39 s** |

Le cross-encoder domine tout, et croît linéairement avec le nombre de candidats.
**À `CHANNEL_LIMIT = 50`, le reranking seul dépasse le budget
`PG_DATABASE_BUDGET_MS = 6000`**, avant même l'encodage et la base.

Le régime observé (~4,8 s) correspond à un jeu de candidats plus petit : la base
ne porte que 730 chunks et une seule collection répond à la requête d'essai.

Le 503 initial est survenu sur la **toute première requête après reconstruction de
l'image**, quand les 2,2 Go de poids n'étaient pas dans le cache de pages de
l'hôte. Ce surcoût unique a suffi à franchir les 6 s. L'OS conserve ensuite le
fichier en cache, y compris à travers les redémarrages de conteneur — d'où la
non-reproductibilité.

### Pourquoi le réchauffement de bout en bout ne suffit pas

Encoder une requête factice avant de déclarer le service prêt ferait disparaître
le cas « cache de pages froid ». Cela ne toucherait pas le cas « 50 candidats »,
qui est le pire cas structurel. Le prochain déclencheur ne serait pas un
redémarrage mais **une collection mieux fournie** — c'est-à-dire le succès du
produit.

Corriger le symptôme le moins probable en laissant le pire cas ouvert
donnerait une assurance que la mesure ne soutient pas.

### Trois leviers, aucun neutre

1. **Élargir le budget** — sans effet sur l'expérience : l'utilisateur attend
   toujours 5 s.
2. **Réduire `CHANNEL_LIMIT`** — moins de candidats rerankés, donc une qualité de
   retrieval moindre. Arbitrage produit.
3. **Sortir le reranking du chemin synchrone** — deux temps de réponse, ou
   reranking asynchrone. Refonte du contrat de l'endpoint.

Le choix engage la qualité du retrieval, pas seulement la latence : il n'est pas
technique.

## 3duodecies. Concurrence — le facteur dimensionnant

À distinguer de la latence nominale : **4 955 ms mesurent UNE requête
séquentielle**, sur CPU, sans GPU sur cette machine (l'ingestion a tourné avec
`CUDA_VISIBLE_DEVICES=""`).

Deux requêtes concurrentes se disputent les mêmes cœurs. Le reranking étant
CPU-bound et dominant, **deux requêtes simultanées font sauter le budget de 6 s**
— sans qu'aucune ne soit anormale prise isolément.

Le facteur dimensionnant est donc la **concurrence**, pas le volume d'index. Un
index dix fois plus grand ne changerait pas le coût du rerank de 50 candidats ;
deux utilisateurs simultanés, si.

Conséquences à considérer avant toute mise en service :

- `deploy.resources.limits.cpus: "2.0"` sur l'ingestor plafonne le parallélisme
  disponible ;
- `--workers 1` est **délibéré** (registre Prometheus process-local), donc la
  capacité ne se scale que par réplicas derrière un agrégateur ;
- aucun test de charge n'a été conduit : le comportement à 2, 5 ou 10 requêtes
  concurrentes est **inconnu**, non pas mauvais.

Mesurer avant de dimensionner : un simple tir à concurrence croissante donnerait
le point de rupture, qui est aujourd'hui une inconnue et non une estimation.

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
| 9 | Auto-allocation Docker sur `192.168.0.0/16` : `bilan-foundation-main-baseline_default` capture `192.168.0.1` et `192.168.1.1`, passerelles de box rencontrées par ce poste itinérant (§3bis) | **haute** |
| 10 | Commit `9b1c2bf` : message limité à cockpit/collections alors que le diff modifie `docker-compose.v2.yml` — décision d'infrastructure invisible dans l'historique (ADR-0051 §6) | moyenne |
| 11 | `WORKER_API_SECRET_KEY` dans `.env` est un espace réservé de développement (`dev_admin_secret_64hex_…`), pas un secret généré | moyenne |
| 12 | Artefact embedding scellé sans `1_Pooling/` : conforme à son empreinte, inutilisable au chargement — resceller (§3ter) | **bloquante** |
| 13 | ~~Format de sceau : `SHA256SUMS` n'atteste pas la complétude~~ — **corrigé** (§3quinquies) : `_model_inventory` récursif + `MODEL_ARTIFACT_INCOMPLETE` | résolue |
| 14 | `prepare-embedding-model-artifact.sh` ne peut pas fonctionner hors ligne : `local_dir=` contourne le cache hub par conception (§3quinquies) | **bloquante** |
| 15 | L'artefact d'ingestion du 26/08 est scellé au format antérieur à `374b231` (manifeste non scellé) : rejeté par l'attestation du runtime (§3quinquies) | moyenne |
| 16 | La release active scelle `e15ab71b…`, l'empreinte de l'artefact embedding défectueux : le runtime ne peut pas démarrer sans rescellement de la release (§3sexies) | **bloquante** |
| 17 | Les manifests `multilevel/` déclarent `e2c7384b…`, empreinte ne correspondant à aucun artefact sur disque — inertes aujourd'hui, bloquants à l'activation (§3sexies) | moyenne |
| 18 | Dépendance de la pile à `/tmp` : deux incidents (surcharges Compose perdues, miroir PDF menacé). Défaut corrigé, mise à l'abri faite — dimensionnement à trancher avant le passage aux 2451 contenus (§3septies) | **haute** |
| 19 | Deux producteurs d'inventaire embedding aux `manifest.json` incompatibles, sans autorité déclarée — cause de fond dont l'artefact amputé était le symptôme. Répartition arrêtée et documentée (§3octies) | **haute** |
| 20 | La reproductibilité de la release dépend de `~/.cache/huggingface` (3ᵉ emplacement volatil). Copie faite et équivalence prouvée ; aucun garde-fou n'interdit encore de repasser le chemin du cache (§3nonies) | moyenne |
| 21 | Dépréciation des 18 scopes `_v1` : exige de prouver qu'aucune enveloppe émise ne les référence. Hors périmètre d'ADR-0052, à trancher séparément | basse |
| 22 | Un scope `_v2` ne dit pas qu'il procède d'un rescellement plutôt que d'un contenu nouveau : le lien vit dans ADR-0052, pas dans l'artefact. Évolution de contrat à envisager | basse |
| 23 | `release_impact_closure.py` couvre deux formes d'empreinte (octets, JSON canonique compact). Étendre : recenser les `canonical_bytes`/`_canonical_bytes` de `nexus_contracts`, associer chaque forme aux modèles qui l'emploient, et faire valider chaque JSON contre les modèles candidats. Énumérer les producteurs, pas les formes | moyenne |
| 26 | **Latence de retrieval** : le rerank de 50 candidats coûte 5,39 s seul, au-dessus du budget de 6 s. Préchargement et healthcheck hors de cause, mesurés (§3undecies) | **haute** |
| 27 | **Concurrence non mesurée** : 4 955 ms pour une requête séquentielle CPU ; deux requêtes simultanées franchissent le budget. Aucun test de charge, point de rupture inconnu (§3duodecies) | **haute** |
| 25 | Le balayage de fermeture porte sur le dépôt ; les runtimes figés (image Docker, `pip install` non éditable) lui sont invisibles par construction. Couvert par `check_runtime_conformance.py`, à exécuter après tout changement de `packages/contracts` | moyenne |
| 24 | **`nexus-contracts` porte au moins cinq canonicalisations JSON divergentes**, plus des empreintes sur projection de champs. Deux modules censés s'accorder sur une empreinte peuvent diverger sans que rien ne le détecte — défaut de paquet, même famille que la dette n°13 (§3decies) | **haute** |

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
