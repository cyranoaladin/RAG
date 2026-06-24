# AGENTS.md — Nexus RAG Platform (monorepo)

Ce dépôt est le monorepo de la plateforme RAG pédagogique Nexus Réussite.

## Structure

```
services/rag-pedago/   — Gouvernance, ingestion agentique, taxonomie
services/rag-engine/   — Moteur RAG (pgvector, retrieval hybride)
services/cockpit/      — SaaS Next.js (agents UI par niveau/profil)
packages/contracts/    — nexus-contracts : contrat partagé (source de vérité)
corpus/                — Référentiels-source (markdown)
docs/adr/              — Architecture Decision Records
```

## Règles cross-service

1. **Contrat unique** : tout échange retrieval passe par `nexus-contracts` (`RetrievalRequest → RetrievalResponse`). Aucun service ne définit ses propres types de retrieval.
2. **Isolation des services** : un service ne doit pas importer directement le code d'un autre service. La communication passe par le contrat ou par API.
3. **Gouvernance** : les verrous dans `services/rag-pedago/configs/pedago_interface_contract.yml` sont protégés. Aucun `allowed: false` ne peut passer à `true` sans ADR référencé et validé.
4. **Historique git** : tout déplacement de fichier utilise `git mv`. Jamais supprimer+recréer.
5. **Tests** : aucun lot ne peut être livré si les suites de tests des services impactés ne sont pas vertes.

## Garde-fous

- Ne jamais activer de capacité runtime dans `rag-pedago` sans ADR.
- Ne jamais écrire directement dans pgvector depuis `rag-pedago` (ingestion agentique passe par `rag-engine`).
- Ne jamais exposer de secret dans le code versionné.
- Ne jamais mélanger logique métier et restructuration dans le même lot.

## Voir aussi

- Chaque service a son propre `AGENTS.md` avec ses règles locales.
- `docs/ROADMAP.md` pour le plan de phases et lots.
- `docs/adr/` pour les décisions d'architecture.
