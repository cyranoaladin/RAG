# Surface d'adoption runtime d'AuthorizationSetV2 — mesurée, non déclarée

Mesure au commit `b6badcb`, après fusion de #162. Remplace les colonnes `UNKNOWN` de
`docs/audits/r1_multiplacement_authority_surface.csv`, dont #162 disait lui-même que plusieurs
consommateurs n'avaient pas été audités.

## Ce que V2 change

V2 est **additif** à V1. Un même `content_sha256` peut être couvert par deux membres si — et
seulement si — ils portent des scopes distincts. Deux membres ne couvrent jamais la même liaison
`(content_sha256, scope)`.

Il sépare deux cardinalités qui ne se substituent jamais :

```text
unique_content_count           contenus physiques uniques couverts
authorization_binding_count    liaisons d'autorité distinctes requises
```

Sur le corpus historique : 319 contenus uniques, 486 liaisons, 167 contenus multi-placés.

`verify_authorization_binding_set_v2` exige une **égalité d'ensemble exacte** entre les liaisons
autorisées et celles que la release scellée requiert — jamais une égalité de cardinalité, jamais
une comparaison contenu-seul qui masquerait un contenu autorisé sous le mauvais scope.

## Les neuf consommateurs de production

```text
AUTH_V2_RUNTIME_CONSUMERS_TOTAL=9
AUTH_V2_RUNTIME_CONSUMERS_MIGRATED=0
AUTH_V2_RUNTIME_CONSUMERS_REMAINING=9
```

| fichier | symboles V1 consommés |
|---|---|
| `services/rag-engine/scripts/deploy_verified_release_cli.py` | `parse_authorization_set` |
| `services/rag-engine/scripts/sign_production_readiness_manifest_cli.py` | `parse_authorization_set` |
| `services/rag-engine/src/ingestor/ingestion_profiles/readiness_gate.py` | `AuthorizationSetV1`, `parse_authorization_set` |
| `services/rag-engine/src/ingestor/ingestion_profiles/release_verification_v2.py` | `AuthorizationSetV1`, `ReleaseScopePlacementV1`, `parse_authorization_set`, `parse_release_scope_placement` |
| `services/rag-engine/src/ingestor/ingestion_worker/authorization_mapping.py` | `AuthorizationSetV1`, `parse_authorization_set` |
| `services/rag-engine/src/ingestor/release_scope_placement.py` | `ReleaseScopePlacementV1`, `parse_release_scope_placement` |
| `services/rag-pedago/rag_pedago/governance/catalog_republish.py` | `AuthorizationSetV1`, `ReleaseScopePlacementV1`, `ReleaseScopePlacementEntryV1`, `parse_authorization_set` |
| `services/rag-pedago/rag_pedago/governance/h2_evidence.py` | `parse_authorization_set` |
| `services/rag-pedago/rag_pedago/imports/h2b_coverage_report.py` | `AuthorizationSetV1`, `parse_authorization_set` |

## Le fait qui commande l'ordre des travaux

```text
V2_PRODUCERS_OUTSIDE_THE_CONTRACT=0
```

Aucun code hors `packages/contracts` ne produit aujourd'hui un `NEXUS-AUTHORIZATION-SET-V2` ni un
`NEXUS-RELEASE-SCOPE-PLACEMENT-V2`. Le producteur de portée, `rag_pedago/governance/cli.py`, émet
la V1. Les sets d'autorisation, eux, sont des documents **fournis par l'opérateur** : les CLI les
reçoivent en entrée.

Deux conséquences, qui interdisent de commencer par les consommateurs :

1. **Migrer un consommateur vers V2 seul le rendrait inutilisable** : il n'existe aucun document V2
   à lui donner.
2. **Migrer vers V2 en refusant V1 rejetterait tout artefact opérateur existant.** L'adoption doit
   accepter les deux et préférer V2, jamais basculer d'un coup.

## Ordre imposé

1. Le producteur de portée émet `NEXUS-RELEASE-SCOPE-PLACEMENT-V2` à côté de la V1.
2. Un producteur de `NEXUS-AUTHORIZATION-SET-V2` existe, ou le format opérateur est documenté.
3. Les neuf consommateurs acceptent les deux protocoles, et `verify_authorization_binding_set_v2`
   devient le gate d'égalité d'ensemble dès qu'une paire V2 est fournie.
4. Les épreuves portent sur les 319 contenus, 486 liaisons et 167 contenus multi-placés réels,
   dérivés de l'autorité scellée, jamais écrits en dur.

## Ce que ce lot ne fait pas

Aucun consommateur n'est migré ici, et aucune autorisation de production n'est fabriquée. Une
migration partielle de code d'autorisation crée une autorisation fausse : c'est le seul défaut que
ni la vitesse ni la pression de livraison ne justifient.
