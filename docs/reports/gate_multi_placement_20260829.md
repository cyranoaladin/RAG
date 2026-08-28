# Gate opérateur — le multi-placement est interdit par la release

*29 août 2026. Arrêt sur gate authentiquement nouveau.*

## Les trois travaux sont faits

| Travail | État |
|---|---|
| 1. Manifeste déclarant les profils | **fait** — 121 profils, `declared_count = 121`, invariant vérifié |
| 2. Partitionnement de la matrice | **fait** — 121 partitions, 2 389 documents |
| 3. `_source_records` → `catalogue-par-scope` | **fait** — empreinte `ec5ccbf7a30fec01…` vérifiée à chaque chargement |

Le producteur franchit désormais `_source_records` pour les 2 389 documents.
Trois défauts rencontrés et corrigés en chemin : `download_url` absent de la
nouvelle branche — laissé **vide**, le catalogue portant l'URL de listing et non
celle de téléchargement, et présenter l'une pour l'autre serait affirmer une
provenance qu'on n'a pas ; `source_evidence` non renseigné ; et la branche
`primary_evidence` qui levait sur un document absent de la table figée
`OFFICIAL_DOWNLOAD_URLS` au lieu de descendre à l'autorité suivante.

## Le gate

`stable_release_order` porte **deux** contrôles d'unicité :

```python
keys = [(row["collection"], row["content_sha256"]) for row in rows]
if len(keys) != len(set(keys)):
    raise ValueError("release contains duplicate collection/content")
content = [row["content_sha256"] for row in rows]
if len(content) != len(set(content)):
    raise ValueError("release contains duplicate content")
```

Le premier est l'invariant réel : un même contenu ne peut pas être placé deux
fois dans la **même** collection.

**Le second interdit qu'un contenu apparaisse dans deux collections
différentes** — c'est-à-dire qu'il interdit le multi-placement.

## Ce que cela bloque, chiffré

| | |
|---|---|
| Documents | 2 389 |
| **En multi-placement** | **922** — 38,6 % |
| Placements totaux | **5 379** |

| Collections par document | Documents |
|---|---|
| 1 | 1 467 |
| 2 | 159 |
| 3 | 251 |
| 4 | 321 |
| 8 | 151 |
| 12 à 28 | 8 |

La release actuelle ne l'exerce pas : **26 placements pour 26 artefacts**.
L'invariant n'a donc jamais été éprouvé contre un corpus qui en a besoin.

## Pourquoi je m'arrête

Le mandat est explicite — « un artefact, plusieurs placements », et le corpus le
déclare lui-même : **2 956 affectations pour 2 451 documents**, dont 505 en
scopes multiples. Le multi-placement n'est pas une commodité, c'est la structure
du corpus.

Mais lever le second contrôle **retire un invariant d'unicité d'un producteur de
release scellée**. Ce n'est pas couvert par ADR-0053, qui autorisait une autorité
de fait de source — pas une modification de ce qu'une release peut contenir.

C'est un gate opérateur authentiquement nouveau, et je ne le franchis pas seul.

## Ce que la décision recouvre

Lever le contrôle demande de vérifier, et de décider :

1. **Que le reste de la chaîne supporte le multi-placement.** La contrainte
   d'unicité en base porte sur `(collection, source_sha256)` — vérifiée
   compatible. Mais `release_readiness` compte `unexpected_placements` et
   `missing_placements` : son comportement à 5 379 placements pour 2 389
   artefacts n'est pas éprouvé.
2. **Que l'invariant conservé soit le bon.** Le premier contrôle —
   `(collection, content)` unique — doit rester, et rester actif.
3. **Un ADR**, parce que la question « qu'est-ce qu'une release peut contenir »
   est la même famille que celle d'ADR-0045 sur la mutation des scopes.

## État livré

Tout ce qui précède le gate est écrit, vérifié et commité :

- **2 400 placements résolus**, 51 hors périmètre assumé, **11 en COVERAGE_GAP**
  — les 11 documents dont le seul niveau établi est `cycle3`, absent de l'enum
  `Niveau` et sans contenu dans le corpus ;
- **121 profils** valides au contrat, **0 refusé** ;
- **121 partitions** de matrice, 2 389 documents couverts ;
- l'autorité de provenance scellée et raccordée.

**L'ingestion n'a pas eu lieu.** Elle ne peut pas avoir lieu tant que la release
ne peut pas être produite, et la release ne peut pas être produite tant que ce
gate n'est pas tranché.
