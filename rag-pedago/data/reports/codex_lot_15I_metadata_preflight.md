# Rapport Codex — Lot 15I : preflight global metadata-only

## 1. Objectif

Créer un orchestrateur de preflight global, strictement metadata-only, qui
agrège les garde-fous existants avant tout futur brouillon réel minimal.

## 2. Point de départ Git

- branche : `main` ;
- commit de départ : `17d31b6 feat: add real draft unlock gate` ;
- dépôt propre avant création du lot ;
- `make doctor`, `make project-doctor` et `make test` : OK, 359 tests passed.

## 3. Fichiers créés ou modifiés

Créés :

- `docs/METADATA_PREFLIGHT_PROTOCOL.md` ;
- `rag_pedago/imports/metadata_preflight.py` ;
- `tests/unit/test_metadata_preflight.py` ;
- `data/reports/codex_lot_15I_metadata_preflight.md`.

Modifié :

- `Makefile`.

## 4. Protocole de preflight global

Le protocole définit un verdict global sur la chaîne de gouvernance
metadata-only. Il n’autorise ni ingestion documentaire, ni validation du contenu
pédagogique, ni création de brouillon réel.

## 5. Module de preflight

Le module `rag_pedago.imports.metadata_preflight` expose :

- `run_template_check` ;
- `run_compile_check` ;
- `run_rehearsal_check` ;
- `run_real_draft_guard_check` ;
- `run_human_unlock_check` ;
- `run_unlock_gate_check` ;
- `build_metadata_preflight_report` ;
- `main`.

Il produit un rapport en mémoire avec `status`, `issue_count`, `checks` et les
statuts synthétiques de chaque sous-check.

## 6. Sous-checks orchestrés

- `pilot-template-check` via le validateur de template ;
- `pilot-compile-check` via le compilateur de brouillon synthétique ;
- `pilot-rehearsal` via un workspace temporaire ;
- `real-draft-guard-check` via la fixture synthétique 15F ;
- `human-unlock-check` via la fixture synthétique 15G ;
- `real-draft-unlock-gate-check` via les fixtures synthétiques 15H.

## 7. Règles contrôlées

- statut template attendu : `needs_completion` ;
- statut compilation attendu : `ready` ;
- statuts rehearsal attendus : compilation, dry-run, readiness, coverage, gate,
  review, décision, import contrôlé metadata-only et audit ledger temporaire ;
- statut real draft guard attendu : `ready_for_human_locked_metadata_validation` ;
- statut human unlock attendu : `approved_for_metadata_only_next_step` ;
- statut gate combiné attendu : `approved_for_real_metadata_draft_preparation` ;
- absence de `data/staging` ;
- absence de document réel dans les fixtures et templates ;
- ledger permanent inchangé.

## 8. Tests ajoutés ou modifiés

Ajout :

- `tests/unit/test_metadata_preflight.py`.

## 9. Tests exécutés

Commandes prévues :

```bash
pytest tests/unit/test_metadata_preflight.py -q
make metadata-preflight
make real-draft-unlock-gate-check
make human-unlock-check
make real-draft-guard-check
make pilot-rehearsal
make doctor
make project-doctor
make test
```

## 10. Résultats

Résultats observés :

- `pytest tests/unit/test_metadata_preflight.py -q` : 11 passed ;
- `make metadata-preflight` : `status=metadata_preflight_ready`, 0 issue ;
- `make real-draft-unlock-gate-check` : `status=approved_for_real_metadata_draft_preparation`, 2 items, 0 issue ;
- `make human-unlock-check` : `status=approved_for_metadata_only_next_step`, 0 issue ;
- `make real-draft-guard-check` : `status=ready_for_human_locked_metadata_validation`, 2 items, 0 issue ;
- `make pilot-rehearsal` : tous les statuts attendus, ledger temporaire sous `/tmp` ;
- scan de sûreté du module : aucune occurrence ;
- `make doctor` : OK ;
- `make project-doctor` : OK ;
- `make test` : 370 passed.

## 11. Limites volontaires

- aucun document réel ;
- aucun PDF ;
- aucun `data/staging` ;
- aucune lecture `source_uri` ;
- aucun hash calculé ;
- aucune écriture ledger ;
- aucun scraping ;
- aucun Qdrant ;
- aucun changement `schema/document.py` ;
- aucune modification taxonomie officielle ;
- aucun brouillon réel créé ;
- aucun manifest réel prêt pour import ;
- aucune validation du contenu pédagogique.

Le fichier
`data/fixtures/pilot_math_terminale/human_unlock/human_unlock.invalid_secret_marker.json`
reste un faux positif connu des scans de noms sensibles. Il appartient au lot
15G, est synthétique et ne contient aucun secret réel.

## 12. Risques restants

- le preflight ne valide toujours pas de métadonnées réelles ;
- une revue humaine reste nécessaire avant tout futur brouillon réel minimal ;
- le contenu pédagogique n’est pas évalué ;
- le futur lot devra préserver les mêmes interdictions metadata-only.

## 13. Verdict

COMMIT_RECOMMANDÉ

## 14. Recommandation pour le lot 15J

Ne pas démarrer 15J avant commit dédié du lot 15I et relecture humaine du
protocole de preflight global. Le lot suivant devra rester metadata-only tant
qu’aucun brouillon réel autorisé n’a été validé par le verrou humain et par le
gate combiné.
