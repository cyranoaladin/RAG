# Lot Wave 0 — ingestion staging complète de la Troisième

## Portée et résultat

Ce lot part du HEAD
`d3190b2ffcaf9746686731a5dfcad9b5bd883cce`. La PR #95 reste Draft et
aucune approbation de production n'est fabriquée.

Le catalogue H2-E scellé a été filtré avant toute ingestion sur les seuls
placements PDF Éduscol dont le niveau externe vaut exactement `3e` et dont la
matière vaut `mathematiques`, `maths` ou `francais`. Ce filtre donne exactement
deux artefacts uniques, deux objets physiques et deux placements : un artefact
Maths et un artefact Français. Il n'existe donc pas d'autre document exact-grade
à ingérer dans cette release ; les ressources `cycle-4`, multi-niveaux, 4e et 5e
restent hors périmètre.

- Mathématiques : 1 candidat, 1 placement, 1 release-eligible, 0 review-required.
- Français : 1 candidat, 1 placement, 1 release-eligible, 0 review-required.
- Artefacts multi-placement : 0.
- Types externes observés : `reperes-attendus` uniquement.

Les 2/2 candidats sont actuels pour 2026-2027 avec listing Éduscol servi,
résolution de l'URL officielle et identité SHA-256 des octets. Les droits sont
`officiel_public` pour 2/2. La preuve PII full Wave 0, ciblée sur ces deux SHA
uniques sous `pii_gate_policy_h2b_v5`, conclut 2 scannés, 2 cleared, 0
quarantined, couverture 1,0 et 0 mismatch SHA. Les 19 pages textuelles sont
extractibles sans page vide.

## Autorités et manifests scellés

L'ancienne preuve currentness V1 des pilotes reste immuable. Le full set repose
sur les autorités suivantes :

- inventaire candidat :
  `0c203af33d97f787f4fcbbf96ae822d37464d571be96074babf5abb529aaf882` ;
- currentness V2 :
  `75d77994809a81ed9f9452eace75448d3869ef4b8ee1942693f66f430ec27f36` ;
- preuve PII full externe immuable :
  `63d0879358a844b44f41c82d21c0b67349e0f7a2f1cdabe7becff2affc58f9f1` ;
- manifest Maths :
  `18035126ebaa2c89b9e1a8c9d2c5e0e82a1280a8c0e16dd2e65f593177f6875e` ;
- manifest Français :
  `4b6c184ec8e3dc5bcf84c374f9d51d5f7bc9305747ba113b635431d72566b567` ;
- manifest agrégé :
  `0cf9c5d8ceaa2766aa97195743e949ec0a907ed0f609f116275a7d1f8202498d`.

Les manifests lient le catalogue corpus, le catalogue de placements,
l'inventaire, currentness, PII, policy PII, droits, profil, programme et les
deux inventaires modèles. Pour chaque artefact, ils scellent le placement, le
nombre de pages, les IDs et SHA de chunks et la couverture des pages avant toute
écriture PostgreSQL.

Le résolveur runtime ne contient plus d'allowlist Python des deux SHA ni de cas
spécial pilote. Il charge le manifest agrégé, l'inventaire, currentness V2, le
mapping documentaire fermé et les profils ; tout SHA ou placement non éligible
est refusé. Le mapping externe observé est fermé sur
`reperes-attendus -> ressource_officielle`.

## Ingestion gouvernée et réconciliation

L'E2E matériel exécute pour chaque ressource le vrai LOT41A staging,
`verify_scope_authorization`, Worker A jusqu'à `NEEDS_REVIEW`, LOT42 staging,
l'attestation exacte, Worker B puis le publisher pgvector. Il ne contient ni
stub d'autorisation de scope ni appel manuel au publisher.

La base PostgreSQL + pgvector jetable et propre contient :

- Mathématiques : 1 artefact, 1 placement, 19 chunks ;
- Français : 1 artefact, 1 placement, 17 chunks ;
- total : 2 artefacts, 2 placements, 36 chunks.

Le validateur compare les ensembles complets à la release. Résultat : 0
artefact, placement ou chunk manquant ; 0 ligne inattendue ; 0 mauvais SHA de
chunk ; 0 mauvaise page ; 0 mauvais modèle ; 0 vecteur null ou de mauvaise
dimension ; 0 statut de revue/currentness divergent. Les deux placements
portent leurs `authorization_id` et `publication_attestation_id`, et les pins
correspondants existent dans le plan de contrôle.

Les chunks couvrent 100 % des 11 pages Maths et des 8 pages Français. Les
bornes E5 réelles sont 18/350/384 tokens en Maths et 17/353/378 en Français
(min/médiane/max), toujours sous la limite 512. Aucun chunk PDF n'a de page
nulle.

## Modèles et idempotence

La campagne n'utilise que :

- `intfloat/multilingual-e5-large`, dimension 1024, inventaire
  `e2c7384ba36096b3f3bdfff4973f728596104aff0f1d38f1b6463e60765fe22a` ;
- `cross-encoder/ms-marco-MiniLM-L-6-v2`, inventaire
  `bdcedc4d7cfe647b9aaa5a7546822dfee7826ebb3c64472bf89eae7592e08fe1`.

Les artefacts modèles sont vérifiés hors Git, sans symlink, et chargés en
`local_files_only`. Les 36 lignes portent le modèle E5 canonique ; aucune ligne
fake n'est présente. La réécriture gouvernée du même artefact conserve un seul
artefact et un seul set de chunks/vecteurs ; après product commit, la reprise
retourne `embedded=false` et n'appelle pas l'encodeur.

La reprise Phase B accepte un état `RETRIEVAL_ELIGIBLE` seulement à la version
attendue + 2 et après preuve des deux événements exacts
`NEEDS_REVIEW -> REVIEWED -> RETRIEVAL_ELIGIBLE` du même job/run/resource et de
l'attestation citée. Les histoires absentes, dupliquées ou divergentes sont
refusées. Les scénarios crash après eligibility, crash après product commit et
expiration/reprise de lease sont couverts.

## Search acceptance

Le même E2E démarre un vrai processus uvicorn. Le lifespan vérifie BFF,
identités signées, registre de scopes, manifeste release, réconciliation DB,
schéma PostgreSQL et les deux modèles avant de servir.

Le dataset contient 20 requêtes naturelles Maths et 20 Français, réparties sur
plusieurs pages et notions du contenu effectivement disponible. Les dix probes
historiques de chaque matière en constituent un sous-ensemble et restent
vertes. Chaque hit doit être reviewed, lié au SHA et chemin scellés, citer la
page attendue et contenir un concept attendu.

- Maths : 20/20, dont régression pilote 10/10.
- Français : 20/20, dont régression pilote 10/10.
- Discoverability : 100 % des artefacts release-eligible dans chaque matière.
- Résultats nuls, mauvais artefacts et citations/pages manquantes : 0.
- Fuites inter-collections et fuites de scope : 0.

La demande de répartir les probes sur plusieurs artefacts par matière n'est pas
réalisable sans élargir illégitimement le scope : l'inventaire scellé exact-grade
contient exhaustivement 1/1 artefact par matière. La couverture est donc
répartie sur plusieurs pages et concepts, et chaque unique artefact est sondé.

Le client officiel `scripts/rag_query.py` est rejoué contre cette socket pour
les deux scopes, sans exposer de token ni accepter une collection physique du
client.

## Readiness et activation

`/collections/readiness` ne dépend plus d'un booléen constant. Le manifest
agrégé et son SHA sont exigés au startup dès qu'une collection V2 Wave 0 est
instanciée, puis le validateur compare le manifest à la DB avant le chargement
des modèles et avant search/chat/picker.

Après réconciliation exacte, le catalogue canonique active uniquement :

- `rag_nexus_maths_troisieme_tc` ;
- `rag_nexus_francais_troisieme_tc`.

Le delta canonique est exactement 2 et le snapshot cockpit reflète uniquement
ces deux booléens. L'overlay staging devient un no-op déterministe. L'ADR-0039
documente ce passage sans lever les verrous `real_documents_allowed` ou
`curated_ingestion_allowed`.

## Runtime et conformité externe

Worker A et Worker B chargent les autorités scellées et leurs SHA avant leur
boucle. Worker A ne peut pas démarrer sans résolveur. Worker B consomme
exclusivement `publication_resume`, le provider E5 attesté et des modèles montés
en lecture seule ; aucun public writer n'est introduit.

Un E2E séparé lance réellement les deux modules CLI en sous-processus avec
`--once` sur deux PostgreSQL/pgvector jetables. Worker A atteint durablement
`NEEDS_REVIEW` sur le SHA Maths exact ; l'opérateur LOT42 staging atteste ensuite
la revue et Worker B atteint `RETRIEVAL_ELIGIBLE`, 1 artefact, 1 placement et
plusieurs chunks E5 1024 non nuls. Aucune fonction de CLI n'est monkeypatchée.
L'acceptance modèle est exécutée sur CPU parce que le GPU partagé 4 Go est
saturé.

Les alertes GitGuardian `36021438` et `36021439` restent des faux positifs
historiques à classer par un humain dans le dashboard. Aucun historique n'est
réécrit et aucun force-push n'est effectué. Le check de revue humaine reste
attendu rouge tant que la PR #95 est Draft.

## Vérification finale

La CI locale canonique a été exécutée depuis la racine avec Python 3.12
système et Node 22.22.0. Elle termine avec 16 cibles passées et 0 échec :
contrats, `rag-pedago` (2 396 tests), `rag-engine` (lint, mypy, suite
non-intégration et `LOT40_HYBRID_INTEGRATION=PASS`), cockpit (178 tests,
build et audits npm), hygiène, topologie CI, revue de confiance, gouvernance,
taxonomie et failsafes.

Les acceptances matérielles complémentaires passent sur PostgreSQL + pgvector
jetable avec les vrais modèles : ingestion gouvernée 19/17 chunks, seconde
exécution sans nouvel embedding, reconciliation exacte, vrai uvicorn,
20/20 requêtes par matière et client officiel. Les deux CLI `--once` passent en
sous-processus. Les images Worker A/Worker B et API v2 sont construites depuis
leurs allowlists ; leurs imports runtime réels passent, notamment
`api_v2 + release_readiness`.

La CI GitHub native est vérifiée après le push du HEAD de livraison. Le check de
revue humaine reste attendu rouge parce que la PR #95 demeure volontairement
Draft ; les deux findings GitGuardian historiques restent séparés et exigent
un dismissal humain.
