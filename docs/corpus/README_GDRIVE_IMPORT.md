<!--
Copie versionnée du README racine du corpus Drive `NEXUS_RAG_GDRIVE_READY`
(dossier Drive du corpus, identifiant et compte propriétaire tenus hors
dépôt). Déposée dans le dépôt le 28/08/2026 : elle
documente la structure du corpus source, les zones à ne pas ingérer, la
déduplication par SHA-256 et les autorités de vérification — informations
dont aucune copie n'existait ici, et dont dépend toute reconstruction du
miroir PDF (cf. docs/runbooks/release_reseal.md).

Document d'origine, non modifié. Le corpus fait autorité sur son propre
contenu : en cas de divergence, c'est ce fichier tel qu'il vit dans Drive
qui prime.
-->

# NEXUS_RAG_GDRIVE_READY

État final préparé le : 2026-08-08T10:40:00.012780+00:00

Corpus documentaire organisé pour être téléversé sur Google Drive et servir de base au RAG de Nexus Réussite.

## 1. Structure principale

### `01_EDUSCOL_OFFICIEL/`

Corpus institutionnel Éduscol principal.

- **2451 PDF**
- **2451 SHA-256 uniques**
- aucune duplication physique dans cette zone
- aucune ressource du catalogue Éduscol manquante

Le catalogue source comptabilise :

- 2 956 affectations documentaires ;
- 2 451 documents PDF uniques ;
- 505 affectations supplémentaires correspondant à des documents apparaissant dans plusieurs niveaux, matières ou scopes.

Lorsqu'un même PDF concerne plusieurs collections, une seule copie canonique est conservée. Les différentes affectations sont documentées dans :

`00_ADMIN/eduscol_affectations.tsv`

### `02_NEXUS_DIAGNOSTICS/`

Banques, tests, exports et ressources de diagnostic Nexus.

- **38 fichiers**
- **19 PDF**
- **17 YAML**

Cette zone doit être ingérée de manière sélective selon le cas d'usage. Elle ne doit pas être fusionnée aveuglément avec le corpus institutionnel.

### `03_RESSOURCES_INTERACTIVES/`

Ressources GeoGebra dédupliquées.

- **37 fichiers `.ggb` uniques**

### `04_COMPLEMENTS_PEDAGOGIQUES/`

Compléments pédagogiques qui ne font pas partie du corpus principal récolté par le harvester Éduscol.

État final : **3 PDF**.

Ils sont séparés par provenance :

- `01_SOURCES_INSTITUTIONNELLES/` — ressources DEPP officielles complémentaires ;
- `02_RESSOURCES_AUTEUR_NEXUS/` — productions pédagogiques d'auteur clairement distinguées des références institutionnelles.

## 2. Zones de gestion — ne pas ingérer automatiquement

### `00_ADMIN/`

Administration, validations, audits, manifestes et exclusions.

Cette zone n'est **pas destinée à l'ingestion pédagogique globale**.

Les fichiers volontairement écartés du corpus actif se trouvent sous :

`00_ADMIN/EXCLUSIONS_HORS_CORPUS/`

État actuel : **3 fichiers exclus**.

Ces exclusions comprennent notamment :

- documents d'information destinés aux familles ;
- variantes historiques ou doublons non canoniques ;
- fichiers sans contenu pédagogique exploitable.

### `00_INDEX_PROVENANCE/`

Catalogues, métadonnées et éléments de provenance.

Cette zone sert à la traçabilité, au routage et à la vérification du corpus. Elle ne doit pas être traitée comme une collection pédagogique ordinaire.

## 3. Statuts des ressources transversales lycée

Les documents lycée non rattachables de manière fiable à un niveau unique ont été regroupés dans :

`01_EDUSCOL_OFFICIEL/LYCEE/TRANSVERSAL_MULTI_NIVEAUX/`

Ils sont distingués selon le statut issu du catalogue :

- `10_ACTUEL_CONFIRME/`
- `20_TRANSITION_OU_ACTUEL/`
- `80_A_VERIFIER/`
- `90_ARCHIVE_CATALOGUE/`
- `99_CONFLITS_STATUTS/`

Important :

- `80_A_VERIFIER` signifie que le statut réglementaire n'a pas été suffisamment établi pour automatiser une décision ;
- `90_ARCHIVE_CATALOGUE` ne signifie pas que le document doit être supprimé ;
- aucune ressource n'a été éliminée uniquement en raison de son ancienneté.

## 4. Déduplication

La déduplication est fondée sur **SHA-256**, pas uniquement sur les noms de fichiers.

Pour Éduscol :

- 2 451 documents uniques ;
- 2 451 PDF physiques dans `01_EDUSCOL_OFFICIEL/` ;
- 0 PDF manquant par rapport au catalogue ;
- 0 SHA supplémentaire ;
- 0 doublon physique.

Les suffixes de hash présents dans de nombreux noms de fichiers participent à la traçabilité et doivent être conservés.

## 5. Règles d'ingestion RAG recommandées

### Ingestion principale

`01_EDUSCOL_OFFICIEL/`

Utiliser les métadonnées de provenance et les affectations pour indexer un même document dans plusieurs collections logiques sans multiplier les copies physiques.

### Ingestion Nexus contrôlée

`02_NEXUS_DIAGNOSTICS/`

Utiliser seulement les banques ou documents validés correspondant au workflow concerné. Les ressources marquées `DRAFT` ne doivent pas être assimilées à des références pédagogiques validées.

### Ressources interactives

`03_RESSOURCES_INTERACTIVES/`

Les `.ggb` nécessitent un traitement spécifique ; ils ne doivent pas être assimilés directement à des PDF textuels.

### Compléments

`04_COMPLEMENTS_PEDAGOGIQUES/`

Conserver explicitement la distinction entre :

- sources institutionnelles ;
- productions Nexus / ressources d'auteur.

### Ne pas ingérer globalement

- `00_ADMIN/`
- `00_INDEX_PROVENANCE/`

## 6. Traçabilité

Les principales preuves et informations de contrôle se trouvent notamment dans :

- `00_ADMIN/SHA256SUMS.txt`
- `00_ADMIN/TREE.txt`
- `00_ADMIN/eduscol_affectations.tsv`
- `00_ADMIN/RECLASSEMENT_NON_CLASSE/`
- `00_ADMIN/HARMONISATION_TRANSVERSAL_360/`
- `00_ADMIN/RECLASSEMENT_COMPLEMENTS_PEDAGOGIQUES/`
- `00_ADMIN/EXCLUSIONS_HORS_CORPUS/`

Le manifeste `SHA256SUMS.txt` doit être régénéré après la présente mise à jour du README avant le téléversement définitif sur Google Drive.

## 7. État final avant scellement

- Corpus Éduscol : **2 451 / 2 451 documents uniques présents**
- GeoGebra : **37 ressources uniques**
- Compléments pédagogiques : **3 PDF**
- Symlinks : **0**
- `99_A_CLASSER` : **absent**
- `90_TRANSVERSAL_A_RECLASSER` : **absent**
- aucune zone provisoire de classement restante

Le fichier `README_GDRIVE_IMPORT.md` à la racine est **intentionnel** : il constitue le mode d'emploi du corpus et doit être conservé lors du téléversement sur Google Drive.
