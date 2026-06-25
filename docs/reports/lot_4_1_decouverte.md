# Rapport — Lot 4.1 : Découverte de sources (vraie couverture par notion)

## Règle de matching stricte

Une source candidate n'est retenue pour une notion **que si** un token significatif (≥3 caractères) de `notion_id`/`notion_label` apparaît dans les métadonnées de la source (`source_id`, `title`, `applies_to`). Aucun fallback curriculaire : une source de programme générique ne couvre pas automatiquement toutes les notions de la matière.

**Supprimé** : `_is_curriculum_source` et l'asymétrie maths/nsi (maths avait 5 keywords de fallback, nsi seulement 1).

## Couverture réelle (matching strict)

| Matière | Notions totales | Couvertes | À découvert |
|---|---|---|---|
| mathematiques | 52 | 1 | 51 |
| nsi | 27 | 0 | 27 |
| **Total** | **79** | **1** | **78** |

### Seule notion couverte
- `mathematiques/formule_des_probabilites_totales` → source `education_maths_reforme_lycee` (tokens `probabilites` + `totales` matchent)

## Constat

Le catalogue local de ~17 sources institutionnelles génériques **ne couvre quasiment aucune notion fine** du programme de Terminale. Ces sources mentionnent la matière et le niveau mais pas les notions individuelles.

**→ La constitution du corpus exige la recherche web ciblée par notion** (Lot 4.2, ouverture réseau scopée sous ADR-0004). Les 78 notions à découvert constituent la file d'entrée du scraping gouverné.

## Audience conforme à ADR-0003

`_infer_audience` produit les 3 valeurs : `tous` (défaut disciplinaire), `libre` (candidat libre), `aefe` (AEFE). Tests à l'appui.

## Plan d'acquisition

Versionné dans `services/rag-pedago/data/acquisition/pilot_terminale_plan.yml`.

## Tests (8/8 PASS)

- Matching strict : source générique ne matche aucune notion
- Source notion-spécifique matche
- Pas d'asymétrie maths/nsi
- Couverture honnête (0 couvert par source générique)
- Audience libre/aefe/tous
- Manifests valides

## CI locale : 6/6 PASS, garde-fou 17/17
