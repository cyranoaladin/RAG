# Guide du reviewer — PII et actualité (chemin minimal C1)

**Feuille à remplir** : `docs/reports/go_live/pii_currentness_minimal_c1_review.tsv` — 75 lignes : 3 actualité,
23 contenus PII promus, leurs 49 findings. Vue de lecture : `PII_CURRENTNESS_MINIMAL_C1_VIEW.md`.
Rien n'y est pré-rempli. Rien n'est importé sans votre ordre explicite (§ 8).

Ces 75 lignes font passer `release_promoted_refused_contents` de 26 à 0 et ouvrent C1. Elles font passer
`pii_undecided` de 149 à 126 seulement : les 126 contenus restants sont dans la feuille complète
(`pii_currentness_decision_sheet.tsv`) et devront aussi être tranchés avant le go-live (`pii_undecided=0` est exigé).

## 1. Préparer le poste (une fois)

```bash
export NEXUS_PII_REVIEW_ROOT=~/nexus-pii-review-v2-20260907
chmod -R go-rwx "$NEXUS_PII_REVIEW_ROOT"          # les répertoires sont en 775 aujourd'hui
```
Ouvrir le TSV dans un tableur **en mode texte** (pas de conversion automatique : les empreintes et les identifiants ne
doivent pas être altérés). Enregistrer en TSV, UTF-8, tabulation.

## 2. Ce que vous remplissez, et où

La colonne `WHAT_TO_FILL_ON_THIS_ROW` le dit ligne par ligne ; `open_this_file` dit quoi ouvrir.

| `row_kind` | Vous remplissez | Vous ne touchez pas |
|---|---|---|
| `PII_FINDING` (49) | `FINDING_DISPOSITION` | tout le reste |
| `PII_CONTENT` (23) | `HUMAN_DECISION`, `JUSTIFICATION_CATEGORY`, `REVIEWER_LOGIN` | tout le reste |
| `CURRENTNESS_CONTENT` (3) | `HUMAN_DECISION`, `REVIEWER_LOGIN`, et `EVIDENCE_REFERENCE` si vous maintenez | tout le reste |

`COMMENT` est libre partout, **sans jamais y recopier une donnée personnelle**. Les colonnes en minuscules sont en
lecture seule : le validateur refuse une feuille où l'une d'elles a changé.

## 3. Statuer un finding — `FINDING_DISPOSITION`

Ouvrir `open_this_file` (la page), repérer le motif `pattern_id`, puis choisir :

| Valeur | Quand |
|---|---|
| `FALSE_POSITIVE_TECHNICAL` | ce n'est pas une donnée personnelle : numéro de série, identifiant technique, suite de chiffres d'un exercice, référence de texte officiel prise pour un NIR ou un téléphone |
| `PUBLIC_INSTITUTIONAL_DATA` | coordonnée d'une institution ou d'un agent **dans sa fonction publique**, publiée par l'institution elle-même : standard d'un rectorat, adresse d'un ministère, courriel fonctionnel |
| `SYNTHETIC_EXAMPLE` | personne ou coordonnée **inventée** pour l'exercice : « Alice Dupont », base de données d'élèves fictifs d'un sujet de NSI, adresse d'exemple |
| `PERSONAL_DATA_PRESENT` | une **personne physique réelle** est identifiable : élève, parent, enseignant à titre privé ; numéro de sécurité sociale, date de naissance, téléphone ou adresse personnels |

En cas de doute entre exemple fictif et personne réelle : `PERSONAL_DATA_PRESENT`, ou laissez vide. Le doute ne profite
jamais à la publication. Attention particulière aux classes `french_ssn`, `date_of_birth`, `student_name_pattern`.

## 4. Statuer un contenu PII — `HUMAN_DECISION`

À faire **après** ses findings.

| Décision | Quand | Condition de validité |
|---|---|---|
| `PII_CLEARED` | **tous** les findings sont `FALSE_POSITIVE_TECHNICAL`, `PUBLIC_INSTITUTIONAL_DATA` ou `SYNTHETIC_EXAMPLE` | aucun finding `PERSONAL_DATA_PRESENT` ; catégorie ≠ `PERSONAL_DATA_PRESENT` |
| `PII_REDACTION_REQUIRED` | le document a une valeur pédagogique réelle **et** la donnée personnelle est localisée et retirable | au moins un finding `PERSONAL_DATA_PRESENT` ; catégorie `PERSONAL_DATA_PRESENT` |
| `EXCLUDE_FROM_SERVABLE_SET` | la donnée personnelle est diffuse, ou le document n'est pas indispensable, ou sa version caviardée n'aurait plus de sens | idem |
| `HUMAN_REVIEW_REQUIRED` (ou vide) | vous ne pouvez pas trancher : avis juridique, source à vérifier, second regard | aucune ; le contenu **reste bloquant** |

`JUSTIFICATION_CATEGORY` qualifie le constat dominant : `TECHNICAL_FALSE_POSITIVE`, `INSTITUTIONAL_CONTACT`,
`PUBLIC_OFFICIAL_PUBLICATION`, `PEDAGOGICAL_EXAMPLE`, `FICTIONAL_IDENTITY`, ou `PERSONAL_DATA_PRESENT` (obligatoire
pour les deux rejets).

Ce que chaque décision déclenche, à savoir avant de choisir :

- `PII_CLEARED` : le contenu reste dans la release. Aucun travail technique.
- `PII_REDACTION_REQUIRED` : le contenu **sort** de la release ; la version caviardée est un **autre** contenu
  (nouvelle empreinte) qui devra être produit, acquis, scanné et revu. C'est le choix le plus coûteux.
- `EXCLUDE_FROM_SERVABLE_SET` : le contenu sort de la release.
- Tout retrait d'un contenu promu exige un rescellement de release. Le constructeur de release **ne sait pas exclure**
  aujourd'hui : dès qu'une de vos décisions retire un contenu, un ADR et un lot technique précèdent C1.

La colonne `prior_v1_decision_not_extended` rappelle qu'une décision V1 `APPROVED` existait sur ces 23 contenus. Elle
portait sur un **autre texte** (la campagne V2 lit des pages que V1 voyait vides). Elle vous oriente, elle ne vous
dispense pas de regarder.

## 5. Les 3 contenus d'actualité

La **source elle-même** déclare ces documents archivés (`ARCHIVE_DECLARED`). Ils ne portent aucune PII.

| Décision | Quand | Exigence |
|---|---|---|
| `EXCLUDE_FROM_PROMOTED_RELEASE` | le document est bien périmé | aucune — c'est le choix cohérent avec la déclaration de la source |
| `REPLACE_WITH_CURRENT_SOURCE` | une version en vigueur existe et doit le remplacer | indiquer sa référence dans `EVIDENCE_REFERENCE` ; la nouvelle source suivra toute la chaîne d'acquisition |
| `KEEP_IF_STILL_CURRENT_WITH_EVIDENCE` | vous affirmez, **contre** la source, que le texte est en vigueur | `EVIDENCE_REFERENCE` **obligatoire** : référence officielle datée (BO, arrêté, page Éduscol datée). C'est une dérogation, tracée à votre nom |
| `HUMAN_REVIEW_REQUIRED` | à vérifier | le contenu reste bloquant |

## 6. Éviter une décision invalide

Avant de me la remettre, contrôlez la feuille — cela n'importe rien et ne modifie rien :

```bash
python3 scripts/go_live/validate_pii_currentness_review_sheet.py docs/reports/go_live/pii_currentness_minimal_c1_review.tsv
```
Il signale : valeur hors liste, `PII_CLEARED` avec un finding personnel, rejet sans finding personnel, décision rendue
sans disposition sur **chaque** finding, `REVIEWER_LOGIN` manquant, preuve manquante pour un maintien, colonne en lecture
seule modifiée, ligne inconnue ou en double, décision posée sur une ligne de finding. `"invalid": 0` = recevable.

## 7. Ordre de travail conseillé

1. Les 3 lignes d'actualité (`review_order` 1 à 3).
2. Les contenus PII dans l'ordre de la feuille — risque `ELEVE` d'abord. Pour chacun : le PDF, chaque page signalée,
   chaque finding, puis la ligne de contenu.
3. Validateur. 4. Remise.

Vous pouvez remettre une feuille partielle : seules les décisions rendues seront importées, le reste continue de bloquer.

## 8. Donner l'ordre d'import

```
PII_DECISIONS_VALIDATED fichier=docs/reports/go_live/pii_currentness_minimal_c1_review.tsv reviewer=<votre login> — IMPORT AUTORISÉ
```
Sans cette phrase, rien n'est importé. À sa réception : validation, conversion en
`governance/pii-review-decisions/<decision_set_id>.json` sous le contrat `NEXUS-PII-REVIEW-DECISIONS-V1`, PR avec revue
humaine épinglée — vos décisions passent donc une seconde fois sous vos yeux avant de produire un effet.
`pii_undecided` ne baissera que du nombre de décisions réellement rendues.
