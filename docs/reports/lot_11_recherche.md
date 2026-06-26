# Rapport — Lot 11 : Recherche réelle (article table)

## Méthode retenue

Les endpoints de recherche API (opensearch, REST search) sont **interdits par robots.txt** sur Wikipedia et Wikiversité. Solution : **table notion→article** (`data/sources/notion_articles.yml`) avec titres d'articles vérifiés.

### Verdict robots.txt par endpoint

| Endpoint | robots |
|---|---|
| `/w/api.php?action=opensearch` (Wikipedia) | **INTERDIT** |
| `/w/rest.php/v1/search/page` (Wikipedia) | **INTERDIT** |
| `/wiki/{titre}` (Wikipedia) | **AUTORISÉ** |
| `/w/api.php` (Wikiversité) | **INTERDIT** |
| `/wiki/{titre}` (Wikiversité) | **AUTORISÉ** |

## Table notion→article

39 entrées (15 maths, 13 NSI, 11 philo) avec titres vérifiés. Traçabilité : chaque fetch expose `search_method` (article_table | title_guess), `candidate_urls`, `chosen_url`.

## Comparaison couverture AVANT/APRÈS

| | Avant (devinette titre) | Après (article table) |
|---|---|---|
| Maths terminale | ~0/5 | **13/13** (100%) |
| NSI terminale | 2/5 | **5/5** (100%) |
| Philosophie terminale | 0/5 | **4/5** (80%) |
| Histoire-géo terminale | 0/5 | 2/5 (40%) |
| Grand Oral | 0/5 | 2/5 (40%) |
| Orientation | 0/5 | 0/5 (0%) |
| **Total** | **~2/12 (17%)** | **26/38 (68%)** |

## Dettes BACKLOG

- DETTE-10.1-A : convention nommage PDF → documentée
- DETTE-10.1-B : devinette titre → résolu (article table)

## Conformité

- robots.txt : aucun endpoint interdit utilisé ✓
- Whitelist respectée ✓
- `ingestion_allowed=false` ✓

## CI locale : 7/7 PASS
