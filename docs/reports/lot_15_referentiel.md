# Rapport — Lot 15 : Référentiel exhaustif + canal ressources curées

## Inventaire exhaustif

**39 programmes** inventoriés (4 niveaux × {tronc commun, spécialités, options, Grand Oral, épreuves anticipées, candidat libre}).

| Niveau | Programmes | Avec taxonomie | Avec chunks |
|---|---|---|---|
| Terminale | 20 | 6 | 3 |
| Première | 13 | 5 | 0 |
| Seconde | 4 | 3 | 0 |
| Troisième | 3 | 3 | 0 |
| **Total** | **39** | **19** | **3** |

## Couverture réelle

- **Squelette** (taxonomie existante) : 19/39 (49%)
- **Remplissage** (chunks indexés) : 3/39 (8%)
- **Programmes à 0%** : 20/39 (principalement : spécialités hors maths/nsi, options, épreuves anticipées, langues, EPS, EMC)

## Statut taxonomie

- **4 fichiers `revise`** : maths tle spé, nsi tle, philo tle, maths 1re
- **15 fichiers `premier_jet`** : à confronter au BO par l'enseignant

## Canal ressources curées (ADR-0009)

- `curated_ingestion_allowed: false` — porte posée, non alimentée
- Baseline : 17 → **18 clés**
- `source_admission_policy` : `curated_resources` déclaré avec `require_human_review`
- Le canal sera alimenté par une interface dédiée (lot ultérieur)

## CI locale : 7/7 PASS, garde-fou 18/18
