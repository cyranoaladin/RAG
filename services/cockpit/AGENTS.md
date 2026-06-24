# AGENTS.md — cockpit

SaaS Next.js pour les élèves et candidats libres.

## Spécificités

- **Stack** : Next.js App Router, design system Nexus Réussite.
- **Contrat** : consomme `nexus-contracts` via l'API retrieval de `rag-engine`.
- **Agents UI** : un agent par niveau/profil, réponses sourcées uniquement.

## Interdictions

- Ne pas appeler pgvector directement (passer par l'API `rag-engine`).
- Ne pas générer de réponse sans source (refus si aucun chunk pertinent).
- Ne pas stocker de données élèves en clair côté client.
