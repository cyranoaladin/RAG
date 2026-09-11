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

| Mesure | Valeur | Source |
| --- | ---: | --- |
| Contenus prouvés incompatibles | 1 | matrice de servabilité |
| Refusés par la matrice | 1 | matrice de servabilité |
| Encore candidats dans la matrice | 0 | matrice de servabilité |
| Contenus réellement promus | 319 | autorité canonique |
| Incompatibles parmi les promus | 0 | intersection |

```
promoted_content_set_source   = scripts/qualification/compute_promoted_content_set.py
promoted_content_set_sha256   = d06d6051e7037372acf4dca4675a1c999c198129433d68491221a9d03bb821cd
release_authority_mechanism   = REGISTRY_FILE
release_registry_source       = DEFAULT
```

L'objet est absent des 319 contenus que la lignée canonique sert. Rien ne le
promeut.

## Une première mesure était fausse, et il faut le dire

La version initiale de cette correction définissait l'ensemble promu par un
**balayage de fichiers** : tous les JSON sous `data/releases`, et toute chaîne
de 64 caractères hexadécimaux retenue comme un contenu.

Elle trouvait **20 739** empreintes là où l'autorité canonique en compte
**319**. Elle ramassait des empreintes d'arbres git, de modèles d'embedding, de
manifestes — tout ce qui a la *forme* d'un sha256 sans en avoir le *rôle*. Une
union de digests techniques n'est pas un ensemble de contenus servis, et
conclure d'une coïncidence de format est un raisonnement faux même quand il
donne le bon résultat.

Elle rendait de surcroît un ensemble **vide** quand la racine manquait, ce qui
transformait « je ne sais pas » en « rien n'est promu » — un faux zéro dans un
compteur de sécurité.

Deux mesures incohérentes coexistaient d'ailleurs dans les artefacts, 77
fichiers contre 41, selon la racine depuis laquelle on balayait. Une source de
vérité qui dépend du répertoire courant n'en est pas une.

L'ensemble promu vient désormais de `compute_promoted_content_set.py`, qui passe
par `select_release_authority` et le contrat de release — le même chemin que le
runtime. Tout refus de cette autorité remonte comme un refus, jamais comme un
ensemble vide.

## Pourquoi ne pas compter simplement « incompatible ∩ candidat »

Parce que ce serait vide de sens. La cascade de la matrice place le programme en
**première** marche : un contenu prouvé incompatible est refusé avant tout autre
examen. L'intersection avec les candidats est donc structurellement nulle, et une
mesure qui ne peut jamais être non nulle ne protège rien.

Ce qui peut réellement mal tourner, c'est qu'une release **matérialisée**
contienne un contenu prouvé incompatible. C'est cela qui se mesure maintenant.

## Ce que le gate compte désormais

```
program_incompatible_in_servable_set  = incompatibles ∩ ensemble promu canonique  (bloquant)
program_incompatible_total            = incompatibles                             (informatif)
program_incompatible_refused_by_matrix                                            (informatif)
promoted_content_set_source, _sha256, _size                                       (traçabilité)
promoted_release_authority_mechanism, promoted_release_registry_source            (traçabilité)
```

Le gate ne balaie aucun fichier de release et ne redéfinit pas ce qu'est une
empreinte de contenu. Une épreuve le vérifie sur le corps de la fonction.

Les deux compteurs informatifs existent pour que **le fait reste visible**. Le
faire disparaître du rapport parce qu'il ne bloque plus reviendrait à le
maquiller.

## Deux épreuves, dans les deux sens

| Épreuve | Ce qu'elle tient |
| --- | --- |
| `test_un_incompatible_absent_du_set_promu_ne_bloque_pas` | un incompatible que rien ne promeut ne bloque pas |
| `test_un_incompatible_PROMU_par_l_autorite_canonique_bloque` | un incompatible promu **bloque** |
| `test_une_empreinte_technique_dans_un_json_de_release_ne_bloque_pas` | une empreinte technique n'est pas un contenu |
| `test_un_calculateur_canonique_absent_est_un_refus` | ne pas savoir n'est pas « rien n'est promu » |
| `test_un_refus_du_calculateur_canonique_remonte` | un refus n'est jamais un ensemble vide |
| `test_un_ensemble_promu_vide_est_refuse` | comparer au vide serait vrai par vacuité |

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
