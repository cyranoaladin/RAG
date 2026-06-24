# Modèle de référentiel officiel

Le référentiel officiel structure les informations institutionnelles indépendamment des documents pédagogiques. Il sert à contrôler les niveaux, matières, spécialités, options, épreuves, statuts candidats et sources réglementaires.

## Pourquoi ce référentiel

Les taxonomies décrivent les notions pédagogiques. Le référentiel officiel décrit le cadre institutionnel : quelle classe existe, quels enseignements sont communs, quelles spécialités ou options sont possibles, quelles épreuves concernent quel candidat, et quelles sources font autorité.

Le RAG ne doit pas inférer ces règles depuis des noms de dossiers ou depuis des résumés LLM. Les futurs manifests et profils doivent pouvoir pointer vers des identifiants stables : `official_level_ref`, `official_exam_ref`, `official_subject_ref`, `candidate_status_ref`.

## Taxonomy vs official reference

- `TaxonomySpec` : thèmes, notions, sous-notions et compétences pédagogiques.
- `SchoolLevelReference` : niveau scolaire, voie, enseignements communs, options, spécialités et examens.
- `SubjectReference` : matière, spécialité ou option, horaires, prérequis et taxonomie associée.
- `ExamReference` : épreuves, candidats concernés, poids contrôle continu/terminal, coefficients et avertissements.

Une notion comme `suites` relève de la taxonomie. Une règle comme “terminale générale conserve deux EDS” relève du référentiel officiel.

## ExamProfile vs ExamReference

- `ExamReference` décrit la règle générale officielle pour une session ou un examen.
- `ExamProfile` décrit la carte d'examen d'un élève concret : session, zone, centre, convocation, épreuves à passer, options et spécialités.

Pour un candidat libre, `ExamProfile` doit être confirmé avant de produire une recommandation réglementaire.

## Scolarisé vs candidat individuel

Un candidat scolarisé a généralement une inscription portée par l'établissement et des informations de contrôle continu. Un candidat individuel dépend d'évaluations ponctuelles et d'épreuves terminales. Les règles d'inscription et de convocation priment sur toute hypothèse pédagogique.

## Incertitudes locales IFT

La source académique Aix-Marseille indique que les candidats isolés de Tunisie passent par Cyclades puis le bureau des examens de l'Institut français de Tunisie. Les modalités locales détaillées IFT sont marquées `verification_status: pending` tant qu'elles ne sont pas confirmées directement par une source IFT accessible et vérifiable.

Information locale non confirmée — à vérifier manuellement par Nexus.

## Intégration dans les futurs manifests

Les manifests pourront porter :

- `official_level_ref` ;
- `official_exam_ref` ;
- `official_subject_ref` ;
- `candidate_status_ref`.

Ces champs restent optionnels au lot 9 pour ne pas casser les manifests existants. Ils devront devenir des critères de qualité sur les lots de données officiels et examens.

## Durcissement lot 9.5

Le lot 9.5 ajoute :

- `OfficialClaim` pour relier chaque affirmation réglementaire à une source ;
- `EstablishmentContextReference` pour séparer AEFE, CNED, double cursus et autres contextes du statut candidat d'examen ;
- des sous-épreuves séparées dans `data/reference/exams/` (`eaf`, `anticipee_maths`, `bac_specialite_ecrit`, `philosophie`, `grand_oral`, `controle_continu_bac`, variantes DNB) ;
- `data/reference/subjects/common_subjects.yml` pour couvrir aussi les matières communes.

AEFE est un contexte d'établissement, pas un type d'examen. Il reste temporairement dans `candidate_statuses.yml` uniquement pour compatibilité et avec `deprecated: true`.

## Branchements qualité lot 10

Le lot 10 charge le référentiel via `load_official_reference_index()` et
vérifie les manifests avant import. Les champs `official_*_ref` restent
optionnels dans `DocumentMeta`, mais deviennent obligatoires selon `type_doc`
et selon la politique qualité.

## Couverture métier lot 10.5

Le lot 10.5 ajoute des fixtures propres couvrant les cas Nexus à vérifier avant
ingestion documentaire :

- troisième DNB scolarisé ;
- troisième DNB candidat individuel avec épreuve de langue vivante spécifique ;
- seconde générale et technologique ;
- première générale avec EAF et épreuve anticipée de mathématiques ;
- terminale générale avec spécialités, philosophie et Grand oral ;
- candidat individuel au bac ;
- élève AEFE scolarisé ;
- double cursus.

Ces fixtures ne sont pas des documents pédagogiques. Elles servent à valider
que les manifests déclarent les bonnes références officielles, claims, sources,
statuts candidats et contextes d'établissement. Les futures réponses
réglementaires devront rester source-backed et ne jamais affirmer une règle
locale `pending` comme définitive.

## Resolver lot 11

Le lot 11 ajoute `OfficialReferenceResolver`. Il transforme le référentiel en
graphe de compatibilité pour distinguer :

- compatibilité directe (`official_exam_ref=grand_oral`) ;
- compatibilité indirecte (`bac_general -> grand_oral`) ;
- incompatibilité forte (`dnb` ne couvre pas `grand_oral`) ;
- contexte d'établissement (`aefe`) distinct du statut candidat.

La politique qualité utilise ce resolver pour les issues
`official_source_applies_to_mismatch` et
`official_claim_applies_to_mismatch`.
