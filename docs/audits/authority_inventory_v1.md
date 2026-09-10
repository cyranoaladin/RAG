# NEXUS-AUTHORITY-INVENTORY-V1

Un concept, une autorité. Ce document nomme l'autorité canonique de chaque
concept, et dit combien d'endroits la décident aujourd'hui.

Il est le résultat d'une cartographie de `services/rag-pedago`,
`services/rag-engine`, `packages/contracts`, `packages/release-chain` et
`scripts/`, sur `main` en `342e710`.

## Le chiffre qui change le plan

Le plan de convergence supposait que la servabilité était décidée à deux ou
trois endroits, dont la matrice. La mesure en trouve **environ trente-neuf**.

```text
SERVABILITY_DECISION_IMPLEMENTATIONS=39   (mesuré, pas estimé)
CURRENTNESS_DECISION_IMPLEMENTATIONS=12
PROGRAM_DECISION_IMPLEMENTATIONS=5
RELEASE_SELECTION_IMPLEMENTATIONS=2
PLACEMENT_PRODUCTION_CORES=2              (un par version de protocole)
AUTHORIZATION_VERIFICATION_IMPLEMENTATIONS=1
```

Converger trente-neuf décideurs en un seul n'est pas un lot : c'est un
programme de travail. Annoncer `SERVABILITY_DECISION_IMPLEMENTATIONS=1` à la
fin de ce lot serait faux. Ce lot fait autre chose, et le dit : il **arrête la
croissance** et supprime les contradictions déclaratives.

## Autorités canoniques

| Concept | Autorité canonique | Décideurs mesurés |
| --- | --- | ---: |
| `SOURCE_IDENTITY_AUTHORITY` | `content_sha256` du catalogue institutionnel | 1 |
| `PII_DECISION_AUTHORITY` | `nexus_contracts.pii_review_decisions` (`NEXUS-PII-REVIEW-DECISIONS-V1`) | 1 |
| `PROGRAM_SERVABILITY_AUTHORITY` | `programme_version` déclarée (ADR-0051), partition `NEXUS-PROGRAM-PARTITION-V4` | 5 |
| `CURRENTNESS_POLICY_AUTHORITY` | `NEXUS-RAG-CURRENTNESS-POLICY-V1`, adoptée par ADR-0055 | 12 |
| `SERVABILITY_POLICY_AUTHORITY` | **absente** — composition à créer | 39 |
| `PLACEMENT_AUTHORITY` | `nexus_contracts.release_scope_placement` | 2 cœurs |
| `AUTHORIZATION_AUTHORITY` | `nexus_contracts.authorization_set` | 1 |
| `RELEASE_IDENTITY_AUTHORITY` | `require_governed_release_id` (ADR-0050) | 1 |
| `RELEASE_REGISTRY_AUTHORITY` | `select_release_authority` | 2 |

## Ce que la mesure a corrigé dans le plan

**La politique d'actualité n'était pas un décideur.** Elle est `applied: false`
et n'a **aucun lecteur de production** : seules deux épreuves la lisent. Sa
contradiction avec ADR-0051 n'était donc exécutée par aucun code, ce qui la
rendait invisible à tout test et à toute métrique. Elle attendait le jour de
l'adoption pour se manifester, c'est-à-dire le jour où elle aurait coûté le plus
cher.

**La moitié V2 de l'autorisation est implémentée mais inatteignable.**
`AuthorizationSetV2`, `ReleaseScopePlacementV2`, `parse_authorization_set_v2`,
`parse_release_scope_placement_v2` et `verify_authorization_binding_set_v2`
existent dans `packages/contracts`, figurent dans les `__all__` de leurs
modules, et sont **absents de `nexus_contracts/__init__.py`**. Aucun code hors
épreuves ne les appelle.

```text
AUTHORIZATION_V2_SYMBOLS_IMPLEMENTED=7
AUTHORIZATION_V2_SYMBOLS_EXPORTED_AT_PACKAGE_LEVEL=0
AUTHORIZATION_V2_NON_TEST_CALLERS=0
```

Ce n'est pas une autorité concurrente : c'est une moitié de contrat qu'on ne
peut pas atteindre par le chemin d'import normal. Le premier pas de la migration
V2 n'est donc pas d'écrire un producteur, c'est de rendre le contrat atteignable.

**La sélection de release a bien deux autorités.** `select_release_authority`
est le mécanisme contractuel ; `resoudre_source_du_registre`, dans
`scripts/qualification/compute_promoted_content_set.py`, superpose une seconde
matrice de précédence avec ses propres modes et son propre refus d'ambiguïté.
C'est la duplication la plus dangereuse de la liste, parce qu'elle porte sur
*quelle release fait foi*.

## Duplications les plus nettes, à résorber dans cet ordre

1. Le prédicat « active + current + reviewed » est écrit **trois fois** : deux
   fois en SQL, une fois en Python.
2. Le routage par zone est implémenté **deux fois**, avec la même table de
   règles et le même repli `REVIEW_REQUIRED`.
3. La propriété `servable` est dupliquée à l'identique dans deux modules Drive.
4. Le gate de déverrouillage existe en **deux** exemplaires.
5. La promotion vers `INGEST` est décidée à **deux** endroits.

## Ce que ce lot fait, et ne fait pas

Fait : la politique d'actualité cesse de décider à la place de cinq autres
autorités ; un contrôle CI empêche toute **nouvelle** autorité d'apparaître ; la
matrice reste dérivée et sans lecteur de production.

Ne fait pas : la fusion des trente-neuf décideurs de servabilité, ni la
migration des neuf consommateurs d'autorisation. Chacun exige son lot, ses
épreuves et sa revue.
