# Rapport de LOT 28 — Mise au point globale : corpus tous niveaux, ingestion continue, cockpit v2

- **Branche proposée** : `lot-28-corpus-ingestion-cockpit`
- **Date** : 2026-07-26
- **ADR** : ADR-0015 (corpus), ADR-0016 (ingestion continue), ADR-0017 (cockpit v2)
- **Audit** : `docs/audits/AUDIT_LOT28_GLOBAL.md`
- **Verrous levés** : **aucun**. Garde-fou `check-governance-locks.sh` : inchangé.

## 1. Livrables

| # | Livrable | Chemins | Volume |
|---|---|---|---|
| 1 | Rapport d'audit global + registre d'écarts E-01→E-07 + plan de convergence A→D | `docs/audits/AUDIT_LOT28_GLOBAL.md` | 1 doc |
| 2 | Arborescence corpus 3e → Terminale (toutes matières du périmètre v1) + `_index.yml` de routage | `corpus/` | 55 fiches + 9 index |
| 3 | Taxonomies manquantes et nouvelles, validées `TaxonomySpec` | `services/rag-pedago/taxonomy/` | 39 fichiers |
| 4 | Catalogue de collections v3 (35 → 59, aucune nouvelle instanciée) | `services/rag-engine/configs/rag_collections.yml` | 1 fichier |
| 5 | Agents d'ingestion continue eduscol + politique + sources semences + planificateur systemd | `services/rag-pedago/agents/`, `configs/`, `scripts/` | 6 fichiers |
| 6 | Cockpit v2 (React/TS/Tailwind, 6 vues, mode dégradé explicite) | `services/cockpit/` | application complète |
| 7 | Runbook de déploiement rag-ui v2 (avec rollback) | `docs/runbooks/rag_ui_v2_deploiement.md` | 1 doc |

## 2. Preuves d'exécution

- **Taxonomies** : 58/60 valides contre `TaxonomySpec` sur l'union dépôt + lot. Les 2 échecs sont **préexistants** (`exams/anticipee_maths.yml`, `exams/bac_general.yml` — schéma distinct), antériorité prouvée contre le parent ; aucune régression introduite.
- **Réconciliation catalogue ↔ taxonomies** : 0 taxonomie référencée manquante après application du lot (16 avant).
- **Compilation** : `py_compile` OK sur `eduscol_agent.py` et `continuous_orchestrator.py`.
- **Smoke test ingestion** : `--plan` OK (20 sources : 8 verified / 12 to_verify) ; `--run` : chaîne de gouvernance validée de bout en bout — skips `to_verify` corrects, ledger JSONL écrit, rapport généré, aucun dépôt hors staging. Fetch réel : HTTP 403 depuis le sandbox (restriction d'égresse de l'environnement de test, les deux User-Agents testés) — à rejouer sur l'hôte de production (runbook §Étape 5).
- **Build cockpit** : `npm run build` vert (Vite, 426 Ko JS / 85 Ko CSS). Prévisualisation sauvegardée (version `12639c0`).

## 3. Dettes et points d'attention (déclarés, non résolus par ce lot)

| ID | Dette | Antériorité | Action proposée |
|---|---|---|---|
| D-28-01 | `exams/anticipee_maths.yml` et `exams/bac_general.yml` non conformes `TaxonomySpec` | Préexistant | Aligner le schéma ou déclarer un schéma d'examen dédié (lot suivant) |
| D-28-02 | `OrchestratorAgent.fetch` exige `ingestion_allowed == false`, or le verrou est `true` (ADR-0008) → orchestrateur historique inopérant | Préexistant (signalé ADR-0016) | Réaligner le garde-fou sur la sémantique actuelle (lot suivant) |
| D-28-03 | `RATE_LIMIT_SECONDS = 2.0` < crawl-delay eduscol (10 s) dans `scrapers/fetch.py` | Préexistant (l'agent lot 28 compense par `per_domain_delay`) | Durcir le module partagé : délai = max(config, robots crawl-delay) (lot suivant) |
| D-28-04 | 12 sources eduscol `to_verify` | Nouveau (volontaire) | Revue humaine des URLs puis bascule `verified` (ADR-0016 §6) |
| D-28-05 | Fiches historiques `corpus/Tronc_commun|Specialites/` dupliquées conceptuellement avec la nouvelle arborescence | Préexistant | `git mv` de consolidation (lot suivant, préserve l'historique) |
| D-28-06 | Cockpit livré en SPA Vite ; cible Next.js App Router | Nouveau (documenté ADR-0017) | Portage au lot Cockpit MVP (structure déjà compatible) |

## 4. Métriques de couverture (substance, pas présence)

- 55 fiches corpus : chacune déclare programme officiel (thèmes → notions issus des BO), épreuves, spécificité candidat libre, attendus et notes RAG — gabarit identique aux fiches historiques.
- 39 taxonomies : thèmes et notions extraits des programmes officiels (versions BO déclarées dans `programme_version`).
- 59 collections : toutes dotées d'une taxonomie résolvable ; 3 instanciées (inchangé) — la substance indexée reste à prouver **par vague** en Phase B avant tout `instanciee: true`.
- Ingestion continue : 8 sources vérifiées actives ; 12 candidates en attente de revue humaine (comportement voulu, pas un manque masqué).

## 5. Conformité AGENTS.md

- Aucun secret, aucune PII, aucun chemin absolu machine-local (script et unités systemd paramétrés par `RAG_ROOT`/`%h`).
- Aucun verrou modifié ; aucune écriture pgvector ; aucune génération de réponse.
- Documentation et contenu pédagogique en français.
