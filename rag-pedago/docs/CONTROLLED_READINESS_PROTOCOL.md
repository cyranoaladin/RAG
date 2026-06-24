# Protocole de transition contrôlée metadata-only

## 1. Objectif

Définir un gate de transition contrôlée avant toute source réelle, sans document réel, sans ingestion, sans parsing, sans chunking, sans embeddings et sans Qdrant.

## 2. Périmètre

Le protocole agrège les lots 17C, 17D, 17E, 17F et 17G :

- scope pilote mathématiques terminale spécialité ;
- évaluation retrieval metadata-only ;
- contrat d’interface pédagogique metadata-only ;
- politique d’admission des sources metadata-only ;
- revue humaine metadata-only.

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

## 4. Gates préalables obligatoires

- pilot_scope_gate ;
- retrieval_metadata_eval_gate ;
- pedago_interface_contract_gate ;
- source_admission_policy_gate ;
- human_source_review_gate ;
- make_target_safety_gate ;
- metadata_preflight_gate ;
- project_doctor_gate.

## 5. Décisions de transition autorisées

- continue_metadata_only ;
- require_human_signoff ;
- defer_real_corpus_lot ;
- do_not_proceed.

## 6. Conditions de revue transitionnelle

Un état prêt pour revue exige :

- tous les gates metadata-only validés ;
- aucune autorisation dangereuse activée ;
- aucune source réelle admise ;
- aucun fichier réel attaché ;
- aucun chemin réel déclaré ;
- aucune URL externe requise ;
- validation humaine requise ;
- rollback à lotir séparément ;
- checksums à lotir séparément ;
- parsing à lotir séparément ;
- chunking à lotir séparément ;
- embeddings à lotir séparément ;
- Qdrant à lotir séparément.

## 7. Conditions avant tout futur lot réel

Un futur lot réel devra être séparé et explicite.

Il devra définir :

- liste nominative des sources réelles ;
- chemins contrôlés ;
- droits confirmés ;
- validations humaines signées ;
- checksums ;
- rollback ;
- parsing ;
- chunking ;
- embeddings ;
- Qdrant ;
- tests et doctors verts.

## 8. Preuves de couverture des gates

Un gate de transition contrôlée prêt pour revue exige une preuve déclarative pour chaque gate requis.

Chaque preuve doit préciser :

- gate_id ;
- evidence_kind ;
- evidence_ref ;
- safe_target ;
- expected_status ;
- destructive_action_allowed ;
- real_document_allowed ;
- network_allowed.

Aucune preuve ne doit pointer vers un document réel, une URL, un fichier bureautique, data/staging ou une cible sensible.

## 9. Cohérence statut / décision

Les décisions de transition doivent rester cohérentes avec le statut du gate :

- passed : continue_metadata_only ou require_human_signoff ;
- blocked : require_human_signoff ou do_not_proceed ;
- deferred : defer_real_corpus_lot ou do_not_proceed.

Aucune décision ne doit autoriser un corpus réel, un fichier réel ou une URL externe.
