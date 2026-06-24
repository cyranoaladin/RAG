# Protocole d’admission des sources pédagogiques metadata-only

## 1. Objectif

Définir les règles d’admission des sources pédagogiques avant tout corpus réel, sans ingestion réelle, sans document réel, sans parsing, sans chunking, sans embeddings et sans Qdrant.

## 2. Périmètre

Le protocole suit les lots 17C, 17D et 17E :

- scope pilote mathématiques terminale spécialité ;
- évaluation retrieval metadata-only ;
- contrat d’interface pédagogique metadata-only.

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

## 4. Sources admissibles

Uniquement des descripteurs metadata-only :

- source officielle décrite par métadonnées ;
- ressource pédagogique synthétique ;
- ressource enseignant décrite sans fichier ;
- référence taxonomique ;
- rapport Codex ;
- protocole interne.

## 5. Sources interdites

- fichier réel ;
- PDF ;
- DOCX ;
- PPTX ;
- XLSX ;
- ressource à droits inconnus ;
- ressource contenant données élève réelles ;
- ressource privée non validée ;
- URL externe non auditée ;
- ressource nécessitant parsing ;
- ressource nécessitant embeddings ou Qdrant.

## 6. Champs metadata obligatoires

Chaque source candidate doit déclarer :

- source_id ;
- title ;
- source_kind ;
- subject ;
- level ;
- track ;
- teaching_status ;
- provenance ;
- rights_status ;
- license_status ;
- visibility ;
- pii_status ;
- real_file_attached ;
- external_url_required ;
- human_review_required ;
- admission_decision ;
- refusal_reason.

## 7. Décisions autorisées

- admit_metadata_only ;
- refuse_real_document ;
- refuse_unknown_rights ;
- refuse_private_data ;
- require_human_review.

## 8. Conditions avant corpus réel

Avant tout corpus réel :

- validation humaine écrite ;
- droits confirmés ;
- source listée ;
- chemin contrôlé ;
- checksum validé ;
- parsing loti séparément ;
- chunking loti séparément ;
- embeddings lotis séparément ;
- Qdrant loti séparément ;
- rollback prévu ;
- tests et doctors verts.

## 9. Cohérence métier d’admission

Une politique prête pour revue exige :

- source_id non vide et unique ;
- title non vide ;
- human_review_required obligatoire ;
- rights_status sûr pour toute admission metadata-only ;
- license_status sûr pour toute admission metadata-only ;
- refusal_reason cohérent avec admission_decision ;
- aucune intersection entre sources admissibles et interdites ;
- aucune décision d’admission inconnue.

## 10. Cas de refus documentaire

Une source décrite comme fichier réel ou format bureautique doit être refusée par décision explicite :

- refuse_real_document ;
- refusal_reason: real_document ;
- real_file_attached: false tant que le lot reste metadata-only.
