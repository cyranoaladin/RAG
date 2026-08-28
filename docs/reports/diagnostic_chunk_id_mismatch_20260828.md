# Chunk ID mismatch — cause établie, correctif prouvé

*28 août 2026. Ce défaut gate toute ingestion future.*

## Le symptôme

Rejouer l'ingestion gouvernée des 26 documents échoue au premier :

```
ValueError: Chunk ID mismatch at index 0 pour e591a87aee63…
```

`chunk_id = sha256(content_sha256 : index : sha256(texte))`. Le nombre de chunks
concordait — 44 attendus, 44 produits — donc seul le **texte** divergeait.

## L'élimination des hypothèses

| Hypothèse | Vérification | Verdict |
|---|---|---|
| PDF du miroir différent | sha256 du fichier | **identique** — écartée |
| Normalisation Unicode | `is_normalized('NFC')` des deux côtés | **NFC des deux** — écartée |
| Chunking divergent | 44 attendus / 44 produits | **écartée** |
| Extraction PDF | *voir ci-dessous* | **confirmée** |

## La divergence, au caractère

Le manifeste ne porte que l'empreinte du texte, pas le texte. La base canonique,
elle, porte le texte scellé — c'est là que la comparaison est possible.

```
index 246 :
  scellé  : 'Sommaire Préambule Visée de cet enseignement Structuration'
  produit : 'Sommaire Préambule Visée de cet enseigneme nt Structuration'
                                                    ↑
  scellé[246]  = U+006E LATIN SMALL LETTER N
  produit[246] = U+0020 SPACE
```

**Un espace parasite inséré au milieu d'un mot.** Longueurs : 892 scellés contre
894 produits — deux caractères de trop, deux espaces insérés.

## La cause

`extract_pdf_pages` appelle `pypdf`. Sur le même fichier, page 1 :

| Version | Texte extrait |
|---|---|
| **pypdf 4.2.0** (`rag-engine/.venv`) | `Visée de cet enseigneme nt Structuration…` |
| **pypdf 6.14.2** (`rag-pedago/.venv`) | `Visée de cet enseignement Structuration…` |
| **scellé en base** | `Visée de cet enseignement Structuration…` |

Le scellement a été produit avec **pypdf 6.14.2**. Le rejeu, depuis
`rag-engine/.venv`, tournait en **4.2.0**.

### Vérification concluante

Rejeu complet du document témoin sous pypdf 6.14.2 :

```
chunks attendus 44 / produits 44
chunk_id CONCORDANTS : 44/44
premier écart : aucun
```

**44 sur 44.** Ce n'est pas un accord sur un échantillon : c'est tout le
périmètre du document.

## Le défaut de fond

`services/rag-pedago/pyproject.toml` déclarait :

```toml
"pypdf>=4.0",
```

Une **contrainte ouverte** sur la bibliothèque qui détermine le texte extrait —
et donc les empreintes de contenu. Elle s'est résolue en 6.14.2 dans `rag-pedago`
et en 4.2.0 dans `rag-engine`, qui l'épinglait.

Le docstring d'`extract_pdf_pages` affirme :

> « Déterministe : deux exécutions sur les mêmes octets rendent la même liste, ce
> qui est la condition pour que le digest d'un chunk identifie un contenu plutôt
> qu'une exécution. »

**L'affirmation est vraie à version constante, et fausse en général.** Rien ne
figeait la version. Le digest identifiait donc « un contenu **et** une version de
pypdf », alors qu'il prétendait identifier un contenu.

C'est le même motif que le sceau qui attestait une liste sans vérifier qu'elle
couvrait ce que l'artefact déclarait : **un contrôle qui affirme plus qu'il n'a
vérifié.** Troisième occurrence de la frontière runtime/dépôt, après
`nexus-contracts` 0.14.0 figé dans l'image et `torch` en build CPU-only.

Celle-ci est la plus insidieuse des trois : elle ne casse rien, ne lève aucune
erreur, ne laisse aucune trace dans les journaux. Elle change silencieusement un
texte, donc une empreinte.

## Le correctif

| Fichier | Avant | Après |
|---|---|---|
| `rag-pedago/pyproject.toml` | `pypdf>=4.0` | **`pypdf==6.14.2`** |
| `requirements.ingestion-worker.txt` | `pypdf==4.2.0` | `pypdf==6.14.2` |
| `requirements.v2.txt` | `pypdf==4.2.0` | `pypdf==6.14.2` |
| `requirements.txt` | `pypdf==4.2.0` | `pypdf==6.14.2` |

`pypdf` rejoint `torch` dans les dépendances surveillées par
`check_runtime_conformance.py` : une divergence de version entre runtimes est
désormais un constat bloquant.

## Ce que cela débloque, et ce que cela ne débloque pas

**Débloqué** : l'ingestion gouvernée redevient reproductible. Les 2451 documents
peuvent être ingérés sans sceller de l'invérifiable.

**Non résolu, et à ne pas passer sous silence** : les 730 chunks actuellement en
base ont été produits par pypdf 6.14.2, et le sont donc légitimement. Mais aucune
vérification n'a été faite que **les 25 autres documents** concordent également.
Le contrôle a porté sur un document sur vingt-six.

**Un contrôle doit s'exercer sur tout son périmètre.** La vérification des 26 est
un préalable à l'ingestion des 2451, et elle n'est pas faite ici — elle demande
un rejeu complet, qui est exactement l'opération que le correctif rend possible.

## Vérification sur le périmètre complet — 26/26

Le premier contrôle ne portait que sur un document. Un contrôle doit s'exercer
sur tout son périmètre ; celui-ci balaie les vingt-six, sous pypdf 6.14.2 :

```
artefacts scellés : 26   PDF au miroir : 26
concordants : 26/26
résistants  : 0
PDF absents : 0
```

**Aucun document ne résiste.** Le correctif est validé sur l'intégralité du
corpus servi, et non par extrapolation depuis un cas.
