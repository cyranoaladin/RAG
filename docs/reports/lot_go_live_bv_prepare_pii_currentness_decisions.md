# Lot BV — Dossier de décision humaine PII et actualité

- Lot : `LOT_GO_LIVE_FINAL_BV_PREPARE_HUMAN_PII_AND_CURRENTNESS_DECISIONS`
- Branche : `go-live/prepare-pii-currentness-decisions`
- **Décision : `HUMAN_GATE_REQUIRED_PII_CURRENTNESS`**
- Dossier scellé : `docs/reports/evidence/pii_currentness_human_decision_packet.json` (`a6a9196b5f9ee394d60786b15524bc16b7c271c00a8152a61cbd7441c768a505`)
- Feuille à remplir : `docs/reports/go_live/pii_currentness_decision_sheet.tsv` (631 lignes)

Ce lot **prépare**. Il ne choisit aucune option, ne caviarde rien, n'exclut rien, ne réduit pas `pii_undecided`,
ne produit pas de release v3, ne ferme aucun blocker. Tous les compteurs sont inchangés.

## Ce qu'il y a à décider

| Population | Nombre | Bloque |
|---|---|---|
| Contenus `PII_UNDECIDED` | **149** (479 findings) | `pii_undecided` |
| … dont promus dans la release | **23** (49 findings) | `release_promoted_refused_contents`, C1 |
| Contenus promus déclarés archivés par leur source | **3** | `release_promoted_refused_contents`, C1 |
| Total promus refusés | **26** | C1 |

Les 23 + 3 sont en tête de feuille (`P1_PROMOTED_BLOCKS_RELEASE`) : ce sont eux qui débloquent C1.
Les 126 autres (`P2_CANDIDATE`) ne bloquent que `pii_undecided`.

### Classes détectées (149 contenus)

| Classe | Findings | Contenus |
|---|---|---|
| `email_address` | 155 | 42 |
| `phone_french` | 136 | 46 |
| `postal_address` | 114 | 50 |
| `student_name_pattern` | 63 | 42 |
| `french_ssn` | 10 | 6 |
| `date_of_birth` | 1 | 1 |

Niveau de risque, **repris du tableau de pilotage existant** (`pii_human_decision_dashboard.json`), jamais recalculé ici :
`ELEVE` 6, `MOYEN` 106, `A_QUALIFIER` 37. Il **ordonne** la revue, il ne la remplace pas.

### Articulation avec l'existant

`main` porte déjà, pour la PII, `export_pii_review_packets.py`, `pii_review_decision_sheet.tsv` (149 lignes, une par
contenu, 0 décision inscrite) et le tableau de pilotage. Ce lot **ne les refait pas** : il les consomme, et ne lit pas la
matrice de servabilité (garde-fou `check-authority-uniqueness`, qui a refusé une première version de ce script — à
raison). Ce que la feuille existante ne permettait pas, et que celle-ci ajoute :

- les **3 lignes d'actualité**, absentes de toute feuille ;
- une ligne **par finding** (479) : le contrat `NEXUS-PII-REVIEW-DECISIONS-V1` exige une disposition pour chacun, une
  feuille à une ligne par contenu ne peut pas produire une décision valide ;
- le rappel des décisions V1 non étendues ;
- un dossier unique, scellé, recoupé avec le readiness.

### Contexte qui n'est PAS une décision

Les 23 contenus promus portent chacun une décision V1 `APPROVED` du 2026-09-03 (13 faux positifs techniques,
5 exemples pédagogiques, 4 contacts institutionnels, 1 publication officielle). Elle a été rendue sur l'index V1 ;
la campagne V2 a un autre texte canonique (OCR, pages jadis vides) et un autre paquet. Conformément à ADR-0047,
**aucune n'est étendue** : elle figure dans la colonne `prior_v1_decision_not_extended` pour éclairer le reviewer.

## Aucune matière brute dans le dépôt

AGENTS.md interdit de committer de la PII. Le dossier ne porte donc ni correspondance ni contexte : empreintes, classes,
pages, comptes. Les **extraits minimaux** demandés sont dans les paquets de revue hors dépôt, que chaque ligne désigne
par `review_bundle_dir` :

```
~/nexus-pii-review-v2-20260907/<review_bundle_dir>/document.pdf
~/nexus-pii-review-v2-20260907/<review_bundle_dir>/pages/page-NNNN.txt
```

Vérifié dans ce lot : 149 paquets présents, `{"intact": true, "ecarts": []}` contre l'index versionné
(`preparer_paquets_revue_pii.py --verifier`), fichiers en `0600`. **Écart constaté** : les répertoires sont en
`775` et non `0700` comme l'annonce `lot_revue_pii_v2.md` ; non corrigé ici (hors dépôt, à la main de l'opérateur :
`chmod -R go-rwx ~/nexus-pii-review-v2-20260907`).

## Comment remplir la feuille

Trois types de lignes (`row_kind`) ; seules les colonnes en MAJUSCULES sont à remplir.

1. `CURRENTNESS_CONTENT` (3) — `HUMAN_DECISION` ∈ `KEEP_IF_STILL_CURRENT_WITH_EVIDENCE` |
   `REPLACE_WITH_CURRENT_SOURCE` | `EXCLUDE_FROM_PROMOTED_RELEASE` | `HUMAN_REVIEW_REQUIRED`.
   `KEEP…` exige une preuve datée dans `EVIDENCE_REFERENCE` : la source elle-même déclare l'archive.
2. `PII_FINDING` (479) — `FINDING_DISPOSITION` ∈ `FALSE_POSITIVE_TECHNICAL` | `PUBLIC_INSTITUTIONAL_DATA` |
   `SYNTHETIC_EXAMPLE` | `PERSONAL_DATA_PRESENT`. Le contrat `NEXUS-PII-REVIEW-DECISIONS-V1` exige **chaque**
   finding : « j'ai vu le premier, ça semble bon » n'y est pas représentable.
3. `PII_CONTENT` (149) — `HUMAN_DECISION` ∈ `PII_CLEARED` | `PII_REDACTION_REQUIRED` |
   `EXCLUDE_FROM_SERVABLE_SET` | `HUMAN_REVIEW_REQUIRED`, plus `JUSTIFICATION_CATEGORY` et `REVIEWER_LOGIN`.

Correspondance avec le contrat existant (aucun protocole nouveau) :

| Option | Effet |
|---|---|
| `PII_CLEARED` | `APPROVED` ; refusé par le contrat si un seul finding est `PERSONAL_DATA_PRESENT` |
| `PII_REDACTION_REQUIRED` | `REJECTED`. Un contenu caviardé est un **autre** contenu (`artifact_id = content_sha256`) : nouvelle acquisition, nouveau scan, nouvelle revue |
| `EXCLUDE_FROM_SERVABLE_SET` | `REJECTED` ; sort du périmètre servable et de la release |
| `HUMAN_REVIEW_REQUIRED` | aucune décision : le contenu continue de bloquer |

## Ce que l'import (lot BW) fera, et seulement après votre confirmation

Conversion de la feuille en `governance/pii-review-decisions/<decision_set_id>.json` validé par le contrat, liaison
(`pii-review-bindings`), reprojection de la matrice. `pii_undecided` ne baissera que du nombre de décisions réellement
rendues. Tout retrait de contenu promu passe par le constructeur de release gouverné — dont
`RESEAL_BUILDER_CAPABILITY_REPORT.md` établit qu'il **n'expose aujourd'hui aucun moyen d'exclure un contenu** : c'est un
prérequis technique de BW, à traiter dès que les décisions indiqueront s'il y a des exclusions.

## Garanties

Générateur `scripts/go_live/build_pii_currentness_decision_packet.py` : dossier **dérivé**, refuse si pilotage, index PII,
impact de release et readiness ne se recoupent pas exactement. 9 épreuves : populations recoupées, 0 décision
pré-remplie, décision V1 citée jamais étendue, aucune matière brute, ordre et risque repris du pilotage, matrice non lue,
colonnes de décision vides,
refus d'autorités incohérentes, artefacts versionnés à jour et scellés.

## Readiness

Inchangé : `GO_LIVE_READY=false`, `--assert-ready=1`, `pii_undecided=149`, `release_promoted_refused_contents=26`,
`current_switch=0`, `production_db_writes=0`, `production_deployments=0`.

## Demande

1. Validation ou décisions humaines sur le TSV.
2. Confirmation explicite pour importer les décisions.
