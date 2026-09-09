# ADR-0051 — Servabilité et programme : la version déclarée fait autorité, l'inconnu ne bloque pas, l'incompatibilité prouvée bloque

- Statut : Proposé. Devient Accepté par une review humaine `APPROVED` du Code
  Owner selon ADR-0025, sur le HEAD exact de la PR qui le porte, avec le
  challenge `NEXUS-TRUSTED-REVIEW-V1` sur une ligne autonome.
- Périmètre : gouvernance de la servabilité au regard du programme scolaire.
  Ne produit, ne rescelle, ne promeut et ne matérialise aucune release.
- S'appuie sur : ADR-0025, ADR-0050, et la partition qualifiée
  `NEXUS-PROGRAM-PARTITION-V4`.

## Autorité citée

Cette ADR s'appuie sur `NEXUS-PROGRAM-PARTITION-V4`, qui supersède V3 et
constitue la mesure qualifiée courante. Une version antérieure de ce texte
citait `NEXUS-PROGRAM-COMPATIBILITY-MEASUREMENT-V2` et ses chiffres
`0 / 0 / 2451` : **cette citation était périmée** et sa conclusion
`PROGRAM_GO_LIVE_BLOCKER_COUNT=0` en découlait à tort.

```text
PROGRAM_POPULATION_TOTAL=2451
PROGRAM_COMPATIBILITY_PROVEN=10
PROGRAM_INCOMPATIBILITY_PROVEN=1
PROGRAM_COMPATIBILITY_UNKNOWN=2440
PROGRAM_PARTITION_SET_EQUALITY=true
PROGRAM_PARTITION_INTERSECTION_COUNT=0
PROGRAM_PARTITION_UNACCOUNTED=0
PROGRAM_PARTITION_UNION_SHA256=baa2a8501ccbf94b0d46cbe5cc4b843c44fabeb95b91543980fb14b81f9c030a
PROGRAM_COMPATIBLE_SHA_SET_SHA256=2caa5baf09142b8438fe29eb2791afb9e8090dbb921797cd009b65d91330bdf6
PROGRAM_INCOMPATIBLE_SHA_SET_SHA256=0698209f85f0195fa21df136a3fa37766a7631cfeaa10b79bbef9c2b4d09dfa5
PROGRAM_UNKNOWN_SHA_SET_SHA256=20620a1646b7b1ec1ae5ddf50d775d1c5ea36f98962aed8ddc31153bbfe531db
```

La partition est exhaustive et disjointe : 10 + 1 + 2440 = 2451, intersection nulle, rien de non
comptabilisé, et l'union a la même empreinte que la population. Elle est émise `applied=false` :
elle mesure, elle n'applique rien.

## Contexte

Le catalogue ne porte aucune colonne de version de programme, et sa colonne d'année est une année
de publication, jamais une version de programme. Un croisement niveau × matière prouve qu'une
autorité de programme existe pour ce périmètre ; il ne lie pas un artefact à une version. D'où une
majorité d'inconnus.

Lu naïvement, 2440 inconnus ressemblent à un bloqueur de go-live massif. La question est donc :
cet inconnu empêche-t-il de servir, et que faire de l'unique incompatibilité prouvée ?

## Ce que le dépôt fait réellement, mesuré

Recherche sur toute la surface servie — `services/rag-engine/src`,
`services/rag-pedago/rag_pedago`, `packages/release-chain`, `packages/contracts` — de tout
consommateur d'un verdict de compatibilité programme :

```text
GATES_CONSUMING_A_PROGRAM_COMPATIBILITY_VERDICT=0
RUNTIME_PATHS_CONSUMING_A_PROGRAM_COMPATIBILITY_VERDICT=0
```

Aucun gate de readiness, aucun chargeur de release, aucun endpoint de retrieval ne lit ces
verdicts. Ce que le runtime consulte est autre chose : la **version de programme déclarée**,
`programme_version`, champ obligatoire de la taxonomie, portée par le périmètre, le placement et le
chunk. `retrieval_pg_v2.py` la filtre en SQL sur les deux, et `servable_corpus_manifest.py` refuse
un périmètre dont la version déclarée ne correspond pas à la version de curriculum du manifeste.

L'autorité de servabilité au regard du programme existe donc déjà, elle est déclarative, scellée et
appliquée. La partition de compatibilité est un instrument d'audit sans consommateur gouverné —
ce qui explique aussi pourquoi l'incompatibilité prouvée ne bloque rien **aujourd'hui** : rien ne
la lit. C'est précisément ce que cette ADR corrige.

## Décision

### 1. La version de programme déclarée est l'autorité de servabilité

```text
PROGRAM_SERVABILITY_AUTHORITY=DECLARED_PROGRAMME_VERSION_IN_SEALED_SCOPE
```

Un contenu est servable au regard du programme si son périmètre scellé déclare une
`programme_version` et que le runtime la fait correspondre à celle de la requête. Cette règle est
déjà appliquée ; cette ADR la nomme.

### 2. Un verdict inconnu ne bloque pas

```text
PROGRAM_UNKNOWN_SERVABILITY_POLICY=ALLOWED_WITH_OTHER_GATES
PROGRAM_UNKNOWN_BLOCKING_CONTENTS=0
HUMAN_REVIEW_REQUIRED_FOR_UNKNOWN=NO
```

Refuser 2440 contenus sur un instrument que rien ne consulte convertirait une lacune d'audit en
interdiction de servir. Les autres gates — PII, droits, fraîcheur, autorisation, placement —
restent entiers. Réduire l'inconnu relève d'un lot d'enrichissement par preuve machine, jamais
d'une revue humaine de masse ni d'un gate de go-live.

### 3. Une incompatibilité prouvée est un bloqueur de go-live

```text
PROVEN_INCOMPATIBILITY_IS_A_SERVABILITY_BLOCKER=YES
PROVEN_INCOMPATIBILITY_GO_LIVE_BLOCKERS=1
PROGRAM_GO_LIVE_BLOCKER_COUNT=1
```

Un contenu dont il est **prouvé** qu'il cite un programme que l'autorité courante de son périmètre
a remplacé ne doit pas être servi sous ce périmètre. La partition V4 en nomme exactement un :

```text
content_sha256=de42e9816d7d012fd5d6b3349171cf43dd038c1e50fa0fe9e664bcc8521194b9
scope_level=troisieme          matiere=technologie
cited_reference=BOEN_31_2020-07-30
authority_current_references=BOEN_9_2024-02-29
attribution_basis=MULTI_SCOPE_EXPLICIT_SECTION
authority_evidence_status=VERIFIED_OFFICIAL_BY_COMMANDITAIRE
```

Cette ADR ne transforme jamais un `INCOMPATIBLE` prouvé en contenu servable.

### 4. Disposition de l'artefact incompatible

Deux issues, à trancher au scellement de la nouvelle release :

```text
EXCLUDE_FROM_NEW_RELEASE   — l'artefact ne fait pas partie de l'ensemble servable
FIX_SCOPE_BINDING          — le périmètre est corrigé pour déclarer l'autorité courante,
                             ou l'artefact est relié au scope dont le programme cité est
                             encore en vigueur
```

Aucune des deux n'est décidée ici. Tant qu'aucune n'est appliquée et prouvée, l'artefact reste
`GOVERNED_NOT_SERVABLE` avec `blocker=PROGRAM_INCOMPATIBILITY_PROVEN`.

```text
PROGRAM_GO_LIVE_BLOCKER_COUNT peut revenir à 0 seulement après preuve que
de42e9816d7d012fd5d6b3349171cf43dd038c1e50fa0fe9e664bcc8521194b9 n'appartient plus au
GOVERNED_SERVABLE_SOURCE_SET, ou que sa liaison de périmètre est corrigée.
```

### 5. Ce que cette ADR ne change pas

Elle ne modifie aucun code, ne relâche aucun gate, et ne déclare aucun contenu servable.
