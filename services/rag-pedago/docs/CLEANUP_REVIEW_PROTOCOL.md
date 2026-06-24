# Protocole de revue humaine du cleanup dry-run

## 1. Objectif

Transformer les résultats du dry-run en paquet de revue humaine.

## 2. Principes

- Le dry-run ne supprime rien.
- Le paquet de revue ne supprime rien.
- Le paquet de revue ne déplace rien.
- Le paquet de revue ne crée aucune archive.
- Les compteurs sont observationnels.
- Les chemins listés ne valent pas autorisation d’action.
- Les secrets, ledgers, bases, uploads, raw, infra/creds et historiques Git ne doivent jamais être supprimés automatiquement.
- rag-local reste read-only.

## 3. Catégories de revue

- safe_delete_candidates
- archive_candidates
- never_delete_matches
- always_keep_matches
- readonly_repo_matches
- deep_scan_exclusions
- summarize_only_roots

## 4. Décisions humaines possibles

Pour chaque catégorie, la seule décision possible à ce stade est :

- conserver ;
- ignorer ;
- archiver dans un futur lot dédié ;
- supprimer dans un futur lot dédié ;
- examiner manuellement ;
- exclure explicitement du périmètre.

Aucune décision ne doit être appliquée par le lot 16D.

## 5. Règles de sortie

- échantillons limités ;
- tri stable ;
- pas de contenu de fichiers sensibles ;
- pas de lecture de .env ;
- pas de lecture de secrets ;
- pas de scan profond des racines exclues ;
- pas de sortie massive non maîtrisée.

## 6. Conditions avant tout futur nettoyage

Un futur nettoyage ne peut être envisagé que si :

- le rapport de revue est relu humainement ;
- le périmètre exact est validé ;
- les chemins sont listés explicitement ;
- les actions sont séparées : suppression ou archivage ;
- un rollback documentaire est prévu ;
- rag-local reste exclu sauf instruction explicite.
