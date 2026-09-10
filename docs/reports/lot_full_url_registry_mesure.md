# FULL_URL_REGISTRY — mesure de couverture avant construction

> `content_sha256`, `drive_file_id`, comptes. Aucune matière.

## 1. Ce que `source_url` est réellement

Dans `release_readiness.py`, `source_url` est un champ **obligatoire et non
vide** de chaque artefact d'un manifeste de release. Les manifestes existants
le renseignent avec l'**URL institutionnelle de publication** — par exemple une
page `eduscol.education.gouv.fr` — et non avec un localisateur de stockage.

C'est la bonne définition : une citation doit pouvoir pointer vers l'autorité
qui publie, pas vers le disque qui héberge. Un lien Drive dérivé du
`drive_file_id` satisferait le schéma en trahissant son intention.

## 2. Couverture mesurée sur le plan de données complet

Toutes les paires `(content_sha256, source_url)` déclarées dans le dépôt ont
été relevées, puis confrontées aux empreintes réelles du corpus.

```
FULL_URL_REGISTRY_TARGET=2530
FULL_URL_REGISTRY_COVERED=328
FULL_URL_UNACCOUNTED=2202

PDF_TOTAL=2473        PDF_ON_DISK=2473
PDF_WITH_SOURCE_URL=328
PDF_WITHOUT_SOURCE_URL=2145

NON_PDF_TOTAL=57      NON_PDF_ON_DISK=0
NON_PDF_WITH_SOURCE_URL=0

CONTROL_PLANE_TOTAL=50  CONTROL_PLANE_ON_DISK=0
```

Les 328 couverts viennent des manifestes de la lignée `prerentree_2026_2027`
— c'est-à-dire du périmètre historique, pas du corpus complet.

## 3. Pourquoi ce n'est pas dérivable ici

Le corpus local ne contient que les **2473 PDF**. Les 57 non-PDF et les
**50 objets du plan de contrôle** (`00_ADMIN/…`) ont été inventoriés sur Drive
sans jamais être conservés localement. Si une provenance d'URL a été enregistrée
au téléchargement, elle est dans ces objets-là.

Les noms de fichiers portent des slugs Eduscol avec un suffixe hexadécimal qui
ressemble fortement à un identifiant de document. **Dériver une URL de ce motif
serait une fabrication** : elle aurait la forme d'une preuve sans en être une,
et un lecteur ne pourrait pas distinguer une URL relevée d'une URL devinée.

```
BLOCKER=DRIVE_ACCESS_REQUIRED
```

## 4. Ce qu'il faut pour lever le blocage

Par ordre de préférence :

1. **Récupérer les 50 objets du plan de contrôle** et y chercher la provenance
   (`00_ADMIN/BUILD_INFO.json`, les TSV d'harmonisation). Si elle y est, le
   registre se construit par relevé, pas par déduction.
2. À défaut, **une campagne de résolution gouvernée** : pour chaque document,
   confronter son empreinte à la ressource publiée par l'institution, et ne
   retenir l'URL que si les octets correspondent. Une URL qui ne rend pas les
   mêmes octets n'est pas la source de ce document.
3. En dernier recours, déclarer explicitement les documents sans URL
   institutionnelle comme tels — plutôt que de leur en inventer une.

## 5. Les 57 non-PDF — disposition consolidée

```
NON_PDF_TOTAL=57            NON_PDF_ENTRIES=57
NON_PDF_DISTINCT_CONTENTS=57  NON_PDF_DISTINCT_DRIVE_IDS=57
NON_PDF_BYTES_ACTUALLY_FETCHED=57   NON_PDF_SIZE_MISMATCH=0
NON_PDF_WITHOUT_SHA=0       NON_PDF_UNACCOUNTED=0

INTERACTIVE_RESOURCE_SERVABLE=37          (application/x-zip — GeoGebra)
DIAGNOSTIC_QUESTION_BANK_NON_INDEXABLE=19 (yaml/json)
OPERATIONAL_DOCUMENTATION_NON_INDEXABLE=1 (markdown)
```

`size_fetched == size` sur les 57 : l'empreinte vient des **octets lus**, pas
d'une taille annoncée par l'API Drive. C'est ce qui distingue une disposition
prise sur le contenu d'une disposition prise sur une fiche.

`NON_PDF_LOCAL_COPY_RETAINED=0` : les octets ont été lus puis relâchés. Pour
entrer dans une release servable, les 37 ressources interactives devront être
re-récupérées et re-confrontées à leur empreinte — leur disposition est
établie, leur matière ne l'est plus.

## 6. Comptabilité inchangée

```
DRIVE_DISCOVERED=2580   CONTROL_PLANE=50
DATA_PLANE_TOTAL=2530   DATA_PLANE_ACCOUNTED=2530   DRIVE_UNACCOUNTED=0
```

Comptabiliser n'est pas servir : `FULL_URL_UNACCOUNTED=2202` porte sur le
registre d'URL, pas sur la comptabilité du corpus, qui reste exacte.
