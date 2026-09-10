# LOT — Les 57 objets non-PDF du plan de données

## Pourquoi ils ne sont pas un reliquat

« Tout le Drive » n'est pas « tous les PDF ». Le plan de données compte 2530
objets, dont 57 ne sont pas des PDF. Les traiter après coup les aurait laissés
dans l'angle mort où un compte se déclare complet en ayant choisi ce qu'il
compte.

```
DRIVE_DISCOVERED   2580
CONTROL_PLANE        50
DATA_PLANE         2530  =  PDF 2473  +  NON_PDF 57
```

## Ce qui a été mesuré

Les 57 objets ont été **récupérés** — 6,6 Mo — et hachés :

```
NON_PDF_TOTAL        57
NON_PDF_FETCHED      57
NON_PDF_UNACCOUNTED   0

empreintes distinctes  57 / 57      (aucun doublon de contenu)
taille annoncée == récupérée        (aucune troncature)
```

| Disposition | Objets |
|---|---|
| `INTERACTIVE_RESOURCE_SERVABLE` | 37 |
| `DIAGNOSTIC_QUESTION_BANK_NON_INDEXABLE` | 19 |
| `OPERATIONAL_DOCUMENTATION_NON_INDEXABLE` | 1 |

Le détail objet par objet — `drive_file_id`, chemin, mime, taille,
`content_sha256`, zone, classification, disposition et raison — est dans
`lot_full_drive_non_pdf_dispositions.json`.

## Les 37 GeoGebra

Tous dans `03_RESSOURCES_INTERACTIVES`, tous servables. Un `.ggb` est une
**archive**, pas un document : rien n'y est exécuté, aucune référence externe
n'est suivie, et rien n'est extrait sur disque — les métadonnées sûres sont
lues en mémoire.

Bornes appliquées avant toute ouverture, chacune disant ce qu'une ressource
légitime ne dépasse jamais : archive ≤ 16 Mio, ≤ 200 membres, ≤ 64 Mio
décompressés. Sont refusés en outre le membre évadé, le membre absolu et le
membre en lien symbolique.

**Un défaut de mon propre garde, trouvé sur les données réelles.** Une archive
du corpus porte des noms de membres à **antislash**
(`220194da…\PointDistantSurCercleIcon32x32.png`) : les archives créées sous
Windows l'emploient comme séparateur. Mon contrôle de traversée ne découpait
que sur `/` — `..\..\cible` y échappait, alors que l'outil d'extraction de la
plateforme d'origine, lui, l'interpréterait. Le contrôle normalise désormais
les deux séparateurs, et refuse aussi le préfixe de lecteur (`C:\`).

Vérifié par sabotage : membre `../evil.png`, `..\..\evil.png`, `/etc/passwd`,
`C:\evil.png` et une archive de 250 membres sont refusés ; un antislash
**légitime** dans un nom de fichier d'icône passe.

Mesures des 37 archives : lecture `OK` sur les 37, de 5 à 23 membres, 34
déclarent `app=classic`, 11 versions GeoGebra distinctes (`5.0.205.0` à
`5.0.573.0`). Trois n'exposent ni `app` ni `version` — leur `geogebra.xml` est
présent et haché, mais sa racine ne porte pas ces attributs : c'est une
variation de format ancienne, pas une anomalie.

**Serving.** Une ressource GeoGebra peut être rendue comme
`type_document=INTERACTIVE_RESOURCE`, `provider=GeoGebra`, avec son
localisateur et sa provenance. Le moteur n'a pas à prétendre que le `.ggb` est
un document textuel : aucun texte n'en est extrait, et son identité reste son
`content_sha256`.

## Les 20 autres

| Mime | Objets | Zone |
|---|---|---|
| `application/yaml` | 17 | `02_NEXUS_DIAGNOSTICS/*/02_BANQUES_SOURCE/` |
| `application/json` | 1 | idem |
| `text/markdown` | 1 | `02_NEXUS_DIAGNOSTICS/99_A_CLASSER/03_DOCUMENTATION/` |
| `text/markdown` | 1 | `README_GDRIVE_IMPORT.md` (racine) |

Les 19 premiers sont des **banques de questions de diagnostic** — la donnée
source d'une autre surface produit, pas des documents qui enseignent. Les
indexer ferait entrer dans le corpus de retrieval des énoncés d'évaluation
dont la vocation est d'être servis par un autre chemin.

Le dernier est la documentation d'import du Drive : opérationnelle, sans
contenu pédagogique.

Aucun des 20 n'est un défaut, et aucun n'est ignoré : chacun porte sa
disposition et sa raison.
