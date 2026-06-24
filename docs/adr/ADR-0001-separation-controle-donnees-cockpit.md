# ADR-0001 — Séparation plan de contrôle / plan de données / cockpit

- **Statut** : Accepté
- **Date** : 2026-06-24
- **Décideur** : Alaeddine Ben Rhouma (Shark)
- **Portée** : Plateforme RAG pédagogique multi-niveaux (candidats libres 1re/Tle + élèves scolarisés réseau AEFE 3e→Tle)
- **Remplace** : —
- **Remplacé par** : —
- **ADR liés** : ADR-0002 (contrat de retrieval, à venir), ADR-0003 (stratégie d'isolation par niveau, à venir), ADR-0004 (ingestion agentique, à venir)

---

## 1. Contexte

Le dépôt `cyranoaladin/RAG` contient aujourd'hui trois ensembles disjoints, issus de trajectoires différentes et non connectés entre eux :

1. **Référentiels-source** (`REFERENTIEL_CANDIDAT_LIBRE.md`, `Tronc_commun/`, `Specialites/`) : contenu pédagogique factuel et sourcé, à l'état de matière première (markdown libre, non chunké, non taggé).

2. **`rag-pedago`** : couche de gouvernance d'ingestion *metadata-only*, très aboutie (17 lots, schémas Pydantic, référentiel officiel niveaux/examens/statuts/contextes, pipeline manifest → quality → readiness → coverage → gate → review → controlled import → ledger SQLite). Volontairement débranchée : son `ARCHITECTURE.md` liste comme inexistants le parsing, le chunking, les embeddings, le retrieval, Qdrant, PostgreSQL, les réponses LLM et l'API cockpit ; `configs/pedago_interface_contract.yml` met l'ensemble des capacités runtime à `false`. Les dossiers `scrapers/`, `retrieval/`, `services/{api,mcp,workers}` sont des stubs vides.

3. **`rag-local`** : moteur RAG hybride fonctionnel construit initialement pour MFAI/Nexus. Schéma pgvector (`rag_documents`, `rag_chunks` 768-dim `nomic-embed-text`, index HNSW + GIN tsvector français + GIN JSONB), colonne `tenant` multi-tenant, recherche hybride dense + BM25 + RRF + reranker CrossEncoder, cache embeddings Redis, ingestor FastAPI, backend JWT, UI Streamlit, stack Docker complète, framework d'évaluation (gold sets, precision/recall/MRR/nDCG). Sans aucune notion de gouvernance pédagogique ni de profil élève. Dette documentaire : le README mentionne encore ChromaDB alors que la cible réelle (vue dans `init.sql` et les scripts `migrate_*_to_pgvector.py`) est pgvector.

### Énoncé du problème

On dispose de **deux demi-systèmes complémentaires** — une intelligence de gouvernance sans moteur, et un moteur sans gouvernance — plus un corpus-graine non structuré. Aucun des objectifs cibles n'est couvert de bout en bout :

- ingérer des données **par niveau** dans un RAG ;
- exposer des **cockpits** par niveau et par profil élève, dotés d'agents et d'outils ;
- mettre en place une **ingestion agentique** (agents qui recherchent, sélectionnent et ingèrent des ressources web).

La question n'est pas de savoir *quoi* construire (les trois objectifs sont clairs) mais *comment organiser les responsabilités* entre les briques existantes pour ne pas casser ce qui marche ni reconstruire ce qui existe.

## 2. Drivers de décision

- **Préserver le verrou de gouvernance déjà construit** dans `rag-pedago` (citations obligatoires, refus en l'absence de source, droits, traçabilité ledger). C'est un actif différenciant et un prérequis RGPD/souveraineté.
- **Réutiliser le moteur fonctionnel** `rag-local` plutôt que réimplémenter pgvector + hybride + reranker + eval.
- **Isoler le risque RGPD/souveraineté** : la donnée élève et la donnée pédagogique ingérée n'ont pas le même régime.
- **Permettre l'évolution indépendante** du moteur de retrieval et de la pédagogie.
- **Minimiser le couplage** entre le SaaS (cockpit) et la base vectorielle.
- **S'appuyer sur les contrats existants** : `RetrievalRequest{student_profile, need, options} → RetrievalResponse{results + citations}` est déjà défini dans `rag-pedago/schema/retrieval.py` et constitue une couture naturelle.

## 3. Options considérées

### Option A — Fusion sous `rag-pedago`
Greffer le moteur `rag-local` (pgvector + hybride) à l'intérieur de `rag-pedago`, en remplaçant le Qdrant prévu. Un seul système, une seule base de code.

- **+** Un seul déploiement, une seule frontière.
- **−** Mélange dans un même service le plan de contrôle (décisionnel, déterministe, testé hors-ligne) et le plan de données (runtime, réseau, lourd) que `rag-pedago` a précisément cloisonnés par design.
- **−** Casse l'invariant « metadata-only » de la phase actuelle ; les verrous `*_allowed: false` perdent leur sens.
- **−** Couple le cycle de vie du moteur à celui de la gouvernance.

### Option B — Séparation plan de contrôle / plan de données / cockpit (**retenue**)
Trois services aux frontières nettes :
- `rag-pedago` = **plan de contrôle** (taxonomie, profils, admission de sources, gouvernance, ledger, orchestration de l'ingestion agentique).
- `rag-engine` (renommage de `rag-local`) = **plan de données** (indexation pgvector + retrieval hybride), exposé uniquement via le contrat de retrieval.
- `cockpit` = **SaaS** (Next.js, lignée Nexus Réussite) qui ne parle qu'au contrat de retrieval et au profil élève, jamais à la base vectorielle.

- **+** Respecte le cloisonnement déjà conçu dans `rag-pedago`.
- **+** Réutilise `rag-local` quasi tel quel (le renommage et le filtrage par tenant suffisent).
- **+** Isole les régimes RGPD et les cycles de vie.
- **+** La couture est déjà spécifiée (`schema/retrieval.py`).
- **−** Trois services à déployer et à observer ; nécessite une discipline de versionnement du contrat.

### Option C — Reconstruction
Repartir d'une base neuve, abandonner les deux existants.

- **−** Jette `rag-local` (moteur fonctionnel + eval) et `rag-pedago` (17 lots de gouvernance). Coût et risque injustifiés.

## 4. Décision

**Option B retenue.** La plateforme est structurée en trois services aux responsabilités strictement séparées, articulés par un contrat unique :

```
┌─────────────────────────┐     RetrievalRequest      ┌──────────────────────────┐
│  cockpit (SaaS Next.js) │ ────────────────────────► │  rag-engine (ex rag-local)│
│  agents + outils + UI   │ ◄──────────────────────── │  pgvector + hybride       │
│  par niveau / profil    │     RetrievalResponse      │  retrieval seul           │
└───────────┬─────────────┘     (+ citations)          └────────────┬─────────────┘
            │                                                        │
            │ profil élève, intent                                   │ index alimenté par
            ▼                                                        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│  rag-pedago (plan de contrôle)                                                     │
│  taxonomie · profils · référentiel officiel · admission de sources · gouvernance   │
│  ledger · ORCHESTRATION DE L'INGESTION AGENTIQUE (scrapers/ + services/workers/)   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 Frontières de responsabilité

| Préoccupation | Service propriétaire |
|---|---|
| Taxonomie, niveaux, examens, statuts, contextes (dont AEFE) | `rag-pedago` |
| Profil élève (`StudentProfile`), résolution des compatibilités | `rag-pedago` |
| Admission de sources, qualité, gate, review humaine, ledger | `rag-pedago` |
| Recherche, sélection et ingestion agentiques de ressources web | `rag-pedago` (orchestration) → `rag-engine` (indexation) |
| Parsing, chunking, embeddings, stockage vectoriel | `rag-engine` |
| Retrieval hybride (dense + BM25 + RRF + rerank), eval | `rag-engine` |
| Authentification SaaS, sessions, RBAC, cockpits par niveau | `cockpit` |
| Agents UI, accompagnement, correction, interaction élève | `cockpit` |

### 4.2 Couture unique

Le seul point de contact entre `cockpit` et `rag-engine` est le contrat déjà défini dans `rag-pedago/schema/retrieval.py` :
- requête : `RetrievalRequest{ student_profile, need: RetrievalNeed, retrieval: RetrievalOptions }` ;
- réponse : `RetrievalResponse{ results: [RetrievalResult], warnings }` avec `Citation` obligatoire.

Ce contrat est promu en **package partagé versionné** (SemVer), importé à la fois par `cockpit`, `rag-engine` et `rag-pedago`. Toute évolution incompatible fait l'objet d'un ADR dédié.

### 4.3 Isolation par niveau

Pas de base de données par niveau. On combine :
- un **tenant logique** par couple (population × niveau), p. ex. `aefe_terminale`, `libre_premiere` ;
- le **filtrage GIN sur metadata** déjà produit par `StudentProfile.to_payload_filters()` (`niveau`, `voie`, `matiere`, `statut_enseignement`, `candidat`).

Décision détaillée et nomenclature des tenants renvoyées à l'ADR-0003.

### 4.4 Traitement de l'existant

- `rag-local` est **renommé `rag-engine`** ; le README est corrigé (pgvector, non ChromaDB).
- Le **Qdrant** anticipé par `rag-pedago` est abandonné au profit de pgvector déjà en place dans `rag-engine`.
- Les capacités `rag-engine` (parsing, chunking, embeddings, retrieval) **restent désactivées côté `rag-pedago`** tant que la phase gouvernance l'exige ; leur activation passe par le protocole de transition existant (`transition_authorization.yml`), pas par effet de bord.
- Le backend JWT et l'UI Streamlit de `rag-local` sont **dépréciés** : l'authentification et l'UI relèvent désormais du `cockpit`. `rag-engine` n'expose qu'une API de retrieval interne (réseau privé, clé d'API par service).

## 5. Conséquences

### Positives
- Le verrou de gouvernance et la traçabilité ledger sont préservés intacts.
- Le moteur fonctionnel et son framework d'eval sont réutilisés sans réécriture.
- Le SaaS n'a jamais accès direct à la base vectorielle ni aux données brutes ; surface RGPD réduite.
- Moteur et pédagogie évoluent indépendamment derrière un contrat stable.
- Les stubs vides de `rag-pedago` (`scrapers/`, `services/workers/`) reçoivent enfin une fonction claire : l'orchestration agentique.

### Négatives
- Trois services à déployer, observer et versionner.
- Discipline requise sur le versionnement du contrat de retrieval (package partagé).
- Latence d'un appel réseau supplémentaire (`cockpit` → `rag-engine`) ; à mesurer et borner.

### Risques et mitigations
- **Dérive du contrat** → package partagé SemVer + tests de contrat (golden queries déjà présentes dans `rag-pedago/tests/golden_queries/`).
- **Double source de vérité taxonomie** (référentiels racine vs `rag-pedago/data/reference/`) → la racine devient corpus-source ingérable ; `rag-pedago` reste l'unique autorité de la taxonomie de métadonnées.
- **Contournement du gate par l'ingestion agentique** → tout chemin agentique passe obligatoirement par `quality → gate → review` avant écriture dans `rag-engine` ; aucun agent n'écrit directement dans pgvector.

## 6. Suites

- **ADR-0002** : promotion du contrat de retrieval en package partagé versionné + tests de contrat.
- **ADR-0003** : nomenclature des tenants et stratégie d'isolation par niveau.
- **ADR-0004** : architecture de l'ingestion agentique (recherche web → admission → gate → indexation) et placement des agents dans `rag-pedago/scrapers` + `services/workers`.
- Correction de la dette documentaire `rag-local` (ChromaDB → pgvector) lors du renommage en `rag-engine`.
