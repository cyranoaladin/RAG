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

### 2. L'artefact canonique **est** la décision (remédiation GATE H1, item B)

Une review GitHub `APPROVED` prouve qu'un humain a lu **un diff précis, à un
commit précis**. Elle ne prouve rien sur un fichier local que l'opérateur
fournirait ensuite à un outil. Tant que la décision enregistrée provient
d'une source indépendante de la review, les deux ne sont reliées par rien :
faire approuver un scope étroit puis enregistrer un scope large ne viole
aucune vérification.

La décision est donc un **artefact canonique versionné dans Git** :

```
governance/authorizations/<authorization_id>.json
```

`packages/contracts/src/nexus_contracts/authority_artifacts.py` définit
`ScopeAuthorizationArtifact` (Pydantic, `extra="forbid"`), portant
l'intégralité de la décision :

| Champ | Rôle |
|---|---|
| `protocol_version` | littéral `"LOT41A-V1"` — jamais implicite, jamais absent |
| `authorization_id` | ASCII minuscule strict ; détermine à lui seul le chemin canonique |
| `decision` | littéral fixe `"AUTHORIZE_INGESTION_SCOPE"` |
| `scope` | `ResourceScope` complet (dix dimensions, réutilisées telles quelles) |
| `manifest_digest` | SHA-256 du manifest de profils approuvé (LOT44c) |
| `profile_id` / `profile_version` / `profile_fingerprint` | identité exacte du profil autorisé |
| `allowed_domains` | hôtes ASCII normalisés, triés, dédupliqués — jamais un wildcard |
| `rights_categories` | catégories autorisées, triées ; `unknown` interdit |
| `exclusions` | hôtes ou préfixes de chemin explicitement exclus |
| `pii_absence_attested` / `pii_absence_evidence` | assertion + référence de preuve |
| `valid_from` / `valid_until` | fenêtre obligatoire (satisfait `expiry_required` de LOT38) |

Trois propriétés rendent le lien inviolable :

1. **Chemin canonique déterministe** — dérivé de l'identifiant seul.
   L'opérateur ne choisit jamais quel fichier est relu, et aucun
   identifiant ne peut désigner un fichier hors de son répertoire.
2. **Sérialisation canonique déterministe** — clés triées, indentation
   fixe, dates UTC, listes normalisées. Les vérificateurs exigent
   l'égalité **octet à octet** entre le blob relu et la re-sérialisation
   de son parse : un fichier commité sous une autre forme est refusé, donc
   les octets revus par l'humain sont exactement ceux dont le digest est
   calculé. La forme est indentée, délibérément : ces octets doivent
   rester lisibles dans un diff, sans quoi la review humaine — la seule
   chose qui donne sa valeur à toute la chaîne — deviendrait impraticable.
3. **Validation stricte** — un champ inconnu ne peut pas voyager
   silencieusement à côté de la décision revue.

L'évidence GitHub n'est délibérément **pas** un champ de l'artefact : un
artefact ne peut pas contenir la preuve de sa propre approbation, qui
n'existe qu'après le commit qui le porte.

### 3. Stockage — `ingestion_control.scope_authorizations`

La table PostgreSQL n'est **jamais** une autorisation : c'est un *index*
vers les octets qui en sont une. Elle porte la projection de l'artefact,
l'évidence GitHub relue à l'enregistrement, les colonnes de révocation, et
surtout le lien cryptographique :

- `artifact_path` — contraint par `CHECK` à valoir exactement
  `governance/authorizations/<authorization_id>.json` ;
- `artifact_blob_sha` — SHA-1 d'objet Git des octets approuvés ;
- `authorization_digest` — SHA-256 de la forme canonique.

Aucun champ de confiance (`approved`, `valid`) n'est stocké : la validité
n'est jamais un booléen figé, toujours recalculée en direct (§ 4).

La révocation suit exactement la même frontière humaine que l'octroi (PR de
révocation dédiée, approuvée), jamais un simple `UPDATE` opérateur.

Écriture réservée au rôle `ingestion_control_authority`, jamais au rôle
`ingestion_control_app` du worker — le worker ne peut jamais s'auto-écrire
une autorisation.

**Aucun index ordonné par `valid_until`** n'existe (item C, § 4).

### 4. Vérification — l'autorisation est **nommée**, jamais devinée

`ingestion_control/scope_authority.py` expose :

```python
verify_scope_authorization(conn, *, authorization_id, scope=None, now=None)
    -> VerifiedAuthorization
```

`authorization_id` est **obligatoire**. Sélectionner « l'autorisation la
plus récente couvrant ce scope » ferait d'une écriture en base une décision
d'autorité : enregistrer une autorisation large plus tardive suffirait à
élargir silencieusement un job déjà planifié. Un job est lié à **une**
autorisation nommée, portée par son payload (`scope_authorization_id`) ;
plusieurs autorisations historiques peuvent coexister pour un même scope
sans qu'aucune ne supplante l'autre.

La vérification refait la chaîne entière, à chaque usage :

1. **ligne exacte** chargée par clé primaire — aucun `ORDER BY`, aucun
   `LIMIT` ;
2. **révocation et fenêtre de validité** — `valid_from ≤ now < valid_until` ;
3. **scope** — si fourni, les dix dimensions doivent coïncider exactement ;
4. **review GitHub relue en direct**, comparée **champ par champ** :
   `repository`, `pull_request`, `base_sha`, `head_sha`, `review_id`,
   `reviewer`, `submitted_at`, `challenge` (remédiation item G — la forme
   antérieure, « le challenge stocké appartient-il à l'ensemble des
   challenges live ? », acceptait une évidence dont le reviewer ou la
   review avaient changé) ;
5. **blob Git relu** au head approuvé exact, au chemin canonique exact ;
   SHA d'objet Git recalculé localement et comparé à celui annoncé par
   GitHub **et** à celui persisté ;
6. **parse canonique + digest recalculé intégralement**, comparé au digest
   persisté ;
7. **égalité champ par champ artefact ↔ ligne PostgreSQL** — sans quoi un
   `UPDATE` direct en base (élargir `allowed_domains`, avancer
   `valid_until`) survivrait à la relecture.

Chacune de ces sept étapes peut refuser seule. C'est cette double
vérification (stockage + relecture live) qui rend la révocation réelle :
dismissre la review GitHub invalide l'autorisation **immédiatement**, sans
qu'aucun opérateur ne touche PostgreSQL.

**Transport.** La relecture passe par `ingestion_control/github_authority.py`
— requêtes `GET` uniquement, jeton lu à l'exécution depuis un fichier
secret, échéance globale bornée. La *décision* elle-même reste exactement
celle d'ADR-0025 : la fonction pure `evaluate_trusted_review` est chargée
non modifiée depuis `scripts/github/trusted_human_review.py`. Seul le
transport change ; la sémantique d'autorité est partagée à l'octet près.

### 4bis. Enforcement pendant l'ingestion (remédiation GATE H1, item D)

Une `VerifiedAuthorization` calculée puis ignorée n'autorise rien : elle
donne seulement le droit de *commencer*. `ingestion_control/
scope_enforcement.py` transforme chaque contrainte en assertion, appliquée
au moment où le fait correspondant devient connu :

| Point de contrôle | Ce qui est confronté |
|---|---|
| `pre_fetch` | `authorization_id`, scope, `manifest_digest`, profil (id/version/empreinte), fenêtre de validité — **avant tout accès réseau** |
| `destination` | hostname normalisé des URL du payload contre `allowed_domains` / `exclusions` |
| `redirect` | **chaque saut réellement suivi** par `safe_fetch` — seul endroit d'où une chaîne de redirection est observable |
| `rights` | catégorie de droits **produite par le pipeline** contre `rights_categories` |
| `pii` | absence de PII (cette release n'en ingère aucune) |

Les hôtes sont comparés par **égalité exacte** après normalisation, jamais
par suffixe : une autorisation pour `education.fr` n'autorise ni
`education.fr.attacker.test`, ni `www.education.fr`.

**Revalidation live.** L'autorisation est revérifiée intégralement — donc
relue contre GitHub — au point de contrôle `rights`, en plus de
`pre_fetch`. Une révocation ou une expiration survenue *pendant*
Scout/Fetcher/Extractor prend donc effet avant que la ressource n'avance,
jamais seulement au job suivant. Les sauts de redirection, eux, réutilisent
l'autorisation déjà vérifiée : imposer une requête GitHub par saut
n'ajouterait aucune garantie et multiplierait la surface de panne.

Toute violation est journalisée (`SCOPE_AUTHORIZATION_DENIED`, avec le nom
du point de contrôle) puis **committée avant de se propager** — le rollback
que l'appelant effectue sur l'exception effacerait sinon la seule trace
durable du refus.

### 5. CLI opérateur — l'opérateur choisit *quelle* autorisation, jamais *ce qu'elle dit*

`ingestion_worker/authorize_scope_cli.py` (jamais un endpoint réseau,
`docker exec` / conteneur ponctuel uniquement) :

```
record-authorization --authorization-id ID --repository R --pull-request N --expected-head SHA
```

Il n'existe **aucune** option décrivant le contenu de la décision — pas de
`--scope-file`, pas de `--manifest-digest`. La chaîne exécutée est :

```
verify_review (live, lecture seule, temps borné)
  -> refus si non APPROVED sur --expected-head exact
  -> fetch_blob_at_ref(chemin canonique dérivé de l'ID, head approuvé)
  -> parse canonique strict (refus si octets non canoniques)
  -> digest SHA-256 recalculé intégralement
  -> INSERT (décision + digest + évidence live)
```

`revoke-authorization` suit la même discipline sur une PR de révocation
dédiée.

**Rôle PostgreSQL.** L'outil se connecte via
`PG_INGESTION_CONTROL_AUTHORITY_DSN`, jamais le DSN applicatif du worker,
et sans aucun repli : l'absence de la variable est une erreur explicite.

### 6. Intégration au worker — fail-closed, à chaque étape

`enforce_production_manifest_gate` (LOT44c) reste inchangé. LOT41A ajoute
une vérification orthogonale, avant toute réclamation effective de job pour
un scope donné, puis les points de contrôle du § 4bis. Un refus fait
échouer le job explicitement (retry/dead\_letter normal), jamais un
traitement poursuivi sous une autorisation supposée.

### 6bis. Isolation des autorités d'opérateur (remédiation GATE H1, item K)

Le conteneur worker de longue durée ne reçoit **jamais** de credential
d'autorité ou d'attestation. Deux services Compose ponctuels et isolés
(`scope-authority-operator`, `publication-attestor-operator`,
`profiles: [operator]`) portent chacun **un seul** secret, n'exposent aucun
port, ne redémarrent pas, tournent en `read_only` avec
`no-new-privileges`, et se terminent après l'opération.

Le rôle `ingestion_control_app` ne détient que `SELECT` sur les deux tables
d'autorité : le worker peut exécuter lui-même la vérification live, jamais
s'écrire une autorisation.

### 7. Cycle de vie des PR d'autorité — décision (remédiation GATE H1, item H)

**Question posée.** Le vérificateur d'ADR-0025 a été conçu pour autoriser une
*fusion* : il exige une PR **ouverte**. Or une autorisation LOT41A/LOT42 est
une autorité *de longue durée*, consultée à chaque job. Que devient-elle
lorsque sa PR est fusionnée ou fermée ?

**Comportement réel, mesuré** (et non supposé) — `evaluate_trusted_review`
d'ADR-0025, exercée directement sur des documents GitHub synthétiques :

| Scénario | `approved` | `reason` |
|---|---|---|
| PR ouverte + review `APPROVED` au head exact | `true` | `approved` |
| **PR fusionnée/fermée** | `false` | `pull_request_not_open` |
| Review dismissée après approbation | `false` | `approval_revoked` |
| Approbation sur un autre head | `false` | `current_head_approval_missing` |
| Mauvaise base (`develop` au lieu de `main`) | `false` | `base_ref_mismatch` |
| Challenge absent/incorrect dans le corps | `false` | `current_head_approval_missing` |
| Relecteur sans droit d'écriture | `false` | `reviewer_permission_insufficient` |
| Head sur un dépôt tiers | `false` | `head_repository_mismatch` |
| PR en brouillon | `false` | `pull_request_is_draft` |

**Décision : les PR d'autorité restent OUVERTES pendant toute la durée de vie
de l'autorisation. Elles ne sont jamais fusionnées.**

L'artefact d'autorisation (§ 2 bis) vit donc sur une branche dédiée
`governance/authorization/<authorization_id>`, jamais fusionnée dans `main`.
C'est cohérent avec sa nature : une autorisation est un **octroi révocable**,
pas du code destiné à devenir un état permanent du dépôt.

Conséquences, toutes fail-closed — aucune ne dépend d'une action opérateur :

- **Révocation par fermeture** : fermer la PR rend l'autorisation invalide
  immédiatement (`pull_request_not_open`), sans aucune écriture PostgreSQL.
- **Révocation par dismissal** : dismisser la review a le même effet
  (`approval_revoked`).
- **Révocation explicite auditée** : artefact de révocation dédié (§ 3),
  pour laisser une trace motivée — jamais l'unique mécanisme.
- **Immutabilité de branche** : un `push --force` sur la branche d'autorité
  change le head ; l'évidence stockée ne correspond alors plus
  (`current_head_approval_missing` et, en amont, divergence de digest). La
  protection de branche est donc une défense en profondeur, jamais le
  garde-fou porteur.
- **Suppression de branche** : GitHub ferme automatiquement la PR — retour au
  cas « fermée », donc refus.
- **Expiration** : `valid_until` est obligatoire et appliqué indépendamment de
  l'état GitHub.

**ADR-0025 n'est ni modifié, ni affaibli, ni contourné.** Aucun mode de
« readback persistant » acceptant une PR fusionnée n'est introduit : il
supprimerait précisément la révocation par fermeture, qui est ici la
propriété la plus utile. L'exigence « PR ouverte », initialement une
contrainte de fusion, devient dans ce contexte une **fonctionnalité** de
révocabilité.

Ces neuf scénarios sont exercés par des tests dédiés, chacun devant refuser.

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
