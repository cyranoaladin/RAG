# Protocole de décision humaine — cleanup review

## 1. Objectif

Transformer le paquet de revue en brouillon de décision humaine sans appliquer aucune action.

## 2. Principes

- Aucune décision n’est appliquée automatiquement.
- Aucune suppression.
- Aucun déplacement.
- Aucune archive.
- Aucun fichier de rag-local n’est modifié.
- Les compteurs sont observationnels.
- Les chemins listés ne valent pas autorisation d’action.
- Toute future suppression ou archive doit être validée dans un lot séparé.

## 3. États de décision

Les états autorisés sont :

- KEEP_REQUIRED
- EXCLUDE_FROM_ACTION
- REVIEW_REQUIRED
- FUTURE_ARCHIVE_CANDIDATE
- FUTURE_DELETE_CANDIDATE
- NEVER_DELETE
- READONLY_REPOSITORY
- DEEP_SCAN_EXCLUDED
- UNDECIDED

## 4. Règles de décision par catégorie

### always_keep_matches

État par défaut : KEEP_REQUIRED.

### never_delete_matches

État par défaut : NEVER_DELETE.

### readonly_repo_matches

État par défaut : READONLY_REPOSITORY.

### deep_scan_exclusions

État par défaut : DEEP_SCAN_EXCLUDED.

### summarize_only_roots

État par défaut : DEEP_SCAN_EXCLUDED.

### archive_candidates

État par défaut : FUTURE_ARCHIVE_CANDIDATE.

Aucune archive n’est créée dans ce lot.

### safe_delete_candidates

État par défaut : FUTURE_DELETE_CANDIDATE.

Aucune suppression n’est réalisée dans ce lot.

## 5. Règles de sortie

- Markdown uniquement.
- Échantillons limités.
- Tri stable.
- Pas de contenu de fichiers sensibles.
- Pas de lecture de .env.
- Pas de secret lu.
- Pas d’action automatique.

## 6. Conditions avant tout futur lot d’action

Avant toute suppression ou archive réelle :

- chemins explicitement listés ;
- validation humaine écrite ;
- séparation stricte suppression / archivage ;
- rollback documentaire ;
- nouvelle exécution des tests ;
- exclusion de rag-local sauf instruction explicite.
