# P0, le bandeau éditeur — couverture 41,9 %, condition d'arrêt atteinte

*29 août 2026.*

## La couverture

| | Documents | |
|---|---|---|
| Corpus | 2 451 | |
| **Avec bandeau** | **1 027** | **41,9 %** |
| Sans bandeau | 1 424 | 58,1 % |

**Le bandeau est absent de la majorité du corpus.** C'est la condition d'arrêt
posée, et je m'y tiens.

### Le négatif est vérifié, pas supposé

Douze documents « sans bandeau » tirés au hasard et relus : **aucun ne porte le
bandeau**. Ils relèvent d'une collection Éduscol antérieure —
« Informer et accompagner les professionnels de l'éducation » — dont l'en-tête
porte la **discipline** et le **thème**, jamais le niveau :

```
FRANÇAIS
Se chercher, se construire
Informer et accompagner
```

Ce n'est donc pas mon motif qui est trop étroit. La leçon de l'accent manquant
sur « BO spécial » a été appliquée : le négatif a été éprouvé avant d'être déclaré.

## Ce que le bandeau apporte là où il existe

Sur les 759 documents dont le bandeau donne un **niveau exact** :

| | |
|---|---|
| **Catalogue contredit par l'éditeur** | **549 / 759 = 72,3 %** |

Décomposition :

| Catalogue | Bandeau éditeur | Documents | Nature |
|---|---|---|---|
| `non-classe` | premiere / terminale / seconde | **225** | **gain net** |
| `multi-niveaux` | premiere / terminale / seconde | **221** | **gain net** |
| `seconde` | **terminale** | 39 | **erreur du catalogue** |
| `terminale` | **premiere** | 24 | **erreur du catalogue** |
| `seconde` | **premiere** | 20 | **erreur du catalogue** |
| `terminale` | **seconde** | 12 | **erreur du catalogue** |
| … | | | |

**446 documents qui étaient non classés ou multi-niveaux reçoivent un niveau
exact**, et **103 erreurs franches du catalogue sont corrigées** — chacune avec
l'extrait du bandeau en preuve.

Corrections enregistrées : `docs/reports/evidence-index/catalogue_corrige_par_bandeau.json`.

Le champ `level` du catalogue est donc faux, ou indéterminé, sur près de trois
quarts des documents où l'éditeur s'est prononcé. **La décision de faire du
bandeau la référence est confirmée par la mesure**, et elle invalide
rétroactivement tout accord calculé contre le catalogue.

## Granularité des portées obtenues

| Granularité | Documents |
|---|---|
| `niveau_exact` | **759** |
| `cycle` | **232** |
| `transversal_lycee` | 36 |
| aucune | 1 424 |

## Ce qui reste possible sur les 58 % sans bandeau

Ils ne sont pas muets. Leur en-tête porte **la discipline** (`FRANÇAIS`,
`ScienceS de la vie et de la terre`, `Chinois`) et souvent **le thème de
programme** — « Se chercher, se construire », « Regarder le monde, inventer des
mondes » — qui sont des intitulés du programme **de cycle 4**.

L'élargissement de portée que vous avez défini s'y applique donc : discipline
établie, cycle déductible du thème, niveau inconnu → **transversal de la
discipline au cycle**. Cela ne demande pas de deviner, cela demande une table
thème → cycle, dérivable des programmes eux-mêmes.

**Je ne l'ai pas fait** : la condition d'arrêt porte sur la couverture du
bandeau, et elle est atteinte.

## Acquisition Éduscol — refus confirmé, hors User-Agent

| En-tête | Réponse |
|---|---|
| `Mozilla/5.0 … Chrome/126.0` | **403** |
| `curl/8.5.0` | **403** |

Ce n'est pas un filtrage sur le `User-Agent`. Le refus est plus robuste, et je ne
cherche pas à le contourner.

`expected_topics` **n'accepte pas de liste vide** : `min_length=1` plus un
validateur qui rejette les entrées vides (remédiation PR#90 — une chaîne vide
ferait accepter n'importe quel document comme conforme à la matière).

Un repli est donc implémenté : dériver les thèmes des **titres des documents que
la collection possède déjà**. Ce sont des intitulés Éduscol réels — « Les climats
de la Terre : comprendre le passé pour agir aujourd'hui et demain » — décrivant le
contenu effectivement servi. Ce n'est pas un thème inventé depuis un nom de
matière ; c'est la description que l'éditeur donne de ses propres ressources,
citée document par document.
