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

- `NEXUS_SSO_ISSUER`, une valeur unique exacte `NEXUS_SSO_AUDIENCE` (liste
  séparée par virgules interdite) et une source de clé
  `NEXUS_SSO_JWKS_URL` ou `NEXUS_SSO_SHARED_SECRET` ;
- `NEXUS_RELEASE_SCHOOL_YEAR` au format contigu `YYYY-YYYY+1` ;
- `NEXUS_INTERNAL_TOKEN_SECRET`, `NEXUS_INTERNAL_TOKEN_ISSUER` et
  `NEXUS_INTERNAL_TOKEN_AUDIENCE` pour le transport cockpit → moteur ;
- `RAG_ENGINE_INTERNAL_TOKEN` pour l'authentification de service BFF ;
- `NEXTAUTH_SECRET` pour le JWT de session httpOnly ;
- `NEXUS_COCKPIT_PUBLIC_ORIGIN`, l'origine publique HTTPS canonique du Cockpit
  (sans credentials, chemin, query ni fragment) ; elle est comparée exactement
  au header `Origin` des mutations de review, y compris lorsque Next.js reçoit
  une URL interne derrière un reverse proxy ;
- `NEXUS_SESSION_REDIS_URL` pour la révocation, la frontière tenant et
  l'anti-rejeu partagés entre instances.

Une absence de Redis ou une erreur du store ferme l'authentification. Le mode
mémoire exige simultanément `NODE_ENV=test`,
`NEXUS_SESSION_STORE_MODE=memory` et
`NEXUS_SESSION_MEMORY_STORE_FOR_TESTS=true` ; il est interdit en production et
en validation. La déconnexion NextAuth inscrit le `jti` de la session dans ce
store ; les endpoints BFF et le vérificateur SSO refusent ensuite ce jeton. La
durée de révocation ne peut pas être configurée sous la durée maximale du
cookie serveur, fixée à 3 600 secondes.

`RAG_ENGINE_INTERNAL_TOKEN` doit être exactement la valeur configurée comme
`RAG_BFF_SERVICE_TOKEN` dans `rag-engine`, et rester distinct de tous les
jetons de rôle humains.

Les routes BFF search, chat et collections ne retiennent que les collections
dont la matière figure dans le profil signé. Elles transmettent l'enveloppe
d'identité à la readiness du moteur. Celle-ci peut diagnostiquer une collection
déclarée mais dormante sans l'autoriser au retrieval et reste fermée tant
qu'une preuve exhaustive de release n'a pas été validée ; un simple nombre de
chunks ne peut pas l'ouvrir. Si le moteur est indisponible, le catalogue BFF est
vide : aucun catalogue statique potentiellement hors profil n'est exposé.

## Sécurité des dépendances Next.js

Next.js est verrouillé sur la version stable `16.2.12`. Les overrides exacts
`postcss@8.5.25` et `sharp@0.35.3` appliqués à Next.js sont conservés tant que
la distribution stable ne les intègre pas. `npm ls`, le build Next réel et
`npm audit` contrôlent cet arbre.
