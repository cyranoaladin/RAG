# Politique de nettoyage — RAG workspace

## 1. Objectif

Définir une politique exploitable pour préparer le nettoyage du workspace RAG sans effectuer de suppression, de déplacement ou d'archivage automatique. Cette politique sert uniquement à classer les fichiers et à encadrer les dry-runs.

## 2. Principes

- Aucun nettoyage sans dry-run.
- Aucun nettoyage sans validation humaine.
- Aucun nettoyage dans rag-local sans instruction explicite.
- Aucun secret supprimé automatiquement.
- Aucun ledger supprimé automatiquement.
- Aucun document source supprimé automatiquement.
- Aucun fichier d’infra production supprimé automatiquement.

## 3. Périmètre

- workspace : /home/alaeddine/Bureau/RAG
- dépôt actif : rag-pedago
- dépôt historique : rag-local en lecture seule

Le lot 16B ne crée aucune archive réelle, ne déplace aucun fichier et ne supprime aucun fichier.

## 4. Catégories

### A. Supprimables après validation humaine

- __pycache__
- fichiers .pyc
- caches pytest
- caches ruff/mypy
- fichiers temporaires évidents

Ces éléments sont seulement des candidats. Leur présence dans un dry-run ne vaut pas autorisation de suppression.

### B. À ignorer via .gitignore

- caches Python
- caches pytest
- caches ruff/mypy
- fichiers temporaires
- sorties runtime non validées

Les règles d'ignore ne doivent pas masquer les rapports Codex, les fixtures synthétiques, les docs, les tests, les schémas ou les taxonomies.

### C. À archiver avant suppression

- rapports runtime massifs
- anciens batch reports
- anciens tree.txt
- patch/diff historiques après revue

L'archivage réel doit faire l'objet d'un lot dédié, avec validation humaine de la destination et du périmètre.

### D. À conserver

- rapports Codex de lots
- protocoles
- fixtures synthétiques
- schémas
- taxonomies
- tests
- docs d’architecture
- rag_pedago/paths.py

### E. À ne jamais supprimer automatiquement

- .env
- .env.bak_*
- creds
- credentials
- clés .pem/.key
- bases SQLite
- ledgers
- uploads
- raw
- fichiers d’infra production
- historiques Git

Ces éléments peuvent être signalés pour revue humaine, mais ils ne doivent jamais être supprimés par automatisation de nettoyage.

### F. À examiner humainement

- patch/diff
- anciens dumps
- anciens tree.txt
- bases locales
- rapports runtime non versionnés
- fichiers sensibles par nom

## 5. Règles de dry-run

Le dry-run doit :

- lire `configs/cleanup_policy.yml` ;
- parcourir `/home/alaeddine/Bureau/RAG` sans suivre les symlinks ;
- ignorer les répertoires `.git` ;
- signaler `rag-local` comme dépôt en lecture seule ;
- classer les chemins par catégorie ;
- afficher des compteurs et des exemples ;
- afficher `would_delete: 0` ;
- afficher `would_move: 0` ;
- ne rien supprimer ;
- ne rien déplacer ;
- ne rien écrire ;
- ne pas ouvrir les fichiers sensibles ;
- ne pas lire le contenu des `.env`.

Le script de dry-run ne doit pas proposer de mode destructif.

## 6. Règles de commit

Un commit de politique ou de dry-run doit inclure uniquement :

- la documentation de politique ;
- la configuration de classification ;
- le script dry-run ;
- la cible Makefile non destructive ;
- les tests unitaires ;
- le rapport Codex du lot ;
- les règles `.gitignore` sûres si elles manquaient.

Il ne doit pas inclure de fichiers supprimés, déplacés, archivés, ni de sorties runtime produites par un nettoyage réel.

## 7. Règles avant un vrai nettoyage

Avant tout nettoyage réel :

1. exécuter le dry-run ;
2. relire les catégories et les compteurs ;
3. valider humainement les chemins ciblés ;
4. exclure explicitement secrets, ledgers, bases, uploads, raw, infra production et historiques Git ;
5. définir si l'action prévue est une suppression ou un archivage ;
6. créer un lot dédié avec commandes exactes, tests et rollback documentaire ;
7. ne jamais appliquer un nettoyage à `rag-local` sans instruction explicite.

## 8. Optimisation du dry-run

Certains dossiers très volumineux, comme `rag-local/.venv`, peuvent être exclus du scan profond.

Ces exclusions ne signifient pas que les dossiers sont supprimables. Elles signifient seulement qu’ils sont signalés comme racines lourdes à traiter séparément.

Les compteurs du dry-run sont des observations de l’état courant du workspace. Ils peuvent varier si de nouveaux rapports runtime, caches ou fichiers locaux apparaissent. Ils ne constituent pas une autorisation de suppression. La décision de nettoyage doit s’appuyer sur une revue humaine des chemins, pas sur les compteurs seuls.

Le dry-run doit rester non destructif :
- would_delete: 0 ;
- would_move: 0 ;
- aucun fichier supprimé ;
- aucun fichier déplacé ;
- aucun secret lu.
