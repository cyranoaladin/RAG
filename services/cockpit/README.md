# cockpit — Nexus Réussite

SaaS Next.js (App Router) destiné aux élèves et candidats libres.

## Périmètre

- Authentification et résolution du profil élève (`StudentProfile`).
- Routage vers un cockpit adapté au niveau et au profil (candidat libre Tle, AEFE 3e→Tle, etc.).
- Agents UI d'accompagnement : Q/R sourcées, révision, exercices, correction.
- Consomme le contrat `nexus-contracts` via l'API retrieval de `rag-engine`.
- Design system aligné sur Nexus Réussite.

## Statut

Migration Vite → Next.js en cours au lot 35 : le shell App Router est
vérifiable, les scripts Vite restent actifs jusqu'à la Task 7b et
l'authentification réelle sera raccordée en Task 8a. Avant ce raccord, les
entrées Next et Vite restent fermées et le navigateur n'appelle que le BFF
same-origin sous `/api/*`.

## Sécurité des dépendances Next.js

Next.js est verrouillé sur la version stable `16.2.12`. Ses dépendances
publiées (`postcss@8.4.31` et `sharp@^0.34.5`) restent couvertes par des avis
de sécurité `high` en juillet 2026. Les overrides exacts `postcss@8.5.25` et
`sharp@0.35.3` sont donc conservés jusqu'à leur intégration dans une version
stable de Next.js ; `npm ls`, le build Next réel et `npm audit` les contrôlent.
