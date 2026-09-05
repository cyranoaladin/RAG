# Candidats d’autorisation de production 2026-2027 — plan d’implémentation

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development to execute this plan task-by-task, with fresh review between tasks.

**Goal:** Produire et vérifier les 18 `ScopeAuthorizationArtifactV2` qui
partitionnent exactement les 26 contenus finaux, puis ouvrir une PR prête pour
la revue humaine exacte.

**Architecture:** Un script `rag-pedago` relit les preuves figées de la release
profils et compose les modèles existants `nexus-contracts`. Il refuse toute
dérive et écrit les fichiers canoniques, une matrice d’audit et le rapport de
lot. Aucun binding ni set n’est simulé avant la revue/signature réelle.

**Tech Stack:** Python 3.11, Pydantic/nexus-contracts, PyYAML, pytest, ruff,
mypy, Git/GitHub CLI.

---

### Task 1: Établir le contrat de génération en RED

**Files:**

- Create: `services/rag-pedago/tests/test_production_authorization_candidates.py`
- Reference: `docs/reports/release_scope_placement_20260825.jsonl`
- Reference: `services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/`

1. Écrire les tests de chargement du module attendu et des constantes figées.
2. Exiger 18 autorisations, union 26, digest final exact et zéro overlap/gap/extra.
3. Exiger la correspondance exacte scope/profil/manifest pour chaque placement.
4. Exiger byte-for-byte le template `pii_absence_evidence` fixé par la spec.
5. Exécuter le seul nouveau fichier de tests et constater l’échec par absence
   du producteur.
6. Commit: `rag-pedago: définir le contrat des autorisations production`.

### Task 2: Implémenter le producteur minimal en GREEN

**Files:**

- Create: `services/rag-pedago/scripts/build_production_authorization_candidates.py`
- Modify: `services/rag-pedago/tests/test_production_authorization_candidates.py`

1. Exiger `--source-commit`, résoudre son tree et refuser tout couple différent
   de `3566caf…` / `8c5081…` pour cette release.
2. Lire les JSON/JSONL/YAML comme blobs Git du tree exact, avec chemins
   littéraux et erreurs fail-closed ; ne lire aucune preuve via le worktree.
3. Vérifier les digests liés par `authority_bindings.json` et l’agrégat.
4. Indexer les 26 artefacts release et refuser toute collision ou absence.
5. Vérifier PII/currentness/droits/domaine pour chaque contenu.
6. Grouper par tuple exact profil/scope et construire 18 modèles V2 canoniques.
7. Enregistrer commit/tree, blob IDs et SHA-256 de chaque input consommé.
8. Relancer les tests ciblés jusqu’au GREEN, sans encore écrire les sorties.
9. Commit: `rag-pedago: construire les candidats d’autorisation production`.

### Task 3: Couvrir les mutations de preuves en RED puis GREEN

**Files:**

- Modify: `services/rag-pedago/tests/test_production_authorization_candidates.py`
- Modify: `services/rag-pedago/scripts/build_production_authorization_candidates.py`

1. Ajouter des mutations isolées : digest, placement, overlap, PII, currentness,
   zone, domaine, droits, profil, contenu manquant et contenu supplémentaire.
2. Constater au moins un échec réel pour chaque nouveau chemin non implémenté.
3. Ajouter le minimum de validations pour rendre chaque mutation verte.
4. Refactorer les index et erreurs sans élargir le protocole.
5. Commit: `rag-pedago: verrouiller les preuves des autorisations production`.

### Task 4: Matérialiser et rejouer les sorties canoniques

**Files:**

- Modify: `services/rag-pedago/scripts/build_production_authorization_candidates.py`
- Modify: `services/rag-pedago/tests/test_production_authorization_candidates.py`
- Create: `governance/authorizations/*.json`
- Create: `docs/reports/production_authorization_matrix_20260825.json`

1. Ajouter un mode `--write` atomique au niveau fichier et un mode `--check`.
2. Écrire 18 artefacts et la matrice, puis relire chaque artefact avec le parseur
   contractuel.
3. Tester qu’un fichier manquant, supplémentaire ou modifié fait échouer
   `--check`.
4. Prouver le replay byte-identique dans un répertoire temporaire.
5. Commit: `rag-pedago: matérialiser les autorisations production`.

### Task 5: Produire le rapport et vérifier le lot complet

**Files:**

- Create: `docs/reports/lot_production_authorization_candidates_20260825.md`
- Modify: `docs/reports/master_go_live_state_20260815.md`
- Modify: `docs/reports/master_go_live_state_20260815.json`

1. Reporter `N=26`, `M=18`, union/gap/overlap/extra et les digests exacts.
2. Reporter par scope les paths/digests droits et currentness dans la matrice,
   et préciser qu’ils sont liés par le HEAD de review/H2 plutôt que par des
   champs inexistants de `ScopeAuthorizationArtifactV2`.
3. Déclarer explicitement bindings/set/campagne/republish/H2 encore faux tant
   qu’ils n’ont pas été réellement exécutés.
4. Exécuter les tests ciblés puis les suites contrats/rag-pedago concernées.
5. Exécuter ruff, mypy ciblé, gouvernance locks, repository controls, gitleaks
   différentiel et tests mutation/adversariaux applicables.
6. Commit: `rag-pedago: consigner le lot d’autorisations production`.

### Task 6: Revues contradictoires, CI et PR exacte

**Files:** Tous les fichiers du lot.

1. Faire une revue correctness et une revue security fraîches du diff final.
2. Corriger chaque finding en TDD, puis rejouer les vérifications impactées.
3. Pousser la branche et ouvrir une PR unique vers `main`.
4. Attendre CI GitHub verte et zéro thread non résolu.
5. Figer base/head, calculer le challenge exact et demander la vraie review
   humaine autorisée sans simuler l’identité.
6. Ne jamais fusionner cette PR : son état ouvert et son HEAD immuable font
   partie de l’autorité révocable définie par ADR-0032.
7. S’arrêter à `=== HUMAN GATE — PRODUCTION AUTHORIZATION PR ===`.

### Task 7: Émettre les bindings opérateur avant toute fermeture

**Files:** Artefacts exacts de la PR d’autorité ouverte ; sorties opérateur
hors branche d’autorité.

1. Revalider live que la PR est ouverte, non draft, approuvée au HEAD exact et
   que le challenge/reviewer sont valides.
2. Préparer ensemble les 18 commandes `issue_review_binding_cli.py issue`, une
   par `authorization_id`, avec le même PR/HEAD exact.
3. Présenter `=== OPERATOR SIGNING GATE — REVIEW BINDINGS ===` sans demander,
   lire ou journaliser la clé privée.
4. Créer un checkout détaché propre au commit de confiance `3566caf…`, vérifier
   son tree `8c5081…` et exécuter exclusivement le producteur fusionné de ce
   checkout ; ne jamais exécuter le code Python de la branche candidate avec
   accès à la clé.
5. L’opérateur exécute les commandes depuis son poste avec accès GitHub et la
   clé détenue localement ; aucun secret ne transite par Git, CI ou serveur.
6. Vérifier localement chaque reçu contre l’ancre publique, son artefact exact
   et son digest, puis conserver les 18 reçus pour le lot AuthorizationSet.
7. Dans le lot de release suivant, matérialiser sous les chemins gouvernés des
   copies byte-identiques des 18 artefacts et bindings ; revérifier tous les
   digests/signatures avant de construire le set, sans pointer H2 vers le
   worktree d’autorité.
8. Garder la PR ouverte et la branche inchangée pendant toute la validité.
