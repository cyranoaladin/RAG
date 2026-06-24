# Rapport d’audit — Lot 14 avant commit

## 1. État Git initial

Commande exécutée :

```bash
pwd
git status --short --branch
git log --oneline --decorate --max-count=15
git diff --stat HEAD
git diff --name-status HEAD
git ls-files --others --exclude-standard
```

Résultat synthétique :

- dépôt courant : `/home/alaeddine/Bureau/rag-pedago` ;
- branche : `main` ;
- fichiers modifiés suivis : `AGENTS.md`, `Makefile`, `README.md` ;
- fichiers non suivis : documentation lot 14, contrats YAML, README locaux,
  `rag_pedago/project_doctor.py`, tests projet, rapport Codex lot 14.

## 2. Dernier commit connu

Dernier commit :

```text
0fa3756 feat: add review and controlled import audit ledger
```

Ce commit correspond au lot 13 : audit runtime des review packages, décisions
humaines et imports contrôlés dans le ledger SQLite.

## 3. Objectif probable du lot 14

Le lot 14 vise à rendre le dépôt plus exploitable par des agents et LLM de
développement sans ajouter de nouvelle capacité d'ingestion.

Hypothèse d'objectif :

- mettre à jour le README pour refléter l'état réel du projet ;
- créer un guide agent plus opérationnel ;
- documenter l'architecture et les workflows ;
- ajouter des contrats YAML machine-readable ;
- ajouter un `project-doctor` pour vérifier docs, contrats, `.gitignore`,
  secrets évidents, imports réseau interdits et patterns d'ouverture
  `source_uri` ;
- ajouter des README locaux dans les dossiers critiques ;
- ajouter des tests de contrats projet.

## 4. Fichiers modifiés

- `AGENTS.md`
- `Makefile`
- `README.md`

## 5. Fichiers créés

- `data/fixtures/README.md`
- `data/reference/README.md`
- `data/reports/README.md`
- `data/reports/codex_lot_14_agent_ready_architecture.md`
- `data/reports/codex_lot_14_audit_before_commit.md`
- `docs/ARCHITECTURE.md`
- `docs/LOT_STATUS.md`
- `docs/WORKFLOWS.md`
- `docs/contracts/README.md`
- `docs/contracts/commands.yml`
- `docs/contracts/invariants.yml`
- `docs/contracts/pipeline_contract.yml`
- `docs/contracts/runtime_artifacts.yml`
- `rag_pedago/imports/README.md`
- `rag_pedago/ledger/README.md`
- `rag_pedago/project_doctor.py`
- `rag_pedago/reference/README.md`
- `schema/README.md`
- `taxonomy/README.md`
- `tests/README.md`
- `tests/unit/test_project_contracts.py`
- `tests/unit/test_project_doctor.py`

## 6. Analyse de cohérence avec AGENTS.md

Points cohérents :

- le lot reste limité à documentation, contrats, diagnostics projet et tests ;
- aucune ingestion documentaire n'est ajoutée ;
- aucune lecture `source_uri` n'est ajoutée ;
- aucune connexion Qdrant, PostgreSQL ou LLM n'est ajoutée ;
- le rapport Codex du lot 14 est présent ;
- les tests ciblés du lot existent.

Point bloquant :

- la nouvelle version de `AGENTS.md` remplace l'ancien contenu au lieu de
  l'étendre. Plusieurs règles historiques importantes disparaissent :
  - ne jamais modifier `schema/document.py` sans tâche dédiée ;
  - ne jamais modifier les taxonomies officielles à la main ;
  - ne jamais réécrire un document source ;
  - ne jamais réindexer un chunk dont le hash n'a pas changé ;
  - ne jamais lancer de scraping massif non limité ;
  - ne jamais mélanger documents propriétaires Nexus et ressources publiques
    sans métadonnée de visibilité ;
  - ne jamais exposer une ressource propriétaire dans une réponse publique ;
  - ne jamais utiliser un LLM pour décider seul d'une classification finale sans
    validation ;
  - exigences de module livré : logs structurés, gestion d'erreur, reprise,
    rapport de sortie et documentation.

Cette suppression affaiblit le contrat agent. Elle doit être corrigée avant
commit en réintégrant ces règles dans le nouveau `AGENTS.md`.

## 7. Analyse des risques

Risques faibles :

- `project_doctor.py` est local, sans réseau, sans suppression et sans écriture
  runtime.
- Les contrats YAML sont déclaratifs.
- Les README locaux n'affectent pas le pipeline.

Risques à corriger :

- `AGENTS.md` perd des garde-fous métier et production déjà validés dans les
  lots antérieurs.
- `project_doctor.py` vérifie les chaînes sensibles dans les fichiers suivis en
  excluant tous les fichiers sous `docs/`, alors que l'intention formulée est
  plutôt "hors docs exemples". Ce point n'est pas bloquant pour le lot 14, mais
  il mérite d'être clarifié si le doctor devient une barrière de commit stricte.
- `docs/PIPELINE.md` et `docs/OPERATIONS.md` sont absents. Ce n'est pas une
  régression du lot 14, mais la demande d'audit les mentionnait comme documents
  de pilotage potentiels.

## 8. Tests exécutés

Commandes exécutées :

```bash
make doctor
make test
make project-doctor
find . -type f \( -name "*.env" -o -name "*secret*" -o -name "*credential*" -o -name "*creds*" -o -name "*gdrive*" -o -name "*.pem" -o -name "*.key" \) -print
```

## 9. Résultats

- `make doctor` : OK.
- `make test` : 274 passed.
- `make project-doctor` : OK.
- Recherche fichiers sensibles : aucun résultat.

## 10. Secrets et fichiers sensibles

La commande de recherche de fichiers sensibles n'a retourné aucun fichier.

Le seul fichier d'environnement autorisé reste `.env.example`; il n'a pas été
signalé par la commande fournie.

## 11. Verdict

CORRECTIONS_NÉCESSAIRES

Raison : le lot 14 est techniquement cohérent et les tests passent, mais le
nouveau `AGENTS.md` supprime plusieurs règles historiques importantes. Le commit
doit attendre une correction ciblée réintégrant ces garde-fous.

## 12. Message de commit proposé

Non proposé car le verdict n'est pas `COMMIT_RECOMMANDÉ`.
