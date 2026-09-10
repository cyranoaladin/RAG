# Migration des consommateurs vers AuthorizationSetV2 — état et obstacle mesuré

## Où en est la migration

```text
AUTH_V2_RUNTIME_CONSUMERS_TOTAL=9
AUTH_V2_RUNTIME_CONSUMERS_MIGRATED=3
AUTH_V2_RUNTIME_CONSUMERS_REMAINING=6
```

Trois consommateurs passent par le chargeur canonique et acceptent désormais les
deux protocoles :

| Consommateur | Ce qu'il lit du document |
| --- | --- |
| `ingestion_profiles/readiness_gate.py` | `members` |
| `scripts/sign_production_readiness_manifest_cli.py` (2 sites) | `members` |
| `scripts/deploy_verified_release_cli.py` (2 sites) | `members`, `profile_manifest_digest` |

Ces champs sont **communs aux deux protocoles**. Leur migration ne change donc
rien à ce qu'ils vérifient : elle élargit seulement ce qu'ils acceptent.

## L'obstacle, et pourquoi ce n'est pas une question d'effort

Les six restants lisent deux champs qui n'existent **que** en V1 :

```text
authority_required_count
authority_required_set_sha256
```

La V2 ne les porte pas, et ce n'est pas un oubli. Elle porte à la place :

```text
authorization_binding_count
authorization_binding_set_sha256
```

C'est **la raison d'être de la V2**. La V1 compare un ensemble de *contenus* ;
la V2 compare un ensemble de *liaisons* `(content_sha256, scope)`. Un même
contenu légitimement placé sous deux scopes est une seule entrée en V1 et deux
en V2. Les deux comptes ne peuvent pas coïncider, et les faire coïncider serait
précisément le défaut que la V2 corrige.

## Ce que chaque consommateur restant devra recevoir

Comparer un ensemble de liaisons exige de connaître les liaisons **exigées**,
c'est-à-dire d'avoir le `ReleaseScopePlacementV2` sous la main. Aucun de ces six
ne l'a aujourd'hui à son point de comparaison :

| Consommateur | Comparaison V1 actuelle | Ce qu'il lui manque |
| --- | --- | --- |
| `ingestion_profiles/release_verification_v2.py` | `authority_required_count` et son empreinte, croisés avec la couverture H2 | le placement, et la version binding des compteurs H2 |
| `ingestion_worker/authorization_mapping.py` | refuse si le compte ou l'empreinte diffèrent | le placement |
| `governance/catalog_republish.py` | idem, plus la republication du catalogue | le placement |
| `imports/h2b_coverage_report.py` | idem, dans le rapport de couverture | le placement |
| `governance/h2_evidence.py` | recoupe trois sources sur les mêmes deux champs | le placement, et les trois sources en version binding |
| `governance/corpus_campaign.py` | porte les deux champs dans son propre modèle | le placement |

Migrer l'un d'eux en remplaçant simplement le nom du champ produirait une
comparaison qui **passe** sans rien prouver : deux compteurs de natures
différentes, mis côte à côte.

## L'ordre qui reste

1. Rendre le `ReleaseScopePlacementV2` disponible au point de comparaison de
   chacun des six.
2. Porter en version liaison les compteurs de couverture H2 dont trois d'entre
   eux dépendent.
3. Alors seulement, faire consommer `verify_authorization_binding_set_v2`.

Tant que 1 et 2 ne sont pas faits, migrer les six ne rapprocherait pas du but :
cela remplacerait une vérification vraie par une vérification vide.

## Où vit le chargeur, et pourquoi une épreuve d'image l'a décidé

Le chargeur a d'abord été écrit dans `packages/release-chain`. Les épreuves
unitaires passaient. L'épreuve d'**image réelle** a refusé :

```text
ModuleNotFoundError: No module named 'nexus_release_chain'
```

`Dockerfile.ingestion-worker` embarque `nexus-contracts` et
`nexus-pdf-page-policy`, pas la chaîne de release. Or le gate de readiness
tourne dans cette image. Aucune épreuve unitaire ne pouvait le voir : elles
tournent toutes dans un environnement où tout est installé.

Élargir l'image aurait résolu le symptôme en alourdissant le conteneur pour une
fonction qui ne parle que du contrat. Choisir entre deux versions d'un contrat
est une affaire de contrat : le chargeur vit donc dans `nexus_contracts`, et une
vérification le prouve en l'important depuis un environnement **sans** chaîne de
release.

## Ce que le lot courant garantit malgré tout

```text
NEW_RELEASE_AUTHORIZATION_PROTOCOL=NEXUS-AUTHORIZATION-SET-V2
V1_NEW_RELEASE_FALLBACK=0
AUTHORIZATION_V2_PRODUCERS=1
```

`LoadedAuthorizationSet.require_v2` existe pour les points qui ne doivent jamais
accepter un document historique. Une release neuve ne retombe pas en V1, et le
refus nomme l'exigence au nom de laquelle il refuse.
