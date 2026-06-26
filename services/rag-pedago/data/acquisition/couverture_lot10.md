# Rapport de couverture hiérarchique — Lot 10.1 (pilote terminale, max 2 notions/matière)

## Résultat de l'exécution orchestrée

| Matière | Notions traitées | Trouvées | Non trouvées | Correspondance BO |
|---|---|---|---|---|
| orientation | 2 | 0 | 2 | non disponible |
| grand_oral | 2 | 0 | 2 | non disponible |
| histoire_geo | 2 | 0 | 2 | non disponible |
| mathematiques | 2 | 0 | 2 | non disponible |
| nsi | 2 | 2 | 0 | non disponible |
| philosophie | 2 | 0 | 2 | non disponible |
| **Total** | **12** | **2** | **10** | |

## Analyse

- **NSI** : les notions `listes` et `piles` ont été trouvées sur Wikipedia (termes génériques bien couverts).
- **Maths/Philo/HG** : les notions pilotes (`suites`, `limites`, `justice`, `etat`, `etats_unis`, `chine`) n'ont pas été trouvées — les pages Wikipedia correspondantes n'ont pas été atteintes par le fetcher (limites du matching titre).
- **Orientation/Grand Oral** : notions spécifiques au système français, absentes de Wikipedia.
- **Correspondance BO** : non disponible pour terminale (PDFs 404). Priorisation non active — toutes les notions ont `priority: no_correspondence`.

## Prochaines étapes

- Récupérer manuellement les programmes terminale (PDFs officiels) pour activer la priorisation BO.
- Améliorer le matching titre du fetcher (synonymes, variantes).
- Élargir les sources pour les matières non-STEM (histoire, philo, orientation).
