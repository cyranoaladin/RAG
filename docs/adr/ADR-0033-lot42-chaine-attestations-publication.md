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

### 2. Les faits viennent du pipeline, jamais de l'opérateur (remédiation GATE H1, item E)

La première implémentation acceptait `--content-sha256`, `--rights-status`,
`--quality-passed`, `--gate-passed` en arguments libres. Un opérateur
pouvait donc attester une publication conforme pour une ressource dont le
gate avait échoué : rien ne confrontait ces affirmations aux faits
réellement produits.

Ces options **n'existent plus**. `ingestion_control/publication_evidence.py`
est la seule source de ces faits, et ne lit que des données que le pipeline
a écrites lui-même :

| Fait | Source durable |
|---|---|
| `collection` | `ingestion_control.resources` |
| `content_sha256` | `ingestion_control.artifacts.sha256` |
| `canonical_url` | `ingestion_control.resource_candidates` |
| `rights_status`, `rights_assessed_at` | `workflow_events` — transition `RIGHTS_CHECKED` écrite par `run_rights_agent` |
| `quality_passed`, `quality_report_digest`, `quality_assessed_at` | `workflow_events` — transition `QUALITY_CHECKED` écrite par `run_quality_agent` |
| `gate_passed`, `gate_name`, `gate_evaluated_at` | `workflow_events` — événement `PUBLICATION_GATE_EVALUATED`, **émis quelle que soit sa valeur** |

`workflow_events` est append-only : aucun rôle ne détient `UPDATE` ni
`DELETE` dessus. Un verdict de gate négatif ne produit aucune transition
d'état ; sans l'événement dédié, « pas de preuve de succès » serait
indistinguable de « pas de preuve du tout ».

**Pas de score scalaire.** L'attestation porte le *digest* du
`QualityReport` complet, jamais un « score de qualité ». Les heuristiques
de ce lot sont des placeholders explicitement documentés ; les résumer en
un scalaire leur donnerait une autorité qu'elles n'ont pas. Le digest, lui,
rend le rapport comparable dans le temps sans rien affirmer sur sa valeur.

### 3. L'artefact de revue canonique et la revue humaine

Comme LOT41A, la décision de publication **est** un artefact canonique
versionné dans Git :

```
governance/publication-reviews/<review_id>-<digest>.json
```

Le digest fait partie du nom : une décision modifiée ne peut jamais
réutiliser le chemin d'une décision déjà approuvée.

`PublicationReviewArtifact` (`nexus_contracts.authority_artifacts`) porte
l'intégralité de la décision, **y compris les `event_id` des
`workflow_events` qui ont produit chaque fait** — une preuve qui ne nomme
pas son événement n'est pas une preuve.

Le protocole est en deux temps :

1. `attest_publication_cli propose-review` lit les faits durables, refuse
   immédiatement toute chaîne négative, et écrit l'artefact canonique. **Ce
   fichier, et lui seul, est ce que l'humain relit dans la PR.**
2. `attest_publication_cli record-attestation`, après approbation :
   revérifie la review en direct (champ par champ, même discipline
   qu'ADR-0032 § 4), relit le blob Git au head approuvé, **recompare octet
   à octet** avec l'artefact redérivé depuis la base, et n'écrit qu'ensuite.

Une divergence DB ↔ artefact est un refus. Le digest faisant partie du
chemin, un artefact falsifié n'est d'ailleurs même pas trouvable.

La revue humaine finale réutilise **exactement** la même frontière GitHub
qu'ADR-0032 — jamais une seconde frontière parallèle, jamais un booléen
`reviewed: true`.

### 4. Une chaîne négative ne publie jamais (remédiation GATE H1, item F)

Le refus est imposé **trois fois, à trois niveaux indépendants**, parce
qu'une seule barrière est une barrière qu'on peut contourner :

1. **Irreprésentable dans l'artefact** — `PublicationReviewArtifact` refuse
   de se construire si `quality_passed` ou `gate_passed` est faux, ou si
   `rights_status` vaut `unknown`.
2. **Irreprésentable en base** — les contraintes `CHECK` de la migration
   008 (`quality_passed = true`, `gate_passed = true`, `rights_status`
   n'incluant pas `unknown`) refusent la ligne, y compris à un accès SQL
   privilégié.
3. **Refusé à la relecture** — la vérification rejette la transition même
   si une ligne avait été introduite par un chemin inattendu.

### 5. Invalidation — automatique, jamais un oubli opérateur

`verify_publication_attestation` réévalue **toute** la chaîne à chaque
appel — jamais un statut mis en cache :

- dérive de `content_sha256`, de `profile_fingerprint`, de
  `manifest_digest` ;
- faits durables du pipeline devenus négatifs, absents, ou divergents de
  ceux revus ;
- artefact de revue introuvable, non canonique, ou d'octets différents ;
- review humaine finale qui ne revérifie plus (PR fermée, review
  dismissée, HEAD divergent, reviewer ayant perdu ses droits) ;
- autorisation de scope LOT41A référencée qui ne vérifie plus, ou qui ne
  couvre plus la catégorie de droits produite.

Toute divergence lève `PublicationAttestationInvalidError`, jamais un
`bool` silencieux. L'invalidation détectée est persistée au mieux-effort
(`invalidated_at`/`invalidated_reason`) — trace d'audit, jamais la source
de vérité, qui reste toujours la relecture live elle-même.

### 5bis. Stockage et rôle — `ingestion_control.publication_attestations`

Écriture réservée au rôle `ingestion_control_attestor`, distinct du rôle
worker. Ce rôle détient en outre `SELECT` sur `workflow_events` et sur les
tables du pipeline : sans cette lecture, le conteneur d'attestation devrait
*aussi* porter le DSN du worker — exactement le cumul de credentials que
l'item K interdit. Il n'a aucune écriture sur ces tables.

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
| `LOT42_PIPELINE_PATH_IMPLEMENTED` | voir rapport de lot | Le chemin interne `ROUTED -> STAGED -> NEEDS_REVIEW -> REVIEWED`, suivi de l'ancre unique, existe pour les répétitions isolées. |
| `LOT42_LIVE_PIPELINE_WIRED` | **`false`** | Ce chemin n'est importé ni par le runner vivant, ni par une API, un démarrage ou un cron. Aucune ressource de production ne peut donc l'emprunter. |

`LOT42_LIVE_PIPELINE_WIRED` reste `false` — et doit être déclaré tel quel —
tant que l'activation gouvernée de ce chemin n'est pas réalisée lors de la
phase de production autorisée. Il ne s'agit pas d'un détail de présentation :
décrire LOT42 comme « un runtime de publication production opérationnel de
bout en bout » serait faux tant que le runner vivant ne l'appelle pas.

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
  par le pipeline vivant de ce lot. Une répétition isolée ne peut l'atteindre
  qu'avec une autorisation LOT41A et une revue LOT42 revérifiées en direct.
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
