# Official reference resolver

Le resolver officiel vérifie la compatibilité entre une source ou une claim et
un document sans se limiter à une égalité directe d'identifiants.

## Pourquoi un resolver

Les sources institutionnelles peuvent viser un objet agrégé :

- `bac_general` ;
- `dnb` ;
- un niveau comme `terminale_generale`.

Un document peut viser une sous-épreuve :

- `grand_oral` ;
- `philosophie` ;
- `bac_specialite_ecrit` ;
- `dnb_candidat_individuel`.

Une intersection directe raterait ces cas ou créerait des faux positifs par
matière partagée. Le resolver utilise donc le graphe du référentiel.

## ID direct vs compatibilité indirecte

Un ID direct est une référence exactement portée par le document :
`official_exam_ref=grand_oral`, `candidate_status_ref=scolarise`, etc.

Une compatibilité indirecte existe lorsqu'un ID source est ancêtre d'une
référence document dans le graphe :

- `bac_general -> grand_oral` ;
- `bac_general -> philosophie` ;
- `dnb -> dnb_candidat_individuel` ;
- `troisieme_generale -> dnb_scolaire`.

## Agrégateurs

Les agrégateurs modélisés sont :

- `bac_general` vers `eaf`, `anticipee_maths`, `bac_specialite_ecrit`,
  `philosophie`, `grand_oral`, `controle_continu_bac` ;
- `dnb` vers `dnb_scolaire`, `dnb_candidat_individuel`.

Une source DNB ne couvre pas un document bac. Une claim candidat individuel ne
couvre pas un document scolarisé sans lien explicite.

## Niveau vers examens

Les niveaux exposent leurs `exam_refs` :

- `premiere_generale` vers `eaf` et `anticipee_maths` ;
- `terminale_generale` vers `bac_specialite_ecrit`, `philosophie`,
  `grand_oral`, `controle_continu_bac` ;
- `troisieme_generale` vers `dnb_scolaire` et `dnb_candidat_individuel`.

## Examen vers niveau

Chaque `ExamReference` porte son `level_id`. Le resolver ajoute la relation
niveau -> examen, ce qui permet de retrouver les ancêtres d'une épreuve.

## Matières

Les matières sont vérifiées en référence directe. Une source qui s'applique à
`troisieme_generale` ne devient pas compatible avec un document terminale
simplement parce que les deux mentionnent `mathematiques`.

## AEFE

AEFE est un contexte d'établissement. Il peut coexister avec
`candidate_status_ref=scolarise`, mais il n'est pas équivalent au statut
candidat. `candidate_status_ref=aefe` reste déprécié.

## Exemples acceptés

- `education_bac_general` couvre un document `official_exam_ref=grand_oral`.
- `education_bac_general` couvre un document
  `official_exam_ref=bac_specialite_ecrit`.
- `education_dnb` couvre un document `official_exam_ref=dnb_candidat_individuel`.

## Exemples rejetés

- `education_dnb` ne couvre pas un document `official_exam_ref=grand_oral`.
- `dnb_individual_foreign_language` ne couvre pas un document scolarisé de
  terminale.
- `aefe` comme contexte ne rend pas un document équivalent à un candidat
  individuel.

## Explications auditables

Depuis le lot 11.5, `explain_source_compatibility()` et
`explain_claim_compatibility()` retournent une `CompatibilityExplanation`
typée :

- `ref_id` : source ou claim évaluée ;
- `document_refs` : références officielles portées par le document ;
- `compatible` : décision booléenne ;
- `matched_ref` : référence document atteinte si compatible ;
- `path` : chemin graphe retenu ;
- `reason` : phrase courte expliquant la décision.

Ces explications sont reprises dans les issues qualité et dans les rapports
readiness, gate et controlled import lorsqu'un mismatch bloque un batch.
