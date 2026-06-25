# Dossier de revue — Lot 6 (sous-pages + NSI Wikipedia)

## Sources : Wikiversité (CC-BY-SA 4.0) + Wikipedia FR (CC-BY-SA 4.0)

### Résultats du fetch

| # | Notion | Matière | Source | Chars | nav_suspected | Statut |
|---|---|---|---|---|---|---|
| 1 | suites | maths | wikiversity | 1920 | False | à_valider |
| 2 | fonction_exponentielle | maths | wikiversity | 3492 | False | à_valider |
| 3 | derivation | maths | wikiversity | 3392 | False | à_valider |
| 4 | probabilites_conditionnelles | maths | wikiversity | 1876 | False | à_valider |
| 5 | primitives | maths | wikiversity | — | 404 | page_inexistante |
| 6 | recursivite | nsi | **wikipedia** | 17771 | **False** | à_valider |
| 7 | arbres | nsi | **wikipedia** | 13507 | True | à_valider (sommaire) |
| 8 | graphes | nsi | **wikipedia** | 59199 | **False** | à_valider |
| 9 | sql | nsi | wikiversity | 3776 | False | à_valider |

### Couverture substance

- **Maths** : 4/5 notions avec contenu (suites, exponentielle, dérivation, probas). Primitives = 404.
- **NSI** : 3/3 notions avec contenu (récursivité 17K, graphes 59K, SQL 3.7K). Arbres = sommaire/nav.
- **Total substance** : 7/9 notions avec contenu non-navigation.

### Extraits réels (text_preview brut, premiers 300 chars)

**recursivite** (Wikipedia, 17771 chars, nav=False) :
```
Récursivité (informatique) — Wikipédia En informatique et en logique, une fonction ou plus généralement un algorithme qui contient un appel à elle-même est dite récursive. L'utilisation de la récursivité en informatique permet de résoudre des problèmes de manière élégante. La récursivité est une notion fondamentale en informatique, car elle est à la base de nombreux algorithmes...
```

**graphes** (Wikipedia, 59199 chars, nav=False) :
```
Théorie des graphes — Wikipédia La théorie des graphes est la discipline mathématique et informatique qui étudie les graphes, lesquels sont des modèles abstraits de dessins de réseaux reliant des objets. Ces modèles sont constitués par la donnée de « sommets » (aussi appelés « nœuds » ou « points »), et d'« arêtes » (aussi appelées « liens » ou « lignes ») entre ces sommets...
```

**suites** (Wikiversité, 1920 chars, nav=False) :
```
Suites et récurrence — Wikiversité Une page de Wikiversité, la communauté pédagogique libre. Suites et récurrence Autres leçons de mathématiques Département Analyse Cours: Suite numérique Terminale S en France Chapitres Chap. 1: Limite d'une suite Chap. 2: Comparaison de suites...
```

## Conformité
- robots.txt : `/wiki/` autorisé sur Wikiversité + Wikipedia ✓
- Rate limit : 2s entre requêtes ✓
- Licences : CC-BY-SA 4.0 (Wikiversité + Wikipedia) ✓
- `ingestion_allowed=false` ✓
