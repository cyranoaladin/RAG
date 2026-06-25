# Rapport — Lot 7 : Taxonomie BO + agent d'acquisition piloté

## Fichiers de taxonomie

| Fichier | Matière | Niveau | Statut | Notions |
|---|---|---|---|---|
| `maths/terminale_specialite.yml` | mathematiques | terminale | specialite | 52 |
| `nsi/terminale.yml` | nsi | terminale | specialite | 27 |
| `philosophie/terminale_tronc_commun.yml` | philosophie | terminale | tronc_commun | 26 |
| `maths/premiere_tronc_commun.yml` | mathematiques | premiere | enseignement_commun | 23 |
| **Total** | | | | **128** |

Tous validés par `TaxonomySpec.model_validate()`. Script `validate_taxonomy.py` intégré à ci-local.sh.

## Agent d'acquisition taxonomy-driven

`scrapers/taxonomy_fetcher.py` :
- Charge un `TaxonomySpec` YAML
- Pour chaque notion, génère des titres candidats et tente Wikipedia FR puis Wikiversité FR
- Applique la chaîne gouvernée (whitelist, robots, rate limit, quality, anti-navigation)
- Dépose en staging avec étiquetage complet (notion_id, matiere, niveau, voie, statut_enseignement)

## Recalibrage anti-navigation

Seuil abaissé : `nav_hits >= 3` ou `(nav_hits >= 2 et words < 500)`. Marqueurs ajoutés : "autres leçons", "département". Les pages Wikiversité index courtes sont maintenant détectées.

## pilot_fetch refactoré

Plus de seed-list hardcodée. `pilot_fetch.py` itère sur les 3 taxonomies pilote (maths tle, nsi tle, philo tle), limité à 5 notions/taxonomie pour le pilote.

## CI locale : 7/7 PASS (+ taxonomy-validation)
