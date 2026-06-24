# Rapport Codex — Lot 17A : audit fonctionnel global du RAG pédagogique

## 1. Objectif

Auditer l’état fonctionnel et technique du RAG pédagogique après la clôture du cycle cleanup governance 16A à 16E.

Le lot 17A ne lance aucun nettoyage réel, aucune ingestion, aucun embedding, aucun accès Qdrant et aucune modification de `rag-local`. Il produit uniquement un protocole d’audit et ce rapport.

## 2. Point de départ

Point de départ vérifié dans `/home/alaeddine/Bureau/RAG/rag-pedago` :

- `HEAD` : `5f8d694 feat: add cleanup decision draft` ;
- `git status --short --branch` initial : `## main` ;
- `make cleanup-dry-run` : OK, `would_delete: 0`, `would_move: 0` ;
- `make cleanup-review` : OK, `human_review_required: true`, `destructive_action_available: false` ;
- `make cleanup-decision-draft` : OK, `human_decision_required: true`, `decision_applied: false`, `destructive_action_available: false` ;
- `make metadata-preflight` : OK, `data_staging_absent: True`, `permanent_ledger_unchanged: True`, `real_documents_absent: True` ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` initial : `408 passed in 82.82s`.

`rag-local` a été vérifié en lecture seule avec les non-suivis préexistants :

- `?? .windsurf/` ;
- `?? rag-ui-nexusreussite-academy-tree-20260613_222121.txt`.

## 3. Méthode d’audit

Méthode suivie :

- lecture ciblée de `README.md`, `AGENTS.md`, `Makefile`, `docs/`, `schema/`, `taxonomy/`, `rag_pedago/`, `tests/`, `data/fixtures/`, `data/reference/` et des rapports Codex ;
- inventaires bornés par scripts Python de lecture ;
- vérification de l’absence de composants opérationnels dans `retrieval/`, `pipeline/` et `services/api/` ;
- utilisation des commandes non destructives demandées ;
- aucune lecture de `.env` ;
- aucun scan profond de `rag-local`, `.git`, secrets, credentials ou racines lourdes exclues ;
- respect de la règle de recherche shell : pas de backticks non échappés, pas de motifs avec `?` ou `*` non protégés, pas de commande ayant provoqué `command not found`.

## 4. Inventaire du projet

Dossiers principaux observés :

- `configs/` : configuration de cleanup policy ;
- `docs/` : 47 fichiers environ, protocoles, contrats, politiques, architecture et workflows ;
- `scripts/` : scripts de cleanup dry-run, review package, decision draft et doctor ;
- `tests/` : 52 fichiers environ, principalement unitaires ;
- `rag_pedago/` : imports metadata-only, ledger, référence officielle, paths et project-doctor ;
- `schema/` : modèles Pydantic document, chunk, retrieval, source, ledger, taxonomie, profils ;
- `taxonomy/` : taxonomies Maths terminale spécialité, NSI terminale, commun, examens, propositions ;
- `data/reference/` : 22 fichiers de référentiel institutionnel ;
- `data/fixtures/` : manifests et fixtures synthétiques, dont pilote mathématiques terminale ;
- `data/reports/` : rapports Codex versionnés et nombreux rapports runtime historiques ;
- `pipeline/`, `retrieval/`, `services/api/`, `services/mcp/`, `services/workers/` : paquets présents mais encore squelettiques.

Scripts existants :

- `scripts/doctor.py` ;
- `scripts/cleanup_dry_run.py` ;
- `scripts/cleanup_review_package.py` ;
- `scripts/cleanup_decision_draft.py`.

Cibles Makefile observées :

- diagnostics : `doctor`, `project-doctor`, `test`, `lint`, `format`, `typecheck` ;
- ledger : `ledger-init`, `ledger-doctor` ;
- manifests : `manifest-import-fixture`, `manifest-dir-dry-run`, `manifest-dir-import-fixture` ;
- readiness, coverage, gate : familles standard et clean ;
- controlled import : `manifest-controlled-import-clean`, `manifest-controlled-import-problem` ;
- review : `review-package-clean-audited` ;
- gouvernance pilote : `pilot-template-check`, `pilot-compile-check`, `pilot-rehearsal`, `real-draft-guard-check`, `human-unlock-check`, `real-draft-unlock-gate-check`, `metadata-preflight` ;
- cleanup governance : `cleanup-dry-run`, `cleanup-review`, `cleanup-decision-draft` ;
- cibles futures à risque si lancées sans lot dédié : `init`, `scrape-official`, `ingest`, `ingest-official`, `ingest-internal`, `eval-retrieval`, `watch`, `api`.

Tests :

- 46 fichiers unitaires observés sous `tests/unit/` ;
- tests d’intégration et e2e présents comme dossiers mais seulement avec `.gitkeep` ;
- tests retrieval limités au schéma `schema/retrieval.py` ;
- aucun test d’API ou de retrieval opérationnel observé.

Protocoles et documents notables :

- `docs/ARCHITECTURE.md` ;
- `docs/WORKFLOWS.md` ;
- `docs/METADATA_PREFLIGHT_PROTOCOL.md` ;
- `docs/PILOT_CORPUS_PROTOCOL.md` ;
- `docs/REAL_MINIMAL_DRAFT_PROTOCOL.md` ;
- `docs/HUMAN_UNLOCK_PROTOCOL.md` ;
- `docs/REAL_DRAFT_UNLOCK_GATE_PROTOCOL.md` ;
- `docs/CLEANUP_POLICY.md` ;
- `docs/CLEANUP_REVIEW_PROTOCOL.md` ;
- `docs/CLEANUP_DECISION_PROTOCOL.md` ;
- `docs/RETRIEVAL_CONTRACT.md` ;
- `docs/contracts/*.yml`.

Configurations :

- `configs/cleanup_policy.yml` ;
- contrats YAML dans `docs/contracts/`.

Fixtures :

- manifests synthétiques généralistes ;
- batchs clean, problématiques et mismatch officiels ;
- fixtures pilote mathématiques terminale spécialité ;
- brouillons synthétiques et garde-fous metadata-only.

Schémas :

- `DocumentMeta` et `ChunkMeta` ;
- `RetrievalRequest`, `RetrievalResponse`, citations et options ;
- `SourceManifestItem`, `SourceTrust` ;
- `StudentProfile` ;
- modèles ledger et référentiel officiel.

Taxonomies :

- Maths terminale spécialité ;
- NSI terminale ;
- niveaux, épreuves, statuts candidats, types documents ;
- dossiers de propositions séparés.

Données permanentes :

- ledger permanent attendu sous `data/ledger/rag_pedago.sqlite`, présent mais non modifié pendant ce lot ;
- `.gitkeep` versionné dans `data/ledger/`.

Zones explicitement interdites :

- `rag-local` ;
- `/srv/nexusreussite/rag-ui` ;
- `.env`, secrets, credentials ;
- documents réels, PDF, uploads privés ;
- Qdrant, embeddings, scraping, ingestion réelle.

## 5. Audit par couche

### 5.1 Objectif produit

Le produit vise un RAG pédagogique local pour Nexus Réussite, capable à terme de servir des cockpits élèves personnalisés avec filtrage fort par niveau, matière, enseignement, épreuve, statut candidat, droits, références officielles et citations.

Public visé :

- élèves accompagnés par Nexus ;
- enseignants ou équipe pédagogique ;
- administrateurs validant les ressources et décisions ;
- à terme, parents ou profils avec droits spécifiques.

Matières et niveaux couverts aujourd’hui :

- schémas multi-niveaux : troisième, seconde, première, terminale, cycle 4, lycée général et technologique ;
- taxonomies concrètes : mathématiques terminale spécialité et NSI terminale ;
- référentiels : DNB, bac général, EAF, philosophie, Grand oral, spécialités, candidats individuels, AEFE ;
- corpus pilote explicite : mathématiques terminale spécialité, AEFE Tunisie, candidat scolarisé.

Différence prototype, pilote, production :

- prototype : schémas, fixtures, manifests, gates et ledger metadata-only ;
- pré-pilote : préparation de corpus et validation humaine sans document réel ;
- pilote : petit corpus validé, ingestion réelle bornée, retrieval mesuré et citations contrôlées ;
- production : API/UI, supervision, droits robustes, évaluation continue, rollback et exploitation.

État actuel estimé : pré-pilote metadata-only solide. Le projet n’est pas encore un RAG produit, car parsing, chunking, embeddings, vector store, retrieval opérationnel, API et UI sont absents.

### 5.2 Corpus et sources

Corpus réel :

- aucun corpus réel exploitable n’est présent ou validé pour ingestion ;
- les fixtures et templates interdisent explicitement PDF, DOCX, PPTX, XLSX et documents réels ;
- `metadata-preflight` confirme `real_documents_absent: True`.

Fixtures synthétiques :

- manifests clean et problématiques ;
- fixtures officielles multi-profils ;
- pilote mathématiques terminale spécialité ;
- unlock humain synthétique et brouillons remplis synthétiques.

Capacité actuelle :

- bonne capacité à préparer un corpus pilote metadata-only ;
- bonne capacité à valider droits, visibilité, références officielles, readiness, coverage et gate ;
- pas encore de capacité à lire, parser, chunker ou indexer un document source.

Risques :

- droits et visibilité restent à valider humainement pour tout corpus réel ;
- sources officielles doivent être revérifiées dans un lot dédié avant usage réglementaire ;
- données internes Nexus et ressources publiques ne doivent pas être mélangées sans `rights` et `visibility`.

### 5.3 Métadonnées

`DocumentMeta` est le point fort du socle :

- champs source : `doc_id`, `source_uri`, `source_type`, `sha256`, dates ;
- droits : `rights`, `visibility`, contextes autorisés ;
- pédagogie : `niveau`, `voie`, `matiere`, `statut_enseignement`, `type_doc`, `epreuve`, `candidat` ;
- temporalité : années scolaires, session, validité ;
- références officielles : niveaux, examens, matières, statuts candidats, sources et claims ;
- pédagogie fine : notions, compétences, prérequis, objectifs ;
- qualité : difficulté, durée, modalité, score, confiance.

Forces :

- validation Pydantic stricte ;
- `rights=unknown` rend le document non récupérable ;
- `ChunkMeta` existe déjà et prépare le futur chunking ;
- `RetrievalRequest` sait produire des filtres payload depuis `StudentProfile`.

Fragilités :

- `DocumentMeta` est riche mais beaucoup de champs restent manuels ;
- pas encore de validation automatique du contenu pédagogique réel ;
- pas encore de champ explicite `zone` dans `DocumentMeta`, compensé dans les protocoles par `extra` ;
- compatibilité avec un futur moteur vectoriel non encore prouvée.

### 5.4 Taxonomies et référentiels

Taxonomies :

- mathématiques terminale spécialité structurée par thèmes, notions et compétences ;
- NSI terminale structurée par thèmes ;
- référentiels communs pour types de documents, niveaux, épreuves et statuts candidats.

Référentiels officiels :

- sources officielles et institutionnelles locales ;
- niveaux, examens, matières, options, spécialités ;
- claims vérifiés et un claim local Tunisie encore `pending`.

Forces :

- séparation claire entre taxonomies officielles et propositions ;
- tests dédiés aux références officielles, intégrité, qualité et explicabilité ;
- règles qualité bloquantes pour références inconnues ou claims réglementaires non vérifiés.

Risques :

- divergence possible si les sources officielles changent ;
- certains champs restent manuels ;
- une source locale `pending` ne doit pas soutenir seule une réponse réglementaire ;
- il faudra un processus de refresh ou revue officielle datée.

### 5.5 Pipeline d’import

Pipeline actuel :

- manifest JSONL ;
- quality policy ;
- readiness ;
- coverage ;
- gate ;
- review package ;
- approval/rejection humain ;
- controlled import ;
- audit ledger.

Forces :

- gate avant import ;
- import contrôlé limité aux métadonnées ;
- hashes des manifests, rapports, référentiel officiel et taxonomies ;
- audit SQLite des review packages, décisions et tentatives ;
- tests couvrant batchs bloqués, clean, review obligatoire et ledger.

Limites :

- `import_manifest_directory` peut écrire un ledger temporaire ou permanent selon commande, mais aucun document source n’est ouvert ;
- les cibles Makefile d’import existent et doivent rester réservées aux lots dédiés ;
- `data/reports/` contient beaucoup de rapports runtime historiques, ce qui complique la lisibilité.

État : READY_FOR_REVIEW pour metadata-only, pas prêt pour ingestion documentaire réelle.

### 5.6 Recherche / retrieval / évaluation

Présent :

- `schema/retrieval.py` ;
- `docs/RETRIEVAL_CONTRACT.md` ;
- test de schéma retrieval ;
- package `retrieval/` présent.

Absent :

- moteur de recherche ;
- index lexical ou vectoriel ;
- embeddings ;
- Qdrant ;
- reranking ;
- golden set ;
- évaluation retrieval ;
- métriques de pertinence ;
- jeux de questions pédagogiques ;
- traçabilité effective des citations au niveau chunk.

Risques :

- l’hallucination et la citation non prouvée ne sont pas encore traitées par un runtime ;
- les critères pédagogiques de pertinence sont documentaires mais pas mesurés ;
- aucun résultat retrieval réel ne peut être audité aujourd’hui.

État : DRAFT.

### 5.7 API / interface / usage pédagogique

Présent :

- package `services/api/` avec un `__init__.py` seulement ;
- cible Makefile `api` pointant vers `services.api.main:app`.

Absent :

- `services/api/main.py` ;
- endpoints ;
- UI ;
- workflow enseignant opérationnel ;
- workflow élève opérationnel ;
- feedback pédagogique ;
- validation UX ;
- cockpit.

Risque :

- la cible `api` existe mais le module applicatif attendu n’est pas implémenté ; elle ne doit pas être considérée comme prête.

État : ABSENT à DRAFT.

### 5.8 Tests et qualité

Forces :

- 408 tests passent ;
- forte couverture des schémas, quality policy, official references, manifests, readiness, coverage, gate, review, controlled import, ledger, cleanup governance, metadata preflight ;
- tests CLI et non-destruction sur les lots cleanup ;
- project-doctor vérifie contrats, secrets évidents, imports réseau dans les modules d’import et patterns d’ouverture de `source_uri`.

Manques :

- tests d’intégration et e2e non implémentés ;
- pas de tests API ;
- pas de tests retrieval opérationnel ;
- pas de tests de performance produit ;
- tests actuels très orientés gouvernance metadata-only.

Lenteurs :

- `make test` dure environ 80 à 90 secondes sur ce poste ;
- acceptable pour validation complète locale, mais un découpage par suites sera utile avant d’ajouter retrieval/API.

### 5.9 Sécurité et gouvernance

Forces :

- interdictions documentées dans `AGENTS.md`, `README.md`, contrats et protocoles ;
- `rag-local` read-only ;
- `data/staging` absent ;
- ledger permanent protégé ;
- cleanup governance 16A à 16E très solide ;
- protocols metadata-only verrouillent documents réels, source URI, PDF, Qdrant, embeddings, scraping et réseau ;
- project-doctor bloque les imports réseau dans `rag_pedago/imports`.

Risques :

- certaines cibles Makefile futures (`init`, `scrape-official`, `ingest`, `api`) peuvent être dangereuses si lancées hors lot dédié ;
- la méthode shell doit rester stricte pour éviter les expansions involontaires ;
- les rapports runtime historiques peuvent brouiller les audits.

La règle de recherche shell du lot 17A a été respectée : les vérifications textuelles ont utilisé des lectures ciblées et scripts Python bornés, sans motifs shell dangereux ni erreur `command not found`.

### 5.10 Documentation

Forces :

- README clair sur l’état metadata-only ;
- AGENTS très explicite ;
- architecture, workflows, contrats et protocoles nombreux ;
- rapports Codex continus depuis les premiers lots ;
- politiques cleanup et décisionnelles récentes.

Manques :

- documentation utilisateur finale absente ;
- documentation API/UI absente car composants absents ;
- documentation exploitation production absente ;
- documentation pédagogique d’usage élève/enseignant encore à écrire ;
- roadmap produit à formaliser après cette revue.

## 6. Matrice de maturité

| Couche | État | Niveau de maturité | Tests existants | Risques | Prochaine action |
|---|---|---|---|---|---|
| Objectif produit | bien documenté, non livré comme produit | READY_FOR_REVIEW | doctors, docs contracts | confusion pré-pilote vs produit | formaliser roadmap produit 17B |
| Corpus et sources | synthétique metadata-only | PARTIAL | fixtures, preflight, guards | aucun corpus réel validé | préparer corpus pilote synthétique ou metadata-only |
| Métadonnées | schéma robuste | READY_FOR_REVIEW | document, rights, source, student profile | champs manuels, zone dans extra | stabiliser un profil pilote |
| Taxonomies et référentiels | contrôlés et testés | READY_FOR_REVIEW | taxonomy, official reference | divergence officielle future | protocole de refresh/revue |
| Pipeline d’import metadata-only | complet avec gate et ledger | READY_FOR_REVIEW | readiness, coverage, gate, review, controlled import | usage accidentel de cibles d’import | clarifier cibles autorisées par lot |
| Parsing/chunking | non implémenté | ABSENT | ChunkMeta seulement | impossible de créer corpus RAG réel | lot dédié après validation corpus |
| Retrieval/évaluation | contrat et schémas seulement | DRAFT | retrieval schema | pas de moteur ni métriques | golden set et fake retrieval offline |
| API/UI | squelette uniquement | DRAFT | aucun test API | cible `api` non fonctionnelle | spécification API/UI |
| Tests et qualité | forte suite metadata-only | READY_FOR_REVIEW | 408 tests | peu d’intégration/e2e | segmenter et ajouter tests produit |
| Sécurité/gouvernance | très solide | READY_FOR_REVIEW | doctors, contracts, cleanup tests | cibles dangereuses existantes | garde-fou Makefile/documentation |
| Documentation | riche côté dev/gouvernance | READY_FOR_REVIEW | project-doctor | doc utilisateur absente | roadmap et docs pédagogiques |

Maturité globale estimée : PARTIAL. Le socle est solide pour une revue roadmap et un pré-pilote metadata-only, mais le RAG opérationnel est bloqué par l’absence de corpus réel validé, parsing, chunking, embeddings, retrieval, API et UI.

## 7. Dettes et angles morts

Les dettes P0 ci-dessous sont bloquantes avant un pilote RAG opérationnel ou un usage produit ; elles ne remettent pas en cause la validité du socle metadata-only ni des audits de gouvernance déjà réalisés.

| Priorité | Dette | Preuve observée | Risque | Lot recommandé |
|---|---|---|---|---|
| P0 | Aucun retrieval opérationnel | `retrieval/__init__.py` seul et test limité au schéma | pas de RAG utilisable | 17D |
| P0 | Aucun corpus réel validé pour pilote | fixtures synthétiques et `real_documents_absent: True` | impossible de tester pertinence réelle | 17C |
| P0 | Aucun parsing/chunking documentaire | README liste parsing PDF, OCR et chunking comme absents | pas d’index exploitable | 17F ou lot dédié parsing |
| P0 | Aucun embedding/vector store | README et architecture listent embeddings/Qdrant comme absents | pas de recherche sémantique | lot après golden set |
| P0 | API/UI non implémentées | `services/api/__init__.py` seul, pas de `main.py` | aucun usage élève/enseignant | 17E |
| P1 | Critères de pertinence pédagogique non mesurés | pas de golden set ni tests retrieval | pertinence non objectivable | 17D |
| P1 | Droits du futur corpus réel non validés | protocole pilote seulement | risque légal et visibilité | 17C |
| P1 | Sources officielles à rafraîchir avant usage réglementaire | sources datées 2026-06-14 et claim Tunisie pending | réponses réglementaires fragiles | 17B/17C |
| P1 | Cibles Makefile dangereuses présentes | `init`, `scrape-official`, `ingest`, `api` | lancement accidentel hors lot | 17B |
| P2 | Tests d’intégration/e2e vides | dossiers `.gitkeep` seulement | régressions de workflow produit non couvertes | 17D/17E |
| P2 | Documentation utilisateur absente | docs surtout dev/gouvernance | adoption difficile | 17E |
| P2 | Rapport runtime massif dans `data/reports` | 3474 fichiers observés | audits moins lisibles | post-cleanup review future |
| P3 | Temps de suite complète | environ 80 à 90 secondes | boucle dev plus lente | segmenter suites |

## 8. Risques

Risques fonctionnels :

- le projet peut être perçu comme un RAG alors qu’il est encore metadata-only ;
- absence de retrieval réel, d’évaluation et de citations effectives ;
- corpus réel non qualifié.

Risques techniques :

- cibles Makefile non utilisées dans ce lot mais dangereuses si lancées sans consigne ;
- absence d’API opérationnelle malgré une cible `api` ;
- dépendances minimales actuelles sans stack retrieval.

Risques de gouvernance :

- droits et visibilité devront rester bloquants ;
- sources officielles doivent être revues avant réponses réglementaires ;
- tout passage à documents réels doit rester loti et humainement validé.

## 9. Feuille de route recommandée

17B — Durcissement roadmap et garde-fous opérationnels :

- clarifier les cibles Makefile autorisées/interdites par phase ;
- documenter le statut exact pré-pilote ;
- ajouter si nécessaire un test de contrat sur l’absence d’API opérationnelle implicite.

17C — Préparation corpus pilote strictement synthétique ou metadata-only :

- choisir le périmètre mathématiques terminale spécialité ;
- préparer un dossier de décision humaine sans document réel ;
- lister droits, sources et champs manquants.

17D — Évaluation retrieval hors embeddings réels :

- créer golden queries synthétiques ;
- définir métriques de pertinence pédagogique ;
- tester filtres metadata-only et citations simulées.

17E — Spécification API/UI pédagogique :

- définir endpoints, profils, droits, retours utilisateur ;
- décrire workflow enseignant et élève ;
- établir critères UX de validation.

17F — Protocole d’ingestion pilote avec validation humaine :

- séparer parsing, chunking, embeddings et upsert ;
- prévoir rollback ;
- interdire Qdrant tant que la couche retrieval offline n’est pas validée.

## 10. Garanties non destructives

Garanties explicites :

- aucun fichier supprimé ;
- aucun fichier déplacé ;
- aucune archive créée ;
- aucun document réel copié ;
- aucun PDF copié ;
- aucun `.env` ouvert ;
- aucun secret lu ;
- aucun embedding créé ;
- aucun Qdrant touché ;
- aucun `data/staging` créé ;
- aucun import réel lancé ;
- `rag-local` non modifié ;
- aucun réseau ;
- aucun push.

## 11. Verdict

READY_FOR_RAG_ROADMAP_REVIEW

## 12. Recommandation pour 17B

Préparer un lot 17B de durcissement roadmap et garde-fous opérationnels, sans ingestion réelle : clarifier les cibles Makefile à ne pas lancer, verrouiller le statut pré-pilote metadata-only, puis définir le périmètre d’un corpus pilote synthétique ou metadata-only.
