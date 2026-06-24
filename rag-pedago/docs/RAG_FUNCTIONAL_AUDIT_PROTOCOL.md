# Protocole d’audit fonctionnel du RAG pédagogique

## 1. Objectif

Évaluer l’état fonctionnel et technique du RAG pédagogique sans lancer d’action réelle. L’audit doit distinguer le socle déjà fiable, les manques, les fragilités, les blocages et les prochains lots recommandés.

## 2. Périmètre

L’audit porte sur le dépôt actif `rag-pedago` :

- documentation projet ;
- schémas ;
- taxonomies ;
- référentiels officiels ;
- fixtures synthétiques ;
- pipeline metadata-only ;
- ledger SQLite ;
- tests ;
- contrats ;
- scripts non destructifs ;
- rapports Codex.

Le dépôt historique `rag-local` reste en lecture seule.

## 3. Interdictions

Pendant l’audit :

- aucun nettoyage réel ;
- aucune suppression ;
- aucun déplacement ;
- aucune archive ;
- aucune ingestion documentaire réelle ;
- aucun parsing de document ;
- aucun scraping ;
- aucun appel réseau ;
- aucun embedding ;
- aucun accès Qdrant ;
- aucune création de `data/staging` ;
- aucune lecture de `.env` ou secret ;
- aucune modification de `rag-local`.

## 4. Couches auditées

Les couches auditées sont :

- objectif produit ;
- corpus et sources ;
- métadonnées ;
- taxonomies et référentiels ;
- pipeline d’import ;
- recherche, retrieval et évaluation ;
- API, interface et usage pédagogique ;
- tests et qualité ;
- sécurité et gouvernance ;
- documentation.

## 5. Méthode de preuve

Les preuves acceptées sont :

- fichiers versionnés ;
- contrats machine-readable ;
- tests unitaires ;
- rapports Codex ;
- sorties de commandes non destructives ;
- inventaires bornés ;
- lectures ciblées de fichiers non sensibles.

La recherche shell doit éviter les motifs ambigus. Les vérifications textuelles doivent utiliser des lectures ciblées, des scripts Python de lecture, ou `rg -F` sur texte exact. Les commandes ne doivent pas contenir de backticks non échappés ni de motifs avec `?` ou `*` non protégés.

## 6. Niveaux de maturité

Les niveaux autorisés sont :

- ABSENT : aucune implémentation ou preuve exploitable ;
- DRAFT : intention ou squelette présent ;
- PARTIAL : fonctionnalité partielle testée mais non exploitable de bout en bout ;
- READY_FOR_PILOT : prêt pour un pilote borné et validé humainement ;
- READY_FOR_REVIEW : prêt pour revue humaine ou technique avant usage ;
- BLOCKED : bloquant pour la prochaine étape visée.

## 7. Classification des dettes

Les dettes sont classées ainsi :

- P0 : bloquant avant tout pilote ;
- P1 : nécessaire avant corpus réel ;
- P2 : amélioration avant usage élève ;
- P3 : confort ou maintenance.

Chaque dette doit être reliée à une preuve observée, un risque et un lot recommandé.

## 8. Conditions avant tout futur pilote

Avant tout pilote :

- périmètre pédagogique explicitement validé ;
- corpus déclaré ou synthétique validé ;
- droits et visibilité qualifiés ;
- critères de pertinence définis ;
- golden set ou jeu de questions créé ;
- garde-fous de non-exposition des contenus privés ;
- revue humaine documentée ;
- tests de non-régression exécutés.

## 9. Conditions avant toute ingestion réelle

Avant toute ingestion réelle :

- validation humaine écrite du périmètre ;
- chemins et sources explicitement listés ;
- droits confirmés ;
- séparation stricte metadata-only, parsing, chunking, embeddings et upsert ;
- rollback documentaire prévu ;
- ledger permanent protégé ;
- `rag-local` exclu sauf instruction explicite ;
- tests et doctors verts après la dernière modification.
