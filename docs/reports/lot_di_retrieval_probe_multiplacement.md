# Lot DI — oracle de la sonde retrieval pour les artefacts multi-placement

## Incident et périmètre

Branche dédiée issue exactement de `b48cf804c968266bc83f5e6ee721262f27a4143d`.
L'opérateur a constaté `PLACEMENTS=9 263 405`, `CHUNKS=5678`, `HGGSP=0`, puis
un refus de la sonde sur un chunk HLP physiquement ancré en Terminale et servi
en Première par un placement actif, revu et `official_snapshot`. Worker B DI
avait terminé ses 329 publications ; ce lot ne le relance pas. La revue #262
reste ouverte et inchangée à son HEAD
`079461659b60f8a8ce9458145a199599ad822bbc`.

Le défaut est dans l'oracle de `staging_retrieval_probe.py` : il lisait seulement
`rag_chunks WHERE collection = scope.collection`, puis classait comme fuite
un candidat absent de ce jeu physique. Le moteur vérifie au contraire les
placements gouvernés de l'artefact. Le bootstrap du registre documente la
même distinction entre ancre physique et portée de publication. Aucune preuve
ne justifie un changement du moteur.

## Correctif

La sonde lit, en lecture seule, tous les chunks atteignables dans chaque
scope émis. Pour un chunk gouverné, elle joint l'artefact et ses placements,
avec les dimensions de collection, tenant, niveau, voie, matière, statut
d'enseignement, candidat, audience, visibilité, année, programme, statut
actif, currentness servie, revue et droits. Pour un chunk legacy sans
`artifact_id`, elle exige le scope physique complet et les droits du chunk.
Son oracle est indépendant de `PgCandidateStore` ; il conserve les triplets
`(chunk_id, artifact_id, placement_id)` autorisés. Les candidats denses et
lexicaux sont tous confrontés à ces triplets, ce qui refuse aussi un placement
non autorisé d'un chunk pourtant atteignable par un autre placement.
Un chunk placé sans vecteur ou sans texte est inclus dans l'oracle puis refusé
explicitement : la sonde ne peut pas masquer une publication incomplète.

L'image sonde existante exécute `/repo/scripts/go_live/staging_retrieval_probe.py`
depuis le montage en lecture seule de `/srv/nexus-staging/repo`. Aucune nouvelle
image n'est nécessaire. Avant la vérification indépendante, l'orchestrateur
exige désormais un checkout opérateur propre au HEAD de `origin/main`, puis
fait récupérer ce commit au checkout distant, le détache et compare son HEAD,
sa propreté et le blob de la sonde avant toute mesure ou lancement du
conteneur. Ces contrôles sont répétés dans l'appel distant qui lance le
conteneur, afin qu'un checkout changé entre deux appels soit refusé. Un écart
arrête l'étape. L'autorisation, la release, les mappings
et le plan DI lié par empreinte ne changent pas.

## Tests et limites d'exécution

- Test rouge observé avant le correctif : artefact physiquement en HLP
  Terminale, placements Première et Terminale, oracle de Première absent.
- 26 tests sur PostgreSQL local jetable : placement nominal, multi-placement,
  placement manquant, inactif, non revu, currentness non servie, chaque
  dimension du scope, droits, candidat cross-scope, canal lexical, legacy et
  refus du rôle student et chunks publiés incomplets. Le parcours complet de la sonde exerce aussi les
  canaux dense et lexical avec le vrai `PgCandidateStore` ; des candidats
  injectés sous un mauvais placement sont refusés sur les deux canaux.
- Cinq tests hermétiques de checkout : mise à jour au commit attendu,
  commit local périmé, checkout local sale, checkout distant sale et changement
  de HEAD entre le pin et le lancement. Le test
  d'orchestration à blanc vérifie que le pinning précède la sonde.
- `scripts/qualification/tests` : 803 réussis, 4 ignorés. Suites retrieval
  ciblées : vertes. La chaîne réelle V4 reste ignorée sans les artefacts E5
  exigés par son marqueur de test. `ruff`, `mypy` ciblé, `bash -n` et
  `git diff --check` : verts.

Ces tests ne visent aucune DB réelle. Ce lot ne fait aucun SSH, ne touche ni
au staging ni à la production, et ne relance ni Worker B ni la vérification
indépendante DI. Le seul PostgreSQL exécuté est un conteneur local jetable.

## Reprise après fusion

L'opérateur met son worktree d'exécution au nouveau `main` fusionné, propre,
en conservant le `STATE_DIR` DI et ses marqueurs existants. L'appel canonique
`staging_v4_partial_recovery.sh run --until partial_independent_verification`
saute les trois étapes déjà faites, épingle automatiquement le checkout
distant au nouveau commit et exécute seulement la vérification indépendante.
Si le checkout ou l'empreinte diverge, l'étape refuse avant la sonde. Le
contrôle `partial_closure_check` reste distinct et #262 reste ouverte.

La CI de la PR sera relevée après son ouverture. Aucune fusion n'est faite par
ce lot.
