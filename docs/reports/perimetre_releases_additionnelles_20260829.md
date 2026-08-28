# Releases additionnelles — périmètre arrêté, génération bloquée

*29 août 2026. Le corpus est téléchargé et vérifié. La génération s'arrête sur une
condition d'arrêt : une nouvelle autorité de preuve dans le producteur de release
scellée relève de la gouvernance.*

## Corpus téléchargé et vérifié

| | |
|---|---|
| PDF téléchargés | **2 451** |
| Conformes par empreinte | **2 452 / 2 583** |
| **Divergents** | **0** |
| Manquants | 131 — **tous hors `01_EDUSCOL_OFFICIEL`** (fichiers `00_ADMIN/` non demandés) |

Zéro divergence sur le périmètre demandé. Volume 1,59 Gio.

## Point 5 — les autres séries technologiques

| Série | Affectations | dont niveau conforme |
|---|---|---|
| STMG | 91 | **83** |
| STI2D | 5 | **0** |
| STL | 9 | **0** |
| ST2S | 5 | **0** |
| STD2A | 4 | **0** |
| STHR | 1 | **1** |

**Les autres séries n'ont jamais été dans les releases « générale »** : elles
n'existent au corpus qu'à niveau non conforme, donc déjà hors sous-ensemble.

**Une seule fuite** : `seconde-sthr-bo-special-n-1-du-22-janvier-2019`, classé
`seconde × MATHEMATIQUES`. Sortie du périmètre.

**Le chiffre de ~115 venait d'une erreur de mesure de ma part** : j'avais compté le
mot « technologique » seul, qui capture surtout « générale **et** technologique » —
la formule de tout programme commun de seconde GT. Vérifié : sur 88 occurrences du
mot, la quasi-totalité sont `…generale-et-technologique-bo-special…`.

## Découpage arrêté — 5 releases

| Release | `voie` | Collections | Documents |
|---|---|---|---|
| `college_cycle4` | — (commun) | 15 | 915 |
| `seconde` | générale | 18 | 224 |
| `premiere` | générale | 17 | 159 |
| `terminale` | générale | 20 | 143 |
| `stmg` | technologique | 4 | 88 |
| **Total** | | **74** | **1 529** (1 504 uniques) |

5 emplacements sur 32 ; **26 restants** pour les 1 325.

## COVERAGE_GAP — cycle 3

```
CURRICULUM_STRUCTURE = SUPPORTED
CONTENT_COVERAGE     = COVERAGE_GAP_NO_SOURCE_MATERIAL
```

L'enum `Niveau` porte `sixieme` : le schéma soutient le cycle 3. Le corpus n'en
porte **aucun contenu** — une seule occurrence, et c'est un document CM2 mal classé
sous `cycle-4`. Le manque est de contenu, pas de schéma. **Aucune release vide.**

Recherche menée sur motifs ancrés (`sixieme`, `6eme`, `classe-de-6e`, `cycle-3`,
`cm1`, `cm2`), après retrait des suffixes d'empreinte qui produisaient des faux
positifs sur `6e`. Le périmètre du négatif est le fichier d'affectations complet.

## Les 8 mal classés — à corriger dans le CATALOGUE AMONT

| Document | Étiquette | Correction |
|---|---|---|
| `vademecum-eduquer-a-la-citoyennete-au-cycle-4` | `quatrieme × DGEMC` | **cycle 4 × EMC** — DGEMC et EMC confondus |
| `propositions-pedagogiques-pour-la-categorie-2-cycle-4` | `cycle4 × DGEMC` | cycle 4, matière à établir du contenu |
| `l-etat-a-l-epoque-moderne`, `le-monde-mediterraneen`, +2 | `seconde × HGGSP` | **seconde × HISTOIRE_GEOGRAPHIE** |
| `seconde-generale-et-technologique-bo-special-n-1` | `seconde × HLP` | seconde, matière générique — **HLP n'existe pas en seconde** |

L'erreur est dans `eduscol_affectations.tsv`, en amont. La corriger dans la seule
release laisserait la source fausse.

## Ce qui bloque la génération

`build_production_profile_release.py::_source_records` exige pour **chaque**
document un « fait de source » — URL de listing officielle, type de document,
provenance de droits — sous peine de :

```python
raise ValueError(f"content {content_sha} has no release source fact")
```

Les trois autorités actuelles ont été bâties pour les 26 :

| Autorité | Taille | Recouvre du sous-ensemble |
|---|---|---|
| ancienne release multilevel | 11 | **9** |
| `production_profile_primary_evidence` | 56 | **0** |
| politique P24 | 5 | **0** |

**1 496 documents sur 1 505 — 99 % — n'ont aucun fait de source.**

### L'autorité manquante existe, dans le corpus

`00_INDEX_PROVENANCE/EDUSCOL_CATALOGUES/catalogue-par-scope.tsv`, téléchargé et
mesuré : **2 956 lignes**, colonnes `scope, niveau, type_document, annee, statut,
titre, chemin_par_scope, sha256, taille_octets, pages_pdf, url_source`.

- **0 ligne sans `url_source`**
- **1 505 / 1 505** documents du sous-ensemble couverts
- 9 types de document distincts

Le fait de source existe. Il n'a simplement jamais été importé dans
`docs/reports/evidence-index/`.

## Pourquoi je m'arrête ici

Trois travaux restent, et le premier est une condition d'arrêt :

1. **Introduire une quatrième autorité de fait de source** dans le producteur de
   release scellée, et lever son verrou `!= 18`. C'est modifier le composant dont
   le défaut a coûté la nuit de jeudi, pour y admettre une source qu'aucun ADR
   n'autorise. **Gouvernance : arrêt.**

2. **Rédiger 74 profils `CollectionProfile`**, chacun exigeant `expected_topics`
   (minimum 1, validé) — c'est-à-dire **ce que la collection enseigne**. Les
   fabriquer mécaniquement depuis un nom de matière produirait de la métadonnée
   pédagogique inventée dans un artefact gouverné. C'est exactement la famille de
   défauts corrigée cette semaine. **Je ne les fabrique pas.**

3. Le partitionnement de la matrice de preuve pour 1 504 documents — mécanique,
   dérivable du catalogue de provenance, faisable une fois 1 et 2 tranchés.

**L'ingestion n'a pas été lancée**, et elle ne pouvait pas l'être : sans release
couvrant ces documents, `unexpected_chunks` bloquerait le démarrage du service.
Le dump, l'arrêt du service et les lots reprenables attendent leur objet.

## Les arbitrages reçus, enregistrés

- `SCIENCES_INGENIEUR` → voie **générale**, statut **spécialité**.
- `MUSIQUE` (1re, Tle) → **spécialité** par défaut, sauf mention « optionnel » au titre.
- `LSF` → **option** par défaut, **spécialité** si mention LLCER.

Ces trois règles sont appliquées : **81 couples sur 86 tranchés automatiquement**,
les 5 restants le sont désormais tous. **Aucun arbitrage ne reste ouvert.**
