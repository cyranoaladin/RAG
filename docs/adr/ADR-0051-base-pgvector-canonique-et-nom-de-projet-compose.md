# ADR-0051 — Base pgvector canonique et nom de projet Compose

- **Statut** : **Accepté**
- **Date** : 2026-08-27
- **Décideur** : Nexus Réussite (opérateur)
- **S'appuie sur** : ADR-0001, ADR-0008, ADR-0039

## Contexte

Deux piles pgvector issues du **même** `services/rag-engine/infra/docker-compose.v2.yml`
coexistent sur la machine de développement, sous deux noms de projet Docker
Compose différents, donc sur **deux volumes de données distincts** :

| Projet | Volume | Port publié |
|---|---|---|
| `nexusrag` | `nexusrag_rag_pgvector_data` | 5436 |
| `infra` | `infra_rag_pgvector_data` | 5437 |

Docker Compose préfixe chaque volume du nom du projet. Le nom du projet provient
soit de `COMPOSE_PROJECT_NAME` dans `.env`, soit d'un `-p` explicite qui l'emporte.
Rien, dans la sortie d'un `docker compose up`, ne signale à l'opérateur *quelle*
base il vient d'atteindre. **La bascule est silencieuse.**

Le 27 août 2026, une soirée entière de remédiation de schéma a été conduite sur
la base `infra` — un vestige de développement du 31 juillet — dans la conviction
qu'il s'agissait de la base de production. Le diagnostic de départ (« la base est
à un état ~001/002 bricolé, les migrations 003/004 n'ont jamais tourné ») était
exact **sur cette base-là**, et c'est précisément ce qui l'a rendu crédible.

L'erreur n'a été détectée que le lendemain, en interrogeant les deux bases côte à
côte.

## Constat, avec preuves

Relevé du 27 août 2026 sur les deux bases, en lecture seule :

| Mesure | `nexusrag` (5436) | `infra` (5437) |
|---|---|---|
| `rag_chunks` | **730** | 24 |
| Collections distinctes | **18** | 1 |
| `rag_artifacts` | **26** | 0 |
| `rag_artifact_placements` | **26** | 0 |
| Chunks liés à un `artifact_id` | **730 / 730** | **0 / 24** |
| `indexed_at` | 2026-08-27 18:46:42 (lot unique) | 2026-07-31 11:45 → 12:23 |
| `rag_schema_migrations` enregistré le | **26 août, par `initdb`** | 27 août, par remédiation manuelle |
| Healthcheck HEAD 004 | exit 0 | exit 0 (après remédiation) |

Quatre preuves convergentes désignent `nexusrag` :

1. **Correspondance exacte au registre de release.** Les 18 collections de
   `nexusrag` sont exactement les 18 déclarées par
   `rag-pedago/data/releases/prerentree_2026_2027/release-registry.json` — zéro
   manquante, zéro en trop. `infra` n'en porte qu'une.
2. **Intégrité du modèle 004.** Les 730 chunks de `nexusrag` sont *tous*
   rattachés à un `artifact_id`, avec 26 artefacts et 26 placements cohérents et
   aucun placement orphelin. Les 24 chunks d'`infra` ont *tous* `artifact_id
   IS NULL` : ils sont antérieurs au modèle 004.
3. **Chronologie.** `nexusrag` a enregistré ses migrations le 26 août par le
   chemin `docker-entrypoint-initdb.d` — donc bootstrap propre — et son corpus
   est ingéré en un seul lot le 27 août à 18:46:42, signature d'une ingestion
   scriptée. `infra` porte des chunks du 31 juillet étalés sur 38 minutes.
4. **Lancement canonique.** `nexusrag-pgvector-1` porte le label
   `com.docker.compose.project.config_files` pointant le seul
   `docker-compose.v2.yml`, sans surcharge. C'est le lancement nominal du dépôt.
   `infra` résulte d'un `-p infra` explicite.

## Décision

### 1. `nexusrag` est la base canonique

La base de données pgvector canonique de `rag-engine` est celle du projet Compose
**`nexusrag`**, volume `nexusrag_rag_pgvector_data`. Elle porte le corpus
`prerentree_2026_2027` : 730 chunks, 26 artefacts, 26 placements, 18 collections,
vecteurs `multilingual-e5-large` en dimension 1024.

### 2. Le lancement canonique n'emploie jamais `-p`

Depuis `services/rag-engine/infra/` :

```bash
docker compose -f docker-compose.v2.yml up -d
```

`.env` fournit `COMPOSE_PROJECT_NAME=nexusrag`. **Ne jamais passer `-p`** : tout
`-p` l'emporte sur `.env` et bascule silencieusement de volume.

### 3. `COMPOSE_PROJECT_NAME` devient une variable documentée

`infra/.env.example` déclare désormais `COMPOSE_PROJECT_NAME=nexusrag`. Son
absence était une composante active du piège : un opérateur partant de
`.env.example` n'avait aucun moyen de savoir que cette variable existait, ni
qu'elle décidait de la base atteinte.

### 4. Garde-fou de non-régression

`services/rag-engine/tests/test_v2_runtime_surface.py::test_env_example_declares_the_canonical_compose_project`
vérifie que `.env.example` déclare le projet canonique. Le motif est celui que le
dépôt sanctionne déjà pour la même classe de défaut : la remédiation de revue
PR#90 sur `infra/scripts/backup-volumes.sh` — où un filtrage de volumes par
sous-chaîne de nom atteignait le mauvais projet — a été verrouillée par un test
dédié (`infra/scripts/tests/test_backup_volumes_project_prefix.sh`), et non par
une simple note de documentation.

### 5. Le nom du projet est affiché avant toute action

`infra/scripts/rag-stack.sh` enveloppe `docker compose` : il résout le projet
effectif, affiche le volume pgvector réellement visé, et **refuse** de s'exécuter
si un `-p` divergent est passé. Une bascule de base ne peut plus être silencieuse.

### 6. Le sous-réseau de `rag_net` reste auto-alloué

`docker-compose.v2.yml` n'épingle aucun sous-réseau. Un pin `10.30.0.0/24` a été
retiré : il visait un symptôme absent de ce fichier, et bloquait la pile.

**Traçabilité du pin — un piège de la même famille que celui de cet ADR.**
Le pin est entré par le commit `9b1c2bf`, daté du 27/08/2026 22:49, dont le
message est *« cockpit: synchronize collections.json snapshot with
rag_collections.yml (ADR-0048/0050) »*. Ce message ne mentionne ni le réseau, ni
`rag-engine`, ni aucun changement d'infrastructure. L'édition de
`docker-compose.v2.yml` était en cours, non commitée, et a été ramassée par un
`git add` tiers portant sur un autre sujet.

Conséquence directe : la seule trace de la décision d'épingler `10.30.0.0/24`
était invisible dans l'historique. Retrouver son origine a exigé un
`git log -p --follow` sur le fichier — pas la lecture des messages de commit.
Un historique qui ne décrit pas son contenu est un piège de la même nature que
`COMPOSE_PROJECT_NAME` : il donne une réponse fausse à qui l'interroge
normalement.

Ce commit est également celui qui a réécrit ce que le fichier déclarait *avant* :
`git show 9b1c2bf~1` montre `rag_net` sans aucun bloc `ipam`. C'est cette
auto-allocation qui a produit le `192.168.160.0/20` sain de la pile canonique.

**Ce que la revue doit en retenir** : un commit dont le message ne couvre pas la
totalité du diff est un défaut de traçabilité, pas une commodité. `AGENTS.md`
exige déjà des messages scopés par service (`rag-engine: …`, `cockpit: …`) ;
mélanger deux périmètres dans un commit viole cette règle et efface la décision.

**Garantie conservée sans pin** :
`tests/test_v2_runtime_surface.py::test_compose_never_pins_a_public_subnet`
refuse tout sous-réseau routable sur Internet dans n'importe quel
`infra/docker-compose*.yml`, surcharges comprises. Il n'impose aucune valeur
particulière — donc n'oblige jamais à recréer un réseau vivant. Vérifié rouge
sur `173.30.0.0/24` (la plage de l'incident) et `8.8.8.0/24`, vert sur
`10.30.0.0/24` et `192.168.99.0/24`.

Le durcissement de l'**auto-allocation** elle-même relève du démon Docker
(`default-address-pools`) et non d'un fichier Compose : dette documentée, non
appliquée, cf. `docs/reports/lot_dette_infra_rag_20260827.md`.

### 7. Artefact embedding rescellé — délégation opératoire du 28/08/2026

L'artefact déclaré au 27/08 était **conforme à son empreinte et inutilisable** :
`SHA256SUMS` scellait dix fichiers plats, tandis que `modules.json` — lui-même
scellé — déclarait un module `Pooling` en `1_Pooling/`, absent du répertoire.
`sentence_transformers` retombait sur un téléchargement distant et le runtime
refusait de démarrer (`EMBEDDING_MODEL_UNAVAILABLE`).

Cause racine :
`rag-pedago/scripts/build_production_profile_release.py::_model_inventory`
parcourait `snapshot.iterdir()` — non récursif — filtré par `is_file()`, qui
écarte les répertoires **sans erreur ni avertissement**. Établi par reproduction
à l'octet près de `manifest.json`, de `SHA256SUMS` et de l'empreinte
`e15ab71b…`.

#### Frontière de la délégation

L'opérateur a autorisé, le 28/08/2026, la modification de
`scripts/e2e/prepare-embedding-model-artifact.sh` sous une frontière stricte,
reprise ici mot pour mot :

> Tu modifies l'**acquisition** des fichiers, jamais le **scellement**. Le bloc
> `find . -type f ! -name SHA256SUMS | sort | xargs sha256sum` et le calcul de
> l'empreinte d'inventaire ne bougent pas d'une ligne. C'est là qu'est
> l'autorité du script ; la toucher ferait tomber la délégation rétroactivement.

Modification effectuée : en `HF_HUB_OFFLINE=1`, résoudre par
`snapshot_download` **sans** `local_dir` puis recopier le snapshot résolu dans
le répertoire cible. `local_dir` contourne le cache hub par conception — la
documentation de `huggingface_hub` est explicite — de sorte qu'un répertoire
cible neuf échouait en `LocalEntryNotFoundError` alors même que la révision
épinglée était intégralement en cache. En ligne, comportement inchangé. La
révision reste épinglée dans les deux branches.

**Frontière tenue, vérifiée deux fois** : le bloc de scellement est identique
octet pour octet (`sha256 = 8c52f5ad76cc4209…` avant et après), et, exécuté sur
une même fixture, les deux versions produisent le même `SHA256SUMS` et la même
empreinte (`9369fa315ad98186…`). Pincé durablement par
`tests/test_prepare_embedding_artifact_sealing.py`.

#### Périmètre de la délégation de report

L'opérateur a délégué par écrit le report de
`RAG_EMBEDDING_MODEL_INVENTORY_SHA256` dans `.env`, **pour cet artefact et
cette fois**, sous réserve que la régénération passe par le script sanctionné
sans écart au scellement. Ce n'est pas une auto-signature : l'autorité reste le
script, le report est délégué nominativement.

Artefact retenu :
`~/rag-model-artifacts/e5-large-prerentree-2026-2027-20260828`, 11 fichiers
scellés, `manifest.json` inclus (format post-`374b231`), `1_Pooling/` présent et
scellé, aucun lien symbolique. Empreinte d'inventaire
`9788d8e5ed307b5f3251cb2525f225af8f8583ef1ad6093981eb03b5866ace3b`.

L'artefact défectueux du 27/08 **n'a pas été écrasé** : il reste la pièce à
conviction et la preuve vivante que le contrôle de complétude fonctionne
(`MODEL_ARTIFACT_INCOMPLETE: 1_Pooling/config.json`). Le retour arrière se
limite à deux lignes de `.env`.

#### Preuve empirique de non-dérive

Les poids sont identiques (`020afdeb…`) entre l'artefact d'ingestion du 26/08 et
l'artefact rescellé. La preuve directe a été faite sur l'artefact **final**, en
reproduisant la convention d'ingestion (`format_passage`,
`normalize_embeddings=True`), sur trois chunks de trois collections :

| Collection | Similarité cosinus | Écart à 1 |
|---|---|---|
| `rag_nexus_dgemc_terminale_option` | 1,000000000075469 | 7,5·10⁻¹¹ |
| `rag_nexus_svt_terminale_specialite` | 1,000000001056675 | 1,1·10⁻⁹ |
| `rag_nexus_maths_seconde_tc` | 0,999999998755483 | 1,2·10⁻⁹ |

Écart maximal 1,2·10⁻⁹, seuil d'arrêt fixé à 10⁻⁷. Valeurs **identiques** à
celles obtenues depuis le cache hub : le modèle qui servira les requêtes est
bien celui qui a produit l'index. L'écart résiduel s'explique entièrement par la
sérialisation des composantes en `f"{c:.8f}"` à l'ingestion, soit huit
décimales.

### 7bis. Ce que le contrôle de complétude a fermé sans qu'on ait à le refuser

Une quatrième voie existait, non pesée au moment de l'arbitrage : conserver
l'artefact du 27/08 et y ajouter `1_Pooling/config.json` **sans resceller**.
L'artefact serait devenu chargeable tout en gardant l'empreinte d'inventaire
`e15ab71b…`, donc compatible avec la release en vigueur. Le runtime aurait
démarré.

Elle est aujourd'hui **fermée par notre propre code**, et c'est la justification
la plus forte du contrôle de complétude (dette n°13) :

- garder `e15ab71b…` suppose que `SHA256SUMS` reste inchangé ;
- donc que `1_Pooling/config.json` reste **hors du sceau** ;
- c'est-à-dire exploiter délibérément le défaut de non-récursivité qui a créé le
  problème, pour faire coïncider un artefact réparé avec l'empreinte d'un
  artefact amputé ;
- or `_assert_declared_modules_are_sealed` exige que chaque chemin déclaré par
  `modules.json` soit **présent et couvert par le sceau**. Un fichier posé à côté
  du sceau est rejeté exactement comme un fichier absent.

Le contrôle refuse donc cette voie sans qu'aucun arbitrage humain n'ait à
trancher. C'est la propriété recherchée : un garde-fou qui ferme la porte avant
qu'on ait à la refuser vaut mieux qu'une règle qu'il faut se rappeler
d'appliquer. La leçon vaut au-delà de ce cas — « présent sur le disque » et
« couvert par le sceau » ne sont pas la même propriété, et seule la seconde
résiste à une substitution silencieuse.

### 8. Trou de traçabilité — les 730 vecteurs de production

Les 730 vecteurs en base ont été produits le 26/08 par l'artefact
`intfloat-multilingual-e5-large-3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3`.
Cet artefact est complet et cohérent — 134 fichiers, sceau vérifié, `1_Pooling/`
présent — mais il est **scellé au format antérieur au commit `374b231`**, qui
excluait `manifest.json` de l'inventaire (`find … ! -name manifest.json`). Son
`manifest.json` porte `repo_commit: ec4bb1cf…`, précisément le commit d'avant
ce correctif.

Or `verify_model_artifact` exige aujourd'hui que `manifest.json` figure dans le
sceau. **L'artefact qui a produit l'index de production serait donc rejeté par
le vérificateur d'aujourd'hui** (`MODEL_ARTIFACT_INVALID`).

Ce n'est pas un problème de correction des données : les poids sont identiques à
ceux de l'artefact rescellé, et la similarité cosinus mesurée ci-dessus le
démontre par le résultat. C'est un **trou de traçabilité** : la chaîne de
scellement a changé de format entre la production de l'index et sa vérification,
sans que les artefacts antérieurs soient rescellés ni marqués comme périmés.

Conséquence pratique : on ne peut pas, aujourd'hui, ré-attester l'artefact qui a
réellement produit l'index. On peut seulement démontrer par mesure que le modèle
est le même. Rescellement des artefacts historiques, ou acceptation explicite de
cette limite : décision opérateur, hors périmètre de cet ADR.

## Conséquences

- La pile `infra` est un vestige. Son dump vérifié est archivé
  (`~/sauvegardes-rag/ragdb_20260827_231012.dump`, restauration réelle validée).
  Son sort — suppression ou conservation en bac à sable — fait l'objet d'une
  décision opérateur distincte ; le volume `infra_rag_pgvector_data` n'est pas
  supprimé par cet ADR.
- Les ports 5437 / 19094 / 19095, attribués à la pile vestige pour éviter les
  collisions, redeviennent sans objet une fois celle-ci arrêtée. `.env` revient
  aux ports canoniques.
- La remédiation de schéma du 27 août (commit `1dc15eb`) a porté sur la base
  vestige. La base canonique satisfaisait déjà le contrat HEAD 004 : elle n'a
  reçu aucune écriture. Les livrables réutilisables du lot — script de
  remédiation idempotent, `postgres/MIGRATIONS.md`, correctif `run_eval.py`,
  `docker-compose.legacy-async.yml` — restent valides et indépendants de la base
  visée.

## Limites

Cet ADR fixe la base canonique et le mécanisme de sélection. Il ne statue ni sur
la suppression du volume vestige, ni sur le sous-réseau de `rag_net`, ni sur
l'ouverture du gate `release database reconciliation` — trois décisions
distinctes.
