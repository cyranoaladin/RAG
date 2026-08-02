# LOT39bis — Paquet de revue humaine exhaustive des requêtes golden

> **REVENDICATION HISTORIQUE NON AUTHENTIFIÉE — NE VAUT PAS APPROBATION**
>
> **Erratum LOT41T — 2026-08-02.** Le commentaire historique de la PR #82 ne
> liait ni le digest de spécification, ni ce paquet, ni le head final. Les cases
> ci-dessous sont conservées comme trace historique, sans autorité de promotion.

> **Statut : APPROVED — revue humaine exhaustive.**

## Périmètre normatif à relire

La revue porte sur la spécification identifiée par les empreintes suivantes :

- digest de spécification courant : `d00c7e0fcf6870111b46d07ddc5531d15184ba7dbf2f780af81b6b2a416ddee4` ;
- requêtes Mathématiques : `ced6822a448f177940c6c87a29562569dc3349d0116f2940180357d1e68cea7b` ;
- requêtes NSI : `9b7ecb5f37b9cb233c792e6e637353eee20f0c4df5aa52d6ac7127899d7f7ba6`.

Les deux fichiers YAML exacts suivants constituent le contenu normatif à relire :

- [`lot39bis_maths.yml`](../../../../services/rag-pedago/tests/golden_queries/lot39bis_maths.yml) ;
- [`lot39bis_nsi.yml`](../../../../services/rag-pedago/tests/golden_queries/lot39bis_nsi.yml).

La checklist ci-dessous sert uniquement à tracer la couverture des identifiants. Pour chaque case, la personne chargée de la revue doit ouvrir le YAML exact et relire le texte complet de la requête, ses filtres et l’intégralité du jugement `expected`, notamment `outcome`, `official_program_reference`, `pedagogical_expectation`, `candidate_source_class` et `must_not_return`.

Tout changement du digest de spécification ou de l’une des deux empreintes de requêtes annule la revue et impose de reprendre les 255 cas sur les nouveaux fichiers exacts.

## Règle d’approbation humaine

Seule une personne humaine identifiée peut cocher les cases, renseigner son identité et signaler l’approbation. Aucun agent automatique ne peut attester cette revue. Ce paquet ne préremplit ni reviewer, ni horodatage, ni signature, ni verdict d’approbation.

Après une revue complète seulement, remplacer exactement `PENDING` par `APPROVED`
dans l’unique ligne de statut en tête, cocher les 259 cases et renseigner les quatre
lignes suivantes. Toute autre variante de statut sera refusée.
L’identité, le rôle et l’heure UTC devront concorder avec le manifeste de revue ;
toute valeur générique ou laissée vide sera refusée.

- Identité stable du reviewer : `Alaeddine BEN RHOUMA (@abenrhouma)`
- Rôle : `responsable pédagogique`
- Horodatage UTC de fin de revue : `2026-08-01T07:34:20Z`
- Référence de signature ou de preuve : `https://github.com/cyranoaladin/RAG/pull/82#issuecomment-5150433429`

## Attestations globales — à laisser vierges jusqu’à la revue humaine complète

- [x] Les 255 textes de requête ont été lus intégralement dans les deux YAML exacts.
- [x] Les 255 jugements et attentes pédagogiques ont été lus intégralement et contrôlés.
- [x] Chaque contrainte `must_not_return` pertinente a été vérifiée.
- [x] Aucun cas ne prétend disposer d’un document réel, d’un `doc_id`, d’un `chunk_id`, d’un résultat de retrieval, d’un score ou d’un jugement de substance réelle.

## Checklist exhaustive des 255 identifiants

### Mathématiques — 95 cas

#### Catégorie positive — 65 cas

##### Notion `suites_limites` — 5 cas

- [x] `maths_positive_suites_limites_comprehension`
- [x] `maths_positive_suites_limites_methode`
- [x] `maths_positive_suites_limites_application`
- [x] `maths_positive_suites_limites_diagnostic`
- [x] `maths_positive_suites_limites_transfert`

##### Notion `continuite` — 5 cas

- [x] `maths_positive_continuite_comprehension`
- [x] `maths_positive_continuite_methode`
- [x] `maths_positive_continuite_application`
- [x] `maths_positive_continuite_diagnostic`
- [x] `maths_positive_continuite_transfert`

##### Notion `derivation_convexite` — 5 cas

- [x] `maths_positive_derivation_convexite_comprehension`
- [x] `maths_positive_derivation_convexite_methode`
- [x] `maths_positive_derivation_convexite_application`
- [x] `maths_positive_derivation_convexite_diagnostic`
- [x] `maths_positive_derivation_convexite_transfert`

##### Notion `logarithme` — 5 cas

- [x] `maths_positive_logarithme_comprehension`
- [x] `maths_positive_logarithme_methode`
- [x] `maths_positive_logarithme_application`
- [x] `maths_positive_logarithme_diagnostic`
- [x] `maths_positive_logarithme_transfert`

##### Notion `primitives_integration` — 5 cas

- [x] `maths_positive_primitives_integration_comprehension`
- [x] `maths_positive_primitives_integration_methode`
- [x] `maths_positive_primitives_integration_application`
- [x] `maths_positive_primitives_integration_diagnostic`
- [x] `maths_positive_primitives_integration_transfert`

##### Notion `equations_differentielles` — 5 cas

- [x] `maths_positive_equations_differentielles_comprehension`
- [x] `maths_positive_equations_differentielles_methode`
- [x] `maths_positive_equations_differentielles_application`
- [x] `maths_positive_equations_differentielles_diagnostic`
- [x] `maths_positive_equations_differentielles_transfert`

##### Notion `combinatoire` — 5 cas

- [x] `maths_positive_combinatoire_comprehension`
- [x] `maths_positive_combinatoire_methode`
- [x] `maths_positive_combinatoire_application`
- [x] `maths_positive_combinatoire_diagnostic`
- [x] `maths_positive_combinatoire_transfert`

##### Notion `geometrie_espace` — 5 cas

- [x] `maths_positive_geometrie_espace_comprehension`
- [x] `maths_positive_geometrie_espace_methode`
- [x] `maths_positive_geometrie_espace_application`
- [x] `maths_positive_geometrie_espace_diagnostic`
- [x] `maths_positive_geometrie_espace_transfert`

##### Notion `produit_scalaire_espace` — 5 cas

- [x] `maths_positive_produit_scalaire_espace_comprehension`
- [x] `maths_positive_produit_scalaire_espace_methode`
- [x] `maths_positive_produit_scalaire_espace_application`
- [x] `maths_positive_produit_scalaire_espace_diagnostic`
- [x] `maths_positive_produit_scalaire_espace_transfert`

##### Notion `succession_epreuves` — 5 cas

- [x] `maths_positive_succession_epreuves_comprehension`
- [x] `maths_positive_succession_epreuves_methode`
- [x] `maths_positive_succession_epreuves_application`
- [x] `maths_positive_succession_epreuves_diagnostic`
- [x] `maths_positive_succession_epreuves_transfert`

##### Notion `variables_aleatoires_esperance` — 5 cas

- [x] `maths_positive_variables_aleatoires_esperance_comprehension`
- [x] `maths_positive_variables_aleatoires_esperance_methode`
- [x] `maths_positive_variables_aleatoires_esperance_application`
- [x] `maths_positive_variables_aleatoires_esperance_diagnostic`
- [x] `maths_positive_variables_aleatoires_esperance_transfert`

##### Notion `loi_grands_nombres` — 5 cas

- [x] `maths_positive_loi_grands_nombres_comprehension`
- [x] `maths_positive_loi_grands_nombres_methode`
- [x] `maths_positive_loi_grands_nombres_application`
- [x] `maths_positive_loi_grands_nombres_diagnostic`
- [x] `maths_positive_loi_grands_nombres_transfert`

##### Notion `python` — 5 cas

- [x] `maths_positive_python_comprehension`
- [x] `maths_positive_python_methode`
- [x] `maths_positive_python_application`
- [x] `maths_positive_python_diagnostic`
- [x] `maths_positive_python_transfert`

#### Catégorie sans source (`no_source`) — 10 cas

##### Notion sans notion cible — 10 cas

- [x] `maths_no_source_astrologie`
- [x] `maths_no_source_pronostic_sportif`
- [x] `maths_no_source_cours_crypto`
- [x] `maths_no_source_posologie`
- [x] `maths_no_source_conseil_juridique`
- [x] `maths_no_source_sujet_futur`
- [x] `maths_no_source_correction_privee`
- [x] `maths_no_source_conversation_privee`
- [x] `maths_no_source_meteo`
- [x] `maths_no_source_manuel_prive`

#### Catégorie confusion — 10 cas

##### Notion `suites_limites` — 1 cas

- [x] `maths_confusion_suites_vs_continuite`

##### Notion `derivation_convexite` — 1 cas

- [x] `maths_confusion_convexite_vs_integration`

##### Notion `logarithme` — 1 cas

- [x] `maths_confusion_logarithme_vs_equation_differentielle`

##### Notion `primitives_integration` — 1 cas

- [x] `maths_confusion_integration_vs_derivation`

##### Notion `equations_differentielles` — 1 cas

- [x] `maths_confusion_equation_differentielle_vs_suite`

##### Notion `combinatoire` — 1 cas

- [x] `maths_confusion_combinatoire_vs_bernoulli`

##### Notion `geometrie_espace` — 1 cas

- [x] `maths_confusion_geometrie_vs_produit_scalaire`

##### Notion `produit_scalaire_espace` — 1 cas

- [x] `maths_confusion_produit_scalaire_vs_incidence`

##### Notion `variables_aleatoires_esperance` — 1 cas

- [x] `maths_confusion_esperance_vs_concentration`

##### Notion `python` — 1 cas

- [x] `maths_confusion_python_vs_preuve`

#### Catégorie adversarial — 10 cas

##### Notion `python` — 2 cas

- [x] `maths_adversarial_system_prompt`
- [x] `maths_adversarial_injection_stockage`

##### Notion `combinatoire` — 1 cas

- [x] `maths_adversarial_secret_environment`

##### Notion `variables_aleatoires_esperance` — 1 cas

- [x] `maths_adversarial_pii_eleves`

##### Notion `logarithme` — 1 cas

- [x] `maths_adversarial_raw_source`

##### Notion `continuite` — 1 cas

- [x] `maths_adversarial_cross_tenant`

##### Notion `suites_limites` — 1 cas

- [x] `maths_adversarial_internal_reasoning`

##### Notion `primitives_integration` — 1 cas

- [x] `maths_adversarial_corpus_integral`

##### Notion `geometrie_espace` — 1 cas

- [x] `maths_adversarial_changement_profil`

##### Notion `loi_grands_nombres` — 1 cas

- [x] `maths_adversarial_exfiltration_encodee`

### NSI — 160 cas

#### Catégorie positive — 130 cas

##### Notion `listes` — 5 cas

- [x] `nsi_positive_listes_comprehension`
- [x] `nsi_positive_listes_methode`
- [x] `nsi_positive_listes_application`
- [x] `nsi_positive_listes_diagnostic`
- [x] `nsi_positive_listes_transfert`

##### Notion `piles` — 5 cas

- [x] `nsi_positive_piles_comprehension`
- [x] `nsi_positive_piles_methode`
- [x] `nsi_positive_piles_application`
- [x] `nsi_positive_piles_diagnostic`
- [x] `nsi_positive_piles_transfert`

##### Notion `files` — 5 cas

- [x] `nsi_positive_files_comprehension`
- [x] `nsi_positive_files_methode`
- [x] `nsi_positive_files_application`
- [x] `nsi_positive_files_diagnostic`
- [x] `nsi_positive_files_transfert`

##### Notion `arbres` — 5 cas

- [x] `nsi_positive_arbres_comprehension`
- [x] `nsi_positive_arbres_methode`
- [x] `nsi_positive_arbres_application`
- [x] `nsi_positive_arbres_diagnostic`
- [x] `nsi_positive_arbres_transfert`

##### Notion `graphes` — 5 cas

- [x] `nsi_positive_graphes_comprehension`
- [x] `nsi_positive_graphes_methode`
- [x] `nsi_positive_graphes_application`
- [x] `nsi_positive_graphes_diagnostic`
- [x] `nsi_positive_graphes_transfert`

##### Notion `dictionnaires` — 5 cas

- [x] `nsi_positive_dictionnaires_comprehension`
- [x] `nsi_positive_dictionnaires_methode`
- [x] `nsi_positive_dictionnaires_application`
- [x] `nsi_positive_dictionnaires_diagnostic`
- [x] `nsi_positive_dictionnaires_transfert`

##### Notion `recursivite` — 5 cas

- [x] `nsi_positive_recursivite_comprehension`
- [x] `nsi_positive_recursivite_methode`
- [x] `nsi_positive_recursivite_application`
- [x] `nsi_positive_recursivite_diagnostic`
- [x] `nsi_positive_recursivite_transfert`

##### Notion `diviser_pour_regner` — 5 cas

- [x] `nsi_positive_diviser_pour_regner_comprehension`
- [x] `nsi_positive_diviser_pour_regner_methode`
- [x] `nsi_positive_diviser_pour_regner_application`
- [x] `nsi_positive_diviser_pour_regner_diagnostic`
- [x] `nsi_positive_diviser_pour_regner_transfert`

##### Notion `programmation_dynamique` — 5 cas

- [x] `nsi_positive_programmation_dynamique_comprehension`
- [x] `nsi_positive_programmation_dynamique_methode`
- [x] `nsi_positive_programmation_dynamique_application`
- [x] `nsi_positive_programmation_dynamique_diagnostic`
- [x] `nsi_positive_programmation_dynamique_transfert`

##### Notion `parcours_graphes` — 5 cas

- [x] `nsi_positive_parcours_graphes_comprehension`
- [x] `nsi_positive_parcours_graphes_methode`
- [x] `nsi_positive_parcours_graphes_application`
- [x] `nsi_positive_parcours_graphes_diagnostic`
- [x] `nsi_positive_parcours_graphes_transfert`

##### Notion `recherche` — 5 cas

- [x] `nsi_positive_recherche_comprehension`
- [x] `nsi_positive_recherche_methode`
- [x] `nsi_positive_recherche_application`
- [x] `nsi_positive_recherche_diagnostic`
- [x] `nsi_positive_recherche_transfert`

##### Notion `tri` — 5 cas

- [x] `nsi_positive_tri_comprehension`
- [x] `nsi_positive_tri_methode`
- [x] `nsi_positive_tri_application`
- [x] `nsi_positive_tri_diagnostic`
- [x] `nsi_positive_tri_transfert`

##### Notion `modele_relationnel` — 5 cas

- [x] `nsi_positive_modele_relationnel_comprehension`
- [x] `nsi_positive_modele_relationnel_methode`
- [x] `nsi_positive_modele_relationnel_application`
- [x] `nsi_positive_modele_relationnel_diagnostic`
- [x] `nsi_positive_modele_relationnel_transfert`

##### Notion `sql` — 5 cas

- [x] `nsi_positive_sql_comprehension`
- [x] `nsi_positive_sql_methode`
- [x] `nsi_positive_sql_application`
- [x] `nsi_positive_sql_diagnostic`
- [x] `nsi_positive_sql_transfert`

##### Notion `contraintes` — 5 cas

- [x] `nsi_positive_contraintes_comprehension`
- [x] `nsi_positive_contraintes_methode`
- [x] `nsi_positive_contraintes_application`
- [x] `nsi_positive_contraintes_diagnostic`
- [x] `nsi_positive_contraintes_transfert`

##### Notion `jointures` — 5 cas

- [x] `nsi_positive_jointures_comprehension`
- [x] `nsi_positive_jointures_methode`
- [x] `nsi_positive_jointures_application`
- [x] `nsi_positive_jointures_diagnostic`
- [x] `nsi_positive_jointures_transfert`

##### Notion `processus` — 5 cas

- [x] `nsi_positive_processus_comprehension`
- [x] `nsi_positive_processus_methode`
- [x] `nsi_positive_processus_application`
- [x] `nsi_positive_processus_diagnostic`
- [x] `nsi_positive_processus_transfert`

##### Notion `protocoles` — 5 cas

- [x] `nsi_positive_protocoles_comprehension`
- [x] `nsi_positive_protocoles_methode`
- [x] `nsi_positive_protocoles_application`
- [x] `nsi_positive_protocoles_diagnostic`
- [x] `nsi_positive_protocoles_transfert`

##### Notion `reseaux` — 5 cas

- [x] `nsi_positive_reseaux_comprehension`
- [x] `nsi_positive_reseaux_methode`
- [x] `nsi_positive_reseaux_application`
- [x] `nsi_positive_reseaux_diagnostic`
- [x] `nsi_positive_reseaux_transfert`

##### Notion `routage` — 5 cas

- [x] `nsi_positive_routage_comprehension`
- [x] `nsi_positive_routage_methode`
- [x] `nsi_positive_routage_application`
- [x] `nsi_positive_routage_diagnostic`
- [x] `nsi_positive_routage_transfert`

##### Notion `securisation` — 5 cas

- [x] `nsi_positive_securisation_comprehension`
- [x] `nsi_positive_securisation_methode`
- [x] `nsi_positive_securisation_application`
- [x] `nsi_positive_securisation_diagnostic`
- [x] `nsi_positive_securisation_transfert`

##### Notion `poo` — 5 cas

- [x] `nsi_positive_poo_comprehension`
- [x] `nsi_positive_poo_methode`
- [x] `nsi_positive_poo_application`
- [x] `nsi_positive_poo_diagnostic`
- [x] `nsi_positive_poo_transfert`

##### Notion `tests_mise_au_point` — 5 cas

- [x] `nsi_positive_tests_mise_au_point_comprehension`
- [x] `nsi_positive_tests_mise_au_point_methode`
- [x] `nsi_positive_tests_mise_au_point_application`
- [x] `nsi_positive_tests_mise_au_point_diagnostic`
- [x] `nsi_positive_tests_mise_au_point_transfert`

##### Notion `gestion_modules` — 5 cas

- [x] `nsi_positive_gestion_modules_comprehension`
- [x] `nsi_positive_gestion_modules_methode`
- [x] `nsi_positive_gestion_modules_application`
- [x] `nsi_positive_gestion_modules_diagnostic`
- [x] `nsi_positive_gestion_modules_transfert`

##### Notion `paradigme_fonctionnel` — 5 cas

- [x] `nsi_positive_paradigme_fonctionnel_comprehension`
- [x] `nsi_positive_paradigme_fonctionnel_methode`
- [x] `nsi_positive_paradigme_fonctionnel_application`
- [x] `nsi_positive_paradigme_fonctionnel_diagnostic`
- [x] `nsi_positive_paradigme_fonctionnel_transfert`

##### Notion `calculabilite_decidabilite` — 5 cas

- [x] `nsi_positive_calculabilite_decidabilite_comprehension`
- [x] `nsi_positive_calculabilite_decidabilite_methode`
- [x] `nsi_positive_calculabilite_decidabilite_application`
- [x] `nsi_positive_calculabilite_decidabilite_diagnostic`
- [x] `nsi_positive_calculabilite_decidabilite_transfert`

#### Catégorie sans source (`no_source`) — 10 cas

##### Notion sans notion cible — 10 cas

- [x] `nsi_no_source_meteo_temps_reel`
- [x] `nsi_no_source_sujet_examen_inedit`
- [x] `nsi_no_source_reparation_materiel_proprietaire`
- [x] `nsi_no_source_diagnostic_medical`
- [x] `nsi_no_source_conseil_juridique`
- [x] `nsi_no_source_cours_crypto_temps_reel`
- [x] `nsi_no_source_api_non_publiee`
- [x] `nsi_no_source_liste_eleves_privee`
- [x] `nsi_no_source_topologie_locale_actuelle`
- [x] `nsi_no_source_preuve_quantique_avancee`

#### Catégorie confusion — 10 cas

##### Notion `piles` — 1 cas

- [x] `nsi_confusion_piles_files`

##### Notion `arbres` — 1 cas

- [x] `nsi_confusion_arbres_graphes`

##### Notion `dictionnaires` — 1 cas

- [x] `nsi_confusion_dictionnaires_modele_relationnel`

##### Notion `programmation_dynamique` — 1 cas

- [x] `nsi_confusion_recursivite_programmation_dynamique`

##### Notion `diviser_pour_regner` — 1 cas

- [x] `nsi_confusion_diviser_dynamique`

##### Notion `sql` — 1 cas

- [x] `nsi_confusion_sql_modele_relationnel`

##### Notion `processus` — 1 cas

- [x] `nsi_confusion_processus_protocoles`

##### Notion `routage` — 1 cas

- [x] `nsi_confusion_reseaux_routage`

##### Notion `securisation` — 1 cas

- [x] `nsi_confusion_protocoles_securisation`

##### Notion `paradigme_fonctionnel` — 1 cas

- [x] `nsi_confusion_poo_fonctionnel`

#### Catégorie adversarial — 10 cas

##### Notion `securisation` — 2 cas

- [x] `nsi_adversarial_injection_prompt_systeme`
- [x] `nsi_adversarial_exfiltration_secrets`

##### Notion `dictionnaires` — 1 cas

- [x] `nsi_adversarial_exfiltration_pii`

##### Notion `gestion_modules` — 1 cas

- [x] `nsi_adversarial_documents_bruts`

##### Notion `sql` — 1 cas

- [x] `nsi_adversarial_sql_destruction`

##### Notion `protocoles` — 1 cas

- [x] `nsi_adversarial_code_malveillant`

##### Notion `reseaux` — 1 cas

- [x] `nsi_adversarial_override_profil`

##### Notion `recherche` — 1 cas

- [x] `nsi_adversarial_citations_inventees`

##### Notion `paradigme_fonctionnel` — 1 cas

- [x] `nsi_adversarial_exfiltration_encodee`

##### Notion `tests_mise_au_point` — 1 cas

- [x] `nsi_adversarial_contenu_non_revu`

## Contrôle attendu de couverture

- Mathématiques : 95 identifiants ;
- NSI : 160 identifiants ;
- total : 255 identifiants uniques ;
- cases cochées à la création de ce paquet : 0.

Ces cardinalités sont un contrôle mécanique de préparation. Elles ne prouvent pas que la revue humaine a eu lieu.
