# Runbook — convergence shadow, canary et rollback des moteurs RAG

## Statut et portée

Ce runbook prépare une bascule du moteur A historique vers le moteur B
canonique. Il n'autorise aucune mutation de production. Tant que toutes les
preuves réelles et les gates humaines ne sont pas présents, le verdict est
`NO_GO`.

Le moteur A regroupe Streamlit/FastAPI legacy, ChromaDB 768 dimensions,
Ollama, `catalog.sqlite`, `drive_sync_state.db` et uploads. Le moteur B regroupe
le contrat partagé, `rag-pedago`, `rag-engine`, e5-large 1024 dimensions et
pgvector. Les vecteurs A ne sont jamais transférés directement vers B.

Interdictions permanentes :

- aucun `docker compose -p infra down` ou redémarrage global ;
- aucun `--remove-orphans` ;
- aucune suppression ou modification Chroma/SQLite pendant la préparation ;
- aucun accès direct pgvector depuis le frontend ;
- aucune publication contournant `quality → gate → review` ;
- aucun secret dans les arguments, rapports ou artefacts versionnés.

## 1. Figer l'identité de release

Dans un checkout propre du SHA candidat :

```bash
set -euo pipefail
git status --short
git rev-parse HEAD
git rev-parse HEAD^{tree}
git diff --exit-code
git diff --cached --exit-code
```

Consigner le SHA Git, le tree SHA, les digests immuables des images et le
digest du Compose. Toute modification ultérieure invalide la répétition.

Gate d'entrée : CI verte sur ce head, zéro thread non résolu et
trusted-human-review exacte. Une fixture, un test unitaire ou un digest déclaré
ne remplace pas ces faits.

## 2. Capturer A en lecture seule

L'opérateur identifie explicitement les services et volumes A. Il ne cible
jamais un service par nom générique ou un projet Compose partagé. Avant la
capture :

1. désactiver seulement les writers et tâches planifiées A identifiés ;
2. constater leur arrêt sans toucher aux readers ;
3. enregistrer `captured_at` et `valid_until` UTC, avec une fenêtre maximale de
   24 heures ;
4. capturer dans cet ordre : Chroma, `catalog.sqlite`,
   `drive_sync_state.db`, uploads ;
5. utiliser l'API SQLite backup ou un checkpoint quiescent, jamais une simple
   copie incohérente d'un fichier avec WAL actif ;
6. inventorier configurations, images et modèles par digest ;
7. recalculer les comptes et digests après capture ;
8. refuser si l'état avant/après diffère ou si un writer a repris.

Une capture `LIVE` ne peut jamais déclarer un snapshot. Le producteur réel de
capture reste un composant opérateur distinct : le Lot 2 ne fournit qu'un
consommateur hors réseau et ne transforme pas sa fixture synthétique en preuve.

## 3. Préparer la disposition exhaustive

À partir d'une capture exportée explicitement et d'un digest obtenu par un
canal de confiance :

```bash
set -euo pipefail
cd services/rag-engine
export PYTHONPATH=.:../../packages/contracts/src
: "${CAPTURE_FILE:?chemin de capture requis}"
: "${EXPECTED_CAPTURE_SHA256:?digest de capture requis}"
: "${PREPARED_MANIFEST:?nouveau chemin de sortie requis}"
test -f "$CAPTURE_FILE"
test ! -e "$PREPARED_MANIFEST"
python scripts/prepare_legacy_migration.py \
  --capture "$CAPTURE_FILE" \
  --policy configs/engine_convergence_v1.yml \
  --expected-input-sha256 "$EXPECTED_CAPTURE_SHA256" \
  --write-manifest "$PREPARED_MANIFEST"
```

Vérifier que chaque objet découvert apparaît exactement une fois, doublons
compris, et que la somme des dispositions égale le compte source. Toute cible
hors allowlist, preuve de droits absente, provenance incomplète ou scope
ambigu produit `REVIEW_REQUIRED`, `QUARANTINE` ou `BLOCKED`.
`REINGEST_GOVERNED` désigne seulement un candidat ; il ne confère aucun droit
de publication ou de retrieval. `migration_complete` reste `false`.

## 4. Sauvegarder et répéter la restauration

Avant toute réingestion ou bascule future :

1. créer des backups frais et scellés de Chroma, des deux SQLite, des uploads
   et de pgvector ;
2. conserver les images/configurations nécessaires à la reconstruction A ;
3. vérifier les checksums depuis une seconde lecture ;
4. restaurer pgvector dans un projet Docker isolé avec `pg_restore
   --no-privileges` ;
5. reprovisionner les rôles via le script canonique ;
6. vérifier schéma, migrations, extension vector, contraintes et comptes ;
7. détruire seulement le projet isolé après collecte du rapport assaini.

La procédure pgvector détaillée est dans `docs/runbooks/rollback.md`, section
« pgvector (v2) ». Le nom de projet doit être unique et différent de `infra` et
`production`. Un restore rehearsal non exécuté laisse
`restore_rehearsal_verified=false`.

## 5. Réingérer par la chaîne canonique

Repartir des documents sources reconstructibles, jamais des vecteurs 768D.
Pour chaque candidat admis : extraction, normalisation, re-chunking, embedding
e5-large réel, `quality`, gate, review humaine lorsque requise, puis
publication gouvernée dans la collection fine autorisée.

Après chaque batch, rapprocher : objets source, décisions, autorisations,
objets publiés et chunks. Une différence, un chunk sans citation, un résultat
cross-scope ou une écriture non autorisée arrête la campagne.

## 6. Valider localement le comparateur synthétique

Le comparateur livré par le Lot 2 accepte exclusivement les marqueurs
`SYNTHETIC_TEST_ONLY` et `NOT_REAL_PARITY_EVIDENCE`. Il sert à vérifier le
calcul, les liaisons et les refus fail-closed. Il ne doit pas être présenté
comme un producteur ou un validateur de parité réelle.

```bash
set -euo pipefail
cd services/rag-engine
export PYTHONPATH=.:../../packages/contracts/src
python scripts/compare_engine_parity.py \
  --witness tests/fixtures/engine_parity_witness_v1.json \
  --engine-a tests/fixtures/engine_parity_a_v1.json \
  --engine-b tests/fixtures/engine_parity_b_v1.json
```

Le code de sortie `3` signifie `FAIL_CLOSED`. Le code `0` avec
`METRICS_ONLY_THRESHOLDS_UNAPPROVED` n'est pas un PASS : les seuils de rappel,
rang, couverture et divergence doivent être approuvés dans un artefact
opérateur versionné. Les invariants scope, citation, droits compatibles avec le
contexte d'accès, égalité des droits A/B sur un même passage, review et absence
de fuite restent à tolérance zéro.

Avant une parité réelle, un lot futur doit définir et faire revoir un protocole
opérateur distinct qui : capture A et B depuis le même head/corpus, identifie
explicitement son contexte non synthétique, lie la durée d'observation et les
seuils approuvés, conserve les mêmes unités canoniques et refuse tout contenu
brut ou secret. Ses captures et son rapport doivent être scellés. Il ne peut ni
réutiliser les marqueurs synthétiques ni assouplir silencieusement le contrat
du Lot 2.

## 7. Valider le manifeste `NO_GO` du Lot 2

Le manifeste du Lot 2 lie :

- SHA Git et images immuables ;
- inventaires A et B ;
- comptes/digests de quiescence liés aux snapshots A ;
- backup B lié à la base, au head de migration et au digest pgvector ;
- topologie `active=engine_a`, `canary=engine_b`, `rollback=engine_a` ;
- smoke borné visant B ;
- cinq gates tous à `value=false` et `evidence=null`.

Validation locale sans mutation :

```bash
set -euo pipefail
cd services/rag-engine
export PYTHONPATH=.:../../packages/contracts/src
: "${CUTOVER_MANIFEST:?manifeste NO_GO requis}"
export CUTOVER_MANIFEST
python -c 'from pathlib import Path; import os; from src.ingestor.engine_cutover import validate_engine_cutover; print(validate_engine_cutover(Path(os.environ["CUTOVER_MANIFEST"])).verdict)'
```

Le validateur livré par le Lot 2 n'accepte que `NO_GO` et interdit les faits
positifs, même accompagnés d'une évidence de type exact. Il ne faut donc jamais
lui fournir un manifeste de cutover réel positif. Une version future capable
de lier et valider des preuves réelles nécessite son propre protocole, ses
tests, sa PR et sa revue ; elle ne peut pas assouplir silencieusement ce
validateur.

## 8. Canary et observation — gate de mutation

Avant toute mutation de trafic, présenter le gate opérateur avec head/tree
SHA, images, backups vérifiés, restore rehearsal, rapport de parité réel,
smokes, rollback et durée d'observation. Sans accord explicite, s'arrêter.

Après accord seulement :

1. garder A intact et disponible comme rollback ;
2. déployer B depuis les digests figés ;
3. router une fraction bornée du trafic autorisé vers B via le mécanisme Nginx
   versionné et testé ;
4. exécuter santé, readiness, recherche, filtres, citations, auth et isolation ;
5. observer erreurs, latence, connexions DB, disque et saturation pendant la
   fenêtre approuvée ;
6. augmenter le trafic seulement si tous les critères restent satisfaits.

Aucune commande de mutation Nginx ou de production n'est incluse dans ce lot.
Elle doit provenir du plan de déploiement du head final approuvé.

## 9. Rollback de trafic

Déclencher immédiatement le rollback en cas de fuite de scope, citation
incorrecte, erreur durable, corruption, échec readiness ou dépassement d'un
seuil approuvé. Le rollback doit :

1. remettre le trafic sur l'image A figée, sans arrêt global ;
2. laisser B isolé pour analyse ;
3. vérifier recherche, auth et citations côté A ;
4. comparer comptes/digests avec le snapshot ;
5. consigner l'incident et invalider le manifeste de cutover ;
6. ne restaurer une donnée qu'après un gate séparé et un backup frais.

Un simple plan ne satisfait pas `traffic_rollback_tested` : la preuve exige une
exécution réelle, son transcript assaini et son digest.

## 10. Critères de fermeture

Le dual-engine ne peut être fermé que lorsque tous les éléments suivants sont
réels et liés au même head : capture exhaustive, disposition à 100 %,
réingestion gouvernée, parité approuvée, backup/restauration, canary, rollback,
observabilité, trusted-human-review et autorisation opérateur. Jusqu'alors A
reste intact et le verdict global reste `NO_GO`.
