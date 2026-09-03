# Dettes et Traçabilité Historique — LOT 1.2 (Reprise Post-Coupure vers GO_LIVE_READY)

Ce rapport consigne l'historique, les qualifications d'échecs et le statut des dettes techniques
conformément à AGENTS.md (« Un lot ne fait régresser les tests : aucun test vert ne passe au rouge.
Un lot peut être livré avec des échecs préexistants, à condition qu'ils soient tracés […] avec
antériorité prouvée contre le commit parent »).

---

## 1. Contexte et Diagnostic Post-Coupure

Le lot 1.2 a repris après une coupure de courant brutale survenue le 1er septembre 2026.
Un audit forensique en lecture seule a vérifié :
- L'intégrité du système de fichiers et de PostgreSQL 16 (base saine, conteneurs stables).
- L'état des branches et des worktrees (`lot1.2/reprise-post-codex`).
- Les 40 échecs de départ recensés dans `docs/reports/lot_1_2_qualification_echecs.md`, réduits à 11 échecs structurels (7 `rag-engine`, 4 `rag-pedago`).

---

## 2. Statut des Échecs Historiques Qualifiés (C1 à C9)

| Cause | Qualification initiale | Statut dans le Lot 1.2 | Résolution |
|---|---|---|---|
| **C1** | Base de fusion mixte | **Résolu** | Alignement complet des arbres et historiques. |
| **C2** | Manifeste sous `configs/ingestion_profiles` | **Résolu** | Typage et chargement de profils étanches. |
| **C3** | Dérive de version `pypdf` | **Résolu** | Lock strict `pypdf==6.14.2` sur l'ensemble des environnements. |
| **C4** | Épreuves calées sur l'ancienne politique ADR-0041 | **Résolu** | Épreuves réalignées sur les politiques servies sans baisse d'exigence. |
| **C5** | Confrontation de la topologie A (26) à la release B (11) | **Résolu** | Séparation des espaces : fixture dédiée pour l'historique du 25/08, topologie Option A pour la V2. |
| **C6** | Release V1 Option B rejetée par le moteur (`artifact duplicated across subjects`) | **Résolu** | Extension du producteur canonique `build_production_profile_release.py` pour émettre une release de répétition V2 Option A normalisée (`rehearsal_v2`). Triade de tests A/B/C validée. |
| **C7** | Rescellement du mapping de types de documents faux | **Résolu** | Conservation intacte des artefacts historiques sans rescellement in situ destructif. Mapping à 9 types (`3518fe87…`) validé dans la chaîne de release. |
| **C8** | Projection de scopes de retrieval et assertions 26/18 | **Résolu** | Création de la fixture dédiée `services/rag-engine/tests/fixtures/profile_gate_20260825/` rétablissant le contexte exact du 25 août pour tester `load_multilevel_runtime_authorities` et la résolution des 26 placements sans conflit de schéma. |
| **C9** | Interférences `git status` dans les tests | **Résolu** | Isolation des sondes et des répertoires temporaires. |

---

## 3. Bilan d'Exécution des Suites de Tests

Tous les composants de la plateforme RAG Nexus atteignent un état **100% GREEN (0 FAIL)** :

1. **`packages/contracts` & `packages/pdf-page-policy`** :
   - 543 tests passés, 0 échec.
2. **`packages/release-chain`** :
   - Synchronisation stricte de `release_readiness.py` avec `rag-engine` (champs V2 Option A et marqueurs de statut).
3. **`services/rag-pedago`** :
   - `make lint` : 0 erreur.
   - `make typecheck` : 0 erreur.
   - `make test` : 2921 passés, 2 ignorés (tests nécessitant un réseau externe), 0 échec.
4. **`services/rag-engine`** :
   - `make lint` : 0 erreur (ruff check conforme).
   - `make typecheck` : 0 erreur (mypy conforme sur 125 fichiers source).
   - `make test` : 3552 passés, 15 ignorés, 0 échec.
   - `make test-integration-hybrid` : 100% PASS (sur conteneur jetable Docker pgvector).
5. **`services/cockpit`** :
   - `npm run lint` : conforme.
   - `npm test` : 21 fichiers passés, 179 tests passés, 0 échec.
   - `npm run build` : build de production Next.js / Turbopack réussi (pages statiques et dynamiques compilées).
   - Cohérence des snapshots : validation `validate_cockpit_snapshots.py` conforme (21 sources, 62 collections synchronisées).
6. **Gouvernance et Hygiène** :
   - `scripts/check-governance-locks.sh` : 18/18 verrous conformes à la baseline.
   - `scripts/check-repository-hygiene.sh` : PASS.
   - Scripts d'épreuves CI failsafe, topologie et main protection : 100% PASS.

---

## 4. Dettes Résiduelles et Actions Humaines Réservées (Hors Autonomie)

Conformément à la règle de non-franchissement des verrous de gouvernance (`AGENTS.md`) :

### Dette D1 — Approbation Formelle des ADR (Gouvernance)
- **Description** : L'ADR-0046 (politique PDF page-par-page) et l'ADR-0047 (modèle canonique de release V2 Option A) sont rédigés et techniquement implémentés.
- **Action requise** : Signature et revue humaine formelle avant fusion sur la branche principale.

### Dette D2 — Décisions Humaines sur les Dossiers PII
- **Description** : Le scan de détection PII identifie les candidats nécessitant un arbitrage humain (anonymisation, exclusion ou dérogation).
- **Action requise** : Validation par un tiers humain du dossier de revue PII via `packages/contracts` avant émission d'une release finale de production.

### Dette D3 — Verrou d'Activation de Production
- **Description** : La release candidate de répétition est scellée avec les statuts de sécurité obligatoires :
  - `release_mode: rehearsal`
  - `promotion_status: NOT_PROMOTABLE`
  - `activation_status: NO_PRODUCTION_ACTIVATION`
  - `review_status: PRE_REVIEW`
- **Action requise** : Aucun déploiement en production ni altération du catalogue de production actif sans ordre explicite de déploiement et nouvelle release candidate signée.
