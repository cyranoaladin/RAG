# Protocole de consolidation de la chaîne metadata-only

## 1. Objectif

Vérifier la cohérence complète de la chaîne de gouvernance metadata-only 17C à 17I, sans source réelle, sans document réel, sans ingestion, sans parsing, sans chunking, sans embeddings et sans Qdrant.

## 2. Lots couverts

- 17C : pilot_corpus_scope ;
- 17D : retrieval_metadata_eval ;
- 17E : pedago_interface_contract ;
- 17F : source_admission_policy ;
- 17G : human_source_review ;
- 17H : controlled_readiness ;
- 17I : transition_authorization.

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

## 4. Invariants de chaîne

La chaîne est cohérente si :

- chaque lot référence correctement les lots antérieurs ;
- chaque identifiant attendu est stable ;
- chaque cible Makefile metadata-only est classée SAFE_METADATA_ONLY ;
- aucune cible sensible n’est nouvellement ajoutée ;
- chaque rapport existe ;
- chaque protocole existe ;
- chaque configuration existe ;
- chaque script d’audit existe ;
- chaque test associé existe ;
- chaque audit sort un état prêt pour revue ;
- aucune étape ne prétend autoriser un corpus réel ;
- aucune étape ne manipule un fichier réel ;
- aucune étape ne crée data/staging ;
- aucune étape ne lit .env ;
- les prochaines étapes restent explicitement séparées et validées humainement.

## 5. Décisions autorisées

- chain_ready_for_metadata_review ;
- chain_requires_human_review ;
- chain_blocked_for_real_corpus ;
- chain_requires_followup_metadata_lot.

## 6. Conditions bloquantes

La chaîne doit être bloquée si :

- un identifiant de lot est incohérent ;
- une référence 17C à 17I manque ;
- une cible Makefile n’est pas classée ;
- une cible sensible est classée sûre à tort ;
- un rapport manque ;
- un protocole manque ;
- une configuration manque ;
- un script d’audit manque ;
- un test manque ;
- une sortie ne contient pas le statut attendu ;
- un fichier réel est mentionné comme autorisé ;
- data/staging est créé ;
- un lot futur réel est implicitement autorisé.

## 7. Décision finale attendue

Le lot 17J ne valide pas une décision générale quelconque.

Pour être prêt pour revue, la chaîne doit porter explicitement :

- `decision: chain_ready_for_metadata_review` ;
- `decision_reason: metadata_governance_chain_complete`.

Les autres décisions autorisées restent documentées comme états de refus ou de suivi, mais elles ne peuvent pas produire `chain_ready_for_review: true`.
