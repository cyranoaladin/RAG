# ADR-0032 — LOT41A : autorité d'autorisation de scope d'ingestion

- **Statut** : Proposé — **non Accepté**. Conformément à ADR-0025, une décision positive exige une review humaine `APPROVED` du Code Owner `@abenrhouma`, dont `commit_id` égale exactement le HEAD final de la PR portant ce document au moment de la review.
- **Date** : 2026-08-07
- **Décideur proposé** : à confirmer par `@abenrhouma` — ce document est rédigé par un agent de codage sous mandat explicite du propriétaire du dépôt, jamais par le Code Owner lui-même.
- **Périmètre** : le mécanisme technique candidat de LOT41A — **jamais** une autorisation de scope elle-même. Aucune autorisation LOT41A n'est déclarée valide par ce document ni par le code qu'il introduit.
- **S'appuie sur** : ADR-0021 (politique de validation pilote dormante, LOT38), ADR-0024 (runtime v2 fail-closed), ADR-0025 (autorité de revue humaine GitHub, LOT41V), ADR-0026 à ADR-0031 (LOT44a-f), `docs/ROADMAP.md`.
- **Ne supersede aucun ADR existant** : ADR-0021, ADR-0024, ADR-0025 et ADR-0031 restent inchangés dans leur texte et leur portée.

## Contexte

`docs/ROADMAP.md`, ADR-0024 et ADR-0025 nomment tous trois LOT41A comme
l'autorité externe manquante qui doit répondre à la question « qui autorise
quel scope, avec quelle preuve, pour combien de temps, et avec quel
mécanisme de révocation » — avant que la moindre ingestion de document réel
ne puisse être activée. `services/rag-engine/src/ingestor/ingestion_profiles/
manifest.py` (LOT44f, ADR-0031) documente explicitement que « LOT41A
("autorisation de scope") n'a, à ce jour, aucune définition, aucun contrat,
aucune implémentation partielle » dans `rag-engine` — et que fabriquer une
autorité de substitution serait exactement l'erreur à éviter.

Une recherche exhaustive du dépôt révèle cependant que LOT41A n'est **pas**
un concept sans aucun ancrage préexistant. ADR-0021 (LOT38, `rag-pedago`)
a déjà :

- défini un scope pilote immuable, `libre_terminale_maths_nsi_real_v1`
  (tenant `libre_terminale`, niveau `terminale`, voie `generale`, statut
  `specialite`, audience `libre`, candidats `cned_libre`/`individuel`/
  `libre`, année scolaire `2026-2027`), à l'état `eligible_for_promotion`,
  jamais `active` ;
- défini une politique de validation dormante,
  `libre_terminale_validation_policy_v1`
  (`services/rag-pedago/configs/pilot_validation_policy.yml`), dont le champ
  `activation_boundary` porte déjà littéralement la valeur `LOT41A` et dont
  `required_authorization` exige déjà `evidence_kind: github_pr_approval`,
  `scope_digest_required`, `policy_digest_required`, `expiry_required`,
  `rights_verification_required`, `pii_absence_required`,
  `rollback_proof_required` ;
- explicitement écrit : « LOT41A devra fournir une approbation humaine
  GitHub indépendante, liée aux octets exacts du payload et au head
  effectivement approuvé » et « LOT41 devra raccorder `rag-engine` au scope
  par contrat/API ou par artefact signé, sans importer ni lire directement
  le code de `rag-pedago` ».

LOT41A n'est donc pas à inventer depuis rien : c'est le **connecteur**,
côté `rag-engine`, qui doit satisfaire exactement les exigences déjà
formalisées par `rag-pedago` en LOT38 — sans jamais importer le code Python
de `rag-pedago` (AGENTS.md : « un service n'importe jamais directement le
code d'un autre service »), et sans jamais réinventer la frontière humaine
GitHub qu'ADR-0025/LOT41V a déjà construite et testée
(`scripts/github/trusted_human_review.py`,
`scripts/github/trusted_human_review_github.py` — code partagé au niveau
racine du dépôt, propriété d'aucun service).

## Décision

### 1. Ce que LOT41A est, et n'est pas

LOT41A est un **mécanisme de vérification**, jamais une autorité en
lui-même. Il ne peut jamais :

- déclarer une autorisation valide par sa seule exécution ;
- accepter un champ `approved_by` librement écrit dans un fichier YAML/JSON
  comme preuve suffisante ;
- accepter une variable d'environnement comme preuve d'autorisation ;
- être satisfait par un test, un fixture, ou un commentaire non authentifié.

La seule source de vérité acceptée est une **review GitHub humaine
`APPROVED`**, sur le **HEAD exact** d'une PR dédiée, avec le challenge
LOT41V correspondant — exactement la frontière qu'ADR-0025 a déjà
construite et que cette session a déjà exercée avec succès trois fois
(PR#90, PR#91, PR#92).

### 2. Contrat `ScopeAuthorization`

Nouveau module `packages/contracts/src/nexus_contracts/scope_authorization.py`
(partagé, jamais possédé par un seul service) définissant un modèle Pydantic
`ScopeAuthorization`, immuable, portant au minimum :

| Champ | Rôle |
|---|---|
| `authorization_id` | identifiant libre, unique |
| `decision` | littéral fixe `"AUTHORIZE_INGESTION_SCOPE"` — jamais un texte libre |
| `scope` | `nexus_contracts.ingestion.ResourceScope` complet (dix dimensions déjà contractuelles, réutilisées telles quelles, jamais redéfinies) |
| `collection` | collection ciblée |
| `manifest_digest` | SHA-256 du manifest de profils approuvé (LOT44c) |
| `profile_id` / `profile_version` / `profile_fingerprint` | identité exacte du profil autorisé |
| `allowed_domains` | sous-ensemble explicite, jamais un wildcard |
| `rights_categories` | catégories de droits/licences autorisées |
| `exclusions` | catégories explicitement exclues (ex. PII, documents nominatifs) |
| `pii_absence_attested` | booléen strict + référence de preuve |
| `valid_from` / `valid_until` | fenêtre de validité — `valid_until` **obligatoire**, jamais `None` (satisfait `expiry_required: true` de LOT38) |
| `evidence` | voir ci-dessous |

`evidence` est un sous-modèle `GitHubApprovalEvidence` portant exactement
les champs déjà produits par le readback JSON du check `Evaluate trusted
human review` (vérifié empiriquement cette session sur PR#90) :
`repository`, `pull_request`, `head_sha`, `base_sha`, `review_id`,
`reviewer`, `submitted_at`, `challenge`.

Aucun champ de confiance (`approved`, `valid`) n'est stocké : la validité
n'est **jamais** un booléen figé dans l'enregistrement — elle est
**toujours** recalculée en direct (voir § 4).

### 3. Stockage — `ingestion_control.scope_authorizations`

Nouvelle table PostgreSQL (migration additive, même schéma logique
`ingestion_control` que LOT44b, décision D1 non remise en cause), portant
la sérialisation de `ScopeAuthorization`, plus :

- `revoked_at` / `revoked_by` / `revocation_reason` (nullable — présents
  seulement si révoqué, jamais réutilisés pour autre chose) ;
- `revocation_evidence` (même structure `GitHubApprovalEvidence`, sur une
  PR de révocation dédiée — la révocation suit exactement la même frontière
  humaine que l'octroi, jamais un simple `UPDATE` opérateur).

Écriture réservée à un rôle dédié `ingestion_control_authority` (least
privilege, même discipline que `provision_ingestion_control_roles.sh`),
jamais au rôle `ingestion_control_app` du worker — le worker ne peut
**jamais** s'auto-écrire une autorisation.

### 4. Vérification — toujours en direct, jamais depuis un cache figé

`ingestion_control/scope_authority.py` (nouveau module `rag-engine`) expose
`verify_scope_authorization(conn, *, scope) -> VerifiedAuthorization` (le
scope porte déjà `collection` comme l'une de ses dix dimensions — jamais un
second paramètre redondant qui pourrait diverger silencieusement du champ
`scope.collection`), qui :

1. lit la ligne `scope_authorizations` correspondant au scope/collection
   demandé, la plus récente non expirée ;
2. si absente, expirée, ou révoquée : lève `ScopeAuthorizationDeniedError`
   (fail-closed, jamais un `None` silencieux) ;
3. **relit en direct** l'évidence GitHub embarquée via
   `scripts/github/trusted_human_review_github.check_github_review`
   (fonction déjà existante, testée, partagée) — jamais une simple
   comparaison de champs stockés. Si la review a été dismissée, si le HEAD
   ne correspond plus, ou si le challenge ne match plus : refus explicite,
   même si la ligne PostgreSQL affirme le contraire.
4. ne retourne un résultat positif que si la vérification live **et**
   l'enregistrement stocké concordent.

Cette double vérification (stockage + relecture live) est ce qui rend la
révocation réelle : dismissre la review GitHub originale invalide
l'autorisation **immédiatement**, sans attendre qu'un opérateur mette à
jour PostgreSQL.

### 5. CLI opérateur — jamais une auto-déclaration

`ingestion_worker/authorize_scope_cli.py` (nouveau, même discipline que
`create_job_cli.py` : jamais un endpoint réseau, `docker exec` uniquement) :

- `record-authorization --pull-request N --scope-file ... --manifest-digest ...` :
  relit la PR N en direct via `check_github_review`, **refuse d'écrire si
  la vérification live échoue**, n'écrit en base que le résultat déjà
  vérifié — jamais une insertion aveugle d'un JSON fourni par l'opérateur ;
- `revoke-authorization --authorization-id ... --revocation-pull-request M` :
  même discipline, sur une PR de révocation séparée.

### 6. Intégration au worker — fail-closed inchangé

`enforce_production_manifest_gate` (LOT44c) reste inchangé dans son
périmètre actuel (manifest + `approved_by`/`approved_at` minimal, ADR-0031
Décision 3). LOT41A ajoute une **seconde** vérification, orthogonale,
avant toute réclamation de job pour un scope donné : `verify_scope_
authorization` doit réussir, sinon le worker refuse de traiter ce job
(nouvel état d'échec explicite, jamais un `dead_letter` silencieux —
`SCOPE_AUTHORIZATION_DENIED`, journalisé dans `workflow_events`).

## Conséquences

- Aucune autorisation LOT41A n'existe à l'issue de ce lot — la table
  `scope_authorizations` reste vide tant qu'aucune PR de scope réelle n'a
  été humainement approuvée selon le protocole ci-dessus.
- Le mécanisme est démontrable end-to-end sur un scope de test factice,
  jamais présenté comme réel.
- `pedago_interface_contract.yml`/`transition_authorization.yml` restent
  inchangés — LOT41A ne les modifie ni ne les contourne.

## Hors périmètre de ce document

- Toute autorisation de scope réelle (elle exige une review humaine
  distincte, sur une PR distincte, jamais celle-ci).
- LOT42 (chaîne d'attestations de publication) — ADR-0033, document
  compagnon.
- Le raccordement bidirectionnel formel avec `rag-pedago` (contrat d'API
  explicite entre les deux plans de contrôle) — cette version consomme
  uniquement la frontière GitHub, commune aux deux services ; un futur lot
  pourra formaliser un contrat `nexus_contracts` dédié si `rag-pedago` a
  besoin de lire l'état d'autorisation de `rag-engine`.

## Alternatives rejetées

Stocker un simple champ `approved: true` sans revérification live est
rejeté : cela reproduirait exactement le défaut que ce document corrige
(une affirmation non revérifiable). Faire porter l'autorisation par
`rag-pedago` seul, lu directement par `rag-engine`, est rejeté : violerait
la règle « aucun service n'importe le code d'un autre » et créerait un
couplage fort non contractuel.

## Retour arrière

Retrait sûr : ne jamais insérer de ligne dans `scope_authorizations`, ne
jamais appeler `authorize_scope_cli.py`. Le worker reste fail-closed par
défaut (absence totale d'autorisation = refus), comportement identique à
avant ce lot.
