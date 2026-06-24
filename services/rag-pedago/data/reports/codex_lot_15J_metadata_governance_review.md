# Rapport Codex — Lot 15J-Audit : revue d’architecture metadata-only

## 1. Objectif

Auditer la chaîne de gouvernance metadata-only construite jusqu’au lot 15I, sans
ajouter de fonctionnalité. La revue distingue ce qui est implémenté, documenté,
testé, encore interdit, et les conditions minimales avant tout futur brouillon
réel metadata-only.

Ce lot ne crée aucun brouillon réel, aucun manifest réel, aucun document source
et aucun dossier `data/staging`.

## 2. Point de départ Git

- dépôt : `/home/alaeddine/Bureau/rag-pedago` ;
- branche : `main` ;
- commit de départ : `fe67d68 feat: add metadata-only preflight` ;
- dépôt propre au démarrage du lot ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` : 370 passed ;
- vérification `rag-local` : aucun rapport 15J ni document de revue 15J détecté.

Tous les fichiers demandés pour la revue existent :

- protocoles `docs/PILOT_CORPUS_PROTOCOL.md`, `docs/REAL_MINIMAL_DRAFT_PROTOCOL.md`,
  `docs/HUMAN_UNLOCK_PROTOCOL.md`, `docs/REAL_DRAFT_UNLOCK_GATE_PROTOCOL.md`,
  `docs/METADATA_PREFLIGHT_PROTOCOL.md` ;
- modules 15C à 15I ;
- tests unitaires associés ;
- rapports 15A à 15I ;
- `Makefile`.

## 3. Chaîne auditée

La chaîne auditée est :

```text
15A protocole corpus pilote
15B fixtures synthétiques metadata-only
15C kit de préparation manifest réel
15D compilateur offline brouillon rempli -> JSONL
15E rehearsal complet metadata-only
15F garde-fou brouillon réel metadata-only
15G verrou humain
15H gate combiné unlock + draft
15I preflight global
```

La chaîne opérationnelle courante reste synthétique ou metadata-only. Elle ne
traite pas de PDF, ne lit aucun `source_uri`, ne crée pas `data/staging` et ne
prépare pas encore de manifest réel prêt pour import.

## 4. Cartographie des lots 15A à 15I

### 15A : protocole corpus pilote

- objectif : cadrer le corpus pilote mathématiques terminale spécialité ;
- fichiers principaux : `docs/PILOT_CORPUS_PROTOCOL.md`,
  `data/reports/codex_lot_15A_state_map_and_pilot_protocol.md` ;
- commande Makefile associée : aucune cible dédiée ;
- tests associés : doctors et suite existante ;
- statut attendu : protocole documentaire ;
- autorisé : définir le cadre, les métadonnées et les interdictions ;
- interdit : ingestion, scraping, lecture `source_uri`, PDF, Qdrant, document réel.

### 15B : fixtures synthétiques metadata-only

- objectif : ajouter des manifests synthétiques mathématiques terminale ;
- fichiers principaux : fixtures sous `data/fixtures/pilot_math_terminale/` ;
- commande Makefile associée : aucune cible dédiée propre au lot ;
- tests associés : tests de fixtures pilotes et suite complète ;
- statut attendu : fixtures valides en `synthetic://` ;
- autorisé : validation metadata-only sur données synthétiques ;
- interdit : source réelle, PDF, scraping, ingestion documentaire.

### 15C : kit de préparation manifest réel

- objectif : créer un kit de préparation humain sans brouillon réel ;
- fichiers principaux : templates `docs/templates/pilot_math_terminale/`,
  `rag_pedago/imports/pilot_manifest_template.py` ;
- commande Makefile associée : `pilot-template-check` ;
- tests associés : `tests/unit/test_pilot_manifest_template.py` ;
- statut attendu : `needs_completion` tant que les placeholders restent présents ;
- autorisé : vérifier templates, placeholders, formes et chemins interdits ;
- interdit : ouvrir `source_uri`, créer un PDF, créer `data/staging`.

### 15D : compilateur offline brouillon rempli -> JSONL

- objectif : compiler un brouillon synthétique rempli en JSONL validant
  `DocumentMeta` ;
- fichiers principaux : `rag_pedago/imports/pilot_manifest_compiler.py`,
  brouillons synthétiques remplis ;
- commande Makefile associée : `pilot-compile-check` ;
- tests associés : `tests/unit/test_pilot_manifest_compiler.py` ;
- statut attendu : `ready` pour le brouillon synthétique valide ;
- autorisé : validation Pydantic, émission JSONL en mémoire ou stdout ;
- interdit : ouvrir `source_uri`, calculer un hash réel, lire un PDF, ingestion.

### 15E : rehearsal complet metadata-only

- objectif : répéter la chaîne complète sur brouillon synthétique avec ledger
  temporaire ;
- fichiers principaux : `rag_pedago/imports/pilot_metadata_rehearsal.py` ;
- commande Makefile associée : `pilot-rehearsal` ;
- tests associés : `tests/unit/test_pilot_metadata_rehearsal.py` ;
- statut attendu : `ready`, `dry_run_success`, `coverage_ok`,
  `ready_for_controlled_import`, `ready_for_review`, `approved`, `imported`,
  `recorded` ;
- autorisé : écriture runtime dans répertoire temporaire et ledger temporaire ;
- interdit : ledger permanent, `data/staging`, `source_uri` réel, PDF, Qdrant.

### 15F : garde-fou brouillon réel metadata-only

- objectif : valider des métadonnées candidates synthétiques avant brouillon réel ;
- fichiers principaux : `docs/REAL_MINIMAL_DRAFT_PROTOCOL.md`,
  `rag_pedago/imports/real_draft_guard.py` ;
- commande Makefile associée : `real-draft-guard-check` ;
- tests associés : `tests/unit/test_real_draft_guard.py` ;
- statut attendu : `ready_for_human_locked_metadata_validation` ;
- autorisé : contrôler droits, visibilité, SHA déclaré, contexte AEFE, candidat,
  chemins interdits et review humaine requise ;
- interdit : ouvrir le chemin source, vérifier l’existence du fichier source,
  calculer un hash, écrire un fichier.

### 15G : verrou humain

- objectif : exiger une autorisation humaine formelle avant tout futur lot réel ;
- fichiers principaux : `docs/HUMAN_UNLOCK_PROTOCOL.md`,
  `docs/templates/human_unlock/`, `rag_pedago/imports/human_unlock_guard.py` ;
- commande Makefile associée : `human-unlock-check` ;
- tests associés : `tests/unit/test_human_unlock_guard.py` ;
- statut attendu : `approved_for_metadata_only_next_step` ;
- autorisé : lire uniquement un JSON d’autorisation ;
- interdit : autoriser parsing, ingestion, scraping, Qdrant, embedding,
  `data/staging`, ledger permanent ou plus de 2 items.

### 15H : gate combiné unlock + draft

- objectif : vérifier la cohérence entre autorisation humaine et brouillon
  metadata-only candidat ;
- fichiers principaux : `docs/REAL_DRAFT_UNLOCK_GATE_PROTOCOL.md`,
  `rag_pedago/imports/real_draft_unlock_gate.py` ;
- commande Makefile associée : `real-draft-unlock-gate-check` ;
- tests associés : `tests/unit/test_real_draft_unlock_gate.py` ;
- statut attendu : `approved_for_real_metadata_draft_preparation` ;
- autorisé : comparer les champs de périmètre entre unlock et draft ;
- interdit : produire un manifest prêt pour ingestion, lire `source_uri`, écrire
  un fichier.

### 15I : preflight global

- objectif : agréger les garde-fous metadata-only et produire un verdict global ;
- fichiers principaux : `docs/METADATA_PREFLIGHT_PROTOCOL.md`,
  `rag_pedago/imports/metadata_preflight.py` ;
- commande Makefile associée : `metadata-preflight` ;
- tests associés : `tests/unit/test_metadata_preflight.py` ;
- statut attendu : `metadata_preflight_ready` ;
- autorisé : orchestrer les sous-checks existants, avec rehearsal en temporaire ;
- interdit : brouillon réel, manifest réel, `data/staging`, ledger permanent,
  lecture `source_uri`, PDF, scraping, Qdrant, ingestion.

## 5. Commandes Makefile liées à la gouvernance metadata-only

Cibles de gouvernance metadata-only :

- `pilot-template-check` ;
- `pilot-compile-check` ;
- `pilot-rehearsal` ;
- `real-draft-guard-check` ;
- `human-unlock-check` ;
- `real-draft-unlock-gate-check` ;
- `metadata-preflight`.

Ces cibles utilisent des fixtures synthétiques ou des templates, n’ouvrent pas
de document source et ne lancent pas d’ingestion documentaire réelle.

Cibles Makefile présentes mais hors chaîne metadata-only :

- `manifest-import-fixture` ;
- `manifest-dir-import-fixture` ;
- `manifest-controlled-import-clean` ;
- `manifest-controlled-import-problem` ;
- `review-package-clean-audited` avec `--audit-ledger data/ledger/rag_pedago.sqlite` ;
- `init`, qui lance aussi `scripts/init_qdrant.py` ;
- `scrape-official` ;
- `ingest`, `ingest-official`, `ingest-internal`.

Ces cibles ne sont pas appelées par `metadata-preflight`, mais elles constituent
un risque opératoire si elles sont lancées manuellement dans un futur lot qui se
croirait encore metadata-only.

## 6. Modules Python concernés

Modules de la chaîne metadata-only :

- `pilot_manifest_template.py` : validation de templates et placeholders ;
- `pilot_manifest_compiler.py` : compilation offline vers JSONL DocumentMeta ;
- `pilot_metadata_rehearsal.py` : rehearsal complet avec ledger temporaire ;
- `real_draft_guard.py` : garde-fou sur métadonnées candidates ;
- `human_unlock_guard.py` : validation JSON d’autorisation humaine ;
- `real_draft_unlock_gate.py` : cohérence unlock + draft ;
- `metadata_preflight.py` : orchestration globale et verdict.

Ce qui est réellement implémenté :

- validateurs offline ;
- rapports en mémoire ou stdout ;
- refus de droits inconnus, chemins interdits, marqueurs sensibles, incohérences
  AEFE/candidat, absence de validation humaine ;
- rehearsal temporaire contrôlé ;
- preflight global.

Ce qui reste documentaire :

- préparation de vrais documents sources hors dépôt ;
- calcul manuel réel de SHA-256 ;
- validation humaine réelle ;
- passage à un brouillon réel minimal ;
- toute ingestion documentaire future.

## 7. Tests concernés

Tests unitaires associés :

- `test_pilot_manifest_template.py` : 16 tests ;
- `test_pilot_manifest_compiler.py` : 16 tests ;
- `test_pilot_metadata_rehearsal.py` : 8 tests ;
- `test_real_draft_guard.py` : 11 tests ;
- `test_human_unlock_guard.py` : 13 tests ;
- `test_real_draft_unlock_gate.py` : 11 tests ;
- `test_metadata_preflight.py` : 11 tests.

Les tests couvrent les cas nominaux et les cas bloqués principaux :
placeholders, droits inconnus, chemins interdits, mauvaises zones, mauvais
statut candidat, parsing autorisé, trop d’items, absence de review humaine,
fixture invalide, sous-check preflight bloqué.

## 8. Statuts attendus

- template : `needs_completion` ;
- compile : `ready` ;
- rehearsal : `rehearsal_ok` au preflight, avec sous-statuts `ready`,
  `dry_run_success`, `coverage_ok`, `ready_for_controlled_import`,
  `ready_for_review`, `approved`, `imported`, `recorded` ;
- real draft guard : `ready_for_human_locked_metadata_validation` ;
- human unlock : `approved_for_metadata_only_next_step` ;
- unlock gate : `approved_for_real_metadata_draft_preparation` ;
- preflight : `metadata_preflight_ready`.

Les statuts sont cohérents entre les garde-fous : chaque étape aval réutilise le
statut attendu de l’étape amont et bloque si celui-ci diverge.

## 9. Garanties actuellement couvertes

- aucune lecture de `source_uri` par les validateurs metadata-only ;
- aucune lecture de PDF/DOCX/PPTX/XLSX ;
- aucun document réel dans les fixtures et templates vérifiés ;
- aucun dossier `data/staging` créé ;
- ledger permanent non modifié par les cibles 15E à 15I ;
- rehearsal écrit uniquement en temporaire ;
- chemins `rag-local` et `rag-ui` refusés dans les garde-fous ;
- marqueurs sensibles refusés ou documentés comme fixtures invalides ;
- droits `unknown` bloqués ;
- visibilité publique refusée pour droits internes/restreints ;
- cohérence AEFE Tunisie et candidat scolarisé contrôlée ;
- source officielle `pending` seule refusée ;
- limite `max_items <= 2` pour le futur brouillon réel ;
- validation humaine explicite requise ;
- absence de validation du contenu pédagogique explicitement documentée.

## 10. Angles morts recherchés

1. Commande pouvant lancer par erreur une ingestion documentaire.
2. Commande pouvant créer `data/staging`.
3. Commande pouvant écrire dans le ledger permanent.
4. Commande pouvant lire un `source_uri`.
5. Commande pouvant lire un PDF.
6. Chemin `file://` réel dans les fixtures.
7. Chemin vers `rag-local` ou `rag-ui` hors cas invalide documenté.
8. Faux positif sensible non documenté.
9. Cohérence des statuts entre garde-fous.
10. Mention claire que le contenu pédagogique n’est pas validé.
11. Blocage suffisant avant brouillon réel par human unlock + real draft guard +
    unlock gate + preflight.
12. Couverture des cas bloqués pour chaque garde-fou.

## 11. Angles morts trouvés

- Le `Makefile` contient encore des cibles hors gouvernance metadata-only qui
  peuvent lancer import, import contrôlé, audit ledger permanent, initialisation
  Qdrant, scraping ou ingestion si elles sont appelées explicitement. Elles ne
  sont pas appelées par `metadata-preflight`, mais leur présence exige une
  discipline de lot stricte.
- `docs/PILOT_CORPUS_PROTOCOL.md` contient des exemples documentaires historiques
  avec `file://data/staging/...` et des commandes futures sur `data/staging`.
  Ces exemples ne sont pas des fixtures ni des manifests réels, mais ils doivent
  être relus avant tout lot réel pour éviter une interprétation opérationnelle
  prématurée.
- Le fichier permanent `data/ledger/rag_pedago.sqlite` peut exister localement.
  La chaîne 15E-15I vérifie l’absence de modification, pas l’absence physique du
  fichier.
- La validation humaine réelle n’est pas encore une preuve externe : le verrou
  15G valide un JSON et ses champs, pas l’identité réelle d’un reviewer ni la
  validité juridique des droits.
- Les SHA-256 réels restent hors pipeline par conception. La chaîne vérifie la
  présence et la forme d’un SHA déclaré, mais ne le calcule pas.
- Le contenu pédagogique n’est pas validé. Les notions, compétences et références
  sont contrôlées metadata-only, pas le contenu d’un document.

Constats non bloquants :

- les seuls chemins `file://` observés dans les fixtures sont des cas invalides
  documentés ;
- les chemins `rag-local` et `rag-ui` dans les fixtures apparaissent uniquement
  dans des fixtures invalides destinées aux tests ;
- le faux positif sensible connu
  `data/fixtures/pilot_math_terminale/human_unlock/human_unlock.invalid_secret_marker.json`
  est documenté et synthétique.

## 12. Risques résiduels

- lancement manuel d’une cible Makefile hors périmètre metadata-only ;
- confusion entre protocole documentaire 15A et commandes autorisées dans les
  lots récents ;
- confiance excessive dans un JSON d’autorisation synthétique ;
- droits réels, absence de données personnelles et provenance à vérifier hors
  pipeline ;
- risque de préparer trop tôt un `source_uri` réel sans validation humaine ;
- aucune preuve de qualité pédagogique des contenus futurs ;
- pas de validation de disponibilité réelle des sources, volontairement.

## 13. Conditions minimales avant tout futur brouillon réel

Avant tout brouillon réel metadata-only, il faut au minimum :

- dépôt propre après commit dédié de la revue ;
- relecture humaine des protocoles 15F, 15G, 15H et 15I ;
- confirmation écrite qu’aucun lot d’ingestion, scraping, Qdrant, Docker ou API
  n’est démarré ;
- liste des 1 à 2 documents sources tenue hors dépôt ;
- droits connus et non `unknown` ;
- absence de données personnelles élève ;
- SHA-256 calculés manuellement hors pipeline ;
- aucune copie de document dans le dépôt ;
- aucun PDF ouvert ou parsé ;
- aucune création de `data/staging` ;
- autorisation humaine JSON réelle validée par `human_unlock_guard` ;
- brouillon metadata-only candidat validé par `real_draft_guard` ;
- cohérence unlock + draft validée par `real_draft_unlock_gate` ;
- `metadata-preflight` vert juste avant le futur lot ;
- décision humaine explicite de rester metadata-only.

## 14. Décision recommandée

READY_FOR_HUMAN_REVIEW

La chaîne metadata-only est cohérente et testée pour une revue humaine. Elle ne
doit pas encore passer à un brouillon réel sans validation humaine explicite et
sans lot séparé, strictement borné.

## 15. Recommandation pour un futur lot 15K

Ne proposer un lot 15K que s’il reste metadata-only. Une option raisonnable
serait un audit de durcissement documentaire et Makefile, par exemple clarifier
une allowlist de cibles metadata-only autorisées et rappeler explicitement que
les cibles historiques d’ingestion, scraping, Qdrant et ledger permanent sont
hors périmètre des lots de gouvernance.
