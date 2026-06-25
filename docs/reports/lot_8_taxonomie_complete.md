# Rapport — Lot 8 : Taxonomie BO complète + auto-découverte

## Couverture taxonomique

| Matière | 3e | 2de | 1re | Tle | Total notions |
|---|---|---|---|---|---|
| Mathématiques | 25 | 27 | 23 | 64 | 139 |
| NSI | — | — | 25 | 37 | 62 |
| Philosophie | — | — | — | 26 | 26 |
| Hist-Géo | 12 | 14 | 20 | 26 | 72 |
| Français | 12 | — | 23 | — | 35 |
| Phys-Chimie | — | — | 22 | — | 22 |
| SVT | — | — | 17 | — | 17 |
| SES | — | — | 19 | — | 19 |
| SNT | — | 7 | — | — | 7 |
| Grand Oral | — | — | — | 10 | 10 |
| Candidats libres | — | — | — | 11 | 11 |
| **Total** | **49** | **48** | **149** | **174** | **420** |

(246 notions principales + 173 subnotions = 419 identifiants uniques)

## Fichiers produits

- **4 fichiers validés BO** (existants, corrigés) : maths tle spé, maths 1re, NSI tle, philo tle
- **15 fichiers PREMIER JET** (à réviser par expert matière)
- **Total : 19 fichiers** validés par TaxonomySpec, 0 erreur

## Lacunes corrigées

- **Maths Tle** : ajout limites, dérivation, convexité comme notions principales (pas seulement subnotions) ; ajout loi_normale
- **NSI Tle** : ajout tests_mise_au_point, gestion_modules, paradigme_fonctionnel, calculabilite_decidabilite
- **programme_version** : format BOEN_* sur tous les fichiers

## Auto-découverte

`pilot_fetch.py` découvre les taxonomies par `TAXONOMY_ROOT.rglob("*.yml")` avec filtre `common/exams/proposals`. Plus de liste hardcodée.

## validate_taxonomy.py enrichi

- Distingue notions/subnotions dans le décompte
- Détecte les fichiers PREMIER JET (warning)
- Vérifie le format `programme_version` (BOEN_*)
- Intégré à ci-local.sh

## CI locale : 7/7 PASS (+ taxonomy-validation)
