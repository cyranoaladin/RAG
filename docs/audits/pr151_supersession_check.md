# #151 n'est pas supersédée par #174 — vérification

Le plan de fusion prévoyait de fermer #151 comme supersédée par le lot d'actualité
V2. La vérification contredit ce plan. Fermer #151 sur cette base aurait perdu du
travail.

## Mesure

Les fichiers de code de #151 sont absents des deux surfaces qui auraient dû les
absorber :

```
services/rag-pedago/rag_pedago/governance/url_source_registry.py       IN_MAIN=0   IN_PR174=0
services/rag-pedago/rag_pedago/governance/currentness_disposition.py   IN_MAIN=0   IN_PR174=0
services/rag-pedago/scripts/build_url_source_registry.py               IN_MAIN=0   IN_PR174=0
services/rag-pedago/configs/make_target_safety.yml                     IN_MAIN=1
```

```
PR151_SUPERSEDED_BY_PR174=false
PR151_UNIQUE_CODE_FILES=3
```

## Pourquoi la confusion était plausible

Les deux lots portent sur les URL sources et l'actualité, mais ils ne livrent pas
la même chose.

| | #151 | #174 |
| --- | --- | --- |
| Objet | registre d'URL sources et disposition de fraîcheur, **portés par une release** | réconciliation de provenance et campagne d'observation, **mesure sur la population** |
| Sortie | `data/releases/prerentree_2026_2027/multilevel/url_source_registry.json` | `docs/reports/handoff/url_provenance_reconciliation.json` |
| Portée | une release nommée | les 2530 relations |

Le recouvrement est thématique, pas fonctionnel. #174 mesure ; #151 matérialise
un artefact dans un répertoire de release.

## Un point à trancher avant de fusionner #151

#151 ajoute deux fichiers **dans un répertoire de release existant** qui en compte
déjà 91. Aucun des deux n'écrase un artefact scellé :

```
url_source_registry.json       EXISTS_ON_MAIN=0
currentness_disposition.json   EXISTS_ON_MAIN=0
```

L'immutabilité au sens d'ADR-0050 n'est donc pas violée par écrasement. Reste une
question de gouvernance que ce document ne tranche pas : ajouter des artefacts à
une release déjà publiée change ce que cette release contient, sans changer son
identité. Cette question relève d'une revue humaine, pas d'une mesure.

## Décision

#151 reste ouverte. Elle n'est ni fermée, ni fusionnée sur la foi d'une
supersession qui n'existe pas.
