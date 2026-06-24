# Protocole de dossier de revue humaine metadata-only

## 1. Objectif

Préparer un dossier de revue humaine de la chaîne metadata-only 17C à 17J, sans source réelle, sans document réel, sans ingestion, sans parsing, sans chunking, sans embeddings et sans Qdrant.

## 2. Lots couverts

- 17C : pilot_corpus_scope ;
- 17D : retrieval_metadata_eval ;
- 17E : pedago_interface_contract ;
- 17F : source_admission_policy ;
- 17G : human_source_review ;
- 17H : controlled_readiness ;
- 17I : transition_authorization ;
- 17J : metadata_governance_chain.

## 3. Interdictions

- aucun document réel ;
- aucun PDF ;
- aucun DOCX ;
- aucun PPTX ;
- aucun XLSX ;
- aucune ingestion ;
- aucun parsing ;
- aucun chunking ;
- aucun embedding ;
- aucun Qdrant ;
- aucun réseau ;
- aucun serveur ;
- aucune API réelle ;
- aucun data/staging.

## 4. Rôles de revue humaine

- reviewer_pedagogique ;
- reviewer_droits ;
- reviewer_technique ;
- responsable_validation.

## 5. Questions de revue

Le dossier doit permettre de vérifier :

- la cohérence des identifiants ;
- la cohérence des références entre lots ;
- la cohérence des décisions finales ;
- l’absence d’autorisation réelle ;
- l’absence de manipulation documentaire ;
- la présence de validations humaines requises ;
- la présence de rollback à lotir séparément ;
- la présence de checksums à lotir séparément ;
- la séparation des futurs lots réels ;
- l’absence de dette de sécurité évidente.

## 6. Décisions de handoff autorisées

- ready_for_human_metadata_review ;
- require_more_metadata_hardening ;
- block_any_real_action ;
- defer_until_named_followup_lot.

## 7. Conditions bloquantes

Le handoff est bloqué si :

- un lot 17C à 17J manque ;
- un rapport manque ;
- un protocole manque ;
- une configuration manque ;
- une validation humaine requise manque ;
- une décision finale est ambiguë ;
- une autorisation réelle apparaît ;
- un fichier réel est mentionné comme utilisable ;
- data/staging est créé ;
- une cible sensible est introduite ;
- une prochaine étape réelle est implicite.

## 8. Couverture complète des décisions de handoff

Le dossier de handoff doit couvrir toutes les décisions déclarées comme critiques :

- ready_for_human_metadata_review ;
- require_more_metadata_hardening ;
- block_any_real_action ;
- defer_until_named_followup_lot.

Une décision autorisée mais non couverte par un cas déclaratif est une dette de gouvernance.

La décision `require_more_metadata_hardening` signifie uniquement qu’un durcissement metadata-only reste nécessaire. Elle n’autorise aucune action réelle, aucun document réel, aucun pipeline et aucun corpus.
