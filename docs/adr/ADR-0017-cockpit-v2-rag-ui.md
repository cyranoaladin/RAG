# ADR-0017 — Cockpit v2 : remplacement du dashboard rag-ui (Streamlit legacy)

- **Statut** : proposé (LOT 28)
- **Date** : 2026-07-26
- **Contexte** : AUDIT_FRONTEND_rag-ui (02/07/2026), PROD_INVENTORY (LOT 20), AUDIT_LOT28 §2.5 (E-04, E-05)

## Décision

1. **Le dashboard `rag-ui.nexusreussite.academy` est reconstruit** sous forme d'application React + TypeScript + Tailwind (SPA) livrée dans `services/cockpit/`. La cible d'architecture reste le portage Next.js App Router (cockpit SaaS, README du service) : la structure en sections typées et le client API isolé (`src/lib/api.ts`) sont conçus pour ce portage. Le build Vite statique sert d'artefact de transition déployable derrière nginx.
2. **Six vues** : Vue d'ensemble (couverture, alertes), Collections (catalogue v3, 59 entrées, invariant M-04), Recherche (API `/search` gouvernée, profil signé, citations obligatoires), Ingestion (3 voies historiques + ingestion continue eduscol LOT 28), Revue humaine (file staging, approve/reject), Gouvernance (verrous, invariants).
3. **Mode dégradé explicite** : sans `VITE_RAG_API_BASE`, le cockpit affiche les données du dépôt en lecture seule avec badge « Démonstration » — jamais de données simulées présentées comme réelles.
4. **Pas d'auto-création de collections** : contrairement au Streamlit legacy (rubriques Maths 1re/Web3/Divers créant des collections vides au clic — A-L03), le cockpit v2 ne propose que les collections `instanciee: true` pour la recherche et n'écrit jamais dans la base vectorielle.
5. **Déploiement** : runbook `docs/runbooks/rag_ui_v2_deploiement.md` — rebuild depuis le dépôt (corrige E-05 : code prod divergent), bascule nginx, décommissionnement progressif du legacy après migration des 9 199 chunks admissibles (Phase C).

## Conséquences

- Les 3 rubriques cassées du legacy disparaissent avec lui (pas de report).
- La génération de réponse reste interdite : le cockpit n'expose que recherche + contexte sourcé.
