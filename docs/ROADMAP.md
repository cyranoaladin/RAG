# ROADMAP — Plateforme RAG pédagogique (Nexus)

> Pilotage : chef de projet = Claude (architecte/PM). Exécution code = Claude Code, via un prompt par lot.
> Décision fondatrice : ADR-0001 (séparation plan de contrôle / plan de données / cockpit).

## Cadrage

- **Deux populations** : candidats libres (1re/Tle) ; élèves scolarisés réseau AEFE (3e→Tle).
- **Trois services** : `rag-pedago` (contrôle/gouvernance/ingestion agentique), `rag-engine` (ex `rag-local` : pgvector + retrieval hybride), `cockpit` (SaaS Next.js, agents UI par niveau/profil).
- **Couture unique** : contrat `RetrievalRequest → RetrievalResponse` (package partagé `nexus-contracts`).
- **Vertical pilote décidé** : Candidat libre — Terminale générale, spécialités Maths + NSI (taxonomie déjà présente, corpus le plus mûr, expertise interne pour juger la qualité). Les autres niveaux/matières se déploient ensuite par réplication.

## Décisions de cadrage prises (sans validation requise)

1. **Monorepo conservé** (les deux briques sont déjà sous le même dépôt). Structure cible : `services/{rag-pedago,rag-engine,cockpit}`, `packages/contracts`, `corpus/`.
2. **Contrat partagé** = package Python `nexus-contracts` v0.1.0, extrait de `rag-pedago/schema/{retrieval,student_profile,document}.py`. Source de vérité unique, SemVer.
3. **Nomenclature des tenants** : `{population}_{niveau}` → `libre_premiere`, `libre_terminale`, `aefe_troisieme`, `aefe_seconde`, `aefe_premiere`, `aefe_terminale`. Isolation par tenant + filtrage GIN metadata (pas de base par niveau).
4. **Stack cockpit** : Next.js (App Router) aligné sur le design system Nexus Réussite existant.
5. **Stockage vectoriel** : pgvector (Qdrant anticipé par `rag-pedago` abandonné). Auth/UI Streamlit de `rag-local` dépréciées → portées par le cockpit.
6. **Ingestion agentique** : toujours via `quality → gate → review` avant écriture ; aucun agent n'écrit directement dans pgvector.

## Phases et lots

| Phase | Lot | Objet | Service | Definition of Done |
|---|---|---|---|---|
| **0 — Fondations** | 0 | Monorepo + package contrat + CI racine | tous | Structure cible en place, tests existants verts, `nexus-contracts` importé par rag-pedago, README rag-engine corrigé, verrous gouvernance inchangés |
| **1 — Plan de données** | 1.1 | Activation contrôlée parsing/chunking pédagogique | rag-engine | Pipeline parse→chunk sur le corpus pilote, chunks taggés (niveau, matière, notion, type, droits) |
| | 1.2 | Embeddings + indexation pgvector du corpus pilote | rag-engine | Tenant `libre_terminale` peuplé (maths+NSI), HNSW + GIN actifs |
| | 1.3 | Retrieval hybride filtré par profil | rag-engine | `to_payload_filters()` câblé, top-k pertinent, citations renvoyées |
| **2 — Couture** | 2.1 | API retrieval interne (contrat live) | rag-engine | Endpoint `/retrieve` consommant `RetrievalRequest`, réseau privé + clé API |
| | 2.2 | Eval gold set par niveau | rag-engine + rag-pedago | Gold set `libre_terminale`, seuils precision@5/recall@5/MRR définis et mesurés |
| **3 — Cockpit MVP** | 3.1 | Auth + profil élève + sélection cockpit | cockpit | Connexion, `StudentProfile` résolu, routage vers cockpit Tle libre |
| | 3.2 | Agent UI d'accompagnement (Q/R sourcées) | cockpit | Réponses RAG sourcées + refus sans source, conformes au contrat d'interface |
| | 3.3 | Outils cockpit (révision, exercices, correction) | cockpit | ≥3 outils branchés sur le retrieval, par intent (`RetrievalNeed.intent`) |
| **4 — Ingestion agentique** | 4.1 | Agent de découverte de sources web | rag-pedago/scrapers | Recherche ciblée par notion/niveau, sortie = candidats de sources |
| | 4.2 | Admission automatisée → gate | rag-pedago | Candidats passés par `source_admission_policy` + `quality` + `gate` |
| | 4.3 | Worker d'ingestion gouvernée | rag-pedago/services/workers → rag-engine | Sources approuvées indexées dans le bon tenant, tracées au ledger |
| **5 — Mise à l'échelle** | 5.x | Déploiement des autres niveaux/matières et du track AEFE | tous | Tenants `libre_premiere`, `aefe_*` peuplés ; cockpits correspondants ouverts |
| **6 — Industrialisation** | 6.x | Observabilité, RGPD, prod, scaling | tous | Prometheus/alertes, conformité RGPD/souveraineté, déploiement prod stabilisé |

## Suivi des ADR

- ADR-0001 — Séparation (accepté).
- ADR-0002 — Contrat partagé `nexus-contracts` (à formaliser au Lot 0).
- ADR-0003 — Tenants / isolation par niveau (à formaliser au Lot 1.2).
- ADR-0004 — Ingestion agentique (à formaliser au Lot 4.1).

## Cadence opérationnelle

Un lot = un prompt Claude Code = une PR = un rapport. Je ne lance pas le lot N+1 avant d'avoir le rapport vert du lot N. Les décisions structurantes de chaque phase sont gelées en ADR avant le code de la phase.
