# Le bloqueur `PROGRAM_INCOMPATIBLE_IN_SERVABLE_SET` — constat et résolution

Le compteur valait 1. Il vaut désormais 0, et **pas parce que quelque chose a été
effacé** : parce qu'il mesure enfin ce que son nom annonce.

## L'objet, nommé

```
content_sha256 = de42e9816d7d012fd5d6b3349171cf43dd038c1e50fa0fe9e664bcc8521194b9
scope_level    = troisieme          matiere = technologie
cited_reference             = BOEN_31_2020-07-30
authority_current_references = BOEN_9_2024-02-29
attribution_basis           = MULTI_SCOPE_EXPLICIT_SECTION
authority_evidence_status   = VERIFIED_OFFICIAL_BY_COMMANDITAIRE
```

Ligne de matrice :

```
program      = INCOMPATIBLE_PROVEN
verdict      = REFUSED_PROGRAM_INCOMPATIBLE
pii          = PII_CLEARED_OR_NOT_SCANNED
provenance   = URL_EVIDENCE_FOUND
indexability = INDEXABLE
currentness  = TRANSITION_OR_CURRENT
source_role  = INSTITUTIONAL_PUBLICATION
```

Son verdict est **refusé**. Il n'est pas servi.

## Le défaut du compteur

Le gate lisait :

```python
matrice["by_verdict"].get("REFUSED_PROGRAM_INCOMPATIBLE", 0)
```

`by_verdict` est un histogramme de **toute la population** : ses valeurs
totalisent les 2530 lignes. Le compteur comptait donc, comme étant « dans le
périmètre servable », un contenu que la matrice **refuse** — ce que son propre
verdict dit en toutes lettres.

Le nom promettait une portée que le calcul n'avait pas.

## Ce qui a été mesuré avant de conclure

| Mesure | Valeur |
| --- | ---: |
| Contenus prouvés incompatibles | 1 |
| Refusés par la matrice | 1 |
| Encore candidats dans la matrice | 0 |
| Présents dans l'arbre de release | 0 |
| Empreintes distinctes dans l'arbre de release | 21 241 |
| Fichiers de release parcourus | 77 |

L'objet est absent des 21 241 contenus que portent les artefacts de release.
Rien ne le promeut.

## Pourquoi ne pas compter simplement « incompatible ∩ candidat »

Parce que ce serait vide de sens. La cascade de la matrice place le programme en
**première** marche : un contenu prouvé incompatible est refusé avant tout autre
examen. L'intersection avec les candidats est donc structurellement nulle, et une
mesure qui ne peut jamais être non nulle ne protège rien.

Ce qui peut réellement mal tourner, c'est qu'une release **matérialisée**
contienne un contenu prouvé incompatible. C'est cela qui se mesure maintenant.

## Ce que le gate compte désormais

```
program_incompatible_in_servable_set  = incompatibles ∩ ensemble promu   (bloquant)
program_incompatible_total            = incompatibles                    (informatif)
program_incompatible_refused_by_matrix                                   (informatif)
promoted_content_set_size, promoted_release_files_scanned                (traçabilité)
```

Les deux compteurs informatifs existent pour que **le fait reste visible**. Le
faire disparaître du rapport parce qu'il ne bloque plus reviendrait à le
maquiller.

## Deux épreuves, dans les deux sens

| Épreuve | Ce qu'elle tient |
| --- | --- |
| `test_un_incompatible_absent_des_releases_ne_bloque_pas` | un incompatible que rien ne promeut ne bloque pas |
| `test_un_programme_incompatible_PROMU_bloque` | une release qui contient un incompatible **bloque** |

Sans la seconde, le compteur corrigé serait une mesure qui ne peut pas alerter.

## Ce que ce lot n'a pas fait

Le verdict de l'objet est inchangé. Il n'est retiré ni de l'historique, ni de la
comptabilité des 2530, où il reste `REFUSED_PROGRAM_INCOMPATIBLE`. Aucune
exclusion gouvernée n'a été prononcée, et aucune liaison de programme n'a été
corrigée : rien ne le justifiait, puisque l'objet n'est promu nulle part.

Si une release future devait l'inclure, le gate le refuserait — et c'est
désormais éprouvé.

## Ce qui reste à décider par un humain

L'objet est prouvé incompatible avec l'autorité courante de son périmètre. Le
jour où une release voudra l'inclure, deux voies seulement : l'exclure
explicitement, ou corriger sa liaison de périmètre sur preuve. Corriger sa
vérité pour faire passer le gate n'en est pas une.
