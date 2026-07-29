# cockpit — Nexus Réussite

SaaS Next.js (App Router) destiné aux élèves et candidats libres.

## Périmètre

- Authentification et résolution du profil élève (`StudentProfile`).
- Routage vers un cockpit adapté au niveau et au profil (candidat libre Tle, AEFE 3e→Tle, etc.).
- Agents UI d'accompagnement : Q/R sourcées, révision, exercices, correction.
- Consomme le contrat `nexus-contracts` via l'API retrieval de `rag-engine`.
- Design system aligné sur Nexus Réussite.

## Statut

La migration Vite → Next.js est achevée par la Task 7b du lot 35. Le shell
App Router, les scripts et le build sont exclusivement Next.js ; Vitest reste
le moteur de tests. L'authentification réelle sera raccordée en Task 8a.
Avant ce raccord, l'unique entrée Next reste fermée et le navigateur n'appelle
que le BFF same-origin sous `/api/*`.

## Sécurité des dépendances Next.js

Next.js est verrouillé sur la version stable `16.2.12`. Les overrides exacts
`postcss@8.5.25` et `sharp@0.35.3` appliqués à Next.js sont conservés tant que
la distribution stable ne les intègre pas. `npm ls`, le build Next réel et
`npm audit` contrôlent cet arbre.
