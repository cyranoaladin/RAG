# Convergence sûre des moteurs RAG A et B — conception

## Statut et décision

Cette conception exécute le Lot 2 décidé par l'opérateur le 2026-08-25.
L'architecture cible est déjà tranchée : le moteur B (`rag-pedago`,
`rag-engine`, pgvector et `nexus-contracts`) est l'unique architecture
canonique. Le moteur A (Streamlit/FastAPI, ChromaDB, Ollama et SQLite) reste
temporairement disponible pour continuité et rollback, sans devenir une
seconde vérité et sans fallback silencieux.

La validation produit préalable demandée par le workflow de conception est
donc constituée par ces décisions opérateur. Le lot ne demande aucune nouvelle
décision P01-P24, ne lève aucun verrou de gouvernance et ne touche pas la
production.

Le verdict global reste `NO_GO` : l'audit production du 2026-08-25 établit que
la table canonique `rag_chunks` est vide. Ce lot construit les garde-fous et
les preuves reproductibles nécessaires à une convergence ultérieure ; il ne
prétend pas démontrer une parité sur des données B qui n'existent pas encore.

## Constats prouvés

### Moteur A

Le runtime historique possède des parcours réels fichiers, URL et Google
Drive, une recherche dense filtrée, un catalogue SQLite, ChromaDB et Ollama.
Il écrit toutefois directement dans ChromaDB sans passer par
`quality → gate → review`. Le catalogue SQLite n'est pas transactionnel avec
ChromaDB, la réindexation admin est un placeholder et la suppression catalogue
ne retire pas les vecteurs. Les citations contractuelles sont absentes.

L'état de rollback A est réparti entre ChromaDB, `catalog.sqlite`,
`drive_sync_state.db`, les uploads, les configurations, les images et les
modèles. Les scripts génériques actuels n'en font pas un snapshot atomique et
le runbook de restauration ne correspond pas à la signature du script.

### Moteur B

L'application canonique `api_v2.py` expose la recherche et la revue, mais aucun
writer public. Le retrieval hybride pgvector, les filtres de scope serveur, les
citations et le refus de génération non autorisée sont implémentés et testés.
Le plan de contrôle d'ingestion existe avec idempotence, transitions,
attestations, revue et publication séparée.

Le routeur fichier/URL/Drive historique n'est pas monté dans l'application v2 ;
sa route Drive est incomplète et ses routes fichier/URL contourneraient la
chaîne canonique. Il ne constitue donc pas un adaptateur temporaire acceptable.
Les parcours Web, Drive, API externe et cockpit sont volontairement traités par
les Lots 3 à 6.

Le harnais d'évaluation B calcule déjà Recall, nDCG, MRR, fuites de filtre et
complétude des citations, mais son répertoire doré par défaut n'est pas alimenté
par une suite exécutable de parité A/B.

### Risque critique de migration

`services/rag-engine/scripts/migrate_chroma_to_pgvector.py` copie directement
les vecteurs Chroma sans recalcul, annonce par défaut `nomic-embed-text:v1.5`
et 768 dimensions, écrit dans un ancien schéma et avale des erreurs partielles.
Le moteur B impose E5 1024 dimensions et une réentrée gouvernée. L'ADR-0013
qualifie déjà cette copie directe d'inopérante. Le laisser exécutable est un
risque P0.

Le mapping historique de collections est un contrat de compatibilité A, pas un
plan de migration B. En particulier, les silos `rag_nexus_education` et
`rag_nexus_web3` ne sont pas des cibles physiques canoniques actuelles.

## Options examinées

1. **Copie directe des chunks et vecteurs — rejetée.** Les dimensions sont
   incompatibles, les métadonnées sont incomplètes et l'écriture contournerait
   la gouvernance.
2. **Double vérité durable avec fallback A invisible — rejetée.** Elle rendrait
   les résultats et les décisions de publication non reproductibles.
3. **Décommissionnement immédiat du moteur A — rejeté.** La cible B n'est pas
   peuplée et le rollback A n'est pas encore prouvé.
4. **Frontière fail-closed, préparation gouvernée et parité hors runtime —
   retenue.** Elle neutralise le chemin dangereux, rend chaque donnée legacy
   comptable et prépare shadow/canary/rollback sans mutation de production.

## Architecture du Lot 2

### 1. Tombstone du migrateur direct

Le chemin historique `migrate_chroma_to_pgvector.py` reste présent pour que les
runbooks ou automatismes anciens échouent explicitement. Toute invocation se
termine avant import client, connexion réseau ou mutation, avec un code de
sortie stable et un message constant orientant vers la préparation gouvernée.

Il ne parse et n'affiche jamais `argv`, même avec options inconnues ou valeurs
ressemblant à des secrets. Il n'accepte plus de DSN ni de paramètres
susceptibles d'exposer un secret dans les arguments de processus. Le fichier ne
contient plus d'`INSERT`, de copie d'embedding ni de dépendance
`asyncpg`/`chromadb`.

### 2. Politique de convergence versionnée

`services/rag-engine/configs/engine_convergence_v1.yml` décrit :

- le moteur B comme seul propriétaire canonique de chaque capacité ;
- la situation du moteur A (`compatibility_only`, `blocked` ou
  `rollback_only`) ;
- le lot responsable des écarts restant (3 à 6 ou 8) ;
- la politique de disposition de chaque collection legacy connue ;
- les seules cibles fines pouvant être établies à partir de métadonnées
  univoques ;
- l'interdiction des silos génériques comme cibles de migration ;
- les invariants de cutover et de rollback.

Ces états ont une sémantique normative :

- `compatibility_only` autorise l'usage A explicitement sélectionné pendant la
  transition, mais jamais un fallback invisible ; toute écriture invalide la
  capture précédente et impose un nouvel inventaire exhaustif ;
- `rollback_only` autorise seulement lecture et démarrage de secours ; toute
  ingestion ou écriture est interdite ;
- `blocked` interdit toute exécution du chemin concerné.

Le fichier n'est pas lu par le runtime de recherche. Un validateur fail-closed
en vérifie le schéma et les invariants afin qu'une future modification ne puisse
pas déclarer un writer A, un fallback silencieux ou une cible non déclarée.
Des tests séparés inspectent les imports, routes et images du runtime canonique :
le YAML seul n'est jamais considéré comme une barrière d'exécution.

### 3. Préparation legacy strictement en lecture seule

Le module `ingestor.legacy_convergence` et le CLI
`scripts/prepare_legacy_migration.py` reçoivent une liste JSONL explicite déjà
exportée par un producteur déclaré. Ils n'ouvrent ni ChromaDB ni PostgreSQL et
n'effectuent aucune requête réseau. Le mode par défaut est un dry-run ;
l'écriture d'un manifeste exige une option explicite, un chemin nouveau et le
SHA-256 attendu de l'entrée.

Chaque ligne est bornée en taille, validée et normalisée. Le format portable
interdit les embeddings et le texte brut : il exige des identités pré-calculées
(`content_sha256`, longueur, provenance et unité canonique de passage). Aucun
secret, contenu documentaire intégral ou vecteur n'est lu ou imprimé. Si une
future capture doit exceptionnellement calculer ces identités depuis le texte,
elle utilisera un mode opérateur privé, non versionné et non CI, sans fichier
temporaire, avec permissions restrictives et sans contenu dans `argv`, les
exceptions ou les logs ; ce mode n'est pas implémenté par ce lot.

Chaque objet reçoit exactement une disposition :

- `REINGEST_GOVERNED` : une source et un scope pédagogique exact sont
  disponibles ; l'objet n'est qu'un candidat au pipeline gouverné ;
- `REVIEW_REQUIRED` : métadonnée, scope, droit ou provenance insuffisants ;
- `QUARANTINE` : contenu connu mais non publiable sans résolution ;
- `IGNORE_EMPTY` : collection prouvée vide par l'inventaire ;
- `BLOCKED` : entrée invalide ou source irrécupérable.

La décision est déterministe et applique la précédence fermée suivante :

1. entrée invalide, identité absente ou collection inconnue : échec du
   manifeste, pas une disposition silencieuse ;
2. source déclarée irrécupérable : `BLOCKED` / `SOURCE_UNAVAILABLE` ;
3. collection prouvée vide et sans objet : `IGNORE_EMPTY` /
   `EMPTY_COLLECTION_VERIFIED` au niveau inventaire uniquement ;
4. contenu explicitement non publiable : `QUARANTINE` avec un reason code
   fermé ;
5. scope, droits ou provenance non exacts : `REVIEW_REQUIRED` avec un reason
   code fermé ;
6. seulement si toutes les preuves minimales sont présentes :
   `REINGEST_GOVERNED` / `EXACT_SOURCE_AND_SCOPE`.

La liste des collections historiques acceptées est fermée dans la politique et
contient au minimum les collections déjà observées : `nsi_corpus`,
`nsi_corpus_v2`, `rag_education`, `rag_francais_premiere`,
`rag_maths_premiere`, `rag_math_correction`, `rag_web3`, `rag_divers` et
`ressources_pedagogiques_terminale`. Le producteur fournit aussi la liste
exhaustive découverte ; elle doit être exactement égale à la liste de la
politique. Une collection inconnue ou une collection politique omise de
l'export fait échouer le processus.

Tout `BLOCKED` ou `REVIEW_REQUIRED` empêche `migration_complete` pour le
périmètre. `QUARANTINE` le bloque également tant qu'une archive scellée ou une
cible B non-retrievable scellée n'en prouve pas la conservation. Seule une
destruction ou exclusion opérateur distincte, explicite, scellée et auditée
peut changer ce périmètre dans un lot ultérieur.

Une disposition `REINGEST_GOVERNED` n'accorde ni droit, ni revue, ni statut
`reviewed`. Elle fournit une source candidate, un hash, une collection fine et
un identifiant de migration ; la chaîne existante doit ensuite produire toutes
les preuves `quality → gate → review`. Aucune fonction de ce lot ne sait écrire
dans `rag_chunks`.

La déduplication est déterministe sur identité de contenu et provenance. Un
objet dupliqué reste compté et référence l'identifiant canonique retenu ; il ne
disparaît jamais du bilan. Les compteurs de dispositions doivent être égaux au
nombre d'entrées, et le manifeste porte le digest de l'entrée et son propre
digest canonique.

### 4. Inventaire et preuve de couverture

Le format d'inventaire représente séparément :

- collections/chunks Chroma et dimension observée ;
- catalogue SQLite et état Drive SQLite ;
- pgvector canonique ;
- fichiers/uploads nécessaires à la reconstruction ;
- configurations et images épinglées.

Sa provenance est obligatoire : outil et version de capture, commit Git,
instant UTC, identité du volume/de la base, preuve du mode read-only, schéma et
état WAL des SQLite, compte source et digest par composant. Pour
`catalog.sqlite` et `drive_sync_state.db`, une capture déclarable utilise
l'API de backup SQLite ou une quiescence suivie d'un checkpoint WAL, conserve
les fichiers `-wal`/`-shm` quand ils existent et exécute
`PRAGMA integrity_check` sur la copie. Une simple archive d'un volume live ne
peut jamais rendre `snapshot_declared=true`. Un inventaire arbitraire, périmé,
non scellé ou sans identité de producteur est refusé.

Le CLI de préparation accepte un inventaire scellé et vérifie l'égalité entre
les comptes annoncés et les objets fournis. Les collections vides sont
explicites. Une différence, un doublon d'identifiant non déclaré ou une entrée
sans disposition fait échouer le processus.

Le Lot 2 livre une fixture exhaustive miniature et un test réel du format. La
capture de production reste read-only et sera rejouée au pré-cutover ; ses
valeurs ne sont pas inventées dans les fixtures.

### 5. Parité sur corpus témoin scellé

Un corpus témoin versionné utilise des identifiants de source et des SHA-256
stables, jamais des identifiants de chunks propres à un moteur. L'unité
canonique de comparaison est
`source_sha256 + canonical_span_id + content_hash` : deux passages du même
document ne sont jamais équivalents par le seul hash de source. Tout résultat
non mappable à cette unité est un mismatch. Le témoin couvre :

- documents admissibles et non admissibles ;
- cohérence des métadonnées ;
- citations et provenance ;
- filtres niveau/matière/collection ;
- absence de fuite inter-collection ;
- déduplication et ordre déterministe aux tolérances documentées.

Le comparateur A/B est hors runtime, borné par une allowlist de requêtes, `k`,
timeout et taille de réponse. Il consomme deux captures JSON explicites,
normalise les résultats par unité canonique de passage et produit un rapport
machine-readable. Il ne contacte pas la production et n'autorise aucun
résultat B hors scope.

Les tests de ce lot prouvent le calcul et les refus fail-closed sur la fixture.
Une exécution contre A puis B réels n'est admissible comme preuve de staging
qu'après peuplement gouverné de B ; le rapport du lot la maintient explicitement
comme gate non satisfaite. Le comparateur calcule rappel, rang et couverture,
mais ne produit aucun `PASS` tant que leurs seuils n'ont pas été fixés dans un
artefact opérateur versionné. La fuite de filtre, une citation incomplète et un
résultat hors périmètre restent toujours à tolérance zéro.

### 6. Shadow, cutover et rollback

Le moteur A reste intact. Le Lot 2 formalise un manifeste de cutover avec :

- SHA Git et digests d'images/configurations ;
- snapshots Chroma, SQLite cohérents, uploads et configuration A ;
- inventaire B, migrations et backup pgvector ;
- cible active et cible de rollback ;
- commandes de smoke bornées ;
- critères de parité et délai d'observation ;
- gates trusted-human-review et opérateur.

Toute capture A destinée à la migration, la parité ou au rollback exige une
preuve fraîche de quiescence : writers et tâches planifiées désactivés,
horodatage, ordre de capture Chroma puis `catalog.sqlite` et
`drive_sync_state.db` selon la méthode SQLite cohérente ci-dessus, puis uploads,
comptes et digests avant/après, et absence de mutation jusqu'à la décision de
trafic. Sans cette preuve, le manifeste reste `NO_GO`.

Le schéma distingue sans substitution :

- `snapshot_declared` et `snapshot_restored_verified` ;
- `real_parity_executed` ;
- `restore_rehearsal_verified` ;
- `traffic_rollback_tested` ;
- `cutover_authorized`.

Chaque preuve positive exige une référence d'évidence scellée. Pour le Lot 2,
les cinq faits d'exécution réelle restent forcés à `false` et le validateur
interdit tout statut `READY`, `GO_LIVE_READY` ou équivalent.

Un validateur refuse un manifeste sans checksums, sans images immuables, sans
état SQLite complet ou dont la cible de rollback est identique à la cible
canary. Le Lot 2 ne restaure rien et ne bascule aucun trafic. Le rehearsal
isolé de backup/restauration et la mutation Nginx appartiennent au Lot 8/9,
avant décommissionnement A.

Cette frontière est volontaire : ajouter aujourd'hui un sélecteur Nginx A/B
non lié à des images et snapshots A vérifiés fabriquerait un faux rollback.

## TDD et vérifications

Le développement suit Red → Green → Refactor :

1. tests rouges du tombstone et de l'absence de primitives de mutation ;
2. tests rouges du schéma de politique et de ses invariants ;
3. tests rouges de disposition exhaustive, déduplication, scellement et
   suppression du contenu/vecteur ;
4. tests rouges du comparateur de parité (citations, filtres, fuites,
   déterminisme) ;
5. tests rouges du manifeste de cutover/rollback fail-closed ;
6. tests ciblés, `ruff`, `mypy`, gouvernance, contrôles dépôt et suite locale
   pertinente.

Les tests unitaires et fixtures ne seront jamais présentés comme preuve de
production. Le rapport séparera `VERIFIED_LOCAL` des preuves staging/prod.

## Livrables et limites Git

Le lot utilise exclusivement la branche
`rag-engine/motor-convergence-20260825` et son worktree dédié. Il livre :

- la politique versionnée et son validateur ;
- le tombstone de migration directe ;
- la préparation read-only et ses fixtures ;
- le comparateur/corpus témoin ;
- le schéma de cutover/rollback ;
- un amendement ADR ;
- le rapport `docs/reports/lot_2_motor_convergence_20260825.md` ;
- une PR unique soumise à CI et trusted-human-review exacte.

Sont hors périmètre : publication réelle, ingestion Drive/Web, API externe,
cockpit, activation de collections, migration de production, bascule Nginx,
arrêt ou suppression de Chroma/SQLite et levée d'un verrou de gouvernance.

## Critères de sortie

Le Lot 2 est localement terminé seulement si :

- le migrateur direct refuse avant toute mutation ;
- 100 % des objets de la fixture d'inventaire ont une disposition ;
- aucune sortie ne contient texte de chunk ou embedding ;
- le digest du manifeste est déterministe et lié à l'entrée ;
- le comparateur refuse toute fuite de collection et toute citation
  incomplète ;
- le manifeste de rollback refuse tout état incomplet ;
- les tests et contrôles de dépôt pertinents sont verts ;
- le rapport n'affirme aucune parité réelle non exécutée ;
- la PR atteint un HEAD figé, CI verte, zéro thread et trusted-human-review
  conforme avant tout merge.

Le moteur A ne pourra être désactivé qu'après parité réelle, migration
gouvernée, sauvegarde/restauration et rollback de trafic effectivement testés.
