# Rapport — Lot 11.3 : Extraction de contenu réelle + qualité honnête

## Failles corrigées

### 1. Extraction sans parseur HTML
**Avant** : regex `re.sub(r"<[^>]+>", " ", text)` stripait les balises mais gardait le chrome (menu, infobox, navbox, références, portails, catégories).

**Après** : BeautifulSoup cible `.mw-parser-output`, retire `nav/header/footer/script/style/sup`, décompose les classes `.navbox/.infobox/.metadata/.references/.hatnote/.bandeau`, supprime les sections terminales (Notes, Voir aussi, Liens externes, Bibliographie), et tronque les résidus footer (Notices d'autorité, Portail).

### 2. Faux négatif du détecteur de qualité
**Avant** : `navigation_suspected = nav_hits >= 3 and words_count < 500` — les articles > 500 mots n'étaient JAMAIS examinés.

**Après** : `navigation_suspected = chrome_hits >= 2` — indépendant de la longueur. Détecte le chrome résiduel post-extraction.

## Preuves sur 3 articles réels

### Suite (mathématiques) — 21 402 chars, nav=False
```
FIRST 200: Exemple de suite : les points bleus représentent ses termes. En mathématiques , une suite est une liste d'éléments...
LAST 200: ...Tapis de Sierpiński  [contenu article, pas de chrome]
```

### État — 66 852 chars, nav=False
```
FIRST 200: Nicolas Machiavel fut un des premiers à faire usage du mot stato dans le sens d' « unité politique d'un peuple...
```

### Récursivité — 13 532 chars, nav=False
```
FIRST 200: La récursivité est une démarche qui fait référence à l'objet même de la démarche...
```

Aucun « Aller au contenu », « Un article de Wikipédia », « Rechercher » dans les 3 articles.

## Couverture substantielle réelle : 16/30 (53%)

| Chiffre précédent | Méthode | Réalité |
|---|---|---|
| 68% (lot 11) | Comptait ok + quality_issues | Faux-vert (quality_issues = chrome) |
| **53% (lot 11.3)** | Notions distinctes substantielles (ok + nav=False) | **Correct** |

## Constat technique vs conceptuelle

- **STEM** (maths, NSI) : **100%** couvertes par Wikipedia
- **Philosophie** : **80%** (concepts universels)
- **Examen/orientation** : **13%** (nécessite sources curées)

## CI locale : 7/7 PASS
