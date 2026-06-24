# Protocole d'autorisation de transition metadata-only

## 1. Objectif

Définir les conditions déclaratives permettant d'autoriser, plus tard, un lot réel séparé, sans encore admettre de source réelle, sans document réel, sans ingestion, sans parsing, sans chunking, sans embeddings et sans Qdrant.

## 2. Périmètre

Le protocole s'appuie sur les lots 17C à 17H :

- scope pilote mathématiques terminale spécialité ;
- retrieval metadata-only ;
- interface pédagogique metadata-only ;
- admission des sources metadata-only ;
- revue humaine metadata-only ;
- controlled readiness metadata-only.

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

## 4. Conditions d'autorisation

Une transition vers un futur lot réel ne pourra être autorisée que si :

- tous les gates 17C à 17H sont validés ;
- une validation humaine finale est requise ;
- les droits sont confirmés ;
- la provenance est connue ;
- les données personnelles sont absentes ou explicitement bloquées ;
- la visibilité est contrôlée ;
- le rollback est défini ;
- les checksums sont prévus ;
- le parsing est loti séparément ;
- le chunking est loti séparément ;
- les embeddings sont lotis séparément ;
- Qdrant est loti séparément ;
- le futur lot réel est nominatif, séparé et explicitement autorisé.

## 5. Décisions d'autorisation autorisées

- authorize_metadata_only_preparation ;
- require_final_human_signoff ;
- block_real_corpus_transition ;
- defer_to_separate_real_lot.

## 6. Conditions bloquantes

La transition doit être bloquée si :

- un gate 17C à 17H manque ;
- une preuve manque ;
- un document réel est mentionné ;
- un chemin réel est déclaré ;
- une URL externe est requise ;
- les droits sont inconnus ;
- des données personnelles sont présentes ;
- le rollback manque ;
- les checksums manquent ;
- un pipeline réel est demandé ;
- une cible sensible est appelée.

## 7. Conditions avant futur lot réel

Le futur lot réel devra être séparé et devra préciser :

- sources réelles nominatives ;
- chemins contrôlés ;
- droits ;
- validation humaine ;
- rollback ;
- checksums ;
- parsing ;
- chunking ;
- embeddings ;
- Qdrant ;
- tests ;
- doctors ;
- plan de retour arrière.

## 8. Couverture des décisions d'autorisation

Une politique prête pour revue doit couvrir explicitement toutes les décisions d'autorisation critiques :

- authorize_metadata_only_preparation ;
- require_final_human_signoff ;
- block_real_corpus_transition ;
- defer_to_separate_real_lot.

Aucune décision déclarée comme autorisée ne doit rester non exercée dans les cas de test déclaratifs.

## 9. Report vers un lot réel séparé

La décision `defer_to_separate_real_lot` ne vaut pas autorisation de corpus réel.

Elle signifie uniquement :

- le futur lot réel devra être séparé ;
- il devra être nominatif ;
- il devra contenir sa propre validation humaine ;
- il devra définir rollback, checksums, parsing, chunking, embeddings et Qdrant dans des lots dédiés ;
- aucun fichier réel ne peut être manipulé dans le lot courant.
