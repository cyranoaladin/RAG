# ADR-0033 — LOT42 : chaîne d'attestations de publication (source → gate → revue)

- **Statut** : Proposé — **non Accepté**. Conformément à ADR-0025, une décision positive exige une review humaine `APPROVED` du Code Owner `@abenrhouma`, dont `commit_id` égale exactement le HEAD final de la PR portant ce document au moment de la review.
- **Date** : 2026-08-07
- **Décideur proposé** : à confirmer par `@abenrhouma`.
- **Périmètre** : le mécanisme technique candidat de LOT42 — jamais une attestation de publication réelle. Aucun document n'atteint `RETRIEVAL_ELIGIBLE` de façon nouvelle par ce document seul : LOT42 **ajoute une condition supplémentaire**, jamais un raccourci.
- **S'appuie sur** : ADR-0026 (contrats canoniques `nexus_contracts.resource_state`/`ingestion`, LOT44a), ADR-0027 à ADR-0030 (LOT44b-e), ADR-0031 (LOT44f), ADR-0032 (LOT41A, document compagnon).
- **Ne supersede aucun ADR existant.**

## Contexte

`nexus_contracts.resource_state` (LOT44a) définit déjà la séquence normale
complète d'une ressource, y compris les états correspondant exactement à
la chaîne `quality → gate → review` que LOT42 doit attester :
`RIGHTS_CHECKED`, `QUALITY_CHECKED`, `ROUTED` (gate de routage, rendu
réellement atteignable en revue incrémentale PR#90), `STAGED →
NEEDS_REVIEW → REVIEWED` (revue humaine), et enfin `RETRIEVAL_ELIGIBLE` —
que le module documente lui-même comme « une vérification déterministe et
automatique (constat, pas une décision) qu'une ressource `REVIEWED`
satisfait le prédicat de scope du retrieval ».

Ce constat déterministe est exactement la fonction que LOT42 doit remplir :
vérifier, avant d'accepter la transition `REVIEWED -> RETRIEVAL_ELIGIBLE`,
qu'une chaîne complète et non invalidée d'attestations existe. LOT42
n'invente donc aucun nouvel état de ressource — il **enrichit** la
transition finale déjà spécifiée par LOT44a d'une condition supplémentaire,
vérifiable indépendamment.

`services/rag-pedago/configs/pilot_validation_policy.yml` (LOT38) nomme
déjà `rag-engine` comme unique `allowed_callers` de `publish_reviewed_
chunks`, avec `quality_chain_required: true` — confirmant que la chaîne
d'attestations que LOT42 construit ici est précisément celle que LOT38
attend de recevoir en amont d'une future activation du pilote.

## Décision

### 1. Ce que LOT42 est, et n'est pas

LOT42 produit des **attestations techniques déterministes** — jamais une
autorité humaine. La seule attestation non-déterministe de la chaîne (la
revue humaine finale) doit elle-même être ancrée sur la même frontière
GitHub qu'ADR-0025/LOT41V, jamais auto-attribuée par un agent ou un script.

### 2. Contrat `PublicationAttestation`

Nouveau module `packages/contracts/src/nexus_contracts/publication_
attestation.py` définissant `PublicationAttestation`, immuable, liée au
minimum à :

| Champ | Source |
|---|---|
| `resource_id` / `artifact_id` | `ingestion_control.resources`/`artifacts` (déjà existants) |
| `content_sha256` | `artifacts.sha256` (déjà existant, LOT44d) |
| `canonical_url` | `resource_candidates.canonical_url` (déjà existant) |
| `collection` | scope de la ressource |
| `scope_authorization_id` | référence à LOT41A (ADR-0032) — jamais nulle |
| `profile_id` / `profile_version` / `profile_fingerprint` | identité exacte du profil (LOT44c, déjà existants) |
| `manifest_digest` | LOT44f, déjà calculé (`manifest_fingerprint`) |
| `rights_result` | sortie déterministe de `RightsAgent` (déjà existant, LOT44d) |
| `quality_result` | sortie déterministe de `QualityAgent`/`RoutingDecision` (déjà existant) |
| `gate_result` | résultat de `enforce_production_manifest_gate` au moment du traitement |
| `human_review` | sous-modèle `HumanReviewEvidence` (voir § 3) |
| `protocol_version` | `"LOT42-V1"` — permet une évolution future sans ambiguïté rétroactive |
| `created_at` | horodatage de construction de l'attestation |
| `invalidated_at` / `invalidated_reason` | nullable, voir § 4 |

### 3. Revue humaine finale — même frontière GitHub, jamais une nouvelle

`HumanReviewEvidence` réutilise **exactement** la structure
`GitHubApprovalEvidence` d'ADR-0032 (pas une seconde frontière parallèle) :
la revue finale avant publication est elle-même une review GitHub
`APPROVED`, sur une PR de revue de lot de publication, HEAD exact,
challenge LOT41V, revérifiée en direct au moment de la construction de
l'attestation — jamais stockée comme un simple booléen `reviewed: true`.

### 4. Invalidation — automatique, jamais un oubli opérateur

Une attestation existante est automatiquement considérée invalide (relue
à chaque vérification, jamais seulement au moment de sa création) si l'une
de ces conditions est vraie :

- `artifacts.sha256` actuel du `artifact_id` référencé diverge de
  `content_sha256` (contenu modifié après attestation) ;
- le `profile_fingerprint` référencé ne correspond plus au profil actuel du
  manifest (LOT44c, mécanisme déjà existant de détection de dérive) ;
- `manifest_digest` référencé diverge du digest actuel du manifest
  approuvé ;
- l'autorisation de scope LOT41A référencée (`scope_authorization_id`) est
  expirée ou révoquée (vérifiée en direct, ADR-0032 § 4) ;
- la revue humaine finale (`human_review`) ne revérifie plus en direct
  (review dismissée, HEAD divergent).

`verify_publication_attestation(conn, *, resource_id) ->
VerifiedAttestation` réévalue ces cinq conditions à chaque appel — jamais
un statut mis en cache. Toute divergence renvoie `PublicationAttestation
InvalidError`, jamais un `bool` silencieux.

### 5. Stockage — `ingestion_control.publication_attestations`

Nouvelle table PostgreSQL additive, même schéma `ingestion_control`.
Écriture réservée à un rôle dédié `ingestion_control_attestor`, distinct du
rôle worker `ingestion_control_app` (moindre privilège — le worker
construit les CINQ premières attestations déterministes de la chaîne
lui-même au fil de son traitement normal, mais **jamais** la revue humaine
finale, qui exige le même CLI opérateur externe qu'ADR-0032).

### 6. Intégration à la machine d'état — un seul point d'ancrage

`apply_resource_transition` (LOT44b, inchangé dans sa primitive générique)
reçoit un appelant supplémentaire, spécifique à la seule transition
`REVIEWED -> RETRIEVAL_ELIGIBLE` : avant de l'invoquer, le worker appelle
`verify_publication_attestation` ; en cas d'échec, la transition n'est
jamais tentée (la ressource reste `REVIEWED`, jamais un état d'erreur
nouveau — `REVIEWED` reste un état stable et valide en soi, LOT42 ne fait
qu'empêcher le pas suivant). Aucune autre transition de
`NORMAL_SEQUENCE` n'est modifiée par LOT42.

### 7. Falsification, replay, concurrence — exigences de test explicites

Le mandat opérateur exige des tests couvrant : falsification (modifier un
champ d'attestation stocké sans que la relecture live ne le détecte pas),
replay (rejouer une ancienne évidence GitHub dismissée), révocation
(scope LOT41A révoqué après attestation → invalidation immédiate),
modification de contenu (SHA changé → invalidation), modification de
profil (fingerprint changé → invalidation), changement de scope,
concurrence (deux tentatives simultanées de construction d'attestation
pour la même ressource), reprise (crash entre deux attestations de la
chaîne — la reprise doit retrouver exactement l'état déterministe déjà
construit, jamais le reconstruire différemment).

### 8. Statut explicite du câblage (remédiation GATE H1, item L)

Deux propriétés distinctes, à ne jamais confondre dans un rapport :

| Drapeau | Valeur | Signification |
|---|---|---|
| `LOT42_MECHANISM_IMPLEMENTED` | voir rapport de lot | Le mécanisme (contrat, stockage, vérification live, point d'ancrage, tests) existe et est éprouvé. |
| `LOT42_LIVE_PIPELINE_WIRED` | **`false`** | Le chemin `STAGED -> NEEDS_REVIEW -> REVIEWED` **n'existe pas encore**. Aucune ressource n'atteint donc `REVIEWED`, et `attempt_retrieval_eligible_transition` n'a en pratique aucun appelant en production. |

`LOT42_LIVE_PIPELINE_WIRED` reste `false` — et doit être déclaré tel quel —
tant que ce chemin n'est pas construit. Il ne s'agit pas d'un détail de
présentation : décrire LOT42 comme « un runtime de publication opérationnel
de bout en bout » serait faux tant que rien ne peut atteindre `REVIEWED`.
Ce câblage relève du Track suivant, après GATE H1.

**Garde-fou dépôt.** `tests/test_lot42_retrieval_eligible_anchor.py` analyse
l'AST de tout `src/` et échoue si un module autre que le point d'ancrage
demande une transition vers `RETRIEVAL_ELIGIBLE` (`new_state=`/`to_state=`).
Il porte aussi une garde anti-vacuité (l'ancre doit réellement effectuer la
transition) et une liste fermée des modules autorisés à seulement
*mentionner* l'état (`claim.py`, qui l'exclut de l'ensemble réclamable).
Non-vacuité démontrée en injectant un second chemin dans `transitions.py` :
le test l'a détecté à la ligne exacte, puis est repassé au vert après
restauration. Le futur lot qui câblera le pipeline devra donc passer par
l'ancre, ou faire échouer ce test.

## Conséquences

- `RETRIEVAL_ELIGIBLE` reste, comme avant, un état terminal jamais atteint
  par ce lot seul — aucune ressource n'y accède tant qu'aucune PR de scope
  LOT41A ni de revue de publication LOT42 n'a été humainement approuvée.
- La publication produit réelle (écriture dans `rag_chunks`/pgvector, hors
  périmètre de `nexus_contracts.resource_state` par sa propre docstring)
  reste un sous-système distinct et **hors périmètre de ce document** — cf.
  section suivante.

## Hors périmètre de ce document

- Le sous-système de publication produit lui-même (chunking, embedding,
  écriture pgvector) — `resource_state.py` documente explicitement que
  « `PUBLISHED` n'existe pas dans cette énumération... la publication
  produit est un sous-système distinct, hors périmètre ». LOT42 attend
  qu'une ressource soit `RETRIEVAL_ELIGIBLE` ; il ne construit pas ce qui
  vient après. Un futur lot dédié (LOT43+, déjà nommé `lot43_evaluator`
  dans la politique dormante LOT38) devra le spécifier séparément.
- Toute attestation réelle, tout scope réel.

## Alternatives rejetées

Fusionner LOT41A et LOT42 en un seul mécanisme est rejeté : l'autorisation
de scope (une décision préalable, à portée large, avec expiration) et
l'attestation de publication (une preuve technique par ressource, invalidée
par tout changement de contenu) ont des cycles de vie et des granularités
different — les confondre affaiblirait la révocabilité de chacun.

## Retour arrière

Retrait sûr : ne jamais construire d'attestation, laisser `REVIEWED` comme
état terminal de fait. Aucune régression sur les transitions déjà
existantes (`DISCOVERED` → ... → `REVIEWED` reste identique).
