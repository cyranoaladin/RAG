# cockpit — Nexus Réussite

SaaS Next.js (App Router) destiné aux élèves et candidats libres.

## Périmètre

- Authentification et résolution du profil élève (`StudentProfile`).
- Routage vers un cockpit adapté au niveau et au profil (candidat libre Tle, AEFE 3e→Tle, etc.).
- Agents UI d'accompagnement : Q/R sourcées, révision, exercices, correction.
- Consomme le contrat `nexus-contracts` via l'API retrieval de `rag-engine`.
- Design system aligné sur Nexus Réussite.

## Statut

La migration Vite → Next.js est achevée. Le shell App Router, les scripts et le
build sont exclusivement Next.js ; Vitest reste le moteur de tests. LOT41 lie
le SSO Nexus au contrat d'identité 0.4 et ferme `search`/`chat` sans session
serveur active. Le navigateur n'appelle que le BFF same-origin sous `/api/*` et
ne reçoit ni identité complète, ni jeton interne, ni jeton de service moteur.

## Configuration d'identité serveur

Les valeurs suivantes sont obligatoires ; aucune n'a de valeur secrète par
défaut dans le dépôt :

- `NEXUS_SSO_ISSUER`, `NEXUS_SSO_AUDIENCE` et une source de clé
  `NEXUS_SSO_JWKS_URL` ou `NEXUS_SSO_SHARED_SECRET` ;
- `NEXUS_RELEASE_SCHOOL_YEAR` au format contigu `YYYY-YYYY+1` ;
- `NEXUS_INTERNAL_TOKEN_SECRET`, `NEXUS_INTERNAL_TOKEN_ISSUER` et
  `NEXUS_INTERNAL_TOKEN_AUDIENCE` pour le transport cockpit → moteur ;
- `RAG_ENGINE_INTERNAL_TOKEN` pour l'authentification de service BFF ;
- `NEXTAUTH_SECRET` pour le JWT de session httpOnly ;
- `NEXUS_SESSION_REDIS_URL` pour la révocation, la frontière tenant et
  l'anti-rejeu partagés entre instances.

Une absence de Redis ou une erreur du store ferme l'authentification. Le mode
mémoire exige simultanément `NODE_ENV=test`,
`NEXUS_SESSION_STORE_MODE=memory` et
`NEXUS_SESSION_MEMORY_STORE_FOR_TESTS=true` ; il est interdit en production et
en validation.

## Sécurité des dépendances Next.js

Next.js est verrouillé sur la version stable `16.2.12`. Les overrides exacts
`postcss@8.5.25` et `sharp@0.35.3` appliqués à Next.js sont conservés tant que
la distribution stable ne les intègre pas. `npm ls`, le build Next réel et
`npm audit` contrôlent cet arbre.
