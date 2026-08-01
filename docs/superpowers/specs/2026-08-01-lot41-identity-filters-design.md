# Design LOT41 — identité autoritative et filtres serveur exhaustifs

## Statut et frontière

Ce design détaille LOT41 du document canonique
`2026-07-31-pilot-go-live-finalization-design.md`. LOT41 part du `main` fusionné
de LOT40 et livre une seule branche, une seule PR et le rapport
`docs/reports/lot_41_profile_filter_enforcement.md`.

LOT41 ferme le chemin identité → collection → PostgreSQL. Il ne lit aucun
document réel, ne publie aucun corpus, n'active aucun verrou de gouvernance et
ne rend pas le pilote public. Le verdict global reste `GO_LIVE: NO_GO`.

## Menace traitée

À la base LOT40, le navigateur peut demander des collections arbitraires, le
BFF appelle `rag-engine` avec un jeton de service statique et le moteur ne
reçoit aucune identité pédagogique. Les deux canaux SQL ne filtrent que la
collection et `review_status=reviewed`. Une configuration erronée ou un IDOR
peut donc mélanger tenant, niveau, voie, matière, candidat, audience, droits ou
année de programme.

LOT41 considère comme non fiable tout champ fourni par le navigateur. Une
identité n'est autoritative qu'après validation SSO par le cockpit et transport
dans un jeton interne signé, borné dans le temps et validé par `rag-engine`.

## Chaîne de confiance

```text
jeton SSO Nexus
  → vérification cockpit (signature, issuer, audience, exp, jti, révocation)
  → InternalIdentity nexus-contracts 0.4.0
  → jeton interne HS256, identity imbriquée, issuer/audience moteur exacts
  → BFF same-origin authentifié
  → jeton service Authorization + jeton identité X-Nexus-Identity
  → validation indépendante rag-engine
  → scope serveur immuable
  → gate collection
  → filtres SQL dense et lexical identiques
  → vérification applicative de chaque ligne
```

Le jeton interne n'aplatit pas l'identité dans les claims JWT réservés. Il
contient un objet `identity` validé par `InternalIdentity`, tandis que `iss`,
`aud`, `sub`, `jti`, `iat` et `exp` décrivent le transport cockpit → moteur.
Il lie aussi un artefact de scope contractuel. `nexus-contracts` 0.4.0 définit
l'enveloppe de transport et `PilotRetrievalScopeArtifact` : identité exacte,
candidats, matières, relation collection → matière → `programme_version`, année
scolaire et digest des octets source LOT38. L'artefact dormant versionné est
une projection canonique du scope LOT38 ; un test cross-service recalcule cette
projection et son SHA-256. Le moteur charge l'artefact via le package partagé,
recalcule son digest et refuse toute divergence. Il n'importe ni ne lit
`rag-pedago` au runtime. LOT41A autorisera l'utilisation de cet artefact exact
dans l'environnement isolé.

L'algorithme accepté est exactement `HS256`. Le secret, l'issuer et l'audience
sont obligatoires et absents du dépôt.

L'enveloppe impose `outer.sub == identity.sub`, `outer.jti == identity.jti`,
`outer.exp <= identity.exp`, des issuer/audience externes admis par la
configuration serveur obligatoire, et un scope inchangé lors des rotations.
Le schéma exporté valide la structure. Un validateur sémantique TypeScript
complémentaire applique les invariants Pydantic non exprimables en JSON Schema
(année contiguë, égalités sub/jti et bornes temporelles). Des fixtures négatives
partagées prouvent la parité Python/TypeScript sur ces invariants.

Le navigateur ne reçoit ni jeton de service, ni jeton interne, ni identité
complète, ni secret de signature. Le callback de session Auth.js ne sérialise
jamais ces objets. Les routes BFF les lisent exclusivement dans le JWT de
session httpOnly côté serveur. Les routes
BFF `search` et `chat` exigent une session active à chaque appel, contrôlent la
révocation avant l'appel moteur et transmettent le jeton interne de la session.
Une identité absente, expirée, révoquée, mal signée ou incohérente ferme le
chemin avant PostgreSQL.

La révocation de session est partagée par toutes les instances cockpit dans
Redis via `NEXUS_SESSION_REDIS_URL`. En production ou validation, une URL
absente ou Redis indisponible ferme l'authentification ; la mémoire locale est
réservée aux tests explicitement configurés. Le BFF est l'unique autorité de
révocation runtime : le moteur n'accepte un jeton d'identité qu'avec le jeton de
service BFF distinct, jamais directement depuis le navigateur. Les tests
simulent deux instances et un redémarrage logique contre le même store.

## Contrat 0.4.0

`nexus-contracts` passe de `0.3.0` à `0.4.0`. Ce changement ajoute un champ
requis avant 1.0 et constitue donc un cutover coordonné et volontairement
cassant ; ADR-0022 documente explicitement l'exception à la règle générale
d'ADR-0002 et le rejet des identités internes 0.3. `InternalIdentity` reçoit le champ
obligatoire `school_year` au format `YYYY-YYYY+1`. Le cockpit le produit depuis
la configuration serveur de release `NEXUS_RELEASE_SCHOOL_YEAR`, jamais depuis
le navigateur ni depuis un claim libre de profil.

Le même cutover borne les chaînes et listes, impose l'unicité des matières, un
`exp` entier JSON sûr et un `sub` pseudonymisé. Les champs libres ou directement
identifiants (`email`, identifiant élève, objectif libre, secrets) restent
interdits par `extra='forbid'`. Cette fermeture évite de transporter de la PII
dans les jetons internes et les logs.

Les schémas JSON et les types/validateurs TypeScript sont régénérés et portent
des identifiants `/v0.4/`. Les tests prouvent : compatibilité des modèles non
touchés, refus d'une identité 0.3 incomplète, année valide et export
déterministe. ADR-0022 consigne le changement SemVer et la frontière de
confiance.

## Scope serveur et règle restrict-only

Le moteur dérive un `ServerRetrievalScope` figé à partir de l'identité et de la
définition canonique de collection. Il contient :

- `tenant` exact ;
- `niveau` exact ;
- `voie` canonique ;
- matière demandée appartenant aux matières signées ;
- `statut_enseignement` exact ;
- candidat exact, avec contenu générique `both` admis ;
- audience signée, avec contenu `tous` admis ;
- droits autorisés pour le rôle ;
- visibilités autorisées pour le rôle ;
- `review_status=reviewed` ;
- collection résolue, instanciée et retrievable ;
- `school_year` exact.
- `programme_version` exacte pour la matière de la collection.

Le client peut demander une ou plusieurs collections, et chaque collection
doit appartenir à l'ensemble dérivé. Il ne peut envoyer aucune dimension qui
élargit le scope. Pour le chat, le profil construit par le BFF doit correspondre
aux dimensions autoritatives ; toute divergence est refusée. La collection est
contrôlée avant l'acquisition d'une connexion, le chargement des modèles ou une
consultation de cache.

## Adaptateur de voie unique

Le loader de catalogue est l'unique frontière entre les slugs historiques et
le contrat. Il convertit `gen` en `generale`, `stmg` en `technologique` et
conserve `null` comme absence explicite de voie. Les valeurs déjà canoniques
sont acceptées ; toute autre valeur est refusée. Aucun endpoint, store ou BFF
ne compare directement `gen` et `generale`.

Pour le pilote terminale générale, une collection sans voie ou d'une autre voie
ne peut pas être autorisée. Les définitions de collection ne sont pas modifiées
par effet de bord.

## Droits et visibilité

Les droits sont dérivés de `RIGHTS_ALLOWED_CONTEXTS` dans le package partagé ;
une valeur DB inconnue ou `unknown` est exclue. Les contextes rôle → accès sont
fermés :

| rôle | contextes de droits | visibility admise |
| --- | --- | --- |
| `student` | `public` | `public` |
| `teacher` | `public`, `internal`, `teacher` | `public`, `internal` |
| `reviewer` | `public`, `internal`, `teacher` | `public`, `internal`, `restricted` |
| `ingest_agent` | `internal` | `internal`, `restricted` |
| `admin` | `admin` | `public`, `internal`, `restricted`, `private` |

Le contexte `owner_student` n'est jamais inféré : le schéma ne porte pas encore
la preuve de propriété d'un document privé. Une ressource privée étudiante est
donc refusée par LOT41.

## Schéma PostgreSQL et migration 003

La migration additive `003_profile_filtering.sql` ajoute à `rag_chunks` :

- `tenant TEXT` sans valeur par défaut ;
- `candidat TEXT` sans valeur par défaut ;
- `visibility TEXT` sans valeur par défaut ;
- `school_year TEXT` sans valeur par défaut ;
- `programme_version TEXT` sans valeur par défaut ;
- les contraintes de domaine et index nécessaires au prédicat exhaustif.

Les lignes historiques restent volontairement non servables par le nouveau
chemin, car toutes les nouvelles dimensions sont nulles. LOT42 est seul
autorisé à les peupler après `quality → gate → review`.

Le rollback 003 refuse de supprimer les colonnes si une ligne a été enrichie
au-delà des valeurs de bootstrap. Dans ce cas, le retour arrière applicatif
conserve l'expansion de schéma. Il ne prétend jamais supprimer des données
publiées sans perte.

## Prédicat SQL exhaustif

Dense et lexical reçoivent le même objet scope et appliquent les mêmes
prédicats paramétrés : collection, tenant, niveau, voie, matière, statut,
candidat exact ou `both`, audience signée ou `tous`, droits, visibilité, année,
version de programme et `review_status='reviewed'`. Aucune chaîne issue de
l'identité n'est interpolée
dans le SQL.

Chaque ligne remonte aussi toutes ces dimensions. Le mapper vérifie une seconde
fois qu'elle est admise par le scope ; une ligne incohérente, inconnue,
`needs_review` ou quarantaine fait échouer tout le canal, sans filtrage silencieux
ni résultat partiel.

## Review, IDOR et révocation

La file et les décisions de review exigent la même identité humaine signée et
le même artefact serveur que le retrieval. Tenant et collection clients ne
peuvent que restreindre ce scope dérivé. Une requête portant un `doc_id` ou
`chunk_id` d'un
autre scope ne lit ni ne modifie aucune ligne et retourne un résultat générique,
sans révéler l'existence de l'identifiant.

La promotion reste uniquement `needs_review → reviewed`. Une révocation
explicite autorise `reviewed → quarantined` pour le même scope et le même rôle
humain ; elle ne permet aucune réactivation ni retour à `needs_review`. La
mutation et l'invalidation sont transactionnelles du point de vue du chemin
servi : la recherche publique n'utilisant pas le cache, la requête identique
suivante relit PostgreSQL et ne peut plus voir le chunk.

## Fermeture des routes historiques

Les handlers historiques restent disponibles au code de maintenance et à leurs
tests, mais la topologie de production ne publie plus `/search`, `/kb/*` ni
`/rag/*`. Nginx retourne `410` sur ces préfixes et n'autorise comme retrieval
public que les routes v2 derrière le BFF. Des tests de topologie échouent si un
proxy vers ces routes réapparaît. Aucun service public ne peut contourner
`ServerRetrievalScope` en appelant l'ancien moteur Chroma/Ollama.

## Cache et révocation

La recherche publique continue à ignorer le cache de warmup et relit la base à
chaque appel. Une révocation de contenu ou un changement de review est donc
visible immédiatement. Le cache administratif est partitionné par digest de
scope, n'est jamais servi au public et est invalidé par génération. Un appel
avec identité expirée/révoquée ou collection devenue interdite est refusé avant
toute lecture de cache, y compris si une entrée empoisonnée existe.

Les réponses et logs ne contiennent ni sujet, jti, jeton ni profil complet. Ils
peuvent exposer uniquement les dimensions pédagogiques non personnelles et un
digest de scope.

## CLI et évaluation

Le CLI et le harnais d'évaluation ne disposent d'aucun bypass. Une exécution DB
réelle doit fournir une identité contractuelle par un fichier local explicitement
sélectionné ou appeler l'endpoint authentifié. Le fichier n'est jamais affiché
ni versionné avec une identité réelle. L'absence de scope est un refus.

LOT43 fournira le manifeste d'identité de validation lié à LOT41A ; LOT41 teste
seulement des identités synthétiques sans PII.

## Preuves obligatoires

Les tests couvrent exhaustivement : les trois candidats `individuel`, `libre`,
`cned_libre`, Mathématiques et NSI, AEFE, mauvais niveau, mauvaise voie,
collection arbitraire, override client, IDOR tenant/sujet, cache après
révocation, `needs_review`, quarantaine, droits/visibility inconnus, année
incompatible et indisponibilité des routes historiques en production.

La preuve réelle utilise PostgreSQL/pgvector éphémère, migration
`002 → 003`, rollback sûr `003 → 002 → 003`, les deux canaux et les endpoints
HTTP. Ruff, mypy, pytest, contrats, cockpit, garde-fous, CI locale et checks
GitHub doivent être verts sur la tête candidate.

LOT41 est livrable seulement si aucun appel non authentifié ou scope divergent
n'acquiert une connexion DB, et si dense/lexical ne peuvent retourner qu'une
ligne conforme à toutes les dimensions. Le projet reste `GO_LIVE: NO_GO` jusqu'à
l'autorisation humaine LOT41A et les lots suivants.
