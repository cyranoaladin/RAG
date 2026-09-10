# Demandes adressées au canal Drive — 2026-09-07

> Tables sanitisées : `content_sha256`, `drive_file_id`, `drive_path`, tailles,
> classes de verdict, numéros de page. Aucune matière, aucun texte.

Cette session n'atteint pas le Drive ; le canal commanditaire l'atteint. Ces
tables existent pour que ce qui manque soit **demandé**, pas déclaré absent.

**Aucune URL n'est dérivée d'un slug de nom de fichier.** Une URL devinée
aurait la forme d'une preuve sans en être une, et un lecteur ne pourrait plus
distinguer une URL relevée d'une URL fabriquée.

## 1. `drive_url_provenance_handoff.json`

Une ligne par objet du plan de données — **2530**, aucune sans
`content_sha256`.

### Commencez par la demande prioritaire

La zone `00_INDEX_PROVENANCE` porte **20 objets, 10 022 282 octets**, jamais
téléchargés. Parmi eux :

| Objet | Taille | Ce qu'il porte probablement |
|---|---|---|
| `EDUSCOL_CATALOGUES/catalogue-complet.csv` / `.tsv` | 2,46 Mo | le catalogue source, vraisemblablement avec les URL |
| `EDUSCOL_MANIFESTES/corpus.sha256` | 450 Ko | les empreintes du corpus — de quoi **joindre** catalogue et documents |
| `EDUSCOL_MANIFESTES/par-{niveau,scope}-manifeste.tsv` | 1,7 Mo | la même chose, découpée |
| `EDUSCOL_RUN/DERNIER-RUN-COMPLET.txt` | 95 o | quel run a produit ces exports |

Lire ces vingt fichiers d'abord peut résoudre des milliers de lignes d'un coup.
Les 2202 recherches unitaires ne sont le bon outil que si ces index ne portent
pas la réponse.

`corpus.sha256` est la pièce décisive : il permet de rattacher une URL de
catalogue à une **empreinte**, donc de prouver que l'URL désigne bien ce
document — au lieu de le supposer par le nom.

### État actuel, avant interrogation

```
DATA_PLANE_TOTAL=2530                       CONTROL_PLANE_TOTAL=50
FULL_URL_LOOKUP_REQUESTS=2530
URL_KNOWN_FROM_LOCAL_EVIDENCE=328           (manifestes de la lignée historique)
FULL_URL_UNACCOUNTED_AFTER_LOCAL_EVIDENCE=2202

required_provenance_lookup :
  DRIVE_PROVENANCE_INDEX=2202       aucune évidence locale
  URL_CURRENCY_CONFIRMATION=328     URL connue, actualité non prouvée

source_role :
  INSTITUTIONAL_PUBLICATION=2451    AUTHOR_DIAGNOSTIC=38
  AUTHOR_INTERACTIVE_RESOURCE=37    AUTHOR_COMPLEMENT=3
  OPERATIONAL_DOCUMENTATION=1

serving_relevance : INDEXABLE=2510   NON_INDEXABLE=20
```

`serving_relevance` est indicatif : un document non indexable n'aura pas de
citation à porter et pourra légitimement finir `NOT_APPLICABLE` — mais c'est
une **disposition**, pas une déduction de l'outil, et elle vous revient.

### Catégories terminales

```
VERIFIED_CURRENT   UNVERIFIABLE_WITH_EVIDENCE   NO_URL_EVIDENCE
NOT_APPLICABLE     ERROR
```

Chaque relation doit y aboutir, pour `FULL_URL_UNACCOUNTED=0`.
`NO_URL_EVIDENCE` **n'est pas** `VERIFIED_CURRENT` : c'est un constat
d'absence prouvé, pas une URL.

## 2. `non_pdf_reacquisition_manifest.json`

Les **57** objets non-PDF, avec leur taille et leur empreinte **attendues** —
relevées sur les octets au moment de la disposition, jamais sur une taille
annoncée par l'API. La récupération se vérifie donc au lieu de se croire.

```
NON_PDF_REQUESTS=57       drive_file_id distincts=57
attendu après récupération :
  REACQUIRED_NON_PDF=57   SIZE_MISMATCH=0   SHA256_MISMATCH=0
  NON_PDF_UNACCOUNTED=0
```

Pour les 37 `.ggb` : le SHA du **fichier physique** reste l'identité de source.
Une extraction de `geogebra.xml` destinée à devenir recherchable passe ensuite
le gate PII. Aucune exécution de macro ni de script ; protections zip bomb,
path traversal, lien symbolique et XXE conservées.

## 3. `not_assessable_source_lookup.json`

Les **9** documents dont une page reste illisible après extraction native
**et** après OCR canonique — **15 pages** au total.

Aucun texte n'y figure : la page concernée est précisément celle que personne
n'a su lire.

```
NOT_ASSESSABLE_SOURCE_REQUESTS=9
disposition intérimaire : GOVERNED_NOT_SERVABLE
blocker_codes = ["PII_NOT_ASSESSABLE", "SOURCE_EXTRACTION_INCOMPLETE"]
```

Une source alternative doit être gouvernée et tracée : le PDF existant n'est
jamais remplacé en silence. Si une source réparée apparaît, l'artefact
d'origine est conservé et le nouveau porte sa propre empreinte, sa propre
preuve de traitement, sa propre disposition PII et un lien de succession.

## 4. Reproductibilité

Ces tables sont produites par
`services/rag-pedago/scripts/preparer_handoff_drive.py`, versionné. Elles se
régénèrent à l'identique depuis l'inventaire, le corpus et le rapport de la
campagne V2.
