# LOT 1 — mesure préalable : que dit le placement ?

> Question posée avant d'arrêter la forme du LOT 3 : le placement dit-il `public` ou
> `internal` pour les 8 324 chunks ? De la réponse dépend si la propagation est mécanique
> ou si une décision éditoriale est requise.

## La réponse : le placement dit `public`, sur les 486

```
profils de la livraison 319 — scope.visibility
   les onze ..................................... public

manifests de sujets scellés — occurrences de "visibility"
   dgemc 13 · hggsp_1re 39 · hggsp_T 35 · hlp_1re 116 · hlp_T 90
   nsi_1re 29 · nsi_T 47 · ses_1re 30 · ses_T 28 · svt_1re 21 · svt_T 38
   TOTAL 486 occurrences · 486 « public » · 0 « internal »
```

**Aucune décision éditoriale n'est requise : elle a été prise, elle est scellée, et elle
dit `public` sur chacun des 486 placements.**

## Pourquoi la base dit `internal`

```
governed_publisher_v2.py:201     "visibility": str(scope.visibility)
```

La colonne est écrite depuis le **scope du profil**, sans autre source. Et les profils
historiques, ceux avec lesquels l'ingestion a eu lieu, déclarent l'autre valeur :

```
ingestion_profiles/*_v1.yml            visibility: internal
ingestion_profiles/v2_livraison_319/*  visibility: public
ffc1bae, manifests de sujets           visibility: internal
release différée, manifests de sujets  visibility: public  (486/486)
```

Le corpus a été ingéré sous les profils `v1`, la release a ensuite scellé les profils
`319`, et **rien n'a propagé le changement**. La restriction de `110da50` — `student`
ramené à `("public",)` — s'est appliquée à une table restée sur l'ancienne valeur.

## Ce que la base contient exactement

```
                              déclaré par la release      en base
contenus distincts                       319                 319
placements                               486                 319
chunks                                12 403               8 324
```

Appartenance vérifiée dans les deux sens, pas seulement les totaux :

```
contenus en base non déclarés ................... 0
contenus déclarés absents de la base ............ 0
placements en base hors des placements déclarés . 0
placements déclarés absents de la base .......... 167
```

**La base est un sous-ensemble strict et cohérent de la release.** Rien d'étranger, rien
d'inventé : cent soixante-sept placements déclarés n'ont jamais été matérialisés.

## Le compte de 4 079, exact

```
chunks du PREMIER placement de chaque contenu ..... 8 324   = exactement la base
chunks des placements SUPPLÉMENTAIRES ............. 4 079   = exactement l'écart
                                                    ------
total déclaré ..................................... 12 403
```

Les 4 079 chunks manquants sont **les 167 placements d'un même document dans une seconde
collection**. Chaque contenu a été ingéré une fois ; ses placements suivants ne l'ont pas
été.

**Correction d'une rétractation.** Ce chiffre de 4 079 avait été annoncé au début de cet
audit, puis retiré parce que la cause avancée — un regroupement sur `rag_chunks.collection`
— était fausse. Le nombre, lui, était juste. **J'ai retiré la mesure en même temps que son
explication ; seule l'explication devait tomber.**

## Conséquence sur l'ordre des lots

L'artefact qui porte la décision d'ouverture est **la release différée**, celle qui n'est
pas dérivable de ses amonts. Le LOT 3 — propagation depuis le placement — ne peut donc pas
précéder la reproduction de cette release au LOT 1.2.

Autrement dit : **ce qui rend la plateforme utilisable par un élève est enfermé dans
l'artefact que nous avons mis de côté**, et le déverrouiller passe par le rectifier, non
par le contourner.
