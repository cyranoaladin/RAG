# ADR-0051 — Servabilité face à une compatibilité programme inconnue : la version déclarée fait autorité, le verdict de compatibilité n'en est pas une

- Statut : Proposé. Devient Accepté par une review humaine `APPROVED` du Code
  Owner selon ADR-0025, sur le HEAD exact de la PR qui le porte, avec le
  challenge `NEXUS-TRUSTED-REVIEW-V1` sur une ligne autonome.
- Périmètre : gouvernance de la servabilité au regard du programme scolaire.
  Ne produit, ne rescelle, ne promeut et ne matérialise aucune release.
- S'appuie sur : ADR-0050 (identité canonique de release), la mesure
  `NEXUS-PROGRAM-COMPATIBILITY-MEASUREMENT-V2`.

## Contexte

La mesure de compatibilité programme, exécutée sur le catalogue courant, rend :

```text
CONTENTS_TOTAL=2451
PROGRAM_COMPATIBILITY_PROVEN=0
PROGRAM_INCOMPATIBILITY_PROVEN=0
PROGRAM_COMPATIBILITY_UNKNOWN=2451
EXACT_ARTIFACT_PROGRAM_BINDING=0
PROGRAM_PROFILE_SCOPE_MATCH=123
PROGRAM_PROFILE_SCOPE_NO_MATCH=2328
```

Son fait bloquant, énoncé par la mesure elle-même : le catalogue ne porte aucune colonne de version
de programme, et sa colonne d'année est une année de publication, jamais une version de programme.
Un croisement niveau × matière prouve qu'une autorité de programme existe pour ce périmètre ; il ne
lie pas un artefact à une version.

Lu naïvement, ce tableau ressemble à un bloqueur de go-live massif : 2451 contenus dont la
compatibilité programme est inconnue. La question posée est donc : cet inconnu empêche-t-il de
servir ?

## Ce que le dépôt fait réellement aujourd'hui, mesuré

Recherche sur toute la surface servie — `services/rag-engine/src`, `services/rag-pedago/rag_pedago`,
`packages/release-chain`, `packages/contracts` — de tout consommateur d'un verdict de compatibilité
programme :

```text
GATES_CONSUMING_A_PROGRAM_COMPATIBILITY_VERDICT=0
RUNTIME_PATHS_CONSUMING_A_PROGRAM_COMPATIBILITY_VERDICT=0
```

Aucun gate de readiness, aucun chargeur de release, aucun endpoint de retrieval ne lit
`PROGRAM_COMPATIBILITY_*`. Ce que le runtime consulte est autre chose : la **version de programme
déclarée**, `programme_version`, champ obligatoire de la taxonomie, porté par le périmètre, le
placement et le chunk. `retrieval_pg_v2.py` la filtre en SQL sur les deux, et
`servable_corpus_manifest.py` refuse un périmètre dont la version déclarée ne correspond pas à la
version de curriculum du manifeste.

Autrement dit, l'autorité de servabilité au regard du programme existe déjà, elle est déclarative
et scellée, et elle est appliquée. La mesure de compatibilité est un instrument d'audit sans
consommateur gouverné.

## Décision

### 1. La version de programme déclarée est l'autorité de servabilité

```text
PROGRAM_SERVABILITY_AUTHORITY=DECLARED_PROGRAMME_VERSION_IN_SEALED_SCOPE
```

Un contenu est servable au regard du programme si, et seulement si, son périmètre scellé déclare
une `programme_version` et que le runtime la fait correspondre à celle de la requête. Cette règle
n'est pas nouvelle : elle est déjà appliquée. Cette ADR la nomme.

### 2. `PROGRAM_COMPATIBILITY_UNKNOWN` n'est pas un bloqueur de servabilité

```text
PROGRAM_UNKNOWN_SERVABILITY_POLICY=ALLOWED_WITH_OTHER_GATES
PROGRAM_UNKNOWN_BLOCKING_CONTENTS=0
```

Un verdict de compatibilité inconnu ne bloque pas, parce qu'il ne fonde aucune décision de service.
Le refuser bloquerait la totalité du corpus sur un instrument que rien ne consulte, et convertirait
une lacune d'audit en interdiction de servir. Les autres gates — PII, droits, fraîcheur,
autorisation, placement — restent entiers et inchangés.

### 3. `PROGRAM_INCOMPATIBILITY_PROVEN` reste un bloqueur

```text
PROVEN_INCOMPATIBILITY_IS_A_SERVABILITY_BLOCKER=YES
```

Une incompatibilité **prouvée** entre un contenu et la version de programme que son périmètre
déclare est un défaut de scellement : le contenu ne doit pas être servi sous ce périmètre. La
mesure courante en compte zéro.

### 4. Aucune revue humaine de masse

```text
HUMAN_REVIEW_REQUIRED_FOR_UNKNOWN=NO
```

Soumettre 2451 contenus à une revue humaine pour lever un inconnu qui ne bloque rien serait une
dépense sans objet. La réduction de l'inconnu, si elle est souhaitée, passe par de la preuve
machine — manifestes d'ingestion, textes officiels, applicabilité déclarée — et relève d'un lot
d'enrichissement, jamais d'un gate de go-live.

### 5. Ce que cette ADR ne change pas

Elle ne modifie aucun code, ne relâche aucun gate existant, et ne déclare aucun contenu servable.
Elle constate l'autorité déjà appliquée et ferme une question ouverte du chantier go-live.

## Conséquence pour le go-live

```text
PROGRAM_GO_LIVE_BLOCKER_COUNT=0
```

sous réserve que cette ADR soit Acceptée. Tant qu'elle est Proposée, la question reste
formellement `POLICY_UNDEFINED`.
