# Protocole de revue humaine des sources metadata-only

## 1. Objectif

Définir une procédure de revue humaine avant toute admission réelle de source pédagogique, sans document réel, sans ingestion, sans parsing, sans chunking, sans embeddings et sans Qdrant.

## 2. Périmètre

Le protocole suit les lots 17C, 17D, 17E et 17F :

- scope pilote mathématiques terminale spécialité ;
- évaluation retrieval metadata-only ;
- contrat d’interface pédagogique metadata-only ;
- politique d’admission des sources metadata-only.

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

Rôles autorisés :

- reviewer_pedagogique ;
- reviewer_droits ;
- reviewer_technique ;
- responsable_validation.

## 5. Étapes de revue

- vérifier le périmètre pédagogique ;
- vérifier les droits ;
- vérifier la provenance ;
- vérifier l’absence de données personnelles ;
- vérifier l’absence de fichier réel ;
- vérifier la visibilité ;
- vérifier la décision proposée ;
- vérifier le motif de refus ou d’admission ;
- exiger une validation finale humaine.

## 6. Décisions de revue autorisées

- approve_metadata_only ;
- reject_real_document ;
- reject_unknown_rights ;
- reject_private_data ;
- request_more_information ;
- defer_until_real_source_lot.

## 7. Conditions minimales d’approbation

Une source ne peut recevoir `approve_metadata_only` que si :

- aucun fichier réel n’est attaché ;
- aucun chemin réel n’est déclaré ;
- aucune URL réelle n’est requise ;
- droits sûrs ;
- licence sûre ;
- pas de données personnelles ;
- provenance connue ;
- visibilité contrôlée ;
- revue pédagogique effectuée ;
- revue droits effectuée ;
- revue technique effectuée ;
- validation responsable effectuée.

## 8. Conditions avant admission réelle

Avant toute admission réelle :

- source réelle listée dans un lot séparé ;
- droits confirmés ;
- fichier réel explicitement autorisé dans un lot séparé ;
- checksum prévu ;
- parsing loti séparément ;
- chunking loti séparément ;
- embeddings lotis séparément ;
- Qdrant loti séparément ;
- rollback prévu ;
- tests et doctors verts.

## 9. Couverture minimale de revue

Une revue prête pour validation exige :

- chaque rôle requis représenté au moins une fois ;
- une revue pédagogique ;
- une revue droits ;
- une revue technique ;
- une validation responsable ;
- aucune validation finale portée par un rôle non responsable.

## 10. Cohérence des décisions par source

Une source ne peut pas être simultanément approuvée et rejetée.

Une source ne peut pas être simultanément approuvée et différée vers un lot réel.

Toute décision `approve_metadata_only` doit être portée par `responsable_validation`.

Toute décision `defer_until_real_source_lot` doit être portée par `responsable_validation`.
