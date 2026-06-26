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

40 entrées (16 maths, 13 NSI, 11 philo) avec titres vérifiés. Traçabilité : chaque fetch expose `search_method` (article_table | title_guess), `candidate_urls`, `chosen_url`, `ignored_candidate_urls`, `source_label`, `selection_reason` et `fallback_used`.

## Correction retours Codex/Cubic

Décision maintenue : une matière + une `notion_id` produit une seule ressource finale et un seul fichier staging `{matiere}_{notion_id}.json`. Les URLs multiples restent des candidats tracés, pas des ressources finales.

`fetch_notion()` s'arrête dès le premier candidat acceptable : HTTP 200, texte extrait substantiel, qualité non bloquante. Une page Wikiversité détectée comme page de navigation n'est pas choisie directement ; ses sous-pages sont évaluées, et une seule sous-page acceptable peut être retenue avec `url == chosen_url == sub_url`, `source_label=wikiversity_<notion>_chN` et `page_type=subpage`.

Les rapports comptent des notions uniques. Les candidats non retenus sont visibles dans `ignored_candidate_urls`.

### Génération ciblée vérifiée

| Notion | Source retenue | URL retenue | Candidats ignorés | Fallback |
|---|---|---|---|---|
| `mathematiques/suites` | `wikipedia_suites` | `https://fr.wikipedia.org/wiki/Suite_%28math%C3%A9matiques%29` | `https://fr.wikiversity.org/wiki/Suites_et_r%C3%A9currence` | non |
| `mathematiques/derivation` | `wikipedia_derivation` | `https://fr.wikipedia.org/wiki/D%C3%A9riv%C3%A9e` | `https://fr.wikiversity.org/wiki/Fonction_d%C3%A9riv%C3%A9e` | non |
| `mathematiques/algorithmique_suites` | `wikipedia_algorithmique_suites` | `https://fr.wikipedia.org/wiki/Suite_%28math%C3%A9matiques%29` | `https://fr.wikiversity.org/wiki/Suites_et_r%C3%A9currence` | non |
| `nsi/dictionnaires` | `wikipedia_dictionnaires` | `https://fr.wikipedia.org/wiki/Tableau_associatif` | `https://fr.wikipedia.org/wiki/Table_de_hachage` | non |

### Avant/après `mathematiques_suites.json`

Avant correction, le fichier canonique était issu de la sous-page Wikiversité `Suites_et_récurrence/Opérations_sur_les_limites`, avec `source_label=wikiversity_suites_ch3`, `status=quality_issues`, `page_type=subpage` et `chosen_url` resté sur la page parente.

Après correction, le fichier canonique retient Wikipedia `Suite_(mathématiques)` : `source_label=wikipedia_suites`, `status=ok`, `page_type=article`, `url == chosen_url`, et la page Wikiversité est seulement listée dans `ignored_candidate_urls`.

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
