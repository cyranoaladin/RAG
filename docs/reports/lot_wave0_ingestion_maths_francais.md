# Lot Wave 0 — pilotes Mathématiques et Français 3e

## Résultat

Le vertical slice staging exécute les vrais octets Éduscol des deux pilotes
depuis Worker A jusqu'à PostgreSQL + pgvector. Les deux ressources atteignent
`NEEDS_REVIEW`, sont attestées avec LOT41A-V2/LOT42-V2 sur l'autorité staging
locale, deviennent `RETRIEVAL_ELIGIBLE`, puis sont publiées sans doublon.

- Mathématiques : SHA-256
  `49ccdca4d97ba4cf25875dfc731474e84d0332985c15396d3abfb9107f5f545a`,
  1 artefact, 1 placement, 1 chunk vectorisé.
- Français : SHA-256
  `c8662b03ca8a7f08bedad5081bafc7da8d2cc8a31b07fa967421fb15304d76bf`,
  1 artefact, 1 placement, 1 chunk vectorisé.

Le second passage rend `artifact_created=false` et `embedded=false`. Les
comptages de doublons artefact, placement, chunk et vecteur restent à zéro.

## Autorités scellées

La currentness est un overlay lié aux deux artefacts et à l'année scolaire
2026-2027. Elle ne modifie ni le classifier physique du catalogue ni les
1 513 documents non classés, les 805 documents à vérifier ou les 49 documents
en transition.

Le resolver unique confronte le catalogue H2-E, le chemin physique, le scope,
la matière, le niveau externe `3e`, le profil Nexus `troisieme`, le programme
`BOEN_special_11_2018-07-26_aj_2020` déclaré dans l'index canonique 3e, la
currentness et le manifest de profils staging. Le manifest de corpus et le
manifest de profils restent deux autorités distinctes.

Worker A et Worker B résolvent les droits depuis le `source_path` du catalogue
scellé. Le classifier conserve son défaut fermé sans placement vérifié.

## PII

La preuve initiale
`5e0d7226cc937ad157c46e0f56853fb126083d1d6b6396abef71859931fe035e`
reste immuable : Français `CLEARED`, Mathématiques `QUARANTINED_PII`.

Le signal Mathématiques a été reproduit puis identifié comme faux positif
objectif de la règle `postal_address` : une branche optionnelle permettait à
un token mathématique de cinq chiffres suivi d'un caractère non numérique de
correspondre sans aucun contexte postal. La politique v5 exige désormais un
contexte local explicite et conserve les vrais positifs en ligne, en minuscules
avec marqueur d'adresse, avec saut LF ou CRLF. Le rescan exact des
deux PDF produit la nouvelle preuve
`e1049c9d4b39b57acce9becadf5029de5b82a20afd8e38c699835bf1e649e125` :
2 scannés, 2 clairs, zéro signal, zéro mismatch et aucune donnée brute dans
les sorties ou journaux.

## Phase B

Le job `publication_resume` lie l'identifiant exact de l'attestation avant
toute transition. Une attestation active A avec un job citant B ne produit ni
`REVIEWED`, ni `RETRIEVAL_ELIGIBLE`, ni ligne produit. Worker B relit les faits
durables des droits et de l'URL canonique, réexécute le resolver commun, puis
entre dans le publisher avec les connexions control et produit à l'état IDLE.

## Portée

La répétition utilise deux PostgreSQL + pgvector jetables, un embedder
déterministe 1024 dimensions et `LocalGitHub`. Elle ne fabrique aucune
approbation de production, ne touche aucune base de production et ne change
pas le statut Draft de la PR #95. Les vrais modèles et `/search/v2` constituent
le prochain lot.

## Vérification

La CI locale a validé contrats, rag-pedago (2 390 tests), rag-engine, le smoke
PostgreSQL/pgvector hybride, le lint, les types, le build cockpit et tous les
contrôles de gouvernance. Son seul target non vert est `services/cockpit` car
`npm audit` n'a pas pu joindre l'endpoint d'audit du registre ; lint, 178 tests
et build Next.js de ce même target sont verts. L'E2E Wave 0 v5 séparé est vert
sur les vrais octets avec le test négatif d'attestation avant publication.
