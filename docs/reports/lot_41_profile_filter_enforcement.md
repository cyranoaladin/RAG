# LOT41 — Identité et filtres serveur exhaustifs

Date de vérification : 2026-08-02

## Verdict et identité de la preuve

- Base `main` vérifiée :
  `a02a09fe0342cf107f1dec49605f01dd4de324ae`.
- Candidat de code final relu et soumis à la CI intégrale :
  `48d1a000e720788140fa831b1ae5be4db936cccc`.
- Le présent rapport vient nécessairement après ce SHA. Il ne contient aucun
  changement fonctionnel et évite ainsi une référence circulaire.
- Branche vérifiée : `lot-41-identity-filters`.
- Diff fonctionnel : 20 commits, 104 fichiers, 9 126 ajouts et 1 031
  suppressions.

LOT41: PASS_CANDIDATE

REVUE_INDÉPENDANTE: APPROVE_HIGH

GO_LIVE: NO_GO

`PASS_CANDIDATE` signifie que LOT41 satisfait ses critères techniques locaux,
ses preuves PostgreSQL réelles et ses deux contre-revues indépendantes. Il ne
signifie ni fusion déjà effectuée, ni autorisation de lire un document réel,
ni aptitude globale au go-live.

Le projet reste `NO_GO` : LOT41A exige une décision humaine GitHub avant toute
validation sur documents réels, puis LOT42 à LOT47 doivent encore qualifier le
corpus, évaluer la substance, calibrer, exercer le rollback et autoriser la
production.

## Périmètre livré

### Contrat partagé 0.4.0

`packages/contracts` est l'unique source des modèles et schémas suivants :

- `InternalIdentity` 0.4 avec `school_year`, sujet pseudonymisé, claims bornés,
  matières uniques et modèles fermés ;
- `InternalIdentityEnvelope`, qui lie `sub`, `jti`, `iat`, `exp`, identité,
  scope, digest et collections autorisées ;
- `PilotRetrievalScopeArtifact`, projection dormante et déterministe du scope
  LOT38 ;
- schémas JSON `/v0.4/`, exports Python et client TypeScript généré du Cockpit.

Le passage `0.3.0 → 0.4.0` est cassant et coordonné. ADR-0022 le traite comme
un changement major-equivalent du cycle pré-1.0. Les identités 0.3 sans année
scolaire sont refusées.

### Transport et session Cockpit

Le Cockpit :

- vérifie issuer, audience SSO unique, signature, expiration et anti-rejeu ;
- émet une enveloppe interne HS256 à durée bornée, avec issuer et audience
  internes exacts ;
- garde séparés le credential machine BFF et le jeton d'identité ;
- n'expose au navigateur ni identité complète, ni jeton interne, ni credential
  moteur ;
- exige une session serveur sur `search`, `chat` et `collections` ;
- utilise Redis partagé en fail-closed pour l'anti-rejeu, la frontière tenant
  et la révocation ;
- produit la révocation au runtime lors de `signOut`, avec une clé liée à
  `tenant`, `sub` et `jti` et une durée au moins égale aux 3 600 secondes du
  cookie serveur ;
- déduplique les collections de chat avant de construire simultanément le
  profil pédagogique et le payload moteur ;
- retourne un catalogue vide, jamais un seed hors profil, si le moteur est
  indisponible.

### Scope effectif et retrieval

Le moteur vérifie simultanément le credential BFF et l'identité signée. Le
scope effectif est l'intersection ordonnée entre les matières signées et les
sujets de l'artefact. Le client peut seulement restreindre ce scope.

Le retrieval public, de chaque requête SQL dense/lexicale à la vérification
post-DB, puis dans les endpoints et le CLI, impose les 13 dimensions suivantes :

- tenant ;
- niveau ;
- voie canonique (`gen → generale`) ;
- matière ;
- statut d'enseignement ;
- candidat (`individuel`, `libre` ou `cned_libre`, plus la compatibilité
  explicitement bornée `both`) ;
- audience ;
- droits ;
- visibilité ;
- statut humain `reviewed` ;
- année scolaire ;
- version de programme ;
- collection autorisée.

La fusion ne reçoit que les candidats déjà filtrés. Toute ligne retournée par
PostgreSQL est revérifiée et une divergence ferme le canal. Le cache
process-local n'est jamais lu par la recherche publique ; une révocation
humaine est donc observable avant toute nouvelle réponse.

La review reprend l'identité signée et les dimensions pédagogiques, tenant et
collection, mais utilise les états adaptés à son objet : `needs_review` pour la
queue, `needs_review → reviewed|quarantined` pour une première décision et
`reviewed → quarantined` pour une révocation.

### Catalogue, readiness et review

- `/collections/v2` ne renvoie que l'intersection profil/artefact qui est
  effectivement instanciée et retrievable, dans l'ordre de l'artefact.
- `/collections/readiness` peut diagnostiquer une collection déclarée mais
  dormante sans franchir le gate de recherche `instanciee: true`.
- `release_evidence_verified` est fixé à `false` dans LOT41 et
  `launch_ready=false` reste obligatoire. Un nombre de chunks `reviewed` est un
  diagnostic, jamais une preuve de substance ou de couverture des notions.
- La queue et les décisions de review sont bornées par tenant et collection ;
  les sélecteurs clients ne peuvent que réduire.
- Les transitions autorisées restent `needs_review → reviewed|quarantined` et
  la révocation `reviewed → quarantined`, sans réactivation implicite.
- Les DSN retrieval/readiness et review sont distincts et n'ont aucun fallback
  vers le rôle owner.

### Migration et surface historique

La migration `003_profile_filtering` ajoute les dimensions de filtre sans
backfill, valeur par défaut ou promotion silencieuse. Son rollback refuse les
données enrichies et le runner prouve montée, descente, refus et réapplication.

Les routes Nginx historiques de retrieval contournables sont fermées par
`410`. Les tests de topologie empêchent leur republication.

## Artefacts et empreintes

- Scope YAML canonique LOT38 :
  `b55ef1383fceabbbe0bf30c47a45a1fce607697f56bac340162156fabcf0fe26`.
- Octets du JSON d'artefact versionné :
  `c48031f8ff6a9fa7541c3b34c9322b9e1f34749a1e462d73f536350de8e699ba`.
- Digest JSON canonique porté par l'enveloppe :
  `a1ed0fb1c7ec6344c17b155004d5bb61172b77f4b5bff6f5a250cc8b968fdd24`.
- Migration `003_profile_filtering.sql` :
  `069cd391d77ee47a6daae037221dbef7403e7710d35abecaecb0484f05d0428a`.
- Rollback `003_profile_filtering.down.sql` :
  `8ef99a380bc471c586ba65480201d07e25b977da21c9a97b05e31719a5accab0`.
- Image pgvector immuable :
  `pgvector/pgvector:pg16@sha256:00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc`.

Le digest canonique de l'artefact est volontairement distinct du SHA des
octets du fichier JSON et du SHA du YAML source.

## Preuves fraîches sur le candidat final

### Contrats

Commande ciblée exécutée après la CI intégrale :

```bash
PYTHONPATH=src python -m pytest -q
```

Verdict : PASS, 86 tests. Les tests couvrent notamment les invariants
d'identité, la concordance enveloppe/artefact, la projection du YAML, les
digests, les modèles fermés et les exports de schéma.

### Moteur hors intégration

La CI canonique a exécuté Ruff, mypy et pytest depuis un venv Python 3.11 frais :

- Ruff : PASS ;
- mypy : PASS, 45 fichiers source ;
- pytest hors intégration : PASS, 1 173 tests exécutés ; les cas PostgreSQL
  sont isolés par marqueur et par disponibilité des trois DSN éphémères.

Deux avertissements d'environnement non bloquants subsistent : dépréciation de
`crypt` dans passlib et déclaration d'incompatibilité Requests avec les
versions installées de `urllib3`/`chardet`/`charset_normalizer`.

### PostgreSQL/pgvector réel

Le target obligatoire `make test-integration-hybrid` a exécuté 16 tests sur
une base PostgreSQL 16/pgvector réelle et éphémère. Verdict :
`LOT40_HYBRID_INTEGRATION=PASS`.

Les preuves comprennent :

- adoption d'un bootstrap 002 sans registre ;
- cycle `001 → 002 → 003 → 002 → 001 → 003` ;
- rollbacks atomiques après échecs injectés d'adoption, montée et descente ;
- refus de rollback 003 après enrichissement ;
- head final 003 et objets de migration réels ;
- rôle applicatif non-superuser en lecture seule et rôle review limité aux
  colonnes autorisées ;
- plans GIN et HNSW, ordre strict, bornes, underfill et égalités ;
- pipeline hybride et smoke HTTP réels ;
- matrice exhaustive 3 candidats × 2 matières : 6/6 PASS ;
- enveloppe signée → scope → HTTP → PostgreSQL :
  `SIGNED_IDENTITY_HTTP_REAL_DB=PASS` ;
- identité Maths-only → NSI instanciée refusée en 403 avant tout appel au
  pipeline, puis identité NSI-only → NSI acceptée avec un seul appel et une
  readiness limitée à NSI : `MONO_SUBJECT_HTTP_SCOPE=PASS` ;
- chat maintenu sans génération et review IDOR/révocation : PASS.

Le temps de plan HNSW final, 65,405 ms, est informatif. Les propriétés
normatives portent sur le plan, l'index et les bornes structurelles, pas sur ce
temps.

### Cockpit

La CI finale a exécuté depuis `npm ci` :

- ESLint : PASS ;
- Vitest : 16 fichiers, 71 tests PASS ;
- validation des contrats générés : PASS ;
- build Next.js 16.2.12 : PASS sur 7 routes/pages ;
- second clean build : PASS ;
- deux audits npm : 0 vulnérabilité ;
- cohérence des snapshots : 6 tests PASS, 20 sources alignées et 59 noms de
  collections alignés au catalogue.

Les 59 noms prouvent uniquement la concordance de catalogue. Ils ne prouvent
ni corpus publié, ni substance pédagogique, ni couverture de notions.

### CI locale intégrale

Commande canonique :

```bash
bash scripts/ci-local.sh
```

Elle a été lancée avec CPython 3.11.14 et Node 22.22.0. Un wrapper temporaire
hors dépôt exposait uniquement `python3.11`, tandis que le `python3` système
conservait les dépendances nécessaires au contrôle des schémas Cockpit. Aucun
fichier versionné n'a été adapté.

Verdict final : exit 0, 13 PASS et 0 FAIL :

1. `packages/contracts` ;
2. `services/rag-pedago` — Ruff, mypy 76 fichiers et 1 751 tests PASS en
   254,75 s ;
3. `services/rag-engine` — Ruff, mypy, 1 173 tests et intégration réelle PASS ;
4. `services/cockpit` — 71 tests, deux builds et audits PASS ;
5. `repository-hygiene` ;
6. `repository-hygiene-tests` ;
7. `ci-topology-tests` — fixture canonique acceptée, 22 mutations refusées ;
8. `main-protection-policy-tests` — 31 tests PASS ;
9. `governance-locks` — 18 clés sur 18 ;
10. `taxonomy-validation` — 57 taxonomies, 0 erreur, 15 premiers jets ;
11. `source-evidence-check` — 11 verdicts conformes ;
12. `governance-guard-tests` — 16 tests PASS ;
13. `ci-failsafe-tests` — 44 contrôles PASS.

Une tentative antérieure, non retenue comme preuve finale, avait produit 12/13
parce que l'ajout du répertoire CPython au `PATH` remplaçait aussi `python3`
pendant le build Cockpit. Le diagnostic était `pydantic` absent. Le routage
d'interpréteur a été corrigé hors dépôt, puis les 13 cibles ont été rejouées
depuis le début. Aucun test n'a été ignoré et aucun code n'a changé entre ces
deux exécutions.

### Gouvernance, hygiène et secrets

- Les 18 verrous correspondent exactement à leur baseline ; aucun verrou n'a
  été activé.
- Aucun diff ne touche le contrat de verrous ni sa baseline.
- `git diff --check` : PASS.
- Le scan des lignes ajoutées ne trouve ni chemin machine-local, ni clé privée,
  ni token, ni DSN avec credential embarqué.
- Aucun document réel n'a été lu, écrit, ingéré ou généré.
- Les ressources Docker éphémères du runner sont à zéro après le trap.
- Les stashes historiques sont restés inchangés.

## Revue indépendante et correctifs

Deux reviewers indépendants ont relu le diff complet, puis chaque delta
correctif, et ont exécuté leurs propres suites.

`lot40_final_code_review` : `APPROVE`, confiance `HIGH`, aucun P0–P3 sur
`48d1a000e720788140fa831b1ae5be4db936cccc`. Sa dernière preuve indépendante
comprend Ruff, `git diff --check` et un runner PostgreSQL frais avec les trois
marqueurs LOT41.

`lot40_public_quality_review` : `APPROVE`, confiance élevée, aucun P0–P3. Sa
contre-revue a notamment rejeté une première preuve cross-matière ambiguë : le
refus NSI-only → Maths pouvait provenir du caractère dormant de Maths. Le test
final demande donc NSI, qui est instanciée, avec une identité Maths-only et
prouve zéro appel au pipeline avant le 403.

Les cycles de revue ont aussi fermé :

- credential readiness incompatible avec le BFF ;
- readiness susceptible de confondre nombre de lignes et substance ;
- impossibilité de diagnostiquer Maths dormante ;
- scope mono-matière non appliqué à toutes les surfaces ;
- profil chat codé en dur ou divergent ;
- audience multiple interprétable différemment ;
- anti-rejeu plus court que l'expiration SSO ;
- absence de producteur runtime de révocation ;
- TTL de révocation inférieur au cookie ;
- catalogue fallback hors profil ;
- ordre lexical seulement accidentel ;
- doublons de collections chat ;
- preuve E2E cross-matière initialement confondue.

## Matrice de preuve

| Contrôle | Environnement | Artefact | Verdict |
|---|---|---|---|
| Contrat identité/enveloppe/scope 0.4 | Python 3.11 | 86 tests + schémas | PASS |
| Projection et digests LOT38 | package partagé + YAML versionné | trois empreintes distinctes | PASS |
| Transport SSO → session → BFF → moteur | Cockpit + moteur | tests JWT, rotation, audience, expiration | PASS |
| Révocation et anti-rejeu partagés | Redis simulé et backend Redis | tests multi-instance, restart logique, signOut | PASS |
| Scope dense/lexical/post-DB | moteur + PostgreSQL réel | 13 dimensions et contrôle de ligne | PASS |
| Matrice candidats × matières | PostgreSQL réel | 6 combinaisons | PASS |
| Refus cross-matière non ambigu | HTTP + PostgreSQL réel | Maths-only → NSI, zéro pipeline | PASS |
| Readiness dormante sans faux vert | HTTP signé | Maths diagnostic, release evidence false | PASS |
| Review tenant/collection et révocation | HTTP + PostgreSQL réel | IDOR doc/chunk et quarantaine | PASS |
| Routes historiques | templates Nginx + tests topologiques | fermetures 410 | PASS |
| Migration 003 | PostgreSQL réel | montée, descente, atomicité, garde de données | PASS |
| Cockpit BFF et build production | Node 22.22.0 | 71 tests, deux builds, deux audits | PASS |
| CI locale intégrale | venvs frais + Docker | 13 cibles canoniques | PASS |
| Revue code indépendante | SHA de code final | diff complet + runner réel | APPROVE/HIGH |
| Revue qualité indépendante | SHA de code final | métriques, périmètre et contre-preuves | APPROVE/HIGH |
| Checks GitHub | PR vers `main` | contextes protégés | PENDING |
| Fusion | PR vers `main` | équivalence des arbres | PENDING |

## Limites et portes restantes

- Le rapport de LOT41 ne remplace pas les checks GitHub ni la fusion via PR.
- LOT41A doit être une PR d'autorisation pure, approuvée humainement. Elle doit
  référencer le SHA fusionné LOT41, le scope exact, l'environnement isolé
  `nexus-validation-1`, les stores et le plan de destruction.
- Aucun document réel, pipeline de validation ou appel OpenRouter n'est
  autorisé avant LOT41A.
- LOT42 doit qualifier 100 % des ressources et prouver
  `quality → gate → review` avant publication dans une DB de validation.
- LOT43/43A doivent figer l'évaluation et obtenir la seconde autorisation
  humaine avant toute promotion.
- LOT44 à LOT46 doivent terminer l'observabilité, l'exploitation, les grants
  de production et le rollback. Le rôle de production réel reste une
  précondition explicite de LOT45 ; LOT41 ne prétend pas l'avoir audité.
- LOT47 porte la décision humaine finale de go-live et ne peut pas être
  auto-autorisée.

En conséquence, LOT41 est techniquement approuvé pour publication par PR, mais
le projet complet reste volontairement `GO_LIVE: NO_GO`.
