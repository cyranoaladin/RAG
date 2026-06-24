# Intégrité du référentiel officiel

Le lot 9.5 durcit le référentiel institutionnel avant tout branchement dans les politiques qualité des manifests.

## Intégrité référentielle

Les fichiers `data/reference/` doivent rester cohérents entre eux :

- chaque `official_sources` référencé doit exister dans `official_sources.yml` ;
- chaque `exam_refs` d'un niveau doit pointer vers un `ExamReference` existant ;
- chaque `level_id` d'un `SubjectReference` doit pointer vers un niveau existant ;
- chaque contrainte `requires_subjects` ou `excludes_terminal_specialties` doit pointer vers un sujet connu ;
- chaque `candidate_types` d'un examen doit pointer vers un `CandidateStatusReference` et non vers un contexte d'établissement.

Ces règles sont couvertes par `tests/unit/test_official_reference_integrity.py`.

## OfficialClaim

`OfficialClaim` relie une affirmation réglementaire à une source précise. Exemple :

- `bac_general_40_60` supporte `bac_general.control_continu_weight` et `bac_general.terminal_weight` ;
- `terminale_generale_two_specialties` supporte le fait qu'un élève conserve deux EDS en terminale ;
- `dnb_individual_foreign_language` supporte l'épreuve écrite de langue vivante des candidats individuels au DNB.

Une claim `verified` doit s'appuyer sur une source `verified`. Une claim `pending` ne peut pas servir seule de support à une règle définitive.

## EstablishmentContextReference

`EstablishmentContextReference` sépare le contexte d'établissement du statut candidat d'examen.

Exemples de contextes :

- `aefe` ;
- `systeme_francais_hors_aefe` ;
- `systeme_tunisien` ;
- `double_cursus` ;
- `cned`.

## Pourquoi AEFE n'est pas un type d'examen

AEFE décrit un contexte de scolarisation ou d'établissement. Le statut d'examen décrit la façon dont le candidat est inscrit et évalué : `scolarise`, `candidat_individuel`, `cned_reglemente`, `cned_libre`.

`aefe` reste temporairement présent dans `candidate_statuses.yml` pour compatibilité, mais il est marqué `deprecated: true` avec l'avertissement : `aefe is an establishment context, not an exam candidate type.`

## Sources pending vs verified

Une source `verified` peut soutenir une règle officielle. Une source `pending` doit être traitée comme information à vérifier.

Les données locales IFT/Tunisie restent `pending` lorsqu'elles ne sont pas confirmées directement par une source institutionnelle locale vérifiable. Les réponses réglementaires futures ne doivent pas les présenter comme définitives.

## Réponses source-backed

Toute réponse réglementaire future du RAG doit pouvoir relier ses affirmations à :

- un `OfficialClaim` ;
- une `OfficialSource` vérifiée ;
- un niveau, examen, sujet ou statut candidat structuré.

Sans claim vérifiée, la réponse doit formuler une incertitude ou demander une vérification manuelle.

## Utilisation par la qualité des manifests

La politique qualité vérifie désormais que les refs officielles pointent vers
des IDs existants et cohérents. Les documents officiels sans source ou claim
vérifiée sont bloqués. Les documents d'examen sans `official_exam_ref` sont
bloqués lorsque `require_official_refs_for_exam_docs` est actif.

## Resolver de compatibilité

`OfficialReferenceResolver` construit un graphe depuis le référentiel :

- niveaux vers examens ;
- examens agrégateurs vers sous-épreuves ;
- examens vers statuts candidats ;
- sujets vers niveaux autorisés.

Il permet de vérifier qu'une source ou claim s'applique au document par un
chemin explicite du graphe. Les relations par matière sont volontairement
strictes : une matière commune ne suffit pas à transférer une source d'un
niveau vers un autre.
